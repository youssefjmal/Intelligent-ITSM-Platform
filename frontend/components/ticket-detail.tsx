"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  ArrowLeft,
  Calendar,
  User,
  Tag,
  MessageSquare,
  Clock,
  CheckCircle2,
  Sparkles,
  Loader2,
  RefreshCw,
  History,
} from "lucide-react"
import {
  type Ticket,
  type TicketCategory,
  type TicketPriority,
  type TicketStatus,
  type TicketType,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  TICKET_TYPE_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { ApiError, apiFetch } from "@/lib/api"
import {
  fetchTicket,
  fetchTicketAiSlaRiskLatest,
  fetchTicketAIRecommendations,
  fetchTicketHistory,
  fetchSimilarTickets,
  fetchTicketSummary,
  fetchResolutionSuggestion,
  type SimilarTicket,
  type TicketHistoryEvent,
  type TicketAiSlaRiskLatest,
  type TicketAIRecommendationsPayload,
  type SummaryResult,
  type ResolutionSuggestionResult,
} from "@/lib/tickets-api"
import { InsightPopup } from "@/components/ui/insight-popup"
import {
  submitTicketRecommendationFeedback,
  type RecommendationFeedbackResponse,
  type RecommendationFeedbackType,
} from "@/lib/ai-feedback-api"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"
import { RecommendationFeedbackControls } from "@/components/recommendation-feedback-controls"
import {
  LLMAdvisoryBlock,
  RecommendationActionBlock,
  RecommendationClusterImpactBlock,
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
  formatConfidencePercent,
  noStrongMatchMessage,
  recommendationModeLabel,
  recommendationStatusLabel,
  sourceLabelText,
} from "@/components/recommendation-sections"

interface TicketDetailProps {
  ticket: Ticket
}

type Assignee = {
  id: string
  name: string
  role: string
}

type ConfirmationDialogState = {
  title: string
  description: string
  onConfirm: () => void
}

type TicketTimelineTone = "primary" | "success" | "warning" | "muted"

type TicketTimelineItem = {
  id: string
  title: string
  detail: string
  at: string
  tone: TicketTimelineTone
}

function toDateInputValue(value: string | null | undefined): string {
  const raw = String(value || "").trim()
  if (!raw) return ""
  const parsed = new Date(raw)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10)
  }
  return raw.slice(0, 10)
}

function slaRiskBandLabel(band: "low" | "medium" | "high" | "critical", locale: "fr" | "en"): string {
  const labels = {
    low: { fr: "Faible", en: "Low" },
    medium: { fr: "Moyen", en: "Medium" },
    high: { fr: "Eleve", en: "High" },
    critical: { fr: "Critique", en: "Critical" },
  }
  return locale === "fr" ? labels[band].fr : labels[band].en
}

function slaRiskBandClass(band: "low" | "medium" | "high" | "critical"): string {
  if (band === "critical") return "border-0 bg-red-100 text-red-700"
  if (band === "high") return "border-0 bg-orange-100 text-orange-700"
  if (band === "medium") return "border-0 bg-amber-100 text-amber-700"
  return "border-0 bg-emerald-100 text-emerald-700"
}

function slaProgressClass(band: "low" | "medium" | "high" | "critical"): string {
  if (band === "critical") return "bg-red-500"
  if (band === "high") return "bg-orange-500"
  if (band === "medium") return "bg-amber-500"
  return "bg-emerald-500"
}

function advisoryModeLabel(mode: "deterministic" | "hybrid" | "ai" | string, locale: "fr" | "en"): string {
  const labels: Record<string, { fr: string; en: string }> = {
    deterministic: { fr: "Deterministe", en: "Deterministic" },
    hybrid: { fr: "Hybride", en: "Hybrid" },
    ai: { fr: "IA", en: "AI" },
  }
  const entry = labels[mode] || { fr: mode || "Deterministe", en: mode || "Deterministic" }
  return locale === "fr" ? entry.fr : entry.en
}

function formatRemainingWindow(seconds: number, locale: "fr" | "en"): string {
  const totalMinutes = Math.max(0, Math.round(seconds / 60))
  if (totalMinutes < 60) {
    return locale === "fr" ? `${totalMinutes} min restantes` : `${totalMinutes} min remaining`
  }
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (locale === "fr") {
    return minutes ? `${hours}h ${minutes}m restantes` : `${hours}h restantes`
  }
  return minutes ? `${hours}h ${minutes}m remaining` : `${hours}h remaining`
}

function timelineDotClass(tone: TicketTimelineTone): string {
  if (tone === "success") return "bg-emerald-500"
  if (tone === "warning") return "bg-amber-500"
  if (tone === "primary") return "bg-primary"
  return "bg-slate-400"
}

/**
 * Derives an impact summary from ticket content using keyword matching.
 * Returns `isFallback: true` so the UI can visually distinguish this from
 * a backend-grounded AI impact assessment.
 *
 * This function exists as a client-side degradation path when the backend
 * does not return an `impact_summary` field.  It should NOT be treated as an
 * AI output and must never be rendered with the same visual weight as
 * backend-grounded impact summaries.
 *
 * @param ticket     The ticket whose title/description/category is inspected.
 * @param similarCount  Number of similar tickets (used to append a cluster note).
 * @param locale     Display locale ("fr" | "en").
 * @returns  Object with `text` (the summary string) and `isFallback: true`,
 *           or `null` if no keyword pattern matched.
 */
function fallbackImpactSummary(
  ticket: Ticket,
  similarCount: number,
  locale: "fr" | "en",
): { text: string; isFallback: true } | null {
  const text = `${ticket.title} ${ticket.description}`.toLowerCase()
  let summary: string | null = null
  if (text.includes("payroll") || text.includes("csv") || text.includes("export")) {
    summary =
      locale === "fr"
        ? "Impact potentiel: le flux d'export applicatif et les validations CSV peuvent etre affectes."
        : "Potential service impact: the application export flow and CSV validations may be affected."
  } else if (text.includes("vpn") || text.includes("mfa") || text.includes("dns")) {
    summary =
      locale === "fr"
        ? "Impact potentiel: l'acces distant et les parcours de connexion peuvent etre perturbes."
        : "Potential service impact: remote access and sign-in journeys may be degraded."
  } else if (text.includes("mail") || text.includes("relay") || text.includes("mailbox") || text.includes("forward")) {
    summary =
      locale === "fr"
        ? "Impact potentiel: les flux de messagerie, de routage ou de transfert peuvent etre affectes."
        : "Potential service impact: mail routing, delivery, or forwarding workflows may be affected."
  } else if (ticket.category === "application") {
    summary =
      locale === "fr"
        ? "Impact potentiel: une partie du service applicatif semble degradee."
        : "Potential service impact: part of the application service appears degraded."
  } else if (ticket.category === "network" || ticket.category === "security") {
    summary =
      locale === "fr"
        ? "Impact potentiel: la connectivite ou l'acces utilisateur peut etre degrade."
        : "Potential service impact: connectivity or user access may be degraded."
  }
  if (!summary) return null
  const finalText =
    similarCount >= 2
      ? locale === "fr"
        ? `${summary} Plusieurs tickets similaires suggerent un impact partage.`
        : `${summary} Multiple similar tickets suggest shared impact.`
      : summary
  return { text: finalText, isFallback: true }
}

