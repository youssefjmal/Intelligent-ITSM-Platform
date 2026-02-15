"""Formatting helpers for AI chat responses."""

from __future__ import annotations

import datetime as dt
from collections import Counter

from app.models.enums import TicketPriority, TicketStatus
from app.schemas.ai import TicketDraft
from app.services.ai.intents import ACTIVE_STATUSES
from app.services.jira_kb import build_jira_knowledge_block
from app.services.tickets import compute_problem_insights

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

