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
    AIChatExtendedActionLink,
    AIChatInsufficientEvidenceResponse,
    AIChatListMetrics,
    AIChatListTicketItem,
    AIChatProblemDetailResponse,
    AIChatProblemLinkedTicketItem,
    AIChatProblemLinkedTicketsResponse,
    AIChatProblemListItem,
    AIChatProblemListResponse,
    AIChatRecommendationListItem,
    AIChatRecommendationListResponse,
    AIChatRelatedEntity,
    AIChatRelatedTicketRef,
    AIChatResolutionAdviceResponse,
    AIChatSLAState,
    AIChatSimilarTicketMatch,
    AIChatSimilarTicketsResponse,
    AIChatStatusResponse,
    AIChatStructuredResponse,
    AIChatTicketDetailsResponse,
    AIChatTicketCommentItem,
    AIChatTicketListResponse,
    AIChatTicketThreadResponse,
    AIChatTopRecommendation,
)
from app.services.ai.calibration import confidence_band
from app.services.ai.formatters import _priority_label, _status_label
from app.services.ai.resolver import ResolverOutput
from app.services.ai.similar_tickets import select_visible_similar_ticket_matches
from app.services.ai.service_requests import build_service_request_guidance
from app.services.ai.taxonomy import TOPIC_HINTS

_ACTIVE_STATUSES = {
    TicketStatus.open.value,
    TicketStatus.in_progress.value,
    TicketStatus.waiting_for_customer.value,
    TicketStatus.waiting_for_support_vendor.value,
    TicketStatus.pending.value,
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


def build_service_request_response(
    ticket: Any,
    *,
    lang: str = "fr",
) -> dict[str, Any]:
    """Build a task-oriented response for planned service requests."""

    payload = build_service_request_guidance(ticket, lang=lang, enable_llm_refinement=True)
    payload.setdefault("cause_analysis", None)
    return payload


def _priority_text(ticket: Any, *, lang: str) -> str:
    raw = getattr(getattr(ticket, "priority", None), "value", getattr(ticket, "priority", None)) or "unknown"
    return _priority_label(str(raw), lang)


def _status_text(ticket: Any, *, lang: str) -> str:
    raw = getattr(getattr(ticket, "status", None), "value", getattr(ticket, "status", None)) or "unknown"
    return _status_label(str(raw), lang)


def _assignee_text(ticket: Any, *, lang: str) -> str:
    return str(getattr(ticket, "assignee", None) or ("Unassigned" if lang == "en" else "Non assigne"))


def _ticket_type_text(ticket: Any) -> str | None:
    return _string_or_none(getattr(getattr(ticket, "ticket_type", None), "value", getattr(ticket, "ticket_type", None)))


def _category_text(ticket: Any) -> str | None:
    return _string_or_none(getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)))


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
    comments = list(getattr(ticket, "comments", None) or [])
    comments = sorted(
        comments,
        key=lambda comment: _iso_or_none(getattr(comment, "created_at", None)) or "",
        reverse=True,
    )
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
        ticket_type=getattr(ticket, "ticket_type", None),
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
    return confidence_band(score)


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


def _topic_match_score(text: str, topic: str) -> int:
    lowered = text.casefold()
    hints = TOPIC_HINTS.get(str(topic or "").strip().lower()) or set()
    return sum(1 for hint in hints if hint in lowered)


def _best_matching_topic(text: str) -> tuple[str | None, int]:
    best_topic: str | None = None
    best_score = 0
    for topic in TOPIC_HINTS:
        score = _topic_match_score(text, topic)
        if score > best_score:
            best_topic = topic
            best_score = score
    return best_topic, best_score


def _lines_in_selected_family(
    rows: list[str],
    *,
    resolver_output: ResolverOutput | None,
    limit: int,
) -> list[str]:
    scoped_rows = _dedupe_lines(rows, limit=max(6, limit * 2))
    preferred_topic = _selected_cluster_topic(resolver_output)
    hints = set(TOPIC_HINTS.get(str(preferred_topic or "").strip().lower()) or [])
    if not hints:
        return scoped_rows[:limit]
    scoped: list[str] = []
    for row in scoped_rows:
        preferred_score = _topic_match_score(row, str(preferred_topic or ""))
        if preferred_score == 0:
            continue
        best_topic, best_score = _best_matching_topic(row)
        if best_score == 0 or best_topic == str(preferred_topic or "").strip().lower():
            scoped.append(row)
    return (scoped or scoped_rows)[:limit]


def _recommended_checks_in_scope(resolver_output: ResolverOutput | None, *, limit: int = 3) -> list[str]:
    return _lines_in_selected_family(
        list(getattr(resolver_output, "validation_steps", []) or [])
        + list(getattr(resolver_output, "next_best_actions", []) or [])
        + ([resolver_output.fallback_action] if resolver_output and resolver_output.fallback_action else []),
        resolver_output=resolver_output,
        limit=limit,
    )


