// API helpers for tickets with snake_case to camelCase mapping.

import { apiFetch } from "@/lib/api"
import type {
  RecommendationCurrentFeedback,
  RecommendationFeedbackSummary,
} from "@/lib/ai-feedback-api"
import {
  type SlaStatus,
  type Ticket,
  type TicketCategory,
  type TicketPriority,
  type TicketStatus,
  type TicketType,
} from "@/lib/ticket-data"

type ApiComment = {
  id: string
  author: string
  content: string
  created_at: string
}

type ApiTicketHistoryChange = {
  field: string
  before?: unknown
  after?: unknown
}

type ApiTicketHistoryEvent = {
  id: string
  ticket_id: string
  event_type: string
  action?: string | null
  actor: string
  actor_id?: string | null
  actor_role?: string | null
  comment_added?: boolean
  comment_id?: string | null
  created_at: string
  changes: ApiTicketHistoryChange[]
}

type ApiTicket = {
  id: string
  problem_id?: string | null
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  ticket_type: TicketType
  category: TicketCategory
  assignee: string
  reporter: string
  auto_assignment_applied?: boolean
  auto_priority_applied?: boolean
  assignment_model_version?: string
  priority_model_version?: string
  predicted_priority?: TicketPriority | null
  predicted_ticket_type?: TicketType | null
  predicted_category?: TicketCategory | null
  assignment_change_count?: number
  first_action_at?: string | null
  resolved_at?: string | null
  due_at?: string | null
  sla_status?: SlaStatus | null
  sla_remaining_minutes?: number | null
  sla_first_response_due_at?: string | null
  sla_resolution_due_at?: string | null
  sla_first_response_breached?: boolean
  sla_resolution_breached?: boolean
  sla_last_synced_at?: string | null
  created_at: string
  updated_at: string
  resolution?: string | null
  tags: string[]
  comments: ApiComment[]
  change_risk?: string | null
  change_scheduled_at?: string | null
  change_approved?: boolean | null
  change_approved_by?: string | null
  change_approved_at?: string | null
}

export type TicketPerformancePayload = {
  total_tickets: number
  resolved_tickets: number
  mttr_hours: {
    before: number | null
    after: number | null
  }
  mttr_global_hours: number | null
  mttr_p90_hours: number | null
  mttr_by_priority_hours: Record<string, number | null>
  mttr_by_category_hours: Record<string, number | null>
  throughput_resolved_per_week: number
  backlog_open_over_days: number
  backlog_threshold_days: number
  reassignment_rate: number
  reassigned_tickets: number
  avg_time_to_first_action_hours: number | null
  median_time_to_first_action_hours: number | null
  classification_accuracy_rate: number | null
  classification_samples: number
  auto_assignment_accuracy_rate: number | null
  auto_assignment_samples: number
  auto_triage_no_correction_rate: number | null
  auto_triage_no_correction_count: number
  auto_triage_samples: number
  sla_breach_rate: number | null
  sla_breached_tickets: number
  sla_tickets_with_due: number
  first_response_sla_breach_rate: number | null
  first_response_sla_breached_count: number
  first_response_sla_eligible: number
  resolution_sla_breach_rate: number | null
  resolution_sla_breached_count: number
  resolution_sla_eligible: number
  reopen_rate: number | null
  first_contact_resolution_rate: number | null
  csat_score: number | null
}

function mapTicket(ticket: ApiTicket): Ticket {
  return {
    id: ticket.id,
    problemId: ticket.problem_id || undefined,
    title: ticket.title,
    description: ticket.description,
    status: ticket.status,
    priority: ticket.priority,
    ticketType: ticket.ticket_type,
    category: ticket.category,
    assignee: ticket.assignee,
    reporter: ticket.reporter,
    autoAssignmentApplied: ticket.auto_assignment_applied,
    autoPriorityApplied: ticket.auto_priority_applied,
    assignmentModelVersion: ticket.assignment_model_version,
    priorityModelVersion: ticket.priority_model_version,
    predictedPriority: ticket.predicted_priority || undefined,
    predictedTicketType: ticket.predicted_ticket_type || undefined,
    predictedCategory: ticket.predicted_category || undefined,
    assignmentChangeCount: ticket.assignment_change_count,
    firstActionAt: ticket.first_action_at || undefined,
    resolvedAt: ticket.resolved_at || undefined,
    dueAt: ticket.due_at ?? null,
    slaStatus: ticket.sla_status ?? null,
    slaRemainingMinutes: ticket.sla_remaining_minutes ?? null,
    slaFirstResponseDueAt: ticket.sla_first_response_due_at ?? null,
    slaResolutionDueAt: ticket.sla_resolution_due_at ?? null,
    slaFirstResponseBreached: Boolean(ticket.sla_first_response_breached),
    slaResolutionBreached: Boolean(ticket.sla_resolution_breached),
    slaLastSyncedAt: ticket.sla_last_synced_at ?? null,
    createdAt: ticket.created_at,
    updatedAt: ticket.updated_at,
    resolution: ticket.resolution || undefined,
    tags: ticket.tags,
    comments: ticket.comments.map((c) => ({
      id: c.id,
      author: c.author,
      content: c.content,
      createdAt: c.created_at,
    })),
  }
}

