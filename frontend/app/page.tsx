"use client"

import { useEffect, useMemo, useState } from "react"
import { AppShell } from "@/components/app-shell"
import { KPICards } from "@/components/kpi-cards"
import { DashboardCharts } from "@/components/dashboard-charts"
import { RecentActivity } from "@/components/recent-activity"
import { OperationalInsights } from "@/components/operational-insights"
import { ProblemInsights } from "@/components/problem-insights"
import { PerformanceMetrics } from "@/components/performance-metrics"
import { type Ticket, type TicketCategory } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { fetchTicketInsights, fetchTickets } from "@/lib/tickets-api"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

type Insights = {
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
    ai_recommendation_confidence?: number
  }>
  operational: {
    critical_recent: Array<{
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
    }>
    stale_active: Array<{
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
    }>
    recent_days: number
    stale_days: number
    counts: {
      critical_recent: number
      stale_active: number
    }
  }
  performance: {
    total_tickets: number
    resolved_tickets: number
    mttr_hours: {
      before: number | null
      after: number | null
    }
    mttr_global_hours: number | null
    mttr_p90_hours: number | null
    mttr_by_priority_hours: Record<string, number | null>
    mttr_by_category_hours: Record<string, number | null>
    throughput_resolved_per_week: number
    backlog_open_over_days: number
    backlog_threshold_days: number
    reassignment_rate: number
    reassigned_tickets: number
    avg_time_to_first_action_hours: number | null
    median_time_to_first_action_hours: number | null
    classification_accuracy_rate: number | null
    classification_samples: number
    auto_assignment_accuracy_rate: number | null
    auto_assignment_samples: number
    auto_triage_no_correction_rate: number | null
    auto_triage_no_correction_count: number
    auto_triage_samples: number
    sla_breach_rate: number | null
    sla_breached_tickets: number
    sla_tickets_with_due: number
    first_response_sla_breach_rate: number | null
    first_response_sla_breached_count: number
    first_response_sla_eligible: number
    resolution_sla_breach_rate: number | null
    resolution_sla_breached_count: number
    resolution_sla_eligible: number
    reopen_rate: number | null
    first_contact_resolution_rate: number | null
    csat_score: number | null
  }
  problem_management?: {
    total: number
    open: number
    investigating: number
    known_error: number
    resolved: number
    closed: number
    active_total: number
    top: Array<{
      id: string
      title: string
      status: string
      occurrences_count: number
      active_count: number
      category: string
      latest_ticket_id: string
      latest_updated_at: string
      ticket_ids: string[]
      highest_priority: "critical" | "high" | "medium" | "low"
      problem_count: number
      problem_triggered: boolean
      trigger_reasons: string[]
      recent_occurrences_7d: number
      same_day_peak: number
      same_day_peak_date: string | null
      ai_recommendation: string
      ai_recommendation_confidence?: number
    }>
  }
}

