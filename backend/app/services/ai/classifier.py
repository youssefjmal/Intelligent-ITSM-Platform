"""Ticket classification service with LLM + rule fallback."""

from __future__ import annotations

from collections import Counter
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ai_classification_log import AiClassificationLog
from app.models.enums import TicketCategory, TicketPriority, TicketType
from app.schemas.ai import UnknownTicketType
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_classification_prompt
from app.services.ai.retrieval import _query_context as retrieval_query_context, grounded_issue_matches
from app.services.ai.service_requests import build_service_request_profile, has_explicit_fulfillment_intent
from app.services.ai.taxonomy import CATEGORY_HINTS as _CATEGORY_HINTS
from app.services.embeddings import list_comments_for_jira_keys, search_kb, search_kb_issues

logger = logging.getLogger(__name__)


def _log_classification(
    *,
    title: str,
    description: str,
    trigger: str,
    ticket_id: str | None,
    suggested_priority: str | None,
    suggested_category: str | None,
    suggested_ticket_type: str | None,
    confidence: float | None,
    confidence_band: str | None,
    decision_source: str,
    strong_match_count: int | None,
    recommendation_mode: str | None,
    reasoning: str,
) -> None:
    """Persist one AI classification decision to the audit log. Never raises."""
    try:
        with SessionLocal() as _db:
            record = AiClassificationLog(
                ticket_id=ticket_id,
                trigger=trigger,
                title=(title or "")[:500],
                description_snippet=(description or "")[:300],
                suggested_priority=suggested_priority,
                suggested_category=suggested_category,
                suggested_ticket_type=suggested_ticket_type,
                confidence=confidence,
                confidence_band=confidence_band,
                decision_source=decision_source,
                strong_match_count=strong_match_count,
                recommendation_mode=recommendation_mode,
                reasoning=(reasoning or "")[:1000],
                model_version=str(settings.OLLAMA_MODEL),
            )
            _db.add(record)
            _db.commit()
    except Exception:  # noqa: BLE001
        logger.debug("AI classification audit log write failed.", exc_info=True)


def _safe_rollback(db: Session | None) -> None:
    if db is None:
        return
    rollback = getattr(db, "rollback", None)
    if not callable(rollback):
        return
    try:
        rollback()
    except Exception:  # noqa: BLE001
        logger.debug("Classifier rollback cleanup failed.", exc_info=True)

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
_TYPE_SIGNAL_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)
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
_TECHNICAL_SIGNAL_KEYWORDS = {
    "error",
    "failed",
    "failure",
    "exception",
    "timeout",
    "timed out",
    "latency",
    "packet loss",
    "disconnect",
    "unreachable",
    "denied",
    "refused",
    "cpu",
    "memory",
    "disk",
    "oom",
    "tls",
    "ssl",
    "certificate",
    "token",
    "config",
    "configuration",
    "deploy",
    "release",
    "rollback",
    "firewall",
    "port",
    "dns",
    "vpn",
    "http",
    "5xx",
    "4xx",
}
_METRIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds|m|min|minutes|%|mb|gb|kbps|mbps)\b", re.IGNORECASE)
_HTTP_CODE_PATTERN = re.compile(r"\b(?:http\s*)?(?:4\d{2}|5\d{2})\b", re.IGNORECASE)
_GENERIC_RECOMMENDATION_PATTERNS = (
    "follow best practices",
    "contact support",
    "investigate the issue",
    "check the system",
    "monitor the system",
    "verify the configuration",
    "review the logs",
    "check logs",
    "ensure proper configuration",
)
_PRIORITY_TOKEN_RE = re.compile(r"\b(critical|high|medium|low)\b", re.IGNORECASE)
_TICKET_TYPE_TOKEN_RE = re.compile(r"\b(incident|service[_\s-]?request)\b", re.IGNORECASE)
_CATEGORY_TOKEN_RE = re.compile(
    r"\b(infrastructure|network|security|application|service[_\s-]?request|hardware|email|problem)\b",
    re.IGNORECASE,
)
_LEGACY_REQUEST_TYPE_SIGNAL_KEYWORDS = (
    # Multi-word phrases are unambiguous — keep as-is
    "need access",
    "access request",
    "new account",
    "create account",
    "request new",
    "onboard",
    "onboarding",
    # "permission" alone fires on "permission denied" (an incident); require a
    # request context word adjacent to it
    "permission request",
    "request permission",
    "grant permission",
    "grant access",
    "demande d'accès",
    "demande de",
    # install / setup are low-ambiguity in ITSM context
    "install",
    "installation",
    "setup",
    "configure",
    # "request" and "enable" are too broad — they appear in incident descriptions
    # ("the API request failed", "unable to enable") and would silently win over
    # incident signals.  Removed.
)
_LEGACY_INCIDENT_TYPE_SIGNAL_KEYWORDS = (
    "incident",
    "outage",
    "down",
    "failure",
    "failed",
    "broken",
    "problem",
    "issue",
    "error",
    "cannot",
    "can't",
    "unable",
    "latency",
    "timeout",
    "degraded",
    "crash",
    # Authorization / HTTP error states — clearly broken, not a request
    "denied",
    "forbidden",
    "unauthorized",
    "not responding",
    "returns error",
    "returning error",
)
REQUEST_TYPE_SIGNAL_WEIGHTS: dict[str, float] = {
    "need access": 1.8,
    "access request": 1.9,
    "new account": 1.8,
    "create account": 1.7,
    "request new": 1.4,
    "onboard": 1.5,
    "onboarding": 1.7,
    "permission request": 1.9,
    "request permission": 1.9,
    "grant permission": 1.8,
    "grant access": 1.8,
    "demande d'acces": 1.8,
    "demande de": 0.8,
    "install": 0.7,
    "installation": 0.9,
    "setup": 0.7,
    "configure": 0.6,
}
INCIDENT_TYPE_SIGNAL_WEIGHTS: dict[str, float] = {
    "incident": 1.4,
    "outage": 1.9,
    "down": 1.6,
    "failure": 1.6,
    "failed": 1.6,
    "broken": 1.4,
    "problem": 1.1,
    "issue": 1.0,
    "error": 1.5,
    "cannot": 1.4,
    "can't": 1.4,
    "unable": 1.4,
    "latency": 1.2,
    "timeout": 1.4,
    "degraded": 1.4,
    "crash": 1.7,
    "denied": 1.7,
    "forbidden": 1.7,
    "unauthorized": 1.7,
    "not responding": 1.6,
    "returns error": 1.6,
    "returning error": 1.6,
}
REQUEST_TYPE_SIGNAL_KEYWORDS = tuple(REQUEST_TYPE_SIGNAL_WEIGHTS.keys())
INCIDENT_TYPE_SIGNAL_KEYWORDS = tuple(INCIDENT_TYPE_SIGNAL_WEIGHTS.keys())
REQUEST_TYPE_NEGATIVE_SIGNAL_WEIGHTS: dict[str, float] = {
    "failed": 0.9,
    "failure": 0.9,
    "error": 0.9,
    "broken": 0.8,
    "down": 1.0,
    "timeout": 0.8,
    "crash": 1.0,
    "cannot": 0.8,
    "can't": 0.8,
    "unable": 0.8,
    "denied": 1.0,
    "forbidden": 1.0,
    "unauthorized": 1.0,
    "not responding": 1.0,
}
INCIDENT_TYPE_NEGATIVE_SIGNAL_WEIGHTS: dict[str, float] = {
    "access request": 0.4,
    "new account": 0.5,
    "create account": 0.5,
    "permission request": 0.5,
    "grant access": 0.5,
    "onboarding": 0.4,
}
_WEAK_INCIDENT_TYPE_SIGNALS = frozenset({"incident", "issue", "problem"})
TICKET_TYPE_SCORE_THRESHOLD = 0.9
TICKET_TYPE_DECISION_MARGIN = 0.35
SERVICE_REQUEST_CATEGORY_HINT_WEIGHT = 1.0