export async function fetchTickets(): Promise<Ticket[]> {
  const data = await apiFetch<ApiTicket[]>("/tickets")
  return data.map(mapTicket)
}

export async function fetchTicket(ticketId: string): Promise<Ticket> {
  const data = await apiFetch<ApiTicket>(`/tickets/${ticketId}`)
  return mapTicket(data)
}

export async function fetchTicketStats(): Promise<{
  total: number
  open: number
  inProgress: number
  pending: number
  resolved: number
  closed: number
  critical: number
  resolutionRate: number
  avgResolutionDays: number
}> {
  const data = await apiFetch<{
    total: number
    open: number
    in_progress: number
    pending: number
    resolved: number
    closed: number
    critical: number
    resolution_rate: number
    avg_resolution_days: number
  }>("/tickets/stats")
  return {
    total: data.total,
    open: data.open,
    inProgress: data.in_progress,
    pending: data.pending,
    resolved: data.resolved,
    closed: data.closed,
    critical: data.critical,
    resolutionRate: data.resolution_rate,
    avgResolutionDays: data.avg_resolution_days,
  }
}

export async function fetchTicketInsights(): Promise<{
  weekly: Array<{ week: string; opened: number; closed: number; pending: number }>
  ticket_type: Array<{ ticket_type: string; count: number }>
  category: Array<{ category: string; count: number }>
  priority: Array<{ priority: string; count: number; fill: string }>
  problems: Array<{
    title: string
    occurrences: number
    active_count: number
    problem_count: number
    highest_priority: "critical" | "high" | "medium" | "low"
    latest_ticket_id: string
    latest_updated_at: string
    ticket_ids: string[]
    problem_triggered: boolean
    trigger_reasons: string[]
    recent_occurrences_7d: number
    same_day_peak: number
    same_day_peak_date: string | null
    ai_recommendation: string
    ai_recommendation_confidence?: number
  }>
  operational: {
    critical_recent: Array<{
      id: string
      title: string
      priority: "critical" | "high" | "medium" | "low"
      status:
        | "open"
        | "in-progress"
        | "waiting-for-customer"
        | "waiting-for-support-vendor"
        | "pending"
        | "resolved"
        | "closed"
      ticket_type: TicketType
      category: TicketCategory
      assignee: string
      created_at: string
      updated_at: string
      age_days: number
      inactive_days: number
    }>
    stale_active: Array<{
      id: string
      title: string
      priority: "critical" | "high" | "medium" | "low"
      status:
        | "open"
        | "in-progress"
        | "waiting-for-customer"
        | "waiting-for-support-vendor"
        | "pending"
        | "resolved"
        | "closed"
      ticket_type: TicketType
      category: TicketCategory
      assignee: string
      created_at: string
      updated_at: string
      age_days: number
      inactive_days: number
    }>
    recent_days: number
    stale_days: number
    counts: {
      critical_recent: number
      stale_active: number
    }
  }
  problem_management?: {
    total: number
    open: number
    investigating: number
    known_error: number
    resolved: number
    closed: number
    active_total: number
    top: Array<{
      id: string
      title: string
      status: string
      occurrences_count: number
      active_count: number
      category: string
      latest_ticket_id: string
      latest_updated_at: string
      ticket_ids: string[]
      highest_priority: "critical" | "high" | "medium" | "low"
      problem_count: number
      problem_triggered: boolean
      trigger_reasons: string[]
      recent_occurrences_7d: number
      same_day_peak: number
      same_day_peak_date: string | null
      ai_recommendation: string
      ai_recommendation_confidence?: number
    }>
  }
  performance: TicketPerformancePayload
}> {
  return apiFetch("/tickets/insights")
}

type PerformanceFilters = {
  scope?: "all" | "before" | "after"
  dateFrom?: string
  dateTo?: string
  category?: TicketCategory
  assignee?: string
}

export async function fetchTicketPerformance(filters: PerformanceFilters = {}): Promise<TicketPerformancePayload> {
  const params = new URLSearchParams()
  if (filters.scope) params.set("scope", filters.scope)
  if (filters.dateFrom) params.set("date_from", filters.dateFrom)
  if (filters.dateTo) params.set("date_to", filters.dateTo)
  if (filters.category) params.set("category", filters.category)
  if (filters.assignee) params.set("assignee", filters.assignee)
  const query = params.toString()
  const path = query ? `/tickets/performance?${query}` : "/tickets/performance"
  return apiFetch<TicketPerformancePayload>(path)
}

