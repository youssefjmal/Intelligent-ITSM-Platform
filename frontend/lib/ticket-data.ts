// Shared ticket types and UI label mappings.

export type TicketStatus =
  | "open"
  | "in-progress"
  | "waiting-for-customer"
  | "waiting-for-support-vendor"
  | "pending"
  | "resolved"
  | "closed"
export type TicketPriority = "critical" | "high" | "medium" | "low"
export type SlaStatus = "ok" | "at_risk" | "breached" | "paused" | "completed" | "unknown"
export type TicketCategory =
  | "infrastructure"
  | "network"
  | "security"
  | "application"
  | "service_request"
  | "hardware"
  | "email"
  | "problem"

export interface TicketComment {
  id: string
  author: string
  content: string
  createdAt: string
}

export interface Ticket {
  id: string
  problemId?: string
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  category: TicketCategory
  assignee: string
  reporter: string
  autoAssignmentApplied?: boolean
  autoPriorityApplied?: boolean
  assignmentModelVersion?: string
  priorityModelVersion?: string
  predictedPriority?: TicketPriority
  predictedCategory?: TicketCategory
  assignmentChangeCount?: number
  firstActionAt?: string
  resolvedAt?: string
  slaStatus?: SlaStatus | null
  createdAt: string
  updatedAt: string
  resolution?: string
  tags: string[]
  comments: TicketComment[]
}

export function getTicketStats(tickets: Ticket[]) {
  const total = tickets.length
  const open = tickets.filter(t => t.status === "open").length
  const inProgress = tickets.filter(t => t.status === "in-progress").length
  const pending = tickets.filter(
    t => t.status === "pending" || t.status === "waiting-for-customer" || t.status === "waiting-for-support-vendor"
  ).length
  const resolved = tickets.filter(t => t.status === "resolved").length
  const closed = tickets.filter(t => t.status === "closed").length
  const critical = tickets.filter(t => t.priority === "critical").length
  const high = tickets.filter(t => t.priority === "high").length

  const resolutionRate = total > 0 ? Math.round(((resolved + closed) / total) * 100) : 0
  const avgResolutionDays = 0

  return { total, open, inProgress, pending, resolved, closed, critical, high, resolutionRate, avgResolutionDays }
}

export const STATUS_CONFIG: Record<TicketStatus, { label: string; color: string }> = {
  open: { label: "Ouvert", color: "bg-blue-100 text-blue-800" },
  "in-progress": { label: "En cours", color: "bg-amber-100 text-amber-800" },
  "waiting-for-customer": { label: "En attente client", color: "bg-yellow-100 text-yellow-800" },
  "waiting-for-support-vendor": { label: "En attente support/fournisseur", color: "bg-orange-100 text-orange-800" },
  pending: { label: "En attente", color: "bg-orange-100 text-orange-800" },
  resolved: { label: "Resolu", color: "bg-emerald-100 text-emerald-800" },
  closed: { label: "Ferme", color: "bg-slate-100 text-slate-700" },
}

export const PRIORITY_CONFIG: Record<TicketPriority, { label: string; color: string }> = {
  critical: { label: "Critique", color: "bg-red-100 text-red-800" },
  high: { label: "Haute", color: "bg-amber-100 text-amber-800" },
  medium: { label: "Moyenne", color: "bg-emerald-100 text-emerald-800" },
  low: { label: "Basse", color: "bg-slate-100 text-slate-700" },
}

export const CATEGORY_CONFIG: Record<TicketCategory, { label: string }> = {
  infrastructure: { label: "Infrastructure" },
  network: { label: "Reseau" },
  security: { label: "Securite" },
  application: { label: "Application" },
  service_request: { label: "Service Request" },
  hardware: { label: "Materiel" },
  email: { label: "Email" },
  problem: { label: "Probleme" },
}
