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
    "most recent problem", "recent problem", "latest problem",
    "show recent problem", "show the latest problem", "show me the latest problem",
    "show me the most recent problem", "show recent problems", "latest problems",
    "dernier probleme", "probleme recent", "problemes recents", "probleme le plus recent",
    "dernier probleme connu", "affiche le dernier probleme",
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

# ---------------------------------------------------------------------------
# Off-topic embedding guard
# ---------------------------------------------------------------------------

# 28 representative ITSM sentences (EN+FR pairs) used as anchors for the
# embedding-based off-topic guard.  Any message whose max cosine similarity
# to all anchors is below OFFTOPIC_SIMILARITY_THRESHOLD is rejected without
# an LLM call.  Covers 8 ITSM domains in both languages.
ITSM_ANCHOR_PHRASES: list[str] = [
    "how do I create an incident ticket",
    "comment créer un ticket d'incident",
    "what is the status of my ticket",
    "quel est le statut de mon ticket",
    "what is an SLA and how does it work",
    "qu'est-ce que le SLA en gestion de services IT",
    "explain service level agreement",
    "ticket SLA breach escalation priority",
    "what is MFA multi-factor authentication",
    "qu'est-ce que l'authentification multifacteur MFA",
    "VPN connection authentication access issue",
    "problème de connexion VPN accès réseau",
    "network connectivity problem DNS server",
    "problème de réseau DNS connexion serveur",
    "what is DNS and how does it resolve hostnames",
    "application crash software error bug",
    "erreur logicielle panne application bug",
    "hardware failure printer laptop",
    "password reset account lockout security",
    "réinitialisation mot de passe sécurité compte",
    "what is CRM customer relationship management software",
    "what is artificial intelligence in IT",
    "qu'est-ce que l'intelligence artificielle",
    "what is a database and how does it store data",
    "qu'est-ce qu'une base de données",
    "incident management problem management ITIL",
    "gestion des incidents problèmes ITIL",
    "performance monitoring server response time",
]

# Prefixes that signal a definitional / explanatory knowledge question.
# Used by _is_knowledge_query() to route "what is MFA", "qu'est-ce que le SLA"
# to the lightweight chitchat LLM instead of the full RAG pipeline.
KNOWLEDGE_QUERY_PREFIXES: frozenset[str] = frozenset({
    # English
    "what is", "what are", "what does", "what do",
    "define ", "explain ", "how does", "how do",
    "tell me about", "describe ",
    # French
    "qu'est-ce que", "qu'est-ce qu'", "c'est quoi",
    "c'est quoi le", "définit ", "définir ", "expliquer ",
    "explique ", "qu'est", "comment fonctionne", "comment fonctionnent",
    "parle moi de", "décris ",
})

# Short polite rejection returned without any LLM call when the off-topic
# embedding guard identifies a clearly off-topic message.
OFFTOPIC_REJECTION_MESSAGES: dict[str, str] = {
    "fr": (
        "Je suis un assistant ITSM spécialisé dans la gestion des tickets, "
        "incidents et services IT. Je ne peux pas répondre à cette question. "
        "Comment puis-je vous aider sur un sujet IT ?"
    ),
    "en": (
        "I'm an ITSM assistant specialised in ticket management, "
        "incidents, and IT services. I'm not able to help with that topic. "
        "Is there an IT-related question I can assist you with?"
    ),
}
