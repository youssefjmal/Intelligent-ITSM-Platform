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
      status: "open" | "in-progress" | "pending" | "resolved" | "closed"
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
      status: "open" | "in-progress" | "pending" | "resolved" | "closed"
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
  const { t } = useI18n()
  const [tickets, setTickets] = useState<Ticket[]>([])
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
      const [ticketList, statsRes, insightsRes] = await Promise.all([
        fetchTickets(),
        fetchTicketStats(),
        fetchTicketInsights(),
      ])

      setTickets(ticketList)
      setStats(statsRes)
      setInsights(insightsRes)
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

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("nav.dashboard")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {t("dashboard.title")}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {t("dashboard.subtitle")}
          </p>
        </div>

        <KPICards stats={stats} />
        <PerformanceMetrics performance={insights.performance} assignees={assigneeOptions} tickets={tickets} />
        <ProblemInsights insights={problemHighlights} />
        <OperationalInsights
          operational={insights.operational}
          showStale={false}
          maxCritical={4}
        />

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-4">
          <div className="xl:col-span-3">
            <DashboardCharts
              weeklyData={insights.weekly}
              categoryData={insights.category}
              priorityData={insights.priority}
            />
          </div>
          <div className="xl:col-span-1">
            <RecentActivity tickets={tickets} />
          </div>
        </div>
      </div>
    </AppShell>
  )
}
