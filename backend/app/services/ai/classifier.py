"""Ticket classification service with LLM + rule fallback."""

from __future__ import annotations

from collections import Counter
import logging
import re
from typing import Any

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.enums import TicketCategory, TicketPriority
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_classification_prompt
from app.services.embeddings import list_comments_for_jira_keys, search_kb, search_kb_issues

logger = logging.getLogger(__name__)

EMAIL_KEYWORDS = (
    "smtp",
    "email",
    "e-mail",
    "mailbox",
    "mailing",
    "mail ",
    " outbox",
    "inbox",
    "outlook",
    "gmail",
    "exchange",
    "distribution list",
    "liste de diffusion",
    "messagerie",
    "courriel",
)
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_GROUNDING_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "this",
    "that",
    "then",
    "after",
    "before",
    "les",
    "des",
    "pour",
    "avec",
    "dans",
    "une",
    "sur",
    "ticket",
    "incident",
    "issue",
    "support",
    "system",
    "service",
    "please",
    "check",
    "verify",
    "action",
    "comment",
    "solution",
    "probleme",
}
_INTRO_PATTERNS = (
    "voici ",
    "here are ",
    "recommended actions",
    "actions concretes",
    "actions:",
    "solutions recommandees",
    "recommended solutions",
    "solution rapide",
)


