"""Structured ticket analytics query helpers for AI chat."""

from __future__ import annotations

import datetime as dt

from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.schemas.ai import TicketDraft
from app.services.ai.formatters import _format_scope_summary, _format_ticket_detail, _format_ticket_digest, _ticket_to_summary
from app.services.tickets import analytics_created_at, analytics_first_action_at, analytics_resolved_at
from app.services.ai.intents import (
    ACTIVE_STATUSES,
    TICKET_ID_PATTERN,
    _detect_window_days,
    _is_count_request,
    _is_first_action_request,
    _is_listing_request,
    _is_mttr_request,
    _is_reassignment_request,
    _is_resolution_rate_request,
    _looks_like_data_query,
    _normalize_intent_text,
    _wants_active_only,
)

STATUS_QUERY_KEYWORDS = {
    TicketStatus.open: ["open", "opened", "ouvert", "ouverts"],
    TicketStatus.in_progress: ["in progress", "in-progress", "en cours", "cours"],
    TicketStatus.waiting_for_customer: ["waiting for customer", "attente client", "en attente client"],
    TicketStatus.waiting_for_support_vendor: ["waiting for support", "waiting for vendor", "en attente support", "en attente fournisseur"],
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


def _match_keyword_map(text: str, mapping: dict) -> set:
    matches = set()
    for value, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            matches.add(value)
    return matches


def _extract_assignee_mentions(text: str, assignee_names: list[str]) -> set[str]:
    lowered = text.casefold()
    return {
        name
        for name in assignee_names
        if name and name.casefold() in lowered
    }


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
        filtered = [ticket for ticket in filtered if analytics_created_at(ticket) >= cutoff]

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
        if analytics_resolved_at(ticket) is not None
    ]
    first_actions = [
        ticket
        for ticket in tickets
        if analytics_first_action_at(ticket) is not None
    ]

    mttr_hours = None
    if resolved:
        mttr_hours = sum(
            (analytics_resolved_at(ticket) - analytics_created_at(ticket)).total_seconds()
            for ticket in resolved
        ) / len(resolved) / 3600

    avg_first_action_hours = None
    if first_actions:
        avg_first_action_hours = sum(
            (analytics_first_action_at(ticket) - analytics_created_at(ticket)).total_seconds()
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
        filtered_sorted = sorted(filtered, key=analytics_created_at, reverse=True)
        header = "Matching tickets:" if lang == "en" else "Tickets correspondants :"
        if scope:
            header = f"{header}\n{scope}"
        digest = _format_ticket_digest(filtered_sorted, lang, header=header)
        return digest, "show_ticket", _ticket_to_summary(filtered_sorted[0], lang)

    return None
