"""Intent detection helpers and keyword maps for AI chat.

Detection strategy:
    Intent classification uses a two-stage approach:

    Stage 1 — Rule-based (fast, deterministic):
        Keyword lists from ``conversation_policy`` are matched against the
        normalized user message.  Single-word keywords use regex word-boundary
        matching (``\\b``) to prevent false positives (e.g. ``"open"`` should
        not match ``"open_source_vulnerability"`` or ``"reopen"``).  Multi-word
        phrases use substring matching because word boundaries are implicit.

    Stage 2 — LLM fallback (slower, only when rule confidence is low):
        If the rule-based stage returns ``IntentConfidence.low`` for a
        ``general`` intent, the message is sent to the LLM for coarse
        classification into one of: ``guidance``, ``information``,
        ``analytics``, ``creation``.

Word-boundary rationale:
    Pure substring matching (``keyword in text``) causes false positives for
    single-word keywords that appear as sub-strings of longer words.  For
    example ``"open" in "open_source_vulnerability"`` is ``True`` even though
    the user is not asking to open a ticket.  Word-boundary regex prevents this
    without changing the keyword lists.

Confidence contract:
    - ``IntentConfidence.high``   — rule-based match with strong signal.
    - ``IntentConfidence.medium`` — rule-based match with softer signal.
    - ``IntentConfidence.low``    — no strong rule match; LLM fallback used.
    Downstream routing uses confidence to decide whether to show structured
    results or fall back to a generic response.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from app.models.enums import TicketStatus
from app.services.ai.conversation_policy import (
    ACTIVE_TICKET_KEYWORDS,
    CRITICAL_TICKET_KEYWORDS,
    EXPLICIT_CREATE_TICKET_KEYWORDS,
    GUIDANCE_CONTEXT_KEYWORDS,
    GUIDANCE_REQUEST_KEYWORDS,
    HELP_REQUEST_KEYWORDS,
    INFO_REQUEST_KEYWORDS,
    MOST_USED_TICKET_KEYWORDS,
    OPEN_TICKET_KEYWORDS,
    PROBLEM_DETAIL_KEYWORDS,
    PROBLEM_DRILL_DOWN_KEYWORDS,
    PROBLEM_LISTING_KEYWORDS,
    RECENT_INTENT_STOPWORDS,
    RECENT_TICKET_KEYWORDS,
    RECOMMENDATION_LISTING_KEYWORDS,
    RECURRING_KEYWORDS,
    SOLUTION_KEYWORDS,
    STATUS_KEYWORD_MAP,
    WEEKLY_SUMMARY_KEYWORDS,
)
from app.services.ai.llm import extract_json, ollama_generate

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}
TICKET_ID_PATTERN = re.compile(r"\bTW-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
PROBLEM_ID_PATTERN = re.compile(r"\bPB-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
TICKET_ID_FLEX_PATTERN = re.compile(r"\bTW(?:[-_\s]+[A-Z0-9]+){2,}\b", re.IGNORECASE)
PROBLEM_ID_FLEX_PATTERN = re.compile(r"\bPB(?:[-_\s]+[A-Z0-9]+){1,}\b", re.IGNORECASE)
RECENT_CONSTRAINT_PATTERN = re.compile(
    r"\b(?:about|with|for|regarding|sur|avec|pour|concernant|qui|where|containing)\s+([a-z0-9][a-z0-9 _\-/\.]{1,80})\b",
    re.IGNORECASE,
)
ERROR_CODE_PATTERN = re.compile(r"\b(?:error|erreur|code)\s*([0-9]{3,5})\b", re.IGNORECASE)
CONSTRAINT_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-_/\.]{2,}", re.IGNORECASE)
_TICKET_INVENTORY_TARGETS = (
    "ticket",
    "tickets",
    "service request",
    "service requests",
    "demande de service",
    "demandes de service",
    "incident",
    "incidents",
)


class ChatIntent(str, Enum):
    create_ticket = "create_ticket"
    recent_ticket = "recent_ticket"
    most_used_tickets = "most_used_tickets"
    weekly_summary = "weekly_summary"
    critical_tickets = "critical_tickets"
    recurring_solutions = "recurring_solutions"
    data_query = "data_query"
    general = "general"
    # Problem and recommendation shortcuts
    problem_listing = "problem_listing"
    problem_detail = "problem_detail"
    problem_drill_down = "problem_drill_down"
    recommendation_listing = "recommendation_listing"


class IntentConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


@dataclass(slots=True)
class ChatIntentDetails:
    intent: ChatIntent
    confidence: IntentConfidence
    source: str
    guidance_requested: bool
    entity_kind: str = "none"
    entity_id: str | None = None
    inventory_kind: str | None = None
    filter_meta: dict[str, list[str] | str | bool | None] = field(default_factory=dict)


def _normalize_locale(locale: str | None) -> str:
    return "en" if (locale or "").lower().startswith("en") else "fr"


# Default confidence returned when the LLM fallback does not include a
# parseable confidence value in its response.  Set to "low" rather than
# "medium" so that ambiguous LLM results do not inflate routing confidence.
LLM_FALLBACK_DEFAULT_CONFIDENCE = "low"


def _matches_keyword(text: str, keyword: str) -> bool:
    """Match a single keyword against text using the safest available strategy.

    Single-word keywords (no spaces) use regex word-boundary matching to avoid
    false positives where the keyword appears as a substring of a longer token.
    For example ``"open"`` must NOT match ``"open_source"`` or ``"reopen"``.

    Multi-word phrases (containing a space) use plain substring matching because
    word boundaries are implicit at phrase boundaries and the phrases are
    specific enough that substring collisions are unlikely.

    Args:
        text: Normalized (lowercased, accent-stripped) input text to search.
        keyword: A single keyword or multi-word phrase to match.

    Returns:
        True if the keyword is found in ``text`` under the appropriate strategy.

    Edge cases:
        - Empty ``keyword`` always returns False.
        - Empty ``text`` always returns False.
        - Matching is case-insensitive regardless of strategy.
    """
    if not keyword or not text:
        return False
    if " " in keyword:
        # Multi-word phrase: substring match is safe because the phrase is
        # specific enough to avoid accidental collisions.
        return keyword in text
    # Single-word keyword: use word boundaries to prevent substring false positives
    # (e.g. "open" should not match "open_source_vulnerability").
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE))


def _contains_any(text: str, keywords: list[str]) -> bool:
    """Return True if any keyword in the list matches the text.

    Delegates per-keyword matching to ``_matches_keyword`` so that
    single-word keywords use word-boundary matching and multi-word phrases
    use substring matching.

    Args:
        text: Normalized input text to search.
        keywords: List of keywords or phrases to check.

    Returns:
        True if at least one keyword matches ``text``.
    """
    return any(_matches_keyword(text, k) for k in keywords)


def _contains_target(text: str, targets: list[str]) -> bool:
    return any(_matches_keyword(text, target) for target in targets)


def _looks_like_inventory_request(
    text: str,
    *,
    targets: list[str],
    list_words: list[str],
    qualifier_words: list[str] | None = None,
) -> bool:
    normalized = _normalize_intent_text(text or "")
    if not normalized or not _contains_target(normalized, targets):
        return False
    if normalized in set(targets):
        return True
    if _contains_any(normalized, list_words):
        return True
    if qualifier_words and _contains_any(normalized, qualifier_words):
        return True
    if "?" in str(text or "") and _contains_any(normalized, ["what", "which", "quels", "quelles"]):
        return True
    return False


def _normalize_intent_text(text: str) -> str:
    value = (text or "").lower().strip()
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    without_marks = without_marks.replace("\u2019", "'").replace("\u00e2\u20ac\u2122", "'")
    return re.sub(r"\s+", " ", without_marks).strip()


def _detect_window_days(text: str) -> int | None:
    if any(token in text for token in ["today", "aujourd"]):
        return 1
    if any(token in text for token in ["this week", "cette semaine", "hebdo"]):
        return 7
    if any(token in text for token in ["this month", "ce mois"]):
        return 30

    direct = re.search(r"(?:last|past|sur|dernier(?:s)?|derniere(?:s)?)\s+(\d{1,3})\s*(?:day|days|jour|jours)", text)
    if direct:
        return max(1, min(365, int(direct.group(1))))

    fallback = re.search(r"(\d{1,3})\s*(?:day|days|jour|jours)", text)
    if fallback and any(token in text for token in ["last", "past", "recent", "dernier", "derniere", "sur"]):
        return max(1, min(365, int(fallback.group(1))))
    return None


def _is_mttr_request(text: str) -> bool:
    return any(token in text for token in ["mttr", "mean time to resolve", "temps moyen de resolution"])


def _is_first_action_request(text: str) -> bool:
    return any(token in text for token in ["first action", "premiere action", "first response", "premiere reponse"])


def _is_reassignment_request(text: str) -> bool:
    return any(token in text for token in ["reassign", "reassignment", "reassignation", "reaffectation"])


def _is_resolution_rate_request(text: str) -> bool:
    return any(token in text for token in ["resolution rate", "taux de resolution"])


def _is_count_request(text: str) -> bool:
    return any(token in text for token in ["how many", "combien", "nombre", "count"])


def _is_listing_request(text: str) -> bool:
    return any(token in text for token in ["list", "show", "affiche", "montre", "quels", "which"])


def _looks_like_ticket_inventory_target(text: str) -> bool:
    return any(token in text for token in _TICKET_INVENTORY_TARGETS)


def _looks_like_info_request(text: str) -> bool:
    has_info_language = any(token in text for token in INFO_REQUEST_KEYWORDS)
    has_target = any(token in text for token in GUIDANCE_CONTEXT_KEYWORDS) or _looks_like_ticket_inventory_target(text)
    return has_info_language and has_target


def _has_explicit_guidance_keyword(text: str) -> bool:
    return any(token in text for token in GUIDANCE_REQUEST_KEYWORDS)


def _looks_like_data_query(text: str) -> bool:
    if _looks_like_guidance_request(text):
        return False
    if _looks_like_info_request(text):
        return True
    if _is_listing_request(text) and _looks_like_ticket_inventory_target(text):
        return True
    data_tokens = [
        "ticket",
        "tickets",
        "service request",
        "service requests",
        "demande de service",
        "demandes de service",
        "mttr",
        "reassign",
        "reaffectation",
        "premiere action",
        "first action",
        "resolution rate",
        "taux de resolution",
        "combien",
        "how many",
        "type",
        "ticket type",
        "kind",
        "priorite",
        "priority",
        "categorie",
        "category",
        "assignee",
        "assigne",
        "owner",
        "reporter",
        "sla",
        "deadline",
        "due",
        "stats",
        "statistiques",
        "analytics",
        "kpi",
        "count",
    ]
    return any(token in text for token in data_tokens)


def _looks_like_guidance_request(text: str) -> bool:
    if _has_explicit_guidance_keyword(text):
        return True
    has_help_language = any(token in text for token in HELP_REQUEST_KEYWORDS)
    has_guidance_context = any(token in text for token in GUIDANCE_CONTEXT_KEYWORDS)
    if has_help_language and has_guidance_context:
        return True
    has_resolution_language = any(
        token in text
        for token in [
            "fix",
            "resolve",
            "solution",
            "recommend",
            "recommande",
            "recommandation",
            "correctif",
            "next step",
            "diagnostic",
        ]
    )
    has_target = any(token in text for token in GUIDANCE_CONTEXT_KEYWORDS + ["probleme"])
    return has_resolution_language and has_target


def is_guidance_request(text: str) -> bool:
    return _looks_like_guidance_request(_normalize_intent_text(text))


def _normalize_entity_id(value: str, *, prefix: str) -> str | None:
    tokens = re.findall(r"[A-Z0-9]+", str(value or "").upper())
    if not tokens or tokens[0] != prefix or len(tokens) < 2:
        return None
    return "-".join(tokens)


def extract_ticket_id(text: str) -> str | None:
    match = TICKET_ID_PATTERN.search(str(text or ""))
    if match:
        return match.group(0).upper()
    flexible_match = TICKET_ID_FLEX_PATTERN.search(str(text or ""))
    return _normalize_entity_id(flexible_match.group(0), prefix="TW") if flexible_match else None


def _looks_like_analytics_request(text: str) -> bool:
    return any(token in text for token in ["mttr", "stats", "statistiques", "analytics", "kpi", "count", "combien"])


def _coarse_label_from_rule_intent(intent: ChatIntent, text: str) -> str:
    if intent == ChatIntent.create_ticket:
        return "creation"
    if intent in {ChatIntent.weekly_summary, ChatIntent.critical_tickets} or _looks_like_analytics_request(text):
        return "analytics"
    if intent == ChatIntent.data_query:
        return "information"
    if intent == ChatIntent.general and _looks_like_guidance_request(text):
        return "guidance"
    return "general"


def extract_problem_id(text: str) -> str | None:
    """Extract a PB-* problem ID from text.

    Args:
        text: Raw user message.
    Returns:
        Uppercase problem ID string or None if not found.
    """
    match = PROBLEM_ID_PATTERN.search(str(text or ""))
    if match:
        return match.group(0).upper()
    flexible_match = PROBLEM_ID_FLEX_PATTERN.search(str(text or ""))
    return _normalize_entity_id(flexible_match.group(0), prefix="PB") if flexible_match else None


def _legacy_problem_listing_request_keyword_only(text: str) -> bool:
    from app.services.ai.resolver import _has_negation_near_match  # noqa: PLC0415
    tokens = text.lower().split()
    for keyword in PROBLEM_LISTING_KEYWORDS:
        if not _matches_keyword(text, keyword):
            continue
        # Find the first token of the keyword in the sentence to locate it for
        # negation checking.  For single-word keywords the token is the keyword
        # itself; for multi-word phrases we use the first word as a proxy.
        kw_first = keyword.split()[0]
        matched_idx = next((i for i, tok in enumerate(tokens) if tok == kw_first), -1)
        if matched_idx == -1:
            # Couldn't locate position — allow match conservatively.
            return True
        if not _has_negation_near_match(tokens, matched_idx, window=3):
            return True
        # Negation found near this keyword — continue checking other keywords.
    return False


def _is_problem_detail_request(text: str, *, has_problem_id: bool = False) -> bool:
    if has_problem_id:
        return True
    return _contains_any(text, PROBLEM_DETAIL_KEYWORDS)


def _is_problem_analysis_request(text: str) -> bool:
    return _contains_any(
        text,
        [
            "why",
            "pourquoi",
            "cause",
            "root cause",
            "analyse",
            "analysis",
            "workaround",
            "fix",
            "resolve",
            "resolution",
            "remediation",
            "recommendation",
            "recommendations",
        ],
    )


def _is_problem_drill_down_request(text: str) -> bool:
    return _contains_any(text, PROBLEM_DRILL_DOWN_KEYWORDS)


def _legacy_recommendation_listing_request_keyword_only(text: str) -> bool:
    return _contains_any(text, RECOMMENDATION_LISTING_KEYWORDS)


def _is_problem_listing_request(text: str) -> bool:
    from app.services.ai.resolver import _has_negation_near_match  # noqa: PLC0415

    normalized = _normalize_intent_text(text or "")
    tokens = normalized.split()
    generic_problem_keywords = {"problem", "problems", "probleme", "problemes"}
    for keyword in PROBLEM_LISTING_KEYWORDS:
        if not _matches_keyword(normalized, keyword):
            continue
        if keyword in generic_problem_keywords:
            continue
        kw_first = keyword.split()[0]
        matched_idx = next((i for i, tok in enumerate(tokens) if tok == kw_first), -1)
        if matched_idx == -1:
            return True
        if not _has_negation_near_match(tokens, matched_idx, window=3):
            return True

    if _looks_like_inventory_request(
        normalized,
        targets=["problem", "problems", "probleme", "problemes", "known error", "known errors", "erreur connue", "erreurs connues"],
        list_words=["list", "show", "show me", "affiche", "montre", "voir", "quels", "quelles", "which", "what are"],
        qualifier_words=[
            "current",
            "existing",
            "active",
            "open",
            "resolved",
            "investigating",
            "known",
            "recurring",
            "en cours",
            "ouverts",
            "actifs",
            "resolus",
            "en investigation",
            "connus",
            "actuels",
            "existants",
        ],
    ):
        matched_idx = next(
            (i for i, tok in enumerate(tokens) if tok in {"problem", "problems", "probleme", "problemes"}),
            -1,
        )
        if matched_idx == -1 or not _has_negation_near_match(tokens, matched_idx, window=3):
            return True
    return False


def _is_recommendation_listing_request(text: str) -> bool:
    normalized = _normalize_intent_text(text or "")
    if _contains_any(normalized, RECOMMENDATION_LISTING_KEYWORDS):
        return True
    return _looks_like_inventory_request(
        normalized,
        targets=["recommendation", "recommendations", "recommandation", "recommandations", "suggestion", "suggestions"],
        list_words=["list", "show", "show me", "affiche", "montre", "voir", "quelles", "which", "what are"],
        qualifier_words=["current", "top", "latest", "my", "mes", "actuelles", "courantes", "meilleures"],
    )


def extract_status_filter(text: str) -> str | None:
    """Extract a problem status filter value from a message using STATUS_KEYWORD_MAP.

    Checks each keyword in STATUS_KEYWORD_MAP against the normalized text
    using _matches_keyword() for word-boundary safety.

    Args:
        text: Normalized user message.
    Returns:
        Status filter string (e.g. "open", "known_error") or None.
    """
    for keyword, status in STATUS_KEYWORD_MAP.items():
        if _matches_keyword(text, keyword):
            return status
    return None


def detect_intent_with_confidence(text: str) -> tuple[ChatIntent, IntentConfidence]:
    normalized = _normalize_intent_text(text or "")
    # Problem and recommendation shortcuts — checked first because they are
    # more specific than the ticket-focused checks below.
    problem_id = extract_problem_id(text or "")
    # When the text contains a problem ID but also looks like a guidance/fix
    # request (e.g. "How do I fix PB-0001?"), route to general guidance rather
    # than the detail shortcut — the resolver/advisor should handle it.
    if problem_id and (_looks_like_guidance_request(normalized) or _is_problem_analysis_request(normalized)):
        return ChatIntent.general, IntentConfidence.high
    if problem_id and _is_problem_drill_down_request(normalized):
        return ChatIntent.problem_drill_down, IntentConfidence.high
    if _is_problem_detail_request(normalized, has_problem_id=bool(problem_id)):
        return ChatIntent.problem_detail, IntentConfidence.high
    # When text matches problem drill-down but also mentions similar/related
    # tickets in the context of a specific ticket (not a problem), do not
    # route to shortcut_problem_linked_tickets — let the resolver handle it.
    if _is_problem_drill_down_request(normalized) and not any(
        token in normalized for token in ["similar", "semblable", "ressemble"]
    ):
        return ChatIntent.problem_drill_down, IntentConfidence.high
    if _is_problem_listing_request(normalized):
        return ChatIntent.problem_listing, IntentConfidence.high
    if _is_recommendation_listing_request(normalized):
        return ChatIntent.recommendation_listing, IntentConfidence.high
    # Existing checks below (unchanged)
    if _is_explicit_ticket_create_request(text or ""):
        return ChatIntent.create_ticket, IntentConfidence.high
    if _is_recent_ticket_request(normalized):
        return ChatIntent.recent_ticket, IntentConfidence.high
    if _is_most_used_request(normalized):
        return ChatIntent.most_used_tickets, IntentConfidence.high
    if _is_weekly_summary_request(normalized):
        return ChatIntent.weekly_summary, IntentConfidence.high
    if _is_critical_ticket_request(normalized):
        return ChatIntent.critical_tickets, IntentConfidence.high
    if _is_recurring_solution_request(normalized):
        return ChatIntent.recurring_solutions, IntentConfidence.high
    if _looks_like_info_request(normalized):
        return ChatIntent.data_query, IntentConfidence.high
    if _has_explicit_guidance_keyword(normalized):
        return ChatIntent.general, IntentConfidence.high
    if _looks_like_guidance_request(normalized):
        return ChatIntent.general, IntentConfidence.medium
    if _looks_like_data_query(normalized):
        return ChatIntent.data_query, IntentConfidence.medium
    return ChatIntent.general, IntentConfidence.low


_VALID_LLM_INTENT_LABELS = frozenset({
    "create_ticket", "recent_ticket", "critical_tickets", "most_used_tickets",
    "weekly_summary", "recurring_solutions", "data_query", "problem_listing",
    "problem_detail", "problem_drill_down", "recommendation_listing", "general",
})

_LLM_INTENT_MAP: dict[str, ChatIntent] = {
    "create_ticket": ChatIntent.create_ticket,
    "recent_ticket": ChatIntent.recent_ticket,
    "critical_tickets": ChatIntent.critical_tickets,
    "most_used_tickets": ChatIntent.most_used_tickets,
    "weekly_summary": ChatIntent.weekly_summary,
    "recurring_solutions": ChatIntent.recurring_solutions,
    "data_query": ChatIntent.data_query,
    "problem_listing": ChatIntent.problem_listing,
    "problem_detail": ChatIntent.problem_detail,
    "problem_drill_down": ChatIntent.problem_drill_down,
    "recommendation_listing": ChatIntent.recommendation_listing,
    "general": ChatIntent.general,
}


def _parse_intent_label(raw: str) -> str | None:
    parsed = extract_json(raw)
    if isinstance(parsed, dict):
        for key in ("label", "intent", "classification"):
            candidate = _normalize_intent_text(str(parsed.get(key) or ""))
            if candidate in _VALID_LLM_INTENT_LABELS:
                return candidate
    normalized = _normalize_intent_text(raw)
    # Match the longest label first to prevent "data_query" matching inside
    # "recent_ticket" etc.
    for label in sorted(_VALID_LLM_INTENT_LABELS, key=len, reverse=True):
        escaped = re.escape(label.replace("_", r"[_ ]?"))
        if re.search(escaped, normalized, re.IGNORECASE):
            return label
    return None


def _map_llm_label_to_intent(label: str | None) -> ChatIntent:
    return _LLM_INTENT_MAP.get(label or "", ChatIntent.general)


def _classify_intent_llm_label(text: str) -> str | None:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None
    prompt = (
        "You are an intent classifier for an ITSM (IT Service Management) chat assistant.\n\n"
        "Classify the user message into exactly one of these labels:\n"
        "- create_ticket\n"
        "- recent_ticket\n"
        "- critical_tickets\n"
        "- most_used_tickets\n"
        "- weekly_summary\n"
        "- recurring_solutions\n"
        "- data_query\n"
        "- problem_listing\n"
        "- problem_detail\n"
        "- problem_drill_down\n"
        "- recommendation_listing\n"
        "- general\n\n"
        "Definitions:\n"
        "create_ticket     = user wants to open, create, submit, log or raise a new ticket\n"
        "recent_ticket     = user wants to see recent, latest, or last tickets\n"
        "critical_tickets  = user wants critical, urgent, high priority, P0 or P1 tickets\n"
        "most_used_tickets = user wants most common, frequent or used ticket types\n"
        "weekly_summary    = user wants a week summary or activity report\n"
        "recurring_solutions = user wants recurring issues, repeated bugs or their known solutions\n"
        "data_query        = user wants ticket data: list, count, stats, KPI, SLA info, assignee, category, network tickets, email tickets, etc.\n"
        "problem_listing   = user wants to see the list of known problems or recurring problems\n"
        "problem_detail    = user wants details about one specific problem record (PB-xxx ID)\n"
        "problem_drill_down = user wants tickets linked to a problem already in context\n"
        "recommendation_listing = user wants to see AI recommendations or suggestions\n"
        "general           = troubleshooting, fixing, diagnosing, root cause, guidance, or unclear\n\n"
        "Examples:\n"
        "create a ticket for VPN issue → create_ticket\n"
        "nouveau ticket imprimante → create_ticket\n"
        "show me recent tickets → recent_ticket\n"
        "derniers tickets → recent_ticket\n"
        "critical tickets → critical_tickets\n"
        "high priority tickets → critical_tickets\n"
        "billets urgents → critical_tickets\n"
        "most common ticket types → most_used_tickets\n"
        "bilan de la semaine → weekly_summary\n"
        "recurring VPN problems → recurring_solutions\n"
        "network tickets → data_query\n"
        "tickets about email → data_query\n"
        "SLA at risk → data_query\n"
        "how many open tickets → data_query\n"
        "show problems → problem_listing\n"
        "quels sont les problèmes → problem_listing\n"
        "tell me about PB-001 → problem_detail\n"
        "show linked tickets → problem_drill_down\n"
        "my recommendations → recommendation_listing\n"
        "how do I fix VPN disconnection → general\n"
        "why is this ticket not resolving → general\n"
        "what should I do about this → general\n\n"
        f"User message: {normalized}\n\n"
        "Return ONLY the label, nothing else."
    )
    try:
        raw = ollama_generate(prompt, json_mode=False)
        label = _parse_intent_label(raw)
        if label is None:
            logger.info("Intent LLM fallback returned no valid label for %r; defaulting to general.", normalized[:60])
            return None
        return label
    except Exception as exc:  # noqa: BLE001
        logger.info("Intent LLM fallback unavailable; defaulting to general: %s", exc)
        return None


def classify_intent_llm(text: str) -> ChatIntent:
    label = _classify_intent_llm_label(text)
    if label is None:
        return ChatIntent.general
    return _map_llm_label_to_intent(label)


def _inventory_filter_meta(text: str, *, inventory_kind: str | None) -> dict[str, list[str] | str | bool | None]:
    normalized = _normalize_intent_text(text or "")
    meta: dict[str, list[str] | str | bool | None] = {
        "inventory_kind": inventory_kind,
        "wants_list": _is_listing_request(normalized),
        "wants_count": _is_count_request(normalized),
    }
    if inventory_kind == "tickets":
        filters: list[str] = []
        if any(token in normalized for token in ["incident", "incidents"]):
            filters.append("incident")
        if any(token in normalized for token in ["service request", "service requests", "demande de service", "demandes de service"]):
            filters.append("service_request")
        if any(token in normalized for token in ["critical", "critique"]):
            filters.append("critical")
        if any(token in normalized for token in ["high", "haute"]):
            filters.append("high")
        if any(token in normalized for token in ["application", "app", "logiciel", "software"]):
            filters.append("application")
        if any(token in normalized for token in ["network", "reseau", "vpn", "router", "switch"]):
            filters.append("network")
        if any(token in normalized for token in ["security", "securite"]):
            filters.append("security")
        if any(token in normalized for token in ["hardware", "materiel", "laptop", "printer", "pc"]):
            filters.append("hardware")
        if any(token in normalized for token in ["email", "mail", "outlook"]):
            filters.append("email")
        if any(token in normalized for token in ["problem", "probleme"]):
            filters.append("problem")
        meta["filters"] = filters
        return meta

    if inventory_kind == "problems":
        statuses: list[str] = []
        if any(token in normalized for token in ["open", "ouverts", "ouvert"]):
            statuses.append("open")
        if any(token in normalized for token in ["known error", "known errors", "erreur connue", "erreurs connues"]):
            statuses.append("known_error")
        if any(token in normalized for token in ["investigating", "investigation", "en investigation"]):
            statuses.append("investigating")
        if any(token in normalized for token in ["resolved", "resolus", "resolu"]):
            statuses.append("resolved")
        meta["status_filters"] = statuses
        return meta

    if inventory_kind == "recommendations":
        qualifiers: list[str] = []
        if any(token in normalized for token in ["current", "actuelles", "courantes"]):
            qualifiers.append("current")
        if any(token in normalized for token in ["top", "best", "meilleures"]):
            qualifiers.append("top")
        if any(token in normalized for token in ["high confidence", "forte confiance", "strong confidence"]):
            qualifiers.append("high_confidence")
        meta["qualifiers"] = qualifiers
        return meta

    return meta


def parse_chat_intent_details(text: str) -> ChatIntentDetails:
    intent, confidence, source, guidance_requested = detect_intent_hybrid_details(text)
    normalized = _normalize_intent_text(text or "")
    ticket_id = extract_ticket_id(text or "")
    problem_id = extract_problem_id(text or "")

    entity_kind = "none"
    entity_id: str | None = None
    if problem_id:
        entity_kind = "problem"
        entity_id = problem_id
    elif ticket_id:
        entity_kind = "ticket"
        entity_id = ticket_id

    inventory_kind: str | None = None
    if intent in {
        ChatIntent.problem_listing,
        ChatIntent.recommendation_listing,
        ChatIntent.critical_tickets,
        ChatIntent.most_used_tickets,
        ChatIntent.weekly_summary,
        ChatIntent.recurring_solutions,
        ChatIntent.recent_ticket,
    }:
        inventory_kind = "tickets"
    if intent == ChatIntent.problem_listing:
        inventory_kind = "problems"
    elif intent == ChatIntent.recommendation_listing:
        inventory_kind = "recommendations"
    elif intent == ChatIntent.data_query and _looks_like_ticket_inventory_target(normalized):
        inventory_kind = "tickets"

    return ChatIntentDetails(
        intent=intent,
        confidence=confidence,
        source=source,
        guidance_requested=guidance_requested,
        entity_kind=entity_kind,
        entity_id=entity_id,
        inventory_kind=inventory_kind,
        filter_meta=_inventory_filter_meta(normalized, inventory_kind=inventory_kind),
    )


def detect_intent_hybrid_details(text: str) -> tuple[ChatIntent, IntentConfidence, str, bool]:
    """Detect intent with confidence using rule-based detection first, LLM fallback second.

    Returns a 4-tuple of (intent, confidence, source, is_guidance):
    - intent: the detected ChatIntent enum value.
    - confidence: IntentConfidence reflecting the actual detection quality.
      When the LLM fallback is used, confidence is set to ``low`` rather than
      the rule-based confidence, because the LLM fallback only fires when
      rule-based confidence was already low.  This prevents the fallback from
      appearing more confident than it actually is.
    - source: one of ``"rules"``, ``"rules_default"``, ``"llm_fallback"``.
    - is_guidance: True if the intent maps to the guidance/troubleshooting domain.

    Args:
        text: Raw user message (not pre-normalized).

    Returns:
        4-tuple of (ChatIntent, IntentConfidence, source_str, is_guidance_bool).
    """
    normalized = _normalize_intent_text(text or "")
    intent, confidence = detect_intent_with_confidence(normalized)
    if confidence == IntentConfidence.high:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules", guidance
    if confidence == IntentConfidence.medium and intent != ChatIntent.general:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules", guidance

    llm_label = _classify_intent_llm_label(text)
    if llm_label is None:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules_default", guidance
    llm_intent = _map_llm_label_to_intent(llm_label)
    guidance = llm_label == "guidance"
    # LLM fallback only fires when rule confidence was already low.
    # When LLM says "guidance" AND text already has partial guidance signal
    # (e.g. action verbs + issue context), upgrade to medium — the phrase was
    # just an unseen phrasing.  For truly ambiguous text with no guidance
    # signal stay at low (LLM_FALLBACK_DEFAULT_CONFIDENCE).
    if guidance and _looks_like_guidance_request(normalized):
        llm_confidence = IntentConfidence.medium
    else:
        llm_confidence = IntentConfidence(LLM_FALLBACK_DEFAULT_CONFIDENCE)
    return llm_intent, llm_confidence, "llm_fallback", guidance


def detect_intent_hybrid(text: str) -> ChatIntent:
    return detect_intent_hybrid_details(text)[0]


def _is_recent_ticket_request(text: str) -> bool:
    return "ticket" in text and _contains_any(text, RECENT_TICKET_KEYWORDS)


def _is_most_used_request(text: str) -> bool:
    return "ticket" in text and _contains_any(text, MOST_USED_TICKET_KEYWORDS)


def _is_weekly_summary_request(text: str) -> bool:
    if _contains_any(text, WEEKLY_SUMMARY_KEYWORDS):
        return True
    has_summary_word = any(k in text for k in ["summarize", "summary", "resume", "resumer", "bilan"])
    has_week_word = any(k in text for k in ["week", "semaine", "hebdo", "hebdomadaire"])
    has_activity_word = any(k in text for k in ["activity", "activite"])
    return has_summary_word and (has_week_word or has_activity_word)


def _is_critical_ticket_request(text: str) -> bool:
    return "ticket" in text and _contains_any(text, CRITICAL_TICKET_KEYWORDS)


def _is_recurring_solution_request(text: str) -> bool:
    has_recurring = _contains_any(text, RECURRING_KEYWORDS)
    has_problem_domain = any(
        token in text for token in ["bug", "bugs", "incident", "incidents", "probleme", "problemes", "ticket", "tickets"]
    )
    has_solution = _contains_any(text, SOLUTION_KEYWORDS)
    return has_recurring and (has_problem_domain or has_solution)


def _wants_open_only(text: str) -> bool:
    return _contains_any(text, OPEN_TICKET_KEYWORDS) or "open" in text or "ouvert" in text


def _wants_active_only(text: str) -> bool:
    return _contains_any(text, ACTIVE_TICKET_KEYWORDS) or _wants_open_only(text)


def _is_explicit_ticket_create_request(text: str) -> bool:
    normalized = _normalize_intent_text(text)
    return _contains_any(normalized, EXPLICIT_CREATE_TICKET_KEYWORDS)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_recent_ticket_constraints(text: str) -> list[str]:
    """Extract qualifier terms for recent-ticket requests (EN/FR)."""
    normalized = _normalize_intent_text(text or "")
    if not _is_recent_ticket_request(normalized):
        return []

    constraints: list[str] = []

    for match in RECENT_CONSTRAINT_PATTERN.finditer(normalized):
        raw_phrase = " ".join((match.group(1) or "").split())
        if not raw_phrase:
            continue
        phrase_tokens = [
            token
            for token in CONSTRAINT_TOKEN_PATTERN.findall(raw_phrase)
            if token.casefold() not in RECENT_INTENT_STOPWORDS and not token.isdigit()
        ]
        if phrase_tokens:
            constraints.append(" ".join(phrase_tokens[:6]))

    for match in ERROR_CODE_PATTERN.finditer(normalized):
        code = str(match.group(1) or "").strip()
        if code:
            constraints.append(f"error {code}")

    for token in CONSTRAINT_TOKEN_PATTERN.findall(normalized):
        lowered = token.casefold()
        if lowered in RECENT_INTENT_STOPWORDS:
            continue
        if lowered.startswith("tw-"):
            constraints.append(lowered)
            continue
        if lowered.isdigit():
            continue
        constraints.append(lowered)

    return _dedupe_preserve_order(constraints)


def has_recent_ticket_constraints(text: str) -> bool:
    return bool(extract_recent_ticket_constraints(text))


def detect_intent(text: str) -> ChatIntent:
    return detect_intent_with_confidence(text)[0]