_SIGNAL_ACTION_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("latency", "packet loss"),
        "Correlate latency/packet-loss windows with gateway interface errors and tunnel renegotiation events.",
    ),
    (
        ("disconnect", "vpn"),
        "Collect VPN session drop reason codes and map them to reconnect timestamps from affected users.",
    ),
    (
        ("timeout", "http", "504", "503"),
        "Trace upstream dependency response times around timeout/error windows and isolate the slow hop.",
    ),
    (
        ("tls", "ssl", "certificate", "token"),
        "Validate certificate/token validity and rotation timeline against the first occurrence of failures.",
    ),
    (
        ("dns", "unreachable", "refused", "denied"),
        "Verify DNS/firewall path for impacted hosts and compare successful vs failed resolution paths.",
    ),
)


def _coerce_priority_value(value: Any) -> TicketPriority | None:
    normalized = _normalize_recommendation_text(str(value or "")).casefold()
    mapping = {
        "critical": TicketPriority.critical,
        "high": TicketPriority.high,
        "medium": TicketPriority.medium,
        "low": TicketPriority.low,
    }
    return mapping.get(normalized)


def _coerce_category_value(value: Any) -> TicketCategory | None:
    normalized = _normalize_recommendation_text(str(value or "")).casefold()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    mapping = {
        "infrastructure": TicketCategory.infrastructure,
        "network": TicketCategory.network,
        "security": TicketCategory.security,
        "application": TicketCategory.application,
        "service_request": TicketCategory.service_request,
        "hardware": TicketCategory.hardware,
        "email": TicketCategory.email,
        "problem": TicketCategory.problem,
    }
    return mapping.get(normalized)


def _coerce_ticket_type_value(value: Any) -> TicketType | None:
    normalized = _normalize_recommendation_text(str(value or "")).casefold()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    mapping = {
        "incident": TicketType.incident,
        "service_request": TicketType.service_request,
    }
    return mapping.get(normalized)


def _recover_classification_payload_from_reply(reply: str) -> dict[str, Any] | None:
    text = str(reply or "").strip()
    if not text:
        return None

    recovered: dict[str, Any] = {}
    priority_match = _PRIORITY_TOKEN_RE.search(text)
    if priority_match:
        recovered["priority"] = str(priority_match.group(1)).lower()

    ticket_type_match = _TICKET_TYPE_TOKEN_RE.search(text)
    if ticket_type_match:
        ticket_type = str(ticket_type_match.group(1)).lower().replace("-", "_").replace(" ", "_")
        recovered["ticket_type"] = ticket_type

    category_match = _CATEGORY_TOKEN_RE.search(text)
    if category_match:
        category = str(category_match.group(1)).lower().replace("-", "_").replace(" ", "_")
        recovered["category"] = category

    technical_signals = _normalize_technical_signals(text)
    if technical_signals:
        recovered["technical_signals"] = technical_signals

    blocked_prefixes = {
        "priority",
        "category",
        "technical_signals",
        "recommendations",
        "sources",
        "notes",
        "confidence",
        "reply",
    }
    recommendation_lines: list[str] = []
    for raw_line in text.splitlines():
        cleaned = raw_line.strip().strip("`")
        cleaned = cleaned.lstrip("-*0123456789. ").strip()
        if not cleaned:
            continue
        if cleaned.startswith("{") or cleaned.startswith("}"):
            continue
        head = cleaned.split(":", 1)[0].strip().casefold()
        if head in blocked_prefixes:
            continue
        recommendation_lines.append(cleaned)

    recommendations = _normalize_recommendations(recommendation_lines)
    if not recommendations:
        fragments = [fragment for fragment in _split_signal_fragments(text) if len(fragment) >= 20]
        recommendations = _normalize_recommendations(fragments)
    if recommendations:
        recovered["recommendations"] = recommendations

    return recovered or None


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


def _split_signal_fragments(text: str) -> list[str]:
    raw = re.split(r"[\n\r\.\!\?;]+", str(text or ""))
    return [_normalize_recommendation_text(item) for item in raw if _normalize_recommendation_text(item)]


def _looks_like_technical_signal(fragment: str) -> bool:
    lowered = fragment.casefold()
    if _METRIC_PATTERN.search(fragment):
        return True
    if _HTTP_CODE_PATTERN.search(fragment):
        return True
    return any(keyword in lowered for keyword in _TECHNICAL_SIGNAL_KEYWORDS)


