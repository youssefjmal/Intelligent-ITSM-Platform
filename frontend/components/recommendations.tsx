"use client"

import React, { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  BrainCircuit,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  RefreshCw,
  Target,
  Zap,
} from "lucide-react"
import Link from "next/link"
import { fetchRecommendations, type Recommendation } from "@/lib/recommendations-api"
import { useI18n } from "@/lib/i18n"

const TYPE_CONFIG = {
  pattern: { icon: TrendingUp, color: "bg-sky-100 text-sky-800 border border-sky-200" },
  priority: { icon: AlertTriangle, color: "bg-amber-100 text-amber-800 border border-amber-200" },
  solution: { icon: Lightbulb, color: "bg-emerald-100 text-emerald-800 border border-emerald-200" },
  workflow: { icon: Zap, color: "bg-teal-100 text-teal-800 border border-teal-200" },
}

const IMPACT_CONFIG = {
  high: { color: "bg-red-50 text-red-700 border-red-200" },
  medium: { color: "bg-amber-50 text-amber-700 border-amber-200" },
  low: { color: "bg-slate-50 text-slate-600 border-slate-200" },
}

export function RecommendationsPanel() {
  const { t } = useI18n()
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState<string>("all")

  const stats = useMemo(() => {
    const total = recommendations.length
    const avgConfidence = total
      ? Math.round(recommendations.reduce((sum, rec) => sum + rec.confidence, 0) / total)
      : 0
    const highImpact = recommendations.filter((rec) => rec.impact === "high").length
    const patterns = recommendations.filter((rec) => rec.type === "pattern").length
    return { total, avgConfidence, highImpact, patterns }
  }, [recommendations])

  const filtered =
    filter === "all"
      ? recommendations
      : recommendations.filter((rec) => rec.type === filter)

  async function loadRecommendations() {
    try {
      const data = await fetchRecommendations()
      setRecommendations(data)
    } catch {
      setRecommendations([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecommendations()
  }, [])

  async function handleRefresh() {
    setRefreshing(true)
    await loadRecommendations()
    setRefreshing(false)
  }

  if (loading) {
    return (
      <div className="surface-card rounded-xl p-6 text-sm text-muted-foreground">
        {t("general.loading")}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 fade-slide-in">
        <StatCard
          icon={BrainCircuit}
          title={t("recs.recommendations")}
          value={stats.total.toString()}
          description={t("recs.generated")}
          iconColor="text-primary"
        />
        <StatCard
          icon={Target}
          title={t("recs.avgConfidence")}
          value={`${stats.avgConfidence}%`}
          description={t("recs.accuracy")}
          iconColor="text-blue-600"
        />
        <StatCard
          icon={AlertTriangle}
          title={t("recs.highImpact")}
          value={stats.highImpact.toString()}
          description={t("recs.treatFirst")}
          iconColor="text-red-600"
        />
        <StatCard
          icon={TrendingUp}
          title={t("recs.patternsDetected")}
          value={stats.patterns.toString()}
          description={t("kpi.thisMonth")}
          iconColor="text-amber-600"
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          {["all", "pattern", "priority", "solution", "workflow"].map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(f)}
              className={filter === f ? "bg-primary text-primary-foreground" : "bg-card/80"}
            >
              {f === "all"
                ? t("recs.all")
                : f === "pattern"
                  ? t("recs.patterns")
                  : f === "priority"
                    ? t("recs.priorities")
                    : f === "solution"
                      ? t("recs.solutions")
                      : t("recs.workflows")}
            </Button>
          ))}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="gap-2 bg-transparent"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          {t("recs.refresh")}
        </Button>
      </div>

      {filtered.length === 0 ? (
        <div className="surface-card rounded-xl p-6 text-sm text-muted-foreground">
          {t("dashboard.problemNoData")}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((rec) => {
            const typeConfig = TYPE_CONFIG[rec.type]
            const impactConfig = IMPACT_CONFIG[rec.impact]
            const TypeIcon = typeConfig.icon

            return (
              <Card key={rec.id} className="surface-card overflow-hidden transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
                <div className="h-1.5 bg-gradient-to-r from-primary/80 via-emerald-500/80 to-amber-500/80" />
                <CardContent className="p-5">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex gap-3 flex-1">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <TypeIcon className="h-4 w-4 text-primary" />
                      </div>
                      <div className="flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-semibold text-foreground">
                            {rec.title}
                          </h3>
                          <Badge className={`${typeConfig.color} text-[10px]`}>
                            {rec.type === "pattern"
                              ? t("recs.pattern")
                              : rec.type === "priority"
                                ? t("recs.priority")
                                : rec.type === "solution"
                                  ? t("recs.solution")
                                  : t("recs.workflow")}
                          </Badge>
                          <Badge
                            variant="outline"
                            className={`${impactConfig.color} text-[10px]`}
                          >
                            {rec.impact === "high"
                              ? t("recs.impactHigh")
                              : rec.impact === "medium"
                                ? t("recs.impactMedium")
                                : t("recs.impactLow")}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {rec.description}
                        </p>
                        <div className="flex flex-wrap items-center gap-3 pt-1">
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-muted-foreground">{t("recs.relatedTickets")}:</span>
                            {rec.relatedTickets.map((tid) => (
                              <Link
                                key={tid}
                                href={`/tickets/${tid}`}
                                className="text-xs font-mono text-primary hover:underline"
                              >
                                {tid}
                              </Link>
                            ))}
                          </div>
                          <Separator orientation="vertical" className="h-3" />
                          <span className="text-xs text-muted-foreground">
                            {t("recs.confidence")}: {rec.confidence}%
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

function StatCard({
  icon: Icon,
  title,
  value,
  description,
  iconColor,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  value: string
  description: string
  iconColor: string
}) {
  return (
    <Card className="border border-border">
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground">{title}</p>
            <p className="text-2xl font-bold text-foreground mt-1">{value}</p>
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
            <Icon className={`h-4 w-4 ${iconColor}`} />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-2">{description}</p>
      </CardContent>
    </Card>
  )
}
