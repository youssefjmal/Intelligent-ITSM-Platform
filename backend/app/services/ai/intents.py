"""Intent detection helpers and keyword maps for AI chat."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from app.models.enums import TicketStatus

RECENT_TICKET_KEYWORDS = [
    "most recent",
    "latest",
    "last",
    "recent",
    "dernier",
    "plus recent",
    "le plus recent",
]

MOST_USED_TICKET_KEYWORDS = [
    "most used",
    "most common",
    "most frequent",
    "plus utilises",
    "plus frequents",
    "plus courants",
    "plus communs",
]

WEEKLY_SUMMARY_KEYWORDS = [
    "summarize the week",
    "summarize week's activity",
    "summarize the week's activity",
    "weekly activity",
    "week activity",
    "week summary",
    "weekly summary",
    "resume l'activite de la semaine",
    "resumer l'activite de la semaine",
    "activite de la semaine",
    "bilan hebdo",
    "bilan hebdomadaire",
]

OPEN_TICKET_KEYWORDS = [
    "open ticket",
    "opened ticket",
    "ticket ouvert",
    "ticket ouverts",
    "ticket open",
    "tickets open",
]

CRITICAL_TICKET_KEYWORDS = [
    "critical",
    "critique",
    "critiques",
    "urgent",
    "urgents",
    "p0",
    "p1",
]

ACTIVE_TICKET_KEYWORDS = [
    "en cours",
    "in progress",
    "active",
    "actif",
    "actifs",
]

RECURRING_KEYWORDS = [
    "recurrent",
    "recurring",
    "repeat",
    "repeated",
    "recurrents",
    "recurrentes",
    "repetitif",
    "repetitifs",
    "repetitive",
    "repetitives",
    "repetes",
]

SOLUTION_KEYWORDS = [
    "solution",
    "solutions",
    "fix",
    "fixes",
    "correctif",
    "correctifs",
    "resolution",
    "resoudre",
    "resolve",
    "recommend",
    "recommande",
    "recommandation",
    "recommandations",
]

EXPLICIT_CREATE_TICKET_KEYWORDS = [
    "create a ticket",
    "create a card",
    "create card",
    "create a task",
    "create task",
    "generate a ticket",
    "draft a ticket",
    "open a ticket",
    "raise a ticket",
    "log a ticket",
    "submit a ticket",
    "generate ticket",
    "draft ticket",
    "new ticket",
    "open an incident",
    "ticket creation",
    "create ticket",
    "ouvrir un ticket",
    "cree un ticket",
    "creer un ticket",
    "creer ticket",
    "creer un nouveau ticket",
    "generer un ticket",
    "genere un ticket",
    "generer ticket",
    "je vais creer un ticket",
    "je veux creer un ticket",
    "i want to create a ticket",
    "i want to create a card",
    "i want to create card",
    "i want to create a task",
    "i will create a ticket",
    "i will create a card",
    "i am going to create a ticket",
    "i am going to create a card",
    "ouvrir un incident",
    "declarer un incident",
    "signaler un incident",
    "creation ticket",
]

ACTIVE_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}
TICKET_ID_PATTERN = re.compile(r"\bTW-\d{3,}\b", re.IGNORECASE)
RECENT_CONSTRAINT_PATTERN = re.compile(
    r"\b(?:about|with|for|regarding|sur|avec|pour|concernant|qui|where|containing)\s+([a-z0-9][a-z0-9 _\-/\.]{1,80})\b",
    re.IGNORECASE,
)
ERROR_CODE_PATTERN = re.compile(r"\b(?:error|erreur|code)\s*([0-9]{3,5})\b", re.IGNORECASE)
CONSTRAINT_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-_/\.]{2,}", re.IGNORECASE)

RECENT_INTENT_STOPWORDS = {
    "ticket",
    "tickets",
    "most",
    "recent",
    "latest",
    "last",
    "dernier",
    "derniere",
    "plus",
    "le",
    "la",
    "les",
    "du",
    "des",
    "de",
    "d",
    "open",
    "opened",
    "ouvert",
    "ouverts",
    "active",
    "actif",
    "actifs",
    "en",
    "cours",
    "about",
    "with",
    "for",
    "regarding",
    "sur",
    "avec",
    "pour",
    "concernant",
    "where",
    "containing",
}


class ChatIntent(str, Enum):
    create_ticket = "create_ticket"
    recent_ticket = "recent_ticket"
    most_used_tickets = "most_used_tickets"
    weekly_summary = "weekly_summary"
    critical_tickets = "critical_tickets"
    recurring_solutions = "recurring_solutions"
    data_query = "data_query"
    general = "general"


def _normalize_locale(locale: str | None) -> str:
    return "en" if (locale or "").lower().startswith("en") else "fr"


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


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


def _looks_like_data_query(text: str) -> bool:
    data_tokens = [
        "ticket",
        "tickets",
        "tw-",
        "mttr",
        "reassign",
        "reaffectation",
        "premiere action",
        "first action",
        "resolution rate",
        "taux de resolution",
        "combien",
        "how many",
        "statut",
        "status",
        "priorite",
        "priority",
        "categorie",
        "category",
        "assignee",
        "assigne",
    ]
    return any(token in text for token in data_tokens)


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
    normalized = _normalize_intent_text(text or "")
    if _is_explicit_ticket_create_request(text or ""):
        return ChatIntent.create_ticket
    if _is_recent_ticket_request(normalized):
        return ChatIntent.recent_ticket
    if _is_most_used_request(normalized):
        return ChatIntent.most_used_tickets
    if _is_weekly_summary_request(normalized):
        return ChatIntent.weekly_summary
    if _is_critical_ticket_request(normalized):
        return ChatIntent.critical_tickets
    if _is_recurring_solution_request(normalized):
        return ChatIntent.recurring_solutions
    if _looks_like_data_query(normalized):
        return ChatIntent.data_query
    return ChatIntent.general
