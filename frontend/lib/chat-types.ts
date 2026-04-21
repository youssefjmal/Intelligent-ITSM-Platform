import type { TicketType } from "@/lib/ticket-data"

export type TicketDraft = {
  title: string
  description: string
  priority: "critical" | "high" | "medium" | "low"
  ticket_type: TicketType
  category: "infrastructure" | "network" | "security" | "application" | "service_request" | "hardware" | "email" | "problem"
  tags: string[]
  assignee?: string | null
}

export type TicketDigestRow = {
  id: string
  title: string
  priority: string
  status: string
  assignee: string
}

export type ChatTicketResult = TicketDigestRow & {
  sla_status?: string | null
  ticket_type?: string | null
  category?: string | null
}

export type TicketResultsPayload = {
  kind: string
  header: string
  scope?: string | null
  total_count: number
  tickets: ChatTicketResult[]
}

export type ChatActionLink = {
  label: string
  route: string
}

export type ChatConfidence = {
  level: "low" | "medium" | "high"
  reason: string
}

export type ChatSLAState = {
  state?: string | null
  due_at?: string | null
  remaining_minutes?: number | null
  remaining_human?: string | null
}

export type ChatCommentSummary = {
  author?: string | null
  content: string
  created_at?: string | null
}

export type ChatRelatedEntity = {
  entity_type: string
  entity_id: string
  title?: string | null
  relation?: string | null
  route: string
}

export type ChatRelatedTicketRef = {
  ticket_id: string
  title: string
  status?: string | null
  priority?: string | null
  route: string
}

export type ChatAdviceStep = {
  step: number
  text: string
  reason?: string | null
  evidence: string[]
}

export type ChatCauseCandidate = {
  title: string
  likelihood: "low" | "medium" | "high"
  explanation: string
  evidence: string[]
  related_tickets: ChatRelatedTicketRef[]
}

export type ChatListMetrics = {
  open_count: number
  critical_count: number
}

export type ChatListTicketItem = {
  ticket_id: string
  title: string
  status: string
  priority: string
  assignee: string
  ticket_type?: string | null
  category?: string | null
  sla_risk?: string | null
  route: string
}

export type ChatTopRecommendation = {
  summary: string
  confidence: number
}

export type ChatSimilarTicketMatch = {
  ticket_id: string
  title: string
  match_reason: string
  match_score: number
  status?: string | null
  route: string
}

export type TicketStatusPayload = {
  type: "ticket_status"
  ticket_id: string
  title: string
  status: string
  priority: string
  assignee: string
  sla_state?: string | null
  updated_at?: string | null
  summary: string
  actions: ChatActionLink[]
}

export type TicketDetailsPayload = {
  type: "ticket_details"
  ticket_id: string
  title: string
  description: string
  ticket_type?: TicketType | null
  status: string
  priority: string
  assignee: string
  reporter?: string | null
  category?: string | null
  created_at?: string | null
  updated_at?: string | null
  sla?: ChatSLAState | null
  recent_comments: ChatCommentSummary[]
  related_entities: ChatRelatedEntity[]
  actions: ChatActionLink[]
}

export type ResolutionAdvicePayload = {
  type: "resolution_advice"
  ticket_id?: string | null
  summary: string
  recommended_actions: ChatAdviceStep[]
  why_this_matches: string[]
  validation_steps: string[]
  next_steps: string[]
  related_tickets: ChatRelatedTicketRef[]
  confidence: ChatConfidence
}

export type CauseAnalysisPayload = {
  type: "cause_analysis"
  ticket_id?: string | null
  summary: string
  possible_causes: ChatCauseCandidate[]
  recommended_checks: string[]
  validation_steps: string[]
  confidence: ChatConfidence
}

export type TicketListPayload = {
  type: "ticket_list"
  list_kind: string
  title: string
  scope?: string | null
  total_count: number
  returned_count?: number
  has_more?: boolean
  summary_metrics: ChatListMetrics
  tickets: ChatListTicketItem[]
  top_recommendation?: ChatTopRecommendation | null
  action_links?: ChatActionLink[]
}

export type SimilarTicketsPayload = {
  type: "similar_tickets"
  source_ticket_id?: string | null
  matches: ChatSimilarTicketMatch[]
}

export type AssignmentRecommendationPayload = {
  type: "assignment_recommendation"
  ticket_id?: string | null
  current_assignee?: string | null
  recommended_assignee?: string | null
  reasoning: string[]
  confidence: ChatConfidence
}

export type InsufficientEvidencePayload = {
  type: "insufficient_evidence"
  summary: string
  known_facts: string[]
  missing_signals: string[]
  recommended_next_checks: string[]
  confidence: ChatConfidence
}

export interface ProblemDetailPayload {
  type: "problem_detail"
  problem_id: string
  title: string
  status: string
  category: string
  occurrences_count: number
  active_count: number
  root_cause?: string | null
  workaround?: string | null
  permanent_fix?: string | null
  ai_probable_cause?: string | null
  linked_ticket_count: number
  last_seen_at?: string | null
  action_links?: Array<{ label: string; route?: string; intent?: string }>
}

export interface ProblemListPayload {
  type: "problem_list"
  title?: string
  scope?: string | null
  problems: Array<{
    id: string
    title: string
    status: string
    category: string
    occurrences_count: number
    active_count: number
    last_seen_at?: string | null
    root_cause?: string | null
    workaround?: string | null
  }>
  status_filter?: string | null
  total_count: number
  returned_count?: number
  has_more?: boolean
  action_links?: Array<{ label: string; route?: string; intent?: string }>
}

