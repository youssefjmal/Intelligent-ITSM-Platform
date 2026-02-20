"use client"

import React, { useEffect, useMemo, useState } from "react"
import { createPortal } from "react-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  const { t, locale } = useI18n()
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState<string>("all")
  const [selectedRec, setSelectedRec] = useState<Recommendation | null>(null)

  const stats = useMemo(() => {
    const total = recommendations.length
    const avgConfidence = total
      ? Math.round(recommendations.reduce((sum, rec) => sum + rec.confidence, 0) / total)
      : 0
    const highImpact = recommendations.filter((rec) => rec.impact === "high").length
    const patterns = recommendations.filter((rec) => rec.type === "pattern").length
    return { total, avgConfidence, highImpact, patterns }
  }, [recommendations])

  const insight = useMemo(() => {
    const safeTotal = Math.max(1, recommendations.length)
    const impactHigh = recommendations.filter((rec) => rec.impact === "high").length
    const impactMedium = recommendations.filter((rec) => rec.impact === "medium").length
    const impactLow = recommendations.filter((rec) => rec.impact === "low").length
    const typePattern = recommendations.filter((rec) => rec.type === "pattern").length
    const typePriority = recommendations.filter((rec) => rec.type === "priority").length
    const typeSolution = recommendations.filter((rec) => rec.type === "solution").length
    const typeWorkflow = recommendations.filter((rec) => rec.type === "workflow").length
    const topConfidence = [...recommendations].sort((a, b) => b.confidence - a.confidence)[0] || null
    const avgLinkedTickets = recommendations.length
      ? (recommendations.reduce((sum, rec) => sum + rec.relatedTickets.length, 0) / recommendations.length).toFixed(1)
      : "0.0"

    return {
      impactHigh,
      impactMedium,
      impactLow,
      typePattern,
      typePriority,
      typeSolution,
      typeWorkflow,
      topConfidence,
      avgLinkedTickets,
      highPct: Math.round((impactHigh / safeTotal) * 100),
      patternPct: Math.round((typePattern / safeTotal) * 100),
    }
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
          hoverDetails={[
            { label: locale === "fr" ? "Total recommandations" : "Total recommendations", value: stats.total.toString() },
            { label: locale === "fr" ? "Impact eleve" : "High impact", value: stats.highImpact.toString() },
            { label: locale === "fr" ? "Patterns" : "Patterns", value: stats.patterns.toString() },
            { label: locale === "fr" ? "Tickets lies / reco (moy.)" : "Linked tickets / rec (avg)", value: insight.avgLinkedTickets },
          ]}
          hoverNote={
            locale === "fr"
              ? `${insight.highPct}% des recommandations sont a impact eleve.`
              : `${insight.highPct}% of recommendations are high impact.`
          }
        />
        <StatCard
          icon={Target}
          title={t("recs.avgConfidence")}
          value={`${stats.avgConfidence}%`}
          description={t("recs.accuracy")}
          iconColor="text-blue-600"
          hoverDetails={[
            { label: t("recs.avgConfidence"), value: `${stats.avgConfidence}%` },
            { label: locale === "fr" ? "Confiance max" : "Top confidence", value: `${Math.max(0, ...recommendations.map((rec) => rec.confidence))}%` },
            { label: locale === "fr" ? "Confiance min" : "Lowest confidence", value: `${recommendations.length ? Math.min(...recommendations.map((rec) => rec.confidence)) : 0}%` },
            { label: locale === "fr" ? "Reco la plus fiable" : "Most reliable rec", value: insight.topConfidence?.id || "-" },
          ]}
          hoverNote={
            locale === "fr"
              ? `${insight.topConfidence?.title || "Aucune recommandation"}`
              : `${insight.topConfidence?.title || "No recommendation available"}`
          }
        />
        <StatCard
          icon={AlertTriangle}
          title={t("recs.highImpact")}
          value={stats.highImpact.toString()}
          description={t("recs.treatFirst")}
          iconColor="text-red-600"
          hoverDetails={[
            { label: t("recs.impactHigh"), value: recommendations.filter((rec) => rec.impact === "high").length.toString() },
            { label: t("recs.impactMedium"), value: recommendations.filter((rec) => rec.impact === "medium").length.toString() },
            { label: t("recs.impactLow"), value: recommendations.filter((rec) => rec.impact === "low").length.toString() },
            { label: locale === "fr" ? "Part impact eleve" : "High-impact share", value: `${insight.highPct}%` },
          ]}
          hoverNote={
            locale === "fr"
              ? "Prioriser ces recommandations pour maximiser le gain operationnel."
              : "Prioritize these recommendations for maximum operational gain."
          }
        />
        <StatCard
          icon={TrendingUp}
          title={t("recs.patternsDetected")}
          value={stats.patterns.toString()}
          description={t("kpi.thisMonth")}
          iconColor="text-amber-600"
          hoverDetails={[
            { label: t("recs.patterns"), value: recommendations.filter((rec) => rec.type === "pattern").length.toString() },
            { label: t("recs.workflows"), value: recommendations.filter((rec) => rec.type === "workflow").length.toString() },
            { label: t("recs.priorities"), value: recommendations.filter((rec) => rec.type === "priority").length.toString() },
            { label: t("recs.solutions"), value: insight.typeSolution.toString() },
            { label: locale === "fr" ? "Part patterns" : "Pattern share", value: `${insight.patternPct}%` },
          ]}
          hoverNote={
            locale === "fr"
              ? "Les patterns repetitifs signalent des causes racines stables."
              : "Recurring patterns usually point to stable root causes."
          }
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
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedRec(rec)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      setSelectedRec(rec)
                    }
                  }}
                  className="w-full text-left"
                >
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
                              {rec.relatedTickets.slice(0, 6).map((tid) => (
                                <Link
                                  key={tid}
                                  href={`/tickets/${tid}`}
                                  className="text-xs font-mono text-primary hover:underline"
                                  onClick={(event) => event.stopPropagation()}
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
                          <p className="text-[11px] font-medium text-primary/80">
                            {locale === "fr" ? "Cliquer pour voir le detail" : "Click to view full details"}
                          </p>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      <Dialog open={Boolean(selectedRec)} onOpenChange={(open) => !open && setSelectedRec(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto border-border/80 sm:max-w-2xl">
          {selectedRec ? (
            <>
              <DialogHeader>
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Badge className={`${TYPE_CONFIG[selectedRec.type].color} text-[10px]`}>
                    {selectedRec.type === "pattern"
                      ? t("recs.pattern")
                      : selectedRec.type === "priority"
                        ? t("recs.priority")
                        : selectedRec.type === "solution"
                          ? t("recs.solution")
                          : t("recs.workflow")}
                  </Badge>
                  <Badge variant="outline" className={`${IMPACT_CONFIG[selectedRec.impact].color} text-[10px]`}>
                    {selectedRec.impact === "high"
                      ? t("recs.impactHigh")
                      : selectedRec.impact === "medium"
                        ? t("recs.impactMedium")
                        : t("recs.impactLow")}
                  </Badge>
                </div>
                <DialogTitle className="text-xl font-semibold text-foreground">
                  {selectedRec.title}
                </DialogTitle>
                <DialogDescription className="text-sm leading-relaxed text-muted-foreground">
                  {selectedRec.description}
                </DialogDescription>
              </DialogHeader>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("recs.confidence")}</p>
                  <p className="mt-1 text-2xl font-bold text-foreground">{selectedRec.confidence}%</p>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{locale === "fr" ? "Cree le" : "Created"}</p>
                  <p className="mt-1 text-sm font-semibold text-foreground">{formatDate(selectedRec.createdAt, locale)}</p>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{locale === "fr" ? "Tickets lies" : "Linked tickets"}</p>
                  <p className="mt-1 text-2xl font-bold text-foreground">{selectedRec.relatedTickets.length}</p>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-semibold text-foreground">{locale === "fr" ? "Plan d'execution" : "Execution plan"}</p>
                <ul className="space-y-2">
                  <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2 text-sm text-muted-foreground">
                    {locale === "fr"
                      ? "Valider ce point avec l'equipe support et confirmer le scope."
                      : "Validate this recommendation with support stakeholders and confirm scope."}
                  </li>
                  <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2 text-sm text-muted-foreground">
                    {locale === "fr"
                      ? "Appliquer l'action sur les tickets lies en priorite."
                      : "Apply the action first on linked tickets with highest urgency."}
                  </li>
                  <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2 text-sm text-muted-foreground">
                    {locale === "fr"
                      ? "Mesurer l'impact apres execution et mettre a jour le workflow."
                      : "Measure impact after rollout and update the workflow/runbook."}
                  </li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-semibold text-foreground">{t("recs.relatedTickets")}</p>
                <div className="flex flex-wrap gap-2">
                  {selectedRec.relatedTickets.map((ticketId) => (
                    <Link
                      key={`${selectedRec.id}-${ticketId}`}
                      href={`/tickets/${ticketId}`}
                      className="rounded-md border border-primary/25 bg-primary/5 px-2 py-1 text-xs font-mono text-primary transition-colors hover:bg-primary/10"
                      onClick={() => setSelectedRec(null)}
                    >
                      {ticketId}
                    </Link>
                  ))}
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function formatDate(value: string, locale: "fr" | "en"): string {
  const date = new Date(value)
  return date.toLocaleString(locale === "fr" ? "fr-FR" : "en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function StatCard({
  icon: Icon,
  title,
  value,
  description,
  iconColor,
  hoverDetails,
  hoverNote,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  value: string
  description: string
  iconColor: string
  hoverDetails: Array<{ label: string; value: string }>
  hoverNote: string
}) {
  const [hovered, setHovered] = useState(false)
  const [pointer, setPointer] = useState({ x: 0, y: 0 })

  return (
    <>
      <Card
        className="border border-border transition-colors hover:border-primary/40"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onMouseMove={(event) => setPointer({ x: event.clientX + 14, y: event.clientY + 14 })}
      >
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
      {hovered && typeof window !== "undefined"
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[9999] hidden min-w-56 rounded-xl border border-border/80 bg-background/95 p-3 shadow-xl backdrop-blur md:block"
              style={{ left: pointer.x, top: pointer.y }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
              <div className="mt-2 space-y-1.5">
                {hoverDetails.map((row) => (
                  <div key={`${title}-${row.label}`} className="flex items-center justify-between gap-3 text-xs">
                    <span className="text-muted-foreground">{row.label}</span>
                    <span className="font-semibold text-foreground">{row.value}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 border-t border-border/60 pt-2">
                <p className="text-[11px] leading-relaxed text-muted-foreground">{hoverNote}</p>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  )
}
