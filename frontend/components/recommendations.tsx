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

const TYPE_CONFIG = {
  pattern: { label: "Pattern", icon: TrendingUp, color: "bg-blue-100 text-blue-800" },
  priority: { label: "Priorite", icon: AlertTriangle, color: "bg-amber-100 text-amber-800" },
  solution: { label: "Solution", icon: Lightbulb, color: "bg-emerald-100 text-emerald-800" },
  workflow: { label: "Workflow", icon: Zap, color: "bg-purple-100 text-purple-800" },
}

const IMPACT_CONFIG = {
  high: { label: "Impact Eleve", color: "bg-red-50 text-red-700 border-red-200" },
  medium: { label: "Impact Moyen", color: "bg-amber-50 text-amber-700 border-amber-200" },
  low: { label: "Impact Faible", color: "bg-slate-50 text-slate-600 border-slate-200" },
}

export function RecommendationsPanel() {
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
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        Chargement des recommandations...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={BrainCircuit}
          title="Recommandations"
          value={stats.total.toString()}
          description="Generees par l'IA"
          iconColor="text-primary"
        />
        <StatCard
          icon={Target}
          title="Confiance Moyenne"
          value={`${stats.avgConfidence}%`}
          description="Taux de precision"
          iconColor="text-blue-600"
        />
        <StatCard
          icon={AlertTriangle}
          title="Impact Eleve"
          value={stats.highImpact.toString()}
          description="A traiter en priorite"
          iconColor="text-red-600"
        />
        <StatCard
          icon={TrendingUp}
          title="Patterns Detectes"
          value={stats.patterns.toString()}
          description="Ce mois-ci"
          iconColor="text-amber-600"
        />
      </div>

      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {["all", "pattern", "priority", "solution", "workflow"].map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(f)}
              className={filter === f ? "bg-primary text-primary-foreground" : ""}
            >
              {f === "all"
                ? "Tout"
                : f === "pattern"
                  ? "Patterns"
                  : f === "priority"
                    ? "Priorites"
                    : f === "solution"
                      ? "Solutions"
                      : "Workflows"}
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
          Actualiser
        </Button>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          Aucune recommandation disponible pour le moment.
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((rec) => {
            const typeConfig = TYPE_CONFIG[rec.type]
            const impactConfig = IMPACT_CONFIG[rec.impact]
            const TypeIcon = typeConfig.icon

            return (
              <Card key={rec.id} className="border border-border hover:border-primary/30 transition-colors">
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
                          <Badge className={`${typeConfig.color} border-0 text-[10px]`}>
                            {typeConfig.label}
                          </Badge>
                          <Badge
                            variant="outline"
                            className={`${impactConfig.color} text-[10px]`}
                          >
                            {impactConfig.label}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {rec.description}
                        </p>
                        <div className="flex flex-wrap items-center gap-3 pt-1">
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-muted-foreground">Tickets lies:</span>
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
                            Confiance: {rec.confidence}%
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
