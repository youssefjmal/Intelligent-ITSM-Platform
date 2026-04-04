"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { AlertTriangle, RefreshCw, ShieldAlert, Siren, Workflow } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  getNotifications,
  markNotificationRead,
  type NotificationEventType,
  type NotificationItem,
} from "@/lib/notifications-api"
import { useI18n } from "@/lib/i18n"

const INSIGHT_WINDOW_MS = 2 * 60 * 60 * 1000
const MAX_PRIORITY_INSIGHTS = 3

type InsightKind = "problem" | "sla_risk" | "sla_breach" | "critical_ticket"

type PriorityInsight = {
  id: string
  kind: InsightKind
  title: string
  description: string
  link: string | null
  createdAt: string
  ageMs: number
  eventType: NotificationEventType
  severity: NotificationItem["severity"]
}

function notificationAgeMs(item: NotificationItem, now = Date.now()): number | null {
  const createdMs = Date.parse(item.created_at)
  if (Number.isNaN(createdMs)) {
    return null
  }
  return Math.max(0, now - createdMs)
}

function humanTimeAgo(ageMs: number, locale: "fr" | "en"): string {
  const seconds = Math.max(1, Math.floor(ageMs / 1000))
  if (seconds < 60) {
    return locale === "fr" ? `il y a ${seconds}s` : `${seconds}s ago`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return locale === "fr" ? `il y a ${minutes} min` : `${minutes}m ago`
  }
  const hours = Math.floor(minutes / 60)
  return locale === "fr" ? `il y a ${hours} h` : `${hours}h ago`
}

function kindLabel(kind: InsightKind, locale: "fr" | "en"): string {
  if (kind === "problem") {
    return locale === "fr" ? "Nouveau probleme" : "New problem"
  }
  if (kind === "sla_breach") {
    return locale === "fr" ? "SLA depasse" : "SLA breached"
  }
  if (kind === "sla_risk") {
    return locale === "fr" ? "Risque SLA" : "SLA risk"
  }
  return locale === "fr" ? "Ticket critique" : "Critical ticket"
}

function kindClasses(kind: InsightKind): string {
  if (kind === "problem") {
    return "border-violet-200 bg-violet-50/80"
  }
  if (kind === "sla_breach") {
    return "border-red-200 bg-red-50/80"
  }
  if (kind === "sla_risk") {
    return "border-amber-200 bg-amber-50/80"
  }
  return "border-rose-200 bg-rose-50/80"
}

function kindBadgeClasses(kind: InsightKind): string {
  if (kind === "problem") {
    return "border-violet-300 bg-violet-100 text-violet-700"
  }
  if (kind === "sla_breach") {
    return "border-red-300 bg-red-100 text-red-700"
  }
  if (kind === "sla_risk") {
    return "border-amber-300 bg-amber-100 text-amber-700"
  }
  return "border-rose-300 bg-rose-100 text-rose-700"
}

function eventKind(item: NotificationItem): InsightKind | null {
  if (item.event_type === "problem_created") {
    return "problem"
  }
  if (item.event_type === "sla_breached") {
    return "sla_breach"
  }
  if (item.event_type === "sla_at_risk" || item.event_type === "ai_sla_risk_high") {
    return "sla_risk"
  }
  if (item.event_type === "system_alert") {
    return "critical_ticket"
  }
  if (item.severity === "critical" && (item.source === "ticket" || String(item.link || "").includes("/tickets/"))) {
    return "critical_ticket"
  }
  return null
}

export function selectPriorityInsights(
  notifications: NotificationItem[],
  now = Date.now(),
): PriorityInsight[] {
  const rows: Array<PriorityInsight | null> = notifications
    .filter((item) => !item.read_at)
    .map((item) => {
      const kind = eventKind(item)
      const ageMs = notificationAgeMs(item, now)
      if (!kind || ageMs === null || ageMs > INSIGHT_WINDOW_MS) {
        return null
      }
      return {
        id: item.id,
        kind,
        title: item.title,
        description: String(item.body || item.metadata_json?.ticket_title || item.metadata_json?.problem_id || "").trim(),
        link: item.link ?? null,
        createdAt: item.created_at,
        ageMs,
        eventType: item.event_type,
        severity: item.severity,
      } satisfies PriorityInsight
    })
  const _KIND_PRIORITY: Record<InsightKind, number> = {
    sla_breach: 0,
    sla_risk: 1,
    problem: 2,
    critical_ticket: 3,
  }
  return rows
    .filter((item): item is PriorityInsight => item !== null)
    .sort((left, right) => {
      const kindDiff = _KIND_PRIORITY[left.kind] - _KIND_PRIORITY[right.kind]
      if (kindDiff !== 0) return kindDiff
      return (right.ageMs ?? 0) - (left.ageMs ?? 0)
    })
    .slice(0, MAX_PRIORITY_INSIGHTS)
}