def _validation_steps_in_scope(resolver_output: ResolverOutput | None, *, limit: int = 4) -> list[str]:
    validation_rows = _lines_in_selected_family(
        list(getattr(resolver_output, "validation_steps", []) or []),
        resolver_output=resolver_output,
        limit=limit,
    )
    missing_rows = _dedupe_lines(list(getattr(resolver_output, "missing_information", []) or []), limit=limit)
    return _dedupe_lines(validation_rows + missing_rows, limit=limit)


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
    return confidence_band(score)


def _supported_cause_hypothesis(
    *,
    advice: Any,
    related_rows: list[dict[str, Any]],
    evidence_refs: list[str],
    confidence: AIChatConfidence,
) -> bool:
    if _string_or_none(getattr(advice, "root_cause", None)):
        return True
    if not _string_or_none(getattr(advice, "probable_root_cause", None)):
        return False
    if related_rows and evidence_refs:
        return True
    if confidence.level in {"medium", "high"} and len(evidence_refs) >= 2:
        return True
    return False


def _cause_summary(
    *,
    title: str,
    confidence: AIChatConfidence,
    confirmed: bool,
    lang: str,
) -> str:
    if lang == "fr":
        if confirmed and confidence.level == "high":
            return f"Cause la plus probable dans ce contexte : {title}."
        return f"Aucune cause racine confirmee pour l'instant. Hypothese principale actuelle dans ce contexte : {title}."
    if confirmed and confidence.level == "high":
        return f"Most likely in-scope cause: {title}."
    return f"No confirmed root cause yet. Strongest supported in-scope hypothesis: {title}."


