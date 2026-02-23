import { apiFetch } from "@/lib/api"

export type NotificationSeverity = "info" | "warning" | "critical"

export interface NotificationItem {
  id: string
  user_id: string
  title: string
  body?: string | null
  severity: NotificationSeverity
  link?: string | null
  source?: string | null
  created_at: string
  read_at?: string | null
}

export async function getNotifications(params?: { unreadOnly?: boolean; limit?: number }) {
  const search = new URLSearchParams()
  if (params?.unreadOnly) search.set("unread_only", "true")
  if (params?.limit) search.set("limit", String(params.limit))
  const qs = search.toString()
  return apiFetch<NotificationItem[]>(`/notifications${qs ? `?${qs}` : ""}`)
}

export async function getUnreadNotificationCount() {
  return apiFetch<{ count: number }>("/notifications/unread-count")
}

export async function markNotificationRead(id: string) {
  return apiFetch<NotificationItem>(`/notifications/${id}/read`, { method: "POST" })
}

export async function markAllNotificationsRead() {
  return apiFetch<{ updated: number }>("/notifications/read-all", { method: "POST" })
}

