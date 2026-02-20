"use client"

import { useEffect, useState } from "react"
import { AppShell } from "@/components/app-shell"
import { KPICards } from "@/components/kpi-cards"
import { DashboardCharts } from "@/components/dashboard-charts"
import { RecentActivity } from "@/components/recent-activity"
import { OperationalInsights } from "@/components/operational-insights"
import { ProblemInsights } from "@/components/problem-insights"
import { PerformanceMetrics } from "@/components/performance-metrics"
import { type Ticket, type TicketCategory } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { fetchTicketInsights, fetchTicketStats, fetchTickets } from "@/lib/tickets-api"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"

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
    reassignment_rate: number
    reassigned_tickets: number
    avg_time_to_first_action_hours: number | null
    classification_accuracy_rate: number | null
    classification_samples: number
    auto_assignment_accuracy_rate: number | null
    auto_assignment_samples: number
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
  const [stats, setStats] = useState({
    total: 0,
    open: 0,
    inProgress: 0,
    pending: 0,
    resolved: 0,
    closed: 0,
    critical: 0,
    resolutionRate: 0,
    avgResolutionDays: 0,
  })
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
      reassignment_rate: 0,
      reassigned_tickets: 0,
      avg_time_to_first_action_hours: null,
      classification_accuracy_rate: null,
      classification_samples: 0,
      auto_assignment_accuracy_rate: null,
      auto_assignment_samples: 0,
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
        const [ticketList, statsRes, insightsRes] = await Promise.all([
          fetchTickets(),
          fetchTicketStats(),
          fetchTicketInsights(),
        ])

        setTickets(ticketList)
        setStats(statsRes)
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
                {isFr ? "Ces KPI restent globaux et ne sont pas impactes par les filtres IA." : "These KPI remain global and are not impacted by AI filters."}
              </p>
            </div>
          </div>
          {loading ? <DashboardKpiSkeleton /> : <KPICards stats={stats} />}
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
