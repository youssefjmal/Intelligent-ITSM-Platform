"""Unified semantic retrieval helpers shared by AI chat and suggestion endpoints."""

from __future__ import annotations

import logging
import math
import re
import time
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.ticket import Ticket
from app.schemas.ai import RetrievalResult
from app.services.ai.calibration import (
    RETRIEVAL_DEFAULT_EVIDENCE_WEIGHT,
    RETRIEVAL_CLUSTER_THRESHOLDS,
    RETRIEVAL_CLUSTER_WEIGHT_BY_EVIDENCE_TYPE as _CLUSTER_WEIGHT_BY_EVIDENCE_TYPE,
    RETRIEVAL_CONSENSUS_WEIGHTS,
    RETRIEVAL_COHERENCE_BONUSES,
    RETRIEVAL_COHERENCE_PENALTIES,
    RETRIEVAL_COHERENCE_TERM_CAPS,
    RETRIEVAL_COHERENCE_WEIGHTS,
    RETRIEVAL_COMMENT_QUALITY,
    RETRIEVAL_CONTEXT_BONUSES,
    RETRIEVAL_CONTEXT_GATE_THRESHOLDS,
    RETRIEVAL_CONTEXT_PENALTIES,
    RETRIEVAL_CONTEXT_WEIGHTS,
    RETRIEVAL_FEEDBACK_BONUS,
    RETRIEVAL_ISSUE_MATCH_BLEND,
    RETRIEVAL_KB_ARTICLE_BLEND,
    RETRIEVAL_LOCAL_LEXICAL,
    RETRIEVAL_LOCAL_SEMANTIC,
    RETRIEVAL_PROBLEM_SEARCH,
    RETRIEVAL_QUALITY_THRESHOLDS as _QUALITY_THRESHOLDS,
    RETRIEVAL_SOLUTION_SCORE_WEIGHTS,
    RETRIEVAL_TICKET_STATUS_SCORES,
)
from app.services.ai.feedback import aggregate_feedback_for_sources
from app.services.ai.taxonomy import (
    ACTION_HINTS as _ACTION_HINTS,
    CATEGORY_HINTS as _CATEGORY_HINTS,
    HIGH_SIGNAL_VOCAB as _HIGH_SIGNAL_VOCAB,
    LOW_SIGNAL_TOKENS as _LOW_SIGNAL_TOKENS,
    OUTCOME_HINTS as _OUTCOME_HINTS,
    SHALLOW_MATCH_TOKENS as _SHALLOW_MATCH_TOKENS,
    TOPIC_HINTS as _TOPIC_HINTS,
    TOPIC_VOCAB as _TOPIC_VOCAB,
)
from app.services.embeddings import compute_embedding, kb_has_data, list_comments_for_jira_keys, search_kb, search_kb_issues

logger = logging.getLogger(__name__)


def _safe_rollback(db: Session | None) -> None:
    if db is None:
        return
    rollback = getattr(db, "rollback", None)
    if not callable(rollback):
        return
    try:
        rollback()
    except Exception:  # noqa: BLE001
        logger.debug("Retrieval rollback cleanup failed.", exc_info=True)

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
    "priority",
    "status",
    "category",
    "ticket_type",
    "generated",
    "contains",
    "contain",
    "next",
    "step",
    "need",
    "needs",
    "using",
    "users",
    "user",
    "cannot",
    "unable",
}
_FOCUS_TOKEN_BLOCKLIST = {
    "error",
    "errors",
    "issue",
    "issues",
    "problem",
    "problems",
    "request",
    "requests",
    "ticket",
    "tickets",
    "broken",
    "value",
    "values",
    "failed",
    "failure",
    "update",
    "updated",
    "system",
    "error",
    "errors",
    "stuck",
    "stalled",
    "queue",
    "latest",
    "writes",
}
_CONTRAST_PREFIX_CUES = (
    "wrong",
    "incorrect",
    "irrelevant",
    "unrelated",
    "mismatched",
    "mistaken",
    "unexpected",
    "spurious",
    "false",
    "bad",
)
_CONTRAST_SUFFIX_CUES = (
    "false positive",
    "false positives",
    "instead of",
    "rather than",
    "not relevant",
    "not the issue",
    "cross-domain",
    "mismatch",
    "bleed",
    "drift",
)
_CONTRAST_PREFIX_WINDOW = 24
_CONTRAST_SUFFIX_WINDOW = 40
_QUERY_TARGET_PATTERNS = (
    re.compile(
        r"\bwhen\s+(?:agents|users|teams|analysts)?\s*(?:query|search|look(?:ing)?\s+for|troubleshoot(?:ing)?)\s+(?:about|for)\s+(?P<span>[^.;:\n]{4,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfor\s+(?P<span>[^.;:\n]{4,80})\s+queries\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhile\s+(?:agents|users|teams|analysts)?\s*(?:troubleshoot(?:ing)?|investigat(?:e|ing)|search(?:ing)?\s+for)\s+(?P<span>[^.;:\n]{4,120})",
        re.IGNORECASE,
    ),
)
_FALSE_POSITIVE_SPAN_PATTERNS = (
    re.compile(
        r"\b(?:return(?:ing)?|surface(?:s|d|ing)?|show(?:s|ing)?|rank(?:s|ed|ing)?|pull(?:s|ed|ing)?|match(?:es|ed|ing)?)\s+(?P<span>[^.;:\n]{4,120}?)\s+as\s+(?:the\s+)?top\s+results?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:return(?:ing)?|surface(?:s|d|ing)?|show(?:s|ing)?|pull(?:s|ed|ing)?|match(?:es|ed|ing)?)\s+(?P<span>[^.;:\n]{4,120}?)\s+as\s+false\s+positives?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:surface(?:s|d|ing)?|return(?:ing)?|pull(?:s|ed|ing)?)\s+(?P<span>[^.;:\n]{4,120}?)\s+while\s+(?:agents|users|teams|analysts)?\s*(?:troubleshoot(?:ing)?|query(?:ing)?|search(?:ing)?)\b",
        re.IGNORECASE,
    ),
)
_RETRIEVAL_ANALYSIS_TOKENS = frozenset(
    {
        "retrieval",
        "embedding",
        "pipeline",
        "rag",
        "query",
        "queries",
        "search",
        "semantic",
        "similarity",
        "context",
        "gate",
        "model",
    }
)
_RETRIEVAL_ANALYSIS_SYMPTOM_TOKENS = frozenset(
    {
        "false",
        "positives",
        "cross-domain",
        "unrelated",
        "mismatch",
        "conflating",
        "bleed",
        "drift",
        "threshold",
    }
)


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _normalize_ticket_id(value: Any) -> str:
    return _normalize_text(str(value or "")).upper()


def _normalize_jira_key(value: Any) -> str:
    return _normalize_text(str(value or "")).upper()


def _truncate(value: str, *, limit: int = 220) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "")}


def _meaningful_tokens(value: str | None) -> set[str]:
    return {token for token in _tokens(value or "") if token not in _STOPWORDS}