export function DashboardPriorityInsights() {
  const { locale } = useI18n()
  const router = useRouter()
  const isFr = locale === "fr"
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [markingId, setMarkingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadInsights = async (showSpinner = false) => {
    if (showSpinner) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    try {
      const rows = await getNotifications({ unreadOnly: true, limit: 30 })
      setNotifications(rows)
      setError(null)
    } catch {
      setError(isFr ? "Synchronisation des notifications indisponible." : "Notification sync unavailable.")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadInsights().catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadInsights(true).catch(() => {})
    }, 60_000)
    const onFocus = () => {
      loadInsights(true).catch(() => {})
    }
    const onNotificationsChanged = () => {
      loadInsights(true).catch(() => {})
    }
    window.addEventListener("focus", onFocus)
    window.addEventListener("notifications:changed", onNotificationsChanged as EventListener)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener("focus", onFocus)
      window.removeEventListener("notifications:changed", onNotificationsChanged as EventListener)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const insights = useMemo(() => selectPriorityInsights(notifications), [notifications])

  async function markChecked(item: PriorityInsight) {
    try {
      setMarkingId(item.id)
      await markNotificationRead(item.id)
      setNotifications((current) => current.filter((row) => row.id !== item.id))
    } catch {
      setError(isFr ? "Impossible de marquer l'alerte comme lue." : "Could not mark the alert as read.")
    } finally {
      setMarkingId(null)
    }
  }

  async function openInsight(item: PriorityInsight) {
    if (!item.link) {
      await markChecked(item)
      return
    }
    try {
      setMarkingId(item.id)
      await markNotificationRead(item.id)
      setNotifications((current) => current.filter((row) => row.id !== item.id))
    } catch {
      // still navigate when possible so the user can inspect the source event
    } finally {
      setMarkingId(null)
    }
    router.push(item.link)
  }

  if (!loading && insights.length === 0 && !error) {
    return null
  }

  return (
    <section className="section-block">
      <div className="surface-card space-y-4 rounded-2xl border border-border/70 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="section-title">{isFr ? "Signaux urgents recents" : "Recent urgent insights"}</h3>
            <p className="section-subtitle">
              {isFr
                ? "Les nouveaux problemes, risques SLA et tickets critiques restent ici pendant 2h ou jusqu'a verification."
                : "New problems, SLA risks, and critical tickets stay here for up to 2 hours or until checked."}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 rounded-xl"
            disabled={loading || refreshing}
            onClick={() => loadInsights(true).catch(() => {})}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {isFr ? "Actualiser" : "Refresh"}
          </Button>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={`priority-insight-skeleton-${index}`} className="rounded-xl border border-border/70 bg-card/70 p-4">
                <Skeleton className="h-3 w-28" />
                <Skeleton className="mt-3 h-5 w-44" />
                <Skeleton className="mt-2 h-3 w-full" />
                <Skeleton className="mt-4 h-8 w-32" />
              </div>
            ))}
          </div>
        ) : insights.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {insights.map((item) => {
              const icon =
                item.kind === "problem"
                  ? Workflow
                  : item.kind === "sla_breach"
                    ? Siren
                    : item.kind === "sla_risk"
                      ? AlertTriangle
                      : ShieldAlert
              const Icon = icon
              return (
                <div
                  key={item.id}
                  className={`rounded-2xl border p-4 transition-all ${kindClasses(item.kind)}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={`border text-[10px] ${kindBadgeClasses(item.kind)}`}>
                          {kindLabel(item.kind, locale)}
                        </Badge>
                        <span className="text-[11px] text-muted-foreground">{humanTimeAgo(item.ageMs, locale)}</span>
                      </div>
                      <p className="text-sm font-semibold leading-snug text-foreground">{item.title}</p>
                    </div>
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-background/70 text-foreground shadow-sm">
                      <Icon className="h-4 w-4" />
                    </div>
                  </div>
                  <p className="mt-3 min-h-10 text-xs leading-relaxed text-muted-foreground">
                    {item.description || (isFr ? "Ouvrez l'alerte pour voir le detail complet." : "Open the alert to view the full details.")}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 rounded-lg"
                      disabled={markingId === item.id}
                      onClick={() => markChecked(item).catch(() => {})}
                    >
                      {isFr ? "Verifie" : "Checked"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      className="h-8 rounded-lg"
                      disabled={markingId === item.id}
                      onClick={() => openInsight(item).catch(() => {})}
                    >
                      {item.link ? (isFr ? "Ouvrir" : "Open") : isFr ? "Masquer" : "Dismiss"}
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border/80 bg-muted/10 p-4 text-sm text-muted-foreground">
            {isFr
              ? "Aucun signal urgent recent. Les insights restent dans leurs sections habituelles plus bas."
              : "No recent urgent signals. The regular insight sections remain in their usual positions below."}
          </div>
        )}

        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>
    </section>
  )
}
