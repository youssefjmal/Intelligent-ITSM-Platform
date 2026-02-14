"""AI endpoints backed by local rule-based logic until Ollama is wired."""

from __future__ import annotations

from fastapi import APIRouter, Depends
import datetime as dt
import re
import unicodedata
from collections import Counter
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ai import AIRecommendationOut, ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse, TicketDraft
from app.services.ai import build_chat_reply, classify_ticket, score_recommendations
from app.services.jira_kb import build_jira_knowledge_block
from app.services.tickets import compute_problem_insights, compute_stats, list_tickets_for_user, select_best_assignee
from app.services.users import list_assignees

router = APIRouter(dependencies=[Depends(rate_limit("ai")), Depends(get_current_user)])

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
    "i will create a ticket",
    "i am going to create a ticket",
    "ouvrir un incident",
    "declarer un incident",
    "signaler un incident",
    "creation ticket",
]

ACTIVE_STATUSES = {TicketStatus.open, TicketStatus.in_progress, TicketStatus.pending}
TICKET_ID_PATTERN = re.compile(r"\bTW-\d{3,}\b", re.IGNORECASE)

STATUS_QUERY_KEYWORDS = {
    TicketStatus.open: ["open", "opened", "ouvert", "ouverts"],
    TicketStatus.in_progress: ["in progress", "in-progress", "en cours", "cours"],
    TicketStatus.pending: ["pending", "en attente", "attente"],
    TicketStatus.resolved: ["resolved", "resolu", "resolus"],
    TicketStatus.closed: ["closed", "clos", "ferme", "fermes"],
}

PRIORITY_QUERY_KEYWORDS = {
    TicketPriority.critical: ["critical", "critique", "urgent", "p0", "p1"],
    TicketPriority.high: ["high", "haute", "elevee"],
    TicketPriority.medium: ["medium", "moyenne", "normal"],
    TicketPriority.low: ["low", "basse", "faible"],
}

CATEGORY_QUERY_KEYWORDS = {
    TicketCategory.infrastructure: ["infrastructure", "infra", "serveur", "servers"],
    TicketCategory.network: ["network", "reseau", "vpn", "switch", "router"],
    TicketCategory.security: ["security", "securite", "acces", "access"],
    TicketCategory.application: ["application", "app", "logiciel", "software", "bug"],
    TicketCategory.service_request: ["service request", "service_request", "demande de service", "request"],
    TicketCategory.hardware: ["hardware", "materiel", "pc", "laptop", "printer", "peripherique"],
    TicketCategory.email: ["email", "mail", "outlook", "boite mail"],
    TicketCategory.problem: ["problem", "probleme", "root cause", "rca"],
}


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
    without_marks = without_marks.replace("’", "'")
    return re.sub(r"\s+", " ", without_marks).strip()


PRIORITY_LABELS = {
    "en": {
        "critical": "Critical",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    },
    "fr": {
        "critical": "Critique",
        "high": "Haute",
        "medium": "Moyenne",
        "low": "Basse",
    },
}

STATUS_LABELS = {
    "en": {
        "open": "Open",
        "in-progress": "In progress",
        "in_progress": "In progress",
        "pending": "Pending",
        "resolved": "Resolved",
        "closed": "Closed",
    },
    "fr": {
        "open": "Ouvert",
        "in-progress": "En cours",
        "in_progress": "En cours",
        "pending": "En attente",
        "resolved": "Resolu",
        "closed": "Clos",
    },
}


def _format_created_at(created_at) -> str:
    if isinstance(created_at, dt.datetime):
        return created_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "unknown"


def _priority_label(value: str, lang: str) -> str:
    return PRIORITY_LABELS.get(lang, {}).get(value, value)


def _status_label(value: str, lang: str) -> str:
    return STATUS_LABELS.get(lang, {}).get(value, value)


def _match_keyword_map(text: str, mapping: dict) -> set:
    matches = set()
    for value, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            matches.add(value)
    return matches


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


def _extract_assignee_mentions(text: str, assignee_names: list[str]) -> set[str]:
    lowered = text.casefold()
    return {
        name
        for name in assignee_names
        if name and name.casefold() in lowered
    }