export type TicketAIRecommendationsPayload = {
  priority: TicketPriority
  ticketType: TicketType
  classifierTicketType: TicketType | null
  category: TicketCategory
  classificationConfidence: number
  recommendations: Array<{ text: string; confidence: number }>
  recommendationsEmbedding: Array<{ text: string; confidence: number }>
  recommendationsLlm: Array<{ text: string; confidence: number }>
  recommendationMode: string
  similarityFound: boolean
  assignee: string | null
  sourceLabel: string
  resolutionConfidence: number
  confidenceBand: string
  confidenceLabel: string
  recommendedAction: string | null
  reasoning: string | null
  probableRootCause: string | null
  rootCause: string | null
  supportingContext: string | null
  whyThisMatches: string[]
  tentative: boolean
  actionRelevanceScore: number
  filteredWeakMatch: boolean
  mode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  displayMode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  matchSummary: string | null
  nextBestActions: string[]
  validationSteps: string[]
  baseRecommendedAction: string | null
  baseNextBestActions: string[]
  baseValidationSteps: string[]
  actionRefinementSource: string | null
  routingDecisionSource: string | null
  serviceRequestProfileDetected: boolean
  serviceRequestProfileConfidence: number
  crossCheckConflictFlag: boolean
  crossCheckSummary: string | null
  incidentCluster: {
    count: number
    windowHours: number
    summary: string
  } | null
  impactSummary: string | null
  evidenceSources: Array<{
    evidenceType: string
    reference: string
    excerpt: string | null
    sourceId?: string | null
    title?: string | null
    relevance?: number
    whyRelevant?: string | null
  }>
  currentFeedback: RecommendationCurrentFeedback | null
  feedbackSummary: RecommendationFeedbackSummary | null
  resolutionAdvice: {
    recommendedAction: string | null
    reasoning: string
    probableRootCause: string | null
    rootCause: string | null
    supportingContext: string | null
    whyThisMatches: string[]
    evidenceSources: Array<{
      evidenceType: string
      reference: string
      excerpt: string | null
      sourceId?: string | null
      title?: string | null
      relevance?: number
      whyRelevant?: string | null
    }>
    tentative: boolean
    confidence: number
    confidenceBand: string
    confidenceLabel: string
    sourceLabel: string
    recommendationMode: string
    actionRelevanceScore: number
    filteredWeakMatch: boolean
    mode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
    displayMode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
    matchSummary: string | null
    nextBestActions: string[]
    baseRecommendedAction: string | null
    baseNextBestActions: string[]
    baseValidationSteps: string[]
    actionRefinementSource: string | null
    incidentCluster: {
      count: number
      windowHours: number
      summary: string
    } | null
    impactSummary: string | null
    workflowSteps: string[]
    validationSteps: string[]
    fallbackAction: string | null
    missingInformation: string[]
    responseText: string
    llmGeneralAdvisory: {
      probableCauses: string[]
      suggestedChecks: string[]
      escalationHint: string | null
      knowledgeSource?: string
      confidence?: number
      language?: string
    } | null
  } | null
}

export type TicketAiSlaRiskLatest = {
  ticketId: string
  riskScore: number
  band: "low" | "medium" | "high" | "critical"
  confidence: number
  reasoning: string[]
  recommendedActions: string[]
  advisoryMode: "deterministic" | "hybrid" | "ai"
  evaluatedAt: string
  remainingSeconds: number
  suggestedPriority: string | null
  slaElapsedRatio: number
  timeConsumedPercent: number
  modelVersion: string
  decisionSource: string
  createdAt: string
} | null

export type TicketSlaAdvisory = {
  ticketId: string
  remainingSeconds: number
  isBreached: boolean
  aiRiskScore: number
  ragAdviceText: string
}

export type SimilarTicket = {
  id: string
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  ticketType: TicketType
  category: TicketCategory
  assignee: string
  reporter: string
  createdAt: string
  updatedAt: string
  similarityScore: number
}

export type TicketHistoryChange = {
  field: string
  before?: unknown
  after?: unknown
}

export type TicketHistoryEvent = {
  id: string
  ticketId: string
  eventType: string
  action?: string | null
  actor: string
  actorId?: string | null
  actorRole?: string | null
  commentAdded: boolean
  commentId?: string | null
  createdAt: string
  changes: TicketHistoryChange[]
}

const ticketAIRecommendationsCache = new Map<string, TicketAIRecommendationsPayload>()

