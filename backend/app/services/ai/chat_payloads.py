"""Typed chat response payload builders for the ITSM copilot."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.models.enums import TicketPriority, TicketStatus
from app.schemas.ai import (
    AIChatActionLink,
    AIChatAdviceStep,
    AIChatAssignmentRecommendationResponse,
    AIChatCauseAnalysisResponse,
    AIChatCauseCandidate,
    AIChatCommentSummary,
    AIChatConfidence,
    AIChatInsufficientEvidenceResponse,
    AIChatListMetrics,
    AIChatListTicketItem,
    AIChatRelatedEntity,
    AIChatRelatedTicketRef,
    AIChatResolutionAdviceResponse,
    AIChatSLAState,
    AIChatSimilarTicketMatch,
    AIChatSimilarTicketsResponse,
    AIChatStatusResponse,
    AIChatStructuredResponse,
    AIChatTicketDetailsResponse,
    AIChatTicketListResponse,
    AIChatTopRecommendation,
)
from app.services.ai.formatters import _priority_label, _status_label
from app.services.ai.resolver import ResolverOutput

_ACTIVE_STATUSES = {
    TicketStatus.open.value,
    TicketStatus.in_progress.value,
    TicketStatus.waiting_for_customer.value,
    TicketStatus.waiting_for_support_vendor.value,
    TicketStatus.pending.value,
}
_TOPIC_STEP_HINTS = {
    "crm_integration": {"crm", "sync", "worker", "token", "oauth", "credential", "integration"},
    "payroll_export": {"export", "date", "formatter", "parser", "schema", "import", "csv", "workbook", "serializer"},
    "notification_distribution": {"distribution", "notification", "recipient", "approval", "manager", "notice"},
    "mail_transport": {"mail", "email", "relay", "connector", "forwarding", "mailbox", "queue"},
    "network_access": {"vpn", "route", "routing", "gateway", "dns", "remote", "tunnel", "mfa"},
}


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return normalized.isoformat()
    return str(value).strip() or None


def _string_or_none(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text or None


def _truncate(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _ticket_route(ticket_id: str) -> str:
    return f"/tickets/{ticket_id}"


def _problem_route(problem_id: str) -> str:
    return f"/problems/{problem_id}"


def _open_ticket_action(ticket_id: str, *, lang: str) -> AIChatActionLink:
    return AIChatActionLink(
        label="Open ticket" if lang == "en" else "Ouvrir le ticket",
        route=_ticket_route(ticket_id),
    )


def _priority_text(ticket: Any, *, lang: str) -> str:
    raw = getattr(getattr(ticket, "priority", None), "value", getattr(ticket, "priority", None)) or "unknown"
    return _priority_label(str(raw), lang)


def _status_text(ticket: Any, *, lang: str) -> str:
    raw = getattr(getattr(ticket, "status", None), "value", getattr(ticket, "status", None)) or "unknown"
    return _status_label(str(raw), lang)


def _assignee_text(ticket: Any, *, lang: str) -> str:
    return str(getattr(ticket, "assignee", None) or ("Unassigned" if lang == "en" else "Non assigne"))


def _ticket_sla_state(ticket: Any) -> AIChatSLAState | None:
    state = _string_or_none(getattr(ticket, "sla_status", None))
    due_at = _iso_or_none(getattr(ticket, "sla_due_at", None))
    remaining_minutes = getattr(ticket, "sla_remaining_minutes", None)
    remaining_human = _string_or_none(getattr(ticket, "sla_remaining_human", None))
    if state is None and due_at is None and remaining_minutes is None and remaining_human is None:
        return None
    minutes = int(remaining_minutes) if isinstance(remaining_minutes, (int, float)) else None
    return AIChatSLAState(
        state=state,
        due_at=due_at,
        remaining_minutes=minutes,
        remaining_human=remaining_human,
    )


def build_ticket_status_payload(ticket: Any, *, lang: str) -> AIChatStatusResponse:
    ticket_id = str(getattr(ticket, "id", "") or "")
    status = _status_text(ticket, lang=lang)
    priority = _priority_text(ticket, lang=lang)
    assignee = _assignee_text(ticket, lang=lang)
    sla = _ticket_sla_state(ticket)
    summary_parts = [
        f"{ticket_id} is currently {status.lower()}." if lang == "en" else f"{ticket_id} est actuellement {status.lower()}.",
        f"Priority is {priority.lower()} and owner is {assignee}."
        if lang == "en"
        else f"La priorite est {priority.lower()} et le proprietaire est {assignee}.",
    ]
    if sla and sla.state:
        summary_parts.append(
            f"SLA state: {sla.state}." if lang == "en" else f"Etat SLA : {sla.state}."
        )
    return AIChatStatusResponse(
        ticket_id=ticket_id,
        title=str(getattr(ticket, "title", "") or ticket_id),
        status=status,
        priority=priority,
        assignee=assignee,
        sla_state=sla.state if sla else None,
        updated_at=_iso_or_none(getattr(ticket, "updated_at", None)),
        summary=" ".join(summary_parts),
        actions=[_open_ticket_action(ticket_id, lang=lang)],
    )


def build_ticket_details_payload(ticket: Any, *, lang: str) -> AIChatTicketDetailsResponse:
    ticket_id = str(getattr(ticket, "id", "") or "")
    comments = getattr(ticket, "comments", None) or []
    recent_comments: list[AIChatCommentSummary] = []
    for comment in comments[:3]:
        content = _string_or_none(getattr(comment, "content", None) or getattr(comment, "body", None))
        if not content:
            continue
        recent_comments.append(
            AIChatCommentSummary(
                author=_string_or_none(getattr(comment, "author", None)),
                content=_truncate(content, limit=220),
                created_at=_iso_or_none(getattr(comment, "created_at", None)),
            )
        )

    related_entities: list[AIChatRelatedEntity] = []
    problem_id = _string_or_none(getattr(ticket, "problem_id", None))
    if problem_id:
        related_entities.append(
            AIChatRelatedEntity(
                entity_type="problem",
                entity_id=problem_id,
                title=None,
                relation="linked_problem",
                route=_problem_route(problem_id),
            )
        )

    return AIChatTicketDetailsResponse(
        ticket_id=ticket_id,
        title=str(getattr(ticket, "title", "") or ticket_id),
        description=_string_or_none(getattr(ticket, "description", None)) or "",
        status=_status_text(ticket, lang=lang),
        priority=_priority_text(ticket, lang=lang),
        assignee=_assignee_text(ticket, lang=lang),
        reporter=_string_or_none(getattr(ticket, "reporter", None)),
        category=_string_or_none(getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None))),
        created_at=_iso_or_none(getattr(ticket, "created_at", None)),
        updated_at=_iso_or_none(getattr(ticket, "updated_at", None)),
        sla=_ticket_sla_state(ticket),
        recent_comments=recent_comments,
        related_entities=related_entities,
        actions=[_open_ticket_action(ticket_id, lang=lang)],
    )


def _confidence_level_from_score(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def _confidence_from_resolver(resolver_output: ResolverOutput | None, *, lang: str) -> AIChatConfidence:
    if resolver_output is None or resolver_output.advice is None:
        return AIChatConfidence(
            level="low",
            reason=(
                "Limited evidence was available for this request."
                if lang == "en"
                else "Les preuves disponibles pour cette demande sont limitees."
            ),
        )
    advice = resolver_output.advice
    level = advice.confidence_band if advice.confidence_band in {"low", "medium", "high"} else _confidence_level_from_score(advice.confidence)
    retrieval_source = str((resolver_output.retrieval or {}).get("source") or "").strip().lower()
    degraded = retrieval_source in {"fallback_rules", "kb_empty", "local_lexical"}
    if level == "high":
        reason = (
            "Multiple matching signals support this guidance."
            if lang == "en"
            else "Plusieurs signaux concordants soutiennent cette orientation."
        )
    elif level == "medium":
        reason = (
            "The match is plausible but still needs validation before a broader change."
            if lang == "en"
            else "La correspondance est plausible mais doit encore etre validee avant un changement plus large."
        )
    else:
        reason = (
            "Evidence is limited, so this should be treated as a diagnostic lead."
            if lang == "en"
            else "Les preuves sont limitees, il faut donc traiter cela comme une piste de diagnostic."
        )
    if degraded:
        reason = (
            f"{reason} Retrieval quality was limited."
            if lang == "en"
            else f"{reason} La qualite de recuperation etait limitee."
        )
    return AIChatConfidence(level=level, reason=reason)


def _dedupe_lines(items: list[str], *, limit: int = 4) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = _string_or_none(raw)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _related_ticket_refs(rows: list[dict[str, Any]]) -> list[AIChatRelatedTicketRef]:
    refs: list[AIChatRelatedTicketRef] = []
    seen: set[str] = set()
    for row in rows:
        ticket_id = _string_or_none(row.get("id"))
        if not ticket_id or ticket_id in seen:
            continue
        seen.add(ticket_id)
        refs.append(
            AIChatRelatedTicketRef(
                ticket_id=ticket_id,
                title=_string_or_none(row.get("title")) or ticket_id,
                status=_string_or_none(row.get("status")),
                priority=_string_or_none(row.get("priority")),
                route=_ticket_route(ticket_id),
            )
        )
    return refs[:3]


def _evidence_references(evidence_sources: list[Any], *, limit: int = 3) -> list[str]:
    return [item.reference for item in evidence_sources[:limit] if _string_or_none(getattr(item, "reference", None))]


def _selected_cluster_id(resolver_output: ResolverOutput | None) -> str | None:
    if resolver_output is None:
        return None
    cluster_summary = dict((resolver_output.retrieval or {}).get("evidence_clusters") or {})
    return _string_or_none(cluster_summary.get("selected_cluster_id"))


def _selected_cluster_topic(resolver_output: ResolverOutput | None) -> str | None:
    if resolver_output is None:
        return None
    cluster_summary = dict((resolver_output.retrieval or {}).get("evidence_clusters") or {})
    selected_cluster_id = _selected_cluster_id(resolver_output)
    for cluster in list(cluster_summary.get("clusters") or []):
        cluster_id = _string_or_none(cluster.get("cluster_id"))
        dominant_topic = _string_or_none(cluster.get("dominant_topic"))
        if selected_cluster_id and cluster_id and cluster_id.casefold() == selected_cluster_id.casefold():
            return dominant_topic or cluster_id
    query_context = dict((resolver_output.retrieval or {}).get("query_context") or {})
    for topic in list(query_context.get("topics") or []):
        normalized = _string_or_none(topic)
        if normalized:
            return normalized
    return None


def _recommended_checks_in_scope(resolver_output: ResolverOutput | None, *, limit: int = 3) -> list[str]:
    rows = _dedupe_lines(
        list(getattr(resolver_output, "validation_steps", []) or [])
        + list(getattr(resolver_output, "next_best_actions", []) or [])
        + ([resolver_output.fallback_action] if resolver_output and resolver_output.fallback_action else []),
        limit=max(6, limit * 2),
    )
    preferred_topic = _selected_cluster_topic(resolver_output)
    hints = set(_TOPIC_STEP_HINTS.get(str(preferred_topic or "").strip().lower()) or [])
    if not hints:
        return rows[:limit]
    scoped = [
        row
        for row in rows
        if any(hint in row.casefold() for hint in hints)
    ]
    return (scoped or rows)[:limit]


def _related_problem_rows_in_scope(
    rows: list[dict[str, Any]],
    *,
    resolver_output: ResolverOutput | None,
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    selected_cluster_id = _selected_cluster_id(resolver_output)
    if not selected_cluster_id:
        return rows
    scoped_rows: list[dict[str, Any]] = []
    evidence_ref_keys = {str(ref).strip().casefold() for ref in evidence_refs if str(ref).strip()}
    for row in rows:
        row_id = _string_or_none(row.get("id"))
        row_cluster_id = _string_or_none(row.get("_advisor_cluster_id") or row.get("cluster_id"))
        if row_id and row_id.casefold() in evidence_ref_keys:
            scoped_rows.append(row)
            continue
        if row_cluster_id and row_cluster_id.casefold() == selected_cluster_id.casefold():
            scoped_rows.append(row)
    return scoped_rows


def _advice_reason_lines(advice: Any, *, limit: int = 4) -> list[str]:
    return _dedupe_lines(
        list(getattr(advice, "why_this_matches", []) or [])
        + ([advice.reasoning] if getattr(advice, "reasoning", None) else []),
        limit=limit,
    )


def build_insufficient_evidence_payload(
    *,
    resolver_output: ResolverOutput | None,
    ticket: Any | None,
    lang: str,
    summary: str | None = None,
) -> AIChatInsufficientEvidenceResponse:
    known_facts: list[str] = []
    if ticket is not None:
        ticket_id = str(getattr(ticket, "id", "") or "")
        known_facts.append(
            f"{ticket_id}: status={_status_text(ticket, lang=lang)}, priority={_priority_text(ticket, lang=lang)}, assignee={_assignee_text(ticket, lang=lang)}"
        )
    if resolver_output is not None:
        if resolver_output.supporting_context:
            known_facts.append(resolver_output.supporting_context)
        evidence_refs = _evidence_references(resolver_output.evidence_sources)
        if evidence_refs:
            known_facts.append(
                f"Retrieved evidence references: {', '.join(evidence_refs)}"
                if lang == "en"
                else f"References de preuve recuperees : {', '.join(evidence_refs)}"
            )
        cluster_summary = dict((resolver_output.retrieval or {}).get("evidence_clusters") or {})
        if bool(cluster_summary.get("evidence_conflict_flag")):
            cluster_subjects = [
                ", ".join(str(token).replace("_", " ") for token in list(cluster.get("signature_terms") or []) if str(token).strip())
                or str(cluster.get("dominant_topic") or "").replace("_", " ")
                or str(cluster.get("cluster_id") or "").replace("_", " ")
                for cluster in list(cluster_summary.get("clusters") or [])[:2]
            ]
            cluster_subjects = [subject for subject in cluster_subjects if subject]
            if cluster_subjects:
                known_facts.append(
                    (
                        f"Conflicting evidence families: {'; '.join(cluster_subjects[:2])}"
                        if lang == "en"
                        else f"Familles de preuves concurrentes : {'; '.join(cluster_subjects[:2])}"
                    )
                )
    missing_signals = _dedupe_lines(list(getattr(resolver_output, "missing_information", []) or []), limit=3)
    if resolver_output is not None:
        cluster_summary = dict((resolver_output.retrieval or {}).get("evidence_clusters") or {})
        if bool(cluster_summary.get("evidence_conflict_flag")):
            missing_signals = _dedupe_lines(
                [
                    (
                        "Conflicting evidence clusters were detected."
                        if lang == "en"
                        else "Des grappes de preuves contradictoires ont ete detectees."
                    ),
                    *missing_signals,
                ],
                limit=3,
            )
    if not missing_signals:
        missing_signals = [
            "A confirmed matching root cause was not found."
            if lang == "en"
            else "Aucune cause racine concordante n'a ete confirmee."
        ]
    recommended = _recommended_checks_in_scope(resolver_output, limit=3)
    if not recommended:
        recommended = [
            "Collect one more verified technical signal before changing the system."
            if lang == "en"
            else "Collectez un signal technique verifie supplementaire avant de modifier le systeme."
        ]
    return AIChatInsufficientEvidenceResponse(
        summary=summary
        or (
            "Insufficient evidence to confirm a specific cause or fix."
            if lang == "en"
            else "Preuves insuffisantes pour confirmer une cause ou un correctif precis."
        ),
        known_facts=known_facts[:3],
        missing_signals=missing_signals,
        recommended_next_checks=recommended,
        confidence=_confidence_from_resolver(resolver_output, lang=lang),
    )


def build_resolution_advice_payload(
    *,
    ticket: Any | None,
    resolver_output: ResolverOutput | None,
    lang: str,
) -> AIChatStructuredResponse:
    if resolver_output is None or resolver_output.advice is None:
        return build_insufficient_evidence_payload(resolver_output=resolver_output, ticket=ticket, lang=lang)

    advice = resolver_output.advice
    if advice.recommendation_mode == "insufficient_evidence":
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=ticket,
            lang=lang,
            summary=_string_or_none(advice.reasoning),
        )
    if advice.display_mode == "no_strong_match" and not advice.recommended_action and not advice.fallback_action:
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=ticket,
            lang=lang,
            summary=(
                "Insufficient evidence to recommend a safe fix yet."
                if lang == "en"
                else "Preuves insuffisantes pour recommander un correctif sur pour le moment."
            ),
        )

    action_step_rows = list((resolver_output.retrieval or {}).get("grounded_action_steps") or [])
    recommended_actions: list[AIChatAdviceStep] = []
    if action_step_rows:
        for index, row in enumerate(action_step_rows[:4], start=1):
            text = _string_or_none(row.get("text"))
            if not text:
                continue
            recommended_actions.append(
                AIChatAdviceStep(
                    step=index,
                    text=text,
                    reason=_string_or_none(row.get("reason")),
                    evidence=_dedupe_lines([str(item) for item in list(row.get("evidence") or [])], limit=4),
                )
            )
    if not recommended_actions:
        step_texts = _dedupe_lines(
            list(advice.workflow_steps or [])
            or ([advice.recommended_action] if advice.recommended_action else [])
            or ([advice.fallback_action] if advice.fallback_action else []),
            limit=4,
        )
        reason_lines = _advice_reason_lines(advice)
        evidence_refs = _evidence_references(advice.evidence_sources)
        recommended_actions = [
            AIChatAdviceStep(
                step=index,
                text=text,
                reason=reason_lines[min(index - 1, len(reason_lines) - 1)] if reason_lines else None,
                evidence=evidence_refs,
            )
            for index, text in enumerate(step_texts, start=1)
        ]
    reason_lines = _advice_reason_lines(advice)
    related_tickets = _related_ticket_refs(list((resolver_output.retrieval or {}).get("similar_tickets") or []))
    summary = _string_or_none(advice.match_summary) or _string_or_none(advice.supporting_context) or (
        "This advice is anchored to the strongest retrieved evidence for the ticket."
        if lang == "en"
        else "Cette orientation s'appuie sur les preuves recuperees les plus solides pour le ticket."
    )
    return AIChatResolutionAdviceResponse(
        ticket_id=str(getattr(ticket, "id", "") or "") or None,
        summary=summary,
        recommended_actions=recommended_actions,
        why_this_matches=reason_lines,
        validation_steps=_dedupe_lines(list(advice.validation_steps or []), limit=4),
        next_steps=_dedupe_lines(list(advice.next_best_actions or []) + ([advice.fallback_action] if advice.fallback_action else []), limit=4),
        related_tickets=related_tickets,
        confidence=_confidence_from_resolver(resolver_output, lang=lang),
    )


def _likelihood_from_score(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def build_cause_analysis_payload(
    *,
    ticket: Any | None,
    resolver_output: ResolverOutput | None,
    lang: str,
) -> AIChatStructuredResponse:
    if resolver_output is None or resolver_output.advice is None:
        return build_insufficient_evidence_payload(resolver_output=resolver_output, ticket=ticket, lang=lang)

    advice = resolver_output.advice
    if advice.recommendation_mode == "insufficient_evidence":
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=ticket,
            lang=lang,
            summary=_string_or_none(advice.reasoning),
        )
    evidence_refs = _evidence_references(advice.evidence_sources)
    related_rows = _related_problem_rows_in_scope(
        list((resolver_output.retrieval or {}).get("related_problems") or []),
        resolver_output=resolver_output,
        evidence_refs=evidence_refs,
    )
    similar_refs = _related_ticket_refs(list((resolver_output.retrieval or {}).get("similar_tickets") or []))
    confidence = _confidence_from_resolver(resolver_output, lang=lang)
    possible_causes: list[AIChatCauseCandidate] = []
    seen: set[str] = set()

    primary_cause = _string_or_none(advice.root_cause or advice.probable_root_cause)
    if primary_cause:
        seen.add(primary_cause.casefold())
        possible_causes.append(
            AIChatCauseCandidate(
                title=primary_cause,
                likelihood=_likelihood_from_score(float(advice.confidence or 0.0)),
                explanation=_string_or_none(advice.reasoning) or _string_or_none(advice.match_summary) or (
                    "This is the strongest current inference supported by retrieved evidence."
                    if lang == "en"
                    else "Il s'agit de l'inference actuelle la plus forte soutenue par les preuves recuperees."
                ),
                evidence=evidence_refs,
                related_tickets=similar_refs[:2],
            )
        )

    for row in related_rows:
        root_cause = _string_or_none(row.get("root_cause"))
        if not root_cause or root_cause.casefold() in seen:
            continue
        seen.add(root_cause.casefold())
        possible_causes.append(
            AIChatCauseCandidate(
                title=root_cause,
                likelihood=_likelihood_from_score(float(row.get("similarity_score") or 0.0)),
                explanation=_string_or_none(row.get("match_reason")) or (
                    "Matched a related recurring problem pattern."
                    if lang == "en"
                    else "Correspond a un probleme recurrent connexe."
                ),
                evidence=_dedupe_lines(
                    [str(row.get("id") or ""), str(row.get("match_reason") or "")]
                    + evidence_refs[:2],
                    limit=3,
                ),
                related_tickets=similar_refs[:2],
            )
        )
        if len(possible_causes) >= 3:
            break

    if not possible_causes:
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=ticket,
            lang=lang,
            summary=(
                "Insufficient evidence to rank specific causes yet."
                if lang == "en"
                else "Preuves insuffisantes pour classer des causes specifiques pour le moment."
            ),
        )

    summary = (
        f"Most likely cause in scope: {possible_causes[0].title}."
        if confidence.level == "high"
        else (
            f"No confirmed root cause yet. Strongest current hypothesis: {possible_causes[0].title}."
            if lang == "en"
            else f"Aucune cause racine confirmee pour l'instant. Hypothese principale actuelle : {possible_causes[0].title}."
        )
    )
    if lang == "fr" and confidence.level == "high":
        summary = f"Cause la plus probable dans ce contexte : {possible_causes[0].title}."
    return AIChatCauseAnalysisResponse(
        ticket_id=str(getattr(ticket, "id", "") or "") or None,
        summary=summary,
        possible_causes=possible_causes,
        recommended_checks=_dedupe_lines(list(advice.next_best_actions or []) + list(advice.validation_steps or []), limit=4),
        validation_steps=_dedupe_lines(list(advice.validation_steps or []) + list(advice.missing_information or []), limit=4),
        confidence=confidence,
    )


def _similarity_reason(row: dict[str, Any], *, lang: str) -> str:
    explicit = _string_or_none(row.get("recommendation_reason") or row.get("reason") or row.get("match_reason"))
    if explicit:
        return explicit
    if _string_or_none(row.get("problem_id")):
        return (
            "Shares the same related problem pattern."
            if lang == "en"
            else "Partage le meme schema de probleme associe."
        )
    if _string_or_none(row.get("resolution_snippet")):
        return (
            "Matched a similar incident with a documented resolution."
            if lang == "en"
            else "Correspond a un incident similaire avec une resolution documentee."
        )
    return (
        "Matched on retrieved lexical and semantic overlap."
        if lang == "en"
        else "Correspondance basee sur un chevauchement lexical et semantique recupere."
    )


def build_similar_tickets_payload(
    *,
    source_ticket_id: str | None,
    resolver_output: ResolverOutput | None,
    lang: str,
) -> AIChatStructuredResponse:
    rows = list((resolver_output.retrieval or {}).get("similar_tickets") or []) if resolver_output is not None else []
    matches = [
        AIChatSimilarTicketMatch(
            ticket_id=str(row.get("id") or ""),
            title=_string_or_none(row.get("title")) or str(row.get("id") or "Ticket"),
            match_reason=_similarity_reason(row, lang=lang),
            match_score=float(row.get("similarity_score") or 0.0),
            status=_string_or_none(row.get("status")),
            route=_ticket_route(str(row.get("id") or "")),
        )
        for row in rows
        if _string_or_none(row.get("id"))
    ]
    if not matches:
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=None,
            lang=lang,
            summary=(
                "No sufficiently similar tickets were retrieved for this request."
                if lang == "en"
                else "Aucun ticket suffisamment similaire n'a ete recupere pour cette demande."
            ),
        )
    return AIChatSimilarTicketsResponse(
        source_ticket_id=source_ticket_id,
        matches=matches[:5],
    )


def build_assignment_recommendation_payload(
    *,
    ticket: Any,
    recommended_assignee: str | None,
    lang: str,
) -> AIChatStructuredResponse:
    current_assignee = _string_or_none(getattr(ticket, "assignee", None)) or (
        "Unassigned" if lang == "en" else "Non assigne"
    )
    suggested = _string_or_none(recommended_assignee) or current_assignee
    category = _string_or_none(getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None))) or "unknown"
    priority = _priority_text(ticket, lang=lang)
    reasoning: list[str] = []
    if suggested == current_assignee:
        reasoning.append(
            f"Current ownership already aligns with category {category} and priority {priority}."
            if lang == "en"
            else f"L'assignation actuelle correspond deja a la categorie {category} et a la priorite {priority}."
        )
    else:
        reasoning.append(
            f"Suggested owner is {suggested} for category {category} with priority {priority}."
            if lang == "en"
            else f"Le proprietaire suggere est {suggested} pour la categorie {category} avec la priorite {priority}."
        )
        reasoning.append(
            "This remains advisory only and should be validated by an agent lead."
            if lang == "en"
            else "Cela reste purement consultatif et doit etre valide par un responsable."
        )
    level = "high" if suggested == current_assignee else "medium"
    reason = (
        "Deterministic assignment rules have a clear candidate."
        if level == "high" and lang == "en"
        else "Deterministic routing suggests a plausible owner."
        if lang == "en"
        else "Les regles deterministes d'assignation fournissent un candidat clair."
        if level == "high"
        else "Le routage deterministe suggere un proprietaire plausible."
    )
    return AIChatAssignmentRecommendationResponse(
        ticket_id=str(getattr(ticket, "id", "") or "") or None,
        current_assignee=current_assignee,
        recommended_assignee=suggested,
        reasoning=reasoning,
        confidence=AIChatConfidence(level=level, reason=reason),
    )


def _sla_top_recommendation(tickets: list[Any], *, lang: str) -> AIChatTopRecommendation | None:
    if not tickets:
        return None
    ranked = sorted(
        tickets,
        key=lambda row: (
            1 if _string_or_none(getattr(row, "sla_status", None)) == "breached" else 0,
            1 if getattr(getattr(row, "priority", None), "value", getattr(row, "priority", None)) == TicketPriority.critical.value else 0,
            _iso_or_none(getattr(row, "updated_at", None)) or "",
        ),
        reverse=True,
    )
    top = ranked[0]
    risk = _string_or_none(getattr(top, "sla_status", None)) or "at_risk"
    top_status = _string_or_none(getattr(getattr(top, "status", None), "value", getattr(top, "status", None))) or "open"
    summary = (
        f"Review {top.id} first because it is {risk} and currently {top_status}."
        if lang == "en"
        else f"Traitez {top.id} en premier car il est {risk} et actuellement {top_status}."
    )
    confidence = 0.84 if risk == "breached" else 0.72
    return AIChatTopRecommendation(summary=summary, confidence=confidence)


def build_ticket_list_payload(
    *,
    tickets: list[Any],
    lang: str,
    list_kind: str,
    title: str,
    scope: str | None = None,
) -> AIChatTicketListResponse:
    items = [
        AIChatListTicketItem(
            ticket_id=str(getattr(ticket, "id", "") or ""),
            title=str(getattr(ticket, "title", "") or ""),
            status=_status_text(ticket, lang=lang),
            priority=_priority_text(ticket, lang=lang),
            assignee=_assignee_text(ticket, lang=lang),
            sla_risk=_string_or_none(getattr(ticket, "sla_status", None)),
            route=_ticket_route(str(getattr(ticket, "id", "") or "")),
        )
        for ticket in tickets
        if _string_or_none(getattr(ticket, "id", None))
    ]
    open_count = sum(
        1
        for ticket in tickets
        if str(getattr(getattr(ticket, "status", None), "value", getattr(ticket, "status", None)) or "").strip().lower() in _ACTIVE_STATUSES
    )
    critical_count = sum(
        1
        for ticket in tickets
        if str(getattr(getattr(ticket, "priority", None), "value", getattr(ticket, "priority", None)) or "").strip().lower()
        == TicketPriority.critical.value
    )
    return AIChatTicketListResponse(
        list_kind=list_kind,
        title=title,
        scope=scope,
        total_count=len(items),
        summary_metrics=AIChatListMetrics(open_count=open_count, critical_count=critical_count),
        tickets=items,
        top_recommendation=_sla_top_recommendation(tickets, lang=lang) if list_kind == "high_sla_risk" else None,
    )


def is_assignment_query(question: str) -> bool:
    normalized = " ".join(str(question or "").strip().lower().split())
    return any(
        token in normalized
        for token in [
            "assignee",
            "assigned",
            "owner",
            "ownership",
            "who should handle",
            "who owns",
            "reassign",
            "reassignment",
            "assignation",
            "assigne",
            "proprietaire",
            "responsable",
            "reaffect",
        ]
    )