def _ordered_meaningful_tokens(value: str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _tokens(value or ""):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _domain_signals(tokens: set[str]) -> set[str]:
    domains: set[str] = set()
    for category, hints in _CATEGORY_HINTS.items():
        if tokens.intersection(hints):
            domains.add(category)
    return domains


def _topic_signals(tokens: set[str]) -> set[str]:
    topics: set[str] = set()
    for topic, hints in _TOPIC_HINTS.items():
        if tokens.intersection(hints):
            topics.add(topic)
    return topics


def _strong_signal_terms(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token in _HIGH_SIGNAL_VOCAB and token not in _LOW_SIGNAL_TOKENS}


def _phrase_occurrences(text: str, phrase: str) -> list[int]:
    escaped = re.escape(phrase).replace("\\ ", r"\s+")
    pattern = re.compile(
        rf"(?<![a-z0-9]){escaped}(?![a-z0-9])",
        re.IGNORECASE,
    )
    starts: list[int] = []
    for match in pattern.finditer(text):
        starts.append(match.start())
    return starts


def _local_contrast_match(text: str, index: int, phrase: str) -> bool:
    left = f" {text[max(0, index - _CONTRAST_PREFIX_WINDOW) : index]} "
    right = f" {text[index + len(phrase) : index + len(phrase) + _CONTRAST_SUFFIX_WINDOW]} "
    if any(marker in left for marker in _CONTRAST_PREFIX_CUES):
        return True
    if any(marker in right for marker in _CONTRAST_SUFFIX_CUES):
        return True
    return False


def _signal_sets_from_span(span: str) -> tuple[set[str], set[str], set[str]]:
    tokens = _meaningful_tokens(span)
    return _domain_signals(tokens), _topic_signals(tokens), tokens


def _apply_positive_signal_span(
    span: str,
    *,
    positive_domains: set[str],
    negative_domains: set[str],
    positive_topics: set[str],
    negative_topics: set[str],
    positive_terms: set[str],
    negative_terms: set[str],
) -> None:
    domains, topics, terms = _signal_sets_from_span(span)
    if not (domains or topics or terms):
        return
    positive_domains.update(domains)
    positive_topics.update(topics)
    positive_terms.update(terms)
    negative_domains.difference_update(domains)
    negative_topics.difference_update(topics)
    negative_terms.difference_update(terms)


def _apply_negative_signal_span(
    span: str,
    *,
    positive_domains: set[str],
    negative_domains: set[str],
    positive_topics: set[str],
    negative_topics: set[str],
    positive_terms: set[str],
    negative_terms: set[str],
) -> None:
    domains, topics, terms = _signal_sets_from_span(span)
    if not (domains or topics or terms):
        return
    negative_domains.update(domains)
    negative_topics.update(topics)
    negative_terms.update(terms)
    positive_domains.difference_update(domains)
    positive_topics.difference_update(topics)
    positive_terms.difference_update(terms)


def _meta_positive_target_spans(text: str) -> list[str]:
    spans: list[str] = []
    for pattern in _QUERY_TARGET_PATTERNS:
        for match in pattern.finditer(text):
            span = _normalize_text(match.group("span"))
            if span:
                spans.append(span)
    return spans


def _meta_negative_target_spans(text: str) -> list[str]:
    spans: list[str] = []
    for pattern in _FALSE_POSITIVE_SPAN_PATTERNS:
        for match in pattern.finditer(text):
            span = _normalize_text(match.group("span"))
            if span:
                spans.append(span)
    return spans


def _is_retrieval_analysis_text(text: str) -> bool:
    tokens = _meaningful_tokens(text)
    return (
        len(tokens.intersection(_RETRIEVAL_ANALYSIS_TOKENS)) >= 2
        and bool(tokens.intersection(_RETRIEVAL_ANALYSIS_SYMPTOM_TOKENS))
    )


def _contextual_signal_sets(
    text: str,
) -> dict[str, set[str]]:
    lowered = f" {_normalize_text(text).lower()} "
    positive_domains: set[str] = set()
    negative_domains: set[str] = set()
    positive_topics: set[str] = set()
    negative_topics: set[str] = set()
    positive_terms: set[str] = set()
    negative_terms: set[str] = set()

    for category, hints in _CATEGORY_HINTS.items():
        for hint in hints:
            phrase = _normalize_text(hint).lower()
            if not phrase:
                continue
            for index in _phrase_occurrences(lowered, phrase):
                hint_terms = _meaningful_tokens(phrase)
                if _local_contrast_match(lowered, index, phrase):
                    negative_domains.add(category)
                    negative_terms.update(hint_terms)
                else:
                    positive_domains.add(category)
                    positive_terms.update(hint_terms)

    for topic, hints in _TOPIC_HINTS.items():
        for hint in hints:
            phrase = _normalize_text(hint).lower()
            if not phrase:
                continue
            for index in _phrase_occurrences(lowered, phrase):
                hint_terms = _meaningful_tokens(phrase)
                if _local_contrast_match(lowered, index, phrase):
                    negative_topics.add(topic)
                    negative_terms.update(hint_terms)
                else:
                    positive_topics.add(topic)
                    positive_terms.update(hint_terms)

    for span in _meta_negative_target_spans(lowered):
        _apply_negative_signal_span(
            span,
            positive_domains=positive_domains,
            negative_domains=negative_domains,
            positive_topics=positive_topics,
            negative_topics=negative_topics,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
        )

    for span in _meta_positive_target_spans(lowered):
        _apply_positive_signal_span(
            span,
            positive_domains=positive_domains,
            negative_domains=negative_domains,
            positive_topics=positive_topics,
            negative_topics=negative_topics,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
        )

    if _is_retrieval_analysis_text(lowered):
        positive_domains.add("application")
        positive_topics.add("ai_ml_pipeline")
        positive_terms.update(_meaningful_tokens("retrieval embedding pipeline semantic search query context gate"))
        negative_domains.discard("application")
        negative_topics.discard("ai_ml_pipeline")

    return {
        "positive_domains": positive_domains,
        "negative_domains": negative_domains,
        "positive_topics": positive_topics,
        "negative_topics": negative_topics,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
    }


def _query_context(query: str) -> dict[str, Any]:
    normalized = _normalize_text(query)
    lines = [_normalize_text(line) for line in str(query or "").splitlines() if _normalize_text(line)]
    metadata: dict[str, str] = {}
    content_lines: list[str] = []
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            cleaned_key = _normalize_text(key).lower()
            cleaned_value = _normalize_text(value).lower()
            if cleaned_key in {"priority", "status", "category", "ticket_type"} and cleaned_value:
                metadata[cleaned_key] = cleaned_value
                continue
        content_lines.append(line)
    content_text = " ".join(content_lines) or normalized
    title = content_lines[0] if content_lines else normalized
    description = " ".join(content_lines[1:]) if len(content_lines) > 1 else ""
    contrast_signals = _contextual_signal_sets(content_text)
    negative_terms = set(contrast_signals["negative_terms"])
    positive_terms = set(contrast_signals["positive_terms"])
    ordered_tokens = [
        token for token in _ordered_meaningful_tokens(content_text)
        if token not in negative_terms or token in positive_terms
    ]
    ordered_title_tokens = [
        token for token in _ordered_meaningful_tokens(title)
        if token not in negative_terms or token in positive_terms
    ]
    focus_terms: list[str] = []
    seen_focus: set[str] = set()
    for token in [*ordered_title_tokens, *ordered_tokens]:
        if token in _FOCUS_TOKEN_BLOCKLIST:
            continue
        if len(token) < 4 and token not in {"csv", "dns", "vpn", "sso"}:
            continue
        if token in seen_focus:
            continue
        seen_focus.add(token)
        focus_terms.append(token)
    ordered_strong_terms = [token for token in [*ordered_title_tokens, *ordered_tokens] if token in _HIGH_SIGNAL_VOCAB]
    strong_terms: list[str] = []
    seen_strong: set[str] = set()
    for token in ordered_strong_terms:
        if token in seen_strong:
            continue
        seen_strong.add(token)
        strong_terms.append(token)
    context_tokens = set(ordered_tokens).union(_meaningful_tokens(metadata.get("category"))).union(
        _meaningful_tokens(metadata.get("ticket_type"))
    )
    domains = contrast_signals["positive_domains"] or _domain_signals(context_tokens)
    topics = contrast_signals["positive_topics"] or _topic_signals(context_tokens)
    return {
        "query": normalized,
        "title": title,
        "description": description,
        "tokens": ordered_tokens,
        "title_tokens": ordered_title_tokens,
        "focus_terms": focus_terms[:10],
        "strong_terms": strong_terms[:10],
        "domains": sorted(domains),
        "topics": sorted(topics),
        "negative_domains": sorted(contrast_signals["negative_domains"]),
        "negative_topics": sorted(contrast_signals["negative_topics"]),
        "negative_terms": sorted(negative_terms),
        "metadata": metadata,
    }


def _ordered_query_terms(query_context: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    for key in ("strong_terms", "focus_terms", "title_tokens", "tokens"):
        for raw in list(query_context.get(key) or []):
            token = str(raw).strip().lower()
            if not token or token in ordered or token in _STOPWORDS:
                continue
            ordered.append(token)
    return ordered


def _collect_excluded_ticket_context(
    db: Session | None,
    *,
    visible_tickets: list[Ticket],
    exclude_ids: set[str],
) -> tuple[set[str], set[str]]:
    excluded_jira_keys: set[str] = set()
    missing_ids: set[str] = set(exclude_ids)

    for ticket in visible_tickets:
        ticket_id = _normalize_ticket_id(getattr(ticket, "id", None))
        if ticket_id not in exclude_ids:
            continue
        missing_ids.discard(ticket_id)
        jira_key = _normalize_jira_key(getattr(ticket, "jira_key", None))
        if jira_key:
            excluded_jira_keys.add(jira_key)

    if db is None or not missing_ids:
        return exclude_ids, excluded_jira_keys

    try:
        rows = db.execute(select(Ticket).where(Ticket.id.in_(list(missing_ids)))).scalars().all()
    except Exception:
        _safe_rollback(db)
        rows = []
    for ticket in rows:
        jira_key = _normalize_jira_key(getattr(ticket, "jira_key", None))
        if jira_key:
            excluded_jira_keys.add(jira_key)
    return exclude_ids, excluded_jira_keys


def _filter_ticket_pool(tickets: list[Ticket], *, exclude_ids: set[str]) -> list[Ticket]:
    if not exclude_ids:
        return list(tickets)
    return [ticket for ticket in tickets if _normalize_ticket_id(getattr(ticket, "id", None)) not in exclude_ids]


def _row_is_excluded(
    row: dict[str, Any],
    *,
    exclude_ids: set[str],
    excluded_jira_keys: set[str],
) -> bool:
    row_id = _normalize_ticket_id(row.get("id") or row.get("ticket_id"))
    if row_id and row_id in exclude_ids:
        return True
    jira_key = _normalize_jira_key(row.get("jira_key") or row.get("source_id"))
    return bool(jira_key and jira_key in excluded_jira_keys)


def extract_evidence_features(
    query_context: dict[str, Any],
    *,
    title: str | None = None,
    text: str | None = None,
    category_hint: str | None = None,
    action_text: str | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    candidate_title = _normalize_text(title)
    candidate_text = _normalize_text(text)
    candidate_action = _normalize_text(action_text)
    candidate_reference = _normalize_text(reference)
    category_tokens = _meaningful_tokens(str(category_hint or "").replace("_", " "))
    candidate_tokens = _meaningful_tokens(
        " ".join(
            part
            for part in [candidate_title, candidate_text, candidate_action, candidate_reference]
            if part
        )
    ).union(category_tokens)
    strong_terms = _strong_signal_terms(candidate_tokens)
    ordered_query_terms = _ordered_query_terms(query_context)
    shared_terms = [token for token in ordered_query_terms if token in candidate_tokens]
    shared_signal_terms = [
        token
        for token in ordered_query_terms
        if token in strong_terms and token not in _SHALLOW_MATCH_TOKENS
    ]
    shared_topic_terms = [token for token in shared_signal_terms if token in _TOPIC_VOCAB]
    generic_overlap_terms = [token for token in shared_terms if token in _SHALLOW_MATCH_TOKENS]
    action_terms = [
        token
        for token in _ordered_meaningful_tokens(candidate_action or candidate_text)
        if token in strong_terms and token not in _ACTION_HINTS and token not in _SHALLOW_MATCH_TOKENS
    ][:3]
    component_terms = [
        token for token in shared_signal_terms if token not in _ACTION_HINTS
    ][:3]
    domains = sorted(_domain_signals(candidate_tokens))
    topics = sorted(_topic_signals(candidate_tokens))
    query_topics = [str(token).strip().lower() for token in list(query_context.get("topics") or []) if str(token).strip()]
    query_domains = [str(token).strip().lower() for token in list(query_context.get("domains") or []) if str(token).strip()]
    # Prefer domain-specific topics over cross-cutting generic ones (e.g. auth_path)
    # when choosing the dominant topic label for a candidate.
    _GENERIC_TOPIC_FAMILIES = frozenset({"auth_path"})
    _query_specific = [t for t in query_topics if t not in _GENERIC_TOPIC_FAMILIES]
    dominant_topic = (
        next((topic for topic in _query_specific if topic in topics), None)
        or next((topic for topic in query_topics if topic in topics), topics[0] if topics else None)
    )
    dominant_domain = next((domain for domain in query_domains if domain in domains), domains[0] if domains else None)
    signature_terms = component_terms or shared_topic_terms or action_terms or [
        token for token in shared_terms if token not in _SHALLOW_MATCH_TOKENS
    ][:2]
    generic_only_overlap = bool(shared_terms) and not shared_signal_terms and len(generic_overlap_terms) >= max(1, len(shared_terms) - 1)
    return {
        "tokens": sorted(candidate_tokens),
        "strong_terms": sorted(strong_terms),
        "domains": domains,
        "topics": topics,
        "shared_terms": shared_terms[:6],
        "shared_signal_terms": shared_signal_terms[:4],
        "shared_topic_terms": shared_topic_terms[:4],
        "generic_overlap_terms": generic_overlap_terms[:4],
        "component_terms": component_terms[:3],
        "action_terms": action_terms[:3],
        "signature_terms": signature_terms[:3],
        "dominant_topic": dominant_topic,
        "dominant_domain": dominant_domain,
        "generic_only_overlap": generic_only_overlap,
    }


def candidate_topic_signature(features: dict[str, Any]) -> str:
    dominant_topic = str(features.get("dominant_topic") or "").strip().lower()
    if dominant_topic:
        return dominant_topic
    dominant_domain = str(features.get("dominant_domain") or "").strip().lower()
    component_terms = [str(token).strip().lower() for token in list(features.get("component_terms") or []) if str(token).strip()]
    if dominant_domain and component_terms:
        return f"{dominant_domain}:{'|'.join(component_terms[:2])}"
    if dominant_domain:
        return f"domain:{dominant_domain}"
    signature_terms = [str(token).strip().lower() for token in list(features.get("signature_terms") or []) if str(token).strip()]
    if signature_terms:
        return f"terms:{'|'.join(signature_terms[:2])}"
    return "generic"


def score_candidate_coherence(
    query_context: dict[str, Any],
    *,
    features: dict[str, Any],
    metrics: dict[str, Any],
    base_score: float,
    evidence_type: str,
) -> float:
    context_score = float(metrics.get("context_score") or 0.0)
    title_overlap = float(metrics.get("title_overlap") or 0.0)
    lexical_overlap = float(metrics.get("lexical_overlap") or 0.0)
    strong_overlap = float(metrics.get("strong_overlap") or 0.0)
    topic_overlap = float(metrics.get("topic_overlap") or 0.0)
    exact_focus_hits = int(metrics.get("exact_focus_hits") or 0)
    exact_strong_hits = int(metrics.get("exact_strong_hits") or 0)
    domain_mismatch = bool(metrics.get("domain_mismatch"))
    topic_mismatch = bool(metrics.get("topic_mismatch"))
    shared_signal_terms = list(features.get("shared_signal_terms") or [])
    component_terms = list(features.get("component_terms") or [])
    action_terms = list(features.get("action_terms") or [])
    generic_overlap_terms = list(features.get("generic_overlap_terms") or [])
    dominant_topic = str(features.get("dominant_topic") or "").strip().lower()
    dominant_domain = str(features.get("dominant_domain") or "").strip().lower()
    query_topics = {str(token).strip().lower() for token in list(query_context.get("topics") or []) if str(token).strip()}
    query_domains = {str(token).strip().lower() for token in list(query_context.get("domains") or []) if str(token).strip()}

    coherence = (
        (RETRIEVAL_COHERENCE_WEIGHTS["base_score"] * max(0.0, min(1.0, float(base_score))))
        + (RETRIEVAL_COHERENCE_WEIGHTS["context_score"] * context_score)
        + (RETRIEVAL_COHERENCE_WEIGHTS["title_overlap"] * title_overlap)
        + (RETRIEVAL_COHERENCE_WEIGHTS["lexical_overlap"] * lexical_overlap)
        + (RETRIEVAL_COHERENCE_WEIGHTS["strong_overlap"] * strong_overlap)
        + (RETRIEVAL_COHERENCE_WEIGHTS["topic_overlap"] * topic_overlap)
        + min(
            RETRIEVAL_COHERENCE_TERM_CAPS["shared_signal_terms"][0],
            len(shared_signal_terms) * RETRIEVAL_COHERENCE_TERM_CAPS["shared_signal_terms"][1],
        )
        + min(
            RETRIEVAL_COHERENCE_TERM_CAPS["component_terms"][0],
            len(component_terms) * RETRIEVAL_COHERENCE_TERM_CAPS["component_terms"][1],
        )
        + min(
            RETRIEVAL_COHERENCE_TERM_CAPS["action_terms"][0],
            len(action_terms) * RETRIEVAL_COHERENCE_TERM_CAPS["action_terms"][1],
        )
    )
    if dominant_topic and dominant_topic in query_topics:
        coherence += RETRIEVAL_COHERENCE_BONUSES["dominant_topic_match"]
    elif dominant_domain and dominant_domain in query_domains:
        coherence += RETRIEVAL_COHERENCE_BONUSES["dominant_domain_match"]
    if exact_strong_hits >= 2:
        coherence += RETRIEVAL_COHERENCE_BONUSES["exact_strong_multi"]
    elif exact_strong_hits >= 1 and shared_signal_terms:
        coherence += RETRIEVAL_COHERENCE_BONUSES["exact_strong_single"]
    if exact_focus_hits >= 2 and shared_signal_terms:
        coherence += RETRIEVAL_COHERENCE_BONUSES["exact_focus_multi"]
    if features.get("generic_only_overlap"):
        coherence -= RETRIEVAL_COHERENCE_PENALTIES["generic_only_overlap"]
    elif len(generic_overlap_terms) >= 2 and not shared_signal_terms:
        coherence -= RETRIEVAL_COHERENCE_PENALTIES["generic_overlap_without_signal"]
    if topic_mismatch:
        coherence -= RETRIEVAL_COHERENCE_PENALTIES["topic_mismatch"]
    if domain_mismatch:
        coherence -= RETRIEVAL_COHERENCE_PENALTIES["domain_mismatch"]
    if not shared_signal_terms and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_mismatch_overlap"] and context_score < RETRIEVAL_COHERENCE_PENALTIES["weak_signal_context_max"]:
        coherence = min(coherence, RETRIEVAL_COHERENCE_PENALTIES["weak_signal_cap"])
    if not dominant_topic and not component_terms and len(shared_signal_terms) < 1 and len(features.get("shared_terms") or []) < 2:
        coherence = min(coherence, RETRIEVAL_COHERENCE_PENALTIES["minimal_signature_cap"])
    coherence += RETRIEVAL_COHERENCE_BONUSES["evidence_weight_factor"] * _CLUSTER_WEIGHT_BY_EVIDENCE_TYPE.get(evidence_type, RETRIEVAL_DEFAULT_EVIDENCE_WEIGHT)
    return round(max(0.0, min(1.0, coherence)), 4)


def cluster_evidence(query_context: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        metrics = dict(candidate.get("metrics") or {})
        features = dict(candidate.get("features") or {})
        if not features:
            features = extract_evidence_features(
                query_context,
                title=str(candidate.get("title") or ""),
                text=str(candidate.get("text") or ""),
                category_hint=str(candidate.get("category_hint") or ""),
                action_text=str(candidate.get("action_text") or ""),
                reference=str(candidate.get("reference") or ""),
            )
        cluster_id = str(candidate.get("cluster_id") or "").strip().lower() or candidate_topic_signature(features)
        coherence_score = candidate.get("coherence_score")
        if coherence_score is None:
            coherence_score = score_candidate_coherence(
                query_context,
                features=features,
                metrics=metrics,
                base_score=float(candidate.get("base_score") or 0.0),
                evidence_type=str(candidate.get("evidence_type") or ""),
            )
        enriched.append(
            {
                **candidate,
                "features": features,
                "metrics": metrics,
                "cluster_id": cluster_id,
                "coherence_score": round(float(coherence_score), 4),
            }
        )

    cluster_map: dict[str, dict[str, Any]] = {}
    for candidate in enriched:
        cluster_id = str(candidate.get("cluster_id") or "generic")
        weight = _CLUSTER_WEIGHT_BY_EVIDENCE_TYPE.get(str(candidate.get("evidence_type") or ""), RETRIEVAL_DEFAULT_EVIDENCE_WEIGHT)
        cluster = cluster_map.setdefault(
            cluster_id,
            {
                "cluster_id": cluster_id,
                "dominant_topic": candidate.get("features", {}).get("dominant_topic"),
                "signature_terms": list(candidate.get("features", {}).get("signature_terms") or []),
                "candidate_count": 0,
                "support_count": 0,
                "score": 0.0,
                "references": [],
                "top_candidate": candidate,
            },
        )
        cluster["candidate_count"] += 1
        if float(candidate.get("coherence_score") or 0.0) >= RETRIEVAL_CLUSTER_THRESHOLDS["support_min_coherence"]:
            cluster["support_count"] += 1
        cluster["score"] += float(candidate.get("coherence_score") or 0.0) * weight
        reference = str(candidate.get("reference") or "").strip()
        if reference and reference not in cluster["references"]:
            cluster["references"].append(reference)
        top_candidate = dict(cluster.get("top_candidate") or {})
        current_key = (
            float(candidate.get("coherence_score") or 0.0),
            float(candidate.get("base_score") or 0.0),
            1 if not bool(candidate.get("topic_mismatch")) else 0,
            1 if not bool(candidate.get("domain_mismatch")) else 0,
        )
        top_key = (
            float(top_candidate.get("coherence_score") or 0.0),
            float(top_candidate.get("base_score") or 0.0),
            1 if not bool(top_candidate.get("topic_mismatch")) else 0,
            1 if not bool(top_candidate.get("domain_mismatch")) else 0,
        )
        if current_key > top_key:
            cluster["top_candidate"] = candidate
            cluster["dominant_topic"] = candidate.get("features", {}).get("dominant_topic")
            cluster["signature_terms"] = list(candidate.get("features", {}).get("signature_terms") or [])

    clusters = list(cluster_map.values())
    for cluster in clusters:
        cluster["score"] = round(
            float(cluster.get("score") or 0.0)
            + min(
                RETRIEVAL_CLUSTER_THRESHOLDS["support_bonus_cap"],
                max(0, int(cluster.get("support_count") or 0) - 1) * RETRIEVAL_CLUSTER_THRESHOLDS["support_bonus_step"],
            )
            + (RETRIEVAL_CLUSTER_THRESHOLDS["dominant_topic_bonus"] if cluster.get("dominant_topic") else 0.0),
            4,
        )

    clusters.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            int(item.get("support_count") or 0),
            float((item.get("top_candidate") or {}).get("coherence_score") or 0.0),
        ),
        reverse=True,
    )
    return {"candidates": enriched, "clusters": clusters}


def select_primary_cluster(clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not clusters:
        return None
    for cluster in clusters:
        top_candidate = dict(cluster.get("top_candidate") or {})
        support_count = int(cluster.get("support_count") or 0)
        score = float(cluster.get("score") or 0.0)
        top_coherence = float(top_candidate.get("coherence_score") or 0.0)
        has_strong_anchor = (
            not bool(top_candidate.get("topic_mismatch"))
            and not bool(top_candidate.get("domain_mismatch"))
            and (
                int(top_candidate.get("exact_strong_hits") or 0) >= 1
                or float(top_candidate.get("strong_overlap") or 0.0) >= RETRIEVAL_CLUSTER_THRESHOLDS["anchor_overlap"]
                or len(list((top_candidate.get("features") or {}).get("shared_signal_terms") or [])) >= 2
            )
        )
        if support_count >= 2 and score >= RETRIEVAL_CLUSTER_THRESHOLDS["support_count_score"]:
            return cluster
        if (
            top_coherence >= RETRIEVAL_CLUSTER_THRESHOLDS["anchored_top_coherence"]
            and has_strong_anchor
            and score >= RETRIEVAL_CLUSTER_THRESHOLDS["anchored_cluster_score"]
        ):
            return cluster
        dominant_topic = str((top_candidate.get("features") or {}).get("dominant_topic") or "").strip().lower()
        shared_signals = list((top_candidate.get("features") or {}).get("shared_signal_terms") or [])
        if (
            top_coherence >= RETRIEVAL_CLUSTER_THRESHOLDS["strong_top_coherence"]
            and score >= RETRIEVAL_CLUSTER_THRESHOLDS["strong_cluster_score"]
            and not bool(top_candidate.get("topic_mismatch"))
            and (
                not bool(top_candidate.get("domain_mismatch"))
                or bool(dominant_topic)
                or len(shared_signals) >= 3
            )
        ):
            return cluster
    return None


def evidence_conflict_detected(selected_cluster: dict[str, Any] | None, clusters: list[dict[str, Any]]) -> bool:
    if selected_cluster is None or len(clusters) < 2:
        return False
    second_cluster = next(
        (cluster for cluster in clusters if str(cluster.get("cluster_id")) != str(selected_cluster.get("cluster_id"))),
        None,
    )
    if second_cluster is None:
        return False
    top_score = float(selected_cluster.get("score") or 0.0)
    second_score = float(second_cluster.get("score") or 0.0)
    top_candidate = dict(selected_cluster.get("top_candidate") or {})
    second_candidate = dict(second_cluster.get("top_candidate") or {})
    strong_second = second_score >= RETRIEVAL_CLUSTER_THRESHOLDS["conflict_second_score"] and (
        int(second_cluster.get("support_count") or 0) >= 1
        or float(second_candidate.get("coherence_score") or 0.0) >= RETRIEVAL_CLUSTER_THRESHOLDS["conflict_second_coherence"]
    )
    scores_close = (
        (top_score - second_score) <= RETRIEVAL_CLUSTER_THRESHOLDS["conflict_margin"]
        or second_score >= (top_score * RETRIEVAL_CLUSTER_THRESHOLDS["conflict_ratio"])
    )
    different_family = str(selected_cluster.get("cluster_id") or "") != str(second_cluster.get("cluster_id") or "")
    return different_family and scores_close and strong_second


def _row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_score": float(row.get("context_score") or 0.0),
        "lexical_overlap": float(row.get("lexical_overlap") or 0.0),
        "title_overlap": float(row.get("title_overlap") or 0.0),
        "focus_overlap": float(row.get("focus_overlap") or 0.0),
        "strong_overlap": float(row.get("strong_overlap") or 0.0),
        "exact_focus_hits": int(row.get("exact_focus_hits") or 0),
        "exact_strong_hits": int(row.get("exact_strong_hits") or 0),
        "topic_overlap": float(row.get("topic_overlap") or 0.0),
        "topic_mismatch": bool(row.get("topic_mismatch")),
        "contrast_topic_match": bool(row.get("contrast_topic_match")),
        "generic_overlap": float(row.get("generic_overlap") or 0.0),
        "domain_mismatch": bool(row.get("domain_mismatch")),
        "contrast_domain_match": bool(row.get("contrast_domain_match")),
    }


def grounded_issue_matches(
    query: str,
    raw_matches: list[dict[str, Any]],
    *,
    top_k: int = 5,
    score_threshold: float = 0.0,
    excluded_jira_keys: set[str] | None = None,
) -> dict[str, Any]:
    query_context = _query_context(query)
    blocked_jira_keys = {_normalize_jira_key(item) for item in (excluded_jira_keys or set()) if _normalize_jira_key(item)}

    grounded: list[dict[str, Any]] = []
    cluster_inputs: list[dict[str, Any]] = []
    contrast_rejections: list[dict[str, Any]] = []
    for idx, match in enumerate(raw_matches, start=1):
        metadata = match.get("metadata") or {}
        jira_key = _normalize_jira_key(match.get("jira_key") or metadata.get("jira_key"))
        if not jira_key or jira_key in blocked_jira_keys:
            continue
        try:
            semantic_score = float(match.get("score") or 0.0)
        except (TypeError, ValueError):
            semantic_score = 0.0
        if semantic_score < score_threshold:
            continue
        title = (
            str(metadata.get("summary") or "").strip()
            or str(metadata.get("title") or "").strip()
            or str(match.get("jira_key") or "").strip()
            or f"KB Match {idx}"
        )
        category_hint = " ".join(
            part
            for part in [
                str(metadata.get("issuetype") or "").strip(),
                str(metadata.get("components") or "").strip(),
                str(metadata.get("labels") or "").strip(),
            ]
            if part
        )
        text = " ".join(part for part in [title, str(match.get("content") or "")] if part)
        metrics = _context_metrics(
            query_context,
            candidate_text=text,
            candidate_title=title,
            category_hint=category_hint,
        )
        features = extract_evidence_features(
            query_context,
            title=title,
            text=str(match.get("content") or ""),
            category_hint=category_hint,
            reference=jira_key,
        )
        cluster_id = candidate_topic_signature(features)
        coherence_score = score_candidate_coherence(
            query_context,
            features=features,
            metrics=metrics,
            base_score=semantic_score,
            evidence_type="KB article",
        )
        if not _passes_context_gate(metrics, semantic_score):
            if bool(metrics.get("contrast_domain_match") or metrics.get("contrast_topic_match")):
                contrast_rejections.append(
                    {
                        "jira_key": jira_key,
                        "score": round(semantic_score, 4),
                        "cluster_id": cluster_id,
                        "coherence_score": coherence_score,
                    }
                )
            continue
        grounded_row = {
            "score": round(semantic_score, 4),
            "distance": float(match.get("distance") or 1.0),
            "jira_key": jira_key,
            "jira_issue_id": str(match.get("jira_issue_id") or "").strip() or None,
            "content": str(match.get("content") or ""),
            "metadata": metadata,
            "title": title,
            "metrics": metrics,
            "features": features,
            "cluster_id": cluster_id,
            "coherence_score": coherence_score,
        }
        grounded.append(grounded_row)
        cluster_inputs.append(
            {
                "reference": jira_key,
                "title": title,
                "text": str(match.get("content") or ""),
                "evidence_type": "KB article",
                "base_score": semantic_score,
                "metrics": metrics,
                "features": features,
                "cluster_id": cluster_id,
                "coherence_score": coherence_score,
                "category_hint": category_hint,
            }
        )

    cluster_result = cluster_evidence(query_context, cluster_inputs)
    selected_cluster = select_primary_cluster(cluster_result["clusters"])
    conflict = evidence_conflict_detected(selected_cluster, cluster_result["clusters"])
    selected_cluster_id = str((selected_cluster or {}).get("cluster_id") or "").strip().lower() or None
    strongest_rejection = max(
        contrast_rejections,
        key=lambda item: (float(item.get("coherence_score") or 0.0), float(item.get("score") or 0.0)),
        default=None,
    )
    if not conflict and selected_cluster is not None and strongest_rejection is not None:
        selected_score = float((selected_cluster or {}).get("score") or 0.0)
        rejected_score = float(strongest_rejection.get("score") or 0.0)
        rejected_cluster_id = str(strongest_rejection.get("cluster_id") or "").strip().lower()
        if (
            rejected_cluster_id
            and rejected_cluster_id != selected_cluster_id
            and (
                rejected_score >= RETRIEVAL_CLUSTER_THRESHOLDS["conflict_second_score"]
                or (
                    selected_score > 0.0
                    and rejected_score >= selected_score * RETRIEVAL_CLUSTER_THRESHOLDS["conflict_ratio"]
                )
            )
        ):
            conflict = True

    if conflict or (selected_cluster is None and len(cluster_result["clusters"]) >= 2):
        filtered = []
    elif selected_cluster_id:
        filtered = [row for row in grounded if str(row.get("cluster_id") or "").strip().lower() == selected_cluster_id]
    else:
        filtered = list(grounded)

    filtered.sort(
        key=lambda row: (
            float(row.get("coherence_score") or 0.0),
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )
    return {
        "query_context": query_context,
        "matches": filtered[: max(1, top_k)],
        "all_matches": grounded,
        "clusters": cluster_result["clusters"],
        "selected_cluster_id": selected_cluster_id,
        "evidence_conflict_flag": conflict,
    }


def _retrieval_consensus(
    query_context: dict[str, Any],
    *,
    kb_articles: list[dict[str, Any]],
    similar_tickets: list[dict[str, Any]],
    solution_recommendations: list[dict[str, Any]],
    related_problems: list[dict[str, Any]],
    raw_confidence: float,
) -> tuple[float, float, dict[str, Any], bool]:
    cluster_inputs: list[dict[str, Any]] = []

    for row in kb_articles:
        cluster_inputs.append(
            {
                "reference": str(row.get("jira_key") or row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "text": str(row.get("excerpt") or ""),
                "evidence_type": "KB article",
                "base_score": float(row.get("similarity_score") or 0.0),
                "metrics": _row_metrics(row),
                "category_hint": str(row.get("source_type") or ""),
            }
        )
    for row in similar_tickets:
        status = str(row.get("status") or "").strip().lower()
        evidence_type = "resolved ticket" if status in {"resolved", "closed"} else "similar ticket"
        cluster_inputs.append(
            {
                "reference": str(row.get("id") or row.get("jira_key") or ""),
                "title": str(row.get("title") or ""),
                "text": " ".join(
                    part
                    for part in [
                        str(row.get("resolution_snippet") or ""),
                        str(row.get("description_snippet") or ""),
                    ]
                    if part
                ),
                "evidence_type": evidence_type,
                "base_score": float(row.get("similarity_score") or 0.0),
                "metrics": _row_metrics(row),
                "category_hint": str(row.get("category") or ""),
            }
        )
    for row in solution_recommendations:
        cluster_inputs.append(
            {
                "reference": str(row.get("source_id") or ""),
                "title": str(row.get("source_id") or ""),
                "text": str(row.get("evidence_snippet") or row.get("text") or ""),
                "evidence_type": "comment",
                "base_score": max(float(row.get("confidence") or 0.0), float(row.get("quality_score") or 0.0)),
                "metrics": _row_metrics(row),
            }
        )
    for row in related_problems:
        cluster_inputs.append(
            {
                "reference": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "text": " ".join(
                    part for part in [str(row.get("match_reason") or ""), str(row.get("root_cause") or "")] if part
                ),
                "evidence_type": "related problem",
                "base_score": float(row.get("similarity_score") or 0.0),
                "metrics": _row_metrics(row),
            }
        )

    if not cluster_inputs:
        return raw_confidence, 0.0, {}, False

    cluster_result = cluster_evidence(query_context, cluster_inputs)
    clusters = list(cluster_result.get("clusters") or [])
    selected_cluster = select_primary_cluster(clusters)
    conflict = evidence_conflict_detected(selected_cluster, clusters)
    selected_score = float((selected_cluster or {}).get("score") or 0.0)
    top_coherence = float(((selected_cluster or {}).get("top_candidate") or {}).get("coherence_score") or 0.0)
    support_count = int((selected_cluster or {}).get("support_count") or 0)
    total_candidates = max(1, len(cluster_inputs))
    support_ratio = support_count / total_candidates
    second_score = 0.0
    if selected_cluster is not None:
        second_score = max(
            (
                float(cluster.get("score") or 0.0)
                for cluster in clusters
                if str(cluster.get("cluster_id") or "") != str(selected_cluster.get("cluster_id") or "")
            ),
            default=0.0,
        )
    margin_ratio = 0.0
    if selected_score > 0.0:
        margin_ratio = max(0.0, min(1.0, (selected_score - second_score) / selected_score))
    consensus_confidence = round(
        max(
            0.0,
            min(
                1.0,
                (RETRIEVAL_CONSENSUS_WEIGHTS["cluster_score"] * selected_score)
                + (RETRIEVAL_CONSENSUS_WEIGHTS["top_coherence"] * top_coherence)
                + (RETRIEVAL_CONSENSUS_WEIGHTS["support_ratio"] * support_ratio)
                + (RETRIEVAL_CONSENSUS_WEIGHTS["margin_ratio"] * margin_ratio),
            ),
        ),
        4,
    )
    if selected_cluster is None and len(clusters) >= 2:
        adjusted_confidence = min(raw_confidence, _QUALITY_THRESHOLDS["low"])
    else:
        adjusted_confidence = (
            (RETRIEVAL_CONSENSUS_WEIGHTS["raw_score"] * raw_confidence)
            + (RETRIEVAL_CONSENSUS_WEIGHTS["consensus_score"] * consensus_confidence)
        )
    if conflict:
        adjusted_confidence = min(adjusted_confidence, _QUALITY_THRESHOLDS["low"])
    evidence_clusters = {
        "selected_cluster_id": str((selected_cluster or {}).get("cluster_id") or ""),
        "coherence_score": round(selected_score, 4),
        "consensus_confidence": consensus_confidence,
        "evidence_conflict_flag": conflict,
        "clusters": [
            {
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "score": round(float(cluster.get("score") or 0.0), 4),
                "support_count": int(cluster.get("support_count") or 0),
                "candidate_count": int(cluster.get("candidate_count") or 0),
                "dominant_topic": cluster.get("dominant_topic"),
                "signature_terms": list(cluster.get("signature_terms") or [])[:3],
                "references": list(cluster.get("references") or [])[:3],
            }
            for cluster in clusters[:4]
        ],
    }
    return round(max(0.0, min(1.0, adjusted_confidence)), 4), consensus_confidence, evidence_clusters, conflict


def _context_metrics(
    query_context: dict[str, Any],
    *,
    candidate_text: str,
    candidate_title: str | None = None,
    category_hint: str | None = None,
) -> dict[str, Any]:
    query_tokens = set(query_context.get("tokens") or [])
    title_tokens = set(query_context.get("title_tokens") or [])
    focus_terms = set(query_context.get("focus_terms") or [])
    strong_terms = set(query_context.get("strong_terms") or [])
    candidate_title_tokens = _meaningful_tokens(candidate_title or "")
    candidate_tokens = _meaningful_tokens(candidate_text)
    candidate_strong_terms = _strong_signal_terms(candidate_tokens.union(candidate_title_tokens))
    lexical_overlap = _overlap_score(query_tokens, candidate_tokens)
    title_overlap = _overlap_score(title_tokens, candidate_title_tokens or candidate_tokens)
    focus_overlap = _overlap_score(focus_terms, candidate_tokens)
    exact_focus_hits = len(focus_terms.intersection(candidate_tokens))
    strong_overlap = _overlap_score(strong_terms, candidate_strong_terms)
    exact_strong_hits = len(strong_terms.intersection(candidate_strong_terms))
    query_domains = set(query_context.get("domains") or [])
    query_topics = set(query_context.get("topics") or [])
    negative_domains = set(query_context.get("negative_domains") or [])
    negative_topics = set(query_context.get("negative_topics") or [])
    category_tokens = _meaningful_tokens(str(category_hint or "").replace("_", " "))
    candidate_with_category = candidate_tokens.union(candidate_title_tokens).union(category_tokens)
    candidate_domains = _domain_signals(candidate_with_category)
    candidate_topics = _topic_signals(candidate_with_category)
    domain_mismatch = bool(query_domains and candidate_domains and query_domains.isdisjoint(candidate_domains))
    contrast_domain_match = bool(negative_domains and candidate_domains and not negative_domains.isdisjoint(candidate_domains))
    # Topic mismatch: fully disjoint, OR domain-specific (non-generic) topics are both
    # non-empty and disjoint even when a cross-cutting topic (e.g. auth_path) is shared.
    _GENERIC_TOPIC_FAMILIES_CTX = frozenset({"auth_path"})
    _query_specific_topics = query_topics - _GENERIC_TOPIC_FAMILIES_CTX
    _cand_specific_topics = candidate_topics - _GENERIC_TOPIC_FAMILIES_CTX
    topic_mismatch = bool(
        query_topics and candidate_topics and (
            query_topics.isdisjoint(candidate_topics)
            or (_query_specific_topics and _cand_specific_topics and _query_specific_topics.isdisjoint(_cand_specific_topics))
        )
    )
    contrast_topic_match = bool(negative_topics and candidate_topics and not negative_topics.isdisjoint(candidate_topics))
    topic_overlap = (
        len(query_topics.intersection(candidate_topics)) / max(1, len(query_topics))
        if query_topics and candidate_topics
        else 0.0
    )
    generic_query_tokens = {token for token in query_tokens if token in _LOW_SIGNAL_TOKENS}
    generic_candidate_tokens = {token for token in candidate_tokens if token in _LOW_SIGNAL_TOKENS}
    generic_overlap = _overlap_score(generic_query_tokens, generic_candidate_tokens)
    exact_phrase_bonus = 0.0
    lowered_title = _normalize_text(candidate_title).lower()
    lowered_text = _normalize_text(candidate_text).lower()
    for token in list(focus_terms)[:4]:
        if token and (f" {token} " in f" {lowered_title} " or f" {token} " in f" {lowered_text} "):
            exact_phrase_bonus += RETRIEVAL_CONTEXT_BONUSES["exact_phrase_step"]
    context_score = (
        (RETRIEVAL_CONTEXT_WEIGHTS["title_overlap"] * title_overlap)
        + (RETRIEVAL_CONTEXT_WEIGHTS["focus_overlap"] * focus_overlap)
        + (RETRIEVAL_CONTEXT_WEIGHTS["lexical_overlap"] * lexical_overlap)
        + (RETRIEVAL_CONTEXT_WEIGHTS["strong_overlap"] * strong_overlap)
        + (RETRIEVAL_CONTEXT_WEIGHTS["topic_overlap"] * topic_overlap)
        + min(RETRIEVAL_CONTEXT_BONUSES["exact_phrase_cap"], exact_phrase_bonus)
    )
    if exact_strong_hits >= 2:
        context_score += RETRIEVAL_CONTEXT_BONUSES["exact_strong_multi"]
    if generic_overlap > strong_overlap and lexical_overlap > 0.0:
        context_score -= RETRIEVAL_CONTEXT_PENALTIES["generic_lexical_penalty"]
    if topic_mismatch:
        context_score -= RETRIEVAL_CONTEXT_PENALTIES["topic_mismatch_penalty"]
    if domain_mismatch:
        context_score -= RETRIEVAL_CONTEXT_PENALTIES["domain_mismatch_penalty"]
    if contrast_topic_match:
        context_score -= RETRIEVAL_CONTEXT_PENALTIES["contrast_topic_penalty"]
    if contrast_domain_match:
        context_score -= RETRIEVAL_CONTEXT_PENALTIES["contrast_domain_penalty"]
    return {
        "lexical_overlap": round(lexical_overlap, 4),
        "title_overlap": round(title_overlap, 4),
        "focus_overlap": round(focus_overlap, 4),
        "exact_focus_hits": exact_focus_hits,
        "strong_overlap": round(strong_overlap, 4),
        "exact_strong_hits": exact_strong_hits,
        "topic_overlap": round(max(0.0, min(1.0, topic_overlap)), 4),
        "topic_mismatch": topic_mismatch,
        "contrast_topic_match": contrast_topic_match,
        "generic_overlap": round(generic_overlap, 4),
        "domain_mismatch": domain_mismatch,
        "contrast_domain_match": contrast_domain_match,
        "candidate_domains": sorted(candidate_domains),
        "candidate_topics": sorted(candidate_topics),
        "context_score": round(max(0.0, min(1.0, context_score)), 4),
    }


def _passes_context_gate(metrics: dict[str, Any], semantic_score: float = 0.0) -> bool:
    context_score = float(metrics.get("context_score") or 0.0)
    title_overlap = float(metrics.get("title_overlap") or 0.0)
    focus_overlap = float(metrics.get("focus_overlap") or 0.0)
    lexical_overlap = float(metrics.get("lexical_overlap") or 0.0)
    strong_overlap = float(metrics.get("strong_overlap") or 0.0)
    domain_mismatch = bool(metrics.get("domain_mismatch"))
    topic_mismatch = bool(metrics.get("topic_mismatch"))
    contrast_domain_match = bool(metrics.get("contrast_domain_match"))
    contrast_topic_match = bool(metrics.get("contrast_topic_match"))
    exact_focus_hits = int(metrics.get("exact_focus_hits") or 0)
    exact_strong_hits = int(metrics.get("exact_strong_hits") or 0)
    generic_overlap = float(metrics.get("generic_overlap") or 0.0)
    if contrast_topic_match and exact_focus_hits == 0 and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["contrast_overlap_max"]:
        return False
    if contrast_domain_match and exact_focus_hits == 0 and focus_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["contrast_overlap_max"] and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["contrast_overlap_max"]:
        return False
    if topic_mismatch and exact_focus_hits == 0 and exact_strong_hits == 0 and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_mismatch_overlap"]:
        return False
    if domain_mismatch and exact_focus_hits == 0 and focus_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["domain_mismatch_overlap"] and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["domain_mismatch_overlap"]:
        return False
    if generic_overlap > strong_overlap and context_score < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["generic_context_min"] and exact_strong_hits == 0:
        return False
    if context_score >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["context_pass_min"] and not (
        topic_mismatch
        and strong_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_context_strong_overlap"]
        and title_overlap < RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_context_title_overlap"]
    ):
        return True
    if exact_focus_hits >= 2 and not domain_mismatch and not topic_mismatch:
        return True
    if exact_strong_hits >= 2 and not topic_mismatch:
        return True
    if semantic_score >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["semantic_score_min"] and not domain_mismatch and not topic_mismatch and (
        strong_overlap >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_mismatch_overlap"]
        or focus_overlap >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_context_title_overlap"]
        or lexical_overlap >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["semantic_lexical_overlap"]
        or title_overlap >= RETRIEVAL_CONTEXT_GATE_THRESHOLDS["topic_context_title_overlap"]
    ):
        return True
    return False


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
        return RETRIEVAL_TICKET_STATUS_SCORES["resolved"]
    if status in {"open", "in_progress", "waiting_for_customer", "waiting_for_support_vendor", "pending"}:
        return RETRIEVAL_TICKET_STATUS_SCORES["open"]
    return 0.0


def _comment_quality_score(content: str) -> float:
    text = _normalize_text(content).lower()
    if not text:
        return 0.0
    length = len(text)
    length_score = 0.0
    if length >= 80:
        length_score += RETRIEVAL_COMMENT_QUALITY["length_80"]
    if length >= 160:
        length_score += RETRIEVAL_COMMENT_QUALITY["length_160"]
    if length >= 260:
        length_score += RETRIEVAL_COMMENT_QUALITY["length_260"]

    action_hits = sum(1 for token in _ACTION_HINTS if token in text)
    outcome_hits = sum(1 for token in _OUTCOME_HINTS if token in text)
    structure_hits = 0
    if any(marker in text for marker in ("1.", "2.", "step", "then", "after", "finally", "\n")):
        structure_hits += 1
    if ":" in text:
        structure_hits += 1

    score = length_score
    score += min(RETRIEVAL_COMMENT_QUALITY["action_hit_cap"], action_hits * RETRIEVAL_COMMENT_QUALITY["action_hit_step"])
    score += min(RETRIEVAL_COMMENT_QUALITY["outcome_hit_cap"], outcome_hits * RETRIEVAL_COMMENT_QUALITY["outcome_hit_step"])
    score += min(RETRIEVAL_COMMENT_QUALITY["structure_hit_cap"], structure_hits * RETRIEVAL_COMMENT_QUALITY["structure_hit_step"])
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


def _local_ticket_similarity(query: str, query_context: dict[str, Any], ticket: Ticket) -> tuple[float, dict[str, Any]]:
    metrics = _context_metrics(
        query_context,
        candidate_text=" ".join(
            part
            for part in [
                _normalize_text(ticket.title),
                _normalize_text(ticket.description),
                _normalize_text(ticket.resolution),
            ]
            if part
        ),
        candidate_title=ticket.title,
        category_hint=getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)),
    )
    score = (
        (RETRIEVAL_LOCAL_LEXICAL["title_overlap"] * float(metrics["title_overlap"]))
        + (RETRIEVAL_LOCAL_LEXICAL["focus_overlap"] * float(metrics["focus_overlap"]))
        + (RETRIEVAL_LOCAL_LEXICAL["lexical_overlap"] * float(metrics["lexical_overlap"]))
        + (RETRIEVAL_LOCAL_LEXICAL["strong_overlap"] * float(metrics.get("strong_overlap") or 0.0))
        + (RETRIEVAL_LOCAL_LEXICAL["topic_overlap"] * float(metrics.get("topic_overlap") or 0.0))
    )

    normalized_query = _normalize_text(query).lower()
    normalized_title = _normalize_text(ticket.title).lower()
    normalized_description = _normalize_text(ticket.description).lower()
    if normalized_query and (normalized_query in normalized_title or normalized_query in normalized_description):
        score += RETRIEVAL_LOCAL_LEXICAL["query_exact_bonus"]

    ticket_id = str(ticket.id or "").strip().lower()
    if ticket_id and ticket_id in normalized_query:
        score += RETRIEVAL_LOCAL_LEXICAL["ticket_id_bonus"]

    category = str(getattr(ticket, "category", None).value if getattr(ticket, "category", None) else "").strip().lower()
    if category:
        category_tokens = _CATEGORY_HINTS.get(category) or _meaningful_tokens(category.replace("_", " "))
        # Category is only a helper signal.
        if set(query_context.get("tokens") or []).intersection(category_tokens):
            score += RETRIEVAL_LOCAL_LEXICAL["category_bonus"]

    if metrics.get("topic_mismatch"):
        score -= RETRIEVAL_LOCAL_LEXICAL["topic_mismatch_penalty"]
    if metrics["domain_mismatch"]:
        score -= RETRIEVAL_LOCAL_LEXICAL["domain_mismatch_penalty"]
    score += _ticket_outcome_score(ticket)
    return max(0.0, min(1.0, score)), metrics


def _local_ticket_matches(query: str, tickets: list[Ticket], *, query_context: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    if not query_context.get("tokens"):
        return []

    scored: list[tuple[float, Ticket, dict[str, Any]]] = []
    for ticket in tickets:
        score, metrics = _local_ticket_similarity(query, query_context, ticket)
        if score < RETRIEVAL_LOCAL_LEXICAL["score_min"]:
            continue
        if not _passes_context_gate(metrics, score):
            continue
        scored.append((score, ticket, metrics))

    scored.sort(
        key=lambda item: (
            item[0],
            float(item[2].get("context_score") or 0.0),
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
            "created_at": getattr(ticket, "created_at", None).isoformat() if getattr(ticket, "created_at", None) else None,
            "updated_at": getattr(ticket, "updated_at", None).isoformat() if getattr(ticket, "updated_at", None) else None,
            "resolution_snippet": _truncate(str(ticket.resolution or "")) or None,
            "similarity_score": round(float(score), 4),
            "problem_id": str(getattr(ticket, "problem_id", None) or "").strip() or None,
            "jira_key": str(getattr(ticket, "jira_key", None) or "").strip() or None,
            "source": "local_lexical",
            "context_score": float(metrics.get("context_score") or 0.0),
            "lexical_overlap": float(metrics.get("lexical_overlap") or 0.0),
            "title_overlap": float(metrics.get("title_overlap") or 0.0),
            "strong_overlap": float(metrics.get("strong_overlap") or 0.0),
            "topic_overlap": float(metrics.get("topic_overlap") or 0.0),
            "topic_mismatch": bool(metrics.get("topic_mismatch")),
            "domain_mismatch": bool(metrics.get("domain_mismatch")),
        }
        for score, ticket, metrics in scored[:limit]
    ]


def _local_ticket_semantic_matches(
    query: str,
    tickets: list[Ticket],
    *,
    query_context: dict[str, Any],
    lexical_seed: list[dict[str, Any]],
    limit: int = 8,
    semantic_pool_size: int = 18,
    query_embedding: tuple[float, ...] | None = None,
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

    if query_embedding is None:
        try:
            query_embedding = _embedding_for_text(normalized_query)
        except Exception:
            return []
    if not query_embedding:
        return []
    query_embedding_list = list(query_embedding)

    scored: list[tuple[float, Ticket, dict[str, Any]]] = []
    for ticket in pool:
        try:
            ticket_embedding = _embedding_for_text(_ticket_semantic_text(ticket))
        except Exception:
            continue
        if not ticket_embedding:
            continue
        cosine = _cosine_similarity(query_embedding_list, list(ticket_embedding))
        semantic_score = _to_unit_score(cosine)
        metrics = _context_metrics(
            query_context,
            candidate_text=_ticket_semantic_text(ticket),
            candidate_title=ticket.title,
            category_hint=getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)),
        )
        if not _passes_context_gate(metrics, semantic_score):
            continue
        score = (
            RETRIEVAL_LOCAL_SEMANTIC["semantic_weight"] * semantic_score
            + RETRIEVAL_LOCAL_SEMANTIC["context_weight"] * float(metrics.get("context_score") or 0.0)
        )
        score += _ticket_outcome_score(ticket)
        if score < RETRIEVAL_LOCAL_SEMANTIC["score_min"]:
            continue
        scored.append((score, ticket, metrics))

    scored.sort(
        key=lambda item: (
            item[0],
            float(item[2].get("context_score") or 0.0),
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
            "created_at": getattr(ticket, "created_at", None).isoformat() if getattr(ticket, "created_at", None) else None,
            "updated_at": getattr(ticket, "updated_at", None).isoformat() if getattr(ticket, "updated_at", None) else None,
            "resolution_snippet": _truncate(str(ticket.resolution or "")) or None,
            "similarity_score": round(float(score), 4),
            "problem_id": str(getattr(ticket, "problem_id", None) or "").strip() or None,
            "jira_key": str(getattr(ticket, "jira_key", None) or "").strip() or None,
            "source": "local_semantic",
            "context_score": float(metrics.get("context_score") or 0.0),
            "lexical_overlap": float(metrics.get("lexical_overlap") or 0.0),
            "title_overlap": float(metrics.get("title_overlap") or 0.0),
            "strong_overlap": float(metrics.get("strong_overlap") or 0.0),
            "topic_overlap": float(metrics.get("topic_overlap") or 0.0),
            "topic_mismatch": bool(metrics.get("topic_mismatch")),
            "domain_mismatch": bool(metrics.get("domain_mismatch")),
        }
        for score, ticket, metrics in scored[:limit]
    ]


def _ticket_from_visible_pool(
    ticket: Ticket,
    *,
    score: float,
    source: str,
    context_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _truncate(str(ticket.resolution or "")) or None
    return {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status.value if getattr(ticket, "status", None) else "unknown",
        "created_at": getattr(ticket, "created_at", None).isoformat() if getattr(ticket, "created_at", None) else None,
        "updated_at": getattr(ticket, "updated_at", None).isoformat() if getattr(ticket, "updated_at", None) else None,
        "resolution_snippet": evidence,
        "similarity_score": round(max(0.0, min(1.0, float(score))), 4),
        "problem_id": str(getattr(ticket, "problem_id", None) or "").strip() or None,
        "jira_key": str(getattr(ticket, "jira_key", None) or "").strip() or None,
        "outcome_score": round(_ticket_outcome_score(ticket), 4),
        "evidence_source": "ticket_resolution" if evidence else "ticket_metadata",
        "evidence_snippet": evidence,
        "recommendation_reason": "Matched similar incident with resolved outcome" if evidence else "Matched similar incident",
        "source": source,
        "context_score": float((context_metrics or {}).get("context_score") or 0.0),
        "lexical_overlap": float((context_metrics or {}).get("lexical_overlap") or 0.0),
        "title_overlap": float((context_metrics or {}).get("title_overlap") or 0.0),
        "strong_overlap": float((context_metrics or {}).get("strong_overlap") or 0.0),
        "topic_overlap": float((context_metrics or {}).get("topic_overlap") or 0.0),
        "topic_mismatch": bool((context_metrics or {}).get("topic_mismatch")),
        "domain_mismatch": bool((context_metrics or {}).get("domain_mismatch")),
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
            key = str(getattr(ticket, "jira_key", None) or "").strip()
            if key:
                ticket_by_jira[key] = ticket
            ticket_by_id[str(ticket.id)] = ticket

    if missing_ticket_ids:
        rows = db.execute(select(Ticket).where(Ticket.id.in_(list(missing_ticket_ids)))).scalars().all()
        for ticket in rows:
            ticket_by_id[str(ticket.id)] = ticket
            key = str(getattr(ticket, "jira_key", None) or "").strip()
            if key:
                ticket_by_jira[key] = ticket

    return ticket_by_jira, ticket_by_id


def _search_related_problems(
    db: Session,
    *,
    query: str,
    query_context: dict[str, Any],
    seed_problem_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if db is None or not hasattr(db, "execute"):
        return []
    q_tokens = _meaningful_tokens(query)
    candidates = db.execute(select(Problem).order_by(Problem.updated_at.desc()).limit(250)).scalars().all()
    if not candidates:
        return []

    seed_set = {str(pid).strip() for pid in (seed_problem_ids or []) if str(pid).strip()}
    scored: list[tuple[float, Problem, str, dict[str, Any]]] = []

    query_embedding: tuple[float, ...] = tuple()
    try:
        query_embedding = _embedding_for_text(query)
    except Exception:
        query_embedding = tuple()

    for problem in candidates:
        p_text = _problem_text(problem)
        metrics = _context_metrics(
            query_context,
            candidate_text=p_text,
            candidate_title=problem.title,
            category_hint=getattr(getattr(problem, "category", None), "value", getattr(problem, "category", None)),
        )
        lexical = float(metrics.get("context_score") or 0.0)
        semantic = 0.0
        if query_embedding:
            try:
                p_embedding = _embedding_for_text(p_text)
            except Exception:
                p_embedding = tuple()
            if p_embedding:
                semantic = _to_unit_score(_cosine_similarity(list(query_embedding), list(p_embedding)))
        if not _passes_context_gate(metrics, semantic):
            continue
        score = max(lexical, semantic)
        if str(problem.id) in seed_set:
            score = max(score, RETRIEVAL_PROBLEM_SEARCH["seed_score"])
        if score < RETRIEVAL_PROBLEM_SEARCH["score_min"]:
            continue
        reason = "Direct semantic/lexical match from problem knowledge"
        if str(problem.id) in seed_set:
            reason = f"Matches related ticket pattern ({problem.category.value})"
        scored.append((score, problem, reason, metrics))

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
    for score, problem, reason, metrics in scored:
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
                "context_score": float(metrics.get("context_score") or 0.0),
                "lexical_overlap": float(metrics.get("lexical_overlap") or 0.0),
                "title_overlap": float(metrics.get("title_overlap") or 0.0),
                "strong_overlap": float(metrics.get("strong_overlap") or 0.0),
                "topic_overlap": float(metrics.get("topic_overlap") or 0.0),
                "topic_mismatch": bool(metrics.get("topic_mismatch")),
                "domain_mismatch": bool(metrics.get("domain_mismatch")),
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


def _merge_ticket_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    best_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        current = best_by_id.get(row_id)
        row_key = (
            1 if not bool(row.get("topic_mismatch")) else 0,
            1 if not bool(row.get("domain_mismatch")) else 0,
            float(row.get("strong_overlap") or 0.0),
            float(row.get("context_score") or 0.0),
            float(row.get("similarity_score") or 0.0),
            1 if str(row.get("status") or "").lower() in {"resolved", "closed"} else 0,
        )
        if current is None:
            best_by_id[row_id] = row
            continue
        current_key = (
            1 if not bool(current.get("topic_mismatch")) else 0,
            1 if not bool(current.get("domain_mismatch")) else 0,
            float(current.get("strong_overlap") or 0.0),
            float(current.get("context_score") or 0.0),
            float(current.get("similarity_score") or 0.0),
            1 if str(current.get("status") or "").lower() in {"resolved", "closed"} else 0,
        )
        if row_key > current_key:
            best_by_id[row_id] = row
    merged = list(best_by_id.values())
    merged.sort(
        key=lambda row: (
            1 if not bool(row.get("topic_mismatch")) else 0,
            1 if not bool(row.get("domain_mismatch")) else 0,
            float(row.get("strong_overlap") or 0.0),
            float(row.get("context_score") or 0.0),
            float(row.get("similarity_score") or 0.0),
            1 if str(row.get("status") or "").lower() in {"resolved", "closed"} else 0,
        ),
        reverse=True,
    )
    return merged[:limit]


def unified_retrieve(
    db: Session,
    *,
    query: str,
    visible_tickets: list[Ticket],
    top_k: int = 5,
    solution_quality: str = "medium",
    enable_local_semantic: bool = True,
    exclude_ids: list[str] | None = None,
) -> RetrievalResult:
    """Single retrieval path used by chat and suggestion APIs."""
    started_at = time.perf_counter()
    normalized = _normalize_text(query)
    query_context = _query_context(query)
    normalized_exclude_ids = {
        _normalize_ticket_id(item)
        for item in list(exclude_ids or [])
        if _normalize_ticket_id(item)
    }
    if not normalized:
        return RetrievalResult(
            kb_articles=[],
            similar_tickets=[],
            related_problems=[],
            suggested_solutions=[],
            confidence=0.0,
            source="fallback_rules",
            comment_matches=[],
            solution_recommendations=[],
            query=normalized,
            query_context=query_context,
            excluded_ids=sorted(normalized_exclude_ids),
        )

    issue_matches: list[dict[str, Any]] = []
    comment_matches: list[dict[str, Any]] = []
    kb_available = False
    query_embedding: tuple[float, ...] | None = None
    try:
        kb_available = kb_has_data(db)
    except Exception:
        _safe_rollback(db)
        kb_available = False
    if kb_available:
        try:
            query_embedding = tuple(float(item) for item in compute_embedding(normalized))
            issue_matches = search_kb_issues(db, normalized, top_k=top_k, query_embedding=query_embedding)
            comment_matches = search_kb(
                db,
                normalized,
                top_k=top_k,
                source_type="jira_comment",
                query_embedding=query_embedding,
            )
        except Exception:
            _safe_rollback(db)
            issue_matches = []
            comment_matches = []

    retrieval_tickets = _filter_ticket_pool(list(visible_tickets or []), exclude_ids=normalized_exclude_ids)
    _, excluded_jira_keys = _collect_excluded_ticket_context(
        db,
        visible_tickets=list(visible_tickets or []),
        exclude_ids=normalized_exclude_ids,
    )
    if not retrieval_tickets:
        fallback_ticket_limit = max(40, min(100, top_k * 12))
        retrieval_tickets = db.execute(
            select(Ticket).order_by(Ticket.updated_at.desc()).limit(fallback_ticket_limit)
        ).scalars().all()
        retrieval_tickets = _filter_ticket_pool(retrieval_tickets, exclude_ids=normalized_exclude_ids)

    grounded_issue_bundle = grounded_issue_matches(
        normalized,
        issue_matches,
        top_k=max(1, top_k * 2),
        excluded_jira_keys=excluded_jira_keys,
    )
    issue_matches = list(grounded_issue_bundle.get("matches") or [])
    issue_evidence_conflict = bool(grounded_issue_bundle.get("evidence_conflict_flag"))

    ticket_by_jira: dict[str, Ticket] = {}
    ticket_by_id: dict[str, Ticket] = {}
    for ticket in retrieval_tickets:
        ticket_by_id[str(ticket.id)] = ticket
        key = str(getattr(ticket, "jira_key", None) or "").strip()
        if key:
            ticket_by_jira[key] = ticket
    ticket_by_jira, ticket_by_id = _fetch_tickets_for_issue_matches(
        db,
        issue_matches=issue_matches,
        ticket_by_jira=ticket_by_jira,
        ticket_by_id=ticket_by_id,
    )
    if normalized_exclude_ids or excluded_jira_keys:
        ticket_by_jira = {
            key: ticket
            for key, ticket in ticket_by_jira.items()
            if _normalize_jira_key(key) not in excluded_jira_keys
            and _normalize_ticket_id(getattr(ticket, "id", None)) not in normalized_exclude_ids
        }
        ticket_by_id = {
            key: ticket
            for key, ticket in ticket_by_id.items()
            if _normalize_ticket_id(key) not in normalized_exclude_ids
            and _normalize_jira_key(getattr(ticket, "jira_key", None)) not in excluded_jira_keys
        }

    semantic_tickets: list[dict[str, Any]] = []
    for match in issue_matches:
        metadata = match.get("metadata") or {}
        jira_key = str(match.get("jira_key") or metadata.get("jira_key") or "").strip()
        ticket_id = str(metadata.get("ticket_id") or "").strip()
        if _normalize_ticket_id(ticket_id) in normalized_exclude_ids or _normalize_jira_key(jira_key) in excluded_jira_keys:
            continue
        ticket = ticket_by_jira.get(jira_key) or ticket_by_id.get(ticket_id)
        if not ticket:
            continue
        metrics = _context_metrics(
            query_context,
            candidate_text=" ".join(
                part
                for part in [
                    str(match.get("content") or ""),
                    str(metadata.get("summary") or metadata.get("title") or ""),
                    _normalize_text(ticket.title),
                    _normalize_text(ticket.description),
                    _normalize_text(ticket.resolution),
                ]
                if part
            ),
            candidate_title=str(metadata.get("summary") or metadata.get("title") or ticket.title or ""),
            category_hint=getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)),
        )
        semantic_score = float(match.get("score") or 0.0)
        if not _passes_context_gate(metrics, semantic_score):
            continue
        semantic_tickets.append(
            _ticket_from_visible_pool(
                ticket,
                score=(
                    RETRIEVAL_ISSUE_MATCH_BLEND["semantic_weight"] * semantic_score
                    + RETRIEVAL_ISSUE_MATCH_BLEND["context_weight"] * float(metrics.get("context_score") or 0.0)
                    + _ticket_outcome_score(ticket)
                ),
                source="semantic_issue",
                context_metrics=metrics,
            )
        )

    lexical_tickets = _local_ticket_matches(
        normalized,
        retrieval_tickets,
        query_context=query_context,
        limit=max(10, top_k * 3),
    )
    semantic_local_tickets: list[dict[str, Any]] = []
    if enable_local_semantic:
        semantic_local_tickets = _local_ticket_semantic_matches(
            normalized,
            retrieval_tickets,
            query_context=query_context,
            lexical_seed=lexical_tickets,
            limit=max(5, top_k * 2),
            query_embedding=query_embedding,
        )
    similar_tickets = _merge_ticket_rows([*semantic_tickets, *semantic_local_tickets, *lexical_tickets], limit=top_k)
    if normalized_exclude_ids or excluded_jira_keys:
        similar_tickets = [
            row for row in similar_tickets
            if not _row_is_excluded(row, exclude_ids=normalized_exclude_ids, excluded_jira_keys=excluded_jira_keys)
        ]

    problem_ids = [str(row.get("problem_id") or "").strip() for row in similar_tickets if row.get("problem_id")]
    related_problems = _search_related_problems(
        db,
        query=normalized,
        query_context=query_context,
        seed_problem_ids=problem_ids,
        top_k=top_k,
    )

    kb_articles: list[dict[str, Any]] = []
    for idx, match in enumerate(issue_matches[:top_k], start=1):
        metadata = match.get("metadata") or {}
        metrics = dict(match.get("metrics") or {})
        jira_key = _normalize_jira_key(match.get("jira_key") or metadata.get("jira_key"))
        if jira_key and jira_key in excluded_jira_keys:
            continue
        title = (
            str(match.get("title") or "").strip()
            or str(metadata.get("summary") or "").strip()
            or str(metadata.get("title") or "").strip()
            or str(match.get("jira_key") or "").strip()
            or f"KB Match {idx}"
        )
        semantic_score = float(match.get("score") or 0.0)
        kb_articles.append(
            {
                "id": str(match.get("jira_key") or metadata.get("jira_key") or f"kb-{idx}"),
                "jira_key": str(match.get("jira_key") or metadata.get("jira_key") or f"kb-{idx}"),
                "title": title,
                "excerpt": _truncate(str(match.get("content") or "")),
                "similarity_score": round(
                    max(
                        0.0,
                        min(
                            1.0,
                            (RETRIEVAL_KB_ARTICLE_BLEND["semantic_weight"] * semantic_score)
                            + (RETRIEVAL_KB_ARTICLE_BLEND["context_weight"] * float(metrics.get("context_score") or 0.0)),
                        ),
                    ),
                    4,
                ),
                "source_type": str(match.get("source_type") or "kb"),
                "context_score": float(metrics.get("context_score") or 0.0),
                "lexical_overlap": float(metrics.get("lexical_overlap") or 0.0),
                "title_overlap": float(metrics.get("title_overlap") or 0.0),
                "strong_overlap": float(metrics.get("strong_overlap") or 0.0),
                "topic_overlap": float(metrics.get("topic_overlap") or 0.0),
                "topic_mismatch": bool(metrics.get("topic_mismatch")),
                "domain_mismatch": bool(metrics.get("domain_mismatch")),
            }
        )

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
        _safe_rollback(db)
        feedback_by_source_id = {}

    solution_recommendations: list[dict[str, Any]] = []
    for match in comment_matches:
        jira_key = str(match.get("jira_key") or "").strip()
        content = str(match.get("content") or "").strip()
        if not jira_key or not content:
            continue
        if _normalize_jira_key(jira_key) in excluded_jira_keys:
            continue
        metrics = _context_metrics(
            query_context,
            candidate_text=content,
            candidate_title=jira_key,
        )
        semantic_score = float(match.get("score") or 0.0)
        if not _passes_context_gate(metrics, semantic_score):
            continue
        quality_score = _comment_quality_score(content)
        if quality_score < quality_threshold:
            continue
        linked_ticket = ticket_by_jira.get(jira_key)
        if linked_ticket is not None and _normalize_ticket_id(getattr(linked_ticket, "id", None)) in normalized_exclude_ids:
            continue
        outcome_bonus = _ticket_outcome_score(linked_ticket)
        feedback_counts = feedback_by_source_id.get(jira_key, {"helpful": 0, "not_helpful": 0})
        helpful_votes = int(feedback_counts.get("helpful", 0))
        not_helpful_votes = int(feedback_counts.get("not_helpful", 0))
        vote_total = helpful_votes + not_helpful_votes
        feedback_signal = ((helpful_votes - not_helpful_votes) / vote_total) if vote_total > 0 else 0.0
        feedback_bonus = max(
            -RETRIEVAL_FEEDBACK_BONUS["cap"],
            min(RETRIEVAL_FEEDBACK_BONUS["cap"], feedback_signal * RETRIEVAL_FEEDBACK_BONUS["multiplier"]),
        )
        confidence_score = max(
            0.0,
            min(
                1.0,
                (RETRIEVAL_SOLUTION_SCORE_WEIGHTS["semantic_weight"] * semantic_score)
                + (RETRIEVAL_SOLUTION_SCORE_WEIGHTS["quality_weight"] * quality_score)
                + (RETRIEVAL_SOLUTION_SCORE_WEIGHTS["context_weight"] * float(metrics.get("context_score") or 0.0))
                + outcome_bonus
                + feedback_bonus,
            ),
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
                "context_score": float(metrics.get("context_score") or 0.0),
                "lexical_overlap": float(metrics.get("lexical_overlap") or 0.0),
                "title_overlap": float(metrics.get("title_overlap") or 0.0),
                "strong_overlap": float(metrics.get("strong_overlap") or 0.0),
                "topic_overlap": float(metrics.get("topic_overlap") or 0.0),
                "topic_mismatch": bool(metrics.get("topic_mismatch")),
                "domain_mismatch": bool(metrics.get("domain_mismatch")),
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
    if normalized_exclude_ids or excluded_jira_keys:
        kb_articles = [
            row for row in kb_articles
            if not _row_is_excluded(row, exclude_ids=normalized_exclude_ids, excluded_jira_keys=excluded_jira_keys)
        ]
        solution_recommendations = [
            row for row in solution_recommendations
            if not _row_is_excluded(row, exclude_ids=normalized_exclude_ids, excluded_jira_keys=excluded_jira_keys)
        ]

    comment_jira_keys = {
        _normalize_jira_key(row.get("jira_key"))
        for row in kb_articles
        if _normalize_jira_key(row.get("jira_key"))
    }.union(
        {
            _normalize_jira_key(row.get("source_id"))
            for row in solution_recommendations
            if _normalize_jira_key(row.get("source_id"))
        }
    )
    comment_rows = list_comments_for_jira_keys(db, sorted(comment_jira_keys), limit_per_issue=2) if comment_jira_keys else []
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

    scores = [float(row.get("similarity_score") or 0.0) for row in [*kb_articles[:2], *solution_recommendations[:2]]]
    if similar_tickets:
        scores.extend(float(row.get("similarity_score") or 0.0) for row in similar_tickets[:2])
    if semantic_local_tickets:
        scores.extend(float(row.get("similarity_score") or 0.0) for row in semantic_local_tickets[:2])
    raw_confidence = max(scores) if scores else 0.0
    raw_confidence = max(0.0, min(1.0, float(raw_confidence)))
    confidence, consensus_confidence, evidence_clusters, evidence_conflict_flag = _retrieval_consensus(
        query_context,
        kb_articles=kb_articles[:top_k],
        similar_tickets=similar_tickets[:top_k],
        solution_recommendations=solution_recommendations[:top_k],
        related_problems=related_problems[:top_k],
        raw_confidence=raw_confidence,
    )
    if issue_evidence_conflict:
        evidence_conflict_flag = True
        confidence = min(confidence, _QUALITY_THRESHOLDS["low"])
        evidence_clusters = {
            **dict(evidence_clusters or {}),
            "issue_match_conflict": True,
        }

    has_jira_semantic = bool(kb_articles or solution_recommendations)
    has_local_semantic = any(str(row.get("source") or "").strip() == "local_semantic" for row in similar_tickets)
    has_local_lexical = any(str(row.get("source") or "").strip() == "local_lexical" for row in similar_tickets)
    if not kb_available:
        source = "kb_empty"
    elif has_jira_semantic and (has_local_semantic or has_local_lexical):
        source = "hybrid_jira_local"
    elif has_jira_semantic:
        source = "jira_semantic"
    elif has_local_semantic:
        source = "local_semantic"
    elif has_local_lexical:
        source = "local_lexical"
    else:
        source = "fallback_rules"

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)

    logger.info(
        "Retrieval complete: source=%s kb_hits=%s local_ticket_hits=%s comment_hits=%s problems=%s elapsed_ms=%s",
        source,
        len(kb_articles[:top_k]),
        len(similar_tickets[:top_k]),
        len(comment_rows[:top_k]),
        len(related_problems[:top_k]),
        elapsed_ms,
    )
    logger.debug(
        "Retrieval confidence=%.4f raw_confidence=%.4f consensus_confidence=%.4f conflict=%s kb_available=%s semantic_issue_hits=%s semantic_comment_hits=%s",
        round(confidence, 4),
        round(raw_confidence, 4),
        round(consensus_confidence, 4),
        evidence_conflict_flag,
        kb_available,
        len(issue_matches),
        len(comment_matches),
    )

    return RetrievalResult(
        query=normalized,
        query_context=query_context,
        kb_articles=kb_articles,
        similar_tickets=similar_tickets[: max(1, top_k)],
        related_problems=related_problems[:3],
        suggested_solutions=suggested_solutions[:3],
        comment_matches=comment_rows,
        solution_recommendations=solution_recommendations[:3],
        confidence=round(confidence, 4),
        consensus_confidence=round(consensus_confidence, 4),
        evidence_conflict_flag=evidence_conflict_flag,
        evidence_clusters=evidence_clusters,
        source=source,
        source_breakdown={
            "kb_status": "ready" if kb_available else "empty",
            "jira_semantic_hits": len(issue_matches) + len(comment_matches),
            "local_semantic_hits": sum(1 for row in similar_tickets if str(row.get("source") or "") == "local_semantic"),
            "local_lexical_hits": sum(1 for row in similar_tickets if str(row.get("source") or "") == "local_lexical"),
            "raw_confidence": round(raw_confidence, 4),
            "consensus_confidence": round(consensus_confidence, 4),
            "evidence_conflict_flag": evidence_conflict_flag,
        },
        excluded_ids=sorted(normalized_exclude_ids),
    )