export interface ProblemLinkedTicketsPayload {
  type: "problem_linked_tickets"
  problem_id: string
  title?: string
  tickets: Array<{
    id: string
    title: string
    status: string
    priority: string
    assignee: string
    created_at?: string | null
    route: string
  }>
  total_count: number
  returned_count?: number
  has_more?: boolean
  action_links?: Array<{ label: string; route?: string; intent?: string }>
}

export interface RecommendationListPayload {
  type: "recommendation_list"
  title?: string
  scope?: string | null
  recommendations: Array<{
    id: string
    title: string
    type: string
    confidence: number
    impact: string
    description: string
  }>
  total_count: number
  returned_count?: number
  has_more?: boolean
  action_links?: Array<{ label: string; route?: string }>
}

export interface TicketThreadCommentItem {
  author: string
  content: string
  created_at?: string | null
  source?: string | null
}

export interface TicketThreadPayload {
  type: "ticket_thread"
  ticket_id: string
  title: string
  status: string
  is_resolved: boolean
  resolution?: string | null
  comment_count: number
  comments: TicketThreadCommentItem[]
}

export type ChatResponsePayload =
  | TicketStatusPayload
  | TicketDetailsPayload
  | ResolutionAdvicePayload
  | CauseAnalysisPayload
  | TicketListPayload
  | ProblemDetailPayload
  | ProblemListPayload
  | ProblemLinkedTicketsPayload
  | RecommendationListPayload
  | SimilarTicketsPayload
  | AssignmentRecommendationPayload
  | InsufficientEvidencePayload
  | TicketThreadPayload

export function ticketListPayloadToResults(payload: TicketListPayload): TicketResultsPayload {
  return {
    kind: payload.list_kind === "high_sla_risk" ? "sla_risk" : payload.list_kind,
    header: payload.title,
    scope: payload.scope || null,
    total_count: payload.total_count,
    tickets: payload.tickets.map((ticket) => ({
      id: ticket.ticket_id,
      title: ticket.title,
      priority: ticket.priority,
      status: ticket.status,
      assignee: ticket.assignee,
      ticket_type: ticket.ticket_type ?? null,
      category: ticket.category ?? null,
      sla_status: ticket.sla_risk ?? null,
    })),
  }
}

export function normalizeResponsePayload(payload: unknown): ChatResponsePayload | null {
  if (!payload) return null

  if (typeof payload === "string") {
    const text = payload.trim()
    if (!text) return null
    try {
      return normalizeResponsePayload(JSON.parse(text))
    } catch {
      return null
    }
  }

  if (typeof payload !== "object") return null

  const candidate = payload as Record<string, unknown>
  if (typeof candidate.type === "string") {
    return candidate as ChatResponsePayload
  }
  if (typeof candidate.response_type === "string") {
    return {
      ...candidate,
      type: candidate.response_type,
    } as ChatResponsePayload
  }

  // Be tolerant to wrappers from API/client/persistence layers so structured
  // chat bubbles still render even if the payload is nested one level deeper.
  if ("response_payload" in candidate) {
    return normalizeResponsePayload(candidate.response_payload)
  }
  if ("responsePayload" in candidate) {
    return normalizeResponsePayload(candidate.responsePayload)
  }
  if ("payload" in candidate) {
    return normalizeResponsePayload(candidate.payload)
  }

  return null
}

export function payloadEntityKind(payload: ChatResponsePayload | null): string | null {
  if (!payload) return null
  if ("ticket_id" in payload && typeof payload.ticket_id === "string" && payload.ticket_id) return "ticket"
  if ("problem_id" in payload && typeof payload.problem_id === "string" && payload.problem_id) return "problem"
  return null
}

export function payloadEntityId(payload: ChatResponsePayload | null): string | null {
  if (!payload) return null
  if ("ticket_id" in payload && typeof payload.ticket_id === "string" && payload.ticket_id) return payload.ticket_id
  if ("problem_id" in payload && typeof payload.problem_id === "string" && payload.problem_id) return payload.problem_id
  if ("source_ticket_id" in payload && typeof payload.source_ticket_id === "string" && payload.source_ticket_id) return payload.source_ticket_id
  return null
}

export function payloadInventoryKind(payload: ChatResponsePayload | null): string | null {
  if (!payload) return null
  if (payload.type === "ticket_list") return "tickets"
  if (payload.type === "problem_linked_tickets") return "tickets"
  if (payload.type === "similar_tickets") return "tickets"
  if (payload.type === "problem_list") return "problems"
  if (payload.type === "recommendation_list") return "recommendations"
  return null
}

export function payloadListedEntityIds(payload: ChatResponsePayload | null): string[] {
  if (!payload) return []
  if (payload.type === "ticket_list") return payload.tickets.map((ticket) => ticket.ticket_id).filter(Boolean)
  if (payload.type === "problem_list") return payload.problems.map((problem) => problem.id).filter(Boolean)
  if (payload.type === "problem_linked_tickets") return payload.tickets.map((ticket) => ticket.id).filter(Boolean)
  if (payload.type === "similar_tickets") return payload.matches.map((ticket) => ticket.ticket_id).filter(Boolean)
  return []
}