function isActionableRecommendation(text: string): boolean {
  const normalized = String(text || "").trim()
  if (!normalized) return false
  const lower = normalized.toLowerCase()
  if (lower.endsWith(":")) return false
  return !(
    lower.startsWith("voici ") ||
    lower.startsWith("here are ") ||
    lower.startsWith("recommended actions") ||
    lower.startsWith("actions:") ||
    lower.startsWith("solutions recommandees") ||
    lower.startsWith("recommended solutions") ||
    lower.startsWith("solution rapide")
  )
}

function cleanRecommendationText(text: string): string {
  return String(text || "")
    .replace(/\*\*/g, "")
    .replace(/\s+/g, " ")
    .trim()
}

function mapScoredRecommendations(
  scored: Array<{ text: string; confidence: number }> | undefined,
  fallback: string[] | undefined,
  startConfidence = 86,
): Array<{ text: string; confidence: number }> {
  if (Array.isArray(scored) && scored.length > 0) {
    return scored
      .map((item) => ({
        text: cleanRecommendationText(item.text),
        confidence: Number.isFinite(item.confidence)
          ? Math.max(0, Math.min(100, Number(item.confidence)))
          : 0,
      }))
      .filter((item) => item.text.length > 0 && isActionableRecommendation(item.text))
  }
  return (Array.isArray(fallback) ? fallback : [])
    .map((text, index) => ({
      text: cleanRecommendationText(String(text || "")),
      confidence: Math.max(55, startConfidence - index * 7),
    }))
    .filter((item) => item.text.length > 0 && isActionableRecommendation(item.text))
}