def _normalize_technical_signals(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = []
    signals: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        for fragment in _split_signal_fragments(entry):
            if len(fragment) < 8 or not _looks_like_technical_signal(fragment):
                continue
            key = fragment.casefold()
            if key in seen:
                continue
            seen.add(key)
            signals.append(_truncate_text(fragment, limit=180))
            if len(signals) >= 8:
                return signals
    return signals


def _extract_technical_signals(
    title: str,
    description: str,
    *,
    issue_matches: list[dict[str, Any]],
    comment_matches: list[dict[str, Any]],
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add_signal(raw: str | None) -> None:
        text = _normalize_recommendation_text(raw)
        if not text:
            return
        for fragment in _split_signal_fragments(text):
            if len(fragment) < 8 or not _looks_like_technical_signal(fragment):
                continue
            key = fragment.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(_truncate_text(fragment, limit=180))
            if len(candidates) >= 8:
                return

    add_signal(title)
    add_signal(description)

    for match in issue_matches[:6]:
        meta = _match_metadata(match)
        add_signal(str(meta.get("summary") or ""))
        add_signal(str(meta.get("description") or ""))
        add_signal(str(meta.get("components") or ""))
        add_signal(str(meta.get("labels") or ""))
        add_signal(str(match.get("content") or ""))
        if len(candidates) >= 8:
            break

    for match in comment_matches[:8]:
        add_signal(str(match.get("content") or ""))
        if len(candidates) >= 8:
            break

    return candidates[:8]


def _is_generic_recommendation(text: str) -> bool:
    lowered = _normalize_recommendation_text(text).casefold()
    if not lowered:
        return True
    if any(pattern in lowered for pattern in _GENERIC_RECOMMENDATION_PATTERNS):
        technical_tokens = _text_tokens(lowered).intersection(_TECHNICAL_SIGNAL_KEYWORDS)
        if not technical_tokens:
            return True
    return False


def _filter_signal_grounded_recommendations(
    recommendations: list[str],
    *,
    technical_signals: list[str],
) -> list[str]:
    signal_tokens: set[str] = set()
    for signal in technical_signals:
        signal_tokens.update(_text_tokens(signal))
    if not signal_tokens:
        return []

    grounded: list[str] = []
    seen: set[str] = set()
    for recommendation in recommendations:
        text = _normalize_recommendation_text(recommendation)
        if not text or not _is_actionable_recommendation(text) or _is_generic_recommendation(text):
            continue
        overlap = _text_tokens(text).intersection(signal_tokens)
        if not overlap:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        grounded.append(text)
    return grounded


def _signal_driven_fallback_recommendations(technical_signals: list[str]) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()
    flattened = " ".join(signal.casefold() for signal in technical_signals)

    for triggers, recommendation in _SIGNAL_ACTION_MAP:
        if any(trigger in flattened for trigger in triggers):
            key = recommendation.casefold()
            if key not in seen:
                seen.add(key)
                recommendations.append(recommendation)

    if not recommendations and technical_signals:
        recommendations.append(
            "Capture exact failing error/symptom timestamps from the ticket signals and correlate with the affected component logs."
        )

    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    return recommendations[:max_items]


def _looks_like_email_issue(title: str, description: str) -> bool:
    text = f" {title} {description} ".casefold()
    return any(keyword in text for keyword in EMAIL_KEYWORDS)


def _category_context_scores(title: str, description: str) -> dict[TicketCategory, float]:
    tokens = _ticket_type_signal_tokens(f"{title} {description}")
    title_tokens = _ticket_type_signal_tokens(title)
    if not tokens:
        return {}

    scores: dict[TicketCategory, float] = {}
    for category_name, hints in _CATEGORY_HINTS.items():
        try:
            category = TicketCategory(category_name)
        except ValueError:
            continue
        score = 0.0
        for phrase in hints:
            phrase_tokens = tuple(_ticket_type_signal_tokens(str(phrase)))
            if not phrase_tokens:
                continue
            if _token_sequence_present(tokens, phrase_tokens):
                weight = 1.0 + (0.2 * max(0, len(phrase_tokens) - 1))
                score += weight
                if _token_sequence_present(title_tokens, phrase_tokens):
                    score += 0.35
        if score > 0.0:
            scores[category] = round(score, 4)
    return scores


def apply_category_guardrail(title: str, description: str, category: TicketCategory) -> TicketCategory:
    scores = _category_context_scores(title, description)
    if not scores:
        return category
    query_context = retrieval_query_context(f"{title}\n{description}")
    negative_categories = {
        TicketCategory(value)
        for value in list(query_context.get("negative_domains") or [])
        if value in {item.value for item in TicketCategory}
    }
    positive_categories = {
        TicketCategory(value)
        for value in list(query_context.get("domains") or [])
        if value in {item.value for item in TicketCategory}
    }
    adjusted_scores = dict(scores)
    for negative_category in negative_categories:
        if negative_category in adjusted_scores:
            adjusted_scores[negative_category] = round(max(0.0, adjusted_scores[negative_category] - 1.25), 4)
    for positive_category in positive_categories:
        if positive_category in adjusted_scores and positive_category != category:
            adjusted_scores[positive_category] = round(adjusted_scores[positive_category] + 0.2, 4)
    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0].value), reverse=True)
    adjusted_ranked = sorted(adjusted_scores.items(), key=lambda item: (item[1], item[0].value), reverse=True)
    dominant_category, dominant_score = adjusted_ranked[0]
    second_score = float(adjusted_ranked[1][1]) if len(adjusted_ranked) > 1 else 0.0
    current_score = float(adjusted_scores.get(category, 0.0))
    if dominant_category == category:
        return category
    if category in negative_categories and dominant_category not in negative_categories:
        if dominant_score >= max(1.0, second_score + 0.15):
            return dominant_category
    if dominant_score >= max(1.0, current_score + 0.6, second_score + 0.6):
        return dominant_category
    return category


def _ticket_type_signal_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TYPE_SIGNAL_TOKEN_RE.findall(text or "")]


def _token_sequence_present(tokens: list[str], phrase_tokens: tuple[str, ...]) -> bool:
    if not phrase_tokens:
        return False
    if len(phrase_tokens) == 1:
        return phrase_tokens[0] in set(tokens)
    max_start = len(tokens) - len(phrase_tokens) + 1
    if max_start <= 0:
        return False
    for start in range(max_start):
        if tuple(tokens[start : start + len(phrase_tokens)]) == phrase_tokens:
            return True
    return False


