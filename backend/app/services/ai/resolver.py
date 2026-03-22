"""Shared evidence-first resolver helpers for tickets and chat."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.schemas.ai import AIIncidentCluster, AIResolutionAdvice, AIResolutionEvidence

_ATTEMPT_KEYWORDS = {
    "already",
    "tried",
    "tested",
    "checked",
    "verified",
    "restarted",
    "reset",
    "cleared",
    "flushed",
    "reran",
    "re-ran",
    "resolved",
    "done",
    "deja",
    "essaye",
    "teste",
    "verifie",
    "redemarre",
    "redemarre",
    "corrige",
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_\-/.]{1,}", re.IGNORECASE)
_STEP_STOPWORDS = {
    "the",
    "and",
    "then",
    "with",
    "from",
    "into",
    "that",
    "this",
    "have",
    "your",
    "pour",
    "avec",
    "dans",
    "des",
    "les",
    "une",
    "sur",
    "after",
    "before",
    "ticket",
    "tickets",
    "issue",
    "problem",
}
_VALIDATION_HINTS = {
    "validate",
    "validation",
    "verify",
    "confirm",
    "monitor",
    "document",
    "check",
    "tester",
    "verifier",
    "confirmer",
    "surveiller",
    "documenter",
    "controler",
}


@dataclass(slots=True)
class ResolverOutput:
    mode: str
    retrieval_query: str
    retrieval: dict[str, Any]
    advice: AIResolutionAdvice | None
    recommended_action: str | None
    reasoning: str | None
    match_summary: str | None
    root_cause: str | None = None
    supporting_context: str | None = None
    why_this_matches: list[str] = field(default_factory=list)
    evidence_sources: list[AIResolutionEvidence] = field(default_factory=list)
    next_best_actions: list[str] = field(default_factory=list)
    workflow_steps: list[str] = field(default_factory=list)
    validation_steps: list[str] = field(default_factory=list)
    fallback_action: str | None = None
    confidence: float = 0.0
    missing_information: list[str] = field(default_factory=list)


def _normalize_line(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clamp_unit_confidence(value: float, *, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(ceiling, float(value)))


def _message_attr(message: Any, name: str) -> Any:
    if isinstance(message, dict):
        return message.get(name)
    return getattr(message, name, None)


def _message_role(message: Any) -> str:
    return _normalize_line(_message_attr(message, "role")).lower()


def _message_content(message: Any) -> str:
    return _normalize_line(_message_attr(message, "content"))


def _iter_conversation_messages(conversation_state: Any) -> list[Any]:
    if conversation_state is None:
        return []
    if isinstance(conversation_state, dict):
        rows = conversation_state.get("messages")
        return list(rows or []) if isinstance(rows, Iterable) else []
    if isinstance(conversation_state, (list, tuple)):
        return list(conversation_state)
    rows = getattr(conversation_state, "messages", None)
    if isinstance(rows, (list, tuple)):
        return list(rows)
    return []


def _conversation_summary(conversation_state: Any) -> str:
    if conversation_state is None:
        return ""
    if isinstance(conversation_state, dict):
        return _normalize_line(conversation_state.get("conversation_summary"))
    return _normalize_line(getattr(conversation_state, "conversation_summary", None))


def _conversation_excerpt(conversation_state: Any, *, current_question: str | None = None, limit: int = 420) -> str:
    current = _normalize_line(current_question).casefold()
    snippets: list[str] = []
    summary = _conversation_summary(conversation_state)
    for message in _iter_conversation_messages(conversation_state)[-8:]:
        role = _message_role(message)
        if role != "user":
            continue
        text = _message_content(message)
        if not text or text.casefold() == current:
            continue
        snippets.append(text)
    if not snippets and not summary:
        return ""
    joined = " ".join(part for part in [summary, *snippets[-3:]] if part)
    if len(joined) <= limit:
        return joined
    return joined[: limit - 3].rstrip() + "..."


def _step_tokens(text: str) -> set[str]:
    def normalize_token(token: str) -> str:
        value = token.lower()
        for suffix in ("ing", "ed", "es", "s"):
            if value.endswith(suffix) and len(value) > len(suffix) + 2:
                value = value[: -len(suffix)]
                break
        return value

    return {
        normalize_token(token)
        for token in _TOKEN_PATTERN.findall(_normalize_line(text))
        if len(token) > 2 and token.lower() not in _STEP_STOPWORDS
    }


def _extract_attempted_steps(conversation_state: Any) -> list[str]:
    attempted: list[str] = []
    for message in _iter_conversation_messages(conversation_state)[-10:]:
        if _message_role(message) != "user":
            continue
        text = _message_content(message)
        if not text:
            continue
        parts = re.split(r"[.;,!?\n]+", text)
        for part in parts:
            normalized = _normalize_line(part)
            if not normalized:
                continue
            lowered = normalized.casefold()
            if any(keyword in lowered for keyword in _ATTEMPT_KEYWORDS):
                attempted.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in attempted:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def _step_is_repeated(step: str, attempted_steps: list[str]) -> bool:
    step_tokens = _step_tokens(step)
    if len(step_tokens) < 2:
        return False
    for attempted in attempted_steps:
        attempted_tokens = _step_tokens(attempted)
        overlap = step_tokens & attempted_tokens
        if len(overlap) >= 2 and (len(overlap) / max(1, min(len(step_tokens), len(attempted_tokens)))) >= 0.45:
            return True
    return False


def _filter_attempted_steps(steps: Iterable[str], *, conversation_state: Any) -> list[str]:
    attempted = _extract_attempted_steps(conversation_state)
    if not attempted:
        return [_normalize_line(step) for step in steps if _normalize_line(step)]
    filtered: list[str] = []
    for step in steps:
        normalized = _normalize_line(step)
        if not normalized or _step_is_repeated(normalized, attempted):
            continue
        filtered.append(normalized)
    return filtered


def build_ticket_retrieval_query(
    ticket: Any,
    *,
    user_question: str | None = None,
    conversation_state: Any = None,
    include_priority: bool = True,
) -> str:
    lines = [
        _normalize_line(getattr(ticket, "title", "")),
        _normalize_line(getattr(ticket, "description", "")),
    ]
    if include_priority:
        priority = getattr(ticket, "priority", None)
        status = getattr(ticket, "status", None)
        category = getattr(ticket, "category", None)
        if priority is not None:
            lines.append(f"priority={getattr(priority, 'value', priority)}")
        if status is not None:
            lines.append(f"status={getattr(status, 'value', status)}")
        if category is not None:
            lines.append(f"category={getattr(category, 'value', category)}")
    question = _normalize_line(user_question)
    if question:
        lines.append(question)
    history = _conversation_excerpt(conversation_state, current_question=question or _normalize_line(getattr(ticket, "title", "")))
    if history:
        lines.append(f"conversation={history}")
    return "\n".join(line for line in lines if line).strip()


def build_problem_retrieval_query(
    problem: Any,
    linked_tickets: list[Any],
    *,
    user_question: str | None = None,
    conversation_state: Any = None,
) -> str:
    ticket_titles = "; ".join(
        _normalize_line(getattr(ticket, "title", ""))
        for ticket in linked_tickets[:4]
        if _normalize_line(getattr(ticket, "title", ""))
    )
    lines = [
        _normalize_line(getattr(problem, "id", "")),
        _normalize_line(getattr(problem, "title", "")),
        _normalize_line(getattr(problem, "root_cause", "")),
        _normalize_line(getattr(problem, "workaround", "")),
        _normalize_line(getattr(problem, "permanent_fix", "")),
    ]
    category = getattr(problem, "category", None)
    status = getattr(problem, "status", None)
    if category is not None:
        lines.append(f"category={getattr(category, 'value', category)}")
    if status is not None:
        lines.append(f"status={getattr(status, 'value', status)}")
    if ticket_titles:
        lines.append(f"linked_tickets={ticket_titles}")
    question = _normalize_line(user_question)
    if question:
        lines.append(question)
    history = _conversation_excerpt(
        conversation_state,
        current_question=question or _normalize_line(getattr(problem, "title", "")),
    )
    if history:
        lines.append(f"conversation={history}")
    return "\n".join(line for line in lines if line).strip()


def candidate_tickets_for_ticket(ticket: Any, visible_tickets: list[Any], *, limit: int = 18) -> list[Any]:
    ticket_id = getattr(ticket, "id", None)
    ticket_category = getattr(ticket, "category", None)
    ticket_problem_id = getattr(ticket, "problem_id", None)
    if ticket_category is None and ticket_problem_id is None:
        return list(visible_tickets[:limit])
    prioritized = [
        row
        for row in visible_tickets
        if getattr(row, "id", None) != ticket_id
        and (getattr(row, "category", None) == ticket_category or (ticket_problem_id and getattr(row, "problem_id", None) == ticket_problem_id))
    ]
    if len(prioritized) < limit:
        extra = [row for row in visible_tickets if getattr(row, "id", None) != ticket_id and row not in prioritized]
        prioritized.extend(extra)
    return prioritized[:limit]


def _build_workflow_steps(
    *,
    recommended_action: str | None,
    next_best_actions: list[str],
    mode: str,
    lang: str,
) -> list[str]:
    steps: list[str] = []
    action = _normalize_line(recommended_action)
    if action:
        steps.append(action)
    if mode == "no_strong_match":
        steps.extend(next_best_actions[:3])
        return steps[:4]
    for item in next_best_actions:
        normalized = _normalize_line(item)
        if not normalized or normalized.casefold() == action.casefold():
            continue
        steps.append(normalized)
    if len(steps) < 2:
        steps.append(
            "Validate the result on one affected ticket before wider rollout."
            if lang == "en"
            else "Validez le resultat sur un ticket affecte avant un deploiement plus large."
        )
    return steps[:4]


def _build_validation_steps(
    *,
    next_best_actions: list[str],
    recommended_action: str | None,
    mode: str,
    lang: str,
) -> list[str]:
    validations: list[str] = []
    for item in next_best_actions:
        normalized = _normalize_line(item)
        if not normalized:
            continue
        tokens = _step_tokens(normalized)
        if tokens & _VALIDATION_HINTS:
            validations.append(normalized)
    if validations:
        return validations[:3]
    if mode == "evidence_action":
        return [
            "Confirm the affected service is stable after the change."
            if lang == "en"
            else "Confirmez que le service affecte est stable apres le changement.",
            "Document the validated fix before closure."
            if lang == "en"
            else "Documentez le correctif valide avant la cloture.",
        ]
    if mode == "tentative_diagnostic":
        fallback = _normalize_line(recommended_action)
        if fallback:
            return [
                "Review the diagnostic result before applying a broader fix."
                if lang == "en"
                else "Examinez le resultat du diagnostic avant d'appliquer un correctif plus large."
            ]
    return []


def _build_missing_information(retrieval: dict[str, Any], *, mode: str, lang: str) -> list[str]:
    if mode == "evidence_action":
        return []
    rows: list[str] = []
    if not list(retrieval.get("similar_tickets") or []):
        rows.append(
            "No closely matched resolved ticket was retrieved."
            if lang == "en"
            else "Aucun ticket resolu suffisamment proche n'a ete retrouve."
        )
    if not list(retrieval.get("kb_articles") or []):
        rows.append(
            "No knowledge article aligned closely enough."
            if lang == "en"
            else "Aucun article de connaissance n'etait assez aligne."
        )
    if not list(retrieval.get("related_problems") or []):
        rows.append(
            "No linked problem record provided a stronger root-cause clue."
            if lang == "en"
            else "Aucun problem record lie n'a apporte d'indice de cause racine plus fort."
        )
    return rows[:3]


def _build_response_text(
    *,
    mode: str,
    recommended_action: str | None,
    reasoning: str | None,
    evidence_sources: list[AIResolutionEvidence],
    validation_steps: list[str],
    fallback_action: str | None,
    missing_information: list[str],
    confidence: float,
    confidence_band: str,
    lang: str,
) -> str:
    lines: list[str] = []
    if mode == "evidence_action":
        if lang == "fr":
            lines.append(f"Action recommandee: {recommended_action or fallback_action or 'Aucune action precise.'}")
        else:
            lines.append(f"Recommended action: {recommended_action or fallback_action or 'No concrete action available.'}")
    elif mode == "tentative_diagnostic":
        if lang == "fr":
            fallback_text = "Collectez plus d'elements avant correction."
            lines.append(f"Diagnostic prudent: {recommended_action or fallback_action or fallback_text}")
        else:
            lines.append(f"Tentative diagnostic: {recommended_action or fallback_action or 'Collect more evidence before changing the system.'}")
    else:
        lines.append(
            "Aucune resolution fortement etayee n'est disponible pour l'instant."
            if lang == "fr"
            else "There is no strong evidence-backed resolution yet."
        )
        if fallback_action:
            lines.append(
                f"Prochaine verification utile: {fallback_action}"
                if lang == "fr"
                else f"Most useful next check: {fallback_action}"
            )
    if reasoning:
        lines.append(f"{'Justification' if lang == 'fr' else 'Reasoning'}: {reasoning}")
    if evidence_sources:
        references = ", ".join(source.reference for source in evidence_sources[:3] if source.reference)
        if references:
            lines.append(f"{'Preuves' if lang == 'fr' else 'Evidence'}: {references}")
    if validation_steps:
        lines.append(
            f"{'Validation' if lang == 'fr' else 'Validation'}: {'; '.join(validation_steps[:2])}"
        )
    if missing_information:
        lines.append(
            f"{'Informations manquantes' if lang == 'fr' else 'Missing information'}: {'; '.join(missing_information[:2])}"
        )
    lines.append(
        f"{'Confiance' if lang == 'fr' else 'Confidence'}: {int(round(_clamp_unit_confidence(confidence) * 100))}% ({confidence_band})"
    )
    return "\n".join(line for line in lines if line).strip()


def build_resolution_advice_model(
    advice_payload: dict[str, Any] | None,
    *,
    default_source_label: str = "fallback_rules",
    lang: str = "en",
    conversation_state: Any = None,
) -> AIResolutionAdvice | None:
    if not isinstance(advice_payload, dict):
        return None
    recommended_action = _normalize_line(advice_payload.get("recommended_action")) or None
    display_mode = _normalize_line(advice_payload.get("display_mode")) or "evidence_action"
    reasoning = _normalize_line(advice_payload.get("reasoning")) or ""
    if not reasoning and not recommended_action and display_mode != "no_strong_match":
        return None
    evidence_sources = [
        AIResolutionEvidence(
            evidence_type=_normalize_line(item.get("evidence_type")),
            reference=_normalize_line(item.get("reference")),
            excerpt=_normalize_line(item.get("excerpt")) or None,
            source_id=_normalize_line(item.get("source_id")) or None,
            title=_normalize_line(item.get("title")) or None,
            relevance=_clamp_unit_confidence(float(item.get("relevance") or 0.0)),
            why_relevant=_normalize_line(item.get("why_relevant")) or None,
        )
        for item in list(advice_payload.get("evidence_sources") or [])
        if _normalize_line(item.get("reference"))
    ][:3]
    next_best_actions = _filter_attempted_steps(list(advice_payload.get("next_best_actions") or []), conversation_state=conversation_state)[:4]
    explicit_workflow_steps = [
        _normalize_line(item)
        for item in list(advice_payload.get("workflow_steps") or [])
        if _normalize_line(item)
    ]
    workflow_steps = _filter_attempted_steps(
        explicit_workflow_steps
        or _build_workflow_steps(
            recommended_action=recommended_action,
            next_best_actions=next_best_actions,
            mode=display_mode,
            lang=lang,
        ),
        conversation_state=conversation_state,
    )[:4]
    explicit_validation_steps = [
        _normalize_line(item)
        for item in list(advice_payload.get("validation_steps") or [])
        if _normalize_line(item)
    ]
    validation_steps = _filter_attempted_steps(
        explicit_validation_steps
        or _build_validation_steps(
            next_best_actions=next_best_actions,
            recommended_action=recommended_action,
            mode=display_mode,
            lang=lang,
        ),
        conversation_state=conversation_state,
    )[:3]
    fallback_action = _normalize_line(advice_payload.get("fallback_action")) or None
    if not fallback_action:
        if display_mode == "tentative_diagnostic":
            fallback_action = recommended_action
        elif display_mode == "no_strong_match" and next_best_actions:
            fallback_action = next_best_actions[0]
    missing_information = [
        _normalize_line(item)
        for item in list(advice_payload.get("missing_information") or [])
        if _normalize_line(item)
    ][:3]
    confidence = _clamp_unit_confidence(float(advice_payload.get("confidence") or 0.0))
    confidence_band = _normalize_line(advice_payload.get("confidence_band")) or (
        "high" if confidence >= 0.78 else "medium" if confidence >= 0.52 else "low"
    )
    response_text = _normalize_line(advice_payload.get("response_text")) or _build_response_text(
        mode=display_mode,
        recommended_action=recommended_action,
        reasoning=reasoning,
        evidence_sources=evidence_sources,
        validation_steps=validation_steps,
        fallback_action=fallback_action,
        missing_information=missing_information,
        confidence=confidence,
        confidence_band=confidence_band,
        lang=lang,
    )
    return AIResolutionAdvice(
        recommended_action=recommended_action,
        reasoning=reasoning,
        probable_root_cause=_normalize_line(advice_payload.get("probable_root_cause")) or None,
        root_cause=_normalize_line(advice_payload.get("root_cause")) or _normalize_line(advice_payload.get("probable_root_cause")) or None,
        supporting_context=_normalize_line(advice_payload.get("supporting_context")) or None,
        why_this_matches=[
            _normalize_line(item)
            for item in list(advice_payload.get("why_this_matches") or [])
            if _normalize_line(item)
        ][:4],
        evidence_sources=evidence_sources,
        tentative=bool(advice_payload.get("tentative", False)),
        confidence=confidence,
        confidence_band=confidence_band,
        confidence_label=_normalize_line(advice_payload.get("confidence_label")) or confidence_band,
        source_label=_normalize_line(advice_payload.get("source_label")) or default_source_label,
        recommendation_mode=_normalize_line(advice_payload.get("recommendation_mode")) or "fallback_rules",
        action_relevance_score=_clamp_unit_confidence(float(advice_payload.get("action_relevance_score") or 0.0)),
        filtered_weak_match=bool(advice_payload.get("filtered_weak_match", False)),
        mode=_normalize_line(advice_payload.get("mode")) or display_mode,
        display_mode=display_mode,
        match_summary=_normalize_line(advice_payload.get("match_summary")) or None,
        next_best_actions=next_best_actions,
        incident_cluster=(
            AIIncidentCluster(
                count=max(0, int((advice_payload.get("incident_cluster") or {}).get("count") or 0)),
                window_hours=max(1, int((advice_payload.get("incident_cluster") or {}).get("window_hours") or 24)),
                summary=_normalize_line((advice_payload.get("incident_cluster") or {}).get("summary")),
            )
            if _normalize_line((advice_payload.get("incident_cluster") or {}).get("summary"))
            else None
        ),
        impact_summary=_normalize_line(advice_payload.get("impact_summary")) or None,
        workflow_steps=workflow_steps,
        validation_steps=validation_steps,
        fallback_action=fallback_action,
        missing_information=missing_information,
        response_text=response_text,
    )


def resolution_advice_to_payload(advice: AIResolutionAdvice | None) -> dict[str, Any] | None:
    if advice is None:
        return None
    return {
        "recommended_action": advice.recommended_action,
        "reasoning": advice.reasoning,
        "probable_root_cause": advice.probable_root_cause,
        "root_cause": advice.root_cause,
        "supporting_context": advice.supporting_context,
        "why_this_matches": list(advice.why_this_matches),
        "evidence_sources": [
            {
                "evidence_type": item.evidence_type,
                "reference": item.reference,
                "excerpt": item.excerpt,
                "source_id": item.source_id,
                "title": item.title,
                "relevance": item.relevance,
                "why_relevant": item.why_relevant,
            }
            for item in advice.evidence_sources
        ],
        "tentative": advice.tentative,
        "confidence": advice.confidence,
        "confidence_band": advice.confidence_band,
        "confidence_label": advice.confidence_label,
        "source_label": advice.source_label,
        "recommendation_mode": advice.recommendation_mode,
        "action_relevance_score": advice.action_relevance_score,
        "filtered_weak_match": advice.filtered_weak_match,
        "mode": advice.mode,
        "display_mode": advice.display_mode,
        "match_summary": advice.match_summary,
        "next_best_actions": list(advice.next_best_actions),
        "incident_cluster": (
            {
                "count": advice.incident_cluster.count,
                "window_hours": advice.incident_cluster.window_hours,
                "summary": advice.incident_cluster.summary,
            }
            if advice.incident_cluster
            else None
        ),
        "impact_summary": advice.impact_summary,
        "workflow_steps": list(advice.workflow_steps),
        "validation_steps": list(advice.validation_steps),
        "fallback_action": advice.fallback_action,
        "missing_information": list(advice.missing_information),
        "response_text": advice.response_text,
    }


def resolve_ticket_advice(
    db: Session,
    ticket: Any,
    *,
    user_question: str | None = None,
    conversation_state: Any = None,
    visible_tickets: list[Any] | None = None,
    top_k: int = 5,
    solution_quality: str = "medium",
    include_workflow: bool = True,
    include_priority: bool = True,
    lang: str = "en",
    retrieval_fn: Callable[..., dict[str, Any]] | None = None,
    advice_builder: Callable[..., dict[str, Any] | None] | None = None,
) -> ResolverOutput:
    if retrieval_fn is None:
        from app.services.ai.retrieval import unified_retrieve as retrieval_fn
    if advice_builder is None:
        from app.services.ai.resolution_advisor import build_resolution_advice as advice_builder
    retrieval_query = build_ticket_retrieval_query(
        ticket,
        user_question=user_question,
        conversation_state=conversation_state,
        include_priority=include_priority,
    )
    candidates = candidate_tickets_for_ticket(ticket, list(visible_tickets or []))
    retrieval = retrieval_fn(
        db,
        query=retrieval_query,
        visible_tickets=candidates,
        top_k=top_k,
        solution_quality=solution_quality,
    )
    default_source_label = _normalize_line((retrieval or {}).get("source")) or "fallback_rules"
    advice_payload = advice_builder(retrieval, lang=lang)
    advice = build_resolution_advice_model(
        advice_payload,
        default_source_label=default_source_label,
        lang=lang,
        conversation_state=conversation_state,
    )
    mode = advice.display_mode if advice is not None else "no_strong_match"
    missing_information = list(advice.missing_information) if advice is not None else _build_missing_information(retrieval or {}, mode=mode, lang=lang)
    if advice is not None and not advice.missing_information and mode != "evidence_action":
        advice.missing_information = missing_information
        advice.response_text = _build_response_text(
            mode=mode,
            recommended_action=advice.recommended_action,
            reasoning=advice.reasoning,
            evidence_sources=advice.evidence_sources,
            validation_steps=advice.validation_steps,
            fallback_action=advice.fallback_action,
            missing_information=missing_information,
            confidence=advice.confidence,
            confidence_band=advice.confidence_band,
            lang=lang,
        )
    recommended_action = advice.recommended_action if advice is not None else None
    next_best_actions = list(advice.next_best_actions) if advice is not None else []
    workflow_steps = list(advice.workflow_steps) if advice is not None and include_workflow else []
    validation_steps = list(advice.validation_steps) if advice is not None and include_workflow else []
    fallback_action = advice.fallback_action if advice is not None else None
    return ResolverOutput(
        mode=mode,
        retrieval_query=retrieval_query,
        retrieval=retrieval,
        advice=advice,
        recommended_action=recommended_action,
        reasoning=advice.reasoning if advice is not None else None,
        match_summary=advice.match_summary if advice is not None else None,
        root_cause=advice.root_cause if advice is not None else None,
        supporting_context=advice.supporting_context if advice is not None else None,
        why_this_matches=list(advice.why_this_matches) if advice is not None else [],
        evidence_sources=list(advice.evidence_sources) if advice is not None else [],
        next_best_actions=next_best_actions,
        workflow_steps=workflow_steps,
        validation_steps=validation_steps,
        fallback_action=fallback_action,
        confidence=advice.confidence if advice is not None else 0.0,
        missing_information=missing_information,
    )


def resolve_problem_advice(
    db: Session,
    problem: Any,
    *,
    linked_tickets: list[Any] | None = None,
    user_question: str | None = None,
    conversation_state: Any = None,
    top_k: int = 5,
    solution_quality: str = "medium",
    include_workflow: bool = True,
    lang: str = "en",
    retrieval_fn: Callable[..., dict[str, Any]] | None = None,
    advice_builder: Callable[..., dict[str, Any] | None] | None = None,
) -> ResolverOutput:
    if retrieval_fn is None:
        from app.services.ai.retrieval import unified_retrieve as retrieval_fn
    if advice_builder is None:
        from app.services.ai.resolution_advisor import build_resolution_advice as advice_builder
    visible = list(linked_tickets or [])
    retrieval_query = build_problem_retrieval_query(
        problem,
        visible,
        user_question=user_question,
        conversation_state=conversation_state,
    )
    retrieval = retrieval_fn(
        db,
        query=retrieval_query,
        visible_tickets=visible,
        top_k=top_k,
        solution_quality=solution_quality,
    )
    default_source_label = _normalize_line((retrieval or {}).get("source")) or "fallback_rules"
    advice_payload = advice_builder(retrieval, lang=lang)
    advice = build_resolution_advice_model(
        advice_payload,
        default_source_label=default_source_label,
        lang=lang,
        conversation_state=conversation_state,
    )
    mode = advice.display_mode if advice is not None else "no_strong_match"
    missing_information = list(advice.missing_information) if advice is not None else _build_missing_information(retrieval or {}, mode=mode, lang=lang)
    if advice is not None and not advice.missing_information and mode != "evidence_action":
        advice.missing_information = missing_information
        advice.response_text = _build_response_text(
            mode=mode,
            recommended_action=advice.recommended_action,
            reasoning=advice.reasoning,
            evidence_sources=advice.evidence_sources,
            validation_steps=advice.validation_steps,
            fallback_action=advice.fallback_action,
            missing_information=missing_information,
            confidence=advice.confidence,
            confidence_band=advice.confidence_band,
            lang=lang,
        )
    recommended_action = advice.recommended_action if advice is not None else None
    next_best_actions = list(advice.next_best_actions) if advice is not None else []
    workflow_steps = list(advice.workflow_steps) if advice is not None and include_workflow else []
    validation_steps = list(advice.validation_steps) if advice is not None and include_workflow else []
    fallback_action = advice.fallback_action if advice is not None else None
    return ResolverOutput(
        mode=mode,
        retrieval_query=retrieval_query,
        retrieval=retrieval,
        advice=advice,
        recommended_action=recommended_action,
        reasoning=advice.reasoning if advice is not None else None,
        match_summary=advice.match_summary if advice is not None else None,
        root_cause=advice.root_cause if advice is not None else None,
        supporting_context=advice.supporting_context if advice is not None else None,
        why_this_matches=list(advice.why_this_matches) if advice is not None else [],
        evidence_sources=list(advice.evidence_sources) if advice is not None else [],
        next_best_actions=next_best_actions,
        workflow_steps=workflow_steps,
        validation_steps=validation_steps,
        fallback_action=fallback_action,
        confidence=advice.confidence if advice is not None else 0.0,
        missing_information=missing_information,
    )
