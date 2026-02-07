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
  created_at: string
  updated_at: string
  resolution?: string | null
  tags: string[]
  comments: ApiComment[]
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
}> {
  return apiFetch("/tickets/insights")
}