export async function fetchTicketAIRecommendations(
  ticket: { id: string; title: string; description: string },
  options: { force?: boolean; locale?: "fr" | "en" } = {},
): Promise<TicketAIRecommendationsPayload> {
  const { force = false, locale = "fr" } = options
  const cacheKey = `${ticket.id}:${locale}`
  if (!force) {
    const cached = ticketAIRecommendationsCache.get(cacheKey)
    if (cached) return cached
  }

  const data = await apiFetch<{
    priority: TicketPriority
    ticket_type: TicketType
    classifier_ticket_type?: TicketType | null
    category: TicketCategory
    classification_confidence?: number
    recommendations: string[]
    recommendations_scored?: Array<{ text: string; confidence: number }>
    recommendations_embedding?: string[]
    recommendations_embedding_scored?: Array<{ text: string; confidence: number }>
    recommendations_llm?: string[]
    recommendations_llm_scored?: Array<{ text: string; confidence: number }>
    recommendation_mode?: string
    similarity_found?: boolean
    assignee?: string | null
    source_label?: string
    resolution_confidence?: number
    confidence_band?: string
    confidence_label?: string
    recommended_action?: string | null
    reasoning?: string | null
    probable_root_cause?: string | null
    root_cause?: string | null
    supporting_context?: string | null
    why_this_matches?: string[]
    tentative?: boolean
    match_summary?: string | null
    action_relevance_score?: number
    filtered_weak_match?: boolean
    mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
    display_mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
    next_best_actions?: string[]
    validation_steps?: string[]
    base_recommended_action?: string | null
    base_next_best_actions?: string[]
    base_validation_steps?: string[]
    action_refinement_source?: string | null
    routing_decision_source?: string | null
    service_request_profile_detected?: boolean
    service_request_profile_confidence?: number
    cross_check_conflict_flag?: boolean
    cross_check_summary?: string | null
    incident_cluster?: {
      count?: number
      window_hours?: number
      summary?: string
    } | null
    impact_summary?: string | null
    current_feedback?: {
      feedback_type: "useful" | "not_relevant" | "applied" | "rejected"
      created_at: string
      updated_at: string
    } | null
    feedback_summary?: {
      total_feedback?: number
      useful_count?: number
      not_relevant_count?: number
      applied_count?: number
      rejected_count?: number
      usefulness_rate?: number
      applied_rate?: number
      rejection_rate?: number
    } | null
    evidence_sources?: Array<{
      evidence_type: string
      reference: string
      excerpt?: string | null
      source_id?: string | null
      title?: string | null
      relevance?: number
      why_relevant?: string | null
    }>
    resolution_advice?: {
      recommended_action?: string | null
      reasoning: string
      probable_root_cause?: string | null
      root_cause?: string | null
      supporting_context?: string | null
      why_this_matches?: string[]
      evidence_sources?: Array<{
        evidence_type: string
        reference: string
        excerpt?: string | null
        source_id?: string | null
        title?: string | null
        relevance?: number
        why_relevant?: string | null
      }>
      tentative?: boolean
      confidence?: number
      confidence_band?: string
      confidence_label?: string
      source_label?: string
      recommendation_mode?: string
      action_relevance_score?: number
      filtered_weak_match?: boolean
      mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
      display_mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
      match_summary?: string | null
      next_best_actions?: string[]
      incident_cluster?: {
        count?: number
        window_hours?: number
        summary?: string
      } | null
      impact_summary?: string | null
      workflow_steps?: string[]
      validation_steps?: string[]
      base_recommended_action?: string | null
      base_next_best_actions?: string[]
      base_validation_steps?: string[]
      action_refinement_source?: string | null
      fallback_action?: string | null
      missing_information?: string[]
      response_text: string
      llm_general_advisory?: {
        probable_causes?: string[]
        suggested_checks?: string[]
        escalation_hint?: string | null
        knowledge_source?: string
        confidence?: number
        language?: string
      } | null
    } | null
  }>("/ai/classify", {
    method: "POST",
    body: JSON.stringify({
      ticket_id: ticket.id,
      title: ticket.title,
      description: ticket.description,
      locale,
    }),
  })

  const payload: TicketAIRecommendationsPayload = {
    priority: data.priority,
    ticketType: data.ticket_type,
    classifierTicketType: data.classifier_ticket_type ?? null,
    category: data.category,
    classificationConfidence: Number.isFinite(data.classification_confidence)
      ? Math.max(0, Math.min(100, Number(data.classification_confidence)))
      : 0,
    recommendations: mapScoredRecommendations(data.recommendations_scored, data.recommendations, 86),
    recommendationsEmbedding: mapScoredRecommendations(
      data.recommendations_embedding_scored,
      data.recommendations_embedding,
      90,
    ),
    recommendationsLlm: mapScoredRecommendations(data.recommendations_llm_scored, data.recommendations_llm, 82),
    recommendationMode: data.recommendation_mode || "fallback_rules",
    similarityFound: Boolean(data.similarity_found),
    assignee: data.assignee ?? null,
    sourceLabel: data.source_label || "fallback_rules",
    resolutionConfidence: Number.isFinite(data.resolution_confidence)
      ? Math.max(0, Math.min(1, Number(data.resolution_confidence)))
      : 0,
    confidenceBand: String(data.confidence_band || "low"),
    confidenceLabel: String(data.confidence_label || data.confidence_band || "low"),
    recommendedAction: data.recommended_action ?? null,
    reasoning: data.reasoning ?? null,
    probableRootCause: data.probable_root_cause ?? null,
    rootCause: data.root_cause ?? data.probable_root_cause ?? null,
    supportingContext: data.supporting_context ?? null,
    whyThisMatches: Array.isArray(data.why_this_matches)
      ? data.why_this_matches.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    tentative: Boolean(data.tentative),
    actionRelevanceScore: Number.isFinite(data.action_relevance_score)
      ? Math.max(0, Math.min(1, Number(data.action_relevance_score)))
      : 0,
    filteredWeakMatch: Boolean(data.filtered_weak_match),
    // display_mode is canonical.  mode is deprecated — fall back to it only
    // when display_mode is absent, and log a console.warn so the debt is
    // visible in devtools.  Remove the fallback when mode is removed from the
    // backend schema.
    displayMode: (() => {
      if (data.display_mode) return data.display_mode
      if (data.mode) {
        console.warn(
          "[tickets-api] Falling back to deprecated `mode` field — `display_mode` missing from AI recommendations response.",
        )
        return data.mode
      }
      return data.recommended_action ? "evidence_action" : "no_strong_match"
    })(),
    mode: data.mode || data.display_mode || (data.recommended_action ? "evidence_action" : "no_strong_match"),
    matchSummary: data.match_summary ?? null,
    nextBestActions: Array.isArray(data.next_best_actions)
      ? data.next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    validationSteps: Array.isArray(data.validation_steps)
      ? data.validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    baseRecommendedAction: data.base_recommended_action ?? null,
    baseNextBestActions: Array.isArray(data.base_next_best_actions)
      ? data.base_next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    baseValidationSteps: Array.isArray(data.base_validation_steps)
      ? data.base_validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    actionRefinementSource: data.action_refinement_source ?? null,
    routingDecisionSource: data.routing_decision_source ?? null,
    serviceRequestProfileDetected: Boolean(data.service_request_profile_detected),
    serviceRequestProfileConfidence: Number.isFinite(data.service_request_profile_confidence)
      ? Math.max(0, Math.min(1, Number(data.service_request_profile_confidence)))
      : 0,
    crossCheckConflictFlag: Boolean(data.cross_check_conflict_flag),
    crossCheckSummary: data.cross_check_summary ?? null,
    incidentCluster:
      data.incident_cluster && data.incident_cluster.summary
        ? {
            count: Number.isFinite(data.incident_cluster.count) ? Math.max(0, Number(data.incident_cluster.count)) : 0,
            windowHours: Number.isFinite(data.incident_cluster.window_hours)
              ? Math.max(1, Number(data.incident_cluster.window_hours))
              : 24,
            summary: String(data.incident_cluster.summary || "").trim(),
          }
        : null,
    impactSummary: data.impact_summary ?? null,
    currentFeedback: data.current_feedback
      ? {
          feedbackType: data.current_feedback.feedback_type,
          createdAt: data.current_feedback.created_at,
          updatedAt: data.current_feedback.updated_at,
        }
      : null,
    feedbackSummary: data.feedback_summary
      ? {
          totalFeedback: Number(data.feedback_summary.total_feedback || 0),
          usefulCount: Number(data.feedback_summary.useful_count || 0),
          notRelevantCount: Number(data.feedback_summary.not_relevant_count || 0),
          appliedCount: Number(data.feedback_summary.applied_count || 0),
          rejectedCount: Number(data.feedback_summary.rejected_count || 0),
          usefulnessRate: Number.isFinite(data.feedback_summary.usefulness_rate)
            ? Math.max(0, Math.min(1, Number(data.feedback_summary.usefulness_rate)))
            : 0,
          appliedRate: Number.isFinite(data.feedback_summary.applied_rate)
            ? Math.max(0, Math.min(1, Number(data.feedback_summary.applied_rate)))
            : 0,
          rejectionRate: Number.isFinite(data.feedback_summary.rejection_rate)
            ? Math.max(0, Math.min(1, Number(data.feedback_summary.rejection_rate)))
            : 0,
        }
      : null,
    evidenceSources: (data.evidence_sources || []).map((item) => ({
      evidenceType: item.evidence_type,
      reference: item.reference,
      excerpt: item.excerpt ?? null,
      sourceId: item.source_id ?? null,
      title: item.title ?? null,
      relevance: Number.isFinite(item.relevance) ? Math.max(0, Math.min(1, Number(item.relevance))) : 0,
      whyRelevant: item.why_relevant ?? null,
    })),
    resolutionAdvice: data.resolution_advice
      ? {
          recommendedAction: data.resolution_advice.recommended_action ?? null,
          reasoning: data.resolution_advice.reasoning,
          probableRootCause: data.resolution_advice.probable_root_cause ?? null,
          rootCause: data.resolution_advice.root_cause ?? data.resolution_advice.probable_root_cause ?? null,
          supportingContext: data.resolution_advice.supporting_context ?? null,
          whyThisMatches: Array.isArray(data.resolution_advice.why_this_matches)
            ? data.resolution_advice.why_this_matches.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          evidenceSources: (data.resolution_advice.evidence_sources || []).map((item) => ({
            evidenceType: item.evidence_type,
            reference: item.reference,
            excerpt: item.excerpt ?? null,
            sourceId: item.source_id ?? null,
            title: item.title ?? null,
            relevance: Number.isFinite(item.relevance) ? Math.max(0, Math.min(1, Number(item.relevance))) : 0,
            whyRelevant: item.why_relevant ?? null,
          })),
          tentative: Boolean(data.resolution_advice.tentative),
          confidence: Number.isFinite(data.resolution_advice.confidence)
            ? Math.max(0, Math.min(1, Number(data.resolution_advice.confidence)))
            : 0,
          confidenceBand: String(data.resolution_advice.confidence_band || "low"),
          confidenceLabel: String(data.resolution_advice.confidence_label || data.resolution_advice.confidence_band || "low"),
          sourceLabel: data.resolution_advice.source_label || "fallback_rules",
          recommendationMode: data.resolution_advice.recommendation_mode || "fallback_rules",
          actionRelevanceScore: Number.isFinite(data.resolution_advice.action_relevance_score)
            ? Math.max(0, Math.min(1, Number(data.resolution_advice.action_relevance_score)))
            : 0,
          filteredWeakMatch: Boolean(data.resolution_advice.filtered_weak_match),
          // display_mode is canonical.  mode is deprecated — fall back to it
          // only when display_mode is absent, and warn in devtools.
          displayMode: (() => {
            const ra = data.resolution_advice
            if (ra.display_mode) return ra.display_mode
            if (ra.mode) {
              console.warn(
                "[tickets-api] Falling back to deprecated `mode` field on resolutionAdvice — `display_mode` missing.",
              )
              return ra.mode
            }
            return ra.recommended_action ? "evidence_action" : "no_strong_match"
          })(),
          mode:
            data.resolution_advice.mode ||
            data.resolution_advice.display_mode ||
            (data.resolution_advice.recommended_action ? "evidence_action" : "no_strong_match"),
          matchSummary: data.resolution_advice.match_summary ?? null,
          nextBestActions: Array.isArray(data.resolution_advice.next_best_actions)
            ? data.resolution_advice.next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          baseRecommendedAction: data.resolution_advice.base_recommended_action ?? null,
          baseNextBestActions: Array.isArray(data.resolution_advice.base_next_best_actions)
            ? data.resolution_advice.base_next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          baseValidationSteps: Array.isArray(data.resolution_advice.base_validation_steps)
            ? data.resolution_advice.base_validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          actionRefinementSource: data.resolution_advice.action_refinement_source ?? null,
          incidentCluster:
            data.resolution_advice.incident_cluster && data.resolution_advice.incident_cluster.summary
              ? {
                  count: Number.isFinite(data.resolution_advice.incident_cluster.count)
                    ? Math.max(0, Number(data.resolution_advice.incident_cluster.count))
                    : 0,
                  windowHours: Number.isFinite(data.resolution_advice.incident_cluster.window_hours)
                    ? Math.max(1, Number(data.resolution_advice.incident_cluster.window_hours))
                    : 24,
                  summary: String(data.resolution_advice.incident_cluster.summary || "").trim(),
                }
              : null,
          impactSummary: data.resolution_advice.impact_summary ?? null,
          workflowSteps: Array.isArray(data.resolution_advice.workflow_steps)
            ? data.resolution_advice.workflow_steps.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          validationSteps: Array.isArray(data.resolution_advice.validation_steps)
            ? data.resolution_advice.validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          fallbackAction: data.resolution_advice.fallback_action ?? null,
          missingInformation: Array.isArray(data.resolution_advice.missing_information)
            ? data.resolution_advice.missing_information.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          responseText: data.resolution_advice.response_text,
          llmGeneralAdvisory:
            data.resolution_advice.llm_general_advisory
              ? {
                  probableCauses: Array.isArray(data.resolution_advice.llm_general_advisory.probable_causes)
                    ? data.resolution_advice.llm_general_advisory.probable_causes.map((item) => String(item || "").trim()).filter(Boolean)
                    : [],
                  suggestedChecks: Array.isArray(data.resolution_advice.llm_general_advisory.suggested_checks)
                    ? data.resolution_advice.llm_general_advisory.suggested_checks.map((item) => String(item || "").trim()).filter(Boolean)
                    : [],
                  escalationHint: data.resolution_advice.llm_general_advisory.escalation_hint ?? null,
                  knowledgeSource: data.resolution_advice.llm_general_advisory.knowledge_source,
                  confidence: Number.isFinite(data.resolution_advice.llm_general_advisory.confidence)
                    ? Math.max(0, Math.min(1, Number(data.resolution_advice.llm_general_advisory.confidence)))
                    : undefined,
                  language: data.resolution_advice.llm_general_advisory.language,
                }
              : null,
        }
      : null,
  }
  ticketAIRecommendationsCache.set(cacheKey, payload)
  return payload
}

