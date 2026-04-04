"use client"

import React, { useEffect, useMemo, useState } from "react"
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
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  BrainCircuit,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  RefreshCw,
  Target,
  Zap,
  Search,
  X,
  ArrowUpDown,
} from "lucide-react"
import Link from "next/link"
import { fetchRecommendations, fetchSlaStrategies, type Recommendation, type SlaStrategies } from "@/lib/recommendations-api"
import { fetchTickets } from "@/lib/tickets-api"
import { type Ticket } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import {
  submitRecommendationFeedback,
  type RecommendationFeedbackResponse,
  type RecommendationFeedbackType,
} from "@/lib/ai-feedback-api"
import { RecommendationFeedbackControls } from "@/components/recommendation-feedback-controls"
import {
  LLMAdvisoryBlock,
  RecommendationActionBlock,
  RecommendationEvidenceAccordion,
  RecommendationMatchBlock,
  RecommendationNextActionsBlock,
  RecommendationReasoningBlock,
  RecommendationRootCauseBlock,
  RecommendationSupportingContextBlock,
  RecommendationWhyMatchesBlock,
  confidenceBadgeClass,
  confidenceBandClass,
  confidenceBandLabel,
  evidenceTypeLabel,
  formatConfidencePercent,
  primaryEvidenceType,
  recommendationModeLabel,
  recommendationStatusLabel,
  sourceLabelText,
} from "@/components/recommendation-sections"
import { HoverDetails } from "@/components/hover-details"
import { ConfidenceBar } from "@/components/ui/confidence-bar"

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

function buildExecutionSteps(rec: Recommendation, locale: "fr" | "en"): string[] {
  const action = String(rec.recommendedAction || rec.description || "").trim()
  if (!action) {
    return []
  }
  const normalized = action.replace(/\.$/, "")
  const clauses = normalized
    .split(/(?:\.\s+|;\s+|,\s+then\s+|\s+then\s+|\s+et\s+ensuite\s+|\s+puis\s+)/i)
    .map((item) => item.trim())
    .filter(Boolean)
  const steps: string[] = []
  if (clauses[0]) {
    steps.push(clauses[0].replace(/^[a-z]/, (letter) => letter.toUpperCase()))
  }
  if (clauses[1]) {
    steps.push(clauses[1].replace(/^[a-z]/, (letter) => letter.toUpperCase()))
  } else {
    steps.push(
      locale === "fr"
        ? "Valider le resultat sur les tickets lies et les utilisateurs affectes."
        : "Validate the outcome across linked tickets and affected users."
    )
  }
  steps.push(
    locale === "fr"
      ? "Documenter l'evidence utilisee, mettre a jour le ticket et confirmer la cloture."
      : "Document the supporting evidence, update the ticket, and confirm closure."
  )
  return steps.slice(0, 3)
}

function buildOperationalSteps(rec: Recommendation, locale: "fr" | "en"): string[] {
  if (rec.nextBestActions.length > 0) {
    return rec.nextBestActions.slice(0, 4)
  }
  return buildExecutionSteps(rec, locale)
}

function buildHoverNote(text?: string | null, fallback?: string | null, limit = 180): string {
  const candidate = String(text || fallback || "").replace(/\s+/g, " ").trim()
  if (!candidate) {
    return ""
  }
  return candidate.length > limit ? `${candidate.slice(0, limit - 1)}...` : candidate
}

function buildRecommendationHoverDetails(rec: Recommendation, locale: "fr" | "en") {
  const primaryEvidence = primaryEvidenceType(rec.evidenceSources)
  return [
    {
      label: locale === "fr" ? "Confiance" : "Confidence",
      value: `${formatConfidencePercent(rec.confidence)}% (${confidenceBandLabel(rec.confidenceBand, locale)})`,
    },
    {
      label: locale === "fr" ? "Mode" : "Mode",
      value: recommendationModeLabel(rec.recommendationMode, locale),
    },
    {
      label: locale === "fr" ? "Source" : "Source",
      value: sourceLabelText(rec.sourceLabel, locale),
    },
    {
      label: locale === "fr" ? "Type d'evidence" : "Evidence type",
      value: primaryEvidence ? evidenceTypeLabel(primaryEvidence, locale) : (locale === "fr" ? "Aucune" : "None"),
    },
    {
      label: locale === "fr" ? "Tickets lies" : "Linked tickets",
      value: String(rec.relatedTickets.length),
    },
    {
      label: locale === "fr" ? "Evidence" : "Evidence",
      value: String(rec.evidenceSources.length),
    },
    {
      label: locale === "fr" ? "Creee" : "Created",
      value: formatDate(rec.createdAt, locale),
    },
  ]
}

