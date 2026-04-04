"""Shared conversational hint vocabularies for intent and session handling."""

from __future__ import annotations

MAX_RECENT_CHAT_TURNS = 8

DETAIL_HINTS = frozenset(
    {
        "status",
        "statut",
        "etat",
        "type",
        "ticket type",
        "kind",
        "priority",
        "priorite",
        "category",
        "categorie",
        "assignee",
        "assigne",
        "owner",
        "reporter",
        "sla",
        "deadline",
        "due",
        "detail",
        "details",
        "summary",
        "resume",
        "info",
        "information",
    }
)

CAUSE_HINTS = frozenset(
    {
        "root cause",
        "cause",
        "why",
        "pourquoi",
        "why did this happen",
        "why is this happening",
        "what caused this",
    }
)

GUIDANCE_HINTS = frozenset(
    {
        "what should i do",
        "what do i do",
        "what should i do next",
        "recommended action",
        "next step",
        "next steps",
        "how do i fix",
        "how do i resolve",
        "how should i fix",
        "how should i resolve",
        "how to fix",
        "how to resolve",
    }
)

SIMILAR_HINTS = frozenset(
    {
        "similar ticket",
        "similar tickets",
        "related ticket",
        "related tickets",
        "other one",
    }
)

LIST_HINTS = frozenset(
    {
        "list",
        "show me",
        "show",
        "tickets",
        "critical tickets",
        "high sla tickets",
        "active tickets",
    }
)

IMPLICIT_REFERENCE_HINTS = frozenset(
    {
        "this ticket",
        "that ticket",
        "the ticket",
        "this one",
        "that one",
        "this issue",
        "that issue",
        "this incident",
        "that incident",
        "and this one",
        "what about this one",
    }
)

SHORT_FOLLOWUP_HINTS = frozenset(
    {
        "why",
        "why?",
        "what about the other one",
        "and this one",
        "what should i do next",
        "what should i do",
        "what do i do",
        "next",
    }
)

COMPARISON_HINTS = frozenset(
    {
        "compare",
        "comparison",
        "versus",
        "vs",
        "difference",
        "previous one",
    }
)

ORDINAL_HINTS: dict[int, tuple[str, ...]] = {
    0: ("first one", "1st one", "first ticket", "premier", "premiere", "le premier"),
    1: ("second one", "2nd one", "second ticket", "deuxieme", "la deuxieme", "le deuxieme"),
    2: ("third one", "3rd one", "third ticket", "troisieme", "la troisieme", "le troisieme"),
}

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
    "high priority",
    "haute priorite",
    "high-priority",
    "priority high",
    "priorite haute",
    "high prio",
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

GUIDANCE_REQUEST_KEYWORDS = [
    "troubleshoot",
    "troubleshooting",
    "help me troubleshoot",
    "help troubleshoot",
    "how do i fix",
    "how do i resolve",
    "how should i fix",
    "how should i resolve",
    "how can i fix",
    "how can i resolve",
    "how to fix",
    "how to resolve",
    "what should i do",
    "what do i do",
    "what should we do",
    "what action should i take",
    "what action should we take",
    "what do you recommend",
    "recommended action",
    "next step",
    "next steps",
    "help me fix",
    "help fix",
    "que dois je faire",
    "que faire",
    "quoi faire",
    "quelle action",
    "action recommandee",
    "prochaine etape",
    "prochaines etapes",
    "comment corriger",
    "comment resoudre",
    "aide moi a corriger",
    "aide moi a resoudre",
    "why is this happening",
    "why is this issue happening",
    "why is this problem happening",
    "why is this ticket happening",
    "why is this incident happening",
    "why is this error happening",
    "pourquoi cela arrive",
    "pourquoi ce probleme arrive",
    "pourquoi ce ticket arrive",
    "pourquoi cette erreur arrive",
]

HELP_REQUEST_KEYWORDS = [
    "help",
    "help me",
    "aide",
    "aide moi",
]

GUIDANCE_CONTEXT_KEYWORDS = [
    "ticket",
    "tw-",
    "problem",
    "pb-",
    "issue",
    "incident",
    "error",
    "bug",
    "this ticket",
    "this issue",
    "this problem",
    "this incident",
    "this error",
    "ce ticket",
    "ce probleme",
    "cet incident",
    "cette erreur",
]

