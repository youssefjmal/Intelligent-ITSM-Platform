"""Shared evidence-first resolver helpers for tickets and chat."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.schemas.ai import (
    AIIncidentCluster,
    AILLMGeneralAdvisory,
    AIResolutionAdvice,
    AIResolutionEvidence,
    GuidanceContract,
    RetrievalResult,
)
from app.services.ai.calibration import confidence_band
from app.services.ai.routing_validation import validate_ticket_routing_for_ticket
from app.services.ai.service_requests import (
    service_request_profile_from_ticket,
    service_request_profile_similarity,
)

logger = logging.getLogger(__name__)

# Tokens that indicate a negation context around an attempted-step keyword.
# Used by _has_negation_near_match to avoid adding actions to the
# "already tried" list when the user says they have NOT done something.
# Example: "I haven't restarted the service" → do NOT add "restart" to attempted list.
NEGATION_MARKERS: frozenset[str] = frozenset({
    "not", "never", "haven't", "hasn't", "didn't", "don't",
    "doesn't", "no", "n't", "cannot", "can't",
})

# Number of tokens to check on each side of a keyword match when detecting
# negation.  4 is conservative — sufficient for standard negation constructions
# like "I haven't X" or "I did not X yet".  Increase only with test coverage.
NEGATION_WINDOW_SIZE: int = 4

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
    retrieval: RetrievalResult
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
    guidance_contract: GuidanceContract | None = None


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


def _has_negation_near_match(tokens: list[str], match_index: int, window: int = NEGATION_WINDOW_SIZE) -> bool:
    """Check whether a negation marker appears within a token window around a match.

    Used to prevent false positives in attempted-step detection when the user
    says "I haven't tried X" — the word "tried" should not add X to the
    attempted list if a negation is nearby.

    Negation markers are defined in the module-level ``NEGATION_MARKERS``
    frozenset.  The window size is controlled by ``NEGATION_WINDOW_SIZE``.

    Args:
        tokens: List of whitespace-split tokens from the sentence (lowercased).
        match_index: Index of the matched keyword token in the list.
        window: Number of tokens to check on each side of the match.
                Defaults to ``NEGATION_WINDOW_SIZE`` (4).

    Returns:
        True if a negation marker is found within the window.  When True,
        the matched action should NOT be added to the attempted list.

    Edge cases:
        - If ``tokens`` is empty or ``match_index`` is out of range, returns
          False so that the caller's conservative default (add to list) applies.
        - Contractions like "haven't" are checked as whole lowercased tokens.
    """
    if not tokens or match_index < 0 or match_index >= len(tokens):
        return False
    start = max(0, match_index - window)
    end = min(len(tokens), match_index + window + 1)
    window_tokens = tokens[start:end]
    return any(tok in NEGATION_MARKERS for tok in window_tokens)


def _extract_attempted_steps(conversation_state: Any) -> list[str]:
    """Extract sentences from recent user messages that describe already-attempted steps.

    Searches the last 10 user messages for sentences containing attempt keywords
    (e.g. "already", "tried", "restarted").  Before adding a sentence to the
    attempted list, negation detection is applied: if a negation marker from
    ``NEGATION_MARKERS`` appears within ``NEGATION_WINDOW_SIZE`` tokens of
    the matched keyword, the sentence is skipped.

    This prevents the resolver from treating "I haven't restarted the service"
    as evidence that a restart was already attempted.

    Negation window size: controlled by ``NEGATION_WINDOW_SIZE`` constant.
    Conservative default: when a sentence is too short to tokenize reliably,
    it is NOT added to the attempted list.

    Args:
        conversation_state: Dict, list, or object containing a ``messages``
                            attribute/key with the conversation history.

    Returns:
        De-duplicated list of up to 6 attempted-step sentences (most recent first).
    """
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
            # Tokenize by whitespace for negation detection.
            tokens = lowered.split()
            for keyword in _ATTEMPT_KEYWORDS:
                if keyword not in lowered:
                    continue
                # Find the position of this keyword token in the token list
                # so we can check the surrounding window for negation markers.
                try:
                    match_index = tokens.index(keyword)
                except ValueError:
                    # Keyword matched as substring; check all token positions.
                    match_index = next(
                        (i for i, tok in enumerate(tokens) if tok.startswith(keyword) or keyword in tok),
                        -1,
                    )
                if match_index == -1:
                    # Cannot locate keyword in token list — skip conservatively.
                    continue
                if _has_negation_near_match(tokens, match_index):
                    logger.debug(
                        "Skipped attempted step %r — negation detected near match in %r.",
                        keyword,
                        normalized[:80],
                    )
                    break  # negation found in this sentence; skip entire sentence
                # No negation found — record this sentence as an attempted step.
                attempted.append(normalized)
                break  # one keyword match per sentence is sufficient
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
    summary_context = _normalize_line(getattr(ticket, "summary_context", ""))
    if summary_context:
        lines.append(f"current_summary={summary_context}")
    comment_context = _normalize_line(getattr(ticket, "comment_context", ""))
    if comment_context:
        lines.append(f"current_comments={comment_context}")
    resolution_context = _normalize_line(getattr(ticket, "resolution_context", ""))
    if resolution_context:
        lines.append(f"current_resolution={resolution_context}")
    if include_priority:
        priority = getattr(ticket, "priority", None)
        status = getattr(ticket, "status", None)
        category = getattr(ticket, "category", None)
        ticket_type = getattr(ticket, "ticket_type", None)
        if priority is not None:
            lines.append(f"priority={getattr(priority, 'value', priority)}")
        if status is not None:
            lines.append(f"status={getattr(status, 'value', status)}")
        if category is not None:
            lines.append(f"category={getattr(category, 'value', category)}")
        if ticket_type is not None:
            lines.append(f"ticket_type={getattr(ticket_type, 'value', ticket_type)}")
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


def build_manual_triage_advice_payload(
    *,
    reason: str,
    lang: str = "en",
    source_label: str = "cross_check",
    next_checks: list[str] | None = None,
) -> dict[str, Any]:
    checks = [
        _normalize_line(item)
        for item in list(next_checks or [])
        if _normalize_line(item)
    ]
    if not checks:
        checks = (
            [
                "Confirmez d'abord si le ticket correspond a un incident actif ou a une demande de service planifiee.",
                "Ajoutez un signal technique ou un livrable attendu supplementaire avant de choisir le flux de resolution.",
            ]
            if lang == "fr"
            else [
                "Confirm first whether the ticket is a live incident or a planned service request.",
                "Add one more technical signal or explicit requested outcome before choosing the remediation path.",
            ]
        )
    confidence = 0.18
    confidence_text = confidence_band(confidence)
    return {
        "recommended_action": None,
        "reasoning": _normalize_line(reason),
        "probable_root_cause": None,
        "root_cause": None,
        "supporting_context": None,
        "why_this_matches": [],
        "evidence_sources": [],
        "tentative": False,
        "confidence": confidence,
        "confidence_band": confidence_text,
        "confidence_label": confidence_text,
        "source_label": source_label,
        "recommendation_mode": "insufficient_evidence",
        "mode": "manual_triage",
        "display_mode": "manual_triage",
        "match_summary": None,
        "next_best_actions": checks,
        "validation_steps": checks[:2],
        "base_recommended_action": None,
        "base_next_best_actions": [],
        "base_validation_steps": [],
        "action_refinement_source": "none",
        "fallback_action": None,
        "missing_information": [_normalize_line(reason)] if _normalize_line(reason) else [],
        "response_text": _normalize_line(reason),
    }


def candidate_tickets_for_ticket(ticket: Any, visible_tickets: list[Any], *, limit: int = 18) -> list[Any]:
    ticket_id = getattr(ticket, "id", None)
    ticket_category = getattr(ticket, "category", None)
    ticket_problem_id = getattr(ticket, "problem_id", None)
    ticket_type = getattr(ticket, "ticket_type", None)
    base_is_service_request = validate_ticket_routing_for_ticket(ticket).use_service_request_guidance
    base_profile = service_request_profile_from_ticket(ticket) if base_is_service_request else None
    if ticket_category is None and ticket_problem_id is None and ticket_type is None:
        return list(visible_tickets[:limit])

    scored: list[tuple[float, int, Any]] = []
    for index, row in enumerate(visible_tickets):
        if getattr(row, "id", None) == ticket_id:
            continue
        score = 0.0
        if ticket_problem_id and getattr(row, "problem_id", None) == ticket_problem_id:
            score += 8
        if ticket_type is not None and getattr(row, "ticket_type", None) == ticket_type:
            score += 6
        if ticket_category is not None and getattr(row, "category", None) == ticket_category:
            score += 4
        row_is_service_request = validate_ticket_routing_for_ticket(row).use_service_request_guidance
        if base_is_service_request and row_is_service_request:
            score += 3
            row_profile = service_request_profile_from_ticket(row)
            profile_similarity = service_request_profile_similarity(base_profile, row_profile)
            score += profile_similarity * 12.0
            if base_profile.family and row_profile.family and base_profile.family != row_profile.family:
                score -= 2.5
        elif base_is_service_request and not row_is_service_request:
            score -= 2
        scored.append((score, -index, row))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in scored[:limit]]


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
    if mode == "service_request":
        for item in next_best_actions:
            normalized = _normalize_line(item)
            if not normalized or normalized.casefold() == action.casefold():
                continue
            steps.append(normalized)
        if len(steps) < 2:
            steps.append(
                "Confirm the request owner and prerequisites before completion."
                if lang == "en"
                else "Confirmez le responsable de la demande et les prerequis avant la cloture."
            )
        return steps[:4]
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
    if mode == "service_request":
        return [
            "Confirm the planned task was completed on the expected schedule and documented on the ticket."
            if lang == "en"
            else "Confirmez que la tache planifiee a ete realisee a la cadence attendue et documentee sur le ticket.",
        ]
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
    if mode in {"evidence_action", "service_request"}:
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
    if mode == "service_request":
        if lang == "fr":
            lines.append(f"Guidage de demande de service: {recommended_action or fallback_action or 'Aucune action precise.'}")
        else:
            lines.append(f"Service request guidance: {recommended_action or fallback_action or 'No concrete action available.'}")
    elif mode == "evidence_action":
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
    base_recommended_action = _normalize_line(advice_payload.get("base_recommended_action")) or None
    explicit_base_next_best_actions = [
        _normalize_line(item)
        for item in list(advice_payload.get("base_next_best_actions") or [])
        if _normalize_line(item)
    ]
    base_next_best_actions = explicit_base_next_best_actions[:4]
    explicit_base_validation_steps = [
        _normalize_line(item)
        for item in list(advice_payload.get("base_validation_steps") or [])
        if _normalize_line(item)
    ]
    base_validation_steps = explicit_base_validation_steps[:3]
    action_refinement_source = _normalize_line(advice_payload.get("action_refinement_source")) or "none"
    if action_refinement_source == "none":
        if base_recommended_action is None:
            base_recommended_action = recommended_action
        if not base_next_best_actions:
            base_next_best_actions = list(next_best_actions)
        if not base_validation_steps:
            base_validation_steps = list(validation_steps)
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
    confidence_band_label = _normalize_line(advice_payload.get("confidence_band")) or confidence_band(confidence)
    response_text = _normalize_line(advice_payload.get("response_text")) or _build_response_text(
        mode=display_mode,
        recommended_action=recommended_action,
        reasoning=reasoning,
        evidence_sources=evidence_sources,
        validation_steps=validation_steps,
        fallback_action=fallback_action,
        missing_information=missing_information,
        confidence=confidence,
        confidence_band=confidence_band_label,
        lang=lang,
    )
    return AIResolutionAdvice(
        recommended_action=recommended_action,
        reasoning=reasoning,
        probable_root_cause=_normalize_line(advice_payload.get("probable_root_cause")) or None,
        root_cause=_normalize_line(advice_payload.get("root_cause")) or None,
        supporting_context=_normalize_line(advice_payload.get("supporting_context")) or None,
        why_this_matches=[
            _normalize_line(item)
            for item in list(advice_payload.get("why_this_matches") or [])
            if _normalize_line(item)
        ][:4],
        evidence_sources=evidence_sources,
        tentative=bool(advice_payload.get("tentative", False)),
        confidence=confidence,
        confidence_band=confidence_band_label,
        confidence_label=_normalize_line(advice_payload.get("confidence_label")) or confidence_band_label,
        source_label=_normalize_line(advice_payload.get("source_label")) or default_source_label,
        recommendation_mode=_normalize_line(advice_payload.get("recommendation_mode")) or "fallback_rules",
        action_relevance_score=_clamp_unit_confidence(float(advice_payload.get("action_relevance_score") or 0.0)),
        filtered_weak_match=bool(advice_payload.get("filtered_weak_match", False)),
        mode=_normalize_line(advice_payload.get("mode")) or display_mode,
        display_mode=display_mode,
        match_summary=_normalize_line(advice_payload.get("match_summary")) or None,
        next_best_actions=next_best_actions,
        base_recommended_action=base_recommended_action,
        base_next_best_actions=base_next_best_actions,
        base_validation_steps=base_validation_steps,
        action_refinement_source=action_refinement_source,
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
        llm_general_advisory=(
            AILLMGeneralAdvisory.model_validate(advice_payload.get("llm_general_advisory"))
            if isinstance(advice_payload.get("llm_general_advisory"), dict)
            else None
        ),
        knowledge_source=_normalize_line(advice_payload.get("knowledge_source")) or None,
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
        "base_recommended_action": advice.base_recommended_action,
        "base_next_best_actions": list(advice.base_next_best_actions),
        "base_validation_steps": list(advice.base_validation_steps),
        "action_refinement_source": advice.action_refinement_source,
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
        "llm_general_advisory": (
            advice.llm_general_advisory.model_dump(mode="json")
            if advice.llm_general_advisory is not None
            else None
        ),
        "knowledge_source": advice.knowledge_source,
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
        exclude_ids=[str(getattr(ticket, "id", "") or "").strip()],
    )
    retrieval = RetrievalResult.coerce(retrieval)
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
    retrieval = RetrievalResult.coerce(retrieval)
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