export async function fetchTicketAiSlaRiskLatest(ticketId: string): Promise<TicketAiSlaRiskLatest> {
  const data = await apiFetch<{
    ticket_id: string
    risk_score?: number | null
    band?: "low" | "medium" | "high" | "critical"
    confidence?: number | null
    reasoning?: string[]
    recommended_actions?: string[]
    advisory_mode?: "deterministic" | "hybrid" | "ai"
    evaluated_at?: string | null
    remaining_seconds?: number | null
    suggested_priority?: string | null
    sla_elapsed_ratio?: number | null
    time_consumed_percent?: number | null
    model_version?: string
    decision_source?: string
    created_at?: string | null
  }>(`/sla/ticket/${ticketId}/ai-risk/latest`)

  if (!data?.ticket_id) {
    return null
  }

  return {
    ticketId: data.ticket_id,
    riskScore: Number.isFinite(data.risk_score) ? Math.max(0, Math.min(1, Number(data.risk_score))) : 0,
    band: data.band || "low",
    confidence: Number.isFinite(data.confidence) ? Math.max(0, Math.min(1, Number(data.confidence))) : 0,
    reasoning: Array.isArray(data.reasoning) ? data.reasoning.map((item) => String(item || "").trim()).filter(Boolean) : [],
    recommendedActions: Array.isArray(data.recommended_actions)
      ? data.recommended_actions.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    advisoryMode: data.advisory_mode || "deterministic",
    evaluatedAt: data.evaluated_at || data.created_at || new Date().toISOString(),
    remainingSeconds: Number.isFinite(data.remaining_seconds) ? Math.max(0, Number(data.remaining_seconds)) : 0,
    suggestedPriority: data.suggested_priority ?? null,
    slaElapsedRatio: Number.isFinite(data.sla_elapsed_ratio)
      ? Math.max(0, Math.min(1, Number(data.sla_elapsed_ratio)))
      : 0,
    timeConsumedPercent: Number.isFinite(data.time_consumed_percent)
      ? Math.max(0, Math.min(100, Number(data.time_consumed_percent)))
      : 0,
    modelVersion: data.model_version || "",
    decisionSource: data.decision_source || "",
    createdAt: data.created_at || data.evaluated_at || new Date().toISOString(),
  }
}