def _matched_weighted_signals(
    tokens: list[str],
    signal_weights: dict[str, float],
) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    for phrase, weight in signal_weights.items():
        phrase_tokens = tuple(_ticket_type_signal_tokens(phrase))
        if not phrase_tokens:
            continue
        if _token_sequence_present(tokens, phrase_tokens):
            score += float(weight)
            matched.append(phrase)
    return score, matched


def _planned_request_profile_present(
    *,
    family: str | None,
    operation: str | None,
    resource: str | None,
    governance: tuple[str, ...],
) -> bool:
    return bool(
        family
        or (operation and resource)
        or (operation and governance)
        or (resource and governance)
    )


def _service_request_profile_boost(
    title: str,
    description: str,
) -> tuple[float, float]:
    if not has_explicit_fulfillment_intent(title, description):
        return 0.0, 0.0

    profile = build_service_request_profile(title, description)
    if not _planned_request_profile_present(
        family=profile.family,
        operation=profile.operation,
        resource=profile.resource,
        governance=profile.governance,
    ):
        return 0.0, 0.0

    boost = 0.0
    if profile.family:
        boost += 0.55
    if profile.operation:
        boost += 0.25
    if profile.resource:
        boost += 0.2
    boost += min(0.12, 0.04 * len(profile.governance))
    boost += min(0.15, profile.confidence * 0.15)
    return round(min(boost, 1.2), 4), float(profile.incident_conflict_score)


def _build_unknown_ticket_type(
    *,
    request_weight: float,
    incident_weight: float,
    matched_request_signals: list[str],
    matched_incident_signals: list[str],
    suppressing_signals: list[str],
) -> UnknownTicketType:
    if matched_request_signals and matched_incident_signals:
        reason = "conflicting_signals"
    elif matched_request_signals or matched_incident_signals:
        reason = "insufficient_signal_weight"
    else:
        reason = "no_strong_signal"
    return UnknownTicketType(
        reason=reason,
        request_weight=round(request_weight, 4),
        incident_weight=round(incident_weight, 4),
        matched_request_signals=matched_request_signals,
        matched_incident_signals=matched_incident_signals,
        suppressing_signals=suppressing_signals,
    )


def split_ticket_type_inference(
    value: TicketType | UnknownTicketType | None,
) -> tuple[TicketType | None, UnknownTicketType | None]:
    if isinstance(value, TicketType):
        return value, None
    if isinstance(value, UnknownTicketType):
        return None, value
    return None, None


def infer_ticket_type(
    title: str,
    description: str,
    *,
    category: TicketCategory | None = None,
    current: TicketType | None = None,
) -> TicketType | UnknownTicketType:
    tokens = _ticket_type_signal_tokens(f"{title} {description}")
    if not tokens:
        if current is not None:
            return current
        return _build_unknown_ticket_type(
            request_weight=0.0,
            incident_weight=0.0,
            matched_request_signals=[],
            matched_incident_signals=[],
            suppressing_signals=[],
        )
    request_score, matched_request_signals = _matched_weighted_signals(tokens, REQUEST_TYPE_SIGNAL_WEIGHTS)
    incident_score, matched_incident_signals = _matched_weighted_signals(tokens, INCIDENT_TYPE_SIGNAL_WEIGHTS)
    request_penalty, request_suppressors = _matched_weighted_signals(tokens, REQUEST_TYPE_NEGATIVE_SIGNAL_WEIGHTS)
    incident_penalty, incident_suppressors = _matched_weighted_signals(tokens, INCIDENT_TYPE_NEGATIVE_SIGNAL_WEIGHTS)
    request_weight = max(0.0, request_score - request_penalty)
    incident_weight = max(0.0, incident_score - incident_penalty)
    suppressing_signals = [*request_suppressors, *incident_suppressors]
    weak_incident_weight = sum(
        float(INCIDENT_TYPE_SIGNAL_WEIGHTS.get(signal, 0.0))
        for signal in matched_incident_signals
        if signal in _WEAK_INCIDENT_TYPE_SIGNALS
    )
    strong_incident_weight = max(0.0, incident_weight - weak_incident_weight)
    request_profile_boost, incident_conflict_score = _service_request_profile_boost(title, description)
    if request_profile_boost > 0.0 and strong_incident_weight < TICKET_TYPE_SCORE_THRESHOLD:
        request_weight += request_profile_boost
        if weak_incident_weight > 0.0 and incident_conflict_score < 1.0:
            reduced_amount = min(weak_incident_weight, request_profile_boost)
            incident_weight = max(0.0, incident_weight - reduced_amount)
            suppressing_signals.append("descriptive_incident_context")
    # When both signal sets fire (e.g. "permission denied" + "access request"),
    # incident wins — something breaking takes precedence over a request keyword.
    if category == TicketCategory.service_request and incident_weight <= 0.0:
        request_weight = max(request_weight, SERVICE_REQUEST_CATEGORY_HINT_WEIGHT)
    if incident_weight >= TICKET_TYPE_SCORE_THRESHOLD and incident_weight >= request_weight + TICKET_TYPE_DECISION_MARGIN:
        return TicketType.incident
    if request_weight >= TICKET_TYPE_SCORE_THRESHOLD and request_weight >= incident_weight + TICKET_TYPE_DECISION_MARGIN:
        return TicketType.service_request
    if incident_weight >= TICKET_TYPE_SCORE_THRESHOLD and request_weight < TICKET_TYPE_SCORE_THRESHOLD:
        return TicketType.incident
    if request_weight >= TICKET_TYPE_SCORE_THRESHOLD and incident_weight < TICKET_TYPE_SCORE_THRESHOLD:
        return TicketType.service_request
    if current is not None:
        return current
    return _build_unknown_ticket_type(
        request_weight=request_weight,
        incident_weight=incident_weight,
        matched_request_signals=matched_request_signals,
        matched_incident_signals=matched_incident_signals,
        suppressing_signals=suppressing_signals,
    )


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


def _match_context_text(match: dict[str, Any], *, include_issuetype: bool = True) -> tuple[str, str]:
    metadata = _match_metadata(match)
    title = _normalize_recommendation_text(
        str(metadata.get("summary") or metadata.get("title") or match.get("title") or match.get("jira_key") or "")
    )
    description = _normalize_recommendation_text(
        " ".join(
            part
            for part in [
                str(metadata.get("issuetype") or "").strip() if include_issuetype else "",
                str(metadata.get("components") or "").strip(),
                str(metadata.get("labels") or "").strip(),
                str(match.get("content") or "").strip(),
            ]
            if str(part or "").strip()
        )
    )
    return title, description