def _cause_explanation(
    *,
    advice: Any,
    confirmed: bool,
    related_rows: list[dict[str, Any]],
    evidence_refs: list[str],
    lang: str,
) -> str:
    base = _string_or_none(getattr(advice, "match_summary", None)) or _string_or_none(getattr(advice, "reasoning", None))
    evidence_bits: list[str] = []
    if related_rows:
        evidence_bits.append(
            "a scoped recurring problem pattern" if lang == "en" else "un schema de probleme recurrent dans le meme perimetre"
        )
    if len(evidence_refs) >= 2:
        evidence_bits.append(
            "multiple aligned evidence references" if lang == "en" else "plusieurs references de preuve alignees"
        )
    elif len(evidence_refs) == 1:
        evidence_bits.append(
            "one direct evidence reference" if lang == "en" else "une reference de preuve directe"
        )
    if confirmed:
        return base or (
            "This cause is the strongest match supported by the retrieved evidence."
            if lang == "en"
            else "Cette cause est la correspondance la plus forte soutenue par les preuves recuperees."
        )
    support_text = ""
    if evidence_bits:
        if lang == "en":
            support_text = " It remains a hypothesis supported by " + " and ".join(evidence_bits) + "."
        else:
            support_text = " Cela reste une hypothese soutenue par " + " et ".join(evidence_bits) + "."
    return (base or (
        "Evidence is still limited, so this remains the leading in-scope hypothesis."
        if lang == "en"
        else "Les preuves restent limitees, donc cela reste l'hypothese principale dans ce contexte."
    )) + support_text


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
    if not _supported_cause_hypothesis(
        advice=advice,
        related_rows=related_rows,
        evidence_refs=evidence_refs,
        confidence=confidence,
    ):
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
    possible_causes: list[AIChatCauseCandidate] = []
    seen: set[str] = set()

    confirmed_cause = _string_or_none(advice.root_cause)
    primary_cause = confirmed_cause or _string_or_none(advice.probable_root_cause)
    if primary_cause:
        seen.add(primary_cause.casefold())
        possible_causes.append(
            AIChatCauseCandidate(
                title=primary_cause,
                likelihood="high" if confirmed_cause and confidence.level == "high" else _likelihood_from_score(float(advice.confidence or 0.0)),
                explanation=_cause_explanation(
                    advice=advice,
                    confirmed=bool(confirmed_cause),
                    related_rows=related_rows,
                    evidence_refs=evidence_refs,
                    lang=lang,
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

    summary = _cause_summary(
        title=possible_causes[0].title,
        confidence=confidence,
        confirmed=bool(confirmed_cause),
        lang=lang,
    )
    return AIChatCauseAnalysisResponse(
        ticket_id=str(getattr(ticket, "id", "") or "") or None,
        summary=summary,
        possible_causes=possible_causes,
        recommended_checks=_recommended_checks_in_scope(resolver_output, limit=4),
        validation_steps=_validation_steps_in_scope(resolver_output, limit=4),
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
    source_ticket: Any | None,
    visible_tickets: list[Any] | None,
    resolver_output: ResolverOutput | None,
    lang: str,
) -> AIChatStructuredResponse:
    rows = list((resolver_output.retrieval or {}).get("similar_tickets") or []) if resolver_output is not None else []
    filtered_matches = select_visible_similar_ticket_matches(
        source_ticket=source_ticket,
        visible_tickets=visible_tickets,
        retrieval_rows=rows,
        limit=5,
        min_score=0.3,
    )
    matches = [
        AIChatSimilarTicketMatch(
            ticket_id=str(getattr(match["ticket"], "id", "") or ""),
            title=_string_or_none(getattr(match["ticket"], "title", None)) or str(getattr(match["ticket"], "id", "") or "Ticket"),
            match_reason=_similarity_reason(match["row"], lang=lang),
            match_score=float(match["similarity_score"] or 0.0),
            status=_string_or_none(getattr(match["ticket"], "status", None)),
            route=_ticket_route(str(getattr(match["ticket"], "id", "") or "")),
        )
        for match in filtered_matches
    ]
    if not matches:
        return build_insufficient_evidence_payload(
            resolver_output=resolver_output,
            ticket=None,
            lang=lang,
            summary=(
                f"No sufficiently similar tickets were retrieved for {source_ticket_id}."
                if lang == "en" and source_ticket_id
                else "No sufficiently similar tickets were retrieved for this request."
                if lang == "en"
                else f"Aucun ticket suffisamment similaire n'a ete recupere pour {source_ticket_id}."
                if source_ticket_id
                else "Aucun ticket suffisamment similaire n'a ete recupere pour cette demande."
            ),
        )
    return AIChatSimilarTicketsResponse(
        source_ticket_id=source_ticket_id,
        matches=matches,
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
    total_count: int | None = None,
) -> AIChatTicketListResponse:
    items = [
        AIChatListTicketItem(
            ticket_id=str(getattr(ticket, "id", "") or ""),
            title=str(getattr(ticket, "title", "") or ""),
            status=_status_text(ticket, lang=lang),
            priority=_priority_text(ticket, lang=lang),
            assignee=_assignee_text(ticket, lang=lang),
            ticket_type=_ticket_type_text(ticket),
            category=_category_text(ticket),
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
        total_count=int(total_count if total_count is not None else len(items)),
        returned_count=len(items),
        has_more=(int(total_count if total_count is not None else len(items)) > len(items)),
        summary_metrics=AIChatListMetrics(open_count=open_count, critical_count=critical_count),
        tickets=items,
        top_recommendation=_sla_top_recommendation(tickets, lang=lang) if list_kind == "high_sla_risk" else None,
        action_links=[],
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


def build_problem_detail_payload(
    problem: dict,
    linked_ticket_count: int,
    ai_probable_cause: str | None,
    language: str = "fr",
) -> AIChatProblemDetailResponse:
    """Build a structured chat payload for a problem detail response.

    Formats problem fields into a chat-renderable card consistent with how
    ticket detail payloads are built. Includes status badge, three resolution
    fields (shown only when non-null), and action links.

    Args:
        problem: Problem dict from the database (all fields).
        linked_ticket_count: Count of tickets linked to this problem.
        ai_probable_cause: Probable cause from resolver if root_cause is
            not yet confirmed. None if both are absent.
        language: "fr" or "en" for label localization.
    Returns:
        Structured problem detail payload for chat rendering.
    """
    problem_id = str(problem.get("id") or "")
    return AIChatProblemDetailResponse(
        problem_id=problem_id,
        title=str(problem.get("title") or ""),
        status=str(problem.get("status") or ""),
        category=str(problem.get("category") or ""),
        occurrences_count=int(problem.get("occurrences_count") or 0),
        active_count=int(problem.get("active_count") or 0),
        root_cause=str(problem.get("root_cause") or "") or None,
        workaround=str(problem.get("workaround") or "") or None,
        permanent_fix=str(problem.get("permanent_fix") or "") or None,
        ai_probable_cause=str(ai_probable_cause).strip() if ai_probable_cause else None,
        linked_ticket_count=linked_ticket_count,
        last_seen_at=str(problem.get("last_seen_at") or "") or None,
        action_links=[
            AIChatExtendedActionLink(
                label="Voir le problème" if language == "fr" else "View Problem",
                route=f"/problems/{problem_id}",
            ),
            AIChatExtendedActionLink(
                label="Tickets liés" if language == "fr" else "Show Linked Tickets",
                intent="problem_linked_tickets",
            ),
        ],
    )


def build_problem_list_payload(
    problems: list[dict],
    status_filter: str | None,
    language: str = "fr",
) -> AIChatProblemListResponse:
    """Build a structured chat payload for a problem list response.

    Args:
        problems: List of problem dicts from the database.
        status_filter: Status that was applied, or None for all.
        language: "fr" or "en".
    Returns:
        Structured problem list payload for chat rendering.
    """
    _ = language
    return AIChatProblemListResponse(
        title="Problems" if language == "en" else "Problemes",
        scope=(f"status={status_filter}" if status_filter else None),
        problems=[
            AIChatProblemListItem(
                id=str(p.get("id") or ""),
                title=str(p.get("title") or ""),
                status=str(p.get("status") or ""),
                category=str(p.get("category") or ""),
                occurrences_count=int(p.get("occurrences_count") or 0),
                active_count=int(p.get("active_count") or 0),
                last_seen_at=str(p.get("last_seen_at") or "") or None,
                workaround=str(p.get("workaround") or "") or None,
            )
            for p in problems
        ],
        status_filter=status_filter,
        total_count=len(problems),
        returned_count=len(problems),
        has_more=False,
        action_links=[],
    )


def build_problem_linked_tickets_payload(
    *,
    problem_id: str,
    tickets: list[dict[str, Any]],
    language: str = "fr",
) -> AIChatProblemLinkedTicketsResponse:
    rows = [
        AIChatProblemLinkedTicketItem(
            id=str(ticket.get("id") or ""),
            title=str(ticket.get("title") or ""),
            status=str(ticket.get("status") or ""),
            priority=str(ticket.get("priority") or ""),
            assignee=str(ticket.get("assignee") or ""),
            created_at=str(ticket.get("created_at") or "") or None,
            route=str(ticket.get("route") or ""),
        )
        for ticket in tickets
        if str(ticket.get("id") or "").strip()
    ]
    return AIChatProblemLinkedTicketsResponse(
        problem_id=str(problem_id or ""),
        title="Problem linked tickets" if language == "en" else "Tickets lies au probleme",
        tickets=rows,
        total_count=len(rows),
        returned_count=len(rows),
        has_more=False,
        action_links=[],
    )


def build_recommendation_list_payload(
    *,
    recommendations: list[dict[str, Any]],
    language: str = "fr",
) -> AIChatRecommendationListResponse:
    rows = [
        AIChatRecommendationListItem(
            id=str(rec.get("id") or ""),
            title=str(rec.get("title") or ""),
            type=str(rec.get("type") or ""),
            confidence=float(rec.get("confidence") or 0.0),
            impact=str(rec.get("impact") or ""),
            description=str(rec.get("description") or ""),
        )
        for rec in recommendations
        if str(rec.get("id") or "").strip()
    ]
    return AIChatRecommendationListResponse(
        title="Recommendations" if language == "en" else "Recommandations",
        scope=None,
        recommendations=rows,
        total_count=len(rows),
        returned_count=len(rows),
        has_more=False,
        action_links=[
            AIChatExtendedActionLink(
                label="Voir toutes les recommandations" if language == "fr" else "View All",
                route="/recommendations",
            )
        ],
    )


def build_ticket_thread_payload(ticket: Any, *, lang: str) -> AIChatTicketThreadResponse:
    """Build a structured payload exposing all comments + resolution for a ticket."""
    ticket_id = str(getattr(ticket, "id", "") or "")
    title = str(getattr(ticket, "title", "") or "")
    raw_status = getattr(ticket, "status", None)
    status_val = str(getattr(raw_status, "value", raw_status) or "")
    is_resolved = status_val in {"resolved", "closed"}
    resolution = str(getattr(ticket, "resolution", "") or "").strip() or None

    comments_raw = list(getattr(ticket, "comments", []) or [])
    items: list[AIChatTicketCommentItem] = []
    for c in comments_raw:
        content = str(getattr(c, "content", "") or "").strip()
        if not content:
            continue
        author = str(getattr(c, "author", "") or "").strip() or ("Unknown" if lang == "en" else "Inconnu")
        created_at = None
        raw_ts = getattr(c, "created_at", None)
        if raw_ts is not None:
            try:
                if hasattr(raw_ts, "strftime"):
                    created_at = raw_ts.strftime("%Y-%m-%d %H:%M")
                else:
                    created_at = str(raw_ts)[:16]
            except Exception:  # noqa: BLE001
                pass
        source = str(getattr(c, "external_source", "") or "").strip() or None
        items.append(AIChatTicketCommentItem(
            author=author,
            content=content[:600],
            created_at=created_at,
            source=source,
        ))

    return AIChatTicketThreadResponse(
        ticket_id=ticket_id,
        title=title,
        status=status_val,
        is_resolved=is_resolved,
        resolution=resolution,
        comment_count=len(items),
        comments=items,
    )
