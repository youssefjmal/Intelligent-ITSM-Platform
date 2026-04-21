"""Schemas for AI classification/chat requests and responses.

SCHEMA DEBT NOTE (added 2026-03-25):
    ``AIResolutionAdvice`` carries two fields that encode the same concept:
    - ``display_mode`` — the canonical field.  Use this.
    - ``mode``         — deprecated; retained only for backwards compatibility
                         with any consumers not yet updated.

    ``mode`` is kept Optional[str] and is backfilled from ``display_mode`` by
    a model_validator so that existing consumers reading ``mode`` continue to
    work without changes.

    Removal condition: remove ``mode`` after confirming zero frontend fallback
    warnings (console.warn in recommendations-api.ts / tickets-api.ts) in
    staging for at least one full release cycle.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import TicketCategory, TicketPriority, TicketType
from app.core.ticket_limits import MAX_TAG_LEN, MAX_TAGS
from app.core.sanitize import clean_list, clean_multiline, clean_single_line

MAX_CHAT_MESSAGES = 40
MAX_CHAT_CONTENT_LEN = 4000
MAX_TITLE_LEN = 120
MAX_DESCRIPTION_LEN = 4000
ALLOWED_CHAT_ROLES = {"user", "assistant", "system", "tool"}
ALLOWED_SOLUTION_QUALITY = {"low", "medium", "high"}


class GuidanceDisplayMode(str, Enum):
    evidence_action = "evidence_action"
    tentative_diagnostic = "tentative_diagnostic"
    service_request = "service_request"
    llm_general_knowledge = "llm_general_knowledge"
    no_strong_match = "no_strong_match"
    needs_more_info = "needs_more_info"
    manual_triage = "manual_triage"

    @classmethod
    def coerce(
        cls,
        value: Any,
        *,
        default: "GuidanceDisplayMode" = None,
    ) -> "GuidanceDisplayMode":
        fallback = default or cls.no_strong_match
        text = clean_single_line(value).lower()
        try:
            return cls(text)
        except ValueError:
            return fallback


def legacy_guidance_display_mode(mode: GuidanceDisplayMode | str | None) -> GuidanceDisplayMode:
    resolved = GuidanceDisplayMode.coerce(mode)
    if resolved == GuidanceDisplayMode.needs_more_info:
        return GuidanceDisplayMode.tentative_diagnostic
    if resolved == GuidanceDisplayMode.manual_triage:
        return GuidanceDisplayMode.no_strong_match
    return resolved


class GuidanceContract(BaseModel):
    display_mode: GuidanceDisplayMode = GuidanceDisplayMode.no_strong_match
    legacy_display_mode: GuidanceDisplayMode = GuidanceDisplayMode.no_strong_match
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    advisor_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "fallback_rules"
    downgraded: bool = False
    downgrade_reason: str | None = None
    evidence_allowed: bool = False

    @model_validator(mode="after")
    def _sync_legacy_mode(self) -> "GuidanceContract":
        self.legacy_display_mode = legacy_guidance_display_mode(self.display_mode)
        return self


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)

    query: str = ""
    query_context: dict[str, Any] = Field(default_factory=dict)
    kb_articles: list[dict[str, Any]] = Field(default_factory=list)
    similar_tickets: list[dict[str, Any]] = Field(default_factory=list)
    related_problems: list[dict[str, Any]] = Field(default_factory=list)
    suggested_solutions: list[str] = Field(default_factory=list)
    comment_matches: list[dict[str, Any]] = Field(default_factory=list)
    solution_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    consensus_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_conflict_flag: bool = False
    evidence_clusters: dict[str, Any] = Field(default_factory=dict)
    source: str = "fallback_rules"
    source_breakdown: dict[str, Any] = Field(default_factory=dict)
    excluded_ids: list[str] = Field(default_factory=list)

    @classmethod
    def coerce(cls, value: "RetrievalResult | dict[str, Any] | None") -> "RetrievalResult":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls.model_validate(value)
        return cls()

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        extra = getattr(self, "__pydantic_extra__", None) or {}
        return extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        extra = getattr(self, "__pydantic_extra__", None) or {}
        if key in extra:
            return extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in type(self).model_fields:
            setattr(self, key, value)
            return
        extra = getattr(self, "__pydantic_extra__", None)
        if extra is None:
            object.__setattr__(self, "__pydantic_extra__", {})
            extra = getattr(self, "__pydantic_extra__", None)
        extra[key] = value


class UnknownTicketType(BaseModel):
    requires_manual_triage: bool = True
    reason: str = "insufficient_signal"
    request_weight: float = Field(default=0.0, ge=0.0)
    incident_weight: float = Field(default=0.0, ge=0.0)
    matched_request_signals: list[str] = Field(default_factory=list)
    matched_incident_signals: list[str] = Field(default_factory=list)
    suppressing_signals: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=MAX_CHAT_CONTENT_LEN)
    response_payload_type: str | None = None
    entity_kind: str | None = None
    entity_id: str | None = None
    inventory_kind: str | None = None
    listed_entity_ids: list[str] = Field(default_factory=list)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        role = clean_single_line(value).lower()
        if role not in ALLOWED_CHAT_ROLES:
            raise ValueError("invalid_role")
        return role

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return clean_multiline(value)

    @field_validator("response_payload_type", "entity_kind", "entity_id", "inventory_kind", mode="before")
    @classmethod
    def normalize_optional_single_line(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("listed_entity_ids", mode="before")
    @classmethod
    def normalize_listed_entity_ids(cls, value: list[str] | None) -> list[str]:
        items = value or []
        normalized: list[str] = []
        for item in items:
            cleaned = clean_single_line(item)
            if cleaned:
                normalized.append(cleaned)
        return normalized


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    locale: str | None = Field(default=None, max_length=16)
    solution_quality: str = Field(default="medium", max_length=16)
    conversation_id: str | None = Field(default=None, max_length=36)

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("solution_quality", mode="before")
    @classmethod
    def normalize_solution_quality(cls, value: str | None) -> str:
        cleaned = (clean_single_line(value) or "medium").lower()
        if cleaned not in ALLOWED_SOLUTION_QUALITY:
            raise ValueError("invalid_solution_quality")
        return cleaned


class TicketDraft(BaseModel):
    title: str = Field(min_length=3, max_length=MAX_TITLE_LEN)
    description: str = Field(min_length=5, max_length=MAX_DESCRIPTION_LEN)
    priority: TicketPriority
    ticket_type: TicketType | None = None
    category: TicketCategory
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    assignee: str | None = Field(default=None, max_length=80)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return clean_multiline(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return clean_list(value, max_items=MAX_TAGS, item_max_length=MAX_TAG_LEN)

    @field_validator("assignee", mode="before")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class ClassificationRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=20)
    title: str = Field(min_length=3, max_length=MAX_TITLE_LEN)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LEN)
    locale: str | None = Field(default=None, max_length=16)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str:
        return clean_multiline(value)

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("ticket_id", mode="before")
    @classmethod
    def normalize_ticket_id(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class AIRecommendationOut(BaseModel):
    text: str
    confidence: int = Field(ge=0, le=100)


class AISuggestedTicket(BaseModel):
    id: str
    title: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    status: str
    resolution_snippet: str | None = None


class AISuggestedProblem(BaseModel):
    id: str
    title: str
    match_reason: str
    root_cause: str | None = None
    affected_tickets: int | None = None


class AISuggestedKBArticle(BaseModel):
    id: str
    title: str
    excerpt: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    source_type: str | None = None


class AISolutionRecommendation(BaseModel):
    text: str
    source: str
    source_id: str | None = None
    evidence_snippet: str | None = None
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    helpful_votes: int = 0
    not_helpful_votes: int = 0
    reason: str | None = None


class AIResolutionEvidence(BaseModel):
    evidence_type: str
    reference: str
    excerpt: str | None = None
    source_id: str | None = None
    title: str | None = None
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    why_relevant: str | None = None


class AIIncidentCluster(BaseModel):
    count: int = 0
    window_hours: int = 24
    summary: str


class AIRecommendationCurrentFeedback(BaseModel):
    feedback_type: str
    created_at: dt.datetime
    updated_at: dt.datetime


class AIRecommendationFeedbackSummary(BaseModel):
    total_feedback: int = 0
    useful_count: int = 0
    not_relevant_count: int = 0
    applied_count: int = 0
    rejected_count: int = 0
    usefulness_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    applied_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    rejection_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class AIRecommendationFeedbackSummaryWithBreakdown(AIRecommendationFeedbackSummary):
    by_surface: dict[str, AIRecommendationFeedbackSummary] = Field(default_factory=dict)
    by_display_mode: dict[str, AIRecommendationFeedbackSummary] = Field(default_factory=dict)
    by_confidence_band: dict[str, AIRecommendationFeedbackSummary] = Field(default_factory=dict)
    by_recommendation_mode: dict[str, AIRecommendationFeedbackSummary] = Field(default_factory=dict)
    by_source_label: dict[str, AIRecommendationFeedbackSummary] = Field(default_factory=dict)


class AILLMGeneralAdvisory(BaseModel):
    """Payload for the llm_general_knowledge display mode.

    Populated only when display_mode is "llm_general_knowledge".
    None on all evidence-backed response types.

    Trust level: lowest in the system — below tentative_diagnostic.
    Frontend must never show an Apply button for this type.
    """

    probable_causes: list[str] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)
    escalation_hint: str | None = None
    knowledge_source: str = "llm_general_knowledge"
    confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    language: str = "fr"


"""
AI resolution advice payload returned by the advisor pipeline.

