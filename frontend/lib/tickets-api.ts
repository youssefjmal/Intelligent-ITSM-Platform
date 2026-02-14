// API helpers for tickets with snake_case to camelCase mapping.

import { apiFetch } from "@/lib/api"
import { type Ticket, type TicketCategory, type TicketPriority, type TicketStatus } from "@/lib/ticket-data"

type ApiComment = {
  id: string
  author: string
  content: string
  created_at: string
}

type ApiTicket = {
  id: string
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
  reassignment_rate: number
  reassigned_tickets: number
  avg_time_to_first_action_hours: number | null
  classification_accuracy_rate: number | null
  classification_samples: number
  auto_assignment_accuracy_rate: number | null
  auto_assignment_samples: number
}

function mapTicket(ticket: ApiTicket): Ticket {
  return {
    id: ticket.id,
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
  }>
  operational: {
    critical_recent: Array<{
      id: string
      title: string
      priority: "critical" | "high" | "medium" | "low"
      status: "open" | "in-progress" | "pending" | "resolved" | "closed"
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
      status: "open" | "in-progress" | "pending" | "resolved" | "closed"
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
  recommendations: string[]
  assignee: string | null
}

const ticketAIRecommendationsCache = new Map<string, TicketAIRecommendationsPayload>()

export async function fetchTicketAIRecommendations(
  ticket: { id: string; title: string; description: string },
  options: { force?: boolean } = {},
): Promise<TicketAIRecommendationsPayload> {
  const { force = false } = options
  if (!force) {
    const cached = ticketAIRecommendationsCache.get(ticket.id)
    if (cached) return cached
  }

  const data = await apiFetch<{
    priority: TicketPriority
    category: TicketCategory
    recommendations: string[]
    assignee?: string | null
  }>("/ai/classify", {
    method: "POST",
    body: JSON.stringify({
      title: ticket.title,
      description: ticket.description,
    }),
  })

  const payload: TicketAIRecommendationsPayload = {
    priority: data.priority,
    category: data.category,
    recommendations: Array.isArray(data.recommendations) ? data.recommendations : [],
    assignee: data.assignee ?? null,
  }
  ticketAIRecommendationsCache.set(ticket.id, payload)
  return payload
}
