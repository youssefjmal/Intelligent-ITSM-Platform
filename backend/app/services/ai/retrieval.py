"""Unified semantic retrieval helpers shared by AI chat and suggestion endpoints."""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.ticket import Ticket
from app.services.ai.feedback import aggregate_feedback_for_sources
from app.services.embeddings import compute_embedding, list_comments_for_jira_keys, search_kb, search_kb_issues

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "were",
    "you",
    "your",
    "our",
    "its",
    "have",
    "has",
    "had",
    "not",
    "but",
    "into",
    "about",
    "issue",
    "ticket",
    "problem",
    "help",
    "please",
    "les",
    "des",
    "pour",
    "avec",
    "dans",
    "une",
    "sur",
    "pas",
}
_CATEGORY_HINTS = {
    "infrastructure": {"infrastructure", "server", "vm", "storage", "cloud"},
    "network": {"network", "vpn", "dns", "router", "switch", "wifi"},
    "security": {"security", "auth", "token", "jwt", "access", "iam"},
    "application": {"application", "app", "service", "api", "backend", "frontend"},
    "service_request": {"service", "request", "onboarding", "permission"},
    "hardware": {"hardware", "laptop", "printer", "device", "ups", "battery"},
    "email": {"email", "mail", "smtp", "outlook", "mailbox"},
    "problem": {"problem", "recurring", "pattern", "rca"},
}
_QUALITY_THRESHOLDS = {"low": 0.35, "medium": 0.55, "high": 0.72}
_ACTION_HINTS = (
    "restart",
    "reset",
    "clear",
    "flush",
    "rotate",
    "patch",
    "update",
    "disable",
    "enable",
    "replace",
    "rollback",
    "validate",
)
_OUTCOME_HINTS = ("resolved", "fixed", "worked", "restored", "mitigated", "verified", "closed")


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _truncate(value: str, *, limit: int = 220) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "")}


def _meaningful_tokens(value: str | None) -> set[str]:
    return {token for token in _tokens(value or "") if token not in _STOPWORDS}


def _overlap_score(query_tokens: set[str], field_tokens: set[str]) -> float:
    if not query_tokens or not field_tokens:
        return 0.0
    return len(query_tokens.intersection(field_tokens)) / max(1, len(query_tokens))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    cosine = dot / (left_norm * right_norm)
    return max(-1.0, min(1.0, cosine))


def _to_unit_score(cosine: float) -> float:
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def _ticket_outcome_score(ticket: Ticket | None) -> float:
    if ticket is None or getattr(ticket, "status", None) is None:
        return 0.0
    status = str(ticket.status.value).lower()
    if status in {"resolved", "closed"}:
        return 0.12
    if status in {"open", "in_progress", "waiting_for_customer", "waiting_for_support_vendor", "pending"}:
        return -0.08
    return 0.0


def _comment_quality_score(content: str) -> float:
    text = _normalize_text(content).lower()
    if not text:
        return 0.0
    length = len(text)
    length_score = 0.0
    if length >= 80:
        length_score += 0.25
    if length >= 160:
        length_score += 0.2
    if length >= 260:
        length_score += 0.1

    action_hits = sum(1 for token in _ACTION_HINTS if token in text)
    outcome_hits = sum(1 for token in _OUTCOME_HINTS if token in text)
    structure_hits = 0
    if any(marker in text for marker in ("1.", "2.", "step", "then", "after", "finally", "\n")):
        structure_hits += 1
    if ":" in text:
        structure_hits += 1

    score = length_score
    score += min(0.25, action_hits * 0.08)
    score += min(0.25, outcome_hits * 0.1)
    score += min(0.15, structure_hits * 0.08)
    return max(0.0, min(1.0, score))


def _ticket_semantic_text(ticket: Ticket) -> str:
    title = _normalize_text(ticket.title)
    description = _normalize_text(ticket.description)
    resolution = _normalize_text(ticket.resolution)
    # Repeat title once to preserve summary intent in embedding.
    parts = [title, title, description]
    if resolution:
        parts.append(f"resolution {resolution}")
    return " ".join(part for part in parts if part)