def _format_scope_summary(meta: dict, lang: str) -> str:
    parts: list[str] = []
    statuses = meta.get("statuses") or set()
    priorities = meta.get("priorities") or set()
    categories = meta.get("categories") or set()
    assignees = meta.get("assignees") or set()
    window_days = meta.get("window_days")

    if statuses:
        labels = ", ".join(_status_label(status.value, lang) for status in sorted(statuses, key=lambda s: s.value))
        parts.append(("Status: " if lang == "en" else "Statut: ") + labels)
    if priorities:
        labels = ", ".join(_priority_label(priority.value, lang) for priority in sorted(priorities, key=lambda p: p.value))
        parts.append(("Priority: " if lang == "en" else "Priorite: ") + labels)
    if categories:
        labels = ", ".join(category.value for category in sorted(categories, key=lambda c: c.value))
        parts.append(("Category: " if lang == "en" else "Categorie: ") + labels)
    if assignees:
        labels = ", ".join(sorted(assignees))
        parts.append(("Assignee: " if lang == "en" else "Assigne: ") + labels)
    if window_days:
        parts.append(
            (f"Window: last {window_days} day(s)" if lang == "en" else f"Fenetre: {window_days} dernier(s) jour(s)")
        )
    return " | ".join(parts)


def _filter_tickets_for_query(text: str, tickets: list, assignee_names: list[str]) -> tuple[list, dict]:
    statuses = _match_keyword_map(text, STATUS_QUERY_KEYWORDS)
    priorities = _match_keyword_map(text, PRIORITY_QUERY_KEYWORDS)
    categories = _match_keyword_map(text, CATEGORY_QUERY_KEYWORDS)
    assignees = _extract_assignee_mentions(text, assignee_names)
    window_days = _detect_window_days(text)

    if not statuses and _wants_active_only(text):
        statuses = set(ACTIVE_STATUSES)

    filtered = tickets
    if statuses:
        filtered = [ticket for ticket in filtered if ticket.status in statuses]
    if priorities:
        filtered = [ticket for ticket in filtered if ticket.priority in priorities]
    if categories:
        filtered = [ticket for ticket in filtered if ticket.category in categories]
    if assignees:
        filtered = [ticket for ticket in filtered if ticket.assignee in assignees]
    if window_days:
        now = dt.datetime.now(dt.timezone.utc)
        cutoff = now - dt.timedelta(days=window_days)
        filtered = [ticket for ticket in filtered if ticket.created_at >= cutoff]

    meta = {
        "statuses": statuses,
        "priorities": priorities,
        "categories": categories,
        "assignees": assignees,
        "window_days": window_days,
    }
    return filtered, meta


def _compute_data_metrics(tickets: list) -> dict:
    resolved = [
        ticket
        for ticket in tickets
        if ticket.resolved_at and ticket.created_at
    ]
    first_actions = [
        ticket
        for ticket in tickets
        if ticket.first_action_at and ticket.created_at
    ]

    mttr_hours = None
    if resolved:
        mttr_hours = sum(
            (ticket.resolved_at - ticket.created_at).total_seconds()
            for ticket in resolved
        ) / len(resolved) / 3600

    avg_first_action_hours = None
    if first_actions:
        avg_first_action_hours = sum(
            (ticket.first_action_at - ticket.created_at).total_seconds()
            for ticket in first_actions
        ) / len(first_actions) / 3600

    reassigned = sum(1 for ticket in tickets if int(getattr(ticket, "assignment_change_count", 0) or 0) > 0)
    reassignment_rate = (reassigned / len(tickets) * 100) if tickets else 0.0

    resolution_rate = (
        sum(1 for ticket in tickets if ticket.status in {TicketStatus.resolved, TicketStatus.closed}) / len(tickets) * 100
        if tickets
        else 0.0
    )

    return {
        "mttr_hours": mttr_hours,
        "avg_first_action_hours": avg_first_action_hours,
        "reassignment_rate": reassignment_rate,
        "reassigned_count": reassigned,
        "resolution_rate": resolution_rate,
    }


