"use client"

import { useEffect, useState } from "react"
import { AppShell } from "@/components/app-shell"
import { KPICards } from "@/components/kpi-cards"
import { DashboardCharts } from "@/components/dashboard-charts"
import { RecentActivity } from "@/components/recent-activity"
import { type Ticket } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { fetchTicketInsights, fetchTicketStats, fetchTickets } from "@/lib/tickets-api"

type Insights = {
  weekly: Array<{ week: string; opened: number; closed: number; pending: number }>
  category: Array<{ category: string; count: number }>
  priority: Array<{ priority: string; count: number; fill: string }>
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

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-foreground text-balance">
            {t("dashboard.title")}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {t("dashboard.subtitle")}
          </p>
        </div>

        <KPICards stats={stats} />

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
