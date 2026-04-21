"use client"

import { useEffect, useMemo, useState } from "react"
import { RefreshCw } from "lucide-react"

import {
  confidenceBandClass,
  confidenceBandLabel,
  recommendationModeLabel,
  sourceLabelText,
} from "@/components/recommendation-sections"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchRecommendationFeedbackAnalytics,
  type RecommendationFeedbackAnalytics,
  type RecommendationFeedbackSummary,
  type RecommendationFeedbackSurface,
} from "@/lib/ai-feedback-api"
import { useI18n } from "@/lib/i18n"

type SurfaceFilter = "all" | RecommendationFeedbackSurface

type SummaryRow = {
  key: string
  label: string
  summary: RecommendationFeedbackSummary
}

type AnalyticsCardProps = {
  title: string
  value: string | number
  subtitle: string
  tone?: string
}

function percent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

function formatSurfaceLabel(surface: string, locale: "fr" | "en"): string {
  if (surface === "ticket_detail") {
    return locale === "fr" ? "Detail ticket" : "Ticket detail"
  }
  if (surface === "recommendations_page") {
    return locale === "fr" ? "Page recommandations" : "Recommendations page"
  }
  return surface || (locale === "fr" ? "Inconnu" : "Unknown")
}

function formatDisplayModeLabel(mode: string, locale: "fr" | "en"): string {
  if (mode === "evidence_action") {
    return locale === "fr" ? "Action appuyee" : "Evidence action"
  }
  if (mode === "tentative_diagnostic") {
    return locale === "fr" ? "Etape diagnostique" : "Diagnostic next step"
  }
  if (mode === "service_request") {
    return locale === "fr" ? "Workflow planifie" : "Planned workflow"
  }
  if (mode === "no_strong_match" || mode === "llm_general_knowledge") {
    return locale === "fr" ? "Repli guide par l'IA" : "AI-guided fallback"
  }
  return mode || (locale === "fr" ? "Inconnu" : "Unknown")
}

function formatSummaryRows(
  rows: Record<string, RecommendationFeedbackSummary>,
  formatter: (key: string) => string,
): SummaryRow[] {
  return Object.entries(rows)
    .map(([key, summary]) => ({
      key,
      label: formatter(key),
      summary,
    }))
    .sort((left, right) => {
      if (right.summary.totalFeedback !== left.summary.totalFeedback) {
        return right.summary.totalFeedback - left.summary.totalFeedback
      }
      return right.summary.appliedRate - left.summary.appliedRate
    })
}

function analyticsTone(rate: number, accent: "emerald" | "blue" | "rose" | "slate"): string {
  if (accent === "emerald") {
    return rate >= 0.7 ? "border-emerald-300 bg-emerald-50/80" : "border-emerald-200 bg-emerald-50/60"
  }
  if (accent === "blue") {
    return rate >= 0.5 ? "border-blue-300 bg-blue-50/80" : "border-blue-200 bg-blue-50/60"
  }
  if (accent === "rose") {
    return rate >= 0.4 ? "border-rose-300 bg-rose-50/80" : "border-rose-200 bg-rose-50/60"
  }
  return "border-slate-200 bg-slate-50/70"
}

function AnalyticsCard({ title, value, subtitle, tone = "border-border/70 bg-card/70" }: AnalyticsCardProps) {
  return (
    <Card className={`surface-card overflow-hidden rounded-2xl border transition-all hover:-translate-y-0.5 hover:shadow-md ${tone}`}>
      <CardContent className="p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
        <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
        <p className="mt-2 text-xs text-muted-foreground">{subtitle}</p>
      </CardContent>
    </Card>
  )
}