def _format_ticket_digest(tickets: list, lang: str, *, header: str, limit: int = 8) -> str:
    lines = [header]
    top = tickets[:limit]
    for ticket in top:
        priority = _priority_label(ticket.priority.value, lang)
        status = _status_label(ticket.status.value, lang)
        assignee = ticket.assignee or ("Unassigned" if lang == "en" else "Non assigne")
        lines.append(f"- {ticket.id} | {ticket.title} | {priority} | {status} | {assignee}")
    if len(tickets) > len(top):
        if lang == "en":
            lines.append(f"... and {len(tickets) - len(top)} more.")
        else:
            lines.append(f"... et {len(tickets) - len(top)} autres.")
    return "\n".join(lines)


def _format_ticket_detail(ticket, lang: str) -> str:
    created = _format_created_at(ticket.created_at)
    updated = _format_created_at(ticket.updated_at)
    priority = _priority_label(ticket.priority.value, lang)
    status = _status_label(ticket.status.value, lang)
    category = ticket.category.value
    assignee = ticket.assignee or ("Unassigned" if lang == "en" else "Non assigne")
    reporter = ticket.reporter or "N/A"
    tags = ", ".join(ticket.tags or []) or ("none" if lang == "en" else "aucun")
    if lang == "en":
        return (
            f"Ticket {ticket.id} details:\n"
            f"- Title: {ticket.title}\n"
            f"- Status: {status}\n"
            f"- Priority: {priority}\n"
            f"- Category: {category}\n"
            f"- Assignee: {assignee}\n"
            f"- Reporter: {reporter}\n"
            f"- Created: {created}\n"
            f"- Updated: {updated}\n"
            f"- Tags: {tags}"
        )
    return (
        f"Details du ticket {ticket.id} :\n"
        f"- Titre: {ticket.title}\n"
        f"- Statut: {status}\n"
        f"- Priorite: {priority}\n"
        f"- Categorie: {category}\n"
        f"- Assigne: {assignee}\n"
        f"- Reporter: {reporter}\n"
        f"- Cree: {created}\n"
        f"- Mis a jour: {updated}\n"
        f"- Tags: {tags}"
    )


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