@lru_cache(maxsize=4096)
def _embedding_for_text(text: str) -> tuple[float, ...]:
    normalized = _normalize_text(text)
    if not normalized:
        return tuple()
    vector = compute_embedding(normalized)
    return tuple(float(item) for item in vector)


def _local_ticket_similarity(query: str, query_tokens: set[str], ticket: Ticket) -> float:
    title_tokens = _meaningful_tokens(ticket.title)
    description_tokens = _meaningful_tokens(ticket.description)
    resolution_tokens = _meaningful_tokens(ticket.resolution)

    title_score = _overlap_score(query_tokens, title_tokens)
    description_score = _overlap_score(query_tokens, description_tokens)
    resolution_score = _overlap_score(query_tokens, resolution_tokens)

    # Prioritize summary/title and description content over metadata.
    score = (0.58 * title_score) + (0.34 * description_score) + (0.06 * resolution_score)

    normalized_query = _normalize_text(query).lower()
    normalized_title = _normalize_text(ticket.title).lower()
    normalized_description = _normalize_text(ticket.description).lower()
    if normalized_query and (normalized_query in normalized_title or normalized_query in normalized_description):
        score += 0.08

    ticket_id = str(ticket.id or "").strip().lower()
    if ticket_id and ticket_id in normalized_query:
        score += 0.15

    category = str(getattr(ticket, "category", None).value if getattr(ticket, "category", None) else "").strip().lower()
    if category:
        category_tokens = _CATEGORY_HINTS.get(category) or _meaningful_tokens(category.replace("_", " "))
        # Category is only a helper signal.
        if query_tokens.intersection(category_tokens):
            score += 0.03

    score += _ticket_outcome_score(ticket)
    return max(0.0, min(1.0, score))


def _local_ticket_matches(query: str, tickets: list[Ticket], *, limit: int = 8) -> list[dict[str, Any]]:
    q_tokens = _meaningful_tokens(query)
    if not q_tokens:
        return []

    scored: list[tuple[float, Ticket]] = []
    for ticket in tickets:
        score = _local_ticket_similarity(query, q_tokens, ticket)
        if score < 0.12:
            continue
        scored.append((score, ticket))

    scored.sort(
        key=lambda item: (
            item[0],
            bool(getattr(item[1], "resolution", None)),
            getattr(item[1], "updated_at", None).timestamp() if getattr(item[1], "updated_at", None) else 0.0,
        ),
        reverse=True,
    )
    return [
        {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status.value if getattr(ticket, "status", None) else "unknown",
            "resolution_snippet": _truncate(str(ticket.resolution or "")) or None,
            "similarity_score": round(float(score), 4),
            "problem_id": str(ticket.problem_id or "").strip() or None,
            "jira_key": str(ticket.jira_key or "").strip() or None,
            "source": "local_lexical",
        }
        for score, ticket in scored[:limit]
    ]