export function TicketDetail({ ticket }: TicketDetailProps) {
  const { hasPermission } = useAuth()
  const { t, locale } = useI18n()
  const [ticketData, setTicketData] = useState<Ticket>(ticket)
  const [status, setStatus] = useState<TicketStatus>(ticket.status)
  const [selectedAssignee, setSelectedAssignee] = useState(ticket.assignee)
  const [selectedPriority, setSelectedPriority] = useState<TicketPriority>(ticket.priority)
  const [selectedTicketType, setSelectedTicketType] = useState<TicketType>(ticket.ticketType)
  const [selectedCategory, setSelectedCategory] = useState<TicketCategory>(ticket.category)
  const [selectedDueDate, setSelectedDueDate] = useState(toDateInputValue(ticket.dueAt))
  const [assignees, setAssignees] = useState<Assignee[]>([])
  const [updating, setUpdating] = useState(false)
  const [triageUpdating, setTriageUpdating] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [triageError, setTriageError] = useState<string | null>(null)
  const [statusComment, setStatusComment] = useState("")
  const [aiSuggestions, setAiSuggestions] = useState<TicketAIRecommendationsPayload | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState(false)
  const [aiFeedbackSubmitting, setAiFeedbackSubmitting] = useState(false)
  const [aiFeedbackMessage, setAiFeedbackMessage] = useState<string | null>(null)
  const [aiRecommendationEvaluatedAt, setAiRecommendationEvaluatedAt] = useState<string | null>(null)
  const [aiSlaRisk, setAiSlaRisk] = useState<TicketAiSlaRiskLatest>(null)
  const [aiSlaRiskLoading, setAiSlaRiskLoading] = useState(false)
  const [similarTickets, setSimilarTickets] = useState<SimilarTicket[]>([])
  const [similarTicketsLoading, setSimilarTicketsLoading] = useState(false)
  const [similarTicketsError, setSimilarTicketsError] = useState(false)
  const [historyEvents, setHistoryEvents] = useState<TicketHistoryEvent[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const [confirmationDialog, setConfirmationDialog] = useState<ConfirmationDialogState | null>(null)
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"

  // AI Summary Panel state
  const [summary, setSummary] = useState<SummaryResult | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryPopupOpen, setSummaryPopupOpen] = useState(false)

  // Feature 5: Resolution suggestion state
  const [resolutionSuggestion, setResolutionSuggestion] = useState<ResolutionSuggestionResult | null>(null)
  const [suggestionDismissed, setSuggestionDismissed] = useState(false)

  const assigneeOptions = (() => {
    if (!selectedAssignee) return assignees
    if (assignees.some((member) => member.name === selectedAssignee)) return assignees
    return [{ id: "current-assignee", name: selectedAssignee, role: "current" }, ...assignees]
  })()

  const triageLabels = {
    assignee: locale === "fr" ? "Reaffecter a" : "Reassign to",
    priority: locale === "fr" ? "Priorite" : "Priority",
    ticketType: locale === "fr" ? "Type" : "Type",
    category: locale === "fr" ? "Categorie" : "Category",
    dueDate: locale === "fr" ? "Echeance" : "Deadline",
    dueDateHint:
      locale === "fr"
        ? "Optionnel. Synchronise aussi la date d'echeance Jira."
        : "Optional. This also syncs the Jira due date.",
    saveDeadline: locale === "fr" ? "Enregistrer" : "Save",
    clearDeadline: locale === "fr" ? "Effacer" : "Clear",
    statusComment: locale === "fr" ? "Commentaire de statut" : "Status comment",
    statusCommentHint:
      locale === "fr"
        ? "Obligatoire pour passer en Resolu (et a la cloture sans resolution)."
        : "Required when setting Resolved (and when closing without a resolution).",
    statusCommentPlaceholder:
      locale === "fr"
        ? "Saisissez le commentaire de resolution..."
        : "Enter the resolution comment...",
    reassignments: locale === "fr" ? "Reassignations" : "Reassignments",
    firstAction: locale === "fr" ? "Premiere action" : "First action",
    notAvailable: locale === "fr" ? "N/A" : "N/A",
    resolutionCommentRequired:
      locale === "fr"
        ? "Un commentaire de resolution est obligatoire."
        : "A resolution comment is required.",
    closureCommentRequired:
      locale === "fr"
        ? "Un commentaire de resolution est obligatoire avant la cloture."
        : "A resolution comment is required before closing.",
    updateFailed: locale === "fr" ? "Mise a jour triage impossible." : "Could not update triage.",
  }

  const historyLabels = {
    title: locale === "fr" ? "Historique des modifications" : "Change history",
    subtitle:
      locale === "fr"
        ? "Journal admin: qui a fait quoi sur ce ticket."
        : "Admin audit log: who changed what on this ticket.",
    empty: locale === "fr" ? "Aucun changement enregistre." : "No tracked changes yet.",
    error: locale === "fr" ? "Impossible de charger l'historique." : "Could not load history.",
    loading: locale === "fr" ? "Chargement de l'historique..." : "Loading change history...",
    by: locale === "fr" ? "Par" : "By",
  }

  const recommendationDisplayMode =
    aiSuggestions?.displayMode || aiSuggestions?.resolutionAdvice?.displayMode || (aiSuggestions?.recommendedAction ? "evidence_action" : "no_strong_match")
  const primaryAiAction =
    aiSuggestions?.recommendedAction ||
    (recommendationDisplayMode !== "no_strong_match"
      ? aiSuggestions?.recommendations[0]?.text || null
      : aiSuggestions?.resolutionAdvice?.fallbackAction || null)
  const primaryAiConfidence = aiSuggestions
    ? aiSuggestions.resolutionConfidence > 0
      ? formatConfidencePercent(aiSuggestions.resolutionConfidence)
      : formatConfidencePercent(aiSuggestions.recommendations[0]?.confidence ?? 0)
    : 0
  const primaryAiConfidenceBand = aiSuggestions?.confidenceBand || "low"
  const recommendationMatchSummary = aiSuggestions?.matchSummary || aiSuggestions?.resolutionAdvice?.matchSummary || null
  const recommendationCluster = aiSuggestions?.incidentCluster || null
  const recommendationImpactSummary = aiSuggestions?.impactSummary || null
  const llmGeneralAdvisory = aiSuggestions?.resolutionAdvice?.llmGeneralAdvisory || null
  const advisoryNextActions = aiSuggestions?.nextBestActions || aiSuggestions?.resolutionAdvice?.nextBestActions || []
  const advisoryValidationSteps = aiSuggestions?.validationSteps || aiSuggestions?.resolutionAdvice?.validationSteps || []

  const applyAiFeedbackResult = useCallback((result: RecommendationFeedbackResponse) => {
    setAiSuggestions((current) => {
      if (!current) return current
      return {
        ...current,
        currentFeedback: result.currentFeedback,
        feedbackSummary: result.feedbackSummary,
      }
    })
  }, [])

  const nextBestActions = useMemo(() => {
    const merged = [
      ...(aiSuggestions?.nextBestActions || []),
      ...(aiSlaRisk?.recommendedActions || []),
    ]
    const deduped: string[] = []
    const seen = new Set<string>()
    for (const item of merged) {
      const cleaned = String(item || "").trim()
      if (!cleaned) continue
      const key = cleaned.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      deduped.push(cleaned)
      if (deduped.length >= 4) break
    }
    return deduped
  }, [aiSuggestions?.nextBestActions, aiSlaRisk?.recommendedActions])

  const clusterInsight = useMemo(() => {
    if (recommendationCluster?.summary) {
      return recommendationCluster
    }
    const now = Date.now()
    const recent = similarTickets.filter((row) => {
      const raw = row.updatedAt || row.createdAt
      const timestamp = raw ? new Date(raw).getTime() : Number.NaN
      return Number.isFinite(timestamp) && now - timestamp <= 24 * 60 * 60 * 1000 && row.similarityScore >= 0.5
    })
    if (recent.length < 2) return null
    const summary =
      locale === "fr"
        ? `Grappe potentielle: ${recent.length} tickets similaires sur les dernieres 24h.`
        : `Potential incident cluster: ${recent.length} similar tickets in the last 24 hours.`
    return { count: recent.length, windowHours: 24, summary }
  }, [locale, recommendationCluster, similarTickets])

  // impactInsight holds either a backend-grounded string (isFallback: false)
  // or a keyword-derived estimate (isFallback: true).  The render site uses
  // isFallback to apply a muted visual treatment to keyword-derived summaries.
  const impactInsight = useMemo<{ text: string; isFallback: boolean } | null>(() => {
    if (recommendationImpactSummary) {
      return { text: recommendationImpactSummary, isFallback: false }
    }
    return fallbackImpactSummary(ticketData, clusterInsight?.count ?? 0, locale)
  }, [clusterInsight?.count, locale, recommendationImpactSummary, ticketData])

  const timelineItems = useMemo(() => {
    const items: TicketTimelineItem[] = [
      {
        id: `${ticketData.id}-created`,
        title: locale === "fr" ? "Ticket cree" : "Ticket created",
        detail: ticketData.title,
        at: ticketData.createdAt,
        tone: "primary",
      },
    ]

    if (ticketData.updatedAt && ticketData.updatedAt !== ticketData.createdAt) {
      items.push({
        id: `${ticketData.id}-updated`,
        title: locale === "fr" ? "Ticket mis a jour" : "Ticket updated",
        detail: locale === "fr" ? `Statut actuel: ${statusLabelForRow(ticketData.status)}` : `Current status: ${statusLabelForRow(ticketData.status)}`,
        at: ticketData.updatedAt,
        tone: "muted",
      })
    }

    if (ticketData.resolution || ticketData.resolvedAt) {
      items.push({
        id: `${ticketData.id}-resolution`,
        title: locale === "fr" ? "Resolution ajoutee" : "Resolution added",
        detail: ticketData.resolution || (locale === "fr" ? "Ticket resolu." : "Ticket resolved."),
        at: ticketData.resolvedAt || ticketData.updatedAt,
        tone: "success",
      })
    }

    for (const comment of ticketData.comments.slice(-4)) {
      items.push({
        id: `${ticketData.id}-comment-${comment.id}`,
        title: locale === "fr" ? "Commentaire ajoute" : "Comment added",
        detail: `${comment.author}: ${comment.content}`,
        at: comment.createdAt,
        tone: "muted",
      })
    }

    for (const event of historyEvents.slice(0, 5)) {
      const detail =
        event.changes.length > 0
          ? `${historyFieldLabel(event.changes[0].field)}: ${historyValue(event.changes[0].before)} -> ${historyValue(event.changes[0].after)}`
          : `${historyLabels.by} ${event.actor}`
      items.push({
        id: `${ticketData.id}-history-${event.id}`,
        title: historyActionLabel(event),
        detail,
        at: event.createdAt,
        tone: event.action === "resolved" || event.action === "closed" ? "success" : "warning",
      })
    }

    if (aiRecommendationEvaluatedAt) {
      items.push({
        id: `${ticketData.id}-ai-rec`,
        title: locale === "fr" ? "Recommandation IA evaluee" : "AI recommendation evaluated",
        detail:
          recommendationDisplayMode === "no_strong_match"
            ? noStrongMatchMessage(locale)
            : primaryAiAction || (locale === "fr" ? "Conseil evidence-first disponible." : "Evidence-first advice available."),
        at: aiRecommendationEvaluatedAt,
        tone: "primary",
      })
    }

    if (aiSlaRisk?.evaluatedAt) {
      items.push({
        id: `${ticketData.id}-sla-ai`,
        title: locale === "fr" ? "Conseil SLA evalue" : "SLA advisory evaluated",
        detail:
          locale === "fr"
            ? `Risque ${slaRiskBandLabel(aiSlaRisk.band, locale)}`
            : `Risk ${slaRiskBandLabel(aiSlaRisk.band, locale)}`,
        at: aiSlaRisk.evaluatedAt,
        tone: aiSlaRisk.band === "high" || aiSlaRisk.band === "critical" ? "warning" : "muted",
      })
    }

    const deduped = new Map<string, TicketTimelineItem>()
    for (const item of items) {
      if (!item.at) continue
      deduped.set(`${item.title}-${item.at}`, item)
    }
    return Array.from(deduped.values())
      .sort((left, right) => new Date(right.at).getTime() - new Date(left.at).getTime())
      .slice(0, 10)
  }, [
    aiRecommendationEvaluatedAt,
    aiSlaRisk,
    historyEvents,
    historyLabels.by,
    locale,
    primaryAiAction,
    recommendationDisplayMode,
    ticketData,
  ])

  const canResolve = hasPermission("resolve_ticket")
  const canEditTriage = hasPermission("edit_ticket_triage")
  const canViewHistory = hasPermission("view_admin")

  useEffect(() => {
    setTicketData(ticket)
    setStatus(ticket.status)
    setSelectedAssignee(ticket.assignee)
    setSelectedPriority(ticket.priority)
    setSelectedTicketType(ticket.ticketType)
    setSelectedCategory(ticket.category)
    setSelectedDueDate(toDateInputValue(ticket.dueAt))
    setStatusError(null)
    setTriageError(null)
    setStatusComment("")
  }, [ticket])

  useEffect(() => {
    let mounted = true
    apiFetch<Assignee[]>("/users/assignees")
      .then((data) => {
        if (!mounted) return
        setAssignees(data)
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  const loadTicketHistory = useCallback(async (ticketId: string) => {
    if (!canViewHistory) {
      setHistoryEvents([])
      setHistoryLoading(false)
      setHistoryError(false)
      return
    }
    setHistoryLoading(true)
    setHistoryError(false)
    try {
      const rows = await fetchTicketHistory({ ticketId, limit: 120 })
      setHistoryEvents(rows)
    } catch {
      setHistoryEvents([])
      setHistoryError(true)
    } finally {
      setHistoryLoading(false)
    }
  }, [canViewHistory])

  useEffect(() => {
    loadTicketHistory(ticketData.id).catch(() => {})
  }, [ticketData.id, loadTicketHistory])

  const loadAiRecommendations = useCallback(async (force = false) => {
    setAiLoading(true)
    setAiError(false)
    setAiFeedbackMessage(null)
    try {
      const data = await fetchTicketAIRecommendations(
        {
          id: ticketData.id,
          title: ticketData.title,
          description: ticketData.description,
        },
        { force, locale },
      )
      setAiSuggestions(data)
      setAiRecommendationEvaluatedAt(new Date().toISOString())
    } catch {
      setAiSuggestions(null)
      setAiRecommendationEvaluatedAt(null)
      setAiError(true)
    } finally {
      setAiLoading(false)
    }
  }, [locale, ticketData.id, ticketData.title, ticketData.description])

  useEffect(() => {
    setAiSuggestions(null)
    setAiRecommendationEvaluatedAt(null)
    setAiError(false)
    setAiFeedbackMessage(null)
    loadAiRecommendations().catch(() => {})
  }, [loadAiRecommendations])

  const handleAiFeedback = useCallback(async (feedbackType: RecommendationFeedbackType) => {
    if (!aiSuggestions || aiFeedbackSubmitting) return
    setAiFeedbackSubmitting(true)
    setAiFeedbackMessage(null)
    try {
      const result = await submitTicketRecommendationFeedback({
        ticketId: ticketData.id,
        feedbackType,
        recommendedAction: primaryAiAction,
        displayMode: recommendationDisplayMode,
        confidence: aiSuggestions.resolutionConfidence || (primaryAiConfidence / 100),
        reasoning: aiSuggestions.reasoning,
        matchSummary: recommendationMatchSummary,
        evidenceCount: aiSuggestions.evidenceSources.length,
        metadata: {
          recommendation_mode: aiSuggestions.recommendationMode,
          source_label: aiSuggestions.sourceLabel,
          confidence_band: aiSuggestions.confidenceBand,
          tentative: aiSuggestions.tentative ? "true" : "false",
        },
      })
      applyAiFeedbackResult(result)
      setAiFeedbackMessage(locale === "fr" ? "Retour enregistre" : "Feedback saved")
    } catch {
      setAiFeedbackMessage(locale === "fr" ? "Echec de l'enregistrement" : "Could not save feedback")
    } finally {
      setAiFeedbackSubmitting(false)
    }
  }, [
    aiSuggestions,
    aiFeedbackSubmitting,
    ticketData.id,
    primaryAiAction,
    recommendationDisplayMode,
    primaryAiConfidence,
    recommendationMatchSummary,
    applyAiFeedbackResult,
    locale,
  ])

  useEffect(() => {
    let mounted = true
    setAiSlaRiskLoading(true)
    fetchTicketAiSlaRiskLatest(ticketData.id)
      .then((payload) => {
        if (!mounted) return
        setAiSlaRisk(payload)
      })
      .catch(() => {
        if (!mounted) return
        setAiSlaRisk(null)
      })
      .finally(() => {
        if (!mounted) return
        setAiSlaRiskLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [ticketData.id])

  useEffect(() => {
    let mounted = true
    setSimilarTicketsLoading(true)
    setSimilarTicketsError(false)
    fetchSimilarTickets(ticketData.id, { limit: 6, minScore: 0.3 })
      .then((rows) => {
        if (!mounted) return
        setSimilarTickets(rows)
      })
      .catch(() => {
        if (!mounted) return
        setSimilarTickets([])
        setSimilarTicketsError(true)
      })
      .finally(() => {
        if (!mounted) return
        setSimilarTicketsLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [ticketData.id])

  useEffect(() => {
    if (!ticketData?.id) return
    setSummaryLoading(true)
    fetchTicketSummary(ticketData.id)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false))
  }, [ticketData?.id])

  function statusLabelForRow(value: TicketStatus): string {
    if (value === "open") return t("status.open")
    if (value === "in-progress") return t("status.inProgress")
    if (value === "waiting-for-customer") return t("status.waitingForCustomer")
    if (value === "waiting-for-support-vendor") return t("status.waitingForSupportVendor")
    if (value === "pending") return t("status.pending")
    if (value === "resolved") return t("status.resolved")
    return t("status.closed")
  }

  function historyActionLabel(event: TicketHistoryEvent): string {
    const action = (event.action || "").toLowerCase()
    if (action === "created") return locale === "fr" ? "Ticket cree" : "Ticket created"
    if (action === "resolved") return locale === "fr" ? "Ticket resolu" : "Ticket resolved"
    if (action === "closed") return locale === "fr" ? "Ticket cloture" : "Ticket closed"
    if (action === "status_changed") return locale === "fr" ? "Statut modifie" : "Status changed"
    if (action === "triage_updated") return locale === "fr" ? "Triage mis a jour" : "Triage updated"
    if (action === "comment_added") return locale === "fr" ? "Commentaire ajoute" : "Comment added"
    if (action === "status_aligned_from_jira") return locale === "fr" ? "Statut aligne Jira" : "Status aligned from Jira"
    return event.eventType.replace(/_/g, " ").toLowerCase()
  }

  function historyFieldLabel(field: string): string {
    const labels: Record<string, string> = {
      status: locale === "fr" ? "Statut" : "Status",
      priority: locale === "fr" ? "Priorite" : "Priority",
      ticket_type: locale === "fr" ? "Type" : "Type",
      category: locale === "fr" ? "Categorie" : "Category",
      assignee: locale === "fr" ? "Assigne" : "Assignee",
      problem_id: locale === "fr" ? "Probleme" : "Problem",
      resolution: locale === "fr" ? "Resolution" : "Resolution",
      tags: "Tags",
      assignment_change_count: locale === "fr" ? "Reaffectations" : "Reassignments",
      due_at: locale === "fr" ? "Echeance" : "Deadline",
    }
    return labels[field] || field.replace(/_/g, " ")
  }

  function historyValue(value: unknown): string {
    if (value === null || value === undefined || value === "") {
      return triageLabels.notAvailable
    }
    if (Array.isArray(value)) {
      return value.map((item) => String(item)).join(", ")
    }
    return String(value)
  }

  function openConfirmationDialog(params: ConfirmationDialogState) {
    setConfirmationDialog(params)
  }

  async function applyStatusChange(newStatus: TicketStatus, comment: string) {
    setUpdating(true)
    try {
      const payload: { status: string; comment?: string } = { status: newStatus }
      if (comment) {
        payload.comment = comment
      }
      await apiFetch(`/tickets/${ticket.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      const refreshed = await fetchTicket(ticket.id)
      setTicketData(refreshed)
      setStatus(refreshed.status)
      setStatusError(null)
      setStatusComment("")
      loadTicketHistory(refreshed.id).catch(() => {})
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 400 && error.detail === "resolution_comment_required") {
          setStatusError(triageLabels.resolutionCommentRequired)
        } else if (error.status === 403) {
          setStatusError(
            locale === "fr"
              ? "Vous n'avez pas les permissions pour changer le statut."
              : "You do not have permission to change status.",
          )
        } else {
          setStatusError(
            locale === "fr"
              ? "Impossible de mettre a jour le statut."
              : "Could not update status.",
          )
        }
      } else {
        setStatusError(
          locale === "fr"
            ? "Impossible de mettre a jour le statut."
            : "Could not update status.",
        )
      }
    } finally {
      setUpdating(false)
    }
  }

  function handleStatusChange(newStatus: string) {
    if (newStatus === status) return

    // Feature 5: Fetch resolution suggestion when switching to "resolved" with empty comment
    if (newStatus === "resolved" && statusComment.trim().length < 20) {
      setSuggestionDismissed(false)
      fetchResolutionSuggestion(ticket.id)
        .then((result) => {
          if (result.suggestion) setResolutionSuggestion(result)
        })
        .catch(() => {})
    }

    const comment = statusComment.trim()
    const castedStatus = newStatus as TicketStatus
    if (newStatus === "resolved" && !comment) {
      setStatusError(triageLabels.resolutionCommentRequired)
      return
    }
    if (newStatus === "closed" && !ticketData.resolution && !comment) {
      setStatusError(triageLabels.closureCommentRequired)
      return
    }

    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer le changement de statut" : "Confirm status change",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment changer le statut vers "${statusLabelForRow(castedStatus)}" ?`
          : `Are you sure you want to change the status to "${statusLabelForRow(castedStatus)}"?`,
      onConfirm: () => {
        void applyStatusChange(castedStatus, comment)
      },
    })
  }

  async function updateTriage(payload: {
    assignee?: string
    priority?: TicketPriority
    ticket_type?: TicketType
    category?: TicketCategory
    due_at?: string | null
  }) {
    setTriageUpdating(true)
    try {
      await apiFetch(`/tickets/${ticket.id}/triage`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      const refreshed = await fetchTicket(ticket.id)
      setTicketData(refreshed)
      setSelectedAssignee(refreshed.assignee)
      setSelectedPriority(refreshed.priority)
      setSelectedTicketType(refreshed.ticketType)
      setSelectedCategory(refreshed.category)
      setSelectedDueDate(toDateInputValue(refreshed.dueAt))
      setStatus(refreshed.status)
      setTriageError(null)
      loadTicketHistory(refreshed.id).catch(() => {})
    } catch {
      setTriageError(triageLabels.updateFailed)
    } finally {
      setTriageUpdating(false)
    }
  }

  function handleAssigneeChange(newAssignee: string) {
    if (!newAssignee || newAssignee === selectedAssignee) return
    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer l'affectation" : "Confirm assignment",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment reaffecter ce ticket a "${newAssignee}" ?`
          : `Are you sure you want to reassign this ticket to "${newAssignee}"?`,
      onConfirm: () => {
        updateTriage({ assignee: newAssignee }).catch(() => {})
      },
    })
  }

  function handlePriorityChange(newPriority: string) {
    const casted = newPriority as TicketPriority
    if (casted === selectedPriority) return
    const priorityLabel = t(`priority.${casted}` as "priority.medium")
    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer le changement de priorite" : "Confirm priority change",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment changer la priorite en "${priorityLabel}" ?`
          : `Are you sure you want to change the priority to "${priorityLabel}"?`,
      onConfirm: () => {
        updateTriage({ priority: casted }).catch(() => {})
      },
    })
  }

  function handleTicketTypeChange(newTicketType: string) {
    const casted = newTicketType as TicketType
    if (casted === selectedTicketType) return
    const ticketTypeLabel = t(`type.${casted}` as "type.incident")
    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer le changement de type" : "Confirm type change",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment changer le type en "${ticketTypeLabel}" ?`
          : `Are you sure you want to change the type to "${ticketTypeLabel}"?`,
      onConfirm: () => {
        updateTriage({ ticket_type: casted }).catch(() => {})
      },
    })
  }

  function handleCategoryChange(newCategory: string) {
    const casted = newCategory as TicketCategory
    if (casted === selectedCategory) return
    const categoryLabel = t(`category.${casted}` as "category.application")
    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer le changement de categorie" : "Confirm category change",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment changer la categorie en "${categoryLabel}" ?`
          : `Are you sure you want to change the category to "${categoryLabel}"?`,
      onConfirm: () => {
        updateTriage({ category: casted }).catch(() => {})
      },
    })
  }

  function handleDueDateSave() {
    const currentDueDate = toDateInputValue(ticketData.dueAt)
    if (selectedDueDate === currentDueDate) return
    updateTriage({ due_at: selectedDueDate ? `${selectedDueDate}T12:00:00.000Z` : null }).catch(() => {})
  }

  function handleDueDateClear() {
    if (!selectedDueDate && !ticketData.dueAt) return
    setSelectedDueDate("")
    updateTriage({ due_at: null }).catch(() => {})
  }

  return (
    <div className="fade-slide-in space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/tickets">
          <Button variant="ghost" size="sm" className="h-9 gap-1.5 rounded-xl">
            <ArrowLeft className="h-4 w-4" />
            {t("detail.back")}
          </Button>
        </Link>
        <Badge variant="outline" className="rounded-full border-border bg-card/80 px-2.5 py-1 text-xs font-mono text-muted-foreground">
          {ticket.id}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="space-y-6 xl:col-span-8">
          <Card className="surface-card overflow-hidden rounded-2xl">
            <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-xl font-bold leading-tight text-foreground sm:text-2xl">
                    {ticketData.title}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {t("detail.reportedBy")} {ticketData.reporter} {t("detail.on")}{" "}
                    {new Date(ticketData.createdAt).toLocaleDateString(localeCode, {
                      day: "2-digit",
                      month: "long",
                      year: "numeric",
                    })}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={`${PRIORITY_CONFIG[ticketData.priority].color} border-0 px-2.5 py-1 text-xs font-semibold`}>
                    {PRIORITY_CONFIG[ticketData.priority].label}
                  </Badge>
                  <Badge className={`${STATUS_CONFIG[status].color} border-0 px-2.5 py-1 text-xs font-semibold`}>
                    {STATUS_CONFIG[status].label}
                  </Badge>
                  <Badge variant="outline" className="border-border bg-background/70 px-2.5 py-1 text-xs">
                    {TICKET_TYPE_CONFIG[ticketData.ticketType].label}
                  </Badge>
                  <Badge variant="outline" className="border-border bg-background/70 px-2.5 py-1 text-xs">
                    {CATEGORY_CONFIG[ticketData.category].label}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* AI Summary Panel */}
              <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[12px] font-medium text-gray-500 uppercase tracking-wide">Résumé IA</span>
                  <div className="flex items-center gap-2">
                    {summary && (
                      <button
                        onClick={() => setSummaryPopupOpen(true)}
                        className="text-[12px] text-blue-600 hover:text-blue-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-1"
                      >
                        Voir le résumé complet
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setSummaryLoading(true)
                        fetchTicketSummary(ticketData.id, true)
                          .then(setSummary)
                          .catch(() => setSummary(null))
                          .finally(() => setSummaryLoading(false))
                      }}
                      title="Régénérer"
                      className="text-gray-400 hover:text-gray-600 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-1"
                    >
                      <svg className={`w-3.5 h-3.5 ${summaryLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                    </button>
                  </div>
                </div>
                {summaryLoading ? (
                  <div className="space-y-2">
                    <div className="h-3 w-full rounded bg-gray-200 animate-skeleton" />
                    <div className="h-3 w-[85%] rounded bg-gray-200 animate-skeleton-delay-1" />
                    <div className="h-3 w-[70%] rounded bg-gray-200 animate-skeleton-delay-2" />
                  </div>
                ) : summary?.summary ? (
                  <p className="text-[13px] text-gray-600 leading-relaxed line-clamp-4">
                    {summary.summary}
                  </p>
                ) : (
                  <p className="text-[13px] text-gray-400 italic">Résumé non disponible.</p>
                )}
                {summary && !summaryLoading && (
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-[11px] text-gray-400">
                      {summary.is_cached ? "En cache" : "Nouveau"}
                      {summary.similar_ticket_count > 0 && ` · ${summary.similar_ticket_count} ticket(s) similaire(s) utilisé(s)`}
                    </span>
                  </div>
                )}
              </div>

              {/* Summary detail popup */}
              {summary && (
                <InsightPopup
                  isOpen={summaryPopupOpen}
                  onClose={() => setSummaryPopupOpen(false)}
                  title="Résumé IA du ticket"
                  subtitle={summary.is_cached ? "Depuis le cache" : "Nouvellement généré"}
                  size="md"
                  actions={[
                    {
                      label: "Régénérer",
                      onClick: () => {
                        setSummaryLoading(true)
                        setSummaryPopupOpen(false)
                        fetchTicketSummary(ticketData.id, true)
                          .then(setSummary)
                          .catch(() => setSummary(null))
                          .finally(() => setSummaryLoading(false))
                      },
                      variant: "outline",
                    },
                    { label: "Fermer", onClick: () => setSummaryPopupOpen(false) },
                  ]}
                >
                  <div className="space-y-4">
                    <p className="text-[14px] text-gray-700 leading-relaxed">{summary.summary}</p>
                    <div className="text-[12px] text-gray-400 space-y-1">
                      <p>Généré le : {new Date(summary.generated_at).toLocaleString("fr-FR")}</p>
                      <p>Langue : {summary.language}</p>
                      {summary.similar_ticket_count === 0 ? (
                        <p className="italic">Ce résumé est basé uniquement sur ce ticket — aucun ticket similaire trouvé.</p>
                      ) : (
                        <p>{summary.similar_ticket_count} ticket(s) similaire(s) utilisé(s) : {summary.used_ticket_ids.join(", ")}</p>
                      )}
                    </div>
                  </div>
                </InsightPopup>
              )}

              <div className="rounded-xl border border-border/70 bg-muted/20 p-4">
                <h3 className="mb-2 text-sm font-semibold text-foreground">{t("detail.description")}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{ticketData.description}</p>
              </div>

              {ticketData.resolution && (
                <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold text-foreground">{t("detail.resolution")}</h3>
                  </div>
                  <p className="text-sm leading-relaxed text-foreground/80">{ticketData.resolution}</p>
                </div>
              )}

              <Separator />

              <div className="space-y-4">
                <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <MessageSquare className="h-4 w-4" />
                  {t("detail.comments")} ({ticketData.comments.length})
                </h3>
                {ticketData.comments.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
                    {t("detail.noComments")}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {ticketData.comments.map((comment) => (
                      <div key={comment.id} className="rounded-xl border border-border/70 bg-card/70 p-3">
                        <div className="flex items-start gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                            {comment.author.slice(0, 2).toUpperCase()}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="text-sm font-medium text-foreground">{comment.author}</span>
                              <span className="text-xs text-muted-foreground">
                                {new Date(comment.createdAt).toLocaleDateString(localeCode, {
                                  day: "2-digit",
                                  month: "short",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </span>
                            </div>
                            <div className="mt-2 rounded-xl bg-muted/35 p-3">
                              <p className="text-sm leading-relaxed text-foreground/90">{comment.content}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="surface-card rounded-2xl">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  {t("detail.aiRecommendations")}
                </CardTitle>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 rounded-lg text-[11px]"
                  onClick={() => loadAiRecommendations(true)}
                  disabled={aiLoading}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${aiLoading ? "animate-spin" : ""}`} />
                  {t("detail.aiRefresh")}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">{t("detail.aiRecommendationsDesc")}</p>
            </CardHeader>
            <CardContent className="space-y-3">
              {aiLoading && (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t("detail.aiRecommendationsLoading")}
                </div>
              )}

              {!aiLoading && aiError && <p className="text-xs text-destructive">{t("detail.aiRecommendationsError")}</p>}

              {!aiLoading && !aiError && aiSuggestions && (
                <>
                  {/* Confidence gate: show classification suggestions only when confidence is sufficient */}
                  {primaryAiConfidence < 35 ? (
                    <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20 p-3">
                      <p className="text-sm font-medium text-amber-700 dark:text-amber-400">
                        {t("classification.manualTriageRequired")}
                      </p>
                      <p className="mt-1 text-xs text-amber-600 dark:text-amber-500">
                        {locale === "fr"
                          ? `Confiance: ${primaryAiConfidence}% — les suggestions automatiques ne sont pas fiables pour ce ticket. Veuillez effectuer un triage manuel.`
                          : `Confidence: ${primaryAiConfidence}% — automatic suggestions are not reliable for this ticket. Please perform manual triage.`}
                      </p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-2">
                      {primaryAiConfidence < 50 && (
                        <div className="flex items-center gap-2 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
                          <span>⚠</span>
                          <span>{t("classification.verifyBeforeApplying")}</span>
                        </div>
                      )}
                    <div className="rounded-lg border border-border/70 bg-background/70 p-2.5">
                      <p className="text-[11px] font-semibold text-muted-foreground">{t("detail.aiSuggestedPriority")}</p>
                      <div className="mt-1">
                        <Badge className={`${PRIORITY_CONFIG[aiSuggestions.priority].color} border-0 text-[10px]`}>
                          {t(`priority.${aiSuggestions.priority}` as "priority.medium")}
                        </Badge>
                      </div>
                    </div>

                    <div className="rounded-lg border border-border/70 bg-background/70 p-2.5">
                      <p className="text-[11px] font-semibold text-muted-foreground">{t("detail.aiSuggestedType")}</p>
                      <p className="mt-1 text-xs font-medium text-foreground">
                        {t(`type.${aiSuggestions.ticketType}` as "type.incident")}
                      </p>
                    </div>

                    <div className="rounded-lg border border-border/70 bg-background/70 p-2.5">
                      <p className="text-[11px] font-semibold text-muted-foreground">{t("detail.aiSuggestedCategory")}</p>
                      <p className="mt-1 text-xs font-medium text-foreground">
                        {t(`category.${aiSuggestions.category}` as "category.network")}
                      </p>
                    </div>

                    <div className="rounded-lg border border-border/70 bg-background/70 p-2.5">
                      <p className="text-[11px] font-semibold text-muted-foreground">{t("detail.aiSuggestedAssignee")}</p>
                      <p className="mt-1 text-xs font-medium text-foreground">{aiSuggestions.assignee || triageLabels.notAvailable}</p>
                    </div>
                  </div>
                  )}

                  <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-primary">
                      {t("form.recommendedSolutions")}
                    </p>
                    {!primaryAiAction && recommendationDisplayMode !== "no_strong_match" ? (
                      <p className="text-xs text-muted-foreground">{t("detail.aiRecommendationsEmpty")}</p>
                    ) : (
                      <div className="space-y-2">
                        <div className="rounded-md border border-border/60 bg-background/70 p-3">
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                            <div className="rounded-md border border-border/60 bg-card/80 p-2.5">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {locale === "fr" ? "Confiance" : "Confidence"}
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${confidenceBadgeClass(primaryAiConfidence)}`}>
                                  {primaryAiConfidence}%
                                </span>
                                <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${confidenceBandClass(primaryAiConfidenceBand)}`}>
                                  {confidenceBandLabel(primaryAiConfidenceBand, locale)}
                                </span>
                              </div>
                            </div>
                            <div className="rounded-md border border-border/60 bg-card/80 p-2.5">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {locale === "fr" ? "Mode" : "Mode"}
                              </p>
                              <p className="mt-2 text-xs font-medium text-foreground">
                                {recommendationModeLabel(aiSuggestions.recommendationMode, locale)}
                              </p>
                            </div>
                            <div className="rounded-md border border-border/60 bg-card/80 p-2.5">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {locale === "fr" ? "Source" : "Source"}
                              </p>
                              <p className="mt-2 text-xs font-medium text-foreground">
                                {sourceLabelText(aiSuggestions.sourceLabel, locale)}
                              </p>
                            </div>
                            <div className="rounded-md border border-border/60 bg-card/80 p-2.5">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {locale === "fr" ? "Statut" : "Status"}
                              </p>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {recommendationDisplayMode === "no_strong_match" ? (
                                  <Badge className="border border-slate-300 bg-slate-100 text-[10px] text-slate-700">
                                    {locale === "fr" ? "Sans match fort" : "No strong match"}
                                  </Badge>
                                ) : recommendationDisplayMode === "service_request" ? (
                                  <Badge className="border border-sky-300 bg-sky-100 text-[10px] text-sky-800">
                                    {recommendationStatusLabel(aiSuggestions.tentative, locale, recommendationDisplayMode)}
                                  </Badge>
                                ) : recommendationDisplayMode === "llm_general_knowledge" ? (
                                  <Badge className="border border-sky-300 bg-sky-100 text-[10px] text-sky-800">
                                    {recommendationStatusLabel(aiSuggestions.tentative, locale, recommendationDisplayMode)}
                                  </Badge>
                                ) : (
                                  <Badge
                                    className={
                                      aiSuggestions.tentative
                                        ? "border border-amber-300 bg-amber-100 text-[10px] text-amber-800"
                                        : "border border-emerald-300 bg-emerald-100 text-[10px] text-emerald-800"
                                    }
                                  >
                                    {recommendationStatusLabel(aiSuggestions.tentative, locale, recommendationDisplayMode)}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>

                          <RecommendationActionBlock
                            locale={locale}
                            displayMode={recommendationDisplayMode}
                            action={primaryAiAction}
                            className="mt-3"
                          />

                          {recommendationDisplayMode === "llm_general_knowledge" ? (
                            <LLMAdvisoryBlock
                              locale={locale}
                              advisory={llmGeneralAdvisory || {}}
                              recommendedAction={primaryAiAction}
                              nextBestActions={advisoryNextActions}
                              validationSteps={advisoryValidationSteps}
                              currentFeedback={
                                aiSuggestions.currentFeedback?.feedbackType === "useful" ||
                                aiSuggestions.currentFeedback?.feedbackType === "not_relevant"
                                  ? aiSuggestions.currentFeedback.feedbackType
                                  : null
                              }
                              className="mt-3"
                              onFeedback={handleAiFeedback}
                            />
                          ) : (
                            <>

                          <RecommendationReasoningBlock
                            locale={locale}
                            reasoning={aiSuggestions.reasoning}
                            className="mt-3"
                          />

                          <RecommendationMatchBlock
                            locale={locale}
                            matchSummary={recommendationMatchSummary}
                            className="mt-3"
                          />

                          <RecommendationWhyMatchesBlock
                            locale={locale}
                            whyThisMatches={aiSuggestions.whyThisMatches}
                            className="mt-3"
                          />

                          <RecommendationRootCauseBlock
                            locale={locale}
                            probableRootCause={aiSuggestions.rootCause || aiSuggestions.probableRootCause}
                            className="mt-3"
                          />

                          <RecommendationSupportingContextBlock
                            locale={locale}
                            supportingContext={aiSuggestions.supportingContext}
                            className="mt-3"
                          />

                          {recommendationDisplayMode !== "service_request" ? (
                            <>
                              <RecommendationClusterImpactBlock
                                locale={locale}
                                clusterInsight={clusterInsight}
                                impactSummary={impactInsight?.text ?? null}
                                className="mt-3"
                              />
                              {/* When the impact summary is keyword-derived (not AI-grounded),
                                  render a muted label so the user knows it is an estimate,
                                  not a confirmed AI assessment. */}
                              {impactInsight?.isFallback ? (
                                <p className="mt-1 text-[11px] text-muted-foreground">
                                  {locale === "fr"
                                    ? "Estimé depuis le contenu du ticket"
                                    : "Estimated from ticket content"}
                                </p>
                              ) : null}
                            </>
                          ) : null}

                          {recommendationDisplayMode !== "no_strong_match" ? (
                            <RecommendationNextActionsBlock
                              locale={locale}
                              actions={nextBestActions}
                              className="mt-3"
                            />
                          ) : null}

                          <RecommendationEvidenceAccordion
                            locale={locale}
                            evidenceSources={aiSuggestions.evidenceSources}
                            className="mt-3"
                          />

                              <RecommendationFeedbackControls
                                locale={locale}
                                currentFeedback={aiSuggestions.currentFeedback}
                                feedbackSummary={aiSuggestions.feedbackSummary}
                                submitting={aiFeedbackSubmitting}
                                successMessage={aiFeedbackMessage}
                                className="mt-3"
                                onSubmit={handleAiFeedback}
                              />
                            </>
                          )}
                          {recommendationDisplayMode !== "no_strong_match" && !aiSuggestions.recommendedAction && aiSuggestions.recommendations.length > 1 ? (
                            <div className="mt-3 space-y-2">
                              {aiSuggestions.recommendations.slice(1).map((recommendation, index) => (
                                <div
                                  key={`${ticketData.id}-ai-rec-main-${index}`}
                                  className="rounded-md border border-border/60 bg-background/60 px-2.5 py-2 text-xs text-foreground"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <span>{recommendation.text}</span>
                                    <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                                      {recommendation.confidence}%
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card className="surface-card rounded-2xl">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Sparkles className="h-4 w-4 text-primary" />
                {t("detail.similarTickets")}
              </CardTitle>
              <p className="text-xs text-muted-foreground">{t("detail.similarTicketsDesc")}</p>
            </CardHeader>
            <CardContent className="space-y-3">
              {similarTicketsLoading ? (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t("detail.similarTicketsLoading")}
                </div>
              ) : null}

              {!similarTicketsLoading && similarTicketsError ? (
                <p className="text-xs text-destructive">{t("detail.similarTicketsError")}</p>
              ) : null}

              {!similarTicketsLoading && !similarTicketsError && similarTickets.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("detail.similarTicketsEmpty")}</p>
              ) : null}

              {!similarTicketsLoading && !similarTicketsError && similarTickets.length > 0 ? (
                <div className="space-y-2">
                  {similarTickets.map((row) => (
                    <HoverCard key={`${ticketData.id}-similar-${row.id}`} openDelay={100} closeDelay={80}>
                      <HoverCardTrigger asChild>
                        <Link
                          href={`/tickets/${row.id}`}
                          className="group block rounded-xl border border-border/70 bg-card/70 p-3 transition-colors hover:bg-card"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="line-clamp-2 text-sm font-medium text-foreground group-hover:text-primary">
                                {row.title}
                              </p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {row.id} | {row.assignee || triageLabels.notAvailable}
                              </p>
                            </div>
                            <Badge variant="outline" className="text-[10px]">
                              {Math.round(row.similarityScore * 100)}%
                            </Badge>
                          </div>
                        </Link>
                      </HoverCardTrigger>
                      <HoverCardContent className="w-96 border-border/70 bg-background/95 p-3 shadow-xl backdrop-blur">
                        <p className="text-sm font-semibold text-foreground">{row.title}</p>
                        <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-muted-foreground">{row.description}</p>
                        <div className="mt-3 grid grid-cols-2 gap-2">
                          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                            <p className="text-[10px] text-muted-foreground">{t("detail.similarityScore")}</p>
                            <p className="text-xs font-semibold text-foreground">{Math.round(row.similarityScore * 100)}%</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                            <p className="text-[10px] text-muted-foreground">{t("tickets.status")}</p>
                            <p className="text-xs font-semibold text-foreground">{statusLabelForRow(row.status)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                            <p className="text-[10px] text-muted-foreground">{t("tickets.priority")}</p>
                            <p className="text-xs font-semibold text-foreground">{t(`priority.${row.priority}` as "priority.medium")}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                            <p className="text-[10px] text-muted-foreground">{t("tickets.type")}</p>
                            <p className="text-xs font-semibold text-foreground">{t(`type.${row.ticketType}` as "type.incident")}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                            <p className="text-[10px] text-muted-foreground">{t("tickets.category")}</p>
                            <p className="text-xs font-semibold text-foreground">{t(`category.${row.category}` as "category.application")}</p>
                          </div>
                        </div>
                        <Link href={`/tickets/${row.id}`} className="mt-3 inline-flex">
                          <Button size="sm" className="h-8 rounded-lg text-xs">
                            {t("detail.openTicket")}
                          </Button>
                        </Link>
                      </HoverCardContent>
                    </HoverCard>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6 xl:col-span-4 xl:sticky xl:top-4 xl:self-start">
          <Card className="surface-card rounded-2xl">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-foreground">
                {locale === "fr" ? "Conseil de risque SLA" : "SLA Risk Advisory"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {aiSlaRiskLoading ? (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {locale === "fr" ? "Chargement du conseil SLA..." : "Loading SLA advisory..."}
                </div>
              ) : null}

              {!aiSlaRiskLoading && !aiSlaRisk ? (
                <p className="text-xs text-muted-foreground">
                  {locale === "fr" ? "Conseil SLA indisponible." : "SLA advisory unavailable."}
                </p>
              ) : null}

              {!aiSlaRiskLoading && aiSlaRisk ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={slaRiskBandClass(aiSlaRisk.band)}>
                      {locale === "fr" ? "Risque SLA" : "SLA Risk"}: {slaRiskBandLabel(aiSlaRisk.band, locale)}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      {locale === "fr" ? "Confiance" : "Confidence"} {formatConfidencePercent(aiSlaRisk.confidence)}%
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      {locale === "fr" ? "Mode" : "Mode"} {advisoryModeLabel(aiSlaRisk.advisoryMode, locale)}
                    </Badge>
                  </div>

                  <div className="rounded-lg border border-border/70 bg-background/70 p-3">
                    <div className="flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      <span>{locale === "fr" ? "Temps SLA consomme" : "SLA time consumed"}</span>
                      <span>{aiSlaRisk.timeConsumedPercent}%</span>
                    </div>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className={`h-full rounded-full transition-all ${slaProgressClass(aiSlaRisk.band)}`}
                        style={{ width: `${Math.max(6, aiSlaRisk.timeConsumedPercent)}%` }}
                      />
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {aiSlaRisk.remainingSeconds > 0
                        ? formatRemainingWindow(aiSlaRisk.remainingSeconds, locale)
                        : locale === "fr"
                          ? "Fenetre SLA expiree ou non disponible"
                          : "SLA window expired or unavailable"}
                    </p>
                  </div>

                  {aiSlaRisk.suggestedPriority ? (
                    <p className="text-xs text-foreground">
                      {locale === "fr" ? "Priorite suggeree" : "Suggested priority"}:{" "}
                      <span className="font-semibold">{aiSlaRisk.suggestedPriority}</span>
                    </p>
                  ) : null}

                  <div className="rounded-lg border border-border/70 bg-background/70 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Pourquoi ce risque existe" : "Why this risk exists"}
                    </p>
                    <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
                      {aiSlaRisk.reasoning.map((item, index) => (
                        <li key={`${ticketData.id}-sla-reason-${index}`} className="flex gap-2">
                          <span className="mt-0.5 text-foreground">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="rounded-lg border border-border/70 bg-background/70 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Actions suggerees" : "Suggested actions"}
                    </p>
                    <ul className="mt-2 space-y-2 text-xs text-foreground">
                      {aiSlaRisk.recommendedActions.map((item, index) => (
                        <li key={`${ticketData.id}-sla-action-${index}`} className="flex gap-2">
                          <span className="mt-0.5 text-primary">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <p className="text-[11px] text-muted-foreground">
                    {new Date(aiSlaRisk.evaluatedAt).toLocaleString(localeCode)} - {aiSlaRisk.modelVersion || advisoryModeLabel(aiSlaRisk.advisoryMode, locale)}
                  </p>
                </>
              ) : null}
            </CardContent>
          </Card>

          <Card className="surface-card rounded-2xl">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-foreground">
                {locale === "fr" ? "Timeline du ticket" : "Ticket Timeline"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {timelineItems.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {locale === "fr" ? "Aucun evenement disponible." : "No timeline events available."}
                </p>
              ) : (
                <div className="space-y-3">
                  {timelineItems.map((item, index) => (
                    <div key={item.id} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span className={`mt-1 h-2.5 w-2.5 rounded-full ${timelineDotClass(item.tone)}`} />
                        {index < timelineItems.length - 1 ? <span className="mt-1 h-full w-px bg-border/70" /> : null}
                      </div>
                      <div className="min-w-0 flex-1 rounded-xl border border-border/70 bg-background/60 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-foreground">{item.title}</p>
                          <span className="text-[11px] text-muted-foreground">
                            {new Date(item.at).toLocaleString(localeCode)}
                          </span>
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="surface-card rounded-2xl">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-foreground">{t("detail.info")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!canResolve && !canEditTriage && (
                <p className="text-xs text-muted-foreground">
                  {locale === "fr"
                    ? "Mode lecture seule: seuls les agents et administrateurs peuvent modifier ce ticket."
                    : "Read-only mode: only agents and administrators can update this ticket."}
                </p>
              )}

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{t("tickets.status")}</p>
                <Select value={status} onValueChange={handleStatusChange} disabled={!canResolve || updating || triageUpdating}>
                  <SelectTrigger className="h-10 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(STATUS_CONFIG).map(([key, val]) => (
                      <SelectItem key={key} value={key}>
                        {val.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <div className="mt-2 space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">{triageLabels.statusComment}</p>
                  {/* Feature 5: AI resolution suggestion panel */}
                  {resolutionSuggestion && !suggestionDismissed && resolutionSuggestion.suggestion && (
                    <div className="rounded-lg bg-teal-50 dark:bg-teal-950/20 border border-teal-200 p-3 mb-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-medium text-teal-700 dark:text-teal-300">Résolution suggérée par l'IA</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                          resolutionSuggestion.confidence >= 0.6 ? "bg-teal-100 text-teal-800" : "bg-yellow-100 text-yellow-800"
                        }`}>
                          {Math.round(resolutionSuggestion.confidence * 100)}%
                        </span>
                      </div>
                      <p className="text-sm text-teal-800 dark:text-teal-200">{resolutionSuggestion.suggestion}</p>
                      <div className="flex gap-2 mt-2">
                        <button
                          type="button"
                          onClick={() => { setStatusComment(resolutionSuggestion.suggestion); setSuggestionDismissed(true); }}
                          className="text-xs px-3 py-1 rounded bg-teal-500 text-white hover:bg-teal-600 transition-colors"
                        >
                          Accepter
                        </button>
                        <button
                          type="button"
                          onClick={() => setSuggestionDismissed(true)}
                          className="text-xs px-3 py-1 rounded border border-teal-300 text-teal-700 hover:bg-teal-100 transition-colors"
                        >
                          Ignorer
                        </button>
                      </div>
                      <p className="mt-1.5 text-[10px] text-teal-600 dark:text-teal-400">
                        Vérifiez que cette description reflète exactement les actions effectuées avant de sauvegarder.
                      </p>
                    </div>
                  )}
                  <Textarea
                    value={statusComment}
                    onChange={(event) => setStatusComment(event.target.value)}
                    placeholder={triageLabels.statusCommentPlaceholder}
                    className="min-h-[92px] rounded-xl text-sm"
                    disabled={!canResolve || updating || triageUpdating}
                  />
                  <p className="text-[11px] text-muted-foreground">{triageLabels.statusCommentHint}</p>
                </div>
                {statusError && <p className="mt-2 text-xs text-destructive">{statusError}</p>}
              </div>

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{triageLabels.assignee}</p>
                <Select
                  value={selectedAssignee}
                  onValueChange={handleAssigneeChange}
                  disabled={!canEditTriage || updating || triageUpdating || assigneeOptions.length === 0}
                >
                  <SelectTrigger className="h-10 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {assigneeOptions.map((member) => (
                      <SelectItem key={member.id} value={member.name}>
                        {member.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{triageLabels.priority}</p>
                <Select value={selectedPriority} onValueChange={handlePriorityChange} disabled={!canEditTriage || updating || triageUpdating}>
                  <SelectTrigger className="h-10 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="critical">{t("priority.critical")}</SelectItem>
                    <SelectItem value="high">{t("priority.high")}</SelectItem>
                    <SelectItem value="medium">{t("priority.medium")}</SelectItem>
                    <SelectItem value="low">{t("priority.low")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{triageLabels.ticketType}</p>
                <Select value={selectedTicketType} onValueChange={handleTicketTypeChange} disabled={!canEditTriage || updating || triageUpdating}>
                  <SelectTrigger className="h-10 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="incident">{t("type.incident")}</SelectItem>
                    <SelectItem value="service_request">{t("type.service_request")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{triageLabels.category}</p>
                <Select value={selectedCategory} onValueChange={handleCategoryChange} disabled={!canEditTriage || updating || triageUpdating}>
                  <SelectTrigger className="h-10 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="infrastructure">{t("category.infrastructure")}</SelectItem>
                    <SelectItem value="network">{t("category.network")}</SelectItem>
                    <SelectItem value="security">{t("category.security")}</SelectItem>
                    <SelectItem value="application">{t("category.application")}</SelectItem>
                    <SelectItem value="service_request">{t("category.service_request")}</SelectItem>
                    <SelectItem value="hardware">{t("category.hardware")}</SelectItem>
                    <SelectItem value="email">{t("category.email")}</SelectItem>
                    <SelectItem value="problem">{t("category.problem")}</SelectItem>
                  </SelectContent>
                </Select>
                {triageError && <p className="mt-2 text-xs text-destructive">{triageError}</p>}
              </div>

              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">{triageLabels.dueDate}</p>
                <Input
                  type="date"
                  value={selectedDueDate}
                  onChange={(event) => setSelectedDueDate(event.target.value)}
                  disabled={!canEditTriage || updating || triageUpdating}
                  className="h-10 rounded-xl text-sm"
                />
                <p className="text-[11px] text-muted-foreground">{triageLabels.dueDateHint}</p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleDueDateSave}
                    disabled={!canEditTriage || updating || triageUpdating || selectedDueDate === toDateInputValue(ticketData.dueAt)}
                  >
                    {triageLabels.saveDeadline}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={handleDueDateClear}
                    disabled={!canEditTriage || updating || triageUpdating || (!selectedDueDate && !ticketData.dueAt)}
                  >
                    {triageLabels.clearDeadline}
                  </Button>
                </div>
              </div>

              <Separator />

              <InfoRow icon={User} label={t("detail.assignedTo")} value={ticketData.assignee} />
              <InfoRow icon={User} label={t("detail.reportedBy")} value={ticketData.reporter} />
              <InfoRow icon={Tag} label={t("tickets.type")} value={TICKET_TYPE_CONFIG[ticketData.ticketType].label} />
              <InfoRow icon={Tag} label={t("tickets.category")} value={CATEGORY_CONFIG[ticketData.category].label} />
              <InfoRow
                icon={Calendar}
                label={triageLabels.dueDate}
                value={ticketData.dueAt ? new Date(ticketData.dueAt).toLocaleDateString(localeCode) : triageLabels.notAvailable}
              />
              <InfoRow icon={Calendar} label={t("detail.createdAt")} value={new Date(ticketData.createdAt).toLocaleDateString(localeCode)} />
              <InfoRow icon={Clock} label={t("detail.updatedAt")} value={new Date(ticketData.updatedAt).toLocaleDateString(localeCode)} />
              <InfoRow icon={Clock} label={triageLabels.reassignments} value={String(ticketData.assignmentChangeCount || 0)} />
              <InfoRow
                icon={Clock}
                label={triageLabels.firstAction}
                value={ticketData.firstActionAt
                  ? new Date(ticketData.firstActionAt).toLocaleDateString(localeCode)
                  : triageLabels.notAvailable}
              />

              {ticketData.tags.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t("form.tags")}</p>
                  <div className="flex flex-wrap gap-1">
                    {ticketData.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {canViewHistory && (
            <Card className="surface-card rounded-2xl">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <History className="h-4 w-4 text-primary" />
                  {historyLabels.title}
                </CardTitle>
                <p className="text-xs text-muted-foreground">{historyLabels.subtitle}</p>
              </CardHeader>
              <CardContent className="space-y-3">
                {historyLoading && (
                  <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {historyLabels.loading}
                  </div>
                )}

                {!historyLoading && historyError && (
                  <p className="text-xs text-destructive">{historyLabels.error}</p>
                )}

                {!historyLoading && !historyError && historyEvents.length === 0 && (
                  <p className="text-xs text-muted-foreground">{historyLabels.empty}</p>
                )}

                {!historyLoading && !historyError && historyEvents.length > 0 && (
                  <div className="max-h-[360px] space-y-2 overflow-auto pr-1">
                    {historyEvents.map((event) => (
                      <div key={event.id} className="rounded-xl border border-border/70 bg-background/60 p-3">
                        <p className="text-xs font-semibold text-foreground">{historyActionLabel(event)}</p>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {historyLabels.by} {event.actor} - {new Date(event.createdAt).toLocaleString(localeCode)}
                        </p>
                        {event.changes.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {event.changes.slice(0, 5).map((change, index) => (
                              <p key={`${event.id}-${change.field}-${index}`} className="text-[11px] text-muted-foreground">
                                <span className="font-medium text-foreground">{historyFieldLabel(change.field)}</span>:{" "}
                                {historyValue(change.before)} {"->"} {historyValue(change.after)}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <AlertDialog
        open={Boolean(confirmationDialog)}
        onOpenChange={(open) => {
          if (!open) setConfirmationDialog(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmationDialog?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirmationDialog?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("form.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const action = confirmationDialog?.onConfirm
                setConfirmationDialog(null)
                action?.()
              }}
            >
              {t("general.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" />
      <div>
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-sm text-foreground">{value}</p>
      </div>
    </div>
  )
}
