// API helpers for recommendations with snake_case to camelCase mapping.

import { apiFetch } from "@/lib/api"
import type {
  RecommendationCurrentFeedback,
  RecommendationFeedbackSummary,
} from "@/lib/ai-feedback-api"

export type RecommendationType = "pattern" | "priority" | "solution" | "workflow"
export type RecommendationImpact = "high" | "medium" | "low"

export type RecommendationEvidenceSource = {
  evidenceType: string
  reference: string
  excerpt: string | null
  sourceId?: string | null
  title?: string | null
  relevance?: number
  whyRelevant?: string | null
}

export type Recommendation = {
  id: string
  type: RecommendationType
  entityType: string
  title: string
  description: string
  recommendedAction: string | null
  reasoning: string | null
  relatedTickets: string[]
  confidence: number
  confidenceBand: string
  confidenceLabel: string
  impact: RecommendationImpact
  tentative: boolean
  probableRootCause: string | null
  rootCause: string | null
  supportingContext: string | null
  sourceLabel: string
  recommendationMode: string
  actionRelevanceScore: number
  filteredWeakMatch: boolean
  mode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  displayMode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  matchSummary: string | null
  whyThisMatches: string[]
  nextBestActions: string[]
  validationSteps: string[]
  baseRecommendedAction: string | null
  baseNextBestActions: string[]
  baseValidationSteps: string[]
  actionRefinementSource: string | null
  evidenceSources: RecommendationEvidenceSource[]
  llmGeneralAdvisory: {
    probableCauses: string[]
    suggestedChecks: string[]
    escalationHint: string | null
    knowledgeSource?: string
    confidence?: number
    language?: string
  } | null
  currentUserFeedback: RecommendationCurrentFeedback | null
  feedbackSummary: RecommendationFeedbackSummary | null
  createdAt: string
}

export type SlaStrategies = {
  summary: string
  commonBreachPatterns: string[]
  processImprovements: string[]
  confidence: number
  sources: string[]
}

type ApiRecommendation = {
  id: string
  type: RecommendationType
  entity_type: string
  title: string
  description: string
  recommended_action?: string | null
  reasoning?: string | null
  related_tickets: string[]
  confidence: number
  confidence_band?: string
  confidence_label?: string
  impact: RecommendationImpact
  tentative?: boolean
  probable_root_cause?: string | null
  root_cause?: string | null
  supporting_context?: string | null
  source_label?: string
  recommendation_mode?: string
  action_relevance_score?: number
  filtered_weak_match?: boolean
  mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  display_mode?: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  match_summary?: string | null
  why_this_matches?: string[]
  next_best_actions?: string[]
  validation_steps?: string[]
  base_recommended_action?: string | null
  base_next_best_actions?: string[]
  base_validation_steps?: string[]
  action_refinement_source?: string | null
  evidence_sources?: Array<{
    evidence_type: string
    reference: string
    excerpt?: string | null
    source_id?: string | null
    title?: string | null
    relevance?: number
    why_relevant?: string | null
  }>
  llm_general_advisory?: {
    probable_causes?: string[]
    suggested_checks?: string[]
    escalation_hint?: string | null
    knowledge_source?: string
    confidence?: number
    language?: string
  } | null
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
  created_at: string
}

type ApiSlaStrategies = {
  summary: string
  common_breach_patterns: string[]
  process_improvements: string[]
  confidence: number
  sources: string[]
}

