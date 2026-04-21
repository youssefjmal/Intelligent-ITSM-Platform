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
from typing import Literal

from app.services.ai.conversation_policy import (
    ACTIVE_TICKET_KEYWORDS,
    CRITICAL_TICKET_KEYWORDS,
    EXPLICIT_CREATE_TICKET_KEYWORDS,
    GUIDANCE_CONTEXT_KEYWORDS,
    GUIDANCE_REQUEST_KEYWORDS,
    HELP_REQUEST_KEYWORDS,
    INFO_REQUEST_KEYWORDS,
    ITSM_ANCHOR_PHRASES,
    KNOWLEDGE_QUERY_PREFIXES,
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
    # Ticket thread (comments + resolution)
    ticket_thread = "ticket_thread"
    # Trivial / off-topic — bypass retrieval pipeline
    chitchat = "chitchat"


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


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_FR_ACCENT_CHARS: frozenset[str] = frozenset("éèêëàâäîïôùûüçœæÉÈÊËÀÂÄÎÏÔÙÛÜÇŒÆ")

_FR_STOPWORDS: frozenset[str] = frozenset({
    "je", "tu", "il", "elle", "nous", "vous", "ils", "elles",
    "le", "la", "les", "de", "du", "des", "une", "un",
    "est", "sont", "c'est", "qu'est", "qu'il", "qu'elle",
    "bonjour", "merci", "salut", "bonsoir", "oui", "non",
    "mais", "avec", "pour", "dans", "sur", "par",
    "et", "ne", "pas", "plus", "que", "qui", "quoi",
    "mon", "ma", "mes", "moi", "ouvert", "resolu", "ferme",
    "nouveau", "bilan",
})

_EN_ONLY_ARTICLES: frozenset[str] = frozenset({"the", "a", "an", "my", "your", "our", "their"})


def detect_language(text: str) -> Literal["fr", "en"]:
    """Heuristically detect whether *text* is French or English.

    Priority:
    1. Any French accented character → immediately "fr".
    2. FR stopword count vs EN-only article count in first 20 tokens.

    Falls back to "en" when no French signal is found.
    """
    raw = (text or "").strip()
    if not raw:
        return "en"
    if any(ch in _FR_ACCENT_CHARS for ch in raw):
        return "fr"
    tokens = raw.lower().split()[:20]
    fr_hits = sum(1 for tok in tokens if tok.rstrip("?!.,;:") in _FR_STOPWORDS)
    en_only_hits = sum(1 for tok in tokens if tok.rstrip("?!.,;:") in _EN_ONLY_ARTICLES)
    if fr_hits >= 2 or (fr_hits >= 1 and en_only_hits == 0):
        return "fr"
    return "en"


# ---------------------------------------------------------------------------
# Off-topic embedding guard helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _is_clearly_offtopic(text: str) -> bool:
    """Return True if the message is semantically unrelated to ITSM topics.

    Computes cosine similarity between the message embedding and 28 ITSM
    anchor phrases.  Returns True only when max similarity < threshold.
    Gracefully returns False (pass-through) on any embedding failure.
    """
    from app.core.config import settings  # lazy import avoids circular dependency  # noqa: PLC0415
    try:
        from app.services.embeddings import compute_embedding  # noqa: PLC0415
    except Exception:
        return False

    normalized = _normalize_intent_text(text or "")
    if not normalized:
        return False

    try:
        query_vec = compute_embedding(normalized)
    except Exception as exc:
        logger.info("Off-topic guard: query embedding failed, skipping: %s", exc)
        return False

    max_sim = 0.0
    best_anchor = ""
    for phrase in ITSM_ANCHOR_PHRASES:
        try:
            anchor_vec = compute_embedding(phrase)
        except Exception:
            continue
        sim = _cosine_similarity(query_vec, anchor_vec)
        if sim > max_sim:
            max_sim = sim
            best_anchor = phrase
        if max_sim >= settings.OFFTOPIC_SIMILARITY_THRESHOLD:
            logger.info(
                "Off-topic guard accepted ITSM context: max_similarity=%.3f threshold=%.3f best_anchor=%r",
                max_sim,
                settings.OFFTOPIC_SIMILARITY_THRESHOLD,
                best_anchor,
            )
            return False  # short-circuit: message is ITSM-related

    logger.info(
        "Off-topic guard verdict: rejected=%s max_similarity=%.3f threshold=%.3f best_anchor=%r",
        max_sim < settings.OFFTOPIC_SIMILARITY_THRESHOLD,
        max_sim,
        settings.OFFTOPIC_SIMILARITY_THRESHOLD,
        best_anchor,
    )
    return max_sim < settings.OFFTOPIC_SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# ITSM knowledge query detector
# ---------------------------------------------------------------------------

_ITSM_KNOWLEDGE_TERMS: frozenset[str] = frozenset({
    "vpn", "dns", "ssl", "tls", "smtp", "http", "https", "api", "ldap", "ssh",
    "dhcp", "tcp", "ip", "nat", "firewall",
    "sla", "itil", "cmdb", "rca", "itsm", "mttr", "mtta", "kpi",
    "incident", "problem", "change", "request", "ticket",
    "mfa", "2fa", "sso", "oauth", "saml", "authentication", "autorisation",
    "authentification", "permission",
    "crm", "erp", "saas", "iaas", "paas", "cloud",
    "database", "base de donnees",
    "active directory", "gpo",
    "ai", "intelligence artificielle", "machine learning",
    "encryption", "chiffrement", "certificat", "certificate",
    "proxy", "load balancer", "reverse proxy",
})

# Procedural "how do I <action>" prefixes — excluded from knowledge fast-path
# because they represent troubleshooting requests, not definitional questions.
_PROCEDURAL_HOW_PREFIXES: frozenset[str] = frozenset({
    "how do i fix", "how do i resolve", "how do i reset", "how do i restart",
    "how do i configure", "how do i install", "how do i set up", "how do i setup",
    "how do i update", "how do i change", "how do i create", "how do i delete",
    "how do i remove", "how do i enable", "how do i disable", "how do i troubleshoot",
    "how do i handle", "how do i deal with", "how do i migrate", "how do i upgrade",
    "how should i fix", "how should i resolve", "how should i configure",
    "how can i fix", "how can i resolve", "how can i configure",
    "comment corriger", "comment resoudre", "comment configurer", "comment installer",
    "comment reinitialiser", "comment redemarrer", "comment reparer",
})


def _is_knowledge_query(text: str) -> bool:
    """Return True if the message is a definitional question about an IT/ITSM topic.

    Both conditions must hold: a knowledge prefix AND an ITSM/IT term.
    This prevents "what is football" from matching, and excludes procedural
    "how do I fix/configure/reset..." queries which should go through the resolver.
    """
    if not text:
        return False
    # Exclude procedural action queries before checking knowledge prefixes
    if any(text.startswith(prefix) for prefix in _PROCEDURAL_HOW_PREFIXES):
        return False
    has_prefix = any(text.startswith(prefix) for prefix in KNOWLEDGE_QUERY_PREFIXES)
    if not has_prefix:
        return False
    return any(_matches_keyword(text, term) for term in _ITSM_KNOWLEDGE_TERMS)


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


def _has_contextual_reference(text: str) -> bool:
    contextual_phrases = [
        "this one",
        "that one",
        "other one",
        "first one",
        "second one",
        "third one",
        "previous one",
        "first ticket",
        "second ticket",
        "third ticket",
        "this ticket",
        "that ticket",
        "the ticket",
        "this issue",
        "that issue",
        "this incident",
        "that incident",
    ]
    return any(token in text for token in contextual_phrases)


def _looks_like_contextual_followup(text: str) -> bool:
    if not _has_contextual_reference(text):
        return False
    followup_tokens = [
        "show",
        "tell me",
        "what happened",
        "what about",
        "compare",
        "versus",
        "vs",
        "why",
        "cause",
        "root cause",
        "fix",
        "resolve",
        "comments",
        "resolution",
        "status",
        "details",
        "summary",
        "linked",
        "similar",
    ]
    return any(token in text for token in followup_tokens)


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


_TICKET_THREAD_KEYWORDS = [
    # English — comments (multi-word phrases, substring match)
    "show comments", "show the comments", "show me the comments", "show me comments",
    "list comments", "display comments", "see comments", "see the comments",
    "what are the comments", "what did people say", "what was said",
    "comments on this ticket", "comments on ticket", "ticket comments",
    "any comments", "get comments", "read comments",
    # English — resolution (multi-word phrases, substring match)
    "show resolution", "show the resolution", "what is the resolution",
    "what was the resolution", "how was it resolved", "resolution of this ticket",
    "ticket resolution", "resolved how", "how was this resolved",
    "see the resolution", "get the resolution",
    # French — comments
    "affiche les commentaires", "montre les commentaires", "commentaires du ticket",
    "voir les commentaires", "quels sont les commentaires", "les commentaires",
    "montre moi les commentaires", "affiche moi les commentaires",
    # French — resolution
    "affiche la resolution", "montre la resolution", "quelle est la resolution",
    "comment a ete resolu", "resolution du ticket", "la resolution",
    "voir la resolution", "montre moi la resolution",
]


_TICKET_THREAD_SINGLE_WORDS = [
    # Word-boundary matched — broad but specific enough to avoid false positives
    "commentaires",   # FR plural, rarely appears outside ticket context in chat
    "commentaire",    # FR singular
]


def _is_ticket_thread_request(text: str) -> bool:
    normalized = _normalize_intent_text(text or "")
    if _contains_any(normalized, _TICKET_THREAD_KEYWORDS):
        return True
    # Single-word fallback: "commentaires" / "commentaire" alone is unambiguous
    return _contains_any(normalized, _TICKET_THREAD_SINGLE_WORDS)


# ---------------------------------------------------------------------------
# Chitchat / off-topic detection
# ---------------------------------------------------------------------------

_CHITCHAT_EXACT_WORDS = frozenset([
    # Acknowledgements EN
    "ok", "okay", "k", "yep", "yup", "yeah", "yes", "no", "nope", "sure",
    "thanks", "thank you", "thx", "ty", "noted", "got it", "understood", "great",
    "cool", "nice", "perfect", "good", "fine", "alright", "right", "exactly",
    # Acknowledgements FR
    "oui", "non", "ok", "ouais", "ouaip", "merci", "super", "bien", "parfait",
    "compris", "recu", "d'accord", "daccord", "entendu", "nickel", "top",
    "genial", "exact", "correct", "formidable",
    # Greetings EN
    "hello", "hi", "hey", "howdy",
    # Greetings FR
    "bonjour", "salut", "bonsoir", "coucou", "allo",
    # Farewells
    "bye", "goodbye", "ciao", "aurevoir", "au revoir", "bonne journee",
])

# ITSM-relevant tokens — if ANY appear, the message is not off-topic
_ITSM_SIGNAL_TOKENS = frozenset([
    # Ticket / incident vocabulary
    "ticket", "incident", "problème", "probleme", "bug", "erreur", "error",
    "panne", "crash", "issue", "defect", "fault",
    # IT infra
    "vpn", "réseau", "reseau", "network", "serveur", "server", "base de donnees",
    "database", "api", "application", "logiciel", "software", "hardware",
    "imprimante", "printer", "wifi", "connexion", "connection", "acces", "accès",
    "access", "permission", "authentification", "authentication", "mot de passe",
    "password", "compte", "account", "email", "mail", "smtp", "dns", "ssl",
    # ITSM process
    "sla", "priority", "priorité", "assignee", "assigné", "résolution", "resolution",
    "escalade", "escalation", "notification", "alerte", "alert", "classification",
    "catégorie", "categorie", "category", "statut", "status",
    # Actions on tickets
    "classifier", "classer", "assigner", "assign", "résoudre", "resolve", "fermer",
    "close", "escalader", "escalate", "ouvrir", "open", "créer", "create",
    "signaler", "report", "afficher", "montrer", "show", "lister", "list",
])

_MAX_CHITCHAT_LENGTH = 40  # chars — messages longer than this always go through normal routing


def _has_itsm_signal(text: str) -> bool:
    """Return True if the message contains at least one ITSM-relevant token."""
    normalized = _normalize_intent_text(text or "")
    return any(_matches_keyword(normalized, token) for token in _ITSM_SIGNAL_TOKENS)


def is_chitchat_or_offtopic(text: str) -> bool:
    """Return True if the message should bypass the retrieval pipeline.

    Fires for:
    - Pure acknowledgements / greetings (exact word list)
    - Short messages (< 40 chars) with no ITSM signal and no ticket ID
    """
    raw = (text or "").strip()
    if not raw:
        return False
    normalized = _normalize_intent_text(raw)

    # Ticket ID present → always ITSM context
    if extract_ticket_id(raw):
        return False

    # Exact single-word/phrase match → definitely chitchat
    if normalized in _CHITCHAT_EXACT_WORDS:
        return True

    # Short message with no ITSM signal → off-topic
    if len(raw) <= _MAX_CHITCHAT_LENGTH and not _has_itsm_signal(normalized):
        return True

    return False


def _should_apply_offtopic_guard(raw_text: str, normalized: str) -> bool:
    """Apply the embedding guard only to unresolved weak-signal prompts.

    This keeps structured ITSM traffic on the deterministic path and limits the
    semantic off-topic check to the ambiguous long-form prompts it is meant for.
    """
    raw = (raw_text or "").strip()
    if len(raw) <= _MAX_CHITCHAT_LENGTH:
        return False
    if extract_ticket_id(raw) or extract_problem_id(raw):
        return False
    if _is_knowledge_query(normalized):
        return False
    if _has_itsm_signal(normalized):
        return False
    return True


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


def detect_intent_with_confidence(text: str) -> tuple[ChatIntent, IntentConfidence, bool]:
    """Detect intent with confidence using rule-based checks.

    Returns a 3-tuple of (intent, confidence, offtopic_guard_fired).
    offtopic_guard_fired is True only when _is_clearly_offtopic() triggered.
    """
    normalized = _normalize_intent_text(text or "")

    # ── Structured ITSM intents — checked BEFORE the knowledge fast-path ──
    # "what are the problems?" has prefix "what are" + ITSM term "problem",
    # so it would match _is_knowledge_query if not intercepted here first.
    problem_id = extract_problem_id(text or "")
    if problem_id and (_looks_like_guidance_request(normalized) or _is_problem_analysis_request(normalized)):
        return ChatIntent.general, IntentConfidence.high, False
    if problem_id and _is_problem_drill_down_request(normalized):
        return ChatIntent.problem_drill_down, IntentConfidence.high, False
    if _is_problem_detail_request(normalized, has_problem_id=bool(problem_id)):
        return ChatIntent.problem_detail, IntentConfidence.high, False
    if _is_problem_drill_down_request(normalized) and not any(
        token in normalized for token in ["similar", "semblable", "ressemble"]
    ):
        return ChatIntent.problem_drill_down, IntentConfidence.high, False
    if _is_problem_listing_request(normalized):
        return ChatIntent.problem_listing, IntentConfidence.high, False
    if _is_recommendation_listing_request(normalized):
        return ChatIntent.recommendation_listing, IntentConfidence.high, False

    # ── ITSM knowledge query fast-path ────────────────────────────────────
    # Routes "what is MFA", "qu'est-ce que le SLA" to the lightweight
    # chitchat LLM instead of the full RAG pipeline.
    # Runs after structured intent checks so listing requests like
    # "what are the problems?" are not incorrectly caught here.
    if _is_knowledge_query(normalized):
        return ChatIntent.chitchat, IntentConfidence.high, False
    if _is_ticket_thread_request(normalized):
        return ChatIntent.ticket_thread, IntentConfidence.high, False
    # Existing checks below (unchanged)
    if _is_explicit_ticket_create_request(text or ""):
        return ChatIntent.create_ticket, IntentConfidence.high, False
    if _is_recent_ticket_request(normalized):
        return ChatIntent.recent_ticket, IntentConfidence.high, False
    if _is_most_used_request(normalized):
        return ChatIntent.most_used_tickets, IntentConfidence.high, False
    if _is_weekly_summary_request(normalized):
        return ChatIntent.weekly_summary, IntentConfidence.high, False
    if _is_critical_ticket_request(normalized):
        return ChatIntent.critical_tickets, IntentConfidence.high, False
    if _is_recurring_solution_request(normalized):
        return ChatIntent.recurring_solutions, IntentConfidence.high, False
    if _has_explicit_guidance_keyword(normalized):
        return ChatIntent.general, IntentConfidence.high, False
    if _looks_like_guidance_request(normalized):
        return ChatIntent.general, IntentConfidence.medium, False
    if _looks_like_info_request(normalized):
        return ChatIntent.data_query, IntentConfidence.high, False
    if _looks_like_contextual_followup(normalized):
        return ChatIntent.general, IntentConfidence.medium, False
    if _looks_like_data_query(normalized):
        return ChatIntent.data_query, IntentConfidence.medium, False
    # Only unresolved, weak-signal prompts should hit the semantic off-topic
    # guard. This keeps the deterministic rules easy to reason about.
    if _should_apply_offtopic_guard(text or "", normalized):
        try:
            if _is_clearly_offtopic(normalized):
                return ChatIntent.chitchat, IntentConfidence.high, True
        except Exception as _guard_exc:  # noqa: BLE001
            logger.info("Off-topic guard error; continuing normal routing: %s", _guard_exc)
    # Chitchat / off-topic — checked last so all specific shortcuts take priority.
    # Returns high confidence to skip the LLM intent-classification call.
    if is_chitchat_or_offtopic(text or ""):
        return ChatIntent.chitchat, IntentConfidence.high, False
    return ChatIntent.general, IntentConfidence.low, False


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
    intent, confidence, source, guidance_requested, offtopic_guard = detect_intent_hybrid_details(text)
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

    meta = _inventory_filter_meta(normalized, inventory_kind=inventory_kind)
    meta["offtopic_guard"] = offtopic_guard
    return ChatIntentDetails(
        intent=intent,
        confidence=confidence,
        source=source,
        guidance_requested=guidance_requested,
        entity_kind=entity_kind,
        entity_id=entity_id,
        inventory_kind=inventory_kind,
        filter_meta=meta,
    )


def detect_intent_hybrid_details(
    text: str,
) -> tuple[ChatIntent, IntentConfidence, str, bool, bool]:
    """Detect intent with confidence using rule-based detection first, LLM fallback second.

    Returns a 5-tuple of (intent, confidence, source, is_guidance, offtopic_guard):
    - intent: the detected ChatIntent enum value.
    - confidence: IntentConfidence reflecting the actual detection quality.
    - source: one of ``"rules"``, ``"rules_default"``, ``"llm_fallback"``.
    - is_guidance: True if the intent maps to the guidance/troubleshooting domain.
    - offtopic_guard: True when the embedding off-topic guard fired.

    Args:
        text: Raw user message (not pre-normalized).
    """
    normalized = _normalize_intent_text(text or "")
    intent, confidence, offtopic_guard = detect_intent_with_confidence(normalized)
    if confidence == IntentConfidence.high:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules", guidance, offtopic_guard
    if confidence == IntentConfidence.medium and intent != ChatIntent.general:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules", guidance, offtopic_guard

    llm_label = _classify_intent_llm_label(text)
    if llm_label is None:
        guidance = _coarse_label_from_rule_intent(intent, normalized) == "guidance"
        return intent, confidence, "rules_default", guidance, offtopic_guard
    llm_intent = _map_llm_label_to_intent(llm_label)
    guidance = llm_label == "guidance"
    if guidance and _looks_like_guidance_request(normalized):
        llm_confidence = IntentConfidence.medium
    else:
        llm_confidence = IntentConfidence(LLM_FALLBACK_DEFAULT_CONFIDENCE)
    return llm_intent, llm_confidence, "llm_fallback", guidance, False


def detect_intent_hybrid(text: str) -> ChatIntent:
    return detect_intent_hybrid_details(text)[0]  # 5-tuple; index 0 = intent


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