export default function DashboardPage() {
  const { t, locale } = useI18n()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [insights, setInsights] = useState<Insights>({
    weekly: [],
    category: [],
    priority: [],
    problems: [],
    operational: {
      critical_recent: [],
      stale_active: [],
      recent_days: 7,
      stale_days: 5,
      counts: {
        critical_recent: 0,
        stale_active: 0,
      },
    },
    performance: {
      total_tickets: 0,
      resolved_tickets: 0,
      mttr_hours: {
        before: null,
        after: null,
      },
      mttr_global_hours: null,
      mttr_p90_hours: null,
      mttr_by_priority_hours: {},
      mttr_by_category_hours: {},
      throughput_resolved_per_week: 0,
      backlog_open_over_days: 0,
      backlog_threshold_days: 7,
      reassignment_rate: 0,
      reassigned_tickets: 0,
      avg_time_to_first_action_hours: null,
      median_time_to_first_action_hours: null,
      classification_accuracy_rate: null,
      classification_samples: 0,
      auto_assignment_accuracy_rate: null,
      auto_assignment_samples: 0,
      auto_triage_no_correction_rate: null,
      auto_triage_no_correction_count: 0,
      auto_triage_samples: 0,
      sla_breach_rate: null,
      sla_breached_tickets: 0,
      sla_tickets_with_due: 0,
      first_response_sla_breach_rate: null,
      first_response_sla_breached_count: 0,
      first_response_sla_eligible: 0,
      resolution_sla_breach_rate: null,
      resolution_sla_breached_count: 0,
      resolution_sla_eligible: 0,
      reopen_rate: null,
      first_contact_resolution_rate: null,
      csat_score: null,
    },
    problem_management: {
      total: 0,
      open: 0,
      investigating: 0,
      known_error: 0,
      resolved: 0,
      closed: 0,
      active_total: 0,
      top: [],
    },
  })

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [ticketList, insightsRes] = await Promise.all([fetchTickets(), fetchTicketInsights()])

        setTickets(ticketList)
        setInsights(insightsRes)
      } finally {
        setLoading(false)
      }
    }

    load().catch(() => {})
  }, [])

  const problemHighlights =
    (insights.problem_management?.top?.length
      ? insights.problem_management.top.map((problem) => ({
          title: problem.title,
          occurrences: problem.occurrences_count,
          active_count: problem.active_count,
          problem_count: problem.problem_count,
          highest_priority: problem.highest_priority,
          latest_ticket_id: problem.latest_ticket_id,
          latest_updated_at: problem.latest_updated_at,
          ticket_ids: problem.ticket_ids,
          problem_triggered: problem.problem_triggered,
          trigger_reasons: problem.trigger_reasons,
          recent_occurrences_7d: problem.recent_occurrences_7d,
          same_day_peak: problem.same_day_peak,
          same_day_peak_date: problem.same_day_peak_date,
          ai_recommendation: problem.ai_recommendation,
          ai_recommendation_confidence: problem.ai_recommendation_confidence,
        }))
      : insights.problems
    ).slice(0, 3)
  const assigneeOptions = Array.from(new Set(tickets.map((ticket) => ticket.assignee).filter(Boolean))).sort()
  const isFr = locale === "fr"
  const [globalScope, setGlobalScope] = useState<"all" | "active" | "resolved">("all")
  const [globalCategory, setGlobalCategory] = useState<"all" | TicketCategory>("all")
  const [globalAssignee, setGlobalAssignee] = useState("all")
  const [globalDateFrom, setGlobalDateFrom] = useState("")
  const [globalDateTo, setGlobalDateTo] = useState("")

  const globalFilteredTickets = useMemo(() => {
    const fromMs = globalDateFrom ? Date.parse(`${globalDateFrom}T00:00:00.000Z`) : null
    const toMs = globalDateTo ? Date.parse(`${globalDateTo}T23:59:59.999Z`) : null
    const assigneeFilter = globalAssignee === "all" ? "" : globalAssignee.trim().toLowerCase()
    const activeStatuses = new Set(["open", "in-progress", "waiting-for-customer", "waiting-for-support-vendor", "pending"])
    const resolvedStatuses = new Set(["resolved", "closed"])
    return tickets.filter((ticket) => {
      const createdMs = Date.parse(ticket.createdAt)
      if (Number.isNaN(createdMs)) return false
      if (fromMs !== null && createdMs < fromMs) return false
      if (toMs !== null && createdMs > toMs) return false
      if (globalCategory !== "all" && ticket.category !== globalCategory) return false
      if (assigneeFilter && (ticket.assignee || "").trim().toLowerCase() !== assigneeFilter) return false
      if (globalScope === "active" && !activeStatuses.has(ticket.status)) return false
      if (globalScope === "resolved" && !resolvedStatuses.has(ticket.status)) return false
      return true
    })
  }, [tickets, globalDateFrom, globalDateTo, globalCategory, globalAssignee, globalScope])

  const globalStats = useMemo(() => {
    const rows = globalFilteredTickets
    const total = rows.length
    const open = rows.filter((t) => t.status === "open").length
    const inProgress = rows.filter((t) => t.status === "in-progress").length
    const pending = rows.filter((t) => t.status === "pending" || t.status === "waiting-for-customer" || t.status === "waiting-for-support-vendor").length
    const resolved = rows.filter((t) => t.status === "resolved").length
    const closed = rows.filter((t) => t.status === "closed").length
    const critical = rows.filter((t) => t.priority === "critical").length
    const high = rows.filter((t) => t.priority === "high").length
    const resolutionRate = total > 0 ? Math.round(((resolved + closed) / total) * 100) : 0
    const resolvedRows = rows.filter((t) => t.status === "resolved" || t.status === "closed")
    const avgResolutionDays = resolvedRows.length
      ? Number(
          (
            resolvedRows.reduce((sum, ticket) => {
              const createdMs = Date.parse(ticket.createdAt)
              const resolvedMs = Date.parse(ticket.resolvedAt || ticket.updatedAt)
              if (Number.isNaN(createdMs) || Number.isNaN(resolvedMs)) return sum
              const days = Math.max((resolvedMs - createdMs) / 86400000, 0)
              return sum + days
            }, 0) / resolvedRows.length
          ).toFixed(2),
        )
      : 0

    return {
      total,
      open,
      inProgress,
      pending,
      resolved,
      closed,
      critical,
      high,
      resolutionRate,
      avgResolutionDays,
    }
  }, [globalFilteredTickets])

  function resetGlobalFilters() {
    setGlobalScope("all")
    setGlobalCategory("all")
    setGlobalAssignee("all")
    setGlobalDateFrom("")
    setGlobalDateTo("")
  }

  return (
    <AppShell>
      <div className="relative fade-slide-in space-y-6">
        <div className="page-hero">
          <p className="section-caption">{t("nav.dashboard")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {t("dashboard.title")}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {t("dashboard.subtitle")}
          </p>
        </div>

        <section className="section-block">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="section-title">{isFr ? "Vue operationnelle" : "Operational snapshot"}</h3>
              <p className="section-subtitle">
                {isFr ? "Ces KPI utilisent des filtres dedies (independants de la section IA)." : "These KPIs use dedicated filters (independent from AI section)."}
              </p>
            </div>
          </div>
          {!loading && (
            <div className="mt-3 rounded-xl border border-border/70 bg-muted/15 p-3">
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-6">
                <Select value={globalScope} onValueChange={(value) => setGlobalScope(value as "all" | "active" | "resolved")}>
                  <SelectTrigger className="h-10 rounded-xl bg-background/70">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{isFr ? "Tous statuts" : "All statuses"}</SelectItem>
                    <SelectItem value="active">{isFr ? "Actifs" : "Active"}</SelectItem>
                    <SelectItem value="resolved">{isFr ? "Resolus/Fermes" : "Resolved/Closed"}</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  type="date"
                  value={globalDateFrom}
                  onChange={(e) => setGlobalDateFrom(e.target.value)}
                  className="h-10 rounded-xl bg-background/70"
                />
                <Input
                  type="date"
                  value={globalDateTo}
                  onChange={(e) => setGlobalDateTo(e.target.value)}
                  className="h-10 rounded-xl bg-background/70"
                />
                <Select value={globalCategory} onValueChange={(value) => setGlobalCategory(value as "all" | TicketCategory)}>
                  <SelectTrigger className="h-10 rounded-xl bg-background/70">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{isFr ? "Toutes categories" : "All categories"}</SelectItem>
                    <SelectItem value="infrastructure">{t("category.infrastructure")}</SelectItem>
                    <SelectItem value="network">{t("category.network")}</SelectItem>
                    <SelectItem value="security">{t("category.security")}</SelectItem>
                    <SelectItem value="application">{t("category.application")}</SelectItem>
                    <SelectItem value="service_request">{t("category.service_request")}</SelectItem>
                    <SelectItem value="hardware">{t("category.hardware")}</SelectItem>
                    <SelectItem value="email">{t("category.email")}</SelectItem>
                    <SelectItem value="problem">{t("category.problem")}</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={globalAssignee} onValueChange={setGlobalAssignee}>
                  <SelectTrigger className="h-10 rounded-xl bg-background/70">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{isFr ? "Tous assignees" : "All assignees"}</SelectItem>
                    {assigneeOptions.map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" className="h-10 rounded-xl px-4" onClick={resetGlobalFilters}>
                    {isFr ? "Reset" : "Reset"}
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {globalScope !== "all" && (
                  <Badge variant="outline" className="border-border bg-background/70 text-[11px]">
                    {isFr ? "Portee" : "Scope"}: {globalScope === "active" ? (isFr ? "Actifs" : "Active") : (isFr ? "Resolus/Fermes" : "Resolved/Closed")}
                  </Badge>
                )}
                {globalCategory !== "all" && (
                  <Badge variant="outline" className="border-border bg-background/70 text-[11px]">
                    {isFr ? "Categorie" : "Category"}: {t(`category.${globalCategory}` as "category.application")}
                  </Badge>
                )}
                {globalAssignee !== "all" && (
                  <Badge variant="outline" className="border-border bg-background/70 text-[11px]">
                    {isFr ? "Assigne" : "Assignee"}: {globalAssignee}
                  </Badge>
                )}
                {(globalDateFrom || globalDateTo) && (
                  <Badge variant="outline" className="border-border bg-background/70 text-[11px]">
                    {isFr ? "Dates" : "Dates"}: {globalDateFrom || "..."} - {globalDateTo || "..."}
                  </Badge>
                )}
              </div>
            </div>
          )}
          {loading ? <DashboardKpiSkeleton /> : <KPICards stats={globalStats} />}
        </section>

        <Separator className="bg-border/60" />

        <section className="section-block">
          {loading ? (
            <PerformanceSectionSkeleton />
          ) : (
            <PerformanceMetrics performance={insights.performance} assignees={assigneeOptions} tickets={tickets} />
          )}
        </section>

        <Separator className="bg-border/60" />

        <section className="section-block">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="section-title">{isFr ? "Signaux de problemes" : "Problem signals"}</h3>
              <p className="section-subtitle">
                {isFr ? "Survolez les cartes pour plus de contexte, puis cliquez pour ouvrir la vue correspondante." : "Hover cards for more context, then click to open the related view."}
              </p>
            </div>
          </div>
          {loading ? <InsightsSkeleton /> : <ProblemInsights insights={problemHighlights} />}
        </section>

        <section className="section-block">
          {loading ? (
            <InsightsSkeleton compact />
          ) : (
            <OperationalInsights
              operational={insights.operational}
              showStale={false}
              maxCritical={4}
            />
          )}
        </section>

        <Separator className="bg-border/60" />

        <section className="section-block">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="section-title">{isFr ? "Tendances et activite" : "Trends and activity"}</h3>
              <p className="section-subtitle">
                {isFr ? "Les tableaux de bord ci-dessous sont consultables au survol et cliquables." : "The dashboard cards below show hover details and are clickable."}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-4">
            <div className="xl:col-span-3">
              {loading ? (
                <ChartsSkeleton />
              ) : (
                <DashboardCharts
                  weeklyData={insights.weekly}
                  categoryData={insights.category}
                  priorityData={insights.priority}
                />
              )}
            </div>
            <div className="xl:col-span-1">
              {loading ? <RecentActivitySkeleton /> : <RecentActivity tickets={tickets} />}
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  )
}

function DashboardKpiSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={`kpi-skeleton-${index}`} className="surface-card rounded-2xl p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-7 w-16" />
            </div>
            <Skeleton className="h-9 w-9 rounded-lg" />
          </div>
          <Skeleton className="mt-3 h-3 w-32" />
        </div>
      ))}
    </div>
  )
}