export async function fetchTicketSlaAdvisory(ticketId: string): Promise<TicketSlaAdvisory | null> {
  const data = await apiFetch<{
    ticket_id: string
    remaining_seconds: number
    is_breached: boolean
    ai_risk_score: number
    rag_advice_text: string
  }>(`/sla/ticket/${ticketId}/advisory`)

  if (!data?.ticket_id) {
    return null
  }

  return {
    ticketId: data.ticket_id,
    remainingSeconds: Number.isFinite(data.remaining_seconds) ? Number(data.remaining_seconds) : 0,
    isBreached: Boolean(data.is_breached),
    aiRiskScore: Number.isFinite(data.ai_risk_score) ? Number(data.ai_risk_score) : 0,
    ragAdviceText: String(data.rag_advice_text || "").trim(),
  }
}

export async function fetchSimilarTickets(
  ticketId: string,
  options: { limit?: number; minScore?: number } = {},
): Promise<SimilarTicket[]> {
  const params = new URLSearchParams()
  if (Number.isFinite(options.limit)) {
    params.set("limit", String(options.limit))
  }
  if (Number.isFinite(options.minScore)) {
    params.set("min_score", String(options.minScore))
  }
  const query = params.toString()
  const path = query ? `/tickets/${ticketId}/similar?${query}` : `/tickets/${ticketId}/similar`

  const data = await apiFetch<{
    ticket_id: string
    matches: Array<{
      id: string
      title: string
      description: string
      status: TicketStatus
      priority: TicketPriority
      ticket_type: TicketType
      category: TicketCategory
      assignee: string
      reporter: string
      created_at: string
      updated_at: string
      similarity_score: number
    }>
  }>(path)

  return data.matches.map((item) => ({
    id: item.id,
    title: item.title,
    description: item.description,
    status: item.status,
    priority: item.priority,
    ticketType: item.ticket_type,
    category: item.category,
    assignee: item.assignee,
    reporter: item.reporter,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    similarityScore: item.similarity_score,
  }))
}