INFO_REQUEST_KEYWORDS = [
    "show ticket",
    "show me",
    "give me",
    "tell me",
    "details",
    "detail",
    "summary",
    "summarize",
    "resume",
    "resumer",
    "info",
    "information",
    "status",
    "statut",
    "etat",
    "type",
    "ticket type",
    "kind",
    "priority",
    "priorite",
    "category",
    "categorie",
    "assignee",
    "assigne",
    "owner",
    "reporter",
    "sla",
    "sla breach",
    "sla at risk",
    "sla a risque",
    "sla risque",
    "at risk",
    "a risque",
    "breached",
    "deadline",
    "due",
    "what happened",
    "list",
    "liste",
    "network tickets",
    "tickets reseau",
    "email tickets",
    "tickets email",
    "security tickets",
    "tickets securite",
    "hardware tickets",
    "tickets materiel",
    "application tickets",
    "tickets application",
    "high priority tickets",
    "tickets haute priorite",
    "open tickets",
    "tickets ouverts",
]

EXPLICIT_CREATE_TICKET_KEYWORDS: list[str] = [
    "create a ticket",
    "open a ticket",
    "create ticket",
    "open ticket",
    "new ticket",
    "submit a ticket",
    "submit ticket",
    "log a ticket",
    "log ticket",
    "raise a ticket",
    "raise ticket",
    "creer un ticket",
    "nouveau ticket",
    "ouvrir un ticket",
    "soumettre un ticket",
    "signaler un ticket",
]

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

# Problem listing shortcuts — routes directly to DB, no LLM, no retrieval.
# Covers status-filtered and unfiltered problem listing requests.
# Added because problem queries were falling through to retrieval pipeline.
PROBLEM_LISTING_KEYWORDS = [
    "problemes ouverts", "problemes en cours", "problemes connus",
    "erreurs connues", "problemes en investigation",
    "problemes resolus", "liste des problemes", "voir les problemes",
    "quels sont les problemes", "affiche les problemes",
    "montre les problemes", "gestion des problemes", "problemes actifs",
    "open problems", "known errors", "known error",
    "problems under investigation", "investigating problems",
    "resolved problems", "list problems", "show problems",
    "show me problems", "problem list", "problem management",
    "active problems", "recurring problems",
    "current problems", "existing problems", "what problems do we have",
    "problems", "what are the problems",
]

# Problem detail shortcuts — agent is asking about one specific problem.
# Triggered when message contains a problem ID pattern (PB-*).
# Routes to problem_detail handler, not retrieval pipeline.
PROBLEM_DETAIL_KEYWORDS = [
    "details du probleme", "infos sur le probleme",
    "problem details", "tell me about problem", "show problem",
    "what is problem", "analyse le probleme",
]

# Problem drill-down — agent wants to see tickets linked to a problem.
# Only fires as a follow-up when a problem is already in session context.
PROBLEM_DRILL_DOWN_KEYWORDS = [
    "tickets lies", "tickets affectes", "montre les tickets",
    "quels tickets", "tickets associes",
    "linked tickets", "affected tickets",
    "which tickets", "related tickets", "tickets for this problem",
    "show linked tickets", "affiche les tickets lies",
]

# Recommendation listing shortcut — routes to DB + cached recommendations.
# Never touches retrieval pipeline.
RECOMMENDATION_LISTING_KEYWORDS = [
    "recommandations", "mes recommandations", "voir les recommandations",
    "liste des recommandations", "suggestions", "affiche les recommandations",
    "quelles sont les recommandations",
    "recommendations", "my recommendations", "show recommendations",
    "list recommendations", "show me recommendations",
    "what are the recommendations", "current recommendations",
    "top recommendations",
]

# Maps intent keywords to problem status filter values.
# Used by the problem listing shortcut handler to apply DB filter.
# Add new entries here when new status-specific keywords are added.
STATUS_KEYWORD_MAP: dict[str, str] = {
    "open problems": "open",
    "problemes ouverts": "open",
    "known errors": "known_error",
    "known error": "known_error",
    "erreurs connues": "known_error",
    "investigating": "investigating",
    "en investigation": "investigating",
    "problemes en investigation": "investigating",
    "resolved problems": "resolved",
    "problemes resolus": "resolved",
}
