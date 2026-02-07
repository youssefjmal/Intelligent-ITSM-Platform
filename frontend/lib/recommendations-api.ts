// API helpers for recommendations with snake_case to camelCase mapping.

import { apiFetch } from "@/lib/api"

export type RecommendationType = "pattern" | "priority" | "solution" | "workflow"
export type RecommendationImpact = "high" | "medium" | "low"

export type Recommendation = {
  id: string
  type: RecommendationType
  title: string
  description: string
  relatedTickets: string[]
  confidence: number
  impact: RecommendationImpact
  createdAt: string
}

type ApiRecommendation = {
  id: string
  type: RecommendationType
  title: string
  description: string
  related_tickets: string[]
  confidence: number
  impact: RecommendationImpact
  created_at: string
}

function mapRecommendation(rec: ApiRecommendation): Recommendation {
  return {
    id: rec.id,
    type: rec.type,
    title: rec.title,
    description: rec.description,
    relatedTickets: rec.related_tickets,
    confidence: rec.confidence,
    impact: rec.impact,
    createdAt: rec.created_at,
  }
}

export async function fetchRecommendations(): Promise<Recommendation[]> {
  const data = await apiFetch<ApiRecommendation[]>("/recommendations")
  return data.map(mapRecommendation)
}