export function AIFeedbackAnalytics() {
  const { locale } = useI18n()
  const isFr = locale === "fr"
  const [surface, setSurface] = useState<SurfaceFilter>("all")
  const [analytics, setAnalytics] = useState<RecommendationFeedbackAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadAnalytics = async (selectedSurface: SurfaceFilter, showSpinner = false) => {
    if (showSpinner) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)
    try {
      const payload = await fetchRecommendationFeedbackAnalytics(selectedSurface === "all" ? null : selectedSurface)
      setAnalytics(payload)
    } catch {
      setAnalytics(null)
      setError(isFr ? "Impossible de charger les analytics IA." : "Could not load AI analytics.")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadAnalytics(surface).catch(() => {})
  }, [surface]) // eslint-disable-line react-hooks/exhaustive-deps

  const surfaceRows = useMemo(
    () => formatSummaryRows(analytics?.bySurface || {}, (key) => formatSurfaceLabel(key, locale)),
    [analytics?.bySurface, locale],
  )
  const displayModeRows = useMemo(
    () => formatSummaryRows(analytics?.byDisplayMode || {}, (key) => formatDisplayModeLabel(key, locale)),
    [analytics?.byDisplayMode, locale],
  )
  const confidenceRows = useMemo(
    () => formatSummaryRows(analytics?.byConfidenceBand || {}, (key) => confidenceBandLabel(key, locale)),
    [analytics?.byConfidenceBand, locale],
  )
  const recommendationModeRows = useMemo(
    () => formatSummaryRows(analytics?.byRecommendationMode || {}, (key) => recommendationModeLabel(key, locale)),
    [analytics?.byRecommendationMode, locale],
  )
  const sourceLabelRows = useMemo(
    () => formatSummaryRows(analytics?.bySourceLabel || {}, (key) => sourceLabelText(key, locale)),
    [analytics?.bySourceLabel, locale],
  )

  const primaryCards = [
    {
      title: isFr ? "Retours IA" : "AI feedback",
      value: analytics?.totalFeedback ?? 0,
      subtitle: isFr ? "Retours agents enregistres sur les recommandations." : "Agent votes captured on AI recommendations.",
      tone: "border-slate-200 bg-slate-50/70",
    },
    {
      title: isFr ? "Taux utile" : "Useful rate",
      value: percent(analytics?.usefulnessRate ?? 0),
      subtitle: `${analytics?.usefulCount ?? 0} ${isFr ? "retours utiles" : "useful votes"}`,
      tone: analyticsTone(analytics?.usefulnessRate ?? 0, "emerald"),
    },
    {
      title: isFr ? "Taux applique" : "Applied rate",
      value: percent(analytics?.appliedRate ?? 0),
      subtitle: `${analytics?.appliedCount ?? 0} ${isFr ? "appliquees" : "applied"}`,
      tone: analyticsTone(analytics?.appliedRate ?? 0, "blue"),
    },
    {
      title: isFr ? "Taux rejete" : "Rejected rate",
      value: percent(analytics?.rejectionRate ?? 0),
      subtitle: `${analytics?.rejectedCount ?? 0} ${isFr ? "rejetees" : "rejected"}`,
      tone: analyticsTone(analytics?.rejectionRate ?? 0, "rose"),
    },
  ]

  const highlightCards = [
    {
      title: isFr ? "Surface principale" : "Top surface",
      value: surfaceRows[0]?.label || "-",
      subtitle: surfaceRows[0]
        ? `${surfaceRows[0].summary.totalFeedback} ${isFr ? "retours" : "feedback items"}`
        : isFr
          ? "Pas encore de donnees"
          : "No data yet",
      badgeClassName: "border-slate-300 bg-slate-50 text-slate-700",
      badgeText: surfaceRows[0] ? String(surfaceRows[0].summary.totalFeedback) : "0",
    },
    {
      title: isFr ? "Bande dominante" : "Top confidence band",
      value: confidenceRows[0]?.label || "-",
      subtitle: confidenceRows[0]
        ? `${isFr ? "Appliquees" : "Applied"} ${percent(confidenceRows[0].summary.appliedRate)}`
        : isFr
          ? "Pas encore de donnees"
          : "No data yet",
      badgeClassName: confidenceRows[0] ? confidenceBandClass(confidenceRows[0].key) : "border-slate-300 bg-slate-50 text-slate-700",
      badgeText: confidenceRows[0] ? String(confidenceRows[0].summary.totalFeedback) : "0",
    },
    {
      title: isFr ? "Mode dominant" : "Top recommendation mode",
      value: recommendationModeRows[0]?.label || "-",
      subtitle: recommendationModeRows[0]
        ? `${isFr ? "Utiles" : "Useful"} ${percent(recommendationModeRows[0].summary.usefulnessRate)}`
        : isFr
          ? "Pas encore de donnees"
          : "No data yet",
      badgeClassName: "border-indigo-300 bg-indigo-50 text-indigo-700",
      badgeText: recommendationModeRows[0] ? String(recommendationModeRows[0].summary.totalFeedback) : "0",
    },
    {
      title: isFr ? "Source la plus evaluee" : "Most evaluated source",
      value: sourceLabelRows[0]?.label || "-",
      subtitle: sourceLabelRows[0]
        ? `${isFr ? "Mode affichage" : "Display mode"}: ${displayModeRows[0]?.label || "-"}`
        : isFr
          ? "Pas encore de donnees"
          : "No data yet",
      badgeClassName: "border-amber-300 bg-amber-50 text-amber-700",
      badgeText: sourceLabelRows[0] ? String(sourceLabelRows[0].summary.totalFeedback) : "0",
    },
  ]

  return (
    <section className="surface-card fade-slide-in space-y-4 rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-foreground">
            {isFr ? "Boucle de feedback IA" : "AI feedback loop"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {isFr
              ? "Cartes resumees pour suivre l'acceptation et l'application des recommandations IA."
              : "Simple summary cards that track how often AI recommendations are accepted and applied."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={surface} onValueChange={(value) => setSurface(value as SurfaceFilter)}>
            <SelectTrigger className="h-9 w-[210px] rounded-xl bg-background/70">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{isFr ? "Toutes les surfaces" : "All surfaces"}</SelectItem>
              <SelectItem value="ticket_detail">{isFr ? "Detail ticket" : "Ticket detail"}</SelectItem>
              <SelectItem value="recommendations_page">{isFr ? "Page recommandations" : "Recommendations page"}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 rounded-xl"
            disabled={loading || refreshing}
            onClick={() => loadAnalytics(surface, true).catch(() => {})}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {isFr ? "Actualiser" : "Refresh"}
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={`feedback-analytics-skeleton-${index}`} className="rounded-xl border border-border/70 bg-card/70 p-4">
              <Skeleton className="h-3 w-28" />
              <Skeleton className="mt-3 h-8 w-24" />
              <Skeleton className="mt-2 h-3 w-32" />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {primaryCards.map((card) => (
              <AnalyticsCard
                key={card.title}
                title={card.title}
                value={card.value}
                subtitle={card.subtitle}
                tone={card.tone}
              />
            ))}
          </div>

          {error ? <p className="text-xs text-destructive">{error}</p> : null}

          {!analytics || analytics.totalFeedback === 0 ? (
            <div className="rounded-xl border border-dashed border-border/80 bg-muted/10 p-5 text-sm text-muted-foreground">
              {isFr
                ? "Aucun feedback IA enregistre pour le moment. Les agents pourront alimenter ces cartes depuis le detail ticket et la page recommandations."
                : "No AI feedback has been recorded yet. Agents can populate these cards from ticket detail and the recommendations page."}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {highlightCards.map((card) => (
                <Card key={card.title} className="surface-card overflow-hidden rounded-2xl border border-border/70 bg-card/70">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{card.title}</p>
                        <p className="text-sm font-semibold leading-snug text-foreground">{card.value}</p>
                      </div>
                      <Badge className={`border text-[10px] ${card.badgeClassName}`}>{card.badgeText}</Badge>
                    </div>
                    <p className="mt-3 text-xs text-muted-foreground">{card.subtitle}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