export function RecommendationsPanel() {
  const { t, locale } = useI18n()
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [slaStrategies, setSlaStrategies] = useState<SlaStrategies | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState<string>("all")
  const [search, setSearch] = useState<string>("")
  const [impactFilter, setImpactFilter] = useState<string>("all")
  const [confidenceFilter, setConfidenceFilter] = useState<string>("all")
  const [sortOrder, setSortOrder] = useState<"newest" | "confidence" | "impact">("newest")
  const [selectedRec, setSelectedRec] = useState<Recommendation | null>(null)
  const [feedbackSubmittingById, setFeedbackSubmittingById] = useState<Record<string, boolean>>({})
  const [feedbackMessageById, setFeedbackMessageById] = useState<Record<string, string>>({})

  const stats = useMemo(() => {
    const total = recommendations.length
    const avgConfidence = total
      ? Math.round(recommendations.reduce((sum, rec) => sum + formatConfidencePercent(rec.confidence), 0) / total)
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

  const filteredRecommendations = useMemo(() => {
    const q = search.trim().toLowerCase()
    let result = recommendations.filter((rec) => {
      if (q) {
        const haystack = [
          rec.id,
          rec.title,
          rec.description,
          rec.recommendedAction ?? "",
          ...rec.relatedTickets,
        ]
          .join(" ")
          .toLowerCase()
        if (!haystack.includes(q)) return false
      }
      if (filter !== "all" && rec.type !== filter) return false
      if (impactFilter !== "all" && rec.impact !== impactFilter) return false
      if (confidenceFilter !== "all") {
        const pct = rec.confidence
        if (confidenceFilter === "high" && pct < 0.78) return false
        if (confidenceFilter === "medium" && (pct >= 0.78 || pct < 0.52)) return false
        if (confidenceFilter === "low" && pct >= 0.52) return false
      }
      return true
    })
    if (sortOrder === "newest") {
      result = [...result].sort((a, b) =>
        new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      )
    } else if (sortOrder === "confidence") {
      result = [...result].sort((a, b) => b.confidence - a.confidence)
    } else if (sortOrder === "impact") {
      const order = { high: 0, medium: 1, low: 2 }
      result = [...result].sort(
        (a, b) =>
          (order[a.impact as keyof typeof order] ?? 3) -
          (order[b.impact as keyof typeof order] ?? 3)
      )
    }
    return result
  }, [recommendations, search, filter, impactFilter, confidenceFilter, sortOrder])

  const activeFilterCount = [
    search.trim() !== "",
    filter !== "all",
    impactFilter !== "all",
    confidenceFilter !== "all",
    sortOrder !== "newest",
  ].filter(Boolean).length

  const slaContext = useMemo(() => {
    const activeStatuses = new Set(["open", "in-progress", "waiting-for-customer", "waiting-for-support-vendor", "pending"])
    const active = tickets.filter((ticket) => activeStatuses.has(ticket.status))
    const breached = active.filter((ticket) => ticket.slaStatus === "breached")
    const atRisk = active
      .filter((ticket) => ticket.slaStatus === "at_risk")
      .sort((a, b) => {
        const left = Number.isFinite(a.slaRemainingMinutes) ? Number(a.slaRemainingMinutes) : 999999
        const right = Number.isFinite(b.slaRemainingMinutes) ? Number(b.slaRemainingMinutes) : 999999
        return left - right
      })
    return {
      activeCount: active.length,
      breachedCount: breached.length,
      atRiskCount: atRisk.length,
      urgentAtRisk: atRisk.slice(0, 3),
    }
  }, [tickets])

  async function loadRecommendations() {
    try {
      const [data, ticketRows, strategies] = await Promise.all([
        fetchRecommendations(locale),
        fetchTickets(),
        fetchSlaStrategies(locale),
      ])
      setRecommendations(data)
      setTickets(ticketRows)
      setSlaStrategies(strategies)
    } catch {
      setRecommendations([])
      setTickets([])
      setSlaStrategies(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecommendations()
  }, [locale])

  async function handleRefresh() {
    setRefreshing(true)
    await loadRecommendations()
    setRefreshing(false)
  }

  function applyFeedbackResult(recommendationId: string, result: RecommendationFeedbackResponse) {
    setRecommendations((current) =>
      current.map((row) =>
        row.id === recommendationId
          ? {
              ...row,
              currentUserFeedback: result.currentFeedback,
              feedbackSummary: result.feedbackSummary,
            }
          : row
      )
    )
    setSelectedRec((current) =>
      current && current.id === recommendationId
        ? {
            ...current,
            currentUserFeedback: result.currentFeedback,
            feedbackSummary: result.feedbackSummary,
          }
        : current
    )
  }

  async function handleRecommendationFeedback(rec: Recommendation, feedbackType: RecommendationFeedbackType) {
    if (feedbackSubmittingById[rec.id]) return
    setFeedbackSubmittingById((current) => ({ ...current, [rec.id]: true }))
    setFeedbackMessageById((current) => ({ ...current, [rec.id]: "" }))
    try {
      const result = await submitRecommendationFeedback(rec.id, {
        ticketId: rec.relatedTickets[0] || null,
        feedbackType,
        recommendedAction: rec.recommendedAction,
        displayMode: rec.displayMode,
        confidence: rec.confidence,
        reasoning: rec.reasoning,
        matchSummary: rec.matchSummary,
        evidenceCount: rec.evidenceSources.length,
        metadata: {
          recommendation_type: rec.type,
          recommendation_mode: rec.recommendationMode,
          source_label: rec.sourceLabel,
          confidence_band: rec.confidenceBand,
          tentative: rec.tentative ? "true" : "false",
        },
      })
      applyFeedbackResult(rec.id, result)
      setFeedbackMessageById((current) => ({
        ...current,
        [rec.id]: locale === "fr" ? "Retour enregistre" : "Feedback saved",
      }))
    } catch {
      setFeedbackMessageById((current) => ({
        ...current,
        [rec.id]: locale === "fr" ? "Echec de l'enregistrement" : "Could not save feedback",
      }))
    } finally {
      setFeedbackSubmittingById((current) => ({ ...current, [rec.id]: false }))
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
            <div className="flex justify-between">
              <div className={`h-4 w-[120px] rounded bg-gray-200 ${i === 0 ? "animate-skeleton" : i === 1 ? "animate-skeleton-delay-1" : "animate-skeleton-delay-2"}`} />
              <div className={`h-4 w-[60px] rounded bg-gray-200 ${i === 0 ? "animate-skeleton" : i === 1 ? "animate-skeleton-delay-1" : "animate-skeleton-delay-2"}`} />
            </div>
            <div className="space-y-2">
              <div className={`h-3 w-full rounded bg-gray-100 ${i === 0 ? "animate-skeleton" : i === 1 ? "animate-skeleton-delay-1" : "animate-skeleton-delay-2"}`} />
              <div className={`h-3 w-3/4 rounded bg-gray-100 ${i === 0 ? "animate-skeleton" : i === 1 ? "animate-skeleton-delay-1" : "animate-skeleton-delay-2"}`} />
              <div className={`h-3 w-1/2 rounded bg-gray-100 ${i === 0 ? "animate-skeleton" : i === 1 ? "animate-skeleton-delay-1" : "animate-skeleton-delay-2"}`} />
            </div>
          </div>
        ))}
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
          statusTone="green"
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
          statusTone={stats.avgConfidence > 80 ? "green" : stats.avgConfidence >= 60 ? "amber" : "red"}
          hoverDetails={[
            { label: t("recs.avgConfidence"), value: `${stats.avgConfidence}%` },
            { label: locale === "fr" ? "Confiance max" : "Top confidence", value: `${Math.max(0, ...recommendations.map((rec) => formatConfidencePercent(rec.confidence)))}%` },
            { label: locale === "fr" ? "Confiance min" : "Lowest confidence", value: `${recommendations.length ? Math.min(...recommendations.map((rec) => formatConfidencePercent(rec.confidence))) : 0}%` },
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
          statusTone={stats.highImpact > 0 ? "red" : "green"}
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
          statusTone="amber"
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

      <HoverDetails
        title={locale === "fr" ? "Bonnes pratiques SLA" : "SLA best practices"}
        details={[
          { label: locale === "fr" ? "Tickets actifs" : "Active tickets", value: String(slaContext.activeCount) },
          { label: locale === "fr" ? "A risque" : "At risk", value: String(slaContext.atRiskCount) },
          { label: locale === "fr" ? "En breach" : "Breached", value: String(slaContext.breachedCount) },
          {
            label: locale === "fr" ? "Plus urgent" : "Most urgent",
            value: slaContext.urgentAtRisk[0]?.id || (locale === "fr" ? "Aucun" : "None"),
          },
        ]}
        note={
          locale === "fr"
            ? "Survolez pour voir le volume SLA actuel, puis utilisez la carte pour prioriser les tickets a faible temps restant."
            : "Hover to inspect the current SLA load, then use the card to prioritize tickets with the least remaining time."
        }
        className="block"
      >
        <Card className="surface-card border border-border/70 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">
              {locale === "fr" ? "Bonnes pratiques SLA" : "SLA best practices"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-200">
                {locale === "fr" ? `Tickets actifs: ${slaContext.activeCount}` : `Active tickets: ${slaContext.activeCount}`}
              </Badge>
              <Badge className="bg-amber-100 text-amber-800 border border-amber-200">
                {locale === "fr" ? `SLA a risque: ${slaContext.atRiskCount}` : `At-risk SLA: ${slaContext.atRiskCount}`}
              </Badge>
              <Badge className="bg-red-100 text-red-800 border border-red-200">
                {locale === "fr" ? `SLA en breach: ${slaContext.breachedCount}` : `Breached SLA: ${slaContext.breachedCount}`}
              </Badge>
            </div>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2">
                {locale === "fr"
                  ? "Traitez en premier les tickets SLA breached puis les tickets at_risk avec le temps restant le plus faible."
                  : "Prioritize breached SLA tickets first, then at-risk tickets with the lowest remaining time."}
              </li>
              <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2">
                {locale === "fr"
                  ? "Verifiez la First Response SLA sur les nouveaux tickets avant de commencer des travaux non urgents."
                  : "Check First Response SLA for new tickets before starting non-urgent work."}
              </li>
              <li className="rounded-lg border border-border/60 bg-card/70 px-3 py-2">
                {locale === "fr"
                  ? "Lancez un dry-run SLA regulierement pour anticiper les escalades sans effet de bord."
                  : "Run SLA dry-runs regularly to anticipate escalations without side effects."}
              </li>
            </ul>
            {slaContext.urgentAtRisk.length > 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                  {locale === "fr" ? "Tickets at_risk prioritaires" : "Priority at-risk tickets"}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {slaContext.urgentAtRisk.map((ticket) => (
                    <Link
                      key={`sla-urgent-${ticket.id}`}
                      href={`/tickets/${ticket.id}`}
                      className="rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-mono text-amber-900 hover:bg-amber-100"
                    >
                      {ticket.id}
                      {Number.isFinite(ticket.slaRemainingMinutes) ? ` (${ticket.slaRemainingMinutes}m)` : ""}
                    </Link>
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </HoverDetails>

      <HoverDetails
        title={locale === "fr" ? "Governance Advisor SLA" : "SLA Governance Advisor"}
        details={
          slaStrategies
            ? [
                { label: locale === "fr" ? "Confiance" : "Confidence", value: `${Math.round(slaStrategies.confidence * 100)}%` },
                { label: locale === "fr" ? "Patterns" : "Patterns", value: String(slaStrategies.commonBreachPatterns.length) },
                { label: locale === "fr" ? "Actions process" : "Process actions", value: String(slaStrategies.processImprovements.length) },
                { label: locale === "fr" ? "Sources" : "Sources", value: String(slaStrategies.sources.length) },
              ]
            : [
                {
                  label: locale === "fr" ? "Etat" : "Status",
                  value: locale === "fr" ? "Indisponible" : "Unavailable",
                },
              ]
        }
        note={
          slaStrategies
            ? buildHoverNote(
                slaStrategies.summary,
                locale === "fr"
                  ? "Le conseiller SLA consolide les patterns de breach et les ameliorations de processus detectees."
                  : "The SLA advisor consolidates detected breach patterns and process improvements."
              )
            : locale === "fr"
              ? "Le conseiller SLA n'a pas retourne de donnees pour cette session."
              : "The SLA advisor did not return data for this session."
        }
        className="block"
      >
        <Card className="surface-card border border-border/70 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">
              {locale === "fr" ? "Governance Advisor SLA" : "SLA Governance Advisor"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {slaStrategies ? (
              <>
                <div className="flex flex-wrap gap-2">
                  <Badge className="border border-blue-200 bg-blue-100 text-blue-800">
                    {locale === "fr" ? "Gouvernance RAG" : "RAG Governance"}
                  </Badge>
                  <Badge className="border border-slate-200 bg-slate-100 text-slate-700">
                    {locale === "fr" ? `Confiance: ${Math.round(slaStrategies.confidence * 100)}%` : `Confidence: ${Math.round(slaStrategies.confidence * 100)}%`}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{slaStrategies.summary}</p>
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Schémas de breach détectés" : "Detected breach patterns"}
                    </p>
                    <ul className="mt-2 space-y-2">
                      {slaStrategies.commonBreachPatterns.slice(0, 4).map((item) => (
                        <li key={`pattern-${item}`} className="rounded-lg border border-border/60 bg-card/70 px-3 py-2 text-sm text-muted-foreground">
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Améliorations suggérées" : "Suggested improvements"}
                    </p>
                    <ul className="mt-2 space-y-2">
                      {slaStrategies.processImprovements.slice(0, 4).map((item) => (
                        <li key={`improve-${item}`} className="rounded-lg border border-border/60 bg-card/70 px-3 py-2 text-sm text-muted-foreground">
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                {slaStrategies.sources.length > 0 ? (
                  <p className="text-[11px] text-muted-foreground">
                    {locale === "fr" ? "Sources RAG: " : "RAG sources: "}
                    {slaStrategies.sources.slice(0, 5).join(", ")}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {locale === "fr" ? "Advisor SLA indisponible." : "SLA governance advisor unavailable."}
              </p>
            )}
          </CardContent>
        </Card>
      </HoverDetails>

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

      {/* Search + impact + confidence + sort + clear */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("recs.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-10 rounded-xl bg-background/70 pl-9"
          />
        </div>
        <Select value={impactFilter} onValueChange={setImpactFilter}>
          <SelectTrigger className="h-10 w-36 rounded-xl bg-background/70">
            <SelectValue placeholder={t("recs.filterImpact")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("recs.all")}</SelectItem>
            <SelectItem value="high">{t("recs.impactHigh")}</SelectItem>
            <SelectItem value="medium">{t("recs.impactMedium")}</SelectItem>
            <SelectItem value="low">{t("recs.impactLow")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={confidenceFilter} onValueChange={setConfidenceFilter}>
          <SelectTrigger className="h-10 w-36 rounded-xl bg-background/70">
            <SelectValue placeholder={t("recs.filterConfidence")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("recs.all")}</SelectItem>
            <SelectItem value="high">{t("recs.impactHigh")}</SelectItem>
            <SelectItem value="medium">{t("recs.impactMedium")}</SelectItem>
            <SelectItem value="low">{t("recs.impactLow")}</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSortOrder((prev) =>
            prev === "newest" ? "confidence" : prev === "confidence" ? "impact" : "newest"
          )}
          className="h-10 gap-1.5 rounded-xl bg-background/70"
        >
          <ArrowUpDown className="h-3.5 w-3.5" />
          {sortOrder === "confidence"
            ? (locale === "fr" ? "Par confiance" : "By confidence")
            : sortOrder === "impact"
            ? (locale === "fr" ? "Par impact" : "By impact")
            : (locale === "fr" ? "Plus récents" : "Newest")}
        </Button>
        {activeFilterCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setSearch("")
              setImpactFilter("all")
              setConfidenceFilter("all")
              setSortOrder("newest")
              setFilter("all")
            }}
            className="h-10 gap-1.5 rounded-xl bg-background/70"
          >
            <X className="h-3.5 w-3.5" />
            {t("general.clear")}
            <span className="ml-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
              {activeFilterCount}
            </span>
          </Button>
        )}
      </div>

      {/* Result count */}
      {recommendations.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {filteredRecommendations.length} {locale === "fr" ? "résultat(s)" : "result(s)"}
        </p>
      )}

      {!loading && recommendations.length === 0 && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.347a3.5 3.5 0 01-4.95 0l-.347-.347z" />
            </svg>
          </div>
          <p className="text-[16px] font-medium text-gray-700">Aucune recommandation disponible</p>
          <p className="text-[13px] text-gray-400">Les recommandations sont générées automatiquement à partir de vos tickets.</p>
        </div>
      )}

      {filteredRecommendations.length === 0 && recommendations.length > 0 ? (
        <div className="surface-card rounded-xl p-6 text-sm text-muted-foreground">
          {t("recs.noResults")}
        </div>
      ) : filteredRecommendations.length > 0 ? (
        <div className="space-y-4">
          {filteredRecommendations.map((rec) => {
            const typeConfig = TYPE_CONFIG[rec.type]
            const impactConfig = IMPACT_CONFIG[rec.impact]
            const TypeIcon = typeConfig.icon
            const confidencePct = formatConfidencePercent(rec.confidence)
            const confidenceBorderClass =
              confidencePct > 80
                ? "border-l-emerald-400"
                : confidencePct >= 60
                  ? "border-l-amber-400"
                  : "border-l-red-400"
            const typeAccentBorder =
              rec.type === "pattern"
                ? "border-l-[4px] border-l-[#534AB7]"
                : rec.type === "solution"
                  ? "border-l-[4px] border-l-[#1D9E75]"
                  : rec.type === "priority"
                    ? "border-l-[4px] border-l-[#E24B4A]"
                    : "border-l-[4px] border-l-[#378ADD]"
            const ticketLabel = rec.relatedTickets[0]
              ? `${rec.relatedTickets[0]} | ${rec.title}`
              : rec.title
            const cardSteps = buildOperationalSteps(rec, locale).slice(0, 3)
            const primaryEvidence = primaryEvidenceType(rec.evidenceSources)
            const hoverDetails = buildRecommendationHoverDetails(rec, locale)
            const hoverNote = buildHoverNote(
              rec.matchSummary,
              rec.reasoning || rec.description
            )

            return (
              <HoverDetails
                key={rec.id}
                title={ticketLabel}
                details={hoverDetails}
                note={hoverNote}
                className="block"
              >
                <Card
                  className={`surface-card overflow-hidden ${typeAccentBorder} transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md`}
                >
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
                          <div className="flex-1 space-y-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {ticketLabel}
                              </p>
                              <Badge variant="outline" className={`${typeConfig.color} text-[10px] opacity-80`}>
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
                                className={`${impactConfig.color} text-[10px] opacity-80`}
                              >
                                {rec.impact === "high"
                                  ? t("recs.impactHigh")
                                  : rec.impact === "medium"
                                    ? t("recs.impactMedium")
                                    : t("recs.impactLow")}
                              </Badge>
                            </div>
                            <RecommendationActionBlock
                              locale={locale}
                              displayMode={rec.displayMode}
                              action={rec.recommendedAction}
                              fallback={rec.reasoning || rec.description}
                            />
                            <RecommendationReasoningBlock
                              locale={locale}
                              reasoning={rec.reasoning || rec.description}
                            />
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="w-[120px]">
                                <ConfidenceBar
                                  confidence={rec.confidence}
                                  band={(() => {
                                    const c = rec.confidence
                                    if (c <= 0.25) return "general_knowledge"
                                    if (c >= 0.78) return "high"
                                    if (c >= 0.52) return "medium"
                                    return "low"
                                  })()}
                                  size="sm"
                                />
                              </div>
                              <Badge variant="outline" className="text-[10px]">
                                {recommendationModeLabel(rec.recommendationMode, locale)}
                              </Badge>
                              <Badge variant="outline" className="text-[10px]">
                                {sourceLabelText(rec.sourceLabel, locale)}
                              </Badge>
                              {primaryEvidence ? (
                                <Badge variant="outline" className="text-[10px]">
                                  {evidenceTypeLabel(primaryEvidence, locale)}
                                </Badge>
                              ) : null}
                              {rec.displayMode === "no_strong_match" ? (
                                <Badge className="border border-slate-300 bg-slate-100 text-[10px] text-slate-700">
                                  {locale === "fr" ? "Sans match fort" : "No strong match"}
                                </Badge>
                              ) : rec.displayMode === "service_request" ? (
                                <Badge className="border border-sky-300 bg-sky-100 text-[10px] text-sky-800">
                                  {recommendationStatusLabel(rec.tentative, locale, rec.displayMode)}
                                </Badge>
                              ) : (
                                <Badge
                                  className={
                                    rec.tentative
                                      ? "border border-amber-300 bg-amber-100 text-[10px] text-amber-800"
                                      : "border border-emerald-300 bg-emerald-100 text-[10px] text-emerald-800"
                                  }
                                >
                                  {recommendationStatusLabel(rec.tentative, locale, rec.displayMode)}
                                </Badge>
                              )}
                            </div>
                            <RecommendationMatchBlock
                              locale={locale}
                              matchSummary={rec.matchSummary}
                            />
                            <RecommendationWhyMatchesBlock
                              locale={locale}
                              whyThisMatches={rec.whyThisMatches}
                            />
                            <RecommendationRootCauseBlock
                              locale={locale}
                              probableRootCause={rec.rootCause || rec.probableRootCause}
                            />
                            <RecommendationSupportingContextBlock
                              locale={locale}
                              supportingContext={rec.supportingContext}
                            />
                            {rec.displayMode !== "no_strong_match" ? (
                              <RecommendationNextActionsBlock
                                locale={locale}
                                actions={cardSteps}
                              />
                            ) : null}
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
                                {locale === "fr" ? "Evidence" : "Evidence"}: {rec.evidenceSources.length}
                              </span>
                            </div>
                            <div
                              className="pt-1"
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => event.stopPropagation()}
                            >
                              <RecommendationFeedbackControls
                                locale={locale}
                                currentFeedback={rec.currentUserFeedback}
                                feedbackSummary={rec.feedbackSummary}
                                submitting={Boolean(feedbackSubmittingById[rec.id])}
                                successMessage={feedbackMessageById[rec.id] || null}
                                compact
                                onSubmit={(feedbackType) => handleRecommendationFeedback(rec, feedbackType)}
                              />
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
              </HoverDetails>
            )
          })}
        </div>
      ) : null}

      <Dialog open={Boolean(selectedRec)} onOpenChange={(open) => !open && setSelectedRec(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto border-border/80 sm:max-w-2xl">
          {selectedRec ? (
            <>
              {(() => {
                const operationalSteps = buildOperationalSteps(selectedRec, locale)
                const primaryEvidence = primaryEvidenceType(selectedRec.evidenceSources)
                const selectedConfidence = formatConfidencePercent(selectedRec.confidence)
                return (
                  <>
              <DialogHeader>
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={`${TYPE_CONFIG[selectedRec.type].color} text-[10px] opacity-80`}>
                    {selectedRec.type === "pattern"
                      ? t("recs.pattern")
                      : selectedRec.type === "priority"
                        ? t("recs.priority")
                        : selectedRec.type === "solution"
                          ? t("recs.solution")
                          : t("recs.workflow")}
                  </Badge>
                  <Badge variant="outline" className={`${IMPACT_CONFIG[selectedRec.impact].color} text-[10px] opacity-80`}>
                    {selectedRec.impact === "high"
                      ? t("recs.impactHigh")
                      : selectedRec.impact === "medium"
                        ? t("recs.impactMedium")
                        : t("recs.impactLow")}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {sourceLabelText(selectedRec.sourceLabel, locale)}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {recommendationModeLabel(selectedRec.recommendationMode, locale)}
                  </Badge>
                  {primaryEvidence ? (
                    <Badge variant="outline" className="text-[10px]">
                      {evidenceTypeLabel(primaryEvidence, locale)}
                    </Badge>
                  ) : null}
                  {selectedRec.displayMode === "no_strong_match" ? (
                    <Badge className="border border-slate-300 bg-slate-100 text-[10px] text-slate-700">
                      {locale === "fr" ? "Sans match fort" : "No strong match"}
                    </Badge>
                  ) : selectedRec.displayMode === "service_request" ? (
                    <Badge className="border border-sky-300 bg-sky-100 text-[10px] text-sky-800">
                      {recommendationStatusLabel(selectedRec.tentative, locale, selectedRec.displayMode)}
                    </Badge>
                  ) : selectedRec.displayMode === "llm_general_knowledge" ? (
                    <Badge className="border border-sky-300 bg-sky-100 text-[10px] text-sky-800">
                      {recommendationStatusLabel(selectedRec.tentative, locale, selectedRec.displayMode)}
                    </Badge>
                  ) : selectedRec.tentative ? (
                    <Badge className="border border-amber-300 bg-amber-100 text-[10px] text-amber-800">
                      {locale === "fr" ? "Recommandation tentative" : "Tentative recommendation"}
                    </Badge>
                  ) : (
                    <Badge className="border border-emerald-300 bg-emerald-100 text-[10px] text-emerald-800">
                      {locale === "fr" ? "Recommandation validee" : "Validated recommendation"}
                    </Badge>
                  )}
                </div>
                <DialogTitle className="text-xl font-semibold text-foreground">
                  {selectedRec.title}
                </DialogTitle>
                <DialogDescription className="text-sm leading-relaxed text-muted-foreground">
                  {selectedRec.reasoning || selectedRec.description}
                </DialogDescription>
              </DialogHeader>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("recs.confidence")}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-sm font-semibold ${confidenceBadgeClass(selectedConfidence)}`}>
                      {selectedConfidence}%
                    </span>
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${confidenceBandClass(selectedRec.confidenceBand)}`}>
                      {confidenceBandLabel(selectedRec.confidenceBand, locale)}
                    </span>
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{locale === "fr" ? "Mode" : "Mode"}</p>
                  <p className="mt-1 text-sm font-semibold text-foreground">{recommendationModeLabel(selectedRec.recommendationMode, locale)}</p>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{locale === "fr" ? "Source" : "Source"}</p>
                  <p className="mt-1 text-sm font-semibold text-foreground">{sourceLabelText(selectedRec.sourceLabel, locale)}</p>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{locale === "fr" ? "Statut" : "Status"}</p>
                  <p className="mt-1 text-sm font-semibold text-foreground">
                    {selectedRec.displayMode === "no_strong_match"
                      ? (locale === "fr" ? "Sans match fort" : "No strong match")
                      : recommendationStatusLabel(selectedRec.tentative, locale, selectedRec.displayMode)}
                  </p>
                </div>
              </div>

              <RecommendationActionBlock
                locale={locale}
                displayMode={selectedRec.displayMode}
                action={selectedRec.recommendedAction}
                fallback={selectedRec.reasoning || selectedRec.description}
              />

              {selectedRec.displayMode === "llm_general_knowledge" ? (
                <LLMAdvisoryBlock
                  locale={locale}
                  advisory={selectedRec.llmGeneralAdvisory || {}}
                  recommendedAction={selectedRec.recommendedAction}
                  nextBestActions={selectedRec.nextBestActions}
                  validationSteps={selectedRec.validationSteps}
                  currentFeedback={
                    selectedRec.currentUserFeedback?.feedbackType === "useful" ||
                    selectedRec.currentUserFeedback?.feedbackType === "not_relevant"
                      ? selectedRec.currentUserFeedback.feedbackType
                      : null
                  }
                  onFeedback={(feedbackType) => handleRecommendationFeedback(selectedRec, feedbackType)}
                />
              ) : (
                <>
                  <RecommendationReasoningBlock
                    locale={locale}
                    reasoning={selectedRec.reasoning || selectedRec.description}
                  />

                  <RecommendationMatchBlock
                    locale={locale}
                    matchSummary={selectedRec.matchSummary}
                  />

                  <RecommendationWhyMatchesBlock
                    locale={locale}
                    whyThisMatches={selectedRec.whyThisMatches}
                  />

                  <RecommendationRootCauseBlock
                    locale={locale}
                    probableRootCause={selectedRec.rootCause || selectedRec.probableRootCause}
                  />

                  <RecommendationSupportingContextBlock
                    locale={locale}
                    supportingContext={selectedRec.supportingContext}
                  />

                  <RecommendationNextActionsBlock
                    locale={locale}
                    actions={selectedRec.displayMode === "no_strong_match" ? [] : operationalSteps}
                  />

                  <RecommendationFeedbackControls
                    locale={locale}
                    currentFeedback={selectedRec.currentUserFeedback}
                    feedbackSummary={selectedRec.feedbackSummary}
                    submitting={Boolean(feedbackSubmittingById[selectedRec.id])}
                    successMessage={feedbackMessageById[selectedRec.id] || null}
                    onSubmit={(feedbackType) => handleRecommendationFeedback(selectedRec, feedbackType)}
                  />

                  <RecommendationEvidenceAccordion
                    locale={locale}
                    evidenceSources={selectedRec.evidenceSources}
                    countBadge
                  />
                </>
              )}

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
                )
              })()}
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
  statusTone,
  hoverDetails,
  hoverNote,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  value: string
  description: string
  iconColor: string
  statusTone: "green" | "amber" | "red"
  hoverDetails: Array<{ label: string; value: string }>
  hoverNote: string
}) {
  return (
    <HoverDetails title={title} details={hoverDetails} note={hoverNote} className="block">
      <Card
        className={`border border-border border-t transition-all hover:-translate-y-0.5 hover:shadow-lg hover:ring-1 hover:ring-primary/20 ${
          statusTone === "green" ? "border-t-emerald-400" : statusTone === "amber" ? "border-t-amber-400" : "border-t-red-400"
        }`}
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
    </HoverDetails>
  )
}