def _answer_data_query(question: str, tickets: list, lang: str, assignee_names: list[str]) -> tuple[str, str | None, TicketDraft | None] | None:
    text = _normalize_intent_text(question or "")
    if not _looks_like_data_query(text):
        return None

    ticket_id_match = TICKET_ID_PATTERN.search(question or "")
    if ticket_id_match:
        requested_id = ticket_id_match.group(0).upper()
        selected = next((ticket for ticket in tickets if ticket.id.upper() == requested_id), None)
        if not selected:
            reply = f"Ticket {requested_id} not found." if lang == "en" else f"Ticket {requested_id} introuvable."
            return reply, None, None
        return _format_ticket_detail(selected, lang), "show_ticket", _ticket_to_summary(selected, lang)

    filtered, meta = _filter_tickets_for_query(text, tickets, assignee_names)
    scope = _format_scope_summary(meta, lang)
    metrics = _compute_data_metrics(filtered)

    if _is_mttr_request(text):
        if metrics["mttr_hours"] is None:
            reply = "No resolved tickets in this scope to compute MTTR." if lang == "en" else "Aucun ticket resolu dans ce scope pour calculer le MTTR."
            if scope:
                reply = f"{reply}\n{scope}"
            return reply, None, None
        mttr_value = round(metrics["mttr_hours"], 2)
        reply = f"MTTR: {mttr_value} hours on {len(filtered)} ticket(s)." if lang == "en" else f"MTTR: {mttr_value} heures sur {len(filtered)} ticket(s)."
        if scope:
            reply = f"{reply}\n{scope}"
        return reply, None, None

    if _is_first_action_request(text):
        if metrics["avg_first_action_hours"] is None:
            reply = "No first-action timestamp available in this scope." if lang == "en" else "Aucune date de premiere action disponible dans ce scope."
            if scope:
                reply = f"{reply}\n{scope}"
            return reply, None, None
        value = round(metrics["avg_first_action_hours"], 2)
        reply = (
            f"Average time to first action: {value} hours."
            if lang == "en"
            else f"Temps moyen avant premiere action: {value} heures."
        )
        if scope:
            reply = f"{reply}\n{scope}"
        return reply, None, None

    if _is_reassignment_request(text):
        value = round(metrics["reassignment_rate"], 2)
        reassigned_count = int(metrics["reassigned_count"])
        reply = (
            f"Reassignment rate: {value}% ({reassigned_count}/{len(filtered)} tickets)."
            if lang == "en"
            else f"Taux de reassignation: {value}% ({reassigned_count}/{len(filtered)} tickets)."
        )
        if scope:
            reply = f"{reply}\n{scope}"
        return reply, None, None

    if _is_resolution_rate_request(text):
        value = round(metrics["resolution_rate"], 2)
        reply = (
            f"Resolution rate: {value}% ({len(filtered)} ticket(s) in scope)."
            if lang == "en"
            else f"Taux de resolution: {value}% ({len(filtered)} ticket(s) dans le scope)."
        )
        if scope:
            reply = f"{reply}\n{scope}"
        return reply, None, None

    if _is_count_request(text):
        if lang == "en":
            reply = f"Count: {len(filtered)} ticket(s)."
        else:
            reply = f"Total: {len(filtered)} ticket(s)."
        if scope:
            reply = f"{reply}\n{scope}"
        return reply, None, None

    if _is_listing_request(text) or "ticket" in text:
        if not filtered:
            reply = "No ticket matches this scope." if lang == "en" else "Aucun ticket ne correspond a ce scope."
            if scope:
                reply = f"{reply}\n{scope}"
            return reply, None, None
        filtered_sorted = sorted(filtered, key=lambda item: item.created_at, reverse=True)
        header = "Matching tickets:" if lang == "en" else "Tickets correspondants :"
        if scope:
            header = f"{header}\n{scope}"
        digest = _format_ticket_digest(filtered_sorted, lang, header=header)
        return digest, "show_ticket", _ticket_to_summary(filtered_sorted[0], lang)

    return None


def _format_most_recent_ticket(ticket, lang: str, *, open_only: bool) -> str:
    if not ticket:
        if lang == "en":
            return "No open tickets yet." if open_only else "No tickets yet."
        return "Aucun ticket ouvert pour le moment." if open_only else "Aucun ticket pour le moment."
    created_at = _format_created_at(ticket.created_at)
    priority = _priority_label(ticket.priority.value, lang)
    status = _status_label(ticket.status.value, lang)
    assignee = ticket.assignee or ("Unassigned" if lang == "en" else "Non assigne")
    if lang == "en":
        return (
            "Most recent ticket:\n"
            f"- ID: {ticket.id}\n"
            f"- Title: {ticket.title}\n"
            f"- Priority: {priority}\n"
            f"- Status: {status}\n"
            f"- Assignee: {assignee}\n"
            f"- Created: {created_at}"
        )
    return (
        "Ticket le plus recent :\n"
        f"- ID: {ticket.id}\n"
        f"- Titre: {ticket.title}\n"
        f"- Priorite: {priority}\n"
        f"- Statut: {status}\n"
        f"- Assigne: {assignee}\n"
        f"- Cree le: {created_at}"
    )


def _format_most_used_tickets(tickets: list, lang: str) -> str:
    if not tickets:
        return "No tickets yet." if lang == "en" else "Aucun ticket pour le moment."
    counts = Counter([t.category.value for t in tickets])
    top = counts.most_common(3)
    labels_en = {
        "infrastructure": "Infrastructure",
        "network": "Network",
        "security": "Security",
        "application": "Application",
        "service_request": "Service request",
        "hardware": "Hardware",
        "email": "Email",
        "problem": "Problem",
    }
    labels_fr = {
        "infrastructure": "Infrastructure",
        "network": "Reseau",
        "security": "Securite",
        "application": "Application",
        "service_request": "Demande de service",
        "hardware": "Materiel",
        "email": "Email",
        "problem": "Probleme",
    }
    labels = labels_en if lang == "en" else labels_fr
    lines = [f"- {labels.get(cat, cat)} ({count})" for cat, count in top]
    header = "Most common ticket categories:" if lang == "en" else "Categories de tickets les plus frequentes :"
    return f"{header}\n" + "\n".join(lines)


