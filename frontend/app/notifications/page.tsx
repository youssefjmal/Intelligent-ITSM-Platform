"use client"

import React from "react"
import { AppShell } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  deleteNotification,
  getNotifications,
  getNotificationPreferences,
  markAllNotificationsRead,
  markNotificationRead,
  markNotificationUnread,
  patchNotificationPreferences,
  type NotificationItem,
  type NotificationSource,
} from "@/lib/notifications-api"
import { AlertCircle, Bell, CheckCircle2, Circle, Trash2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { apiFetch } from "@/lib/api"

const PAGE_SIZE = 10

function severityBadgeClass(severity: string): string {
  if (severity === "critical") return "bg-red-100 text-red-800 border-red-200"
  if (severity === "high" || severity === "warning") return "bg-orange-100 text-orange-800 border-orange-200"
  return "bg-blue-100 text-blue-800 border-blue-200"
}

function severityIcon(severity: string) {
  if (severity === "critical") return <AlertCircle className="h-4 w-4 text-red-600" />
  if (severity === "high" || severity === "warning") return <AlertCircle className="h-4 w-4 text-orange-500" />
  return <CheckCircle2 className="h-4 w-4 text-blue-500" />
}

function prettyTime(iso: string): string {
  const ts = new Date(iso).getTime()
  const diff = Math.max(1, Math.floor((Date.now() - ts) / 1000))
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function eventLabel(eventType: string | undefined): string {
  const normalized = String(eventType || "").replace(/_/g, " ").trim()
  if (!normalized) return "update"
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

export default function NotificationsPage() {
  const router = useRouter()
  const [rows, setRows] = React.useState<NotificationItem[]>([])
  const [loading, setLoading] = React.useState(false)
  const [unreadOnly, setUnreadOnly] = React.useState(false)
  const [severity, setSeverity] = React.useState<"" | "critical">("")
  const [source, setSource] = React.useState<"" | NotificationSource>("")
  const [offset, setOffset] = React.useState(0)
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const [markAllBusy, setMarkAllBusy] = React.useState(false)
  const [prefsBusy, setPrefsBusy] = React.useState(false)
  const [prefs, setPrefs] = React.useState<{
    email_enabled: boolean
    email_min_severity: "info" | "warning" | "high" | "critical"
    immediate_email_min_severity: "info" | "warning" | "high" | "critical"
    digest_enabled: boolean
    digest_frequency: "none" | "hourly"
    quiet_hours_enabled: boolean
    critical_bypass_quiet_hours: boolean
    ticket_assignment_enabled: boolean
    ticket_comment_enabled: boolean
    sla_notifications_enabled: boolean
    problem_notifications_enabled: boolean
    ai_notifications_enabled: boolean
  } | null>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await getNotifications({
        unreadOnly,
        severity,
        source,
        limit: PAGE_SIZE,
        offset,
      })
      setRows(data)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [offset, severity, source, unreadOnly])

  React.useEffect(() => {
    load().catch(() => {})
  }, [load])

  React.useEffect(() => {
    getNotificationPreferences()
      .then((data) =>
        setPrefs({
          email_enabled: data.email_enabled,
          email_min_severity: data.email_min_severity,
          immediate_email_min_severity: data.immediate_email_min_severity,
          digest_enabled: data.digest_enabled,
          digest_frequency: data.digest_frequency,
          quiet_hours_enabled: data.quiet_hours_enabled,
          critical_bypass_quiet_hours: data.critical_bypass_quiet_hours,
          ticket_assignment_enabled: data.ticket_assignment_enabled,
          ticket_comment_enabled: data.ticket_comment_enabled,
          sla_notifications_enabled: data.sla_notifications_enabled,
          problem_notifications_enabled: data.problem_notifications_enabled,
          ai_notifications_enabled: data.ai_notifications_enabled,
        })
      )
      .catch(() => setPrefs(null))
  }, [])

  const hasPrev = offset > 0
  const hasNext = rows.length === PAGE_SIZE

  const onMark = async (item: NotificationItem, read: boolean) => {
    setBusyId(item.id)
    try {
      if (read) {
        await markNotificationRead(item.id)
        setRows((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)))
      } else {
        await markNotificationUnread(item.id)
        setRows((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: null } : n)))
      }
    } finally {
      setBusyId(null)
    }
  }

  const onDelete = async (id: string) => {
    setBusyId(id)
    try {
      await deleteNotification(id)
      setRows((prev) => prev.filter((n) => n.id !== id))
    } finally {
      setBusyId(null)
    }
  }

  const onMarkAllRead = async () => {
    setMarkAllBusy(true)
    try {
      await markAllNotificationsRead()
      await load()
    } finally {
      setMarkAllBusy(false)
    }
  }

  const openNotificationDetail = async (item: NotificationItem) => {
    if (!item.link) return
    if (!item.read_at) {
      try {
        await markNotificationRead(item.id)
        setRows((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)))
      } catch {
        // keep navigation smooth even if mark-read fails
      }
    }
    router.push(item.link)
  }

  const ticketIdFromNotification = (item: NotificationItem): string | null => {
    const fromPayload = String(item.action_payload?.ticket_id || item.metadata_json?.ticket_id || "").trim()
    if (fromPayload) return fromPayload
    const link = String(item.link || "")
    const match = link.match(/\/tickets\/([^/?#]+)/)
    return match?.[1] || null
  }

  const onInlineAction = async (item: NotificationItem) => {
    const actionType = String(item.action_type || "").toLowerCase()
    if (!actionType || actionType === "view") return
    if (actionType === "dismiss") {
      await onMark(item, true)
      return
    }
    const ticketId = ticketIdFromNotification(item)
    if (!ticketId) return
    if (actionType === "reassign") {
      const assignee = String(item.action_payload?.assignee || item.metadata_json?.assignee || "").trim()
      if (!assignee) return
      await apiFetch(`/tickets/${ticketId}/triage`, {
        method: "PATCH",
        body: JSON.stringify({
          assignee,
          comment: "Applied from SLA high-risk notification action.",
        }),
      })
    } else {
      const endpoint = actionType === "approve" ? `/tickets/${ticketId}/approve` : `/tickets/${ticketId}/escalate`
      await apiFetch(endpoint, { method: "PATCH" })
    }
    await onMark(item, true)
  }

  const actionLabel = (actionType: string | null | undefined): string => {
    const normalized = String(actionType || "").toLowerCase()
    if (normalized === "reassign") return "Reassign"
    if (normalized === "approve") return "Approve"
    if (normalized === "escalate") return "Escalate"
    if (normalized === "dismiss") return "Dismiss"
    return normalized || "Action"
  }

  const updatePrefs = async (next: Partial<NonNullable<typeof prefs>>) => {
    if (!prefs) return
    setPrefsBusy(true)
    try {
      const updated = await patchNotificationPreferences({
        email_enabled: next.email_enabled ?? prefs.email_enabled,
        email_min_severity: next.email_min_severity ?? prefs.email_min_severity,
        immediate_email_min_severity: next.immediate_email_min_severity ?? prefs.immediate_email_min_severity,
        digest_enabled: next.digest_enabled ?? prefs.digest_enabled,
        digest_frequency: next.digest_frequency ?? prefs.digest_frequency,
        quiet_hours_enabled: next.quiet_hours_enabled ?? prefs.quiet_hours_enabled,
        critical_bypass_quiet_hours: next.critical_bypass_quiet_hours ?? prefs.critical_bypass_quiet_hours,
        ticket_assignment_enabled: next.ticket_assignment_enabled ?? prefs.ticket_assignment_enabled,
        ticket_comment_enabled: next.ticket_comment_enabled ?? prefs.ticket_comment_enabled,
        sla_notifications_enabled: next.sla_notifications_enabled ?? prefs.sla_notifications_enabled,
        problem_notifications_enabled: next.problem_notifications_enabled ?? prefs.problem_notifications_enabled,
        ai_notifications_enabled: next.ai_notifications_enabled ?? prefs.ai_notifications_enabled,
      })
      setPrefs({
        email_enabled: updated.email_enabled,
        email_min_severity: updated.email_min_severity,
        immediate_email_min_severity: updated.immediate_email_min_severity,
        digest_enabled: updated.digest_enabled,
        digest_frequency: updated.digest_frequency,
        quiet_hours_enabled: updated.quiet_hours_enabled,
        critical_bypass_quiet_hours: updated.critical_bypass_quiet_hours,
        ticket_assignment_enabled: updated.ticket_assignment_enabled,
        ticket_comment_enabled: updated.ticket_comment_enabled,
        sla_notifications_enabled: updated.sla_notifications_enabled,
        problem_notifications_enabled: updated.problem_notifications_enabled,
        ai_notifications_enabled: updated.ai_notifications_enabled,
      })
    } finally {
      setPrefsBusy(false)
    }
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">Notifications</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground sm:text-4xl">Notification Center</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            Track SLA escalations, critical incidents, and automation alerts.
          </p>
        </div>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold">
                <Bell className="h-4 w-4 text-primary" />
                Notifications
              </CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={unreadOnly ? "unread" : "all"}
                  onValueChange={(v) => {
                    setUnreadOnly(v === "unread")
                    setOffset(0)
                  }}
                >
                  <SelectTrigger className="h-8 w-[130px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="unread">Unread</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={severity || "all"}
                  onValueChange={(v) => {
                    setSeverity(v === "all" ? "" : "critical")
                    setOffset(0)
                  }}
                >
                  <SelectTrigger className="h-8 w-[130px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All severities</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={source || "all"}
                  onValueChange={(v) => {
                    setSource(v === "all" ? "" : (v as NotificationSource))
                    setOffset(0)
                  }}
                >
                  <SelectTrigger className="h-8 w-[140px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All sources</SelectItem>
                      <SelectItem value="n8n">n8n</SelectItem>
                      <SelectItem value="ticket">Ticket</SelectItem>
                      <SelectItem value="problem">Problem</SelectItem>
                      <SelectItem value="ai">AI</SelectItem>
                      <SelectItem value="system">System</SelectItem>
                      <SelectItem value="user">User</SelectItem>
                      <SelectItem value="sla">SLA</SelectItem>
                  </SelectContent>
                </Select>

                <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onMarkAllRead} disabled={markAllBusy}>
                  {markAllBusy ? "Marking..." : "Mark all read"}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="py-8 text-center text-sm text-muted-foreground">Loading notifications...</div>
            ) : rows.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">No notifications found.</div>
            ) : (
              <div className="space-y-2">
                {rows.map((item) => {
                  const isUnread = !item.read_at
                  const isLink = Boolean(item.link)
                  const rowContent = (
                    <div
                      key={item.id}
                      className={`rounded-lg border border-border/60 px-3 py-2 ${isUnread ? "bg-[var(--color-background-secondary)]" : "bg-[var(--color-background-primary)]"} ${item.severity === "critical" ? "border-l-[4px] border-l-[#E24B4A]" : item.severity === "warning" || item.severity === "high" ? "border-l-[4px] border-l-[#EF9F27]" : item.severity === "info" ? "border-l-[4px] border-l-[#378ADD]" : ""} ${isLink ? "cursor-pointer transition-colors hover:border-primary/40 hover:bg-accent/30" : ""}`}
                      title={
                        isLink
                          ? `${item.title}${item.body ? `\n${item.body}` : ""}\nSeverité: ${item.severity} | Source: ${item.source || "system"}\nHover for preview — click to open details`
                          : undefined
                      }
                      onClick={() => {
                        if (isLink) {
                          openNotificationDetail(item).catch(() => {})
                        }
                      }}
                      role={isLink ? "button" : undefined}
                      tabIndex={isLink ? 0 : undefined}
                      onKeyDown={(event) => {
                        if (!isLink) return
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault()
                          openNotificationDetail(item).catch(() => {})
                        }
                      }}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            {severityIcon(item.severity)}
                            <p className="line-clamp-1 text-sm font-medium">{item.title}</p>
                            {isUnread ? <Circle className="h-2.5 w-2.5 fill-primary text-primary" /> : null}
                          </div>
                          {item.body ? <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.body}</p> : null}
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                            <Badge className={`border text-[10px] ${severityBadgeClass(item.severity)}`}>{item.severity}</Badge>
                            <Badge variant="outline" className="text-[10px]">{eventLabel(item.event_type)}</Badge>
                            {item.source ? <Badge variant="outline" className="text-[10px]">{item.source}</Badge> : null}
                            {item.pinned_until_read && !item.read_at ? <Badge variant="outline" className="text-[10px]">Pinned</Badge> : null}
                            <span>{prettyTime(item.created_at)}</span>
                            <span>{isUnread ? "Unread" : "Read"}</span>
                            {/* tooltip text moved to title attribute on container */}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          {item.action_type && item.action_type !== "view" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              disabled={busyId === item.id}
                              onClick={(event) => {
                                event.stopPropagation()
                                onInlineAction(item).catch(() => {})
                              }}
                            >
                              {actionLabel(item.action_type)}
                            </Button>
                          ) : null}
                          {!item.link ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              disabled={busyId === item.id}
                              onClick={(event) => {
                                event.stopPropagation()
                                onMark(item, isUnread).catch(() => {})
                              }}
                            >
                              {isUnread ? "Mark read" : "Mark unread"}
                            </Button>
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-destructive"
                            disabled={busyId === item.id}
                            onClick={(event) => {
                              event.stopPropagation()
                              onDelete(item.id).catch(() => {})
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                  return (
                    isLink ? (
                      <HoverCard key={item.id} openDelay={90} closeDelay={90}>
                        <HoverCardTrigger asChild>{rowContent}</HoverCardTrigger>
                        <HoverCardContent className="w-96 space-y-2 p-3">
                          <p className="text-xs font-semibold">{item.title}</p>
                          {item.body ? <p className="text-xs text-muted-foreground">{item.body}</p> : null}
                          <div className="text-[11px] text-muted-foreground">
                            <p>Event: {eventLabel(item.event_type)}</p>
                            <p>Severity: {item.severity}</p>
                            <p>Source: {item.source || "system"}</p>
                            <p>Click to open details</p>
                          </div>
                        </HoverCardContent>
                      </HoverCard>
                    ) : (
                      rowContent
                    )
                  )
                })}
              </div>
            )}

            <div className="mt-4 flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
                disabled={!hasPrev}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
                disabled={!hasNext}
              >
                Next
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">Email Notification Preferences</CardTitle>
          </CardHeader>
          <CardContent>
            {!prefs ? (
              <p className="text-sm text-muted-foreground">Preferences unavailable.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={prefs.email_enabled ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs"
                  disabled={prefsBusy}
                  onClick={() => updatePrefs({ email_enabled: !prefs.email_enabled }).catch(() => {})}
                >
                  {prefs.email_enabled ? "Email enabled" : "Email disabled"}
                </Button>
                <Select
                  value={prefs.immediate_email_min_severity}
                  onValueChange={(v) =>
                    updatePrefs({ immediate_email_min_severity: v as typeof prefs.immediate_email_min_severity }).catch(() => {})
                  }
                  disabled={prefsBusy}
                >
                  <SelectTrigger className="h-8 w-[170px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="critical">Immediate email: Critical</SelectItem>
                    <SelectItem value="high">Immediate email: High</SelectItem>
                    <SelectItem value="warning">Immediate email: Warning</SelectItem>
                    <SelectItem value="info">Immediate email: Info</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  value={prefs.digest_frequency}
                  onValueChange={(v) => updatePrefs({ digest_frequency: v as typeof prefs.digest_frequency }).catch(() => {})}
                  disabled={prefsBusy}
                >
                  <SelectTrigger className="h-8 w-[170px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hourly">Digest: Hourly</SelectItem>
                    <SelectItem value="none">Digest: Off</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant={prefs.digest_enabled ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs"
                  disabled={prefsBusy}
                  onClick={() => updatePrefs({ digest_enabled: !prefs.digest_enabled }).catch(() => {})}
                >
                  {prefs.digest_enabled ? "Digest enabled" : "Digest disabled"}
                </Button>
                <Button
                  variant={prefs.sla_notifications_enabled ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs"
                  disabled={prefsBusy}
                  onClick={() => updatePrefs({ sla_notifications_enabled: !prefs.sla_notifications_enabled }).catch(() => {})}
                >
                  SLA alerts
                </Button>
                <Button
                  variant={prefs.ticket_assignment_enabled ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs"
                  disabled={prefsBusy}
                  onClick={() => updatePrefs({ ticket_assignment_enabled: !prefs.ticket_assignment_enabled }).catch(() => {})}
                >
                  Assignment alerts
                </Button>
                <Button
                  variant={prefs.ticket_comment_enabled ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs"
                  disabled={prefsBusy}
                  onClick={() => updatePrefs({ ticket_comment_enabled: !prefs.ticket_comment_enabled }).catch(() => {})}
                >
                  Comment alerts
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}

