import { apiFetch } from "@/lib/api"

export type NotificationSeverity = "info" | "warning" | "high" | "critical"
export type NotificationSource = "n8n" | "system" | "user" | "sla" | "ticket" | "problem" | "ai"
export type NotificationActionType = "view" | "approve" | "escalate" | "dismiss" | "reassign"
export type NotificationEventType =
  | "ticket_created"
  | "ticket_assigned"
  | "ticket_reassigned"
  | "ticket_commented"
  | "ticket_status_changed"
  | "ticket_resolved"
  | "sla_at_risk"
  | "sla_breached"
  | "sla_recovered"
  | "problem_created"
  | "problem_linked"
  | "ai_recommendation_ready"
  | "ai_sla_risk_high"
  | "mention"
  | "system_alert"

export interface NotificationItem {
  id: string
  user_id: string
  title: string
  body?: string | null
  severity: NotificationSeverity
  event_type: NotificationEventType
  link?: string | null
  source?: string | null
  dedupe_key?: string | null
  metadata_json?: Record<string, unknown> | null
  action_type?: NotificationActionType | null
  action_payload?: Record<string, unknown> | null
  created_at: string
  read_at?: string | null
  pinned_until_read?: boolean
}

export interface NotificationPreferences {
  email_enabled: boolean
  email_min_severity: NotificationSeverity
  immediate_email_min_severity: NotificationSeverity
  digest_enabled: boolean
  digest_frequency: "none" | "hourly"
  quiet_hours_enabled: boolean
  quiet_hours_start?: string | null
  quiet_hours_end?: string | null
  critical_bypass_quiet_hours: boolean
  ticket_assignment_enabled: boolean
  ticket_comment_enabled: boolean
  sla_notifications_enabled: boolean
  problem_notifications_enabled: boolean
  ai_notifications_enabled: boolean
}

export interface NotificationDebugItem {
  notification_id: string
  user_id: string
  title: string
  severity: NotificationSeverity
  event_type?: NotificationEventType | null
  source?: string | null
  workflow_name?: string | null
  trace_id?: string | null
  recipients: string[]
  duplicate_suppression?: string | null
  delivery_status: string
  created_at: string
}

export interface NotificationAnalytics {
  notifications_created_total: Record<string, number>
  notifications_read_rate: Record<string, number>
  email_delivery_rate: Record<string, number>
}

function emitNotificationsChanged() {
  if (typeof window === "undefined") return
  window.dispatchEvent(new CustomEvent("notifications:changed"))
}

export async function getNotifications(params?: {
  unreadOnly?: boolean
  source?: NotificationSource | ""
  severity?: NotificationSeverity | ""
  limit?: number
  offset?: number
}) {
  const search = new URLSearchParams()
  if (params?.unreadOnly) search.set("unread_only", "true")
  if (params?.source) search.set("source", params.source)
  if (params?.severity) search.set("severity", params.severity)
  if (params?.limit) search.set("limit", String(params.limit))
  if (params?.offset) search.set("offset", String(params.offset))
  const qs = search.toString()
  return apiFetch<NotificationItem[]>(`/notifications${qs ? `?${qs}` : ""}`)
}

export async function getUnreadNotificationCount() {
  return apiFetch<{ count: number }>("/notifications/unread-count")
}

export async function markNotificationRead(id: string) {
  const res = await apiFetch<NotificationItem>(`/notifications/${id}/read`, { method: "PATCH" })
  emitNotificationsChanged()
  return res
}

export async function markNotificationUnread(id: string) {
  const res = await apiFetch<NotificationItem>(`/notifications/${id}/unread`, { method: "PATCH" })
  emitNotificationsChanged()
  return res
}

export async function markAllNotificationsRead() {
  const res = await apiFetch<{ updated: number }>("/notifications/mark-all-read", { method: "POST" })
  emitNotificationsChanged()
  return res
}

export async function deleteNotification(id: string) {
  const res = await apiFetch<{ deleted: boolean }>(`/notifications/${id}`, { method: "DELETE" })
  emitNotificationsChanged()
  return res
}

export async function getNotificationPreferences() {
  return apiFetch<NotificationPreferences>("/notifications/preferences")
}

export async function patchNotificationPreferences(payload: Partial<NotificationPreferences>) {
  return apiFetch<NotificationPreferences>("/notifications/preferences", {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
}

export async function sendNotificationEmail(id: string) {
  return apiFetch<{ status: string; reason: string }>(`/notifications/${id}/send-email`, {
    method: "POST",
  })
}

export async function runNotificationDigest() {
  return apiFetch<{ users: number; emails_sent: number }>("/notifications/digest/run", {
    method: "POST",
  })
}

export async function getNotificationDebugRecent(params?: {
  workflow?: string
  user_id?: string
  delivery_status?: string
  limit?: number
}) {
  const search = new URLSearchParams()
  if (params?.workflow) search.set("workflow", params.workflow)
  if (params?.user_id) search.set("user_id", params.user_id)
  if (params?.delivery_status) search.set("delivery_status", params.delivery_status)
  if (params?.limit) search.set("limit", String(params.limit))
  const qs = search.toString()
  return apiFetch<NotificationDebugItem[]>(`/notifications/debug-recent${qs ? `?${qs}` : ""}`)
}

export async function getNotificationAnalytics() {
  return apiFetch<NotificationAnalytics>("/notifications/analytics")
}
