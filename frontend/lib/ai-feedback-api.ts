import { apiFetch } from "@/lib/api"

export type RecommendationFeedbackType = "useful" | "not_relevant" | "applied" | "rejected"
export type RecommendationFeedbackSurface = "ticket_detail" | "recommendations_page" | "ticket_chatbot"

export type RecommendationCurrentFeedback = {
  feedbackType: RecommendationFeedbackType
  createdAt: string
  updatedAt: string
}

export type RecommendationFeedbackSummary = {
  totalFeedback: number
  usefulCount: number
  notRelevantCount: number
  appliedCount: number
  rejectedCount: number
  usefulnessRate: number
  appliedRate: number
  rejectionRate: number
}

export type RecommendationFeedbackAnalytics = RecommendationFeedbackSummary & {
  bySurface: Record<string, RecommendationFeedbackSummary>
  byDisplayMode: Record<string, RecommendationFeedbackSummary>
  byConfidenceBand: Record<string, RecommendationFeedbackSummary>
  byRecommendationMode: Record<string, RecommendationFeedbackSummary>
  bySourceLabel: Record<string, RecommendationFeedbackSummary>
}

export type RecommendationFeedbackResponse = {
  status: string
  ticketId: string | null
  recommendationId: string | null
  sourceSurface: RecommendationFeedbackSurface | null
  currentFeedback: RecommendationCurrentFeedback | null
  feedbackSummary: RecommendationFeedbackSummary | null
}

type ApiRecommendationFeedbackState = {
  feedback_type: RecommendationFeedbackType
  created_at: string
  updated_at: string
}

type ApiRecommendationFeedbackSummary = {
  total_feedback: number
  useful_count: number
  not_relevant_count: number
  applied_count: number
  rejected_count: number
  usefulness_rate: number
  applied_rate: number
  rejection_rate: number
}

type ApiRecommendationFeedbackAnalytics = ApiRecommendationFeedbackSummary & {
  by_surface?: Record<string, ApiRecommendationFeedbackSummary>
  by_display_mode?: Record<string, ApiRecommendationFeedbackSummary>
  by_confidence_band?: Record<string, ApiRecommendationFeedbackSummary>
  by_recommendation_mode?: Record<string, ApiRecommendationFeedbackSummary>
  by_source_label?: Record<string, ApiRecommendationFeedbackSummary>
}

type ApiRecommendationFeedbackResponse = {
  status: string
  ticket_id?: string | null
  recommendation_id?: string | null
  source_surface?: RecommendationFeedbackSurface | null
  current_feedback?: ApiRecommendationFeedbackState | null
  feedback_summary?: ApiRecommendationFeedbackSummary | null
}

export type TicketDetailFeedbackPayload = {
  ticketId: string
  feedbackType: RecommendationFeedbackType
  answerType?: "resolution_advice" | "cause_analysis" | "suggestion_resolution_advice" | null
  recommendedAction?: string | null
  displayMode?: string | null
  confidence?: number | null
  reasoning?: string | null
  matchSummary?: string | null
  evidenceCount?: number | null
  metadata?: Record<string, string | number | boolean | null>
}

export type RecommendationPageFeedbackPayload = {
  ticketId?: string | null
  feedbackType: RecommendationFeedbackType
  recommendedAction?: string | null
  displayMode?: string | null
  confidence?: number | null
  reasoning?: string | null
  matchSummary?: string | null
  evidenceCount?: number | null
  metadata?: Record<string, string | number | boolean | null>
}

function clampUnit(value: number | null | undefined): number | undefined {
  if (!Number.isFinite(value)) {
    return undefined
  }
  return Math.max(0, Math.min(1, Number(value)))
}

function mapFeedbackResponse(data: ApiRecommendationFeedbackResponse): RecommendationFeedbackResponse {
  return {
    status: data.status,
    ticketId: data.ticket_id ?? null,
    recommendationId: data.recommendation_id ?? null,
    sourceSurface: data.source_surface ?? null,
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
          usefulnessRate: clampUnit(data.feedback_summary.usefulness_rate) ?? 0,
          appliedRate: clampUnit(data.feedback_summary.applied_rate) ?? 0,
          rejectionRate: clampUnit(data.feedback_summary.rejection_rate) ?? 0,
        }
      : null,
  }
}