def _dominant_scored_category(
    scores: dict[TicketCategory, float],
    *,
    minimum: float = 1.0,
    margin: float = 0.45,
) -> TicketCategory | None:
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0].value), reverse=True)
    dominant_category, dominant_score = ranked[0]
    second_score = float(ranked[1][1]) if len(ranked) > 1 else 0.0
    if dominant_score >= max(minimum, second_score + margin):
        return dominant_category
    return None


def _category_from_match(match: dict[str, Any]) -> TicketCategory | None:
    title, description = _match_context_text(match, include_issuetype=False)
    category = _dominant_scored_category(_category_context_scores(title, description))
    if category is not None:
        return category
    metadata = _match_metadata(match)
    explicit_category = _coerce_category_value(
        metadata.get("category")
        or metadata.get("mapped_category")
        or metadata.get("ticket_category")
    )
    if explicit_category is not None:
        return explicit_category
    return None


def _ticket_type_from_match(match: dict[str, Any]) -> TicketType | None:
    title, description = _match_context_text(match, include_issuetype=True)
    inferred_category = _category_from_match(match)
    inference = infer_ticket_type(title, description, category=inferred_category)
    if isinstance(inference, TicketType):
        return inference
    metadata = _match_metadata(match)
    explicit_type = _coerce_ticket_type_value(
        metadata.get("ticket_type")
        or metadata.get("mapped_ticket_type")
    )
    if explicit_type is not None:
        return explicit_type
    return None


def _infer_classification_from_strong_matches(
    strong_matches: list[dict[str, Any]],
) -> tuple[TicketPriority | None, TicketCategory | None, TicketType | None]:
    if not strong_matches:
        return None, None, None

    weighted_priority: Counter[TicketPriority] = Counter()
    weighted_category: Counter[TicketCategory] = Counter()
    weighted_ticket_type: Counter[TicketType] = Counter()
    total_weight = 0.0
    for match in strong_matches:
        score = max(0.0, min(1.0, float(match.get("score") or 0.0)))
        # Keep a minimum vote so near-threshold strong matches still contribute.
        weight = max(0.2, score)
        metadata = _match_metadata(match)
        p = _priority_from_match(metadata)
        c = _category_from_match(match)
        tt = _ticket_type_from_match(match)
        if p is not None:
            weighted_priority[p] += weight
        if c is not None:
            weighted_category[c] += weight
        if tt is not None:
            weighted_ticket_type[tt] += weight
        total_weight += weight

    if total_weight <= 0.0:
        return None, None, None

    inferred_priority: TicketPriority | None = None
    inferred_category: TicketCategory | None = None
    inferred_ticket_type: TicketType | None = None

    if weighted_priority:
        top_priority, top_priority_weight = weighted_priority.most_common(1)[0]
        if (top_priority_weight / total_weight) >= 0.52:
            inferred_priority = top_priority

    if weighted_category:
        top_category, top_category_weight = weighted_category.most_common(1)[0]
        if (top_category_weight / total_weight) >= 0.52:
            inferred_category = top_category

    if weighted_ticket_type:
        top_ticket_type, top_ticket_type_weight = weighted_ticket_type.most_common(1)[0]
        if (top_ticket_type_weight / total_weight) >= 0.52:
            inferred_ticket_type = top_ticket_type

    return inferred_priority, inferred_category, inferred_ticket_type