def _format_critical_tickets(tickets: list, lang: str, *, active_only: bool) -> str:
    if not tickets:
        if lang == "en":
            return "No critical active tickets found." if active_only else "No critical tickets found."
        return "Aucun ticket critique actif trouve." if active_only else "Aucun ticket critique trouve."

    top = tickets[:3]
    lines: list[str] = []
    for ticket in top:
        priority = _priority_label(ticket.priority.value, lang)
        status = _status_label(ticket.status.value, lang)
        assignee = ticket.assignee or ("Unassigned" if lang == "en" else "Non assigne")
        if lang == "en":
            lines.append(
                f"- {ticket.id} | {ticket.title} | {priority} | {status} | {assignee}"
            )
        else:
            lines.append(
                f"- {ticket.id} | {ticket.title} | {priority} | {status} | {assignee}"
            )

    if lang == "en":
        header = "Critical active tickets:" if active_only else "Critical tickets:"
        if len(tickets) > len(top):
            lines.append(f"... and {len(tickets) - len(top)} more.")
    else:
        header = "Tickets critiques actifs :" if active_only else "Tickets critiques :"
        if len(tickets) > len(top):
            lines.append(f"... et {len(tickets) - len(top)} autres.")
    return f"{header}\n" + "\n".join(lines)


def _format_weekly_summary(tickets: list, stats: dict, lang: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=7)
    recent = [t for t in tickets if t.created_at >= window_start]
    closed_recent = [
        t
        for t in tickets
        if t.status in {TicketStatus.resolved, TicketStatus.closed} and t.updated_at >= window_start
    ]
    critical_active = [
        t
        for t in tickets
        if t.priority == TicketPriority.critical and t.status in ACTIVE_STATUSES
    ]
    category_counts = Counter([t.category.value for t in recent]).most_common(3)

    labels_en = {
        "infrastructure": "Infrastructure",
        "network": "Network",
        "security": "Security",
        "application": "Application",
        "service_request": "Service request",
        "hardware": "Hardware",
        "email": "Email",
        "problem": "Problem",
    }
    labels_fr = {
        "infrastructure": "Infrastructure",
        "network": "Reseau",
        "security": "Securite",
        "application": "Application",
        "service_request": "Demande de service",
        "hardware": "Materiel",
        "email": "Email",
        "problem": "Probleme",
    }
    labels = labels_en if lang == "en" else labels_fr
    top_categories = (
        ", ".join([f"{labels.get(cat, cat)} ({count})" for cat, count in category_counts])
        if category_counts
        else ("None" if lang == "en" else "Aucune")
    )

    if lang == "en":
        return (
            "Weekly activity summary (last 7 days):\n"
            f"- New tickets: {len(recent)}\n"
            f"- Resolved/closed: {len(closed_recent)}\n"
            f"- Open now: {stats.get('open', 0)}\n"
            f"- In progress: {stats.get('in_progress', 0)}\n"
            f"- Pending: {stats.get('pending', 0)}\n"
            f"- Critical active tickets: {len(critical_active)}\n"
            f"- Resolution rate: {stats.get('resolution_rate', 0)}%\n"
            f"- Avg. resolution time: {stats.get('avg_resolution_days', 0)} days\n"
            f"- Top categories this week: {top_categories}"
        )
    return (
        "Resume de l'activite (7 derniers jours) :\n"
        f"- Nouveaux tickets : {len(recent)}\n"
        f"- Resolus/fermes : {len(closed_recent)}\n"
        f"- Ouverts actuellement : {stats.get('open', 0)}\n"
        f"- En cours : {stats.get('in_progress', 0)}\n"
        f"- En attente : {stats.get('pending', 0)}\n"
        f"- Tickets critiques actifs : {len(critical_active)}\n"
        f"- Taux de resolution : {stats.get('resolution_rate', 0)}%\n"
        f"- Temps moyen de resolution : {stats.get('avg_resolution_days', 0)} jours\n"
        f"- Categories principales de la semaine : {top_categories}"
    )


