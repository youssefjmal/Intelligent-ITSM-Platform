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
import { useI18n } from "@/lib/i18n"
import { toast } from "@/hooks/use-toast"

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

function eventLabel(eventType: string | undefined, locale: "fr" | "en"): string {
  const normalized = String(eventType || "").replace(/_/g, " ").trim()
  if (!normalized) return locale === "fr" ? "mise a jour" : "update"
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function prettyTime(iso: string, locale: "fr" | "en"): string {
  const ts = new Date(iso).getTime()
  const diff = Math.max(1, Math.floor((Date.now() - ts) / 1000))
  if (diff < 60) return locale === "fr" ? `il y a ${diff}s` : `${diff}s ago`
  if (diff < 3600) return locale === "fr" ? `il y a ${Math.floor(diff / 60)} min` : `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return locale === "fr" ? `il y a ${Math.floor(diff / 3600)} h` : `${Math.floor(diff / 3600)}h ago`
  return locale === "fr" ? `il y a ${Math.floor(diff / 86400)} j` : `${Math.floor(diff / 86400)}d ago`
}

export default function NotificationsPage() {
  const router = useRouter()
  const { locale } = useI18n()
  const isFr = locale === "fr"
  const labels = {
    pageCaption: isFr ? "Notifications" : "Notifications",
    pageTitle: isFr ? "Centre de notifications" : "Notification Center",
    pageDescription: isFr
      ? "Suivez les escalades SLA, les incidents critiques et les alertes d'automatisation."
      : "Track SLA escalations, critical incidents, and automation alerts.",
    notificationsTitle: isFr ? "Flux de notifications" : "Notification feed",
    filtersTitle: isFr ? "Filtres rapides" : "Quick filters",
    unreadOnly: isFr ? "Non lues" : "Unread",
    all: isFr ? "Toutes" : "All",
    allSeverities: isFr ? "Toutes severites" : "All severities",
    allSources: isFr ? "Toutes sources" : "All sources",
    markAll: isFr ? "Tout marquer comme lu" : "Mark all read",
    marking: isFr ? "Mise a jour..." : "Marking...",
    loading: isFr ? "Chargement des notifications..." : "Loading notifications...",
    empty: isFr ? "Aucune notification trouvee." : "No notifications found.",
    unread: isFr ? "Non lue" : "Unread",
    read: isFr ? "Lue" : "Read",
    pinned: isFr ? "Epinglee" : "Pinned",
    markRead: isFr ? "Marquer lue" : "Mark read",
    markUnread: isFr ? "Marquer non lue" : "Mark unread",
    previous: isFr ? "Precedent" : "Previous",
    next: isFr ? "Suivant" : "Next",
    openDetails: isFr ? "Cliquer pour ouvrir les details" : "Click to open details",
    preferencesTitle: isFr ? "Preferences de notification" : "Notification preferences",
    preferencesDescription: isFr
      ? "Gardez les alertes visibles dans le centre de notifications et ajustez l'email, le digest et les categories sensibles."
      : "Keep alerts visible in the notification center and tune email, digest, and sensitive categories.",
    preferencesUnavailable: isFr ? "Preferences indisponibles." : "Preferences unavailable.",
    emailEnabled: isFr ? "Email active" : "Email enabled",
    emailDisabled: isFr ? "Email inactive" : "Email disabled",
    digestEnabled: isFr ? "Digest actif" : "Digest enabled",
    digestDisabled: isFr ? "Digest inactif" : "Digest disabled",
    slaAlerts: isFr ? "Alertes SLA" : "SLA alerts",
    assignmentAlerts: isFr ? "Alertes d'assignation" : "Assignment alerts",
    commentAlerts: isFr ? "Alertes de commentaire" : "Comment alerts",
    problemAlerts: isFr ? "Alertes probleme" : "Problem alerts",
    aiAlerts: isFr ? "Alertes IA" : "AI alerts",
    immediateSeverity: isFr ? "Email immediat" : "Immediate email",
    digestFrequency: isFr ? "Digest" : "Digest",
    critical: isFr ? "Critique" : "Critical",
    high: isFr ? "Elevee" : "High",
    warning: isFr ? "Avertissement" : "Warning",
    info: isFr ? "Info" : "Info",
    digestHourly: isFr ? "Toutes les heures" : "Hourly",
    digestOff: isFr ? "Desactive" : "Off",
    saveSuccess: isFr ? "Preferences mises a jour." : "Preferences updated.",
    saveError: isFr ? "Impossible de mettre a jour les preferences." : "Unable to update preferences.",
    actionError: isFr ? "Action indisponible pour cette notification." : "This notification action is unavailable.",
    navigationError: isFr ? "Le statut de lecture sera resynchronise plus tard." : "Read status will resync later.",
    deleteError: isFr ? "Impossible de supprimer cette notification." : "Unable to delete that notification.",
    view: isFr ? "Voir" : "View",
    dismiss: isFr ? "Ignorer" : "Dismiss",
    approve: isFr ? "Approuver" : "Approve",
    escalate: isFr ? "Escalader" : "Escalate",
    reassign: isFr ? "Reassigner" : "Reassign",
  } as const

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
        }),
      )
      .catch(() => setPrefs(null))
  }, [])

  const hasPrev = offset > 0
  const hasNext = rows.length === PAGE_SIZE

  const actionLabel = (actionType: string | null | undefined): string => {
    const normalized = String(actionType || "").toLowerCase()
    if (normalized === "reassign") return labels.reassign
    if (normalized === "approve") return labels.approve
    if (normalized === "escalate") return labels.escalate
    if (normalized === "dismiss") return labels.dismiss
    return labels.view
  }

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
    } catch {
      toast({
        title: labels.deleteError,
        variant: "destructive",
      })
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
        toast({
          title: labels.navigationError,
          variant: "destructive",
        })
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
    try {
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
    } catch {
      toast({
        title: labels.actionError,
        variant: "destructive",
      })
    }
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
      toast({ title: labels.saveSuccess })
    } catch {
      toast({
        title: labels.saveError,
        variant: "destructive",
      })
    } finally {
      setPrefsBusy(false)
    }
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{labels.pageCaption}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground sm:text-4xl">{labels.pageTitle}</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {labels.pageDescription}
          </p>
        </div>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <Bell className="h-4 w-4 text-primary" />
                  {labels.notificationsTitle}
                </CardTitle>
                <p className="text-xs text-muted-foreground">{labels.filtersTitle}</p>
              </div>
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
                    <SelectItem value="all">{labels.all}</SelectItem>
                    <SelectItem value="unread">{labels.unreadOnly}</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={severity || "all"}
                  onValueChange={(v) => {
                    setSeverity(v === "all" ? "" : "critical")
                    setOffset(0)
                  }}
                >
                  <SelectTrigger className="h-8 w-[140px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{labels.allSeverities}</SelectItem>
                    <SelectItem value="critical">{labels.critical}</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={source || "all"}
                  onValueChange={(v) => {
                    setSource(v === "all" ? "" : (v as NotificationSource))
                    setOffset(0)
                  }}
                >
                  <SelectTrigger className="h-8 w-[150px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{labels.allSources}</SelectItem>
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
                  {markAllBusy ? labels.marking : labels.markAll}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="py-8 text-center text-sm text-muted-foreground">{labels.loading}</div>
            ) : rows.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">{labels.empty}</div>
            ) : (
              <div className="space-y-2">
                {rows.map((item) => {
                  const isUnread = !item.read_at
                  const isLink = Boolean(item.link)
                  const rowContent = (
                    <div
                      key={item.id}
                      className={`rounded-lg border border-border/60 px-3 py-2 ${isUnread ? "bg-[var(--color-background-secondary)]" : "bg-[var(--color-background-primary)]"} ${item.severity === "critical" ? "border-l-[4px] border-l-[#E24B4A]" : item.severity === "warning" || item.severity === "high" ? "border-l-[4px] border-l-[#EF9F27]" : item.severity === "info" ? "border-l-[4px] border-l-[#378ADD]" : ""} ${isLink ? "cursor-pointer transition-colors hover:border-primary/40 hover:bg-accent/30" : ""}`}
                      title={isLink ? `${item.title}${item.body ? `\n${item.body}` : ""}\n${labels.openDetails}` : undefined}
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
                            <Badge variant="outline" className="text-[10px]">{eventLabel(item.event_type, isFr ? "fr" : "en")}</Badge>
                            {item.source ? <Badge variant="outline" className="text-[10px]">{item.source}</Badge> : null}
                            {item.pinned_until_read && !item.read_at ? <Badge variant="outline" className="text-[10px]">{labels.pinned}</Badge> : null}
                            <span>{prettyTime(item.created_at, isFr ? "fr" : "en")}</span>
                            <span>{isUnread ? labels.unread : labels.read}</span>
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
                              {isUnread ? labels.markRead : labels.markUnread}
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
                  return isLink ? (
                    <HoverCard key={item.id} openDelay={90} closeDelay={90}>
                      <HoverCardTrigger asChild>{rowContent}</HoverCardTrigger>
                      <HoverCardContent className="w-96 space-y-2 p-3">
                        <p className="text-xs font-semibold">{item.title}</p>
                        {item.body ? <p className="text-xs text-muted-foreground">{item.body}</p> : null}
                        <div className="text-[11px] text-muted-foreground">
                          <p>{eventLabel(item.event_type, isFr ? "fr" : "en")}</p>
                          <p>{item.severity}</p>
                          <p>{item.source || "system"}</p>
                          <p>{labels.openDetails}</p>
                        </div>
                      </HoverCardContent>
                    </HoverCard>
                  ) : (
                    rowContent
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
                {labels.previous}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
                disabled={!hasNext}
              >
                {labels.next}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">{labels.preferencesTitle}</CardTitle>
            <p className="text-sm text-muted-foreground">{labels.preferencesDescription}</p>
          </CardHeader>
          <CardContent>
            {!prefs ? (
              <p className="text-sm text-muted-foreground">{labels.preferencesUnavailable}</p>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant={prefs.email_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ email_enabled: !prefs.email_enabled }).catch(() => {})}
                  >
                    {prefs.email_enabled ? labels.emailEnabled : labels.emailDisabled}
                  </Button>
                  <Button
                    variant={prefs.digest_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ digest_enabled: !prefs.digest_enabled }).catch(() => {})}
                  >
                    {prefs.digest_enabled ? labels.digestEnabled : labels.digestDisabled}
                  </Button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={prefs.immediate_email_min_severity}
                    onValueChange={(v) =>
                      updatePrefs({ immediate_email_min_severity: v as typeof prefs.immediate_email_min_severity }).catch(() => {})
                    }
                    disabled={prefsBusy}
                  >
                    <SelectTrigger className="h-8 w-[190px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">{labels.immediateSeverity}: {labels.critical}</SelectItem>
                      <SelectItem value="high">{labels.immediateSeverity}: {labels.high}</SelectItem>
                      <SelectItem value="warning">{labels.immediateSeverity}: {labels.warning}</SelectItem>
                      <SelectItem value="info">{labels.immediateSeverity}: {labels.info}</SelectItem>
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
                      <SelectItem value="hourly">{labels.digestFrequency}: {labels.digestHourly}</SelectItem>
                      <SelectItem value="none">{labels.digestFrequency}: {labels.digestOff}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant={prefs.sla_notifications_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ sla_notifications_enabled: !prefs.sla_notifications_enabled }).catch(() => {})}
                  >
                    {labels.slaAlerts}
                  </Button>
                  <Button
                    variant={prefs.ticket_assignment_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ ticket_assignment_enabled: !prefs.ticket_assignment_enabled }).catch(() => {})}
                  >
                    {labels.assignmentAlerts}
                  </Button>
                  <Button
                    variant={prefs.ticket_comment_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ ticket_comment_enabled: !prefs.ticket_comment_enabled }).catch(() => {})}
                  >
                    {labels.commentAlerts}
                  </Button>
                  <Button
                    variant={prefs.problem_notifications_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ problem_notifications_enabled: !prefs.problem_notifications_enabled }).catch(() => {})}
                  >
                    {labels.problemAlerts}
                  </Button>
                  <Button
                    variant={prefs.ai_notifications_enabled ? "default" : "outline"}
                    size="sm"
                    className="h-8 text-xs"
                    disabled={prefsBusy}
                    onClick={() => updatePrefs({ ai_notifications_enabled: !prefs.ai_notifications_enabled }).catch(() => {})}
                  >
                    {labels.aiAlerts}
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