def _load_strong_similarity_matches(
    title: str,
    description: str,
    *,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    query = _normalize_recommendation_text(f"{title}\n{description}")
    if not query:
        return []

    threshold = max(0.0, min(1.0, float(settings.AI_CLASSIFY_STRONG_SIMILARITY_THRESHOLD)))
    top_k = max(1, int(settings.AI_CLASSIFY_SEMANTIC_TOP_K))
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        matches = search_kb_issues(db, query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.info("Semantic retrieval unavailable during classify: %s", exc)
        return []
    finally:
        if owns_session:
            db.close()

    grounded = grounded_issue_matches(
        query,
        matches,
        top_k=top_k,
        score_threshold=threshold,
    )
    strong: list[dict[str, Any]] = []
    for match in list(grounded.get("matches") or []):
        strong.append(
            {
                "score": float(match.get("score") or 0.0),
                "distance": float(match.get("distance") or 1.0),
                "jira_key": str(match.get("jira_key") or "").strip(),
                "jira_issue_id": str(match.get("jira_issue_id") or "").strip() or None,
                "content": str(match.get("content") or ""),
                "metadata": _match_metadata(match),
                "coherence_score": float(match.get("coherence_score") or 0.0),
                "cluster_id": str(match.get("cluster_id") or "").strip() or None,
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


def _load_related_comment_matches(
    query: str,
    issue_matches: list[dict[str, Any]],
    *,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    if not issue_matches:
        return []
    jira_keys = [str(match.get("jira_key") or "").strip() for match in issue_matches if str(match.get("jira_key") or "").strip()]
    if not jira_keys:
        return []

    top_k = max(1, int(settings.AI_CLASSIFY_SEMANTIC_TOP_K))
    per_issue_limit = max(1, int(settings.JIRA_KB_MAX_COMMENTS_PER_ISSUE))
    max_comments = max(top_k * per_issue_limit, per_issue_limit)
    owns_session = db is None
    if db is None:
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
        _safe_rollback(db)
        logger.info("Issue-comment retrieval unavailable during classify: %s", exc)
        return []
    finally:
        if owns_session:
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
    signals = _normalize_technical_signals([title, description])
    signal_context = "\n".join(f"- {item}" for item in signals[:6]) if signals else "- no explicit signal extracted"
    prompt_json = (
        "Tu es un assistant support IT. Reponds uniquement en JSON valide.\n"
        "Schema: {\"recommendations\": [\"action 1\", \"action 2\", \"action 3\"]}\n"
        "Donne 2 a 4 actions concretes, non generiques, basees strictement sur les signaux techniques.\n"
        f"Signaux techniques:\n{signal_context}\n"
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
        "Chaque action doit referencer explicitement un signal technique present.\n"
        f"Signaux techniques:\n{signal_context}\n"
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
    inferred_ticket_type: TicketType | None,
    recommendation_mode: str,
    has_recommendations: bool,
    llm_success: bool,
) -> int:
    """Compute a 0-100 classification confidence score.

    Signals must be earned — there is no inflated base score.
    Each signal independently contributes, so a ticket with no
    evidence honestly scores low rather than defaulting to ~60.

    Score ranges:
        0–29  : very low  — almost no signal
        30–49 : low       — limited evidence
        50–69 : medium    — partial signal
        70–84 : high      — LLM + evidence
        85–97 : very high — all signals present
    """
    score = 0

    # Primary signal: LLM succeeded (well-formed response, no parse error)
    if llm_success:
        score += 35

    # Historical evidence: semantically similar past tickets found
    if strong_matches:
        # Reward more matches up to 4 (diminishing returns beyond that)
        match_bonus = min(25, 10 + 5 * min(len(strong_matches), 3))
        score += match_bonus

    # Field inference signals — each independently indicates the classifier
    # extracted a meaningful value rather than falling back to a default
    if inferred_category is not None:
        score += 15
    if inferred_priority is not None:
        score += 10
    if inferred_ticket_type is not None:
        score += 10

    # Recommendation quality: hybrid means both LLM + embedding agreed
    if recommendation_mode == "hybrid":
        score += 5
    elif recommendation_mode == "embedding":
        score += 2

    # Penalise if no actionable recommendations were produced
    if not has_recommendations:
        score -= 10

    # Floor at 10 (not 0) so UI never shows "0% confident"
    # Ceiling at 97 — never claim perfect confidence
    return int(max(10, min(97, score)))


def _semantic_signal_confidence(
    *,
    strong_matches: list[dict[str, Any]],
    inferred_category: TicketCategory | None,
    inferred_ticket_type: TicketType | None,
) -> float:
    score = 0.0
    if strong_matches:
        score += min(0.52, 0.14 + (0.09 * len(strong_matches[:4])))
    if inferred_ticket_type is not None:
        score += 0.2
    if inferred_category is not None:
        score += 0.1
    return round(min(score, 0.92), 4)


def _build_deterministic_classification_result(
    *,
    title: str,
    description: str,
    strong_matches: list[dict[str, Any]],
    inferred_priority: TicketPriority | None,
    inferred_category: TicketCategory | None,
    inferred_ticket_type: TicketType | None,
    technical_signals: list[str],
    related_comment_matches: list[dict[str, Any]],
    embedding_recommendations: list[str],
    llm_recommendations: list[str],
) -> dict[str, Any]:
    max_items = max(1, int(settings.AI_CLASSIFY_MAX_RECOMMENDATIONS))
    priority, category, ticket_type = _rule_based_classify(title, description)
    if inferred_priority is not None:
        priority = inferred_priority
    if inferred_category is not None:
        category = inferred_category
    category = apply_category_guardrail(title, description, category)
    ticket_type_inference = infer_ticket_type(
        title,
        description,
        category=category,
        current=inferred_ticket_type or ticket_type,
    )
    ticket_type, unknown_ticket_type = split_ticket_type_inference(ticket_type_inference)
    if strong_matches and not embedding_recommendations:
        embedding_recommendations = _recommendations_from_matches(related_comment_matches)
    embedding_recommendations = _filter_signal_grounded_recommendations(
        embedding_recommendations,
        technical_signals=technical_signals,
    )
    llm_recommendations = _filter_signal_grounded_recommendations(
        llm_recommendations,
        technical_signals=technical_signals,
    )
    final_recommendations = embedding_recommendations or llm_recommendations
    if not final_recommendations:
        final_recommendations = _signal_driven_fallback_recommendations(technical_signals)
    recommendation_mode = _resolve_recommendation_mode(
        strong_matches=strong_matches,
        embedding_recommendations=embedding_recommendations,
        llm_recommendations=llm_recommendations,
    )
    return {
        "priority": priority,
        "ticket_type": ticket_type,
        "classifier_ticket_type": ticket_type,
        "manual_triage_required": unknown_ticket_type is not None,
        "unknown_ticket_type": unknown_ticket_type,
        "category": category,
        "semantic_ticket_type": inferred_ticket_type,
        "semantic_category": inferred_category,
        "strong_match_count": len(strong_matches),
        "semantic_signal_confidence": _semantic_signal_confidence(
            strong_matches=strong_matches,
            inferred_category=inferred_category,
            inferred_ticket_type=inferred_ticket_type,
        ),
        "recommendations": final_recommendations[:max_items],
        "recommendations_embedding": embedding_recommendations[:max_items],
        "recommendations_llm": llm_recommendations[:max_items],
        "recommendation_mode": recommendation_mode,
        "similarity_found": bool(strong_matches),
        "classification_confidence": _compute_classification_confidence(
            strong_matches=strong_matches,
            inferred_priority=inferred_priority,
            inferred_category=inferred_category,
            inferred_ticket_type=inferred_ticket_type,
            recommendation_mode=recommendation_mode,
            has_recommendations=bool(final_recommendations),
            llm_success=False,
        ),
    }


def classify_ticket_detailed(
    title: str,
    description: str,
    *,
    db: Session | None = None,
    use_llm: bool = True,
    ticket_id: str | None = None,
    trigger: str = "creation",
    _do_log: bool = False,
) -> dict[str, Any]:
    description = description or title
    query = _normalize_recommendation_text(f"{title}\n{description}")
    strong_matches = _load_strong_similarity_matches(title, description, db=db)
    inferred_priority, inferred_category, inferred_ticket_type = _infer_classification_from_strong_matches(strong_matches)
    related_comment_matches = _load_related_comment_matches(query, strong_matches, db=db) if strong_matches else []
    technical_signals = _extract_technical_signals(
        title,
        description,
        issue_matches=strong_matches,
        comment_matches=related_comment_matches,
    )
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
    if not use_llm:
        return _build_deterministic_classification_result(
            title=title,
            description=description,
            strong_matches=strong_matches,
            inferred_priority=inferred_priority,
            inferred_category=inferred_category,
            inferred_ticket_type=inferred_ticket_type,
            technical_signals=technical_signals,
            related_comment_matches=related_comment_matches,
            embedding_recommendations=embedding_recommendations,
            llm_recommendations=llm_recommendations,
        )

    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if not data:
            data = _recover_classification_payload_from_reply(reply)
            if data:
                logger.info("Classifier recovered non-JSON model reply using heuristic extraction.")
        if not data:
            raise ValueError("invalid_json")

        priority = _coerce_priority_value(data.get("priority")) or inferred_priority
        category = _coerce_category_value(data.get("category")) or inferred_category
        ticket_type = _coerce_ticket_type_value(data.get("ticket_type")) or inferred_ticket_type
        if priority is None or category is None:
            raise ValueError("invalid_json_schema")

        category = apply_category_guardrail(title, description, category)
        if inferred_priority is not None:
            priority = inferred_priority
        if inferred_category is not None:
            category = apply_category_guardrail(title, description, inferred_category)
        ticket_type_inference = infer_ticket_type(
            title,
            description,
            category=category,
            current=inferred_ticket_type or ticket_type,
        )
        ticket_type, unknown_ticket_type = split_ticket_type_inference(ticket_type_inference)

        model_signals = _normalize_technical_signals(data.get("technical_signals"))
        if model_signals:
            technical_signals = model_signals
        llm_recommendations = _normalize_recommendations(data.get("recommendations"))
        llm_recommendations = _filter_signal_grounded_recommendations(
            llm_recommendations,
            technical_signals=technical_signals,
        )
        if strong_matches:
            grounded = _filter_grounded_recommendations(llm_recommendations, related_comment_matches)
            embedding_grounded = _filter_signal_grounded_recommendations(
                embedding_recommendations,
                technical_signals=technical_signals,
            )
            final_recommendations = grounded if grounded else embedding_grounded
        else:
            final_recommendations = llm_recommendations

        if not final_recommendations and not strong_matches:
            llm_recommendations = _generate_llm_basic_recommendations(title, description)
            llm_recommendations = _filter_signal_grounded_recommendations(
                llm_recommendations,
                technical_signals=technical_signals,
            )
            final_recommendations = llm_recommendations
        if not final_recommendations:
            final_recommendations = _signal_driven_fallback_recommendations(technical_signals)

        recommendation_mode = _resolve_recommendation_mode(
            strong_matches=strong_matches,
            embedding_recommendations=embedding_recommendations,
            llm_recommendations=llm_recommendations,
        )
        if _do_log:
            from app.services.ai.calibration import confidence_band as _band
            _conf = _compute_classification_confidence(
                strong_matches=strong_matches,
                inferred_priority=inferred_priority,
                inferred_category=inferred_category,
                inferred_ticket_type=inferred_ticket_type,
                recommendation_mode=recommendation_mode,
                has_recommendations=bool(final_recommendations),
                llm_success=True,
            ) / 100
            _p = getattr(priority, "value", priority)
            _c = getattr(category, "value", category)
            _t = getattr(ticket_type, "value", ticket_type) if ticket_type else None
            _reasoning = (
                f"Classified as {_c}/{_p} ({recommendation_mode} mode). Top hint: {final_recommendations[0][:120]}"
                if final_recommendations
                else f"Classified as {_c}/{_p}."
            )
            _log_classification(
                title=title,
                description=description,
                trigger=trigger,
                ticket_id=ticket_id,
                suggested_priority=str(_p or ""),
                suggested_category=str(_c or ""),
                suggested_ticket_type=str(_t) if _t else None,
                confidence=round(_conf, 4),
                confidence_band=_band(_conf),
                decision_source="llm",
                strong_match_count=len(strong_matches),
                recommendation_mode=recommendation_mode,
                reasoning=_reasoning,
            )
        return {
            "priority": priority,
            "ticket_type": ticket_type,
            "classifier_ticket_type": ticket_type,
            "manual_triage_required": unknown_ticket_type is not None,
            "unknown_ticket_type": unknown_ticket_type,
            "category": category,
            "semantic_ticket_type": inferred_ticket_type,
            "semantic_category": inferred_category,
            "strong_match_count": len(strong_matches),
            "semantic_signal_confidence": _semantic_signal_confidence(
                strong_matches=strong_matches,
                inferred_category=inferred_category,
                inferred_ticket_type=inferred_ticket_type,
            ),
            "recommendations": final_recommendations[:max_items],
            "recommendations_embedding": embedding_recommendations[:max_items],
            "recommendations_llm": llm_recommendations[:max_items],
            "recommendation_mode": recommendation_mode,
            "similarity_found": bool(strong_matches),
            "classification_confidence": _compute_classification_confidence(
                strong_matches=strong_matches,
                inferred_priority=inferred_priority,
                inferred_category=inferred_category,
                inferred_ticket_type=inferred_ticket_type,
                recommendation_mode=recommendation_mode,
                has_recommendations=bool(final_recommendations),
                llm_success=True,
            ),
        }
    except Exception as exc:
        logger.warning("Ollama classify failed, using fallback: %s", exc)
        _fallback = _build_deterministic_classification_result(
            title=title,
            description=description,
            strong_matches=strong_matches,
            inferred_priority=inferred_priority,
            inferred_category=inferred_category,
            inferred_ticket_type=inferred_ticket_type,
            technical_signals=technical_signals,
            related_comment_matches=related_comment_matches,
            embedding_recommendations=embedding_recommendations,
            llm_recommendations=llm_recommendations,
        )
        if _do_log:
            from app.services.ai.calibration import confidence_band as _band
            _fp = getattr(_fallback.get("priority"), "value", _fallback.get("priority"))
            _fc = getattr(_fallback.get("category"), "value", _fallback.get("category"))
            _ft = _fallback.get("ticket_type")
            _ft_val = getattr(_ft, "value", _ft) if _ft else None
            _frm = str(_fallback.get("recommendation_mode") or "")
            _frecs = _fallback.get("recommendations") or []
            _fconf = float(_fallback.get("classification_confidence") or 0) / 100
            _f_reasoning = (
                f"Fallback: {_fc}/{_fp} ({_frm} mode). Top hint: {_frecs[0][:120]}"
                if _frecs
                else f"Fallback: {_fc}/{_fp}."
            )
            _log_classification(
                title=title,
                description=description,
                trigger=trigger,
                ticket_id=ticket_id,
                suggested_priority=str(_fp or ""),
                suggested_category=str(_fc or ""),
                suggested_ticket_type=str(_ft_val) if _ft_val else None,
                confidence=round(_fconf, 4),
                confidence_band=_band(_fconf),
                decision_source="fallback",
                strong_match_count=int(_fallback.get("strong_match_count") or 0),
                recommendation_mode=_frm,
                reasoning=_f_reasoning,
            )
        return _fallback


def score_recommendations(
    recommendations: list[str],
    *,
    start_confidence: int = 86,
    rank_decay: int = 7,
    floor: int = 55,
    ceiling: int = 95,
    classification_confidence: int | None = None,
) -> list[dict[str, object]]:
    """Build confidence scores for recommendation strings.

    When ``classification_confidence`` is provided (0-100 int from
    ``_compute_classification_confidence``), each recommendation's score is
    scaled by how certain the classifier was.  A ticket classified with 30%
    confidence produces recommendations capped lower than one with 90%
    confidence, preventing the UI from showing confident-looking cards for
    poorly understood tickets.

    Scaling formula:
        effective_ceiling = ceiling × (classification_confidence / 100)
        effective_floor   = max(floor × 0.5, floor × (classification_confidence / 100))
    """
    if classification_confidence is not None:
        conf_factor = max(0.1, min(1.0, classification_confidence / 100))
        ceiling = int(ceiling * conf_factor)
        floor = int(max(floor * 0.5, floor * conf_factor))
        # Ensure a minimum gap of 5 points between floor and ceiling so that
        # rank_decay can produce at least one visible confidence step between
        # the top and bottom recommendations even at very low classification
        # confidence.  Without this guard, floor could equal ceiling and all
        # recommendations would display the same score.
        floor = min(floor, max(0, ceiling - 5))

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


def _rule_based_classify(title: str, description: str) -> tuple[TicketPriority, TicketCategory, TicketType | None]:
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

    ticket_type, _ = split_ticket_type_inference(infer_ticket_type(title, description))
    return priority, category, ticket_type


def classify_ticket(
    title: str,
    description: str,
    *,
    db: Session | None = None,
    use_llm: bool = True,
    ticket_id: str | None = None,
    trigger: str = "creation",
) -> tuple[TicketPriority, TicketType | None, TicketCategory, list[str]]:
    data = classify_ticket_detailed(
        title, description, db=db, use_llm=use_llm,
        ticket_id=ticket_id, trigger=trigger, _do_log=True,
    )
    return data["priority"], data["ticket_type"], data["category"], data["recommendations"]


async def classify_draft(
    title: str,
    description: str,
    ticket_type: str,
) -> dict:
    """
    Classify a ticket draft from title and description alone.

    Wrapper around classify_ticket_detailed that constructs a minimal
    ticket-like context from the provided fields. Used by the
    classify-draft endpoint before ticket creation.

    Args:
        title: Draft ticket title.
        description: Draft ticket description.
        ticket_type: "incident" or "service_request". Stored for context
            only — classify_ticket_detailed does not accept it as a parameter.

    Returns:
        Dict with keys: suggested_priority, suggested_category,
        suggested_assignee, confidence, confidence_band, reasoning.
        Never raises — returns a low-confidence fallback result on error.

    Edge cases:
        - Empty title or description: returns fallback with confidence=0.1
        - LLM unavailable: returns rule-based result with lower confidence
        - Invalid ticket_type: accepted and ignored silently
    """
    from app.services.ai.calibration import confidence_band as _band
    try:
        title_clean = str(title or "").strip()
        desc_clean = str(description or "").strip()

        if not title_clean or not desc_clean:
            return {
                "suggested_priority": "medium",
                "suggested_category": "service_request",
                "suggested_assignee": None,
                "confidence": 0.1,
                "confidence_band": "low",
                "reasoning": "Title or description too short to classify.",
            }

        # Delegate to the full classify_ticket_detailed pipeline (no db session
        # — uses its own session internally via SessionLocal when needed)
        result = classify_ticket_detailed(
            title=title_clean,
            description=desc_clean,
            db=None,
            _do_log=False,  # classify_draft manages its own audit log entry
        )

        # classify_ticket_detailed always returns a dict
        priority = str(
            result.get("priority").value
            if hasattr(result.get("priority"), "value")
            else result.get("priority") or "medium"
        ).lower()
        category = str(
            result.get("category").value
            if hasattr(result.get("category"), "value")
            else result.get("category") or "service_request"
        ).lower()
        confidence_raw = float(result.get("classification_confidence") or 0.5)

        # Build a reasoning string from recommendation_mode if available
        rec_mode = str(result.get("recommendation_mode") or "")
        recs = result.get("recommendations") or []
        if recs:
            reasoning = f"Classified as {category}/{priority} ({rec_mode or 'rule'} mode). Top hint: {recs[0][:120]}"
        else:
            reasoning = f"Classified as {category}/{priority} based on title and description."

        _log_classification(
            title=title_clean,
            description=desc_clean,
            trigger="draft",
            ticket_id=None,
            suggested_priority=priority,
            suggested_category=category,
            suggested_ticket_type=ticket_type,
            confidence=round(confidence_raw, 4),
            confidence_band=_band(confidence_raw),
            decision_source=str(result.get("recommendation_mode") or "llm"),
            strong_match_count=int(result.get("strong_match_count") or 0),
            recommendation_mode=str(result.get("recommendation_mode") or ""),
            reasoning=reasoning,
        )
        return {
            "suggested_priority": priority,
            "suggested_category": category,
            "suggested_assignee": None,
            "confidence": round(confidence_raw, 4),
            "confidence_band": _band(confidence_raw),
            "reasoning": reasoning,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("classify_draft failed: %s", exc)
        _log_classification(
            title=str(title or ""),
            description=str(description or ""),
            trigger="draft",
            ticket_id=None,
            suggested_priority="medium",
            suggested_category="service_request",
            suggested_ticket_type=None,
            confidence=0.15,
            confidence_band="low",
            decision_source="fallback",
            strong_match_count=0,
            recommendation_mode=None,
            reasoning="Classification unavailable. Please set fields manually.",
        )
        return {
            "suggested_priority": "medium",
            "suggested_category": "service_request",
            "suggested_assignee": None,
            "confidence": 0.15,
            "confidence_band": "low",
            "reasoning": "Classification unavailable. Please set fields manually.",
        }
