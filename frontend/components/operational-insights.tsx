"use client"

import Link from "next/link"
import { AlertTriangle, ArrowRight, Clock3 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { useI18n } from "@/lib/i18n"
import { type TicketCategory } from "@/lib/ticket-data"

type OperationalTicket = {
  id: string
  title: string
  priority: "critical" | "high" | "medium" | "low"
  status:
    | "open"
    | "in-progress"
    | "waiting-for-customer"
    | "waiting-for-support-vendor"
    | "pending"
    | "resolved"
    | "closed"
  category: TicketCategory
  assignee: string
  created_at: string
  updated_at: string
  age_days: number
  inactive_days: number
}

type OperationalInsightsPayload = {
  critical_recent: OperationalTicket[]
  stale_active: OperationalTicket[]
  recent_days: number
  stale_days: number
  counts: {
    critical_recent: number
    stale_active: number
  }
}

function priorityBadgeClass(priority: OperationalTicket["priority"]): string {
  if (priority === "critical") return "border-red-200 bg-red-100 text-red-800 dark:border-red-500/40 dark:bg-red-500/20 dark:text-red-200"
  if (priority === "high") return "border-amber-200 bg-amber-100 text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/20 dark:text-amber-200"
  if (priority === "medium") return "border-emerald-200 bg-emerald-100 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/20 dark:text-emerald-200"
  return "border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-500/40 dark:bg-slate-500/20 dark:text-slate-200"
}

function statusLabel(status: OperationalTicket["status"], t: ReturnType<typeof useI18n>["t"]): string {
  if (status === "open") return t("status.open")
  if (status === "in-progress") return t("status.inProgress")
  if (status === "waiting-for-customer") return t("status.waitingForCustomer")
  if (status === "waiting-for-support-vendor") return t("status.waitingForSupportVendor")
  if (status === "pending") return t("status.pending")
  if (status === "resolved") return t("status.resolved")
  return t("status.closed")
}

type TicketRowProps = {
  ticket: OperationalTicket
  localeCode: string
}

function InsightTicketRow({ ticket, localeCode }: TicketRowProps) {
  const { t } = useI18n()

  return (
    <HoverCard openDelay={100} closeDelay={80}>
      <HoverCardTrigger asChild>
        <Link href={`/tickets/${ticket.id}`} className="group block">
          <article className="rounded-lg border border-border/70 bg-white/90 p-3 transition-colors hover:bg-white dark:border-slate-700/70 dark:bg-slate-900/70 dark:hover:bg-slate-900/90">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="line-clamp-2 text-sm font-medium text-foreground group-hover:text-primary">{ticket.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {ticket.id} | {ticket.assignee || "-"}
                </p>
              </div>
              <Badge className={`text-[10px] ${priorityBadgeClass(ticket.priority)}`}>
                {t(`priority.${ticket.priority}` as "priority.medium")}
              </Badge>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <Badge variant="secondary" className="text-[10px]">
                {statusLabel(ticket.status, t)}
              </Badge>
              <span>{t("dashboard.lastUpdateDays", { days: ticket.inactive_days })}</span>
              <span>
                {new Date(ticket.updated_at).toLocaleDateString(localeCode, {
                  day: "2-digit",
                  month: "short",
                })}
              </span>
            </div>
          </article>
        </Link>
      </HoverCardTrigger>

      <HoverCardContent className="w-80 border-border/70 bg-background/95 p-3 shadow-xl backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/95">
        <p className="text-sm font-semibold text-foreground">{ticket.title}</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
            <p className="text-[10px] text-muted-foreground">{t("tickets.id")}</p>
            <p className="text-xs font-semibold text-foreground">{ticket.id}</p>
          </div>
          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
            <p className="text-[10px] text-muted-foreground">{t("tickets.assignee")}</p>
            <p className="text-xs font-semibold text-foreground">{ticket.assignee || "-"}</p>
          </div>
          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
            <p className="text-[10px] text-muted-foreground">{t("tickets.status")}</p>
            <p className="text-xs font-semibold text-foreground">{statusLabel(ticket.status, t)}</p>
          </div>
          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
            <p className="text-[10px] text-muted-foreground">{t("tickets.category")}</p>
            <p className="text-xs font-semibold text-foreground">
              {t(`category.${ticket.category}` as "category.application")}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span>{t("dashboard.ticketAgeDays", { days: ticket.age_days })}</span>
          <span>{t("dashboard.lastUpdateDays", { days: ticket.inactive_days })}</span>
        </div>
        <Link href={`/tickets/${ticket.id}`} className="mt-3 inline-flex">
          <Button size="sm" className="h-8 gap-1.5">
            {t("tickets.view")}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </Link>
      </HoverCardContent>
    </HoverCard>
  )
}

type OperationalInsightsProps = {
  operational: OperationalInsightsPayload
  showCritical?: boolean
  showStale?: boolean
  maxCritical?: number
  maxStale?: number
}

export function OperationalInsights({
  operational,
  showCritical = true,
  showStale = true,
  maxCritical = 4,
  maxStale = 3,
}: OperationalInsightsProps) {
  const { t, locale } = useI18n()
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"
  const criticalRows = operational.critical_recent.slice(0, Math.max(1, maxCritical))
  const staleRows = operational.stale_active.slice(0, Math.max(1, maxStale))

  if (!showCritical && !showStale) {
    return null
  }

  return (
    <section className="fade-slide-in space-y-4">
      {showCritical && (
      <Card className="border-red-200/70 bg-gradient-to-br from-red-50 to-orange-50 dark:border-red-500/40 dark:bg-gradient-to-br dark:from-red-950/40 dark:to-orange-950/30">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold text-red-900 dark:text-red-100">
              <AlertTriangle className="h-4 w-4 text-red-700 dark:text-red-300" />
              {t("dashboard.criticalRecentTitle")}
            </CardTitle>
            <Badge className="border-red-200 bg-white text-red-700 dark:border-red-500/40 dark:bg-red-500/20 dark:text-red-100">
              {operational.counts.critical_recent}
            </Badge>
          </div>
          <p className="text-xs text-red-900/75 dark:text-red-100/90">
            {t("dashboard.criticalRecentSubtitle", { days: operational.recent_days })}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {criticalRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("dashboard.criticalRecentEmpty")}</p>
          ) : (
            criticalRows.map((ticket) => (
              <InsightTicketRow key={`critical-${ticket.id}`} ticket={ticket} localeCode={localeCode} />
            ))
          )}
          <Link href="/tickets?view=critical">
            <Button size="sm" variant="outline" className="gap-1.5 border-red-300 bg-white text-red-800 hover:bg-red-100 dark:border-red-500/40 dark:bg-red-950/30 dark:text-red-100 dark:hover:bg-red-900/40">
              {t("dashboard.viewCriticalTickets")}
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </CardContent>
      </Card>
      )}

      {showStale && (
      <Card className="border-amber-200/70 bg-gradient-to-br from-amber-50 to-yellow-50 dark:border-amber-500/40 dark:bg-gradient-to-br dark:from-amber-950/30 dark:to-yellow-950/20">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold text-amber-900 dark:text-amber-100">
              <Clock3 className="h-4 w-4 text-amber-700 dark:text-amber-300" />
              {t("dashboard.staleTicketsTitle")}
            </CardTitle>
            <Badge className="border-amber-200 bg-white text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/20 dark:text-amber-100">
              {operational.counts.stale_active}
            </Badge>
          </div>
          <p className="text-xs text-amber-900/75 dark:text-amber-100/90">
            {t("dashboard.staleTicketsSubtitle", { days: operational.stale_days })}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {staleRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("dashboard.staleTicketsEmpty")}</p>
          ) : (
            staleRows.map((ticket) => (
              <InsightTicketRow key={`stale-${ticket.id}`} ticket={ticket} localeCode={localeCode} />
            ))
          )}
          <Link href="/tickets?view=stale">
            <Button size="sm" variant="outline" className="gap-1.5 border-amber-300 bg-white text-amber-800 hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-100 dark:hover:bg-amber-900/40">
              {t("dashboard.viewStaleTickets")}
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </CardContent>
      </Card>
      )}
    </section>
  )
}
