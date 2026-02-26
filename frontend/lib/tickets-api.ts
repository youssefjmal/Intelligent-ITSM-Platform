// API helpers for tickets with snake_case to camelCase mapping.

import { apiFetch } from "@/lib/api"
import { type SlaStatus, type Ticket, type TicketCategory, type TicketPriority, type TicketStatus } from "@/lib/ticket-data"

type ApiComment = {
  id: string
  author: string
  content: string
  created_at: string
}

type ApiTicket = {
  id: string
  problem_id?: string | null
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  category: TicketCategory
  assignee: string
  reporter: string
  auto_assignment_applied?: boolean
  auto_priority_applied?: boolean
  assignment_model_version?: string
  priority_model_version?: string
  predicted_priority?: TicketPriority | null
  predicted_category?: TicketCategory | null
  assignment_change_count?: number
  first_action_at?: string | null
  resolved_at?: string | null
  sla_status?: SlaStatus | null
  sla_remaining_minutes?: number | null
  created_at: string
  updated_at: string
  resolution?: string | null
  tags: string[]
  comments: ApiComment[]
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
    category: ticket.category,
    assignee: ticket.assignee,
    reporter: ticket.reporter,
    autoAssignmentApplied: ticket.auto_assignment_applied,
    autoPriorityApplied: ticket.auto_priority_applied,
    assignmentModelVersion: ticket.assignment_model_version,
    priorityModelVersion: ticket.priority_model_version,
    predictedPriority: ticket.predicted_priority || undefined,
    predictedCategory: ticket.predicted_category || undefined,
    assignmentChangeCount: ticket.assignment_change_count,
    firstActionAt: ticket.first_action_at || undefined,
    resolvedAt: ticket.resolved_at || undefined,
    slaStatus: ticket.sla_status ?? null,
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
  category: TicketCategory
  classificationConfidence: number
  recommendations: Array<{ text: string; confidence: number }>
  recommendationsEmbedding: Array<{ text: string; confidence: number }>
  recommendationsLlm: Array<{ text: string; confidence: number }>
  recommendationMode: "embedding" | "llm" | "hybrid"
  similarityFound: boolean
  assignee: string | null
}

export type TicketAiSlaRiskLatest = {
  ticketId: string
  riskScore: number | null
  confidence: number | null
  suggestedPriority: string | null
  reasoningSummary: string
  modelVersion: string
  decisionSource: string
  createdAt: string
} | null

export type SimilarTicket = {
  id: string
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  category: TicketCategory
  assignee: string
  reporter: string
  createdAt: string
  updatedAt: string
  similarityScore: number
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
    category: TicketCategory
    classification_confidence?: number
    recommendations: string[]
    recommendations_scored?: Array<{ text: string; confidence: number }>
    recommendations_embedding?: string[]
    recommendations_embedding_scored?: Array<{ text: string; confidence: number }>
    recommendations_llm?: string[]
    recommendations_llm_scored?: Array<{ text: string; confidence: number }>
    recommendation_mode?: "embedding" | "llm" | "hybrid"
    similarity_found?: boolean
    assignee?: string | null
  }>("/ai/classify", {
    method: "POST",
    body: JSON.stringify({
      title: ticket.title,
      description: ticket.description,
      locale,
    }),
  })

  const payload: TicketAIRecommendationsPayload = {
    priority: data.priority,
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
    recommendationMode: data.recommendation_mode || "llm",
    similarityFound: Boolean(data.similarity_found),
    assignee: data.assignee ?? null,
  }
  ticketAIRecommendationsCache.set(cacheKey, payload)
  return payload
}

export async function fetchTicketAiSlaRiskLatest(ticketId: string): Promise<TicketAiSlaRiskLatest> {
  const data = await apiFetch<{
    ticket_id: string
    latest?: null
    risk_score?: number | null
    confidence?: number | null
    suggested_priority?: string | null
    reasoning_summary?: string
    model_version?: string
    decision_source?: string
    created_at?: string | null
  }>(`/sla/ticket/${ticketId}/ai-risk/latest`)

  if ("latest" in data && data.latest === null) {
    return null
  }
  if (!data.created_at) {
    return null
  }

  return {
    ticketId: data.ticket_id,
    riskScore: data.risk_score ?? null,
    confidence: data.confidence ?? null,
    suggestedPriority: data.suggested_priority ?? null,
    reasoningSummary: data.reasoning_summary || "",
    modelVersion: data.model_version || "",
    decisionSource: data.decision_source || "",
    createdAt: data.created_at,
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
    category: item.category,
    assignee: item.assignee,
    reporter: item.reporter,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    similarityScore: item.similarity_score,
  }))
}