def _local_ticket_semantic_matches(
    query: str,
    tickets: list[Ticket],
    *,
    lexical_seed: list[dict[str, Any]],
    limit: int = 8,
    semantic_pool_size: int = 40,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_text(query)
    if not normalized_query or not tickets:
        return []

    ticket_by_id = {str(ticket.id): ticket for ticket in tickets}
    seeded_ids = [str(row.get("id") or "").strip() for row in lexical_seed if str(row.get("id") or "").strip()]

    pool: list[Ticket] = []
    seen: set[str] = set()
    for ticket_id in seeded_ids:
        ticket = ticket_by_id.get(ticket_id)
        if not ticket:
            continue
        key = str(ticket.id)
        if key in seen:
            continue
        seen.add(key)
        pool.append(ticket)
        if len(pool) >= semantic_pool_size:
            break

    if len(pool) < semantic_pool_size:
        for ticket in sorted(tickets, key=lambda item: item.updated_at, reverse=True):
            key = str(ticket.id)
            if key in seen:
                continue
            seen.add(key)
            pool.append(ticket)
            if len(pool) >= semantic_pool_size:
                break

    try:
        query_embedding = _embedding_for_text(normalized_query)
    except Exception:
        return []
    if not query_embedding:
        return []

    scored: list[tuple[float, Ticket]] = []
    for ticket in pool:
        try:
            ticket_embedding = _embedding_for_text(_ticket_semantic_text(ticket))
        except Exception:
            continue
        if not ticket_embedding:
            continue
        cosine = _cosine_similarity(list(query_embedding), list(ticket_embedding))
        score = _to_unit_score(cosine)
        score += _ticket_outcome_score(ticket)
        if score < 0.35:
            continue
        scored.append((score, ticket))

    scored.sort(
        key=lambda item: (
            item[0],
            bool(getattr(item[1], "resolution", None)),
            getattr(item[1], "updated_at", None).timestamp() if getattr(item[1], "updated_at", None) else 0.0,
        ),
        reverse=True,
    )

    return [
        {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status.value if getattr(ticket, "status", None) else "unknown",
            "resolution_snippet": _truncate(str(ticket.resolution or "")) or None,
            "similarity_score": round(float(score), 4),
            "problem_id": str(ticket.problem_id or "").strip() or None,
            "jira_key": str(ticket.jira_key or "").strip() or None,
            "source": "local_semantic",
        }
        for score, ticket in scored[:limit]
    ]


def _ticket_from_visible_pool(ticket: Ticket, *, score: float, source: str) -> dict[str, Any]:
    evidence = _truncate(str(ticket.resolution or "")) or None
    return {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status.value if getattr(ticket, "status", None) else "unknown",
        "resolution_snippet": evidence,
        "similarity_score": round(max(0.0, min(1.0, float(score))), 4),
        "problem_id": str(ticket.problem_id or "").strip() or None,
        "jira_key": str(ticket.jira_key or "").strip() or None,
        "outcome_score": round(_ticket_outcome_score(ticket), 4),
        "evidence_source": "ticket_resolution" if evidence else "ticket_metadata",
        "evidence_snippet": evidence,
        "recommendation_reason": "Matched similar incident with resolved outcome" if evidence else "Matched similar incident",
        "source": source,
    }


def _problem_text(problem: Problem) -> str:
    return " ".join(
        part
        for part in [
            _normalize_text(problem.title),
            _normalize_text(problem.root_cause),
            _normalize_text(problem.workaround),
            _normalize_text(problem.permanent_fix),
            _normalize_text(problem.similarity_key),
        ]
        if part
    )


def _fetch_tickets_for_issue_matches(
    db: Session,
    *,
    issue_matches: list[dict[str, Any]],
    ticket_by_jira: dict[str, Ticket],
    ticket_by_id: dict[str, Ticket],
) -> tuple[dict[str, Ticket], dict[str, Ticket]]:
    missing_jira_keys: set[str] = set()
    missing_ticket_ids: set[str] = set()
    for match in issue_matches:
        metadata = match.get("metadata") or {}
        jira_key = str(match.get("jira_key") or metadata.get("jira_key") or "").strip()
        ticket_id = str(metadata.get("ticket_id") or "").strip()
        if jira_key and jira_key not in ticket_by_jira:
            missing_jira_keys.add(jira_key)
        if ticket_id and ticket_id not in ticket_by_id:
            missing_ticket_ids.add(ticket_id)

    if missing_jira_keys:
        rows = db.execute(select(Ticket).where(Ticket.jira_key.in_(list(missing_jira_keys)))).scalars().all()
        for ticket in rows:
            key = str(ticket.jira_key or "").strip()
            if key:
                ticket_by_jira[key] = ticket
            ticket_by_id[str(ticket.id)] = ticket

    if missing_ticket_ids:
        rows = db.execute(select(Ticket).where(Ticket.id.in_(list(missing_ticket_ids)))).scalars().all()
        for ticket in rows:
            ticket_by_id[str(ticket.id)] = ticket
            key = str(ticket.jira_key or "").strip()
            if key:
                ticket_by_jira[key] = ticket

    return ticket_by_jira, ticket_by_id


def _search_related_problems(
    db: Session,
    *,
    query: str,
    seed_problem_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    q_tokens = _meaningful_tokens(query)
    candidates = db.execute(select(Problem).order_by(Problem.updated_at.desc()).limit(250)).scalars().all()
    if not candidates:
        return []

    seed_set = {str(pid).strip() for pid in (seed_problem_ids or []) if str(pid).strip()}
    scored: list[tuple[float, Problem, str]] = []

    query_embedding: tuple[float, ...] = tuple()
    try:
        query_embedding = _embedding_for_text(query)
    except Exception:
        query_embedding = tuple()

    for problem in candidates:
        p_text = _problem_text(problem)
        lexical = _overlap_score(q_tokens, _meaningful_tokens(p_text))
        semantic = 0.0
        if query_embedding:
            try:
                p_embedding = _embedding_for_text(p_text)
            except Exception:
                p_embedding = tuple()
            if p_embedding:
                semantic = _to_unit_score(_cosine_similarity(list(query_embedding), list(p_embedding)))
        score = max(lexical, semantic)
        if str(problem.id) in seed_set:
            score = max(score, 0.85)
        if score < 0.18:
            continue
        reason = "Direct semantic/lexical match from problem knowledge"
        if str(problem.id) in seed_set:
            reason = f"Matches related ticket pattern ({problem.category.value})"
        scored.append((score, problem, reason))

    scored.sort(
        key=lambda item: (
            item[0],
            int(item[1].active_count or 0),
            int(item[1].occurrences_count or 0),
            item[1].updated_at.timestamp() if getattr(item[1], "updated_at", None) else 0.0,
        ),
        reverse=True,
    )

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, problem, reason in scored:
        if problem.id in seen:
            continue
        seen.add(problem.id)
        output.append(
            {
                "id": problem.id,
                "title": problem.title,
                "match_reason": reason,
                "root_cause": _truncate(str(problem.root_cause or "")) or None,
                "affected_tickets": int(problem.occurrences_count or 0),
                "similarity_score": round(score, 4),
            }
        )
        if len(output) >= max(1, top_k):
            break
    return output


def _dedupe_by_id(rows: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(row)
    return out


def unified_retrieve(
    db: Session,
    *,
    query: str,
    visible_tickets: list[Ticket],
    top_k: int = 5,
    solution_quality: str = "medium",
) -> dict[str, Any]:
    """Single retrieval path used by chat and suggestion APIs."""
    normalized = _normalize_text(query)
    if not normalized:
        return {
            "kb_articles": [],
            "similar_tickets": [],
            "related_problems": [],
            "suggested_solutions": [],
            "confidence": 0.0,
            "source": "llm_fallback",
            "comment_matches": [],
            "solution_recommendations": [],
        }

    issue_matches: list[dict[str, Any]] = []
    kb_matches: list[dict[str, Any]] = []
    comment_matches: list[dict[str, Any]] = []
    try:
        issue_matches = search_kb_issues(db, normalized, top_k=top_k)
        kb_matches = search_kb(db, normalized, top_k=top_k)
        comment_matches = search_kb(db, normalized, top_k=top_k, source_type="jira_comment")
    except Exception:
        issue_matches = []
        kb_matches = []
        comment_matches = []

    retrieval_tickets = list(visible_tickets or [])
    if not retrieval_tickets:
        retrieval_tickets = db.execute(select(Ticket).order_by(Ticket.updated_at.desc()).limit(300)).scalars().all()

    jira_keys: list[str] = []
    for match in [*issue_matches, *comment_matches]:
        jira_key = str(match.get("jira_key") or "").strip()
        if jira_key:
            jira_keys.append(jira_key)

    ticket_by_jira: dict[str, Ticket] = {}
    ticket_by_id: dict[str, Ticket] = {}
    for ticket in retrieval_tickets:
        ticket_by_id[str(ticket.id)] = ticket
        key = str(ticket.jira_key or "").strip()
        if key:
            ticket_by_jira[key] = ticket
    ticket_by_jira, ticket_by_id = _fetch_tickets_for_issue_matches(
        db,
        issue_matches=issue_matches,
        ticket_by_jira=ticket_by_jira,
        ticket_by_id=ticket_by_id,
    )

    semantic_tickets: list[dict[str, Any]] = []
    for match in issue_matches:
        metadata = match.get("metadata") or {}
        jira_key = str(match.get("jira_key") or metadata.get("jira_key") or "").strip()
        ticket_id = str(metadata.get("ticket_id") or "").strip()
        ticket = ticket_by_jira.get(jira_key) or ticket_by_id.get(ticket_id)
        if not ticket:
            continue
        semantic_tickets.append(
            _ticket_from_visible_pool(
                ticket,
                score=float(match.get("score") or 0.0) + _ticket_outcome_score(ticket),
                source="semantic_issue",
            )
        )

    lexical_tickets = _local_ticket_matches(normalized, retrieval_tickets, limit=max(10, top_k * 3))
    semantic_local_tickets = _local_ticket_semantic_matches(
        normalized,
        retrieval_tickets,
        lexical_seed=lexical_tickets,
        limit=max(5, top_k * 2),
    )
    similar_tickets = _dedupe_by_id([*semantic_tickets, *semantic_local_tickets, *lexical_tickets], key="id")[:top_k]

    problem_ids = [str(row.get("problem_id") or "").strip() for row in similar_tickets if row.get("problem_id")]
    related_problems = _search_related_problems(
        db,
        query=normalized,
        seed_problem_ids=problem_ids,
        top_k=top_k,
    )

    kb_articles: list[dict[str, Any]] = []
    for idx, match in enumerate(kb_matches[:top_k], start=1):
        metadata = match.get("metadata") or {}
        title = (
            str(metadata.get("summary") or "").strip()
            or str(metadata.get("title") or "").strip()
            or str(match.get("jira_key") or "").strip()
            or f"KB Match {idx}"
        )
        kb_articles.append(
            {
                "id": str(match.get("jira_key") or metadata.get("jira_key") or f"kb-{idx}"),
                "title": title,
                "excerpt": _truncate(str(match.get("content") or "")),
                "similarity_score": round(max(0.0, min(1.0, float(match.get("score") or 0.0))), 4),
                "source_type": str(match.get("source_type") or "kb"),
            }
        )

    comment_rows = list_comments_for_jira_keys(db, jira_keys, limit_per_issue=2) if jira_keys else []
    comment_rows = _dedupe_by_id(
        [
            {
                "id": str(item.get("comment_id") or item.get("jira_key") or ""),
                "jira_key": str(item.get("jira_key") or ""),
                "content": _truncate(str(item.get("content") or "")),
            }
            for item in comment_rows
        ],
        key="id",
    )[:top_k]

    normalized_quality = str(solution_quality or "medium").strip().lower()
    quality_threshold = _QUALITY_THRESHOLDS.get(normalized_quality, _QUALITY_THRESHOLDS["medium"])
    comment_source_ids = [
        str(match.get("jira_key") or "").strip()
        for match in comment_matches
        if str(match.get("jira_key") or "").strip()
    ]
    try:
        feedback_by_source_id = aggregate_feedback_for_sources(
            db,
            source="jira_comment",
            source_ids=comment_source_ids,
        )
    except Exception:
        feedback_by_source_id = {}

    solution_recommendations: list[dict[str, Any]] = []
    for match in comment_matches:
        jira_key = str(match.get("jira_key") or "").strip()
        content = str(match.get("content") or "").strip()
        if not jira_key or not content:
            continue
        quality_score = _comment_quality_score(content)
        if quality_score < quality_threshold:
            continue
        semantic_score = float(match.get("score") or 0.0)
        linked_ticket = ticket_by_jira.get(jira_key)
        outcome_bonus = _ticket_outcome_score(linked_ticket)
        feedback_counts = feedback_by_source_id.get(jira_key, {"helpful": 0, "not_helpful": 0})
        helpful_votes = int(feedback_counts.get("helpful", 0))
        not_helpful_votes = int(feedback_counts.get("not_helpful", 0))
        vote_total = helpful_votes + not_helpful_votes
        feedback_signal = ((helpful_votes - not_helpful_votes) / vote_total) if vote_total > 0 else 0.0
        feedback_bonus = max(-0.12, min(0.12, feedback_signal * 0.12))
        confidence_score = max(
            0.0,
            min(1.0, (0.5 * semantic_score) + (0.4 * quality_score) + outcome_bonus + feedback_bonus),
        )
        reason = f"High-quality Jira resolution comment (quality={quality_score:.2f})"
        if linked_ticket is not None:
            reason += f"; linked ticket={linked_ticket.id} status={linked_ticket.status.value}"
        if vote_total > 0:
            reason += f"; human_feedback={helpful_votes} helpful/{not_helpful_votes} not_helpful"
        solution_recommendations.append(
            {
                "text": _truncate(content, limit=320),
                "source": "jira_comment",
                "source_id": jira_key,
                "evidence_snippet": _truncate(content, limit=220),
                "quality_score": round(quality_score, 4),
                "confidence": round(confidence_score, 4),
                "helpful_votes": helpful_votes,
                "not_helpful_votes": not_helpful_votes,
                "reason": reason,
            }
        )

    solution_recommendations.sort(
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            float(item.get("quality_score") or 0.0),
        ),
        reverse=True,
    )
    solution_recommendations = solution_recommendations[:top_k]

    suggested_solutions: list[str] = []
    for row in solution_recommendations:
        snippet = str(row.get("text") or "").strip()
        if snippet:
            suggested_solutions.append(snippet)
    for row in similar_tickets:
        snippet = str(row.get("resolution_snippet") or "").strip()
        if snippet:
            suggested_solutions.append(snippet)
    for row in kb_articles:
        snippet = str(row.get("excerpt") or "").strip()
        if snippet:
            suggested_solutions.append(snippet)
    suggested_solutions = list(dict.fromkeys(suggested_solutions))[:top_k]

    scores = [float(match.get("score") or 0.0) for match in [*issue_matches[:2], *kb_matches[:2], *comment_matches[:2]]]
    if similar_tickets:
        scores.extend(float(row.get("similarity_score") or 0.0) for row in similar_tickets[:2])
    if semantic_local_tickets:
        scores.extend(float(row.get("similarity_score") or 0.0) for row in semantic_local_tickets[:2])
    confidence = max(scores) if scores else 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    has_embedding_data = bool(issue_matches or kb_matches or comment_matches)
    has_lexical_data = bool(lexical_tickets)
    if has_embedding_data and has_lexical_data:
        source = "hybrid"
    elif has_embedding_data:
        source = "embedding"
    elif has_lexical_data:
        source = "hybrid"
    else:
        source = "llm_fallback"

    logger.info(
        "Retrieval: %s | confidence: %.4f | tickets: %d | kb: %d | problems: %d",
        source,
        round(confidence, 4),
        len(similar_tickets[:3]),
        len(kb_articles[:top_k]),
        len(related_problems[:3]),
    )

    return {
        "kb_articles": kb_articles,
        "similar_tickets": similar_tickets[:3],
        "related_problems": related_problems[:3],
        "suggested_solutions": suggested_solutions[:3],
        "comment_matches": comment_rows,
        "solution_recommendations": solution_recommendations[:3],
        "confidence": round(confidence, 4),
        "source": source,
    }
