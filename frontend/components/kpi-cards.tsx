"use client"

import { Card, CardContent } from "@/components/ui/card"
import {
  TicketCheck,
  Clock,
  AlertTriangle,
  TrendingUp,
  Loader2,
  FolderOpen,
} from "lucide-react"
import { useI18n } from "@/lib/i18n"

interface KPICardsProps {
  stats: {
    total: number
    open: number
    inProgress: number
    pending: number
    resolved: number
    closed: number
    critical: number
    resolutionRate: number
    avgResolutionDays: number
  }
}

export function KPICards({ stats }: KPICardsProps) {
  const { t } = useI18n()

  const kpis = [
    {
      title: t("kpi.totalTickets"),
      value: stats.total,
      icon: FolderOpen,
      description: `${stats.open} ${t("kpi.opened")}`,
      iconBg: "bg-primary/10",
      iconColor: "text-primary",
    },
    {
      title: t("kpi.inProgress"),
      value: stats.inProgress,
      icon: Loader2,
      description: `${stats.pending} ${t("kpi.pendingDesc")}`,
      iconBg: "bg-amber-50",
      iconColor: "text-amber-600",
    },
    {
      title: t("kpi.resolvedClosed"),
      value: stats.resolved + stats.closed,
      icon: TicketCheck,
      description: `${t("kpi.rateDesc")}: ${stats.resolutionRate}%`,
      iconBg: "bg-emerald-50",
      iconColor: "text-emerald-600",
    },
    {
      title: t("kpi.critical"),
      value: stats.critical,
      icon: AlertTriangle,
      description: t("kpi.maxPriority"),
      iconBg: "bg-red-50",
      iconColor: "text-red-600",
    },
    {
      title: t("kpi.avgTime"),
      value: `${stats.avgResolutionDays}j`,
      icon: Clock,
      description: t("kpi.resolutionTime"),
      iconBg: "bg-blue-50",
      iconColor: "text-blue-600",
    },
    {
      title: t("kpi.resolutionRate"),
      value: `${stats.resolutionRate}%`,
      icon: TrendingUp,
      description: t("kpi.thisMonth"),
      iconBg: "bg-primary/10",
      iconColor: "text-primary",
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {kpis.map((kpi) => (
        <Card key={kpi.title} className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">
                  {kpi.title}
                </p>
                <p className="text-2xl font-bold text-foreground">
                  {kpi.value}
                </p>
              </div>
              <div
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-lg",
                  kpi.iconBg
                )}
              >
                <kpi.icon className={cn("h-4 w-4", kpi.iconColor)} />
              </div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {kpi.description}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function cn(...classes: (string | undefined | false)[]) {
  return classes.filter(Boolean).join(" ")
}