function PerformanceSectionSkeleton() {
  return (
    <div className="surface-card space-y-4 rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Skeleton className="h-5 w-56" />
        <Skeleton className="h-5 w-32" />
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={`filter-skeleton-${index}`} className="h-10 w-full rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={`metric-skeleton-${index}`} className="rounded-xl border border-border/70 p-3">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-2 h-7 w-20" />
            <Skeleton className="mt-3 h-3 w-32" />
          </div>
        ))}
      </div>
    </div>
  )
}

function InsightsSkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <div className="surface-card rounded-2xl p-4 sm:p-6">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {Array.from({ length: compact ? 2 : 3 }).map((_, index) => (
          <div key={`insight-skeleton-${index}`} className="rounded-xl border border-border/70 p-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-3 h-3 w-full" />
            <Skeleton className="mt-2 h-3 w-3/4" />
          </div>
        ))}
      </div>
    </div>
  )
}

function ChartsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
      <div className="surface-card rounded-2xl p-5 lg:col-span-2">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="mt-4 h-[260px] w-full rounded-xl" />
      </div>
      <div className="surface-card rounded-2xl p-5">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-4 h-[260px] w-full rounded-xl" />
      </div>
      <div className="surface-card rounded-2xl p-5 xl:col-span-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="mt-4 h-[200px] w-full rounded-xl" />
      </div>
    </div>
  )
}

function RecentActivitySkeleton() {
  return (
    <div className="surface-card rounded-2xl p-4">
      <Skeleton className="h-4 w-40" />
      <div className="mt-4 space-y-3">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={`activity-skeleton-${index}`} className="rounded-lg border border-border/70 p-3">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="mt-2 h-3 w-24" />
          </div>
        ))}
      </div>
    </div>
  )
}