display_mode controls frontend rendering:
- evidence_action: strong local evidence, show full recommendation card
- tentative_diagnostic: weak local evidence, show cautious diagnostic card
- service_request: planned fulfillment workflow, show runbook-style guidance
- no_strong_match: no evidence and LLM fallback unavailable, show minimal state
- llm_general_knowledge: no local evidence but LLM advisory available,
    show general advisory card with explicit disclaimer and no Apply button

Trust hierarchy (highest to lowest):
evidence_action > tentative_diagnostic > service_request > llm_general_knowledge > no_strong_match
"""


class AIResolutionAdvice(BaseModel):
    recommended_action: str | None = None
    reasoning: str
    probable_root_cause: str | None = None
    root_cause: str | None = None
    supporting_context: str | None = None
    why_this_matches: list[str] = Field(default_factory=list)
    evidence_sources: list[AIResolutionEvidence] = Field(default_factory=list)
    tentative: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_band: str = "low"
    confidence_label: str = "low"
    source_label: str = "fallback_rules"
    recommendation_mode: str = "fallback_rules"
    action_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filtered_weak_match: bool = False
    # Deprecated: use display_mode.  Retained for backwards compatibility with
    # consumers not yet updated.  Will be removed after zero frontend fallback
    # warnings are confirmed in staging.  Backfilled from display_mode by the
    # model_validator below.
    mode: GuidanceDisplayMode | None = None
    display_mode: GuidanceDisplayMode = GuidanceDisplayMode.evidence_action
    match_summary: str | None = None
    next_best_actions: list[str] = Field(default_factory=list)
    base_recommended_action: str | None = None
    base_next_best_actions: list[str] = Field(default_factory=list)
    base_validation_steps: list[str] = Field(default_factory=list)
    action_refinement_source: str | None = None
    incident_cluster: AIIncidentCluster | None = None
    impact_summary: str | None = None
    workflow_steps: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    fallback_action: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    response_text: str
    # Populated only when display_mode is "llm_general_knowledge".
    # None on all evidence-backed response types.
    llm_general_advisory: AILLMGeneralAdvisory | None = None
    # "llm_general_knowledge" when the fallback fired, None otherwise.
    # Used by frontend to select correct visual treatment.
    knowledge_source: str | None = None
    # True when the recommendation was generated entirely by the LLM with no
    # supporting evidence from past tickets. Frontend shows a warning banner.
    ai_only_warning: bool = False

    @model_validator(mode="after")
    def _backfill_deprecated_mode(self) -> "AIResolutionAdvice":
        """Ensure ``mode`` is always populated even when callers omit it.

        ``mode`` is deprecated in favour of ``display_mode``.  This validator
        copies ``display_mode`` into ``mode`` when ``mode`` is None so that
        existing consumers that still read ``mode`` continue to work without
        any changes on their side.

        Removal: delete this validator when ``mode`` is removed from the schema.
        """
        if self.mode is None:
            self.mode = self.display_mode
        return self


class AISuggestionBundle(BaseModel):
    tickets: list[AISuggestedTicket] = Field(default_factory=list)
    problems: list[AISuggestedProblem] = Field(default_factory=list)
    kb_articles: list[AISuggestedKBArticle] = Field(default_factory=list)
    solution_recommendations: list[AISolutionRecommendation] = Field(default_factory=list)
    resolution_advice: AIResolutionAdvice | None = None
    guidance_contract: GuidanceContract | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "llm_fallback"


class AIDraftContext(BaseModel):
    pre_filled_description: str
    suggested_priority: str | None = None
    related_tickets: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AIChatGrounding(BaseModel):
    entity_type: str = "none"
    entity_id: str | None = None
    mode: str = "informational"
    confidence_band: str = "low"
    root_cause: str | None = None
    recommended_action: str | None = None
    supporting_context: str | None = None
    why_this_matches: list[str] = Field(default_factory=list)
    evidence_sources: list[AIResolutionEvidence] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    fallback_action: str | None = None
    next_best_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    retrieval_mode: str = "fallback_rules"
    degraded: bool = False


class AIChatTicketResult(BaseModel):
    id: str
    title: str
    priority: str
    status: str
    assignee: str
    sla_status: str | None = None


class AIChatTicketResults(BaseModel):
    kind: str = "generic"
    header: str
    scope: str | None = None
    total_count: int = 0
    tickets: list[AIChatTicketResult] = Field(default_factory=list)


class AIChatActionLink(BaseModel):
    label: str
    route: str


class AIChatConfidence(BaseModel):
    level: Literal["low", "medium", "high"] = "low"
    reason: str


class AIChatSLAState(BaseModel):
    state: str | None = None
    due_at: str | None = None
    remaining_minutes: int | None = None
    remaining_human: str | None = None


class AIChatCommentSummary(BaseModel):
    author: str | None = None
    content: str
    created_at: str | None = None


class AIChatRelatedEntity(BaseModel):
    entity_type: str
    entity_id: str
    title: str | None = None
    relation: str | None = None
    route: str


class AIChatRelatedTicketRef(BaseModel):
    ticket_id: str
    title: str
    status: str | None = None
    priority: str | None = None
    route: str


class AIChatStatusResponse(BaseModel):
    type: Literal["ticket_status"] = "ticket_status"
    ticket_id: str
    title: str
    status: str
    priority: str
    assignee: str
    sla_state: str | None = None
    updated_at: str | None = None
    summary: str
    actions: list[AIChatActionLink] = Field(default_factory=list)


class AIChatTicketDetailsResponse(BaseModel):
    type: Literal["ticket_details"] = "ticket_details"
    ticket_id: str
    title: str
    description: str
    ticket_type: TicketType | None = None
    status: str
    priority: str
    assignee: str
    reporter: str | None = None
    category: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    sla: AIChatSLAState | None = None
    recent_comments: list[AIChatCommentSummary] = Field(default_factory=list)
    related_entities: list[AIChatRelatedEntity] = Field(default_factory=list)
    actions: list[AIChatActionLink] = Field(default_factory=list)


class AIChatAdviceStep(BaseModel):
    step: int
    text: str
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)


class AIChatResolutionAdviceResponse(BaseModel):
    type: Literal["resolution_advice"] = "resolution_advice"
    ticket_id: str | None = None
    summary: str
    recommended_actions: list[AIChatAdviceStep] = Field(default_factory=list)
    why_this_matches: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    related_tickets: list[AIChatRelatedTicketRef] = Field(default_factory=list)
    confidence: AIChatConfidence


class AIChatCauseCandidate(BaseModel):
    title: str
    likelihood: Literal["low", "medium", "high"] = "low"
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    related_tickets: list[AIChatRelatedTicketRef] = Field(default_factory=list)


class AIChatCauseAnalysisResponse(BaseModel):
    type: Literal["cause_analysis"] = "cause_analysis"
    ticket_id: str | None = None
    summary: str
    possible_causes: list[AIChatCauseCandidate] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    confidence: AIChatConfidence


class AIChatListMetrics(BaseModel):
    open_count: int = 0
    critical_count: int = 0


class AIChatListTicketItem(BaseModel):
    ticket_id: str
    title: str
    status: str
    priority: str
    assignee: str
    ticket_type: str | None = None
    category: str | None = None
    sla_risk: str | None = None
    route: str


class AIChatTopRecommendation(BaseModel):
    summary: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AIChatTicketListResponse(BaseModel):
    type: Literal["ticket_list"] = "ticket_list"
    list_kind: str = "generic"
    title: str
    scope: str | None = None
    total_count: int = 0
    returned_count: int = 0
    has_more: bool = False
    summary_metrics: AIChatListMetrics = Field(default_factory=AIChatListMetrics)
    tickets: list[AIChatListTicketItem] = Field(default_factory=list)
    top_recommendation: AIChatTopRecommendation | None = None
    action_links: list[AIChatExtendedActionLink] = Field(default_factory=list)


class AIChatExtendedActionLink(BaseModel):
    label: str
    route: str | None = None
    intent: str | None = None


class AIChatProblemDetailResponse(BaseModel):
    type: Literal["problem_detail"] = "problem_detail"
    problem_id: str
    title: str
    status: str
    category: str
    occurrences_count: int = 0
    active_count: int = 0
    root_cause: str | None = None
    workaround: str | None = None
    permanent_fix: str | None = None
    ai_probable_cause: str | None = None
    linked_ticket_count: int = 0
    last_seen_at: str | None = None
    action_links: list[AIChatExtendedActionLink] = Field(default_factory=list)


class AIChatProblemListItem(BaseModel):
    id: str
    title: str
    status: str
    category: str
    occurrences_count: int = 0
    active_count: int = 0
    last_seen_at: str | None = None
    workaround: str | None = None


class AIChatProblemListResponse(BaseModel):
    type: Literal["problem_list"] = "problem_list"
    title: str = "Problems"
    scope: str | None = None
    problems: list[AIChatProblemListItem] = Field(default_factory=list)
    status_filter: str | None = None
    total_count: int = 0
    returned_count: int = 0
    has_more: bool = False
    action_links: list[AIChatExtendedActionLink] = Field(default_factory=list)


class AIChatProblemLinkedTicketItem(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    assignee: str
    created_at: str | None = None
    route: str


class AIChatProblemLinkedTicketsResponse(BaseModel):
    type: Literal["problem_linked_tickets"] = "problem_linked_tickets"
    problem_id: str
    title: str = "Problem linked tickets"
    tickets: list[AIChatProblemLinkedTicketItem] = Field(default_factory=list)
    total_count: int = 0
    returned_count: int = 0
    has_more: bool = False
    action_links: list[AIChatExtendedActionLink] = Field(default_factory=list)


class AIChatRecommendationListItem(BaseModel):
    id: str
    title: str
    type: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    impact: str
    description: str


class AIChatRecommendationListResponse(BaseModel):
    type: Literal["recommendation_list"] = "recommendation_list"
    title: str = "Recommendations"
    scope: str | None = None
    recommendations: list[AIChatRecommendationListItem] = Field(default_factory=list)
    total_count: int = 0
    returned_count: int = 0
    has_more: bool = False
    action_links: list[AIChatExtendedActionLink] = Field(default_factory=list)


class AIChatSimilarTicketMatch(BaseModel):
    ticket_id: str
    title: str
    match_reason: str
    match_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str | None = None
    route: str


class AIChatSimilarTicketsResponse(BaseModel):
    type: Literal["similar_tickets"] = "similar_tickets"
    source_ticket_id: str | None = None
    matches: list[AIChatSimilarTicketMatch] = Field(default_factory=list)


class AIChatAssignmentRecommendationResponse(BaseModel):
    type: Literal["assignment_recommendation"] = "assignment_recommendation"
    ticket_id: str | None = None
    current_assignee: str | None = None
    recommended_assignee: str | None = None
    reasoning: list[str] = Field(default_factory=list)
    confidence: AIChatConfidence


class AIChatInsufficientEvidenceResponse(BaseModel):
    type: Literal["insufficient_evidence"] = "insufficient_evidence"
    summary: str
    known_facts: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    recommended_next_checks: list[str] = Field(default_factory=list)


class AIChatTicketCommentItem(BaseModel):
    author: str
    content: str
    created_at: str | None = None
    source: str | None = None  # "jira" | "local"


class AIChatTicketThreadResponse(BaseModel):
    type: Literal["ticket_thread"] = "ticket_thread"
    ticket_id: str
    title: str
    status: str
    is_resolved: bool = False
    resolution: str | None = None
    comment_count: int = 0
    comments: list[AIChatTicketCommentItem] = Field(default_factory=list)
    confidence: AIChatConfidence


AIChatStructuredResponse = Annotated[
    AIChatStatusResponse
    | AIChatTicketDetailsResponse
    | AIChatResolutionAdviceResponse
    | AIChatCauseAnalysisResponse
    | AIChatTicketListResponse
    | AIChatProblemDetailResponse
    | AIChatProblemListResponse
    | AIChatProblemLinkedTicketsResponse
    | AIChatRecommendationListResponse
    | AIChatSimilarTicketsResponse
    | AIChatAssignmentRecommendationResponse
    | AIChatInsufficientEvidenceResponse
    | AIChatTicketThreadResponse,
    Field(discriminator="type"),
]


class ChatResponse(BaseModel):
    reply: str
    message: str | None = None
    action: str | None = None
    ticket: TicketDraft | None = None
    rag_grounding: bool = False
    retrieval_mode: str = "fallback_rules"
    degraded: bool = False
    conversation_id: str | None = None
    # Structured fields — required for rich card rendering in the frontend.
    resolution_advice: AIResolutionAdvice | None = None
    grounding: AIChatGrounding | None = None
    suggestions: AISuggestionBundle = Field(default_factory=AISuggestionBundle)
    draft_context: AIDraftContext | None = None
    actions: list[str] = Field(default_factory=list)
    ticket_results: AIChatTicketResults | None = None
    response_payload: AIChatStructuredResponse | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
    message_count: int = 0


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: dt.datetime
    action: str | None = None
    ticket: TicketDraft | None = None
    rag_grounding: bool = False
    resolution_advice: AIResolutionAdvice | None = None
    grounding: AIChatGrounding | None = None
    suggestions: AISuggestionBundle = Field(default_factory=AISuggestionBundle)
    draft_context: AIDraftContext | None = None
    actions: list[str] = Field(default_factory=list)
    ticket_results: AIChatTicketResults | None = None
    response_payload: AIChatStructuredResponse | None = None


class SuggestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_CHAT_CONTENT_LEN)
    locale: str | None = Field(default=None, max_length=16)
    solution_quality: str = Field(default="medium", max_length=16)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return clean_multiline(value)

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_suggest_locale(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("solution_quality", mode="before")
    @classmethod
    def normalize_suggest_solution_quality(cls, value: str | None) -> str:
        cleaned = (clean_single_line(value) or "medium").lower()
        if cleaned not in ALLOWED_SOLUTION_QUALITY:
            raise ValueError("invalid_solution_quality")
        return cleaned


class SuggestResponse(BaseModel):
    rag_grounding: bool = False
    suggestions: AISuggestionBundle = Field(default_factory=AISuggestionBundle)
    actions: list[str] = Field(default_factory=list)


class AIFeedbackRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=20)
    recommendation_id: str | None = Field(default=None, max_length=64)
    answer_type: str | None = Field(default=None, max_length=32)
    feedback_type: str | None = Field(default=None, max_length=24)
    source_surface: str | None = Field(default=None, max_length=32)
    recommended_action: str | None = Field(default=None, max_length=MAX_CHAT_CONTENT_LEN)
    display_mode: str | None = Field(default=None, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    match_summary: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    evidence_count: int | None = Field(default=None, ge=0, le=99)
    metadata: dict[str, str | int | float | bool | None] | None = None
    query: str | None = Field(default=None, max_length=MAX_CHAT_CONTENT_LEN)
    recommendation_text: str | None = Field(default=None, max_length=MAX_CHAT_CONTENT_LEN)
    source: str | None = Field(default=None, max_length=32)
    source_id: str | None = Field(default=None, max_length=120)
    vote: str | None = Field(default=None, max_length=16)
    context: dict[str, str | int | float | bool | None] | None = None

    @field_validator(
        "query",
        "recommendation_text",
        "recommended_action",
        "reasoning",
        "match_summary",
        mode="before",
    )
    @classmethod
    def normalize_feedback_body_fields(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value) if value is not None else None
        return cleaned or None

    @field_validator("ticket_id", "recommendation_id", "answer_type", "source", "source_id", "source_surface", "display_mode", mode="before")
    @classmethod
    def normalize_feedback_identity_fields(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value) if value is not None else None
        return cleaned or None

    @field_validator("vote", "feedback_type", mode="before")
    @classmethod
    def normalize_feedback_vote(cls, value: str) -> str:
        cleaned = clean_single_line(value).lower() if value is not None else ""
        return cleaned or None

    @model_validator(mode="after")
    def validate_feedback_shape(self) -> "AIFeedbackRequest":
        if self.feedback_type:
            if self.feedback_type not in {"useful", "not_relevant", "applied", "rejected"}:
                raise ValueError("invalid_feedback_type")
            if self.source_surface not in {"ticket_detail", "recommendations_page", "ticket_chatbot"}:
                raise ValueError("invalid_source_surface")
            if self.source_surface in {"ticket_detail", "ticket_chatbot"} and not self.ticket_id:
                raise ValueError("ticket_id_required")
            if self.source_surface == "ticket_chatbot" and self.answer_type not in {
                "resolution_advice",
                "cause_analysis",
                "suggestion_resolution_advice",
            }:
                raise ValueError("invalid_chatbot_answer_type")
            if self.source_surface == "recommendations_page" and not self.recommendation_id:
                raise ValueError("recommendation_id_required")
            return self

        if not self.recommendation_text:
            raise ValueError("recommendation_text_required")
        if not self.source:
            raise ValueError("source_required")
        if self.vote not in {"helpful", "not_helpful"}:
            raise ValueError("invalid_vote")
        return self


class AIFeedbackResponse(BaseModel):
    status: str
    source: str | None = None
    source_id: str | None = None
    ticket_id: str | None = None
    recommendation_id: str | None = None
    source_surface: str | None = None
    helpful_votes: int = 0
    not_helpful_votes: int = 0
    current_feedback: AIRecommendationCurrentFeedback | None = None
    feedback_summary: AIRecommendationFeedbackSummary | None = None


class ClassificationResponse(BaseModel):
    priority: TicketPriority
    ticket_type: TicketType | None = None
    classifier_ticket_type: TicketType | None = None
    manual_triage_required: bool = False
    unknown_ticket_type: UnknownTicketType | None = None
    category: TicketCategory
    classification_confidence: int = Field(ge=0, le=100)
    recommendations: list[str]
    recommendations_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendations_embedding: list[str] = Field(default_factory=list)
    recommendations_embedding_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendations_llm: list[str] = Field(default_factory=list)
    recommendations_llm_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendation_mode: str = "fallback_rules"
    similarity_found: bool = False
    assignee: str | None = None
    source_label: str = "fallback_rules"
    resolution_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    resolution_advice: AIResolutionAdvice | None = None
    recommended_action: str | None = None
    reasoning: str | None = None
    evidence_sources: list[AIResolutionEvidence] = Field(default_factory=list)
    probable_root_cause: str | None = None
    root_cause: str | None = None
    supporting_context: str | None = None
    why_this_matches: list[str] = Field(default_factory=list)
    tentative: bool = False
    confidence_band: str = "low"
    confidence_label: str = "low"
    action_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filtered_weak_match: bool = False
    mode: str = "evidence_action"
    display_mode: str = "evidence_action"
    guidance_contract: GuidanceContract | None = None
    match_summary: str | None = None
    next_best_actions: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    base_recommended_action: str | None = None
    base_next_best_actions: list[str] = Field(default_factory=list)
    base_validation_steps: list[str] = Field(default_factory=list)
    action_refinement_source: str | None = None
    routing_decision_source: str | None = None
    service_request_profile_detected: bool = False
    service_request_profile_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cross_check_conflict_flag: bool = False
    cross_check_summary: str | None = None
    incident_cluster: AIIncidentCluster | None = None
    impact_summary: str | None = None
    current_feedback: AIRecommendationCurrentFeedback | None = None
    feedback_summary: AIRecommendationFeedbackSummary | None = None
