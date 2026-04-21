"""Chat orchestration for ITSM assistant."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import ai_pipeline_duration_seconds
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType, UserRole
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.schemas.ai import (
    AIChatGrounding,
    AIChatStructuredResponse,
    AIChatTicketResults,
    AIDraftContext,
    AIRecommendationOut,
    AIResolutionAdvice,
    AISolutionRecommendation,
    AISuggestedKBArticle,
    AISuggestedProblem,
    AISuggestedTicket,
    AISuggestionBundle,
    ChatRequest,
    ChatResponse,
    ClassificationRequest,
    ClassificationResponse,
    GuidanceContract,
    GuidanceDisplayMode,
    RetrievalResult,
    SuggestRequest,
    SuggestResponse,
    TicketDraft,
)
from app.services.ai.calibration import (
    CHAT_KB_SEMANTIC_MIN_SCORE,
    DEFAULT_RESOLVER_TOP_K,
    GUIDANCE_CONFIDENCE_THRESHOLD,
    confidence_band,
)
from app.services.ai.analytics_queries import _answer_data_query, _extract_ticket_query_meta
from app.services.ai.chat_payloads import (
    build_assignment_recommendation_payload,
    build_cause_analysis_payload,
    build_insufficient_evidence_payload,
    build_problem_detail_payload,
    build_problem_linked_tickets_payload,
    build_problem_list_payload,
    build_recommendation_list_payload,
    build_resolution_advice_payload,
    build_service_request_response,
    build_similar_tickets_payload,
    build_ticket_list_payload,
    build_ticket_thread_payload,
    is_assignment_query,
)
from app.services.ai.chat_session import (
    build_chat_session,
    build_relevant_history_context,
    resolve_comparison_targets,
    resolve_contextual_reference,
    resolve_problem_contextual_reference,
)
from app.services.ai.classifier import (
    apply_category_guardrail,
    classify_ticket,
    classify_ticket_detailed,
    infer_ticket_type,
    score_recommendations,
    split_ticket_type_inference,
)
from app.services.ai.feedback import get_feedback_bundle_for_target
from app.services.ai.formatters import (
    _build_ticket_results_payload,
    _format_critical_tickets,
    _format_most_recent_ticket,
    _format_most_used_tickets,
    _format_recurring_solutions,
    _priority_label,
    _status_label,
    _format_weekly_summary,
    _ticket_to_summary,
)
from app.services.ai.conversation_policy import OFFTOPIC_REJECTION_MESSAGES
from app.services.ai.intents import (
    ACTIVE_STATUSES,
    ChatIntent,
    detect_intent_hybrid_details,
    detect_language,
    parse_chat_intent_details,
    extract_problem_id,
    extract_recent_ticket_constraints,
    extract_status_filter,
    extract_ticket_id,
    _is_explicit_ticket_create_request,
    _normalize_intent_text,
    _normalize_locale,
    _wants_active_only,
    _wants_open_only,
    detect_intent,
    is_guidance_request as _is_guidance_request,
    is_chitchat_or_offtopic as _is_chitchat_or_offtopic,
)
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_chat_grounded_prompt, build_chat_prompt
from app.services.ai.quickfix import append_solution
from app.services.ai.resolver import (
    ResolverOutput,
    build_ticket_retrieval_query,
    build_manual_triage_advice_payload,
    build_resolution_advice_model as _build_shared_resolution_advice_model,
    resolve_problem_advice,
    resolve_ticket_advice,
)
from app.services.ai.resolution_advisor import build_resolution_advice
from app.services.ai.routing_validation import validate_ticket_routing, validate_ticket_routing_for_ticket
from app.services.ai.retrieval import unified_retrieve
from app.services.ai.service_requests import (
    build_service_request_profile,
    build_service_request_guidance,
)
from app.services.embeddings import search_kb
from app.services.jira_kb import build_jira_knowledge_block
from app.services.problems import get_problem
from app.services.tickets import (
    compute_stats,
    get_critical_tickets_for_user,
    get_recent_ticket_for_user,
    get_tickets_by_category_for_user,
    list_tickets_for_user,
    select_best_assignee,
)
from app.services.users import list_assignees

logger = logging.getLogger(__name__)
_CHAT_TICKET_ID_RE = re.compile(r"\bTW-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
_CHAT_PROBLEM_ID_RE = re.compile(r"\bPB-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
_DETERMINISTIC_CHAT_RESPONSE_PLANS = {
    "forced_create_ticket",
    "shortcut_recent_ticket",
    "shortcut_most_used_tickets",
    "shortcut_weekly_summary",
    "shortcut_critical_tickets",
    "shortcut_recurring_solutions",
    "shortcut_problems",
    "shortcut_problem_detail",
    "shortcut_problem_linked_tickets",
    "shortcut_recommendations",
    "shortcut_ticket_thread",
    "shortcut_chitchat",
    "structured_data_query",
}


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return normalized.isoformat()
    return str(value).strip() or None


def _truncate_to(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 3].rstrip() + "..."


@dataclass(slots=True)
class RoutingPlan:
    name: str
    intent: ChatIntent
    use_llm: bool
    use_kb: bool
    constraints: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class ChatGuidanceContext:
    grounding: AIChatGrounding | None
    resolver_output: ResolverOutput | None
    authoritative: bool
    entity_type: str = "none"
    entity_id: str | None = None
    retrieval_mode: str = "fallback_rules"
    degraded: bool = False


def is_guidance_request(user_input: str) -> bool:
    return _is_guidance_request(user_input)


def build_routing_plan(
    question: str,
    *,
    intent: ChatIntent,
    create_requested: bool,
    guidance_requested: bool = False,
    entity_specific_ticket_query: bool = False,
    needs_structured_ticket_filter: bool = False,
    resolver_first_pattern: str | None = None,
) -> RoutingPlan:
    if create_requested or intent == ChatIntent.create_ticket:
        return RoutingPlan(
            name="forced_create_ticket",
            intent=ChatIntent.create_ticket,
            use_llm=True,
            use_kb=True,
            reason="explicit_create_request" if create_requested else "hybrid_create_intent",
        )

    if guidance_requested:
        return RoutingPlan(
            name="general_llm",
            intent=ChatIntent.general,
            use_llm=True,
            use_kb=True,
            reason="guidance_priority_override",
        )

    if intent == ChatIntent.recent_ticket:
        constraints = extract_recent_ticket_constraints(question)
        if constraints:
            return RoutingPlan(
                name="recent_ticket_filtered",
                intent=intent,
                use_llm=True,
                use_kb=True,
                constraints=constraints,
                reason="recent_ticket_with_constraints",
            )
        return RoutingPlan(
            name="shortcut_recent_ticket",
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason="plain_recent_ticket_no_constraints",
        )

    deterministic = {
        ChatIntent.most_used_tickets: "shortcut_most_used_tickets",
        ChatIntent.weekly_summary: "shortcut_weekly_summary",
        ChatIntent.critical_tickets: "shortcut_critical_tickets",
        ChatIntent.recurring_solutions: "shortcut_recurring_solutions",
        # New problem and recommendation shortcuts
        ChatIntent.problem_listing: "shortcut_problems",
        ChatIntent.problem_detail: "shortcut_problem_detail",
        ChatIntent.problem_drill_down: "shortcut_problem_linked_tickets",
        ChatIntent.recommendation_listing: "shortcut_recommendations",
        ChatIntent.ticket_thread: "shortcut_ticket_thread",
        ChatIntent.chitchat: "shortcut_chitchat",
    }
    if intent in deterministic:
        if intent == ChatIntent.critical_tickets and needs_structured_ticket_filter:
            return RoutingPlan(
                name="structured_data_query",
                intent=ChatIntent.data_query,
                use_llm=False,
                use_kb=False,
                reason="compound_ticket_filter_override",
            )
        return RoutingPlan(
            name=deterministic[intent],
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason=f"deterministic_{intent.value}",
        )

    if entity_specific_ticket_query and intent == ChatIntent.data_query:
        return RoutingPlan(
            name="structured_data_query",
            intent=ChatIntent.data_query,
            use_llm=False,
            use_kb=False,
            reason="entity_specific_ticket_override",
        )

    if intent == ChatIntent.data_query:
        if resolver_first_pattern in {"SIMILAR_TICKETS", "PROBLEM_ANALYSIS", "ASSIGNMENT_RECOMMENDATION"}:
            return RoutingPlan(
                name="general_llm",
                intent=ChatIntent.general,
                use_llm=True,
                use_kb=True,
                reason="resolver_first_pattern_override",
            )
        return RoutingPlan(
            name="structured_data_query",
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason="query_looks_structured",
        )

    return RoutingPlan(
        name="general_llm",
        intent=intent,
        use_llm=True,
        use_kb=True,
        reason="default_general_flow",
    )


def _retrieval_mode_from_source(source: str | None) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"fallback_rules", "kb_empty"}:
        return "fallback_rules"
    if normalized == "local_lexical":
        return "lexical_only"
    return "semantic"


def _is_degraded_retrieval(retrieval_mode: str) -> bool:
    return retrieval_mode in {"lexical_only", "fallback_rules"}


def _guidance_display_mode(value: Any, *, default: GuidanceDisplayMode = GuidanceDisplayMode.no_strong_match) -> GuidanceDisplayMode:
    return GuidanceDisplayMode.coerce(value, default=default)


def _guidance_fallback_mode(*, retrieval: RetrievalResult, base_mode: GuidanceDisplayMode) -> GuidanceDisplayMode:
    if base_mode == GuidanceDisplayMode.service_request:
        return GuidanceDisplayMode.service_request
    has_retrieval_evidence = bool(retrieval.similar_tickets or retrieval.kb_articles or retrieval.solution_recommendations)
    if has_retrieval_evidence and base_mode in {
        GuidanceDisplayMode.evidence_action,
        GuidanceDisplayMode.tentative_diagnostic,
    }:
        return GuidanceDisplayMode.needs_more_info
    return GuidanceDisplayMode.manual_triage


def _build_guidance_contract(resolver_output: ResolverOutput | None) -> tuple[RetrievalResult, GuidanceContract | None]:
    retrieval = RetrievalResult.coerce(getattr(resolver_output, "retrieval", None))
    if resolver_output is None:
        return retrieval, None
    if resolver_output.guidance_contract is not None and isinstance(resolver_output.retrieval, RetrievalResult):
        return resolver_output.retrieval, resolver_output.guidance_contract

    advice = resolver_output.advice
    retrieval_confidence = float(retrieval.confidence or 0.0)
    advisor_confidence = float(getattr(advice, "confidence", 0.0) or resolver_output.confidence or 0.0)
    base_mode = _guidance_display_mode(getattr(advice, "display_mode", None))
    if base_mode in {GuidanceDisplayMode.service_request, GuidanceDisplayMode.llm_general_knowledge}:
        unified_confidence = advisor_confidence if advisor_confidence > 0.0 else max(
            retrieval_confidence,
            GUIDANCE_CONFIDENCE_THRESHOLD,
        )
    elif base_mode in {GuidanceDisplayMode.evidence_action, GuidanceDisplayMode.tentative_diagnostic}:
        unified_confidence = retrieval_confidence if retrieval_confidence > 0.0 else advisor_confidence
    else:
        unified_confidence = advisor_confidence if advisor_confidence > 0.0 else retrieval_confidence
    effective_mode = base_mode
    downgraded = False
    downgrade_reason: str | None = None
    if base_mode not in {GuidanceDisplayMode.service_request, GuidanceDisplayMode.llm_general_knowledge} and unified_confidence < GUIDANCE_CONFIDENCE_THRESHOLD:
        effective_mode = _guidance_fallback_mode(retrieval=retrieval, base_mode=base_mode)
        downgraded = effective_mode != base_mode
        downgrade_reason = "below_confidence_threshold"

    evidence_allowed = (
        unified_confidence >= GUIDANCE_CONFIDENCE_THRESHOLD
        and effective_mode in {GuidanceDisplayMode.evidence_action, GuidanceDisplayMode.tentative_diagnostic}
    )
    contract = GuidanceContract(
        display_mode=effective_mode,
        confidence=round(unified_confidence, 4),
        advisor_confidence=round(advisor_confidence, 4),
        retrieval_confidence=round(retrieval_confidence, 4),
        threshold=GUIDANCE_CONFIDENCE_THRESHOLD,
        source=str(retrieval.source or "fallback_rules"),
        downgraded=downgraded,
        downgrade_reason=downgrade_reason,
        evidence_allowed=evidence_allowed,
    )
    resolver_output.retrieval = retrieval
    resolver_output.guidance_contract = contract
    resolver_output.confidence = contract.confidence

    if advice is not None:
        compat_mode = contract.legacy_display_mode
        contract_band = confidence_band(contract.confidence)
        resolver_output.advice = advice.model_copy(
            update={
                "confidence": contract.confidence,
                "confidence_band": contract_band,
                "confidence_label": contract_band,
                "display_mode": compat_mode,
                "mode": compat_mode,
                "recommended_action": None if contract.display_mode == GuidanceDisplayMode.manual_triage else advice.recommended_action,
            }
        )
        resolver_output.mode = resolver_output.advice.display_mode.value
    else:
        resolver_output.mode = contract.legacy_display_mode.value
    return retrieval, contract


def _supports_resolver_first_guidance(pattern: str, *, plan: RoutingPlan) -> bool:
    if plan.name in {
        "shortcut_recent_ticket",
        "shortcut_most_used_tickets",
        "shortcut_weekly_summary",
        "shortcut_critical_tickets",
        "shortcut_recurring_solutions",
        "shortcut_problems",
        "shortcut_problem_detail",
        "shortcut_problem_linked_tickets",
        "shortcut_recommendations",
        "shortcut_ticket_thread",
        "shortcut_chitchat",
        "structured_data_query",
        "forced_create_ticket",
    }:
        return False
    return pattern in {"HOW_TO_FIX", "PROBLEM_ANALYSIS", "SIMILAR_TICKETS", "ESCALATION_HELP", "CONFIRM_RESOLUTION"}


def _extract_chat_ticket_id(question: str) -> str | None:
    return extract_ticket_id(question)


def _extract_chat_problem_id(question: str) -> str | None:
    match = _CHAT_PROBLEM_ID_RE.search(str(question or ""))
    return match.group(0).upper() if match else None


def _find_ticket_by_id(tickets: list[Any], ticket_id: str | None) -> Any | None:
    if not ticket_id:
        return None
    wanted = str(ticket_id).strip().upper()
    for ticket in tickets:
        current = str(getattr(ticket, "id", "") or "").strip().upper()
        if current == wanted:
            return ticket
    return None


def _load_ticket_hint(
    db: Session,
    *,
    ticket_id: str | None,
    current_user: Any = None,
) -> Any | None:
    normalized_ticket_id = str(ticket_id or "").strip()
    if not normalized_ticket_id:
        return None

    if current_user is not None:
        try:
            visible_tickets = list_tickets_for_user(db, current_user)
        except Exception as exc:  # noqa: BLE001
            logger.info("Ticket hint lookup via visible tickets failed: %s", exc)
            visible_tickets = []
        ticket = _find_ticket_by_id(visible_tickets, normalized_ticket_id)
        return ticket

    query = getattr(db, "query", None)
    if not callable(query):
        return None
    try:
        return db.query(Ticket).filter(Ticket.id == normalized_ticket_id).first()
    except Exception as exc:  # noqa: BLE001
        logger.info("Ticket hint lookup via direct query failed: %s", exc)
        return None


def _single_line_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate_text(value: str, limit: int = 220) -> str:
    text = _single_line_text(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def _ticket_context_snippets(ticket: Any) -> dict[str, str]:
    if ticket is None:
        return {"summary_context": "", "comment_context": "", "resolution_context": ""}

    summary_context = _truncate_text(
        getattr(ticket, "ai_summary", None)
        or getattr(ticket, "summary", None)
        or "",
        limit=220,
    )
    resolution_context = _truncate_text(getattr(ticket, "resolution", None) or "", limit=220)

    comment_lines: list[str] = []
    comments = list(getattr(ticket, "comments", []) or [])
    for comment in comments[-3:]:
        content = _truncate_text(getattr(comment, "content", "") or "", limit=180)
        if not content:
            continue
        author = _single_line_text(getattr(comment, "author", "") or "")
        comment_lines.append(f"{author}: {content}" if author else content)
    comment_context = _truncate_text(" | ".join(comment_lines), limit=420)

    return {
        "summary_context": summary_context,
        "comment_context": comment_context,
        "resolution_context": resolution_context,
    }


def _extract_unique_ticket_ids(text: str) -> list[str]:
    matches = _CHAT_TICKET_ID_RE.findall(str(text or ""))
    unique: list[str] = []
    seen: set[str] = set()
    for match in matches:
        current = str(match or "").strip().upper()
        if not current or current in seen:
            continue
        seen.add(current)
        unique.append(current)
    return unique


def _find_last_referenced_ticket_id(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        message_text = getattr(message, "content", "")
        ticket_ids = _extract_unique_ticket_ids(message_text)
        if len(ticket_ids) == 1:
            return ticket_ids[0]
    return None


def resolve_ticket_context(text: str, session: Any) -> tuple[str | None, str]:
    explicit_ticket_id = extract_ticket_id(text)
    if explicit_ticket_id:
        return explicit_ticket_id, "explicit"
    chat_session = build_chat_session(session)
    return resolve_contextual_reference(text, chat_session)


def _is_multi_ticket_listing_request(text: str) -> bool:
    normalized = _normalize_intent_text(text)
    if any(
        token in normalized
        for token in [
            "all tickets",
            "show me all tickets",
            "list all tickets",
            "show all tickets",
            "tous les tickets",
            "liste des tickets",
            "montre tous les tickets",
        ]
    ):
        return True
    return "tickets" in normalized and any(token in normalized for token in ["list", "show", "affiche", "montre"])


def _is_entity_specific_ticket_query(text: str, ticket_id: str | None) -> bool:
    if not ticket_id:
        return False
    normalized = _normalize_intent_text(text)
    if is_guidance_request(normalized) or _is_explicit_ticket_create_request(normalized):
        return False
    if _is_multi_ticket_listing_request(normalized):
        return False
    if any(token in normalized for token in ["similar", "related", "linked", "compare", "versus", " vs "]):
        return False
    return any(
        token in normalized
        for token in [
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
            "resumer",
            "info",
            "information",
            "show me",
            "show ticket",
            "this ticket",
            "that ticket",
            "the ticket",
            "this issue",
            "that issue",
            "this incident",
            "that incident",
            "first one",
            "second one",
            "third one",
            "previous one",
            "other one",
        ]
    )


def _build_ticket_comparison_reply(current_ticket: Any, previous_ticket: Any, *, lang: str) -> str:
    current_id = str(getattr(current_ticket, "id", "") or "current")
    previous_id = str(getattr(previous_ticket, "id", "") or "previous")
    current_status = _status_label(str(getattr(getattr(current_ticket, "status", None), "value", getattr(current_ticket, "status", None)) or "unknown"), lang)
    previous_status = _status_label(str(getattr(getattr(previous_ticket, "status", None), "value", getattr(previous_ticket, "status", None)) or "unknown"), lang)
    current_priority = _priority_label(str(getattr(getattr(current_ticket, "priority", None), "value", getattr(current_ticket, "priority", None)) or "unknown"), lang)
    previous_priority = _priority_label(str(getattr(getattr(previous_ticket, "priority", None), "value", getattr(previous_ticket, "priority", None)) or "unknown"), lang)
    current_category = str(getattr(getattr(current_ticket, "category", None), "value", getattr(current_ticket, "category", None)) or "unknown")
    previous_category = str(getattr(getattr(previous_ticket, "category", None), "value", getattr(previous_ticket, "category", None)) or "unknown")
    current_assignee = str(getattr(current_ticket, "assignee", None) or ("Unassigned" if lang == "en" else "Non assigne"))
    previous_assignee = str(getattr(previous_ticket, "assignee", None) or ("Unassigned" if lang == "en" else "Non assigne"))

    same_category = current_category == previous_category
    if lang == "fr":
        lines = [
            f"Comparaison de tickets : {current_id} vs {previous_id}",
            f"- {current_id} | {current_priority} | {current_status} | {current_category} | {current_assignee}",
            f"- {previous_id} | {previous_priority} | {previous_status} | {previous_category} | {previous_assignee}",
            (
                f"- Point commun : les deux tickets restent dans la meme categorie ({current_category})."
                if same_category
                else f"- Difference principale : {current_id} est dans {current_category}, tandis que {previous_id} est dans {previous_category}."
            ),
        ]
    else:
        lines = [
            f"Ticket comparison: {current_id} vs {previous_id}",
            f"- {current_id} | {current_priority} | {current_status} | {current_category} | {current_assignee}",
            f"- {previous_id} | {previous_priority} | {previous_status} | {previous_category} | {previous_assignee}",
            (
                f"- Shared context: both tickets are in the same category ({current_category})."
                if same_category
                else f"- Main difference: {current_id} is in {current_category}, while {previous_id} is in {previous_category}."
            ),
        ]
    return "\n".join(lines)


def _build_chat_grounding(
    *,
    entity_type: str,
    entity_id: str | None,
    resolver_output: ResolverOutput | None,
) -> AIChatGrounding | None:
    if resolver_output is None:
        return None
    retrieval, guidance_contract = _build_guidance_contract(resolver_output)
    advice = resolver_output.advice
    retrieval_source = str(retrieval.get("source") or "fallback_rules")
    retrieval_mode = _retrieval_mode_from_source(retrieval_source)
    degraded = _is_degraded_retrieval(retrieval_mode)
    if advice is None:
        return AIChatGrounding(
            entity_type=entity_type,
            entity_id=entity_id,
            mode=guidance_contract.legacy_display_mode.value if guidance_contract is not None else "informational",
            confidence_band="low",
            retrieval_mode=retrieval_mode,
            degraded=degraded,
        )
    return AIChatGrounding(
        entity_type=entity_type,
        entity_id=entity_id,
        mode=advice.display_mode,
        confidence_band=advice.confidence_band,
        root_cause=advice.root_cause,
        recommended_action=advice.recommended_action,
        supporting_context=advice.supporting_context,
        why_this_matches=list(advice.why_this_matches),
        evidence_sources=list(advice.evidence_sources),
        validation_steps=list(advice.validation_steps),
        fallback_action=advice.fallback_action,
        next_best_actions=list(advice.next_best_actions),
        missing_information=list(advice.missing_information),
        retrieval_mode=retrieval_mode,
        degraded=degraded,
    )


def _resolver_output_from_classification_response(
    *,
    ticket: Any,
    classification: ClassificationResponse,
) -> ResolverOutput:
    retrieval_query = build_ticket_retrieval_query(ticket, include_priority=True)
    retrieval = RetrievalResult(
        query=retrieval_query,
        query_context={
            "metadata": {
                "ticket_id": str(getattr(ticket, "id", "") or "").strip() or None,
                "ticket_type": str(getattr(classification.ticket_type, "value", classification.ticket_type) or ""),
                "category": str(getattr(classification.category, "value", classification.category) or ""),
                "routing_decision_source": classification.routing_decision_source,
                "cross_check_conflict_flag": bool(classification.cross_check_conflict_flag),
                "service_request_profile_detected": bool(classification.service_request_profile_detected),
            }
        },
        source=str(classification.source_label or "fallback_rules"),
    )
    advice = classification.resolution_advice
    return ResolverOutput(
        mode=str(classification.display_mode or classification.mode or "no_strong_match"),
        retrieval_query=retrieval_query,
        retrieval=retrieval,
        advice=advice,
        recommended_action=classification.recommended_action,
        reasoning=classification.reasoning,
        match_summary=classification.match_summary,
        root_cause=classification.root_cause,
        supporting_context=classification.supporting_context,
        why_this_matches=list(classification.why_this_matches),
        evidence_sources=list(classification.evidence_sources),
        next_best_actions=list(classification.next_best_actions),
        workflow_steps=list(advice.workflow_steps) if advice is not None else [],
        validation_steps=list(classification.validation_steps),
        fallback_action=advice.fallback_action if advice is not None else None,
        confidence=(
            float(classification.guidance_contract.confidence)
            if classification.guidance_contract is not None
            else float(advice.confidence if advice is not None else classification.resolution_confidence or 0.0)
        ),
        missing_information=list(advice.missing_information) if advice is not None else [],
        guidance_contract=classification.guidance_contract,
    )


def _resolve_ticket_guidance_consistent_with_detail(
    *,
    db: Session,
    ticket: Any,
    current_user: Any,
    lang: str,
) -> ResolverOutput | None:
    try:
        classification = handle_classify(
            ClassificationRequest(
                title=str(getattr(ticket, "title", "") or ""),
                description=str(getattr(ticket, "description", "") or ""),
                ticket_id=str(getattr(ticket, "id", "") or "").strip() or None,
                locale=lang,
            ),
            db,
            current_user=current_user,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Ticket-specific chat guidance fallback to resolver path for %s: %s",
            str(getattr(ticket, "id", "") or "?"),
            exc,
        )
        return None
    return _resolver_output_from_classification_response(ticket=ticket, classification=classification)


def _time_greeting(lang: str) -> str:
    hour = dt.datetime.now().hour
    is_evening = hour >= 18 or hour < 5
    if lang == "fr":
        return "Bonsoir" if is_evening else "Bonjour"
    return "Good evening" if is_evening else "Good morning"


def _normalize_action(action: Any) -> str | None:
    if not isinstance(action, str):
        return None
    value = action.strip().lower()
    if value in {"create_ticket", "none"}:
        return value
    return None


def _solution_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip()).strip()
    return ""


def _safe_ticket_payload(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _fallback_reply_from_payload(data: dict[str, Any], *, lang: str, greeting: str) -> str:
    solution = _solution_text(data.get("solution"))
    if solution:
        return f"{greeting}, {solution}"

    ticket_payload = _safe_ticket_payload(data.get("ticket"))
    title = str((ticket_payload or {}).get("title") or "").strip()
    action = _normalize_action(data.get("action"))
    if action == "create_ticket":
        if lang == "fr":
            return f"{greeting}, brouillon de ticket prepare{': ' + title if title else '.'}"
        return f"{greeting}, ticket draft prepared{': ' + title if title else '.'}"
    if title:
        if lang == "fr":
            return f"{greeting}, voici le resultat analyse: {title}"
        return f"{greeting}, here is the analyzed result: {title}"

    return (
        f"{greeting}, je n'ai pas pu formuler une reponse claire, pouvez-vous reformuler ?"
        if lang == "fr"
        else f"{greeting}, I could not produce a clear answer. Could you rephrase?"
    )


def _build_chat_text_fallback_prompt(
    *,
    question: str,
    lang: str,
    greeting: str,
    knowledge_section: str,
    assignee_list: list[str],
    stats: dict,
) -> str:
    language_name = "French" if lang == "fr" else "English"
    return (
        "You are an ITSM assistant. Answer in plain text only (no JSON).\n"
        "Think step by step internally, then provide a concise actionable response.\n"
        "KNOWLEDGE-FIRST POLICY:\n"
        "- If Knowledge Section has Jira matches, base classification and troubleshooting on those matches first.\n"
        "- Every recommendation must be grounded in retrieved comments or Jira fields when matches exist.\n"
        "- If Knowledge Section is empty or insufficient, use basic IT troubleshooting knowledge.\n"
        "- Never invent Jira keys, incidents, fixes, or past actions.\n"
        f"Language: {language_name}\n"
        f"Greeting to start with: {greeting}\n"
        f"Available assignees: {assignee_list}\n"
        f"Stats: {stats}\n"
        f"{knowledge_section}"
        f"User question: {question}\n"
    )


_CHAT_RENDER_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "then",
    "into",
    "your",
    "vous",
    "avec",
    "pour",
    "dans",
    "les",
    "des",
    "une",
    "sur",
    "before",
    "after",
    "more",
    "plus",
    "avant",
    "apres",
    "ticket",
    "issue",
    "probleme",
}


def _normalize_chat_render_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").split())


def _truncate_chat_render_item(value: str, *, max_words: int) -> str:
    words = value.split()
    if len(words) <= max_words:
        return value
    return " ".join(words[:max_words]).rstrip(" ,;:") + "..."


def _chat_render_signature(value: str) -> str:
    normalized = _normalize_chat_render_text(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _chat_render_tokens(value: str) -> set[str]:
    return {
        token
        for token in _chat_render_signature(value).split()
        if len(token) > 2 and token not in _CHAT_RENDER_STOPWORDS
    }


def _is_redundant_chat_item(candidate: str, existing: list[str]) -> bool:
    candidate_sig = _chat_render_signature(candidate)
    if not candidate_sig:
        return True
    candidate_tokens = _chat_render_tokens(candidate)
    for item in existing:
        current_sig = _chat_render_signature(item)
        if not current_sig:
            continue
        if candidate_sig == current_sig or candidate_sig in current_sig or current_sig in candidate_sig:
            return True
        current_tokens = _chat_render_tokens(item)
        if not candidate_tokens or not current_tokens:
            continue
        overlap = candidate_tokens & current_tokens
        if len(overlap) >= 4:
            ratio = len(overlap) / max(1, min(len(candidate_tokens), len(current_tokens)))
            if ratio >= 0.72:
                return True
    return False


def _dedupe_chat_items(
    items: list[str],
    *,
    existing: list[str] | None = None,
    max_items: int,
    max_words: int = 24,
) -> list[str]:
    deduped: list[str] = []
    seen = list(existing or [])
    for raw in items:
        normalized = _normalize_chat_render_text(raw)
        if not normalized:
            continue
        shortened = _truncate_chat_render_item(normalized, max_words=max_words)
        if _is_redundant_chat_item(shortened, seen):
            continue
        deduped.append(shortened)
        seen.append(shortened)
        if len(deduped) >= max_items:
            break
    return deduped


def _coerce_formatter_items(value: Any, *, max_items: int = 2) -> list[str]:
    items: list[str] = []
    if isinstance(value, list):
        items = [_normalize_chat_render_text(item) for item in value]
    elif isinstance(value, str):
        normalized = _normalize_chat_render_text(value)
        if normalized:
            parts = [segment.strip() for segment in re.split(r"(?:\n+|[;•])", normalized) if segment.strip()]
            items = parts or [normalized]
    return _dedupe_chat_items(items, max_items=max_items, max_words=18)


def _chat_section_title(key: str, *, lang: str) -> str:
    if lang == "fr":
        titles = {
            "summary": "Summary",
            "action": "Recommended Action",
            "why": "Why this matches",
            "validation": "Validation",
            "next": "Next Steps",
            "confidence": "Confidence",
        }
        return titles[key]
    titles = {
        "summary": "Summary",
        "action": "Recommended Action",
        "why": "Why this matches",
        "validation": "Validation",
        "next": "Next Steps",
        "confidence": "Confidence",
    }
    return titles[key]


def _default_summary_items(grounding: AIChatGrounding, *, lang: str) -> list[str]:
    items: list[str] = []
    if grounding.mode == "service_request":
        items.append(
            "This is planned task guidance, not incident diagnosis."
            if lang == "en"
            else "Il s'agit d'un guidage de tache planifiee, pas d'un diagnostic d'incident."
        )
    elif grounding.mode == "tentative_diagnostic":
        items.append(
            "This is a tentative diagnostic, not a confirmed fix."
            if lang == "en"
            else "Il s'agit d'un diagnostic prudent, pas d'un correctif confirme."
        )
    elif grounding.mode == "no_strong_match":
        items.append(
            "No strong evidence-backed fix is confirmed yet."
            if lang == "en"
            else "Aucun correctif fortement etaye n'est confirme pour l'instant."
        )
    if grounding.root_cause:
        prefix = (
            "Likely root cause: "
            if grounding.mode == "evidence_action"
            else "Likely issue: "
        )
        if lang == "fr":
            prefix = "Cause probable : " if grounding.mode == "evidence_action" else "Hypothese principale : "
        items.append(f"{prefix}{grounding.root_cause}")
    if grounding.supporting_context:
        items.append(
            f"Supporting context: {grounding.supporting_context}"
            if lang == "en"
            else f"Contexte utile : {grounding.supporting_context}"
        )
    if not items:
        items.append(
            "Resolver-backed guidance is available for this request."
            if lang == "en"
            else "Une orientation issue du resolver est disponible pour cette demande."
        )
    return items


def _default_action_items(grounding: AIChatGrounding, *, lang: str) -> list[str]:
    if grounding.recommended_action:
        return [grounding.recommended_action]
    if grounding.fallback_action:
        return [grounding.fallback_action]
    if grounding.mode == "service_request":
        return [
            "Confirm prerequisites and execute the planned task using the documented workflow."
            if lang == "en"
            else "Confirmez les prerequis et executez la tache planifiee selon le workflow documente."
        ]
    if grounding.mode == "no_strong_match":
        return [
            "Collect one more verified signal before applying a broad change."
            if lang == "en"
            else "Collectez un signal verifie supplementaire avant d'appliquer un changement large."
        ]
    return [
        "Verify the current hypothesis before changing the system."
        if lang == "en"
        else "Verifiez d'abord l'hypothese courante avant de modifier le systeme."
    ]


def _default_why_items(grounding: AIChatGrounding, *, lang: str) -> list[str]:
    items = [_normalize_chat_render_text(item) for item in grounding.why_this_matches]
    if not items:
        for evidence in grounding.evidence_sources[:2]:
            if evidence.why_relevant:
                items.append(evidence.why_relevant)
            elif evidence.title:
                items.append(
                    f"Evidence {evidence.reference} matches the same component or symptom pattern."
                    if lang == "en"
                    else f"La preuve {evidence.reference} correspond au meme composant ou au meme symptome."
                )
    if not items:
        if grounding.mode == "evidence_action":
            items.append(
                "Resolver-selected evidence aligns on symptom, component, and prior resolution pattern."
                if lang == "en"
                else "Les preuves retenues par le resolver convergent sur le symptome, le composant et le schema de resolution."
            )
        elif grounding.mode == "tentative_diagnostic":
            items.append(
                "The evidence is only partially aligned, so this remains a diagnostic hypothesis."
                if lang == "en"
                else "Les preuves ne sont qu'en partie alignees, donc cela reste une hypothese de diagnostic."
            )
        else:
            items.append(
                "Current evidence is too weak or mismatched to confirm a safe fix."
                if lang == "en"
                else "Les preuves actuelles sont trop faibles ou trop divergentes pour confirmer un correctif sur."
            )
    return items


def _default_validation_items(grounding: AIChatGrounding, *, lang: str) -> list[str]:
    if grounding.validation_steps:
        return [_normalize_chat_render_text(item) for item in grounding.validation_steps]
    if grounding.mode == "service_request":
        return [
            "Confirm the task was completed and documented on the ticket."
            if lang == "en"
            else "Confirmez que la tache a ete realisee et documentee sur le ticket."
        ]
    if grounding.mode == "evidence_action":
        return [
            "Confirm the affected workflow works end to end after the change."
            if lang == "en"
            else "Confirmez que le flux affecte fonctionne de bout en bout apres le changement."
        ]
    if grounding.mode == "tentative_diagnostic":
        return [
            "Use the check results to confirm the hypothesis before applying a fix."
            if lang == "en"
            else "Utilisez le resultat des verifications pour confirmer l'hypothese avant d'appliquer un correctif."
        ]
    return [
        "Validate one additional verified signal before applying a broad change."
        if lang == "en"
        else "Validez un signal verifie supplementaire avant d'appliquer un changement large."
    ]


def _default_next_step_items(grounding: AIChatGrounding, *, lang: str) -> list[str]:
    items = [_normalize_chat_render_text(item) for item in grounding.next_best_actions]
    if not items and grounding.mode != "evidence_action" and grounding.fallback_action:
        items.append(grounding.fallback_action)
    if not items and grounding.missing_information:
        items.extend(_normalize_chat_render_text(item) for item in grounding.missing_information[:2])
    return items


def _default_confidence_note(grounding: AIChatGrounding, *, lang: str) -> str:
    degraded = grounding.retrieval_mode in {"lexical_only", "fallback_rules"}
    if grounding.mode == "service_request":
        return (
            "Runbook-guided - this request matches a planned fulfillment workflow."
            if lang == "en"
            else "Guide par runbook - cette demande correspond a un workflow planifie de fulfilment."
        )
    if grounding.confidence_band == "high":
        return (
            "High - evidence-backed recommendation supported by closely matching incidents."
            if lang == "en"
            else "High - recommandation etayee par des incidents tres proches."
        )
    if grounding.confidence_band == "medium":
        if degraded:
            return (
                "Medium - partial match with limited retrieval quality, so validate the checks before broader changes."
                if lang == "en"
                else "Medium - correspondance partielle avec une recuperation limitee, donc validez les verifications avant un changement plus large."
            )
        return (
            "Medium - partial match, so validate the checks before applying a broader change."
            if lang == "en"
            else "Medium - correspondance partielle, donc validez les verifications avant d'appliquer un changement plus large."
        )
    if degraded:
        return (
            "Low - limited matching evidence and degraded retrieval, so treat this as a diagnostic lead."
            if lang == "en"
            else "Low - preuves limitees et recuperation degradee, donc traitez ceci comme une piste de diagnostic."
        )
    return (
        "Low - limited matching evidence, so do not treat this as a confirmed fix."
        if lang == "en"
        else "Low - preuves limitees, donc ne traitez pas cela comme un correctif confirme."
    )


def _format_chat_section(title: str, items: list[str]) -> str:
    lines = [f"{title}:"]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _render_grounded_chat_reply(
    grounding: AIChatGrounding,
    *,
    lang: str,
    summary_items: list[str] | None = None,
    why_items: list[str] | None = None,
    confidence_note: str = "",
) -> str:
    resolver_summary = list(summary_items or []) + _default_summary_items(grounding, lang=lang)
    summary = _dedupe_chat_items(resolver_summary, max_items=2, max_words=22)

    action = _dedupe_chat_items(
        _default_action_items(grounding, lang=lang),
        existing=summary,
        max_items=3,
        max_words=24,
    )

    resolver_why = list(why_items or []) + _default_why_items(grounding, lang=lang)
    why = _dedupe_chat_items(
        resolver_why,
        existing=summary + action,
        max_items=3,
        max_words=20,
    )

    validation = _dedupe_chat_items(
        _default_validation_items(grounding, lang=lang),
        existing=summary + action + why,
        max_items=3,
        max_words=20,
    )

    next_steps = _dedupe_chat_items(
        _default_next_step_items(grounding, lang=lang),
        existing=summary + action + why + validation,
        max_items=3,
        max_words=20,
    )

    confidence = _normalize_chat_render_text(confidence_note) or _default_confidence_note(grounding, lang=lang)

    sections = [
        _format_chat_section(_chat_section_title("summary", lang=lang), summary),
        _format_chat_section(_chat_section_title("action", lang=lang), action),
        _format_chat_section(_chat_section_title("why", lang=lang), why),
        _format_chat_section(_chat_section_title("validation", lang=lang), validation),
    ]
    if next_steps:
        sections.append(_format_chat_section(_chat_section_title("next", lang=lang), next_steps))
    sections.append(f"{_chat_section_title('confidence', lang=lang)}:\n{confidence}")
    return "\n\n".join(section for section in sections if section).strip()


def _build_grounded_chat_reply(
    question: str,
    *,
    grounding: AIChatGrounding,
    lang: str,
    greeting: str,
) -> tuple[str, str | None, dict[str, Any] | None]:
    prompt = build_chat_grounded_prompt(
        question=question,
        grounding=grounding.model_dump(),
        lang=lang,
        greeting=greeting,
    )
    summary_items: list[str] = []
    why_items: list[str] = []
    confidence_note = ""
    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply) or {}
        summary_items = _coerce_formatter_items(data.get("summary"), max_items=2)
        why_items = _coerce_formatter_items(data.get("why_this_matches"), max_items=2)
        if not why_items:
            why_items = _coerce_formatter_items(data.get("evidence_summary"), max_items=2)
        confidence_note = _normalize_chat_render_text(data.get("confidence_note") or data.get("caution_note") or "")
    except Exception as exc:
        logger.info("Grounded chat formatter failed; using deterministic grounded reply: %s", exc)
    return _render_grounded_chat_reply(
        grounding,
        lang=lang,
        summary_items=summary_items,
        why_items=why_items,
        confidence_note=confidence_note,
    ), None, None


def build_chat_reply(
    question: str,
    stats: dict,
    top_tickets: list[str],
    *,
    lang: str | None = None,
    locale: str | None = None,
    assignees: list[str] | None = None,
    grounding: AIChatGrounding | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    resolved_lang = lang or _normalize_locale(locale)
    greeting = _time_greeting(resolved_lang)
    if grounding is not None:
        return _build_grounded_chat_reply(
            question,
            grounding=grounding,
            lang=resolved_lang,
            greeting=greeting,
        )
    assignee_list = assignees or []
    knowledge_block = build_jira_knowledge_block(
        question,
        lang=resolved_lang,
        limit=3,
        semantic_only=True,
        semantic_min_score=CHAT_KB_SEMANTIC_MIN_SCORE,
    )
    knowledge_section = f"{knowledge_block}\n\n" if knowledge_block else ""
    prompt = build_chat_prompt(
        question=question,
        knowledge_section=knowledge_section,
        lang=resolved_lang,
        greeting=greeting,
        assignee_list=assignee_list,
        stats=stats,
        top_tickets=top_tickets,
    )

    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if data:
            reply_text = str(data.get("reply", "") or "").strip()
            action = _normalize_action(data.get("action"))
            solution = _solution_text(data.get("solution"))
            notes = str(data.get("notes") or "").strip()
            ticket_payload = _safe_ticket_payload(data.get("ticket"))
            classification = data.get("classification")
            if isinstance(ticket_payload, dict) and isinstance(classification, dict):
                if not ticket_payload.get("priority") and isinstance(classification.get("priority"), str):
                    ticket_payload["priority"] = classification.get("priority")
                if not ticket_payload.get("ticket_type") and isinstance(classification.get("ticket_type"), str):
                    ticket_payload["ticket_type"] = classification.get("ticket_type")
                if not ticket_payload.get("category") and isinstance(classification.get("category"), str):
                    ticket_payload["category"] = classification.get("category")
            if not reply_text:
                reply_text = _fallback_reply_from_payload(data, lang=resolved_lang, greeting=greeting)
            if solution and action in {None, "none"} and solution.casefold() not in reply_text.casefold():
                reply_text = append_solution(reply_text, solution, lang=resolved_lang)
            if notes and notes.casefold() not in reply_text.casefold():
                reply_text = f"{reply_text}\n\n{notes}".strip()
            if not (reply_text or "").strip():
                reply_text = _fallback_reply_from_payload(data, lang=resolved_lang, greeting=greeting)
            return reply_text, action, ticket_payload

        raw_reply = str(reply or "").strip()
        should_retry_text = not raw_reply or raw_reply.startswith("{")
        if should_retry_text:
            try:
                raw_reply = ollama_generate(
                    _build_chat_text_fallback_prompt(
                        question=question,
                        lang=resolved_lang,
                        greeting=greeting,
                        knowledge_section=knowledge_section,
                        assignee_list=assignee_list,
                        stats=stats,
                    ),
                    json_mode=False,
                ).strip()
            except Exception as exc:
                logger.info("Ollama chat text fallback failed: %s", exc)
                raw_reply = str(reply or "").strip()

        if not raw_reply:
            raw_reply = (
                f"{greeting}, I could not produce a clear answer. Could you rephrase?"
                if resolved_lang == "en"
                else f"{greeting}, je n'ai pas pu formuler une reponse claire, pouvez-vous reformuler ?"
            )
        return raw_reply, None, None
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        error_reply = "LLM is unavailable. Please try again." if resolved_lang == "en" else "LLM indisponible. Reessayez."
        return error_reply, None, None


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
            "Return action=create_ticket with title, detailed description, priority, ticket_type, category, tags and assignee when possible.\n"
            f"User message: {question}"
        )
        if lang == "en"
        else (
            "Genere un brouillon complet de ticket ITSM a partir du message utilisateur. "
            "Retourne action=create_ticket avec titre, description detaillee, priorite, type, categorie, tags et assigne si possible.\n"
            f"Message utilisateur: {question}"
        )
    )
    _reply, _action, payload = build_chat_reply(
        force_prompt,
        stats,
        top,
        lang=lang,
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
        ticket_type = TicketType(data.get("ticket_type"))
        category = TicketCategory(data.get("category"))
        category = apply_category_guardrail(title, description, category)
    except Exception:
        priority, ticket_type, category, _ = classify_ticket(title, description)
    else:
        ticket_type, _ = split_ticket_type_inference(
            infer_ticket_type(title, description, category=category, current=ticket_type)
        )

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
        ticket_type=ticket_type,
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


def _created_at_sort_value(value: object) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _ticket_prompt_lines(tickets: list, *, limit: int = 40) -> list[str]:
    return [
        (
            f"{str(getattr(t, 'id', '') or '').strip() or 'unknown'} | "
            f"{str(getattr(t, 'title', '') or '').strip() or 'Untitled'} | "
            f"{getattr(getattr(t, 'priority', None), 'value', getattr(t, 'priority', None)) or 'unknown'} | "
            f"{getattr(getattr(t, 'status', None), 'value', getattr(t, 'status', None)) or 'unknown'} | "
            f"{getattr(getattr(t, 'category', None), 'value', getattr(t, 'category', None)) or 'unknown'} | "
            f"{str(getattr(t, 'assignee', '') or '').strip() or 'unassigned'}"
        )
        for t in tickets[:limit]
    ]


def _ticket_search_blob(ticket: Any) -> str:
    parts = [
        str(getattr(ticket, "id", "") or ""),
        str(getattr(ticket, "title", "") or ""),
        str(getattr(ticket, "description", "") or ""),
        str(getattr(ticket, "assignee", "") or ""),
        str(getattr(ticket, "reporter", "") or ""),
        str(getattr(ticket, "resolution", "") or ""),
    ]
    comments = getattr(ticket, "comments", None) or []
    for comment in comments:
        parts.append(str(getattr(comment, "author", "") or ""))
        parts.append(str(getattr(comment, "content", "") or ""))
    return _normalize_intent_text(" ".join(parts))


def _filter_recent_tickets_by_constraints(tickets: list, constraints: list[str]) -> list:
    if not constraints:
        return list(tickets)

    scored: list[tuple[int, dt.datetime, Any]] = []
    for ticket in tickets:
        searchable = _ticket_search_blob(ticket)
        if not searchable:
            continue
        score = sum(1 for constraint in constraints if constraint and constraint in searchable)
        if score <= 0:
            continue
        scored.append((score, _created_at_sort_value(getattr(ticket, "created_at", None)), ticket))

    scored.sort(key=lambda item: (item[0], item[1], str(getattr(item[2], "id", ""))), reverse=True)
    return [item[2] for item in scored]


def _recent_local_context(ticket: Any, *, lang: str) -> str:
    if ticket is None:
        return ""
    if lang == "fr":
        return (
            "Candidat local recent (a verifier avec contraintes): "
            f"{ticket.id} | {ticket.title} | {ticket.priority.value} | {ticket.status.value} | {ticket.category.value} | {ticket.assignee}"
        )
    return (
        "Recent local candidate (verify against constraints): "
        f"{ticket.id} | {ticket.title} | {ticket.priority.value} | {ticket.status.value} | {ticket.category.value} | {ticket.assignee}"
    )


def _build_ticket_draft_from_payload(
    *,
    ticket_payload: dict[str, Any],
    fallback_question: str,
    assignee_names: list[str],
    current_user,
) -> TicketDraft:
    title = str(ticket_payload.get("title") or fallback_question or "New ticket")
    description = str(ticket_payload.get("description") or fallback_question or title)
    try:
        priority = TicketPriority(ticket_payload.get("priority"))
        ticket_type = TicketType(ticket_payload.get("ticket_type"))
        category = TicketCategory(ticket_payload.get("category"))
        category = apply_category_guardrail(title, description, category)
    except Exception:
        priority, ticket_type, category, _ = classify_ticket(title, description)
    else:
        ticket_type, _ = split_ticket_type_inference(
            infer_ticket_type(title, description, category=category, current=ticket_type)
        )
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
    return TicketDraft(
        title=title,
        description=description,
        priority=priority,
        ticket_type=ticket_type,
        category=category,
        tags=tags,
        assignee=assignee,
    )


def _normalize_recommendation_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if text:
            items.append(text)
    return items


def _prefer_translated_list(original: list[str], candidate: list[str]) -> list[str]:
    if len(candidate) != len(original):
        return original
    return candidate


def _translate_recommendation_groups(
    groups: dict[str, list[str]],
    *,
    lang: str,
) -> dict[str, list[str]]:
    if lang not in {"en", "fr"}:
        return groups
    if not any(groups.values()):
        return groups

    target_language = "English" if lang == "en" else "French"
    prompt = (
        "You are a technical translator for IT support recommendations.\n"
        "Return ONLY valid JSON with this schema exactly:\n"
        "{\n"
        '  "recommendations": ["..."],\n'
        '  "recommendations_embedding": ["..."],\n'
        '  "recommendations_llm": ["..."]\n'
        "}\n"
        f"Translate all recommendation strings to {target_language}.\n"
        "Rules:\n"
        "- Keep each array length unchanged.\n"
        "- Keep item order unchanged.\n"
        "- Keep technical terms, product names and acronyms accurate.\n"
        "- Keep concise, actionable support style.\n"
        "- Do not add or remove recommendations.\n"
        f"Input JSON:\n{json.dumps(groups, ensure_ascii=True)}\n"
    )
    try:
        translated_raw = ollama_generate(prompt, json_mode=True)
        translated = extract_json(translated_raw) or {}
        translated_main = _normalize_recommendation_list(translated.get("recommendations"))
        translated_embedding = _normalize_recommendation_list(translated.get("recommendations_embedding"))
        translated_llm = _normalize_recommendation_list(translated.get("recommendations_llm"))
        return {
            "recommendations": _prefer_translated_list(groups["recommendations"], translated_main),
            "recommendations_embedding": _prefer_translated_list(groups["recommendations_embedding"], translated_embedding),
            "recommendations_llm": _prefer_translated_list(groups["recommendations_llm"], translated_llm),
        }
    except Exception as exc:
        logger.info("Recommendation translation skipped; using source language: %s", exc)
        return groups


def _build_resolution_advice_model(advice_payload: dict[str, Any] | None) -> AIResolutionAdvice | None:
    return _build_shared_resolution_advice_model(advice_payload)


def _truncate_sla_context(text: str, *, limit: int = 260) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _sla_advice_fallback(ticket: Ticket, *, lang: str) -> str:
    remaining = getattr(ticket, "sla_remaining_minutes", None)
    status = str(getattr(ticket, "sla_status", None) or "unknown").strip().lower()
    if lang == "fr":
        if status == "breached":
            return "SLA depassee: escalade immediate, communication au client, et plan d'action de resolution a court terme."
        if remaining is not None and remaining <= max(1, int(settings.SLA_AT_RISK_MINUTES)):
            return (
                "SLA a risque: prioriser la premiere action, confirmer le responsable, "
                "et limiter les changements non critiques jusqu'a stabilisation."
            )
        return "Conseil SLA indisponible: verifier la priorite, l'assignation, et la cadence de suivi."
    if status == "breached":
        return "SLA breached: escalate immediately, notify stakeholders, and execute a short-term recovery plan."
    if remaining is not None and remaining <= max(1, int(settings.SLA_AT_RISK_MINUTES)):
        return "SLA at risk: prioritize first action, confirm ownership, and pause non-critical changes."
    return "SLA advice unavailable: verify priority, ownership, and update cadence."


def _build_sla_advice_query(ticket: Ticket) -> str:
    category = getattr(ticket.category, "value", ticket.category) or "unknown"
    return (
        "SLA policy guidance for ITSM incident handling. "
        f"Category: {category}. "
        f"Title: {ticket.title}. "
        f"Description: {ticket.description}."
    )


def _collect_sla_kb_matches(db: Session, *, query: str, top_k: int) -> list[dict[str, Any]]:
    buckets = [
        search_kb(db, query, top_k=top_k, source_type="sla_policy"),
        search_kb(db, query, top_k=top_k, source_type="internal_sla"),
        search_kb(db, query, top_k=top_k),
    ]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rows in buckets:
        for row in rows:
            content_key = _truncate_sla_context(str(row.get("content") or ""), limit=180)
            source_key = str(row.get("source_type") or "kb")
            key = f"{source_key}|{content_key}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) >= top_k:
                return merged
    return merged


def _sla_context_block(matches: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, match in enumerate(matches, start=1):
        metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
        source_type = str(match.get("source_type") or "kb").strip() or "kb"
        jira_key = str(match.get("jira_key") or metadata.get("jira_key") or "").strip()
        source_label = f"{source_type}:{jira_key}" if jira_key else source_type
        score = float(match.get("score") or 0.0)
        content = _truncate_sla_context(str(match.get("content") or ""))
        lines.append(f"[{index}] source={source_label} score={score:.2f} text={content}")
    return "\n".join(lines)


def get_sla_advice(
    db: Session,
    *,
    ticket: Ticket,
    locale: str | None = None,
) -> dict[str, Any]:
    """Return grounded SLA advisory text generated from KB chunks."""
    lang = _normalize_locale(locale)
    top_k = max(1, min(int(settings.SLA_ADVISOR_RAG_TOP_K), 8))
    query = _build_sla_advice_query(ticket)
    matches = _collect_sla_kb_matches(db, query=query, top_k=top_k)
    if not matches:
        return {
            "advice_text": _sla_advice_fallback(ticket, lang=lang),
            "sources": [],
            "grounded": False,
            "confidence": 0.0,
        }

    context = _sla_context_block(matches)
    prompt = (
        "You are an ITSM SLA advisor.\n"
        "Use ONLY the retrieved context below.\n"
        "If context is insufficient, explicitly say insufficient_context.\n"
        "Do not add facts not present in context.\n"
        "Return JSON only with schema:\n"
        "{\n"
        '  "advice_text": "short actionable guidance",\n'
        '  "sources": ["source_label_1", "source_label_2"],\n'
        '  "grounded": true\n'
        "}\n\n"
        f"Context:\n{context}\n\n"
        f"Ticket title: {ticket.title}\n"
        f"Ticket description: {ticket.description}\n"
        f"Ticket status: {getattr(ticket.status, 'value', ticket.status)}\n"
        f"SLA status: {getattr(ticket, 'sla_status', 'unknown')}\n"
        f"SLA remaining minutes: {getattr(ticket, 'sla_remaining_minutes', None)}\n"
    )

    fallback = _sla_advice_fallback(ticket, lang=lang)
    try:
        raw = ollama_generate(prompt, json_mode=True)
        parsed = extract_json(raw) or {}
        advice_text = str(parsed.get("advice_text") or "").strip()
        if not advice_text:
            advice_text = fallback
        source_candidates = parsed.get("sources")
        if isinstance(source_candidates, list):
            sources = [str(item).strip() for item in source_candidates if str(item).strip()]
        else:
            sources = []
        if not sources:
            sources = [
                f"{str(match.get('source_type') or 'kb')}:{str(match.get('jira_key') or '').strip()}"
                if str(match.get("jira_key") or "").strip()
                else str(match.get("source_type") or "kb")
                for match in matches[:top_k]
            ]
        confidence_values = [float(match.get("score") or 0.0) for match in matches[:top_k]]
        avg_conf = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
        return {
            "advice_text": advice_text,
            "sources": sources[:top_k],
            "grounded": bool(parsed.get("grounded", True)),
            "confidence": avg_conf,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("SLA advisory fallback used for %s: %s", getattr(ticket, "id", "?"), exc)
        confidence_values = [float(match.get("score") or 0.0) for match in matches[:top_k]]
        avg_conf = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
        return {
            "advice_text": fallback,
            "sources": [
                str(match.get("source_type") or "kb")
                for match in matches[:top_k]
            ],
            "grounded": False,
            "confidence": avg_conf,
        }


def get_sla_strategies_advice(
    db: Session,
    *,
    tickets: list[Ticket],
    locale: str | None = None,
) -> dict[str, Any]:
    """Return governance-level SLA strategy advice using RAG + live ticket signals."""
    lang = _normalize_locale(locale)
    active_statuses = {
        TicketStatus.open,
        TicketStatus.in_progress,
        TicketStatus.waiting_for_customer,
        TicketStatus.waiting_for_support_vendor,
        TicketStatus.pending,
    }
    active_rows = [ticket for ticket in tickets if ticket.status in active_statuses]
    breached_rows = [ticket for ticket in active_rows if str(ticket.sla_status or "").strip().lower() == "breached"]
    at_risk_rows = [ticket for ticket in active_rows if str(ticket.sla_status or "").strip().lower() == "at_risk"]

    category_counts: dict[str, int] = {}
    for ticket in [*breached_rows, *at_risk_rows]:
        category = str(getattr(ticket.category, "value", ticket.category) or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
    top_categories = sorted(category_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    category_text = ", ".join([f"{name}:{count}" for name, count in top_categories]) or "none"

    query = (
        "ITIL 4 SLA governance practices for preventing breach and reducing first-response delays. "
        f"Observed categories: {category_text}. "
        f"Active count={len(active_rows)}, breached={len(breached_rows)}, at_risk={len(at_risk_rows)}."
    )
    top_k = max(1, min(int(settings.SLA_ADVISOR_RAG_TOP_K) + 1, 10))
    matches = _collect_sla_kb_matches(db, query=query, top_k=top_k)

    fallback_summary = (
        "Focus governance on ownership discipline, faster first response, and proactive at-risk monitoring."
        if lang == "en"
        else "Concentrez la gouvernance sur la discipline d'assignation, la premiere reponse rapide et le suivi proactif des tickets a risque."
    )
    fallback_patterns = [
        "Recurring delays before first technical action.",
        "Priority/category mismatch causing slow routing.",
        "Insufficient escalation before SLA breach.",
    ]
    fallback_improvements = [
        "Introduce 30-minute at-risk standups for active queue.",
        "Enforce assignee acknowledgment within first-response window.",
        "Run SLA dry-run checks before each shift handover.",
    ]

    if not matches:
        return {
            "summary": fallback_summary,
            "common_breach_patterns": fallback_patterns,
            "process_improvements": fallback_improvements,
            "confidence": 0.0,
            "sources": [],
        }

    context = _sla_context_block(matches)
    prompt = (
        "You are an ITSM governance advisor.\n"
        "Use ONLY retrieved context and observed metrics.\n"
        "Return JSON only:\n"
        "{\n"
        '  "summary": "short summary",\n'
        '  "common_breach_patterns": ["pattern 1", "pattern 2", "pattern 3"],\n'
        '  "process_improvements": ["improvement 1", "improvement 2", "improvement 3"]\n'
        "}\n\n"
        f"Observed metrics:\nactive={len(active_rows)}\nbreached={len(breached_rows)}\nat_risk={len(at_risk_rows)}\n"
        f"categories={category_text}\n\n"
        f"Context:\n{context}\n"
    )

    try:
        raw = ollama_generate(prompt, json_mode=True)
        parsed = extract_json(raw) or {}
        summary = str(parsed.get("summary") or "").strip() or fallback_summary
        patterns = [str(item).strip() for item in list(parsed.get("common_breach_patterns") or []) if str(item).strip()]
        improvements = [str(item).strip() for item in list(parsed.get("process_improvements") or []) if str(item).strip()]
        if not patterns:
            patterns = fallback_patterns
        if not improvements:
            improvements = fallback_improvements
        confidence_values = [float(match.get("score") or 0.0) for match in matches]
        avg_conf = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
        sources = [
            f"{str(match.get('source_type') or 'kb')}:{str(match.get('jira_key') or '').strip()}"
            if str(match.get("jira_key") or "").strip()
            else str(match.get("source_type") or "kb")
            for match in matches[:top_k]
        ]
        return {
            "summary": summary,
            "common_breach_patterns": patterns[:5],
            "process_improvements": improvements[:5],
            "confidence": avg_conf,
            "sources": sources,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("SLA strategy fallback used: %s", exc)
        confidence_values = [float(match.get("score") or 0.0) for match in matches]
        avg_conf = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
        return {
            "summary": fallback_summary,
            "common_breach_patterns": fallback_patterns,
            "process_improvements": fallback_improvements,
            "confidence": avg_conf,
            "sources": [str(match.get("source_type") or "kb") for match in matches[:top_k]],
        }


def handle_classify(payload: ClassificationRequest, db: Session, current_user=None) -> ClassificationResponse:
    with ai_pipeline_duration_seconds.labels(operation="classify").time():
        return _handle_classify_inner(payload, db, current_user)


def _handle_classify_inner(payload: ClassificationRequest, db: Session, current_user=None) -> ClassificationResponse:
    lang = _normalize_locale(payload.locale)
    details = classify_ticket_detailed(payload.title, payload.description, db=db, use_llm=False)
    stored_ticket = _load_ticket_hint(
        db,
        ticket_id=payload.ticket_id,
        current_user=current_user,
    )
    try:
        visible_tickets = list_tickets_for_user(db, current_user) if current_user is not None else []
    except Exception as exc:  # noqa: BLE001
        logger.info("Visible ticket scope lookup failed during classify: %s", exc)
        visible_tickets = []
    priority = details["priority"]
    stored_ticket_type = getattr(stored_ticket, "ticket_type", None)
    classifier_ticket_type = details.get("classifier_ticket_type") or details.get("ticket_type")
    profile = build_service_request_profile(payload.title, payload.description)
    routing_cross_check = validate_ticket_routing(
        title=payload.title,
        description=payload.description,
        classifier_details=details,
        stored_ticket_type=stored_ticket_type,
        profile=profile,
    )
    unresolved_routing = routing_cross_check.routing_decision_source == "cross_check_unresolved"
    ticket_type = None if unresolved_routing else (routing_cross_check.resolved_ticket_type or details["ticket_type"] or stored_ticket_type)
    unknown_ticket_type = details.get("unknown_ticket_type")
    category = details["category"]
    ticket_context = _ticket_context_snippets(stored_ticket)
    resolver_ticket = SimpleNamespace(
        id=str(payload.ticket_id or "").strip() or None,
        title=payload.title,
        description=payload.description,
        priority=priority,
        status=getattr(stored_ticket, "status", None),
        ticket_type=ticket_type,
        category=category,
        problem_id=getattr(stored_ticket, "problem_id", None),
        summary_context=ticket_context["summary_context"],
        comment_context=ticket_context["comment_context"],
        resolution_context=ticket_context["resolution_context"],
    )
    service_request_mode = routing_cross_check.use_service_request_guidance
    if service_request_mode:
        service_request_payload = build_service_request_guidance(
            resolver_ticket,
            lang=lang,
            enable_llm_refinement=True,
        )
        resolution_advice = _build_shared_resolution_advice_model(
            service_request_payload,
            default_source_label=str(service_request_payload.get("source_label") or "service_request"),
            lang=lang,
        )
        retrieval = RetrievalResult(
            query=f"{payload.title}\n{payload.description}",
            query_context={
                "metadata": {
                    "ticket_type": "service_request",
                    "category": str(getattr(category, "value", category) or ""),
                    "service_request_profile": service_request_payload.get("service_request_profile") or {},
                    "routing_decision_source": routing_cross_check.routing_decision_source,
                    "cross_check_conflict_flag": routing_cross_check.cross_check_conflict_flag,
                }
            },
            source="service_request",
        )
        guidance_contract = GuidanceContract(
            display_mode=GuidanceDisplayMode.service_request,
            confidence=round(float(service_request_payload.get("confidence") or 0.0), 4),
            advisor_confidence=round(float(service_request_payload.get("confidence") or 0.0), 4),
            retrieval_confidence=0.0,
            threshold=GUIDANCE_CONFIDENCE_THRESHOLD,
            source=str(service_request_payload.get("source_label") or "service_request"),
            downgraded=False,
            downgrade_reason=None,
            evidence_allowed=False,
        )
    elif unresolved_routing:
        manual_reason = (
            "Les signaux de routage restent en conflit entre incident et demande de service; un triage manuel est preferable avant de lancer une resolution guidee."
            if lang == "fr"
            else "Routing signals still conflict between incident and service request, so manual triage is safer before guided resolution."
        )
        manual_payload = build_manual_triage_advice_payload(
            reason=manual_reason,
            lang=lang,
            source_label="cross_check",
        )
        resolution_advice = _build_shared_resolution_advice_model(
            manual_payload,
            default_source_label="cross_check",
            lang=lang,
        )
        retrieval = RetrievalResult(
            query=f"{payload.title}\n{payload.description}",
            query_context={
                "metadata": {
                    "ticket_type": str(getattr(classifier_ticket_type, "value", classifier_ticket_type) or ""),
                    "category": str(getattr(category, "value", category) or ""),
                    "routing_decision_source": routing_cross_check.routing_decision_source,
                    "cross_check_conflict_flag": True,
                }
            },
            source="cross_check",
        )
        guidance_contract = GuidanceContract(
            display_mode=GuidanceDisplayMode.manual_triage,
            confidence=round(float(manual_payload.get("confidence") or 0.0), 4),
            advisor_confidence=round(float(manual_payload.get("confidence") or 0.0), 4),
            retrieval_confidence=0.0,
            threshold=GUIDANCE_CONFIDENCE_THRESHOLD,
            source="cross_check",
            downgraded=True,
            downgrade_reason="cross_check_unresolved",
            evidence_allowed=False,
        )
    else:
        resolver_output = resolve_ticket_advice(
            db,
            resolver_ticket,
            visible_tickets=visible_tickets,
            top_k=DEFAULT_RESOLVER_TOP_K,
            solution_quality="medium",
            include_workflow=True,
            include_priority=True,
            lang=lang,
            retrieval_fn=unified_retrieve,
            advice_builder=build_resolution_advice,
        )
        retrieval, guidance_contract = _build_guidance_contract(resolver_output)
        resolution_advice = resolver_output.advice
    raw_groups = {
        "recommendations": list(details.get("recommendations") or []),
        "recommendations_embedding": list(details.get("recommendations_embedding") or []),
        "recommendations_llm": list(details.get("recommendations_llm") or []),
    }
    translated_groups = raw_groups if resolution_advice is not None else _translate_recommendation_groups(raw_groups, lang=lang)
    classifier_recommendations = translated_groups["recommendations"]
    recommendations_embedding = translated_groups["recommendations_embedding"]
    recommendations_llm = translated_groups["recommendations_llm"]
    try:
        assignee = select_best_assignee(db, category=category, priority=priority)
    except Exception as exc:  # noqa: BLE001
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            try:
                rollback()
            except Exception:  # noqa: BLE001
                logger.debug("Classify rollback cleanup failed.", exc_info=True)
        logger.warning("Classify assignee suggestion unavailable: %s", exc)
        assignee = None
    if resolution_advice is not None:
        recommendations = [resolution_advice.recommended_action] if resolution_advice.recommended_action else []
        scored_out = (
            [
                AIRecommendationOut(
                    text=resolution_advice.recommended_action,
                    confidence=max(0, min(100, int(round(resolution_advice.confidence * 100)))),
                )
            ]
            if resolution_advice.recommended_action
            else []
        )
        recommendation_mode = resolution_advice.recommendation_mode
        source_label = resolution_advice.source_label
        resolution_confidence = guidance_contract.confidence if guidance_contract is not None else resolution_advice.confidence
        evidence_sources = resolution_advice.evidence_sources
        recommended_action = resolution_advice.recommended_action
        reasoning = resolution_advice.reasoning
        probable_root_cause = resolution_advice.probable_root_cause
        root_cause = resolution_advice.root_cause
        supporting_context = resolution_advice.supporting_context
        why_this_matches = list(resolution_advice.why_this_matches)
        tentative = resolution_advice.tentative
        confidence_band = resolution_advice.confidence_band
        confidence_label = resolution_advice.confidence_label
        action_relevance_score = resolution_advice.action_relevance_score
        filtered_weak_match = resolution_advice.filtered_weak_match
        mode = guidance_contract.legacy_display_mode.value if guidance_contract is not None else str(resolution_advice.mode or resolution_advice.display_mode)
        display_mode = guidance_contract.legacy_display_mode.value if guidance_contract is not None else resolution_advice.display_mode.value
        match_summary = resolution_advice.match_summary
        next_best_actions = list(resolution_advice.next_best_actions)
        validation_steps = list(resolution_advice.validation_steps)
        base_recommended_action = resolution_advice.base_recommended_action
        base_next_best_actions = list(resolution_advice.base_next_best_actions)
        base_validation_steps = list(resolution_advice.base_validation_steps)
        action_refinement_source = resolution_advice.action_refinement_source
        incident_cluster = resolution_advice.incident_cluster
        impact_summary = resolution_advice.impact_summary
    else:
        recommendations = classifier_recommendations
        recommendation_mode = "fallback_rules"
        source_label = str(retrieval.get("source") or "fallback_rules")
        resolution_confidence = 0.0
        evidence_sources = []
        recommended_action = None
        reasoning = None
        probable_root_cause = None
        root_cause = None
        supporting_context = None
        why_this_matches = []
        tentative = False
        confidence_band = "low"
        confidence_label = "low"
        action_relevance_score = 0.0
        filtered_weak_match = False
        display_mode = guidance_contract.legacy_display_mode.value if guidance_contract is not None else ("evidence_action" if recommendations else "no_strong_match")
        mode = display_mode
        match_summary = None
        next_best_actions = []
        validation_steps = []
        base_recommended_action = None
        base_next_best_actions = []
        base_validation_steps = []
        action_refinement_source = "none"
        incident_cluster = None
        impact_summary = None
    # Scale recommendation confidence by how certain the classifier was.
    # A ticket with weak classification signals produces lower-confidence cards.
    _cls_conf: int | None = details.get("classification_confidence")
    if resolution_advice is None and str(details.get("recommendation_mode") or "") in {"embedding", "hybrid"}:
        scored = score_recommendations(recommendations, start_confidence=90, rank_decay=6, floor=55, ceiling=97, classification_confidence=_cls_conf)
    elif resolution_advice is None:
        scored = score_recommendations(recommendations, start_confidence=84, rank_decay=8, floor=56, ceiling=92, classification_confidence=_cls_conf)
    if resolution_advice is None:
        scored_out = [AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored]
    scored_embedding = score_recommendations(recommendations_embedding, start_confidence=90, rank_decay=6, floor=55, ceiling=97, classification_confidence=_cls_conf)
    scored_llm = score_recommendations(recommendations_llm, start_confidence=82, rank_decay=8, floor=50, ceiling=93, classification_confidence=_cls_conf)
    feedback_bundle = {"current_feedback": None, "feedback_summary": None}
    ticket_id = str(payload.ticket_id or "").strip() or None
    current_user_id = getattr(current_user, "id", None)
    if ticket_id and current_user_id is not None:
        try:
            feedback_bundle = get_feedback_bundle_for_target(
                db,
                current_user_id=current_user_id,
                source_surface="ticket_detail",
                ticket_id=ticket_id,
            )
        except Exception as exc:  # noqa: BLE001
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                try:
                    rollback()
                except Exception:  # noqa: BLE001
                    logger.debug("Classify feedback rollback cleanup failed.", exc_info=True)
            logger.warning("Classify feedback state unavailable: %s", exc)
            feedback_bundle = {"current_feedback": None, "feedback_summary": None}
    return ClassificationResponse(
        priority=priority,
        ticket_type=ticket_type,
        classifier_ticket_type=classifier_ticket_type,
        manual_triage_required=(
            bool(details.get("manual_triage_required"))
            or bool(unknown_ticket_type)
            or routing_cross_check.routing_decision_source == "cross_check_unresolved"
        ),
        unknown_ticket_type=unknown_ticket_type,
        category=category,
        classification_confidence=int(details.get("classification_confidence") or 70),
        recommendations=recommendations,
        recommendations_scored=scored_out,
        recommendations_embedding=recommendations_embedding,
        recommendations_embedding_scored=[
            AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored_embedding
        ],
        recommendations_llm=recommendations_llm,
        recommendations_llm_scored=[
            AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored_llm
        ],
        recommendation_mode=recommendation_mode,
        similarity_found=bool(details.get("similarity_found")),
        assignee=assignee,
        source_label=source_label,
        resolution_confidence=resolution_confidence,
        resolution_advice=resolution_advice,
        recommended_action=recommended_action,
        reasoning=reasoning,
        evidence_sources=evidence_sources,
        probable_root_cause=probable_root_cause,
        root_cause=root_cause,
        supporting_context=supporting_context,
        why_this_matches=why_this_matches,
        tentative=tentative,
        confidence_band=confidence_band,
        confidence_label=confidence_label,
        action_relevance_score=action_relevance_score,
        filtered_weak_match=filtered_weak_match,
        mode=mode,
        display_mode=display_mode,
        guidance_contract=guidance_contract,
        match_summary=match_summary,
        next_best_actions=next_best_actions,
        validation_steps=validation_steps,
        base_recommended_action=base_recommended_action,
        base_next_best_actions=base_next_best_actions,
        base_validation_steps=base_validation_steps,
        action_refinement_source=action_refinement_source,
        routing_decision_source=routing_cross_check.routing_decision_source,
        service_request_profile_detected=routing_cross_check.service_request_profile_detected,
        service_request_profile_confidence=routing_cross_check.service_request_profile_confidence,
        cross_check_conflict_flag=routing_cross_check.cross_check_conflict_flag,
        cross_check_summary=routing_cross_check.cross_check_summary,
        incident_cluster=incident_cluster,
        impact_summary=impact_summary,
        current_feedback=feedback_bundle.get("current_feedback"),
        feedback_summary=feedback_bundle.get("feedback_summary"),
    )


def _requires_structured_ticket_filter_route(text: str, assignee_names: list[str]) -> bool:
    meta = _extract_ticket_query_meta(text, assignee_names)
    priorities = set(meta.get("priorities") or set())
    statuses = set(meta.get("statuses") or set())
    categories = set(meta.get("categories") or set())
    ticket_types = set(meta.get("ticket_types") or set())
    assignees = set(meta.get("assignees") or set())
    window_days = meta.get("window_days")

    extra_filters = bool(statuses or categories or ticket_types or assignees or window_days)
    if not extra_filters:
        return False

    # Preserve fast deterministic shortcuts for simple "critical tickets"
    # queries, but route compound filters like "critical incident tickets"
    # through the shared structured query engine so no constraint is lost.
    return priorities == {TicketPriority.critical} or bool(priorities)


def _detect_unified_pattern(question: str, *, plan: RoutingPlan, guidance_requested: bool = False) -> str:
    text = _normalize_intent_text(question)
    if any(token in text for token in ["thanks", "thank you", "that worked", "fixed", "resolved", "merci", "resolu", "marche"]):
        return "CONFIRM_RESOLUTION"
    if any(token in text for token in ["compare", "comparison", "versus", " vs ", "difference"]):
        return "PROBLEM_ANALYSIS"
    if any(token in text for token in ["similar", "related ticket", "ticket like", "semblable", "similaire"]):
        return "SIMILAR_TICKETS"
    # Priority analysis questions must be caught before PROBLEM_ANALYSIS — "analyse" alone is
    # too broad and would otherwise route priority questions into the resolver pipeline.
    _has_priority_token = any(token in text for token in [
        "priorit", "priority", "urgenc", "urgency", "severit", "severite",
    ])
    _has_recommend_token = any(token in text for token in [
        "recommand", "recommend", "correcte", "correct", "appropriate",
        "appropriee", "should be", "devrait", "evaluer", "evaluate",
        "classifier", "classify", "quelle priorite", "what priority",
    ])
    if _has_priority_token and (_has_recommend_token or "analyse" in text or "analysis" in text):
        return "PRIORITY_ANALYSIS"
    if any(
        token in text
        for token in [
            "root cause",
            "pattern",
            "cause",
            "why",
            "pourquoi",
            "why did this happen",
            "why does this happen",
            "why is this happening",
            "what caused this",
        ]
    ):
        return "PROBLEM_ANALYSIS"
    if guidance_requested or is_guidance_request(text):
        return "HOW_TO_FIX"
    # Generic "analyse/analysis" without priority or root-cause context → let LLM handle it.
    if any(token in text for token in ["analyse", "analysis", "analyser"]):
        return "GENERAL_ITSM"
    if any(token in text for token in ["status", "statut", "etat", "detail", "details", "summary", "resume", "info", "information"]):
        return "STATUS_UPDATE"
    if any(token in text for token in ["escalat", "urgent help", "need escalation", "escalade"]):
        return "ESCALATION_HELP"
    if plan.intent == ChatIntent.create_ticket or _is_explicit_ticket_create_request(question):
        return "TICKET_CREATE"
    if any(token in text for token in ["fix", "resolve", "solution", "cannot", "can't", "unable", "error", "issue", "panne"]):
        return "HOW_TO_FIX"
    if plan.intent == ChatIntent.data_query or any(token in text for token in ["trend", "kpi", "count", "critical network", "analytics", "stats"]):
        return "ANALYTICS"
    return "GENERAL_ITSM"


def _build_chat_resolver_ticket(question: str, *, conversation_state: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id="chat-context",
        title=" ".join(str(question or "").strip().split()),
        description="",
        priority=None,
        status=None,
        category=None,
        problem_id=None,
        conversation_state=conversation_state,
    )


def resolve_chat_guidance(
    *,
    question: str,
    lang: str,
    plan: RoutingPlan,
    db: Session,
    tickets: list[Any],
    conversation_state: Any,
    current_user: Any = None,
    solution_quality: str,
    guidance_requested: bool = False,
    resolved_ticket_id: str | None = None,
) -> ChatGuidanceContext:
    pattern = _detect_unified_pattern(question, plan=plan, guidance_requested=guidance_requested)
    if not _supports_resolver_first_guidance(pattern, plan=plan):
        return ChatGuidanceContext(
            grounding=None,
            resolver_output=None,
            authoritative=False,
        )

    session_state = build_chat_session(conversation_state)
    problem_id = _extract_chat_problem_id(question)
    if not problem_id:
        problem_id, _ = resolve_problem_contextual_reference(question, session_state)
    if problem_id and db is not None:
        try:
            problem = get_problem(db, problem_id)
        except Exception as exc:  # noqa: BLE001
            logger.info("Problem lookup failed during chat guidance resolution: %s", exc)
            problem = None
        if problem is not None:
            linked_tickets = [ticket for ticket in tickets if str(getattr(ticket, "problem_id", "") or "").strip() == problem.id]
            resolver_output = resolve_problem_advice(
                db,
                problem,
                linked_tickets=linked_tickets,
                user_question=question,
                conversation_state=conversation_state,
                top_k=DEFAULT_RESOLVER_TOP_K,
                solution_quality=solution_quality,
                include_workflow=True,
                lang=lang,
                retrieval_fn=unified_retrieve,
                advice_builder=build_resolution_advice,
            )
            grounding = _build_chat_grounding(
                entity_type="problem",
                entity_id=problem.id,
                resolver_output=resolver_output,
            )
            return ChatGuidanceContext(
                grounding=grounding,
                resolver_output=resolver_output,
                authoritative=True,
                entity_type="problem",
                entity_id=problem.id,
                retrieval_mode=grounding.retrieval_mode if grounding else "fallback_rules",
                degraded=bool(grounding.degraded) if grounding else True,
            )

    ticket_id = _extract_chat_ticket_id(question) or (str(resolved_ticket_id).strip().upper() if resolved_ticket_id else None)
    referenced_ticket = _find_ticket_by_id(tickets, ticket_id)

    if referenced_ticket is not None:
        if db is not None:
            classification_resolver_output = _resolve_ticket_guidance_consistent_with_detail(
                db=db,
                ticket=referenced_ticket,
                current_user=current_user,
                lang=lang,
            )
            if classification_resolver_output is not None:
                grounding = _build_chat_grounding(
                    entity_type="ticket",
                    entity_id=str(getattr(referenced_ticket, "id", "") or None),
                    resolver_output=classification_resolver_output,
                )
                return ChatGuidanceContext(
                    grounding=grounding,
                    resolver_output=classification_resolver_output,
                    authoritative=True,
                    entity_type="ticket",
                    entity_id=str(getattr(referenced_ticket, "id", "") or None),
                    retrieval_mode=grounding.retrieval_mode if grounding else "fallback_rules",
                    degraded=bool(grounding.degraded) if grounding else True,
                )

        if validate_ticket_routing_for_ticket(referenced_ticket).use_service_request_guidance:
            _sr_payload = build_service_request_response(referenced_ticket, lang=lang)
            return ChatGuidanceContext(
                grounding=None,
                resolver_output=None,
                authoritative=False,
                entity_type="ticket",
                entity_id=str(getattr(referenced_ticket, "id", "") or None),
                retrieval_mode="service_request",
                degraded=False,
            )

        resolver_output = resolve_ticket_advice(
            db,
            referenced_ticket,
            user_question=question,
            conversation_state=conversation_state,
            visible_tickets=tickets,
            top_k=DEFAULT_RESOLVER_TOP_K,
            solution_quality=solution_quality,
            include_workflow=True,
            include_priority=True,
            lang=lang,
            retrieval_fn=unified_retrieve,
            advice_builder=build_resolution_advice,
        )
        grounding = _build_chat_grounding(
            entity_type="ticket",
            entity_id=str(getattr(referenced_ticket, "id", "") or None),
            resolver_output=resolver_output,
        )
        return ChatGuidanceContext(
            grounding=grounding,
            resolver_output=resolver_output,
            authoritative=True,
            entity_type="ticket",
            entity_id=str(getattr(referenced_ticket, "id", "") or None),
            retrieval_mode=grounding.retrieval_mode if grounding else "fallback_rules",
            degraded=bool(grounding.degraded) if grounding else True,
        )

    resolver_output = resolve_ticket_advice(
        db,
        _build_chat_resolver_ticket(question, conversation_state=conversation_state),
        user_question=question,
        conversation_state=conversation_state,
        visible_tickets=tickets,
        top_k=DEFAULT_RESOLVER_TOP_K,
        solution_quality=solution_quality,
        include_workflow=True,
        include_priority=False,
        lang=lang,
        retrieval_fn=unified_retrieve,
        advice_builder=build_resolution_advice,
    )
    grounding = _build_chat_grounding(
        entity_type="ticket",
        entity_id=None,
        resolver_output=resolver_output,
    )
    return ChatGuidanceContext(
        grounding=grounding,
        resolver_output=resolver_output,
        authoritative=True,
        entity_type="ticket",
        entity_id=None,
        retrieval_mode=grounding.retrieval_mode if grounding else "fallback_rules",
        degraded=bool(grounding.degraded) if grounding else True,
    )


def _render_resolver_first_chat_reply(
    resolver_output: ResolverOutput,
    *,
    lang: str,
) -> str:
    advice = resolver_output.advice
    if advice is None:
        return (
            "I could not build an evidence-backed recommendation for this request yet."
            if lang == "en"
            else "Je n'ai pas encore pu construire une recommandation etayee pour cette demande."
        )
    lines: list[str] = []
    if advice.display_mode == "service_request":
        lines.append(
            f"Service request guidance: {advice.recommended_action}"
            if lang == "en"
            else f"Guidage de demande de service : {advice.recommended_action}"
        )
    elif advice.display_mode == "evidence_action":
        lines.append(
            f"Recommended action: {advice.recommended_action}"
            if lang == "en"
            else f"Action recommandee : {advice.recommended_action}"
        )
    elif advice.display_mode == "tentative_diagnostic":
        lines.append(
            f"Tentative diagnostic: {advice.recommended_action or advice.fallback_action}"
            if lang == "en"
            else f"Diagnostic prudent : {advice.recommended_action or advice.fallback_action}"
        )
    else:
        lines.append(
            "There is no strong evidence-backed resolution yet."
            if lang == "en"
            else "Il n'y a pas encore de resolution fortement etayee."
        )
        if advice.fallback_action:
            lines.append(
                f"Most useful next check: {advice.fallback_action}"
                if lang == "en"
                else f"Verification la plus utile : {advice.fallback_action}"
            )
    if advice.reasoning:
        lines.append(f"{'Reasoning' if lang == 'en' else 'Justification'}: {advice.reasoning}")
    if advice.evidence_sources:
        references = ", ".join(item.reference for item in advice.evidence_sources[:3] if item.reference)
        if references:
            lines.append(f"{'Evidence' if lang == 'en' else 'Preuves'}: {references}")
    validation_or_next = advice.validation_steps or advice.next_best_actions
    if validation_or_next:
        label = "Validation" if advice.display_mode == "evidence_action" else ("Next checks" if lang == "en" else "Prochaines verifications")
        if lang == "fr" and advice.display_mode == "evidence_action":
            label = "Validation"
        lines.append(f"{label}: {'; '.join(validation_or_next[:2])}")
    if advice.missing_information and advice.display_mode != "evidence_action":
        lines.append(
            f"{'Missing information' if lang == 'en' else 'Informations manquantes'}: {'; '.join(advice.missing_information[:2])}"
        )
    lines.append(
        f"{'Confidence' if lang == 'en' else 'Confiance'}: {int(round(advice.confidence * 100))}% ({advice.confidence_band})"
    )
    return "\n".join(line for line in lines if line).strip()


def _build_suggestion_bundle(resolver_output: ResolverOutput, *, lang: str) -> AISuggestionBundle:
    retrieval, guidance_contract = _build_guidance_contract(resolver_output)
    confidence = float(guidance_contract.confidence if guidance_contract is not None else retrieval.get("confidence") or 0.0)
    source = str(guidance_contract.source if guidance_contract is not None else retrieval.get("source") or "fallback_rules")
    if guidance_contract is not None and not guidance_contract.evidence_allowed:
        return AISuggestionBundle(
            confidence=confidence,
            source=source,
            resolution_advice=resolver_output.advice,
            guidance_contract=guidance_contract,
        )

    tickets = [
        AISuggestedTicket(
            id=str(item.get("id") or ""),
            title=str(item.get("title") or "Ticket"),
            similarity_score=float(item.get("similarity_score") or 0.0),
            status=str(item.get("status") or "unknown"),
            resolution_snippet=str(item.get("resolution_snippet") or "").strip() or None,
        )
        for item in list(retrieval.get("similar_tickets") or [])[:3]
        if str(item.get("id") or "").strip()
    ]
    problems = [
        AISuggestedProblem(
            id=str(item.get("id") or ""),
            title=str(item.get("title") or "Problem"),
            match_reason=str(item.get("match_reason") or "Pattern match"),
            root_cause=str(item.get("root_cause") or "").strip() or None,
            affected_tickets=int(item.get("affected_tickets") or 0) or None,
        )
        for item in list(retrieval.get("related_problems") or [])[:3]
        if str(item.get("id") or "").strip()
    ]
    kb_articles = [
        AISuggestedKBArticle(
            id=str(item.get("id") or f"kb-{idx}"),
            title=str(item.get("title") or "Knowledge Article"),
            excerpt=str(item.get("excerpt") or "").strip(),
            similarity_score=float(item.get("similarity_score") or 0.0),
            source_type=str(item.get("source_type") or "kb"),
        )
        for idx, item in enumerate(list(retrieval.get("kb_articles") or [])[:3], start=1)
        if str(item.get("excerpt") or "").strip()
    ]
    solution_recommendations = [
        AISolutionRecommendation(
            text=str(item.get("text") or "").strip(),
            source=str(item.get("source") or "unknown"),
            source_id=str(item.get("source_id") or "").strip() or None,
            evidence_snippet=str(item.get("evidence_snippet") or "").strip() or None,
            quality_score=float(item.get("quality_score") or 0.0),
            confidence=float(item.get("confidence") or 0.0),
            reason=str(item.get("reason") or "").strip() or None,
        )
        for item in list(retrieval.get("solution_recommendations") or [])[:3]
        if str(item.get("text") or "").strip()
    ]
    return AISuggestionBundle(
        tickets=tickets,
        problems=problems,
        kb_articles=kb_articles,
        solution_recommendations=solution_recommendations,
        resolution_advice=resolver_output.advice,
        guidance_contract=guidance_contract,
        confidence=confidence,
        source=source,
    )


def _suggestion_actions(pattern: str, bundle: AISuggestionBundle, *, base_action: str | None) -> list[str]:
    actions: list[str] = []
    if base_action and base_action != "none":
        actions.append(base_action)
    if bundle.tickets:
        actions.extend(["apply_solution", "view_ticket"])
    if bundle.problems:
        actions.append("view_problem")
    if pattern in {"STATUS_UPDATE", "ESCALATION_HELP"}:
        actions.append("escalate")
    if pattern == "CONFIRM_RESOLUTION":
        actions.extend(["close_ticket", "add_to_kb"])
    if pattern == "TICKET_CREATE":
        actions.append("create_ticket")
    if pattern == "GENERAL_ITSM":
        actions.append("create_ticket")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in actions:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _augment_reply_with_hints(reply: str, *, pattern: str, bundle: AISuggestionBundle, lang: str) -> str:
    text = (reply or "").strip()
    if bundle.confidence < GUIDANCE_CONFIDENCE_THRESHOLD:
        fallback = (
            "\n\nNeed more specific help? Try: create ticket / show mine."
            if lang == "en"
            else "\n\nBesoin d'aide plus precise ? Essayez : creer un ticket / afficher mes tickets."
        )
        return (text + fallback).strip()

    ticket_ids = [item.id for item in bundle.tickets[:3]]
    if pattern in {"HOW_TO_FIX", "SIMILAR_TICKETS"} and ticket_ids:
        suffix = (
            f"\n\nRelated solved tickets: {', '.join(ticket_ids)}."
            if lang == "en"
            else f"\n\nTickets resolus similaires : {', '.join(ticket_ids)}."
        )
        return (text + suffix).strip()
    if pattern == "PROBLEM_ANALYSIS" and bundle.problems:
        problem = bundle.problems[0]
        suffix = (
            f"\n\nPattern match: {problem.id} ({problem.title})."
            if lang == "en"
            else f"\n\nPattern detecte : {problem.id} ({problem.title})."
        )
        return (text + suffix).strip()
    if pattern == "STATUS_UPDATE" and bundle.tickets:
        suffix = (
            "\n\nSimilar tickets were resolved quickly; monitor SLA risk."
            if lang == "en"
            else "\n\nDes tickets similaires ont ete resolus rapidement ; surveillez le risque SLA."
        )
        return (text + suffix).strip()
    if pattern == "CONFIRM_RESOLUTION":
        suffix = (
            "\n\nClose ticket and add to knowledge base?"
            if lang == "en"
            else "\n\nFermer le ticket et ajouter la solution a la base de connaissance ?"
        )
        return (text + suffix).strip()
    return text


def _merge_suggested_fix_into_description(description: str, *, suggestion: str, lang: str) -> str:
    current = (description or "").strip()
    snippet = (suggestion or "").strip()
    if not snippet:
        return current
    marker = "Suggested fix (from retrieval):" if lang == "en" else "Correctif suggere (depuis la base):"
    if marker.casefold() in current.casefold():
        return current
    suffix = f"\n\n{marker}\n{snippet}"
    return f"{current}{suffix}".strip()


def _build_draft_context(
    *,
    ticket: TicketDraft | None,
    bundle: AISuggestionBundle,
    lang: str,
) -> AIDraftContext | None:
    if ticket is None:
        return None
    preferred = ""
    if bundle.tickets:
        preferred = str(bundle.tickets[0].resolution_snippet or "").strip()
    if not preferred and bundle.kb_articles:
        preferred = str(bundle.kb_articles[0].excerpt or "").strip()

    prefilled = ticket.description
    if preferred and bundle.confidence >= GUIDANCE_CONFIDENCE_THRESHOLD:
        prefilled = _merge_suggested_fix_into_description(prefilled, suggestion=preferred, lang=lang)

    return AIDraftContext(
        pre_filled_description=prefilled,
        suggested_priority=ticket.priority.value if getattr(ticket, "priority", None) else None,
        related_tickets=[item.id for item in bundle.tickets[:3]],
        confidence=bundle.confidence,
    )


def _response_payload_anchor(response_payload: AIChatStructuredResponse | None) -> str | None:
    if response_payload is None:
        return None
    for field_name in ("ticket_id", "source_ticket_id"):
        value = getattr(response_payload, field_name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _call_llm_for_chitchat(message: str, history_context: str, *, lang: str) -> str:
    """Minimal LLM call for chitchat / off-topic messages.

    No retrieval, no KB, no embeddings. Just the last conversational turns
    and a brief ITSM-assistant system instruction.
    """
    lang_instruction = (
        "Réponds en français. Tu es un assistant ITSM concis. "
        "Tu peux répondre aux questions générales sur les technologies IT (protocoles, acronymes, outils) "
        "si elles sont posées dans un contexte de support informatique."
        if lang == "fr"
        else "Respond in English. You are a concise ITSM assistant. "
        "You may answer general IT questions (protocols, acronyms, tools) "
        "when asked in an IT support context."
    )
    history_block = f"\nConversation so far:\n{history_context}\n" if history_context and history_context.strip() else ""
    prompt = (
        f"{lang_instruction} Keep replies to 1-3 sentences."
        f"{history_block}\nUser: {message}\nAssistant:"
    )
    try:
        result = ollama_generate(prompt).strip()
        if not result:
            raise ValueError("empty_reply")
        return result
    except Exception:  # noqa: BLE001
        return "Bonjour ! Comment puis-je vous aider ?" if lang == "fr" else "Hello! How can I help you?"


def _compose_chat_response(
    *,
    question: str,
    lang: str,
    plan: RoutingPlan,
    db: Session,
    tickets: list,
    solution_quality: str,
    reply: str,
    action: str | None,
    ticket: TicketDraft | None,
    ticket_results: AIChatTicketResults | None = None,
    response_payload: AIChatStructuredResponse | None = None,
    conversation_state: Any = None,
    chat_guidance: ChatGuidanceContext | None = None,
    resolved_ticket_id: str | None = None,
    ticket_context_source: str = "none",
    allow_resolver_fallback: bool = True,
    request_started_at: float | None = None,
) -> ChatResponse:
    resolver_output = chat_guidance.resolver_output if chat_guidance is not None else None
    deterministic_response = not allow_resolver_fallback and resolver_output is None and chat_guidance is None
    if resolver_output is None and allow_resolver_fallback:
        try:
            resolver_output = resolve_ticket_advice(
                db,
                _build_chat_resolver_ticket(question, conversation_state=conversation_state),
                user_question=question,
                conversation_state=conversation_state,
                visible_tickets=tickets,
                top_k=DEFAULT_RESOLVER_TOP_K,
                solution_quality=solution_quality,
                include_workflow=True,
                include_priority=False,
                lang=lang,
                retrieval_fn=unified_retrieve,
                advice_builder=build_resolution_advice,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Chat resolver fallback used while composing response: %s", exc)
            resolver_output = ResolverOutput(
                mode="informational",
                retrieval_query=question,
                retrieval={
                    "query_context": {"query": question},
                    "similar_tickets": [],
                    "kb_articles": [],
                    "solution_recommendations": [],
                    "related_problems": [],
                    "confidence": 0.0,
                    "source": "fallback_rules",
                },
                advice=None,
                recommended_action=None,
                reasoning=None,
                match_summary=None,
            )
    bundle = _build_suggestion_bundle(resolver_output, lang=lang) if resolver_output is not None else AISuggestionBundle()
    pattern = _detect_unified_pattern(question, plan=plan)
    draft_context = _build_draft_context(ticket=ticket, bundle=bundle, lang=lang)
    if draft_context and ticket is not None:
        ticket.description = draft_context.pre_filled_description
    skip_hint_augmentation = plan.name in _DETERMINISTIC_CHAT_RESPONSE_PLANS or plan.name == "recent_ticket_filtered"
    referenced_ticket_id = (
        str(chat_guidance.entity_id).strip().upper()
        if chat_guidance is not None and chat_guidance.entity_type == "ticket" and chat_guidance.entity_id
        else (str(resolved_ticket_id).strip().upper() if resolved_ticket_id else None)
    )
    referenced_ticket = _find_ticket_by_id(tickets, referenced_ticket_id)
    if response_payload is None and chat_guidance is not None and chat_guidance.authoritative:
        if pattern == "SIMILAR_TICKETS":
            response_payload = build_similar_tickets_payload(
                source_ticket_id=referenced_ticket_id,
                source_ticket=referenced_ticket,
                visible_tickets=tickets,
                resolver_output=resolver_output,
                lang=lang,
            )
        elif is_assignment_query(question) and referenced_ticket is not None:
            recommended_assignee = select_best_assignee(
                db,
                category=getattr(referenced_ticket, "category", None),
                priority=getattr(referenced_ticket, "priority", None),
            )
            response_payload = build_assignment_recommendation_payload(
                ticket=referenced_ticket,
                recommended_assignee=recommended_assignee,
                lang=lang,
            )
        elif pattern == "PROBLEM_ANALYSIS":
            response_payload = build_cause_analysis_payload(
                ticket=referenced_ticket,
                resolver_output=resolver_output,
                lang=lang,
            )
        elif pattern in {"HOW_TO_FIX", "ESCALATION_HELP", "CONFIRM_RESOLUTION"}:
            response_payload = build_resolution_advice_payload(
                ticket=referenced_ticket,
                resolver_output=resolver_output,
                lang=lang,
            )
        elif resolver_output is not None and resolver_output.advice is None and pattern in {
            "HOW_TO_FIX", "PROBLEM_ANALYSIS", "ESCALATION_HELP", "SIMILAR_TICKETS",
        }:
            # Only show INSUFFICIENT EVIDENCE for patterns that expect resolver output.
            # GENERAL_ITSM, STATUS_UPDATE, PRIORITY_ANALYSIS, ANALYTICS and CONFIRM_RESOLUTION
            # use the LLM reply directly — no resolver evidence is expected for them.
            response_payload = build_insufficient_evidence_payload(
                resolver_output=resolver_output,
                ticket=referenced_ticket,
                lang=lang,
            )
    if chat_guidance is not None and chat_guidance.authoritative:
        reply_text = reply
    else:
        advice_reply = ""
        if pattern in {"HOW_TO_FIX", "PROBLEM_ANALYSIS", "SIMILAR_TICKETS"} and bundle.resolution_advice is not None:
            advice_reply = _render_resolver_first_chat_reply(resolver_output, lang=lang)
        if advice_reply:
            reply_text = advice_reply
        elif skip_hint_augmentation:
            reply_text = reply
        else:
            reply_text = _augment_reply_with_hints(reply, pattern=pattern, bundle=bundle, lang=lang)
    anchor = _response_payload_anchor(response_payload)
    if anchor and anchor.casefold() not in reply_text.casefold():
        reply_text = f"Ticket {anchor}\n\n{reply_text}".strip()
    actions = _suggestion_actions(pattern, bundle, base_action=action)
    retrieval_mode = (
        chat_guidance.retrieval_mode
        if chat_guidance is not None
        else "deterministic"
        if deterministic_response
        else _retrieval_mode_from_source(bundle.source)
    )
    degraded = chat_guidance.degraded if chat_guidance is not None else (False if deterministic_response else _is_degraded_retrieval(retrieval_mode))
    rag_grounding = bool(
        bundle.guidance_contract is not None
        and bundle.guidance_contract.evidence_allowed
        and retrieval_mode == "semantic"
        and bundle.source not in {"fallback_rules", "kb_empty"}
    )
    normalized_action = action if action and action != "none" else None
    logger.info(
        "AI formatter selected: formatter=%s entity_ticket_id=%s context_source=%s route=%s",
        getattr(response_payload, "type", "legacy_text"),
        referenced_ticket_id or "-",
        ticket_context_source,
        plan.name,
    )
    duration_ms = round((time.perf_counter() - request_started_at) * 1000, 2) if request_started_at is not None else None
    logger.info(
        "AI chat completed: route=%s payload_type=%s resolver_used=%s llm_enabled=%s deterministic=%s retrieval_mode=%s duration_ms=%s",
        plan.name,
        getattr(response_payload, "type", "legacy_text"),
        resolver_output is not None,
        plan.use_llm,
        deterministic_response,
        retrieval_mode,
        duration_ms if duration_ms is not None else "-",
    )
    # Guard: response_payload must carry a 'type' discriminator to satisfy the
    # pydantic union. Drop it silently if something non-conforming slipped through
    # (e.g. an AIChatTicketResults object that has no 'type' field).
    if response_payload is not None and not hasattr(response_payload, "type"):
        logger.warning(
            "response_payload dropped: missing 'type' discriminator (got %s)",
            type(response_payload).__name__,
        )
        response_payload = None
    return ChatResponse(
        reply=reply_text,
        message=reply_text,
        action=normalized_action,
        ticket=ticket,
        rag_grounding=rag_grounding,
        retrieval_mode=retrieval_mode,
        degraded=degraded,
        resolution_advice=bundle.resolution_advice,
        grounding=chat_guidance.grounding if chat_guidance is not None else None,
        suggestions=bundle,
        draft_context=draft_context,
        actions=actions,
        ticket_results=ticket_results,
        response_payload=response_payload,
    )


def handle_chat(payload: ChatRequest, db: Session, current_user) -> ChatResponse:
    with ai_pipeline_duration_seconds.labels(operation="chat").time():
        return _handle_chat_inner(payload, db, current_user)


def _handle_chat_inner(payload: ChatRequest, db: Session, current_user) -> ChatResponse:
    request_started_at = time.perf_counter()
    last_question = payload.messages[-1].content if payload.messages else ""
    _client_lang = _normalize_locale(payload.locale) if payload.locale else None
    lang = _client_lang or detect_language(last_question or "")
    lowered = _normalize_intent_text(last_question or "")
    history_session = build_chat_session(payload.messages[:-1])
    conversation_session = build_chat_session(payload.messages)
    resolved_ticket_id, ticket_context_source = resolve_ticket_context(last_question, history_session)
    compare_current_id, compare_previous_id = resolve_comparison_targets(last_question, history_session)
    history_context = build_relevant_history_context(history_session, question=last_question)
    entity_specific_ticket_query = _is_entity_specific_ticket_query(last_question, resolved_ticket_id)

    # ── Intent detection happens BEFORE loading all tickets ───────────────
    intent_details = parse_chat_intent_details(last_question or "")
    intent = intent_details.intent
    intent_confidence = intent_details.confidence
    intent_source = intent_details.source
    guidance_requested = intent_details.guidance_requested

    # ── Off-topic early exit ───────────────────────────────────────────────
    # No ticket load, no LLM call — instant polite rejection.
    if intent_details.filter_meta.get("offtopic_guard"):
        rejection = OFFTOPIC_REJECTION_MESSAGES.get(lang, OFFTOPIC_REJECTION_MESSAGES["en"])
        offtopic_plan = build_routing_plan(
            last_question, intent=ChatIntent.chitchat, create_requested=False,
            guidance_requested=False, entity_specific_ticket_query=False,
        )
        return _compose_chat_response(
            question=last_question, lang=lang, plan=offtopic_plan, db=db,
            tickets=[], solution_quality=payload.solution_quality,
            reply=rejection, action=None, ticket=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    # ── Shortcut intents: use targeted DB queries, skip full table scan ───
    _PURE_SHORTCUTS = {
        ChatIntent.recent_ticket,
        ChatIntent.critical_tickets,
        ChatIntent.most_used_tickets,
    }
    if intent in _PURE_SHORTCUTS and not guidance_requested and not entity_specific_ticket_query:
        if intent == ChatIntent.recent_ticket:
            open_only = _wants_open_only(lowered)
            recent = get_recent_ticket_for_user(db, current_user, open_only=open_only)
            reply = _format_most_recent_ticket(recent, lang, open_only=open_only)
            summary = _ticket_to_summary(recent, lang)
            plan = build_routing_plan(
                last_question, intent=intent, create_requested=False,
                guidance_requested=False, entity_specific_ticket_query=False,
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db,
                tickets=[], solution_quality=payload.solution_quality,
                reply=reply, action="show_ticket" if summary else None,
                ticket=summary, conversation_state=conversation_session,
                allow_resolver_fallback=False, request_started_at=request_started_at,
            )

        if intent == ChatIntent.critical_tickets:
            active_only = _wants_active_only(lowered)
            critical = get_critical_tickets_for_user(db, current_user, active_only=active_only)
            reply = _format_critical_tickets(critical, lang, active_only=active_only)
            summary = _ticket_to_summary(critical[0], lang) if critical else None
            ticket_results = (
                _build_ticket_results_payload(
                    critical, lang,
                    header="Critical tickets:" if lang == "en" else "Tickets critiques :",
                    kind="critical",
                )
                if critical else None
            )
            response_payload = build_ticket_list_payload(
                tickets=critical,
                lang=lang,
                list_kind="critical",
                title="Critical tickets" if lang == "en" else "Tickets critiques",
                scope=("Status: active" if lang == "en" else "Statut: actifs") if active_only else None,
                total_count=len(critical),
            )
            plan = build_routing_plan(
                last_question, intent=intent, create_requested=False,
                guidance_requested=False, entity_specific_ticket_query=False,
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db,
                tickets=critical, solution_quality=payload.solution_quality,
                reply=reply, action="show_ticket" if summary else None,
                ticket=summary, ticket_results=ticket_results,
                response_payload=response_payload,
                conversation_state=conversation_session,
                allow_resolver_fallback=False, request_started_at=request_started_at,
            )

        if intent == ChatIntent.most_used_tickets:
            category_tickets = get_tickets_by_category_for_user(db, current_user)
            reply = _format_most_used_tickets(category_tickets, lang)
            plan = build_routing_plan(
                last_question, intent=intent, create_requested=False,
                guidance_requested=False, entity_specific_ticket_query=False,
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db,
                tickets=[], solution_quality=payload.solution_quality,
                reply=reply, action=None, ticket=None,
                conversation_state=conversation_session,
                allow_resolver_fallback=False, request_started_at=request_started_at,
            )

    # ── Full ticket load for all other intents (RAG, LLM, weekly, etc.) ──
    tickets = list_tickets_for_user(db, current_user)
    tickets = sorted(
        tickets,
        key=lambda item: (_created_at_sort_value(getattr(item, "created_at", None)), str(getattr(item, "id", ""))),
        reverse=True,
    )
    stats = compute_stats(tickets)
    assignees = list_assignees(db)
    assignee_names = [u.name for u in assignees]
    create_requested = _is_explicit_ticket_create_request(last_question or "") or intent == ChatIntent.create_ticket
    provisional_plan = build_routing_plan(
        last_question,
        intent=intent,
        create_requested=create_requested,
    )
    provisional_pattern = _detect_unified_pattern(
        last_question,
        plan=provisional_plan,
        guidance_requested=guidance_requested,
    )
    plan = build_routing_plan(
        last_question,
        intent=intent,
        create_requested=create_requested,
        guidance_requested=guidance_requested,
        entity_specific_ticket_query=entity_specific_ticket_query,
        needs_structured_ticket_filter=(
            provisional_plan.name == "shortcut_critical_tickets"
            and _requires_structured_ticket_filter_route(lowered, assignee_names)
        ),
        resolver_first_pattern=(
            "ASSIGNMENT_RECOMMENDATION"
            if provisional_plan.name == "structured_data_query" and is_assignment_query(last_question)
            else provisional_pattern
        ),
    )
    logger.info(
        "AI intent detection: intent=%s confidence=%s source=%s",
        intent.value,
        intent_confidence.value,
        intent_source,
    )
    logger.info(
        "AI entity context: ticket_id=%s source=%s",
        resolved_ticket_id or "-",
        ticket_context_source,
    )
    resolver_first_pattern = _detect_unified_pattern(
        last_question,
        plan=plan,
        guidance_requested=guidance_requested,
    )
    logger.info(
        "AI routing plan selected: %s (intent=%s, constraints=%s, reason=%s, entity_kind=%s, entity_id=%s, inventory_kind=%s, guidance=%s)",
        plan.name,
        plan.intent.value,
        plan.constraints,
        plan.reason,
        intent_details.entity_kind,
        intent_details.entity_id or "-",
        intent_details.inventory_kind or "-",
        guidance_requested,
    )
    if resolved_ticket_id:
        logger.info(
            "AI entity route: ticket_id=%s source=%s route=%s",
            resolved_ticket_id,
            ticket_context_source,
            "single_ticket_data_query" if plan.name == "structured_data_query" and entity_specific_ticket_query else plan.name,
        )
    top = _ticket_prompt_lines(tickets)

    if plan.name == "forced_create_ticket":
        redirect_reply = (
            "La création de tickets se fait via Jira. Je peux vous aider à modifier, analyser ou prioriser un ticket existant."
            if lang == "fr"
            else "Ticket creation is handled via Jira. I can help you modify, analyse, or prioritise an existing ticket."
        )
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=redirect_reply,
            action=None,
            ticket=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_recent_ticket":
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        recent = pool[0] if pool else None
        reply = _format_most_recent_ticket(recent, lang, open_only=open_only)
        summary = _ticket_to_summary(recent, lang)
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=reply,
            action="show_ticket" if summary else None,
            ticket=summary,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_most_used_tickets":
        reply = _format_most_used_tickets(tickets, lang)
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=reply,
            action=None,
            ticket=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_weekly_summary":
        reply = _format_weekly_summary(tickets, stats, lang)
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=reply,
            action=None,
            ticket=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_critical_tickets":
        active_only = _wants_active_only(lowered)
        critical = [t for t in tickets if t.priority == TicketPriority.critical]
        if active_only:
            critical = [t for t in critical if t.status in ACTIVE_STATUSES]
        reply = _format_critical_tickets(critical, lang, active_only=active_only)
        summary = _ticket_to_summary(critical[0], lang) if critical else None
        ticket_results = (
            _build_ticket_results_payload(
                critical,
                lang,
                header="Critical tickets:" if lang == "en" else "Tickets critiques :",
                kind="critical",
            )
            if critical
            else None
        )
        response_payload = build_ticket_list_payload(
            tickets=critical,
            lang=lang,
            list_kind="critical",
            title="Critical tickets" if lang == "en" else "Tickets critiques",
            scope=("Status: active" if lang == "en" else "Statut: actifs") if active_only else None,
            total_count=len(critical),
        )
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=reply,
            action="show_ticket" if summary else None,
            ticket=summary,
            ticket_results=ticket_results,
            response_payload=response_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_recurring_solutions":
        reply = _format_recurring_solutions(tickets, lang, last_question)
        return _compose_chat_response(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            solution_quality=payload.solution_quality,
            reply=reply,
            action=None,
            ticket=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_problems":
        # Problem listing shortcut — fetch from DB, no LLM
        from app.services.ai.conversation_policy import STATUS_KEYWORD_MAP  # noqa: F401
        status_filter = extract_status_filter(lowered)
        query = db.query(Problem)
        if status_filter:
            query = query.filter(Problem.status == status_filter)
        problems_db = query.order_by(Problem.occurrences_count.desc()).limit(20).all()
        problems_list = [
            {
                "id": str(getattr(p, "id", "") or ""),
                "title": str(getattr(p, "title", "") or ""),
                "status": str(getattr(getattr(p, "status", None), "value", getattr(p, "status", None)) or ""),
                "category": str(getattr(getattr(p, "category", None), "value", getattr(p, "category", None)) or ""),
                "occurrences_count": int(getattr(p, "occurrences_count", 0) or 0),
                "active_count": int(getattr(p, "active_count", 0) or 0),
                "last_seen_at": _iso_or_none(getattr(p, "last_seen_at", None)),
                "workaround": _truncate_to(str(getattr(p, "workaround", "") or ""), 120),
            }
            for p in problems_db
        ]
        problem_ids = [p["id"] for p in problems_list if p["id"]]
        # Update session context
        if problem_ids:
            conversation_session.last_problem_list = problem_ids[:8]
            if len(problem_ids) == 1:
                conversation_session.last_problem_id = problem_ids[0]
        response_payload = build_problem_list_payload(problems_list, status_filter, lang)
        if lang == "fr":
            if not problems_list:
                reply = "Aucun problème trouvé" + (f" avec le statut « {status_filter} »" if status_filter else "") + "."
            else:
                reply = f"{len(problems_list)} problème(s) trouvé(s)" + (f" — statut : {status_filter}" if status_filter else "") + "."
        else:
            if not problems_list:
                reply = "No problems found" + (f" with status '{status_filter}'" if status_filter else "") + "."
            else:
                reply = f"{len(problems_list)} problem(s) found" + (f" — status: {status_filter}" if status_filter else "") + "."
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=reply,
            action=None, ticket=None, response_payload=response_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_problem_detail":
        # Single problem detail — fetch by explicit ID or session context
        explicit_problem_id = extract_problem_id(last_question)
        if not explicit_problem_id:
            explicit_problem_id, _ = resolve_problem_contextual_reference(last_question, history_session)
        if not explicit_problem_id:
            explicit_problem_id = history_session.last_problem_id
        problem_obj = get_problem(db, explicit_problem_id) if explicit_problem_id else None
        if problem_obj is None:
            not_found_id = explicit_problem_id or "?"
            reply = (
                f"Problème {not_found_id} introuvable." if lang == "fr"
                else f"Problem {not_found_id} not found."
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
                solution_quality=payload.solution_quality, reply=reply,
                action=None, ticket=None, conversation_state=conversation_session,
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )
        # Update session context
        conversation_session.last_problem_id = str(getattr(problem_obj, "id", "") or "")
        visible_linked_tickets = [
            ticket
            for ticket in tickets
            if str(getattr(ticket, "problem_id", "") or "").strip() == str(getattr(problem_obj, "id", "") or "").strip()
        ]
        linked_count = len(visible_linked_tickets)
        ai_probable_cause: str | None = None
        if not getattr(problem_obj, "root_cause", None):
            try:
                resolver_output = resolve_problem_advice(
                    db,
                    problem_obj,
                    linked_tickets=visible_linked_tickets,
                    user_question=last_question,
                    conversation_state=conversation_session,
                    top_k=DEFAULT_RESOLVER_TOP_K,
                    solution_quality=payload.solution_quality,
                    include_workflow=True,
                    lang=lang,
                    retrieval_fn=unified_retrieve,
                    advice_builder=build_resolution_advice,
                )
                ai_probable_cause = (
                    getattr(getattr(resolver_output, "advice", None), "root_cause", None)
                    or getattr(getattr(resolver_output, "advice", None), "probable_root_cause", None)
                    or getattr(resolver_output, "root_cause", None)
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("Problem detail enrichment failed for %s: %s", explicit_problem_id, exc)
        problem_dict = {
            "id": str(getattr(problem_obj, "id", "") or ""),
            "title": str(getattr(problem_obj, "title", "") or ""),
            "status": str(getattr(getattr(problem_obj, "status", None), "value", getattr(problem_obj, "status", None)) or ""),
            "category": str(getattr(getattr(problem_obj, "category", None), "value", getattr(problem_obj, "category", None)) or ""),
            "occurrences_count": int(getattr(problem_obj, "occurrences_count", 0) or 0),
            "active_count": int(getattr(problem_obj, "active_count", 0) or 0),
            "root_cause": str(getattr(problem_obj, "root_cause", "") or "") or None,
            "workaround": str(getattr(problem_obj, "workaround", "") or "") or None,
            "permanent_fix": str(getattr(problem_obj, "permanent_fix", "") or "") or None,
            "last_seen_at": _iso_or_none(getattr(problem_obj, "last_seen_at", None)),
        }
        response_payload = build_problem_detail_payload(problem_dict, linked_count, ai_probable_cause, lang)
        if lang == "fr":
            reply = f"Problème {problem_dict['id']} — {problem_dict['title']} ({problem_dict['status']})."
        else:
            reply = f"Problem {problem_dict['id']} — {problem_dict['title']} ({problem_dict['status']})."
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=reply,
            action=None, ticket=None, response_payload=response_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_problem_linked_tickets":
        # Drill-down: tickets linked to the last discussed problem
        target_problem_id = extract_problem_id(last_question)
        if not target_problem_id:
            target_problem_id, _ = resolve_problem_contextual_reference(last_question, history_session)
        if not target_problem_id:
            target_problem_id = history_session.last_problem_id
        if not target_problem_id:
            reply = (
                "Aucun problème sélectionné. Mentionnez un ID de problème (ex: PB-001)."
                if lang == "fr"
                else "No problem selected. Please mention a problem ID (e.g. PB-001)."
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
                solution_quality=payload.solution_quality, reply=reply,
                action=None, ticket=None, conversation_state=conversation_session,
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )
        linked_tickets = [
            ticket
            for ticket in tickets
            if str(getattr(ticket, "problem_id", "") or "").strip() == str(target_problem_id).strip()
        ]
        # Group: open/in_progress first, resolved/closed last
        active_linked = [t for t in linked_tickets if t.status not in {TicketStatus.resolved, TicketStatus.closed}]
        resolved_linked = [t for t in linked_tickets if t.status in {TicketStatus.resolved, TicketStatus.closed}]
        ordered = active_linked + resolved_linked
        conversation_session.last_problem_id = str(target_problem_id)
        ticket_summaries = [
            {
                "id": str(getattr(t, "id", "") or ""),
                "title": str(getattr(t, "title", "") or ""),
                "status": str(getattr(getattr(t, "status", None), "value", getattr(t, "status", None)) or ""),
                "priority": str(getattr(getattr(t, "priority", None), "value", getattr(t, "priority", None)) or ""),
                "assignee": str(getattr(t, "assignee", "") or ""),
                "created_at": _iso_or_none(getattr(t, "created_at", None)),
                "route": f"/tickets/{getattr(t, 'id', '')}",
            }
            for t in ordered
        ]
        response_payload = build_problem_linked_tickets_payload(
            problem_id=str(target_problem_id),
            tickets=ticket_summaries,
            language=lang,
        )
        if lang == "fr":
            reply = f"{len(ticket_summaries)} ticket(s) lié(s) au problème {target_problem_id}."
        else:
            reply = f"{len(ticket_summaries)} ticket(s) linked to problem {target_problem_id}."
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=reply,
            action=None, ticket=None, response_payload=response_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_recommendations":
        # Recommendation listing shortcut — read from recommendations service
        try:
            from app.services.recommendations import list_recommendations
            all_recs = list_recommendations(db, current_user)
        except Exception:  # noqa: BLE001
            all_recs = []
        from app.services.ai.calibration import MAX_CHAT_RECOMMENDATIONS
        top_recs = sorted(
            all_recs,
            key=lambda r: float(getattr(r, "confidence", 0) or 0),
            reverse=True,
        )[:MAX_CHAT_RECOMMENDATIONS]
        rec_list = [
            {
                "id": str(getattr(r, "id", "") or ""),
                "title": str(getattr(r, "title", "") or ""),
                "type": str(getattr(r, "recommendation_type", "") or getattr(r, "type", "") or ""),
                "confidence": float(getattr(r, "confidence", 0) or 0),
                "impact": str(getattr(r, "impact", "") or ""),
                "description": str(getattr(r, "description", "") or "")[:160],
            }
            for r in top_recs
        ]
        response_payload = build_recommendation_list_payload(
            recommendations=rec_list,
            language=lang,
        )
        if not rec_list:
            reply = (
                "Aucune recommandation disponible. Ouvrez la page des recommandations pour en générer de nouvelles."
                if lang == "fr"
                else "No recommendations available. Open the recommendations page to generate new ones."
            )
        else:
            reply = (
                f"{len(rec_list)} recommandation(s) disponible(s)."
                if lang == "fr"
                else f"{len(rec_list)} recommendation(s) available."
            )
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=reply,
            action=None, ticket=None, response_payload=response_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_ticket_thread":
        # Ticket thread shortcut — show all comments + resolution for a ticket
        tid = (
            _extract_chat_ticket_id(last_question)
            or (str(resolved_ticket_id).strip().upper() if resolved_ticket_id else None)
        )
        if not tid:
            no_ctx_reply = (
                "Précisez l'identifiant du ticket (ex. TW-123) pour afficher ses commentaires et sa résolution."
                if lang == "fr"
                else "Please specify the ticket ID (e.g. TW-123) to display its comments and resolution."
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
                solution_quality=payload.solution_quality, reply=no_ctx_reply,
                action=None, ticket=None, response_payload=None,
                conversation_state=conversation_session,
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )
        target_ticket = _find_ticket_by_id(tickets, tid)
        if target_ticket is None:
            not_found_reply = (
                f"Ticket {tid} introuvable dans le contexte actuel."
                if lang == "fr"
                else f"Ticket {tid} not found in the current context."
            )
            return _compose_chat_response(
                question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
                solution_quality=payload.solution_quality, reply=not_found_reply,
                action=None, ticket=None, response_payload=None,
                conversation_state=conversation_session,
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )
        thread_payload = build_ticket_thread_payload(target_ticket, lang=lang)
        comment_count = thread_payload.comment_count
        if thread_payload.is_resolved and thread_payload.resolution:
            if lang == "fr":
                thread_reply = (
                    f"Le ticket {tid} est résolu. "
                    f"{'%d commentaire(s) disponible(s).' % comment_count if comment_count else 'Aucun commentaire.'}"
                )
            else:
                thread_reply = (
                    f"Ticket {tid} is resolved. "
                    f"{'%d comment(s) available.' % comment_count if comment_count else 'No comments.'}"
                )
        elif comment_count:
            thread_reply = (
                f"{comment_count} commentaire(s) pour {tid}."
                if lang == "fr"
                else f"{comment_count} comment(s) for {tid}."
            )
        else:
            thread_reply = (
                f"Aucun commentaire ni résolution pour {tid}."
                if lang == "fr"
                else f"No comments or resolution found for {tid}."
            )
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=thread_reply,
            action=None, ticket=target_ticket, response_payload=thread_payload,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name == "shortcut_chitchat":
        # Chitchat / off-topic — no retrieval, no KB, no embeddings.
        # One minimal LLM call with conversation context only.
        reply = _call_llm_for_chitchat(last_question, history_context, lang=lang)
        return _compose_chat_response(
            question=last_question, lang=lang, plan=plan, db=db, tickets=tickets,
            solution_quality=payload.solution_quality, reply=reply,
            action=None, ticket=None, response_payload=None,
            conversation_state=conversation_session,
            allow_resolver_fallback=False,
            request_started_at=request_started_at,
        )

    if plan.name != "forced_create_ticket" and compare_current_id and compare_previous_id:
        current_ticket = _find_ticket_by_id(tickets, compare_current_id)
        previous_ticket = _find_ticket_by_id(tickets, compare_previous_id)
        if current_ticket is not None and previous_ticket is not None:
            comparison_reply = _build_ticket_comparison_reply(current_ticket, previous_ticket, lang=lang)
            comparison_results = _build_ticket_results_payload(
                [current_ticket, previous_ticket],
                lang,
                header=(
                    f"Comparison: {compare_current_id} vs {compare_previous_id}"
                    if lang == "en"
                    else f"Comparaison : {compare_current_id} vs {compare_previous_id}"
                ),
                kind="comparison",
            )
            return _compose_chat_response(
                question=last_question,
                lang=lang,
                plan=plan,
                db=db,
                tickets=tickets,
                solution_quality=payload.solution_quality,
                reply=comparison_reply,
                action=None,
                ticket=None,
                ticket_results=comparison_results,
                conversation_state=conversation_session,
                resolved_ticket_id=compare_current_id,
                ticket_context_source="comparison_context",
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )

    if plan.name == "structured_data_query":
        structured_answer = _answer_data_query(
            last_question,
            tickets,
            lang,
            assignee_names,
            resolved_ticket_id=resolved_ticket_id if entity_specific_ticket_query else None,
            force_single_ticket=entity_specific_ticket_query,
            parsed_filter_meta=intent_details.filter_meta,
        )
        if structured_answer:
            return _compose_chat_response(
                question=last_question,
                lang=lang,
                plan=plan,
                db=db,
                tickets=tickets,
                solution_quality=payload.solution_quality,
                reply=structured_answer.reply,
                action=structured_answer.action,
                ticket=structured_answer.ticket,
                ticket_results=structured_answer.ticket_results,
                response_payload=structured_answer.response_payload,
                conversation_state=conversation_session,
                resolved_ticket_id=resolved_ticket_id,
                ticket_context_source=ticket_context_source,
                allow_resolver_fallback=False,
                request_started_at=request_started_at,
            )
        logger.info("AI routing fallback to general_llm because structured_data_query returned no answer.")
        plan = RoutingPlan(
            name="general_llm",
            intent=ChatIntent.general,
            use_llm=True,
            use_kb=True,
            reason="structured_data_query_no_match",
        )

    question_for_llm = last_question
    top_for_llm = top

    if plan.name == "recent_ticket_filtered":
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        filtered_pool = _filter_recent_tickets_by_constraints(pool, plan.constraints)
        best_recent = filtered_pool[0] if filtered_pool else None
        logger.info(
            "AI routing recent_ticket_filtered: open_only=%s local_matches=%s constraints=%s",
            open_only,
            len(filtered_pool),
            plan.constraints,
        )

        if best_recent is not None:
            question_for_llm = f"{last_question}\n\n{_recent_local_context(best_recent, lang=lang)}"
            filtered_ids = {str(getattr(ticket, "id", "")) for ticket in filtered_pool}
            remainder = [ticket for ticket in tickets if str(getattr(ticket, "id", "")) not in filtered_ids]
            top_for_llm = _ticket_prompt_lines([*filtered_pool[:60], *remainder[:60]], limit=120)
        elif lang == "fr":
            question_for_llm = (
                f"{last_question}\n\n"
                "Aucun ticket local correspondant aux contraintes n'a ete trouve. "
                "Analysez avec prudence et utilisez uniquement des elements verifies."
            )
        else:
            question_for_llm = (
                f"{last_question}\n\n"
                "No local ticket matched these constraints. "
                "Analyze carefully and rely only on verifiable information."
            )
    if history_context and history_context not in question_for_llm:
        question_for_llm = f"{question_for_llm}\n\nConversation context:\n{history_context}".strip()

    try:
        chat_guidance = resolve_chat_guidance(
            question=last_question,
            lang=lang,
            plan=plan,
            db=db,
            tickets=tickets,
            conversation_state=conversation_session,
            current_user=current_user,
            solution_quality=payload.solution_quality,
            guidance_requested=guidance_requested,
            resolved_ticket_id=resolved_ticket_id,
        )
    except Exception as _guidance_exc:
        logger.warning("resolve_chat_guidance failed, falling back to LLM-only path: %s", _guidance_exc)
        chat_guidance = ChatGuidanceContext(grounding=None, resolver_output=None, authoritative=False)
    # For recommendation-like chat requests, the resolver/advisor owns the
    # recommendation truth. The LLM is only allowed to format that grounding.
    if chat_guidance.authoritative and chat_guidance.grounding is not None:
        reply, action, ticket_payload = build_chat_reply(
            last_question,
            stats,
            top_for_llm,
            lang=lang,
            locale=payload.locale,
            assignees=assignee_names,
            grounding=chat_guidance.grounding,
        )
    else:
        reply, action, ticket_payload = build_chat_reply(
            question_for_llm,
            stats,
            top_for_llm,
            lang=lang,
            locale=payload.locale,
            assignees=assignee_names,
        )

    if action == "create_ticket" and not create_requested:
        # Keep the draft payload available as a preview/create option,
        # but avoid forcing explicit create action when intent is ambiguous.
        action = "none"

    ticket: TicketDraft | None = None
    if isinstance(ticket_payload, dict):
        ticket = _build_ticket_draft_from_payload(
            ticket_payload=ticket_payload,
            fallback_question=last_question,
            assignee_names=assignee_names,
            current_user=current_user,
        )

    return _compose_chat_response(
        question=last_question,
        lang=lang,
        plan=plan,
        db=db,
        tickets=tickets,
        solution_quality=payload.solution_quality,
        reply=reply,
        action=action,
        ticket=ticket,
        conversation_state=conversation_session,
        chat_guidance=chat_guidance,
        resolved_ticket_id=resolved_ticket_id,
        ticket_context_source=ticket_context_source,
        request_started_at=request_started_at,
    )


def handle_suggest(payload: SuggestRequest, db: Session, current_user) -> SuggestResponse:
    with ai_pipeline_duration_seconds.labels(operation="suggest").time():
        return _handle_suggest_inner(payload, db, current_user)


def _handle_suggest_inner(payload: SuggestRequest, db: Session, current_user) -> SuggestResponse:
    tickets = list_tickets_for_user(db, current_user)
    resolver_output = resolve_ticket_advice(
        db,
        _build_chat_resolver_ticket(payload.query, conversation_state=None),
        user_question=payload.query,
        conversation_state=None,
        visible_tickets=tickets,
        top_k=DEFAULT_RESOLVER_TOP_K,
        solution_quality=payload.solution_quality,
        include_workflow=True,
        include_priority=False,
        lang=_normalize_locale(payload.locale),
        retrieval_fn=unified_retrieve,
        advice_builder=build_resolution_advice,
    )
    bundle = _build_suggestion_bundle(resolver_output, lang=_normalize_locale(payload.locale))
    plan = RoutingPlan(
        name="suggestion_engine",
        intent=detect_intent(payload.query),
        use_llm=False,
        use_kb=True,
        reason="explicit_suggest_endpoint",
    )
    pattern = _detect_unified_pattern(payload.query, plan=plan)
    actions = _suggestion_actions(pattern, bundle, base_action=None)
    rag_grounding = bool(
        bundle.guidance_contract is not None
        and bundle.guidance_contract.evidence_allowed
        and bundle.source not in {"fallback_rules", "kb_empty"}
    )
    return SuggestResponse(
        rag_grounding=rag_grounding,
        suggestions=bundle,
        actions=actions,
    )