function mapRecommendation(rec: ApiRecommendation): Recommendation {
  return {
    id: rec.id,
    type: rec.type,
    entityType: rec.entity_type,
    title: rec.title,
    description: rec.description,
    recommendedAction: rec.recommended_action ?? null,
    reasoning: rec.reasoning ?? null,
    relatedTickets: rec.related_tickets,
    confidence: Number.isFinite(rec.confidence) ? Math.max(0, Math.min(1, Number(rec.confidence))) : 0,
    confidenceBand: rec.confidence_band || "low",
    confidenceLabel: rec.confidence_label || rec.confidence_band || "low",
    impact: rec.impact,
    tentative: Boolean(rec.tentative),
    probableRootCause: rec.probable_root_cause ?? null,
    rootCause: rec.root_cause ?? rec.probable_root_cause ?? null,
    supportingContext: rec.supporting_context ?? null,
    sourceLabel: rec.source_label || "fallback_rules",
    recommendationMode: rec.recommendation_mode || "fallback_rules",
    actionRelevanceScore: Number.isFinite(rec.action_relevance_score)
      ? Math.max(0, Math.min(1, Number(rec.action_relevance_score)))
      : 0,
    filteredWeakMatch: Boolean(rec.filtered_weak_match),
    // display_mode is canonical.  mode is deprecated — fall back to it only
    // when display_mode is absent, and log a console.warn so the debt is
    // visible in devtools.  Remove the fallback when mode is removed from the
    // backend schema.
    displayMode: (() => {
      if (rec.display_mode) return rec.display_mode
      if (rec.mode) {
        console.warn(
          "[recommendations-api] Falling back to deprecated `mode` field — `display_mode` missing from API response.",
          { rec_id: rec.id },
        )
        return rec.mode
      }
      return rec.recommended_action ? "evidence_action" : "no_strong_match"
    })(),
    mode: rec.mode || rec.display_mode || (rec.recommended_action ? "evidence_action" : "no_strong_match"),
    matchSummary: rec.match_summary ?? null,
    whyThisMatches: Array.isArray(rec.why_this_matches)
      ? rec.why_this_matches.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    nextBestActions: Array.isArray(rec.next_best_actions)
      ? rec.next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    validationSteps: Array.isArray(rec.validation_steps)
      ? rec.validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    baseRecommendedAction: rec.base_recommended_action ?? null,
    baseNextBestActions: Array.isArray(rec.base_next_best_actions)
      ? rec.base_next_best_actions.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    baseValidationSteps: Array.isArray(rec.base_validation_steps)
      ? rec.base_validation_steps.map((item) => String(item || "").trim()).filter(Boolean)
      : [],
    actionRefinementSource: rec.action_refinement_source ?? null,
    evidenceSources: (rec.evidence_sources || []).map((source) => ({
      evidenceType: source.evidence_type,
      reference: source.reference,
      excerpt: source.excerpt ?? null,
      sourceId: source.source_id ?? null,
      title: source.title ?? null,
      relevance: Number.isFinite(source.relevance) ? Math.max(0, Math.min(1, Number(source.relevance))) : 0,
      whyRelevant: source.why_relevant ?? null,
    })),
    llmGeneralAdvisory: rec.llm_general_advisory
      ? {
          probableCauses: Array.isArray(rec.llm_general_advisory.probable_causes)
            ? rec.llm_general_advisory.probable_causes.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          suggestedChecks: Array.isArray(rec.llm_general_advisory.suggested_checks)
            ? rec.llm_general_advisory.suggested_checks.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
          escalationHint: rec.llm_general_advisory.escalation_hint ?? null,
          knowledgeSource: rec.llm_general_advisory.knowledge_source,
          confidence: Number.isFinite(rec.llm_general_advisory.confidence)
            ? Math.max(0, Math.min(1, Number(rec.llm_general_advisory.confidence)))
            : undefined,
          language: rec.llm_general_advisory.language,
        }
      : null,
    currentUserFeedback: rec.current_feedback
      ? {
          feedbackType: rec.current_feedback.feedback_type,
          createdAt: rec.current_feedback.created_at,
          updatedAt: rec.current_feedback.updated_at,
        }
      : null,
    feedbackSummary: rec.feedback_summary
      ? {
          totalFeedback: Number(rec.feedback_summary.total_feedback || 0),
          usefulCount: Number(rec.feedback_summary.useful_count || 0),
          notRelevantCount: Number(rec.feedback_summary.not_relevant_count || 0),
          appliedCount: Number(rec.feedback_summary.applied_count || 0),
          rejectedCount: Number(rec.feedback_summary.rejected_count || 0),
          usefulnessRate: Number.isFinite(rec.feedback_summary.usefulness_rate)
            ? Math.max(0, Math.min(1, Number(rec.feedback_summary.usefulness_rate)))
            : 0,
          appliedRate: Number.isFinite(rec.feedback_summary.applied_rate)
            ? Math.max(0, Math.min(1, Number(rec.feedback_summary.applied_rate)))
            : 0,
          rejectionRate: Number.isFinite(rec.feedback_summary.rejection_rate)
            ? Math.max(0, Math.min(1, Number(rec.feedback_summary.rejection_rate)))
            : 0,
        }
      : null,
    createdAt: rec.created_at,
  }
}

export async function fetchRecommendations(locale: "fr" | "en" = "en"): Promise<Recommendation[]> {
  const data = await apiFetch<ApiRecommendation[]>(`/recommendations?locale=${locale}`)
  return data.map(mapRecommendation)
}

export async function fetchSlaStrategies(locale: "fr" | "en" = "en"): Promise<SlaStrategies> {
  const data = await apiFetch<ApiSlaStrategies>(`/recommendations/sla-strategies?locale=${locale}`)
  return {
    summary: data.summary,
    commonBreachPatterns: data.common_breach_patterns || [],
    processImprovements: data.process_improvements || [],
    confidence: Number.isFinite(data.confidence) ? Number(data.confidence) : 0,
    sources: data.sources || [],
  }
}