def _top_unique_resolution_snippets(tickets: list, ticket_ids: list[str], *, lang: str, limit: int = 2) -> list[str]:
    by_id = {t.id: t for t in tickets}
    snippets: list[str] = []
    for ticket_id in ticket_ids:
        ticket = by_id.get(ticket_id)
        if not ticket:
            continue
        if ticket.status not in {TicketStatus.resolved, TicketStatus.closed}:
            continue
        resolution = (ticket.resolution or "").strip()
        if not resolution:
            continue
        snippets.append(_summarize(resolution, max_len=170))

    unique: list[str] = []
    seen: set[str] = set()
    for text in snippets:
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
        if len(unique) >= limit:
            break
    if unique:
        return unique

    if lang == "en":
        return [
            "Collect logs and timestamps, then compare with the last resolved similar incident.",
            "Document the root cause and add a standard recovery checklist to avoid recurrence.",
        ]
    return [
        "Collecter les logs et horodatages, puis comparer avec le dernier incident similaire resolu.",
        "Documenter la cause racine et ajouter une checklist de reprise standard pour eviter la recurrence.",
    ]


def _format_recurring_solutions(tickets: list, lang: str, question: str) -> str:
    patterns = compute_problem_insights(tickets, min_repetitions=2, limit=3)
    if not patterns:
        if lang == "en":
            return (
                "No recurring bug pattern detected yet.\n"
                "- Add resolution comments when closing tickets.\n"
                "- Re-run after more incidents to generate pattern-based recommendations."
            )
        return (
            "Aucun pattern de bug recurrent detecte pour le moment.\n"
            "- Ajoutez des commentaires de resolution lors de la cloture.\n"
            "- Relancez la demande apres plus d'incidents pour obtenir des recommandations basees sur les patterns."
        )

    if lang == "en":
        lines = ["Recommended solutions for recurring bugs:"]
    else:
        lines = ["Solutions recommandees pour les bugs recurrents :"]

    for idx, pattern in enumerate(patterns, start=1):
        title = str(pattern.get("title") or "")
        occurrences = int(pattern.get("occurrences") or 0)
        active_count = int(pattern.get("active_count") or 0)
        ticket_ids = [str(ticket_id) for ticket_id in (pattern.get("ticket_ids") or []) if ticket_id]

        if lang == "en":
            lines.append(
                f"{idx}. {title} ({occurrences} occurrences, {active_count} active)"
            )
            lines.append("   Actions:")
        else:
            lines.append(
                f"{idx}. {title} ({occurrences} occurrences, {active_count} actifs)"
            )
            lines.append("   Actions :")

        for solution in _top_unique_resolution_snippets(tickets, ticket_ids, lang=lang):
            lines.append(f"   - {solution}")

    kb_block = build_jira_knowledge_block(question, lang=lang, limit=2)
    if kb_block:
        if lang == "en":
            lines.append("\nJSM comment knowledge used:")
        else:
            lines.append("\nConnaissance JSM utilisee :")
        kb_lines = [line for line in kb_block.splitlines()[1:] if line.strip()]
        lines.extend(kb_lines[:2])

    return "\n".join(lines)


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


