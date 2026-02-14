"use client"

import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
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

type KPIDetail = {
  label: string
  value: string | number
}

type KPIItem = {
  title: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  description: string
  iconBg: string
  iconColor: string
  href: string
  accent: string
  details: KPIDetail[]
}

export function KPICards({ stats }: KPICardsProps) {
  const { t, locale } = useI18n()
  const resolvedClosed = stats.resolved + stats.closed
  const activeBacklog = stats.open + stats.inProgress + stats.pending
  const criticalShare = stats.total > 0 ? Math.round((stats.critical / stats.total) * 100) : 0

  const kpis: KPIItem[] = [
    {
      title: t("kpi.totalTickets"),
      value: stats.total,
      icon: FolderOpen,
      description: `${stats.open} ${t("kpi.opened")}`,
      iconBg: "bg-primary/10 dark:bg-primary/20",
      iconColor: "text-primary",
      href: "/tickets?view=total",
      accent: "from-primary/20 via-primary/10 to-transparent",
      details: [
        { label: t("status.open"), value: stats.open },
        { label: t("status.inProgress"), value: stats.inProgress },
        { label: t("status.pending"), value: stats.pending },
      ],
    },
    {
      title: t("kpi.inProgress"),
      value: stats.inProgress,
      icon: Loader2,
      description: `${stats.pending} ${t("kpi.pendingDesc")}`,
      iconBg: "bg-amber-50 dark:bg-amber-500/20",
      iconColor: "text-amber-600 dark:text-amber-300",
      href: "/tickets?view=in-progress",
      accent: "from-amber-300/30 via-amber-200/20 to-transparent",
      details: [
        { label: t("status.pending"), value: stats.pending },
        { label: t("status.open"), value: stats.open },
        { label: locale === "fr" ? "Backlog actif" : "Active backlog", value: activeBacklog },
      ],
    },
    {
      title: t("kpi.resolvedClosed"),
      value: resolvedClosed,
      icon: TicketCheck,
      description: `${t("kpi.rateDesc")}: ${stats.resolutionRate}%`,
      iconBg: "bg-emerald-50 dark:bg-emerald-500/20",
      iconColor: "text-emerald-600 dark:text-emerald-300",
      href: "/tickets?view=resolved",
      accent: "from-emerald-300/30 via-emerald-200/20 to-transparent",
      details: [
        { label: t("status.resolved"), value: stats.resolved },
        { label: t("status.closed"), value: stats.closed },
        { label: t("kpi.resolutionRate"), value: `${stats.resolutionRate}%` },
      ],
    },
    {
      title: t("kpi.critical"),
      value: stats.critical,
      icon: AlertTriangle,
      description: t("kpi.maxPriority"),
      iconBg: "bg-red-50 dark:bg-red-500/20",
      iconColor: "text-red-600 dark:text-red-300",
      href: "/tickets?view=critical",
      accent: "from-red-300/30 via-red-200/20 to-transparent",
      details: [
        { label: t("kpi.totalTickets"), value: stats.total },
        { label: locale === "fr" ? "Part critique" : "Critical share", value: `${criticalShare}%` },
        { label: t("status.inProgress"), value: stats.inProgress },
      ],
    },
    {
      title: t("kpi.avgTime"),
      value: `${stats.avgResolutionDays}j`,
      icon: Clock,
      description: t("kpi.resolutionTime"),
      iconBg: "bg-blue-50 dark:bg-blue-500/20",
      iconColor: "text-blue-600 dark:text-blue-300",
      href: "/tickets?view=avg-time",
      accent: "from-blue-300/30 via-blue-200/20 to-transparent",
      details: [
        { label: t("status.resolved"), value: stats.resolved },
        { label: t("status.closed"), value: stats.closed },
        { label: t("kpi.resolutionRate"), value: `${stats.resolutionRate}%` },
      ],
    },
    {
      title: t("kpi.resolutionRate"),
      value: `${stats.resolutionRate}%`,
      icon: TrendingUp,
      description: t("kpi.thisMonth"),
      iconBg: "bg-primary/10 dark:bg-primary/20",
      iconColor: "text-primary",
      href: "/tickets?view=resolution-rate",
      accent: "from-primary/20 via-primary/10 to-transparent",
      details: [
        { label: locale === "fr" ? "Resolus/Fermes" : "Resolved/Closed", value: resolvedClosed },
        { label: t("kpi.totalTickets"), value: stats.total },
        { label: locale === "fr" ? "Backlog actif" : "Active backlog", value: activeBacklog },
      ],
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {kpis.map((kpi) => (
        <HoverCard key={kpi.title} openDelay={120} closeDelay={100}>
          <HoverCardTrigger asChild>
            <Link href={kpi.href} className="block">
              <Card className="surface-card overflow-hidden rounded-xl transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
                <CardContent className="relative overflow-hidden p-4">
                  <div className={cn("pointer-events-none absolute inset-x-0 top-0 h-12 bg-gradient-to-b", kpi.accent)} />
                  <div className="relative flex items-start justify-between">
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">{kpi.title}</p>
                      <p className="text-2xl font-bold text-foreground">{kpi.value}</p>
                    </div>
                    <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", kpi.iconBg)}>
                      <kpi.icon className={cn("h-4 w-4", kpi.iconColor)} />
                    </div>
                  </div>
                  <p className="relative mt-2 text-xs text-muted-foreground">{kpi.description}</p>
                </CardContent>
              </Card>
            </Link>
          </HoverCardTrigger>
          <HoverCardContent className="w-72 border-border/80 bg-background/95 p-0 shadow-xl backdrop-blur">
            <div className="rounded-lg border border-border/60 p-3">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{kpi.title}</p>
                <kpi.icon className={cn("h-4 w-4", kpi.iconColor)} />
              </div>
              <div className="grid grid-cols-3 gap-2">
                {kpi.details.map((item) => (
                  <div key={`${kpi.title}-${item.label}`} className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                    <p className="text-[10px] text-muted-foreground">{item.label}</p>
                    <p className="text-sm font-semibold text-foreground">{item.value}</p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-muted-foreground">
                {locale === "fr" ? "Cliquez pour ouvrir le detail filtre." : "Click to open filtered details."}
              </p>
            </div>
          </HoverCardContent>
        </HoverCard>
      ))}
    </div>
  )
}

function cn(...classes: (string | undefined | false)[]) {
  return classes.filter(Boolean).join(" ")
}