def _normalize_recommendation_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _is_actionable_recommendation(text: str) -> bool:
    normalized = _normalize_recommendation_text(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    if lowered in {"-", "*"}:
        return False
    if lowered.endswith(":"):
        return False
    return not any(lowered.startswith(pattern) for pattern in _INTRO_PATTERNS)


def _looks_like_email_issue(title: str, description: str) -> bool:
    text = f" {title} {description} ".casefold()
    return any(keyword in text for keyword in EMAIL_KEYWORDS)


def apply_category_guardrail(title: str, description: str, category: TicketCategory) -> TicketCategory:
    if category != TicketCategory.email and _looks_like_email_issue(title, description):
        return TicketCategory.email
    return category


def _normalize_recommendations(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _normalize_recommendation_text(item)
        if not text or not _is_actionable_recommendation(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    return cleaned[:max_items]


def _truncate_text(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _text_tokens(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {token for token in tokens if token not in _GROUNDING_STOPWORDS}


def _match_metadata(match: dict[str, Any]) -> dict[str, Any]:
    metadata = match.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _normalize_priority_name(value: str | None) -> str:
    return _SPACE_RE.sub(" ", (value or "").strip().lower())


def _normalize_category_name(value: str | None) -> str:
    return _SPACE_RE.sub(" ", (value or "").strip().lower())


def _priority_from_match(metadata: dict[str, Any]) -> TicketPriority | None:
    value = _normalize_priority_name(str(metadata.get("priority") or ""))
    if not value:
        return None
    if value in {"highest", "critical"}:
        return TicketPriority.critical
    if value == "high":
        return TicketPriority.high
    if value == "medium":
        return TicketPriority.medium
    if value in {"low", "lowest"}:
        return TicketPriority.low
    return None


def _category_from_match(metadata: dict[str, Any]) -> TicketCategory | None:
    issue_type = _normalize_category_name(str(metadata.get("issuetype") or ""))
    components = _normalize_category_name(str(metadata.get("components") or ""))
    labels = _normalize_category_name(str(metadata.get("labels") or ""))
    haystack = f" {issue_type} {components} {labels} "

    if _looks_like_email_issue(issue_type, f"{components} {labels}"):
        return TicketCategory.email
    if any(token in haystack for token in ["security", "vulner", "iam", "mfa", "auth"]):
        return TicketCategory.security
    if any(token in haystack for token in ["network", "vpn", "dns", "firewall", "router", "switch", "wifi", "wi-fi"]):
        return TicketCategory.network
    if any(token in haystack for token in ["infra", "database", "server", "cloud", "kubernetes", "cluster"]):
        return TicketCategory.infrastructure
    if any(token in haystack for token in ["hardware", "laptop", "printer", "peripheral"]):
        return TicketCategory.hardware
    if any(token in haystack for token in ["service request", "request", "access", "permission", "onboarding"]):
        return TicketCategory.service_request
    if any(token in haystack for token in ["problem", "root cause", "rca"]):
        return TicketCategory.problem
    if any(token in haystack for token in ["application", "bug", "frontend", "backend", "api", "software"]):
        return TicketCategory.application
    return None


def _infer_classification_from_strong_matches(
    strong_matches: list[dict[str, Any]],
) -> tuple[TicketPriority | None, TicketCategory | None]:
    if not strong_matches:
        return None, None

    weighted_priority: Counter[TicketPriority] = Counter()
    weighted_category: Counter[TicketCategory] = Counter()
    total_weight = 0.0
    for match in strong_matches:
        score = max(0.0, min(1.0, float(match.get("score") or 0.0)))
        # Keep a minimum vote so near-threshold strong matches still contribute.
        weight = max(0.2, score)
        metadata = _match_metadata(match)
        p = _priority_from_match(metadata)
        c = _category_from_match(metadata)
        if p is not None:
            weighted_priority[p] += weight
        if c is not None:
            weighted_category[c] += weight
        total_weight += weight

    if total_weight <= 0.0:
        return None, None

    inferred_priority: TicketPriority | None = None
    inferred_category: TicketCategory | None = None

    if weighted_priority:
        top_priority, top_priority_weight = weighted_priority.most_common(1)[0]
        if (top_priority_weight / total_weight) >= 0.52:
            inferred_priority = top_priority

    if weighted_category:
        top_category, top_category_weight = weighted_category.most_common(1)[0]
        if (top_category_weight / total_weight) >= 0.52:
            inferred_category = top_category

    return inferred_priority, inferred_category


def _load_strong_similarity_matches(title: str, description: str) -> list[dict[str, Any]]:
    query = _normalize_recommendation_text(f"{title}\n{description}")
    if not query:
        return []

    threshold = max(0.0, min(1.0, float(settings.AI_CLASSIFY_STRONG_SIMILARITY_THRESHOLD)))
    top_k = max(1, int(settings.AI_CLASSIFY_SEMANTIC_TOP_K))
    db = SessionLocal()
    try:
        matches = search_kb_issues(db, query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        logger.info("Semantic retrieval unavailable during classify: %s", exc)
        return []
    finally:
        db.close()

    seen_keys: set[str] = set()
    strong: list[dict[str, Any]] = []
    for match in matches:
        try:
            score = float(match.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        jira_key = str(match.get("jira_key") or "").strip()
        if score < threshold or not jira_key or jira_key in seen_keys:
            continue
        seen_keys.add(jira_key)
        strong.append(
            {
                "score": score,
                "distance": float(match.get("distance") or 1.0),
                "jira_key": jira_key,
                "jira_issue_id": str(match.get("jira_issue_id") or "").strip() or None,
                "content": str(match.get("content") or ""),
                "metadata": _match_metadata(match),
            }
        )
    return strong[:top_k]


def _merge_comment_matches(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in [*primary, *secondary]:
        jira_key = str(match.get("jira_key") or "").strip()
        comment_id = str(match.get("comment_id") or "").strip()
        content_key = _normalize_recommendation_text(str(match.get("content") or ""))[:200]
        key = f"{jira_key}|{comment_id}|{content_key}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(match)
        if len(merged) >= limit:
            break
    return merged


def _load_related_comment_matches(query: str, issue_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not issue_matches:
        return []
    jira_keys = [str(match.get("jira_key") or "").strip() for match in issue_matches if str(match.get("jira_key") or "").strip()]
    if not jira_keys:
        return []

    top_k = max(1, int(settings.AI_CLASSIFY_SEMANTIC_TOP_K))
    per_issue_limit = max(1, int(settings.JIRA_KB_MAX_COMMENTS_PER_ISSUE))
    max_comments = max(top_k * per_issue_limit, per_issue_limit)
    db = SessionLocal()
    try:
        semantic = search_kb(
            db,
            query,
            top_k=max_comments,
            source_type="jira_comment",
            jira_keys=jira_keys,
        )
        recent = list_comments_for_jira_keys(db, jira_keys, limit_per_issue=per_issue_limit)
    except Exception as exc:  # noqa: BLE001
        logger.info("Issue-comment retrieval unavailable during classify: %s", exc)
        return []
    finally:
        db.close()

    return _merge_comment_matches(semantic, recent, limit=max_comments)


def _strong_matches_knowledge_section(
    issue_matches: list[dict[str, Any]],
    comment_matches: list[dict[str, Any]],
) -> str:
    if not issue_matches:
        return ""

    lines = ["Issues Jira a forte similarite (base prioritaire pour classification):"]
    for match in issue_matches:
        meta = _match_metadata(match)
        jira_key = str(match.get("jira_key") or "-")
        summary = _normalize_recommendation_text(str(meta.get("summary") or ""))
        if not summary:
            summary = _truncate_text(_normalize_recommendation_text(str(match.get("content") or "")), limit=180)
        priority = str(meta.get("priority") or "-").strip() or "-"
        status = str(meta.get("status") or "-").strip() or "-"
        issuetype = str(meta.get("issuetype") or "-").strip() or "-"
        components = str(meta.get("components") or "-").strip() or "-"
        labels = str(meta.get("labels") or "-").strip() or "-"
        score = float(match.get("score") or 0.0)
        lines.append(
            f"- [{jira_key}] score={score:.2f} resume={_truncate_text(summary, limit=160)} "
            f"({priority} | {status} | type={issuetype} | composants={components} | labels={labels})"
        )

    if comment_matches:
        lines.append("")
        lines.append("Commentaires pertinents provenant de ces issues (base obligatoire des recommandations):")
        prompt_comment_limit = max(4, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS) * 3)
        for match in comment_matches[:prompt_comment_limit]:
            meta = _match_metadata(match)
            jira_key = str(match.get("jira_key") or "-")
            content = _normalize_recommendation_text(str(match.get("content") or ""))
            if not content:
                continue
            score = float(match.get("score") or 0.0)
            author = str(meta.get("author") or "Unknown").strip() or "Unknown"
            lines.append(
                f"- [{jira_key}] score={score:.2f} commentaire={_truncate_text(content, limit=220)} "
                f"(auteur={author})"
            )

    if len(lines) <= 1:
        return ""
    return "\n".join(lines) + "\n\n"


def _recommendations_from_matches(matches: list[dict[str, Any]]) -> list[str]:
    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    recommendations: list[str] = []
    seen: set[str] = set()
    for match in matches:
        content = _normalize_recommendation_text(str(match.get("content") or ""))
        if not content:
            continue
        fragments = re.split(r"(?<=[\.\!\?;])\s+", content)
        if not fragments:
            fragments = [content]
        for fragment in fragments:
            text = _normalize_recommendation_text(fragment)
            if len(text) < 20 or not _is_actionable_recommendation(text):
                continue
            normalized = _truncate_text(text, limit=220)
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            recommendations.append(normalized)
            if len(recommendations) >= max_items:
                return recommendations
    return recommendations


def _filter_grounded_recommendations(
    recommendations: list[str],
    matches: list[dict[str, Any]],
) -> list[str]:
    comment_tokens: set[str] = set()
    for match in matches:
        comment_tokens.update(_text_tokens(str(match.get("content") or "")))
    if not comment_tokens:
        return []

    grounded: list[str] = []
    for recommendation in recommendations:
        if not _is_actionable_recommendation(recommendation):
            continue
        rec_tokens = _text_tokens(recommendation)
        if rec_tokens.intersection(comment_tokens):
            grounded.append(recommendation)
    return grounded


def _generate_llm_basic_recommendations(title: str, description: str) -> list[str]:
    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    prompt_json = (
        "Tu es un assistant support IT. Reponds uniquement en JSON valide.\n"
        "Schema: {\"recommendations\": [\"action 1\", \"action 2\", \"action 3\"]}\n"
        "Donne 2 a 4 actions concretes, non generiques, basees sur une connaissance IT generale.\n"
        f"Titre: {title}\n"
        f"Description: {description}\n"
    )
    try:
        reply = ollama_generate(prompt_json, json_mode=True)
        data = extract_json(reply) or {}
        recommendations = _normalize_recommendations(data.get("recommendations"))[:max_items]
        if recommendations:
            return recommendations
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM basic recommendation JSON mode failed: %s", exc)

    prompt_text = (
        "Tu es un assistant support IT.\n"
        "Donne exactement 3 actions concretes, une par ligne, sans JSON.\n"
        f"Titre: {title}\n"
        f"Description: {description}\n"
    )
    try:
        reply_text = ollama_generate(prompt_text, json_mode=False)
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM basic recommendation text mode failed: %s", exc)
        return []

    lines: list[str] = []
    for raw_line in str(reply_text).splitlines():
        cleaned = raw_line.strip().lstrip("-*0123456789. ").strip()
        if cleaned:
            lines.append(cleaned)
    return _normalize_recommendations(lines)[:max_items]


def _resolve_recommendation_mode(
    *,
    strong_matches: list[dict[str, Any]],
    embedding_recommendations: list[str],
    llm_recommendations: list[str],
) -> str:
    if strong_matches:
        if embedding_recommendations and llm_recommendations:
            return "hybrid"
        if embedding_recommendations:
            return "embedding"
        if llm_recommendations:
            return "llm"
        return "embedding"
    return "llm"


def _compute_classification_confidence(
    *,
    strong_matches: list[dict[str, Any]],
    inferred_priority: TicketPriority | None,
    inferred_category: TicketCategory | None,
    recommendation_mode: str,
    has_recommendations: bool,
    llm_success: bool,
) -> int:
    score = 62
    if llm_success:
        score += 8
    if strong_matches:
        score += 12
    if inferred_priority is not None:
        score += 5
    if inferred_category is not None:
        score += 5
    if recommendation_mode == "hybrid":
        score += 4
    elif recommendation_mode == "embedding":
        score += 2
    if not has_recommendations:
        score -= 6
    return int(max(45, min(97, score)))


def classify_ticket_detailed(title: str, description: str) -> dict[str, Any]:
    description = description or title
    query = _normalize_recommendation_text(f"{title}\n{description}")
    strong_matches = _load_strong_similarity_matches(title, description)
    inferred_priority, inferred_category = _infer_classification_from_strong_matches(strong_matches)
    related_comment_matches = _load_related_comment_matches(query, strong_matches) if strong_matches else []
    embedding_recommendations = _recommendations_from_matches(related_comment_matches) if strong_matches else []
    knowledge_section = _strong_matches_knowledge_section(strong_matches, related_comment_matches)
    prompt = build_classification_prompt(
        title=title,
        description=description,
        knowledge_section=knowledge_section,
        recommendations_mode="comments_strong" if strong_matches else "llm_general",
    )
    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    llm_recommendations: list[str] = []
    final_recommendations: list[str] = []

    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if not data:
            raise ValueError("invalid_json")
        priority = TicketPriority(data["priority"])
        category = TicketCategory(data["category"])
        category = apply_category_guardrail(title, description, category)
        if inferred_priority is not None:
            priority = inferred_priority
        if inferred_category is not None:
            category = apply_category_guardrail(title, description, inferred_category)

        llm_recommendations = _normalize_recommendations(data.get("recommendations"))
        if strong_matches:
            grounded = _filter_grounded_recommendations(llm_recommendations, related_comment_matches)
            final_recommendations = grounded if grounded else embedding_recommendations
        else:
            final_recommendations = llm_recommendations

        if not final_recommendations and not strong_matches:
            llm_recommendations = _generate_llm_basic_recommendations(title, description)
            final_recommendations = llm_recommendations

        recommendation_mode = _resolve_recommendation_mode(
            strong_matches=strong_matches,
            embedding_recommendations=embedding_recommendations,
            llm_recommendations=llm_recommendations,
        )
        return {
            "priority": priority,
            "category": category,
            "recommendations": final_recommendations[:max_items],
            "recommendations_embedding": embedding_recommendations[:max_items],
            "recommendations_llm": llm_recommendations[:max_items],
            "recommendation_mode": recommendation_mode,
            "similarity_found": bool(strong_matches),
            "classification_confidence": _compute_classification_confidence(
                strong_matches=strong_matches,
                inferred_priority=inferred_priority,
                inferred_category=inferred_category,
                recommendation_mode=recommendation_mode,
                has_recommendations=bool(final_recommendations),
                llm_success=True,
            ),
        }
    except Exception as exc:
        logger.warning("Ollama classify failed, using fallback: %s", exc)
        priority, category = _rule_based_classify(title, description)
        if inferred_priority is not None:
            priority = inferred_priority
        if inferred_category is not None:
            category = inferred_category
        category = apply_category_guardrail(title, description, category)
        if strong_matches and not embedding_recommendations:
            embedding_recommendations = _recommendations_from_matches(related_comment_matches)
        if not llm_recommendations and not strong_matches:
            llm_recommendations = _generate_llm_basic_recommendations(title, description)
        final_recommendations = embedding_recommendations or llm_recommendations
        recommendation_mode = _resolve_recommendation_mode(
            strong_matches=strong_matches,
            embedding_recommendations=embedding_recommendations,
            llm_recommendations=llm_recommendations,
        )
        return {
            "priority": priority,
            "category": category,
            "recommendations": final_recommendations[:max_items],
            "recommendations_embedding": embedding_recommendations[:max_items],
            "recommendations_llm": llm_recommendations[:max_items],
            "recommendation_mode": recommendation_mode,
            "similarity_found": bool(strong_matches),
            "classification_confidence": _compute_classification_confidence(
                strong_matches=strong_matches,
                inferred_priority=inferred_priority,
                inferred_category=inferred_category,
                recommendation_mode=recommendation_mode,
                has_recommendations=bool(final_recommendations),
                llm_success=False,
            ),
        }


def score_recommendations(
    recommendations: list[str],
    *,
    start_confidence: int = 86,
    rank_decay: int = 7,
    floor: int = 55,
    ceiling: int = 95,
) -> list[dict[str, object]]:
    """Build short confidence scores for recommendation strings."""
    scored: list[dict[str, object]] = []
    seen: set[str] = set()
    action_tokens = {"verify", "check", "collect", "apply", "rollback", "document", "monitor", "logs", "review"}

    for index, raw in enumerate(recommendations):
        text = _normalize_recommendation_text(raw)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)

        text_len = len(text)
        confidence = start_confidence - (index * rank_decay)
        if 45 <= text_len <= 210:
            confidence += 2
        lowered = text.casefold()
        if any(token in lowered for token in action_tokens):
            confidence += 2
        confidence = max(floor, min(ceiling, confidence))
        scored.append({"text": text, "confidence": int(confidence)})

    return scored


def _rule_based_classify(title: str, description: str) -> tuple[TicketPriority, TicketCategory]:
    text = f"{title} {description}".lower()
    if any(k in text for k in ["xss", "vulnerabil", "secur", "auth", "sso"]):
        priority = TicketPriority.critical
        category = TicketCategory.security
    elif _looks_like_email_issue(title, description):
        priority = TicketPriority.high
        category = TicketCategory.email
    elif any(k in text for k in ["performance", "lent", "optimisation", "cache"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(k in text for k in ["migration", "postgres", "database", "server", "cloud", "aws", "azure", "vm", "virtualisation", "virtualization"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(
        k in text
        for k in [
            "network",
            "reseau",
            "wifi",
            "wi-fi",
            "vpn",
            "dns",
            "dhcp",
            "ip address",
            "adresse ip",
            "latency",
            "latence",
            "packet loss",
            "perte de paquets",
            "router",
            "switch",
            "firewall",
            "proxy",
        ]
    ):
        priority = TicketPriority.high
        category = TicketCategory.network
    elif any(k in text for k in ["laptop", "ordinateur", "printer", "imprim", "keyboard", "mouse", "peripheral", "ecran", "monitor"]):
        priority = TicketPriority.medium
        category = TicketCategory.hardware
    elif any(k in text for k in ["access", "permission", "onboard", "account", "install", "demande", "request", "support", "helpdesk"]):
        priority = TicketPriority.medium
        category = TicketCategory.service_request
    elif any(k in text for k in ["report", "dashboard", "export", "pdf", "excel", "bug", "feature", "error", "crash", "api", "frontend", "backend"]):
        priority = TicketPriority.medium
        category = TicketCategory.application
    else:
        priority = TicketPriority.medium
        category = TicketCategory.service_request

    return priority, category


def classify_ticket(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
    data = classify_ticket_detailed(title, description)
    return data["priority"], data["category"], data["recommendations"]