function mapFeedbackSummary(data?: ApiRecommendationFeedbackSummary | null): RecommendationFeedbackSummary {
  return {
    totalFeedback: Number(data?.total_feedback || 0),
    usefulCount: Number(data?.useful_count || 0),
    notRelevantCount: Number(data?.not_relevant_count || 0),
    appliedCount: Number(data?.applied_count || 0),
    rejectedCount: Number(data?.rejected_count || 0),
    usefulnessRate: clampUnit(data?.usefulness_rate) ?? 0,
    appliedRate: clampUnit(data?.applied_rate) ?? 0,
    rejectionRate: clampUnit(data?.rejection_rate) ?? 0,
  }
}

function mapFeedbackSummaryRecord(
  value?: Record<string, ApiRecommendationFeedbackSummary> | null,
): Record<string, RecommendationFeedbackSummary> {
  if (!value || typeof value !== "object") {
    return {}
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, summary]) => [key, mapFeedbackSummary(summary)])
  )
}

export async function submitTicketRecommendationFeedback(
  payload: TicketDetailFeedbackPayload,
): Promise<RecommendationFeedbackResponse> {
  const data = await apiFetch<ApiRecommendationFeedbackResponse>("/ai/feedback", {
    method: "POST",
    body: JSON.stringify({
      ticket_id: payload.ticketId,
      feedback_type: payload.feedbackType,
      source_surface: "ticket_detail",
      recommended_action: payload.recommendedAction ?? null,
      display_mode: payload.displayMode ?? null,
      confidence: clampUnit(payload.confidence),
      reasoning: payload.reasoning ?? null,
      match_summary: payload.matchSummary ?? null,
      evidence_count: Number.isFinite(payload.evidenceCount) ? payload.evidenceCount : null,
      metadata: payload.metadata ?? null,
    }),
  })
  return mapFeedbackResponse(data)
}

export async function submitChatTicketRecommendationFeedback(
  payload: TicketDetailFeedbackPayload,
): Promise<RecommendationFeedbackResponse> {
  const data = await apiFetch<ApiRecommendationFeedbackResponse>("/ai/feedback", {
    method: "POST",
    body: JSON.stringify({
      ticket_id: payload.ticketId,
      answer_type: payload.answerType ?? null,
      feedback_type: payload.feedbackType,
      source_surface: "ticket_chatbot",
      recommended_action: payload.recommendedAction ?? null,
      display_mode: payload.displayMode ?? null,
      confidence: clampUnit(payload.confidence),
      reasoning: payload.reasoning ?? null,
      match_summary: payload.matchSummary ?? null,
      evidence_count: Number.isFinite(payload.evidenceCount) ? payload.evidenceCount : null,
      metadata: payload.metadata ?? null,
    }),
  })
  return mapFeedbackResponse(data)
}

export async function submitRecommendationFeedback(
  recommendationId: string,
  payload: RecommendationPageFeedbackPayload,
): Promise<RecommendationFeedbackResponse> {
  const data = await apiFetch<ApiRecommendationFeedbackResponse>(`/recommendations/${encodeURIComponent(recommendationId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      ticket_id: payload.ticketId ?? null,
      feedback_type: payload.feedbackType,
      recommended_action: payload.recommendedAction ?? null,
      display_mode: payload.displayMode ?? null,
      confidence: clampUnit(payload.confidence),
      reasoning: payload.reasoning ?? null,
      match_summary: payload.matchSummary ?? null,
      evidence_count: Number.isFinite(payload.evidenceCount) ? payload.evidenceCount : null,
      metadata: payload.metadata ?? null,
    }),
  })
  return mapFeedbackResponse(data)
}

export async function fetchRecommendationFeedbackAnalytics(
  sourceSurface?: RecommendationFeedbackSurface | null,
): Promise<RecommendationFeedbackAnalytics> {
  const query = sourceSurface ? `?source_surface=${encodeURIComponent(sourceSurface)}` : ""
  const data = await apiFetch<ApiRecommendationFeedbackAnalytics>(`/ai/feedback/analytics${query}`)
  return {
    ...mapFeedbackSummary(data),
    bySurface: mapFeedbackSummaryRecord(data.by_surface),
    byDisplayMode: mapFeedbackSummaryRecord(data.by_display_mode),
    byConfidenceBand: mapFeedbackSummaryRecord(data.by_confidence_band),
    byRecommendationMode: mapFeedbackSummaryRecord(data.by_recommendation_mode),
    bySourceLabel: mapFeedbackSummaryRecord(data.by_source_label),
  }
}
