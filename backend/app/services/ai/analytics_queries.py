"""Structured ticket analytics query helpers for AI chat."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.schemas.ai import AIChatStructuredResponse, AIChatTicketResults, TicketDraft
from app.services.ai.chat_payloads import (
    build_ticket_details_payload,
    build_ticket_list_payload,
    build_ticket_status_payload,
)
from app.services.ai.formatters import (
    _build_ticket_results_payload,
    _format_scope_summary,
    _format_ticket_comments_snapshot,
    _format_ticket_detail,
    _format_ticket_digest,
    _format_ticket_status_snapshot,
    _ticket_to_summary,
)
from app.services.tickets import analytics_created_at, analytics_first_action_at, analytics_resolved_at
from app.services.ai.intents import (
    ACTIVE_STATUSES,
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
    extract_ticket_id,
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
    TicketCategory.hardware: ["hardware", "materiel", "pc", "laptop", "printer", "peripherique"],
    TicketCategory.email: ["email", "mail", "outlook", "boite mail"],
    TicketCategory.problem: ["problem", "probleme", "root cause", "rca"],
}

TICKET_TYPE_QUERY_KEYWORDS = {
    TicketType.incident: [
        "incident",
        "incidents",
    ],
    TicketType.service_request: [
        "service request",
        "service requests",
        "service_request",
        "demande de service",
        "demandes de service",
    ],
}


@dataclass(slots=True)
class StructuredChatAnswer:
    reply: str
    action: str | None
    ticket: TicketDraft | None
    ticket_results: AIChatTicketResults | None = None
    response_payload: AIChatStructuredResponse | None = None


def _append_scope(reply: str, scope: str | None) -> str:
    if not scope:
        return reply
    return f"{reply}\n{scope}"


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


def _ticket_matches_ticket_type(ticket: object, ticket_types: set[TicketType]) -> bool:
    normalized_ticket_types = {ticket_type.value for ticket_type in ticket_types}
    current_ticket_type = str(
        getattr(getattr(ticket, "ticket_type", None), "value", getattr(ticket, "ticket_type", None)) or ""
    ).strip().lower()
    if current_ticket_type in normalized_ticket_types:
        return True

    # Backward-compatible support for older rows that still persist the legacy
    # service_request category even when ticket_type is absent.
    if TicketType.service_request in ticket_types:
        current_category = str(
            getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)) or ""
        ).strip().lower()
        return current_category == TicketCategory.service_request.value
    return False


def _extract_ticket_query_meta(text: str, assignee_names: list[str]) -> dict:
    statuses = _match_keyword_map(text, STATUS_QUERY_KEYWORDS)
    priorities = _match_keyword_map(text, PRIORITY_QUERY_KEYWORDS)
    categories = _match_keyword_map(text, CATEGORY_QUERY_KEYWORDS)
    ticket_types = _match_keyword_map(text, TICKET_TYPE_QUERY_KEYWORDS)
    assignees = _extract_assignee_mentions(text, assignee_names)
    window_days = _detect_window_days(text)
    if _is_high_sla_risk_request(text):
        priorities = set()

    if not statuses and _wants_active_only(text):
        statuses = set(ACTIVE_STATUSES)

    return {
        "statuses": statuses,
        "priorities": priorities,
        "categories": categories,
        "ticket_types": ticket_types,
        "assignees": assignees,
        "window_days": window_days,
    }


# Stop-words that should never be treated as topic keywords.
_QUERY_STOP_WORDS: frozenset[str] = frozenset({
    "are", "there", "any", "tickets", "ticket", "related", "to", "about", "for",
    "show", "me", "list", "give", "find", "get", "all", "the", "a", "an", "of",
    "with", "and", "or", "in", "on", "that", "have", "has", "is", "was", "be",
    "do", "does", "can", "will", "what", "which", "how", "many", "much",
    "y", "a-t-il", "des", "les", "le", "la", "de", "du", "un", "une", "qui",
    "quels", "quelles", "quel", "quelle", "sur", "avec", "pour", "par", "dans",
    "il", "elle", "ils", "elles", "est", "sont", "ont", "avoir", "etre",
    "montre", "affiche", "voir", "donne", "cherche", "trouve",
})


def _stem_keyword(kw: str) -> str:
    """Strip common inflection suffixes to get a matchable root (e.g. 'databases' → 'database')."""
    for suffix in ("iques", "ique", "tions", "tion", "ings", "ing", "ers", "er", "es", "s"):
        if kw.endswith(suffix) and len(kw) - len(suffix) >= 4:
            return kw[: -len(suffix)]
    return kw


def _extract_topic_keywords(text: str, meta: dict) -> list[str]:
    """Extract free-text topic words not captured by structured filters."""
    covered: set[str] = set()
    for kw_map in (STATUS_QUERY_KEYWORDS, PRIORITY_QUERY_KEYWORDS, CATEGORY_QUERY_KEYWORDS, TICKET_TYPE_QUERY_KEYWORDS):
        for keywords in kw_map.values():
            covered.update(keywords)

    tokens = [t for t in text.split() if len(t) >= 2]
    topic = []
    for t in tokens:
        if t in _QUERY_STOP_WORDS or t in covered or t.startswith("tw-") or t.startswith("pb-") or t.isdigit():
            continue
        # Use stemmed form for matching so "databases" → "database", "crashes" → "crash"
        topic.append(_stem_keyword(t))
    return topic


def _ticket_content_blob(ticket: object) -> str:
    parts = [
        str(getattr(ticket, "id", "") or ""),
        str(getattr(ticket, "title", "") or ""),
        str(getattr(ticket, "description", "") or ""),
        str(getattr(ticket, "assignee", "") or ""),
        str(getattr(ticket, "reporter", "") or ""),
        str(getattr(ticket, "resolution", "") or ""),
    ]
    tags = getattr(ticket, "tags", None) or []
    parts.extend(str(t) for t in tags)
    comments = getattr(ticket, "comments", None) or []
    for comment in comments:
        parts.append(str(getattr(comment, "content", "") or ""))
    return " ".join(parts).casefold()


def _filter_tickets_for_query(text: str, tickets: list, assignee_names: list[str]) -> tuple[list, dict]:
    meta = _extract_ticket_query_meta(text, assignee_names)
    statuses = meta["statuses"]
    priorities = meta["priorities"]
    categories = meta["categories"]
    ticket_types = meta["ticket_types"]
    assignees = meta["assignees"]
    window_days = meta["window_days"]

    filtered = tickets
    if statuses:
        filtered = [ticket for ticket in filtered if ticket.status in statuses]
    if priorities:
        filtered = [ticket for ticket in filtered if ticket.priority in priorities]
    if categories:
        filtered = [ticket for ticket in filtered if ticket.category in categories]
    if ticket_types:
        filtered = [ticket for ticket in filtered if _ticket_matches_ticket_type(ticket, ticket_types)]
    if assignees:
        filtered = [ticket for ticket in filtered if ticket.assignee in assignees]
    if window_days:
        now = dt.datetime.now(dt.timezone.utc)
        cutoff = now - dt.timedelta(days=window_days)
        filtered = [ticket for ticket in filtered if analytics_created_at(ticket) >= cutoff]

    # Free-text topic filter: if no structured filter narrowed the results AND
    # the query contains topic keywords, filter by keyword match in ticket content.
    no_structured_filter = not (statuses or priorities or categories or ticket_types or assignees)
    if no_structured_filter:
        topic_keywords = _extract_topic_keywords(_normalize_intent_text(text), meta)
        if topic_keywords:
            filtered = [
                ticket for ticket in filtered
                if any(kw in _ticket_content_blob(ticket) for kw in topic_keywords)
            ]

    return filtered, meta


def _merge_ticket_query_meta(
    base_meta: dict,
    parsed_filter_meta: dict[str, list[str] | str | bool | None] | None,
) -> dict:
    if not parsed_filter_meta:
        return base_meta
    return {
        **base_meta,
        "parsed_filters": parsed_filter_meta.get("filters") if isinstance(parsed_filter_meta, dict) else None,
    }


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


def _is_single_ticket_status_request(text: str) -> bool:
    return any(token in text for token in ["status", "statut", "etat"])


def _is_single_ticket_comment_request(text: str) -> bool:
    return any(
        token in text
        for token in [
            "comment",
            "comments",
            "commentaire",
            "commentaires",
            "note",
            "notes",
        ]
    )


def _is_high_sla_risk_request(text: str) -> bool:
    lowered = str(text or "")
    if "sla" not in lowered:
        return False
    return any(token in lowered for token in ["risk", "at risk", "high", "breach", "breached", "a risque", "depasse"])


def _ticket_results_kind(text: str, meta: dict) -> str:
    lowered = str(text or "")
    if meta.get("ticket_types") == {TicketType.incident}:
        return "incident"
    if meta.get("ticket_types") == {TicketType.service_request}:
        return "service_request"
    if "sla" in lowered and any(token in lowered for token in ["risk", "at risk", "high", "breach", "breached"]):
        return "sla_risk"
    if meta.get("priorities") == {TicketPriority.critical}:
        return "critical"
    return "generic"


def _ticket_list_title(kind: str, *, header: str, lang: str) -> str:
    if kind == "sla_risk":
        return "High SLA risk tickets" if lang == "en" else "Tickets a risque SLA eleve"
    if kind == "incident":
        return "Incident tickets" if lang == "en" else "Tickets d'incident"
    if kind == "service_request":
        return "Service requests" if lang == "en" else "Demandes de service"
    return header


def _answer_data_query(
    question: str,
    tickets: list,
    lang: str,
    assignee_names: list[str],
    *,
    resolved_ticket_id: str | None = None,
    force_single_ticket: bool = False,
    parsed_filter_meta: dict[str, list[str] | str | bool | None] | None = None,
) -> StructuredChatAnswer | None:
    text = _normalize_intent_text(question or "")
    if not force_single_ticket and not _looks_like_data_query(text):
        return None

    requested_id = extract_ticket_id(question or "")
    if requested_id is None and resolved_ticket_id:
        requested_id = str(resolved_ticket_id).strip().upper() or None
    if requested_id:
        selected = next((ticket for ticket in tickets if ticket.id.upper() == requested_id), None)
        if not selected:
            reply = f"Ticket {requested_id} not found." if lang == "en" else f"Ticket {requested_id} introuvable."
            return StructuredChatAnswer(reply=reply, action=None, ticket=None)
        if _is_single_ticket_status_request(text):
            return StructuredChatAnswer(
                reply=_format_ticket_status_snapshot(selected, lang),
                action=None,
                ticket=None,
                response_payload=build_ticket_status_payload(selected, lang=lang),
            )
        if _is_single_ticket_comment_request(text):
            return StructuredChatAnswer(
                reply=_format_ticket_comments_snapshot(selected, lang),
                action="show_ticket",
                ticket=_ticket_to_summary(selected, lang),
                response_payload=build_ticket_details_payload(selected, lang=lang),
            )
        return StructuredChatAnswer(
            reply=_format_ticket_detail(selected, lang),
            action="show_ticket",
            ticket=_ticket_to_summary(selected, lang),
            response_payload=build_ticket_details_payload(selected, lang=lang),
        )

    filtered, meta = _filter_tickets_for_query(text, tickets, assignee_names)
    meta = _merge_ticket_query_meta(meta, parsed_filter_meta)
    if _is_high_sla_risk_request(text):
        filtered = [
            ticket
            for ticket in filtered
            if str(getattr(ticket, "sla_status", "") or "").strip().lower() in {"at_risk", "breached"}
        ]
    scope = _format_scope_summary(meta, lang)
    metrics = _compute_data_metrics(filtered)

    if _is_mttr_request(text):
        if metrics["mttr_hours"] is None:
            reply = "No resolved tickets in this scope to compute MTTR." if lang == "en" else "Aucun ticket resolu dans ce scope pour calculer le MTTR."
            return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)
        mttr_value = round(metrics["mttr_hours"], 2)
        reply = f"MTTR: {mttr_value} hours on {len(filtered)} ticket(s)." if lang == "en" else f"MTTR: {mttr_value} heures sur {len(filtered)} ticket(s)."
        return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)

    if _is_first_action_request(text):
        if metrics["avg_first_action_hours"] is None:
            reply = "No first-action timestamp available in this scope." if lang == "en" else "Aucune date de premiere action disponible dans ce scope."
            return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)
        value = round(metrics["avg_first_action_hours"], 2)
        reply = (
            f"Average time to first action: {value} hours."
            if lang == "en"
            else f"Temps moyen avant premiere action: {value} heures."
        )
        return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)

    if _is_reassignment_request(text):
        value = round(metrics["reassignment_rate"], 2)
        reassigned_count = int(metrics["reassigned_count"])
        reply = (
            f"Reassignment rate: {value}% ({reassigned_count}/{len(filtered)} tickets)."
            if lang == "en"
            else f"Taux de reassignation: {value}% ({reassigned_count}/{len(filtered)} tickets)."
        )
        return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)

    if _is_resolution_rate_request(text):
        value = round(metrics["resolution_rate"], 2)
        reply = (
            f"Resolution rate: {value}% ({len(filtered)} ticket(s) in scope)."
            if lang == "en"
            else f"Taux de resolution: {value}% ({len(filtered)} ticket(s) dans le scope)."
        )
        return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)

    if _is_count_request(text):
        if lang == "en":
            reply = f"Count: {len(filtered)} ticket(s)."
        else:
            reply = f"Total: {len(filtered)} ticket(s)."
        return StructuredChatAnswer(reply=_append_scope(reply, scope), action=None, ticket=None)

    if _is_listing_request(text) or "ticket" in text:
        if not filtered:
            reply = "No ticket matches this scope." if lang == "en" else "Aucun ticket ne correspond a ce scope."
            results_kind = _ticket_results_kind(text, meta)
            list_kind = (
                "high_sla_risk"
                if results_kind == "sla_risk"
                else "critical"
                if results_kind == "critical"
                else "incident"
                if results_kind == "incident"
                else "service_request"
                if results_kind == "service_request"
                else "generic"
            )
            return StructuredChatAnswer(
                reply=_append_scope(reply, scope),
                action=None,
                ticket=None,
                response_payload=build_ticket_list_payload(
                    tickets=[],
                    lang=lang,
                    list_kind=list_kind,
                    title=_ticket_list_title(results_kind, header="Matching tickets:" if lang == "en" else "Tickets correspondants :", lang=lang),
                    scope=scope,
                    total_count=0,
                ),
            )
        filtered_sorted = sorted(filtered, key=analytics_created_at, reverse=True)
        header = "Matching tickets:" if lang == "en" else "Tickets correspondants :"
        digest_header = f"{header}\n{scope}" if scope else header
        digest = _format_ticket_digest(filtered_sorted, lang, header=digest_header)
        results_kind = _ticket_results_kind(text, meta)
        list_kind = (
            "high_sla_risk"
            if results_kind == "sla_risk"
            else "critical"
            if results_kind == "critical"
            else "incident"
            if results_kind == "incident"
            else "service_request"
            if results_kind == "service_request"
            else "generic"
        )
        ticket_results = _build_ticket_results_payload(
            filtered_sorted,
            lang,
            header=header,
            scope=scope,
            kind=results_kind,
        )
        return StructuredChatAnswer(
            reply=digest,
            action="show_ticket",
            ticket=_ticket_to_summary(filtered_sorted[0], lang),
            ticket_results=ticket_results,
            response_payload=build_ticket_list_payload(
                tickets=filtered_sorted,
                lang=lang,
                list_kind=list_kind,
                title=_ticket_list_title(results_kind, header=header, lang=lang),
                scope=scope,
                total_count=len(filtered_sorted),
            ),
        )

    return None