def _summarize(text: str, max_len: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _ticket_to_summary(ticket, lang: str) -> TicketDraft | None:
    if not ticket:
        return None
    created_at = _format_created_at(ticket.created_at)
    status = _status_label(ticket.status.value, lang)
    summary = _summarize(ticket.description)
    if lang == "en":
        details = f"Status: {status} | Created: {created_at}\n{summary}"
    else:
        details = f"Statut: {status} | Cree: {created_at}\n{summary}"
    return TicketDraft(
        title=f"{ticket.id} - {ticket.title}",
        description=details,
        priority=ticket.priority,
        category=ticket.category,
        tags=ticket.tags or [],
        assignee=ticket.assignee,
    )


def _extract_create_subject(question: str, *, lang: str) -> str:
    raw = (question or "").strip()
    if not raw:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"

    normalized = _normalize_intent_text(raw)
    patterns = [
        r"^(please\s+)?(create|generate|draft|open|raise|log|submit)\s+(a\s+)?(new\s+)?(ticket|incident)\s*(about|for|regarding)?\s*",
        r"^(je\s+veux\s+)?(creer|genere?r|ouvrir|declarer|signaler)\s+(un\s+)?(nouveau\s+)?(ticket|incident)\s*(sur|pour|concernant)?\s*",
        r"^je\s+vais\s+creer\s+un\s+ticket\s*(sur|pour|concernant)?\s*",
    ]
    for pattern in patterns:
        normalized = re.sub(pattern, "", normalized).strip(" .:-")
    if not normalized:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"
    words = normalized.split()
    subject = " ".join(words[:14]).strip()
    if not subject:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"
    return subject[:110]


def _title_case_words(text: str) -> str:
    words = [word for word in (text or "").split() if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _build_forced_ai_ticket_draft(
    *,
    question: str,
    lang: str,
    db: Session,
    stats: dict,
    assignee_names: list[str],
    current_user,
    top: list[str],
) -> ChatResponse:
    force_prompt = (
        (
            "Generate one complete ITSM ticket draft from this user message. "
            "Return action=create_ticket with title, detailed description, priority, category, tags and assignee when possible.\n"
            f"User message: {question}"
        )
        if lang == "en"
        else (
            "Genere un brouillon complet de ticket ITSM a partir du message utilisateur. "
            "Retourne action=create_ticket avec titre, description detaillee, priorite, categorie, tags et assigne si possible.\n"
            f"Message utilisateur: {question}"
        )
    )
    reply, action, payload = build_chat_reply(
        force_prompt,
        stats,
        top,
        locale=lang,
        assignees=assignee_names,
    )

    data = payload if isinstance(payload, dict) else {}
    subject = _extract_create_subject(question, lang=lang)
    subject_title = _title_case_words(subject)
    default_title = (
        f"New ticket - {subject_title}"
        if lang == "en"
        else f"Nouveau ticket - {subject_title}"
    )[:120]
    default_description = (
        "Ticket draft generated by AI assistant.\n"
        f"User request: {question or subject}\n"
        f"Context: {subject_title}\n"
        "Please review scope, impacted users and expected outcome before submission."
        if lang == "en"
        else
        "Brouillon de ticket genere par l'assistant IA.\n"
        f"Demande utilisateur: {question or subject}\n"
        f"Contexte: {subject_title}\n"
        "Veuillez confirmer le scope, les utilisateurs impactes et le resultat attendu avant soumission."
    )

    title = str(data.get("title") or default_title).strip()[:120]
    description = str(data.get("description") or default_description).strip()
    if len(description) < 5:
        description = default_description

    try:
        priority = TicketPriority(data.get("priority"))
        category = TicketCategory(data.get("category"))
    except Exception:
        priority, category, _ = classify_ticket(title, description)

    assignee = data.get("assignee")
    if isinstance(assignee, str):
        assignee = assignee.strip()
    else:
        assignee = None
    if assignee and assignee_names and assignee not in assignee_names:
        assignee = None
    if not assignee:
        assignee = select_best_assignee(db, category=category, priority=priority)
    if not assignee:
        if getattr(current_user, "role", None) in {UserRole.admin, UserRole.agent}:
            assignee = current_user.name
        elif assignee_names:
            assignee = assignee_names[0]

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    if "ai-draft" not in clean_tags:
        clean_tags.append("ai-draft")
    if len(clean_tags) > 10:
        clean_tags = clean_tags[:10]

    draft = TicketDraft(
        title=title,
        description=description,
        priority=priority,
        category=category,
        tags=clean_tags,
        assignee=assignee,
    )
    response_text = (
        "AI ticket draft generated. Review it and click Create ticket."
        if lang == "en"
        else "Brouillon de ticket IA genere. Verifiez-le puis cliquez sur Creer le ticket."
    )
    return ChatResponse(reply=response_text, action="create_ticket", ticket=draft)


@router.post("/classify", response_model=ClassificationResponse)
def classify(payload: ClassificationRequest, db: Session = Depends(get_db)) -> ClassificationResponse:
    priority, category, recommendations = classify_ticket(payload.title, payload.description)
    assignee = select_best_assignee(db, category=category, priority=priority)
    scored = score_recommendations(recommendations)
    return ClassificationResponse(
        priority=priority,
        category=category,
        recommendations=recommendations,
        recommendations_scored=[AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored],
        assignee=assignee,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ChatResponse:
    tickets = list_tickets_for_user(db, current_user)
    stats = compute_stats(tickets)
    last_question = payload.messages[-1].content if payload.messages else ""
    lang = _normalize_locale(payload.locale)
    lowered = _normalize_intent_text(last_question or "")
    assignees = list_assignees(db)
    assignee_names = [u.name for u in assignees]
    create_requested = _is_explicit_ticket_create_request(last_question or "")
    top = [
        f"{t.id} | {t.title} | {t.priority.value} | {t.status.value} | {t.category.value} | {t.assignee}"
        for t in tickets[:120]
    ]

    if create_requested:
        return _build_forced_ai_ticket_draft(
            question=last_question,
            lang=lang,
            db=db,
            stats=stats,
            assignee_names=assignee_names,
            current_user=current_user,
            top=top,
        )

    if _is_recent_ticket_request(lowered):
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        recent = pool[0] if pool else None
        reply = _format_most_recent_ticket(recent, lang, open_only=open_only)
        summary = _ticket_to_summary(recent, lang)
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)
    if _is_most_used_request(lowered):
        reply = _format_most_used_tickets(tickets, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)
    if _is_weekly_summary_request(lowered):
        reply = _format_weekly_summary(tickets, stats, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)
    if _is_critical_ticket_request(lowered):
        active_only = _wants_active_only(lowered)
        critical = [t for t in tickets if t.priority == TicketPriority.critical]
        if active_only:
            critical = [t for t in critical if t.status in ACTIVE_STATUSES]
        reply = _format_critical_tickets(critical, lang, active_only=active_only)
        summary = _ticket_to_summary(critical[0], lang) if critical else None
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)
    if _is_recurring_solution_request(lowered):
        reply = _format_recurring_solutions(tickets, lang, last_question)
        return ChatResponse(reply=reply, action=None, ticket=None)

    structured_answer = _answer_data_query(last_question, tickets, lang, assignee_names)
    if structured_answer:
        reply, action, ticket = structured_answer
        return ChatResponse(reply=reply, action=action, ticket=ticket)

    reply, action, ticket_payload = build_chat_reply(
        last_question,
        stats,
        top,
        locale=payload.locale,
        assignees=assignee_names,
    )

    if action == "create_ticket" and not create_requested:
        action = None
        ticket_payload = None

    ticket: TicketDraft | None = None
    if action == "create_ticket" and isinstance(ticket_payload, dict):
        title = str(ticket_payload.get("title") or last_question or "New ticket")
        description = str(ticket_payload.get("description") or last_question or title)
        try:
            priority = TicketPriority(ticket_payload.get("priority"))
            category = TicketCategory(ticket_payload.get("category"))
        except Exception:
            priority, category, _ = classify_ticket(title, description)
        tags = ticket_payload.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        assignee = ticket_payload.get("assignee")
        if assignee and assignee_names and assignee not in assignee_names:
            assignee = None
        if not assignee:
            if getattr(current_user, "role", None) in {UserRole.admin, UserRole.agent}:
                assignee = current_user.name
            elif assignee_names:
                assignee = assignee_names[0]
        ticket = TicketDraft(
            title=title,
            description=description,
            priority=priority,
            category=category,
            tags=tags,
            assignee=assignee,
        )

    return ChatResponse(reply=reply, action=action, ticket=ticket)