function mapHistoryEvent(item: ApiTicketHistoryEvent): TicketHistoryEvent {
  return {
    id: item.id,
    ticketId: item.ticket_id,
    eventType: item.event_type,
    action: item.action ?? null,
    actor: item.actor,
    actorId: item.actor_id ?? null,
    actorRole: item.actor_role ?? null,
    commentAdded: Boolean(item.comment_added),
    commentId: item.comment_id ?? null,
    createdAt: item.created_at,
    changes: (item.changes || []).map((change) => ({
      field: change.field,
      before: change.before,
      after: change.after,
    })),
  }
}

export async function fetchTicketHistory(options: { ticketId?: string; limit?: number } = {}): Promise<TicketHistoryEvent[]> {
  const params = new URLSearchParams()
  if (Number.isFinite(options.limit)) {
    params.set("limit", String(options.limit))
  }
  const query = params.toString()
  const basePath = options.ticketId ? `/tickets/${options.ticketId}/history` : "/tickets/history"
  const path = query ? `${basePath}?${query}` : basePath
  const data = await apiFetch<ApiTicketHistoryEvent[]>(path)
  return data.map(mapHistoryEvent)
}

export interface SummaryResult {
  summary: string
  similar_ticket_count: number
  used_ticket_ids: string[]
  generated_at: string
  is_cached: boolean
  language: string
}

export async function fetchTicketSummary(
  ticketId: string,
  forceRegenerate = false,
  language = "fr",
): Promise<SummaryResult> {
  const params = new URLSearchParams()
  if (forceRegenerate) params.set("force_regenerate", "true")
  params.set("language", language)
  const path = `/tickets/${ticketId}/summary?${params.toString()}`
  return apiFetch<SummaryResult>(path)
}

/**
 * AI-suggested resolution text for a ticket being closed.
 */
export interface ResolutionSuggestionResult {
  suggestion: string;
  confidence: number;
  based_on_comments: boolean;
  based_on_feedback: boolean;
}

/**
 * Fetch an AI-suggested resolution text for a ticket being closed.
 * Call when the agent opens the resolve dialog and the resolution is empty.
 *
 * @param ticketId - ID of the ticket being resolved
 * @returns ResolutionSuggestionResult
 */
export async function fetchResolutionSuggestion(
  ticketId: string
): Promise<ResolutionSuggestionResult> {
  try {
    const res = await fetch(`/api/tickets/${ticketId}/resolution-suggestion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return { suggestion: "", confidence: 0, based_on_comments: false, based_on_feedback: false };
    return res.json();
  } catch {
    return { suggestion: "", confidence: 0, based_on_comments: false, based_on_feedback: false };
  }
}
