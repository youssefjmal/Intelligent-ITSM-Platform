// Simple chat UI that calls the backend AI endpoint.
"use client"

import React, { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { ApiError, apiFetch } from "@/lib/api"
import { Send, Bot, User, Sparkles, RotateCcw, Ticket, CheckCircle2, Lightbulb, AlertCircle, BookOpen, ThumbsUp, ThumbsDown, ArrowUpRight } from "lucide-react"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"
import { useRouter } from "next/navigation"
import { getBadgeStyle } from "@/lib/badge-utils"
import { ConfidenceBar } from "@/components/ui/confidence-bar"
import { AssistantMascot } from "@/components/assistant-mascot"
import { RecommendationFeedbackControls } from "@/components/recommendation-feedback-controls"
import {
  type RecommendationCurrentFeedback,
  type RecommendationFeedbackSummary,
  type RecommendationFeedbackType,
  submitChatTicketRecommendationFeedback,
} from "@/lib/ai-feedback-api"
import {
  type ChatActionLink,
  type ChatCauseCandidate,
  type ChatConfidence,
  type ChatRelatedTicketRef,
  type ChatResponsePayload,
  type ChatTicketResult,
  type ProblemDetailPayload,
  type ProblemLinkedTicketsPayload,
  type ProblemListPayload,
  type RecommendationListPayload,
  type TicketThreadPayload,
  type TicketDigestRow,
  type TicketDraft,
  type TicketListPayload,
  type TicketResultsPayload,
  normalizeResponsePayload,
  payloadEntityId,
  payloadEntityKind,
  payloadInventoryKind,
  payloadListedEntityIds,
  ticketListPayloadToResults,
} from "@/lib/chat-types"

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: string
  sourceQuery?: string | null
  ticketDraft?: TicketDraft
  ticketAction?: string | null
  ragGrounding?: boolean
  suggestions?: SuggestionBundle
  draftContext?: DraftContext | null
  actions?: string[]
  ticketResults?: TicketResultsPayload | null
  responsePayload?: ChatResponsePayload | null
  currentFeedback?: RecommendationCurrentFeedback | null
  feedbackSummary?: RecommendationFeedbackSummary | null
  feedbackMessage?: string | null
}

type SuggestionTicket = {
  id: string
  title: string
  similarity_score: number
  status: string
  resolution_snippet?: string | null
}

type SuggestionProblem = {
  id: string
  title: string
  match_reason: string
  root_cause?: string | null
  affected_tickets?: number | null
}

type SuggestionKb = {
  id: string
  title: string
  excerpt: string
  similarity_score: number
  source_type?: string | null
}

type SolutionRecommendation = {
  text: string
  source: string
  source_id?: string | null
  evidence_snippet?: string | null
  quality_score: number
  confidence: number
  helpful_votes?: number
  not_helpful_votes?: number
  reason?: string | null
}

type ResolutionEvidence = {
  evidence_type: string
  reference: string
  excerpt?: string | null
}

type LLMGeneralAdvisoryInline = {
  probable_causes: string[]
  suggested_checks: string[]
  escalation_hint: string | null
  knowledge_source?: string
  confidence?: number
  language?: string
}

type ResolutionAdvice = {
  recommended_action?: string | null
  reasoning: string
  probable_root_cause?: string | null
  evidence_sources: ResolutionEvidence[]
  tentative: boolean
  confidence: number
  confidence_band: string
  source_label: string
  recommendation_mode: string
  action_relevance_score: number
  filtered_weak_match: boolean
  display_mode: "evidence_action" | "tentative_diagnostic" | "service_request" | "llm_general_knowledge" | "no_strong_match"
  match_summary?: string | null
  next_best_actions: string[]
  workflow_steps?: string[]
  validation_steps?: string[]
  fallback_action?: string | null
  missing_information?: string[]
  response_text: string
  llm_general_advisory?: LLMGeneralAdvisoryInline | null
}

type SuggestionBundle = {
  tickets: SuggestionTicket[]
  problems: SuggestionProblem[]
  kb_articles: SuggestionKb[]
  solution_recommendations?: SolutionRecommendation[]
  resolution_advice?: ResolutionAdvice | null
  confidence: number
  source: "embedding" | "hybrid" | "llm_fallback" | string
}

type DraftContext = {
  pre_filled_description: string
  suggested_priority?: string | null
  related_tickets: string[]
  confidence: number
}

const MAX_CHAT_MESSAGES = 40
const MAX_CHAT_CONTENT_LEN = 4000

function normalizeAssistantReply(content: string, locale: string): string {
  const raw = (content || "").trim()
  if (!raw.startsWith("{") || !raw.endsWith("}")) return raw
  try {
    const data = JSON.parse(raw) as {
      reply?: unknown
      solution?: unknown
      ticket?: { title?: unknown } | null
    }
    const reply = typeof data.reply === "string" ? data.reply.trim() : ""
    if (reply) return reply

    if (typeof data.solution === "string" && data.solution.trim()) return data.solution.trim()
    if (Array.isArray(data.solution)) {
      const text = data.solution
        .map((item) => String(item || "").trim())
        .filter(Boolean)
        .join(" ")
      if (text) return text
    }

    const title = String(data.ticket?.title || "").trim()
    if (title) {
      return locale === "fr"
        ? `Resultat IA: ${title}`
        : `AI result: ${title}`
    }
    return raw
  } catch {
    return raw
  }
}

function parseTicketDigest(content: string): { header: string; rows: TicketDigestRow[]; extra: string | null } | null {
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return null

  const rows: TicketDigestRow[] = []
  let extra: string | null = null
  for (const line of lines.slice(1)) {
    if (line.startsWith("...")) {
      extra = line
      continue
    }
    if (!line.startsWith("-")) continue
    const clean = line.replace(/^-+\s*/, "")
    const parts = clean.split("|").map((part) => part.trim())
    if (parts.length < 5) continue
    const [id, title, priority, status, ...assigneeParts] = parts
    rows.push({
      id,
      title,
      priority,
      status,
      assignee: assigneeParts.join(" | "),
    })
  }

  if (!rows.length) return null
  return {
    header: lines[0],
    rows,
    extra,
  }
}

function priorityBadgeClass(priority: string): string {
  const p = priority.toLowerCase()
  if (p.includes("critical") || p.includes("critique")) return "border-red-200 bg-red-500/10 text-red-700"
  if (p.includes("high") || p.includes("haute")) return "border-orange-200 bg-orange-500/10 text-orange-700"
  if (p.includes("medium") || p.includes("moyenne")) return "border-amber-200 bg-amber-500/10 text-amber-700"
  return "border-slate-200 bg-slate-500/10 text-slate-700"
}

function statusBadgeClass(status: string): string {
  const s = status.toLowerCase()
  if (s.includes("open") || s.includes("ouvert")) return "border-blue-200 bg-blue-500/10 text-blue-700"
  if (s.includes("progress") || s.includes("cours")) return "border-cyan-200 bg-cyan-500/10 text-cyan-700"
  if (s.includes("pending") || s.includes("attente")) return "border-yellow-200 bg-yellow-500/10 text-yellow-700"
  if (s.includes("resolved") || s.includes("resolu")) return "border-emerald-200 bg-emerald-500/10 text-emerald-700"
  if (s.includes("closed") || s.includes("clos")) return "border-slate-200 bg-slate-500/10 text-slate-700"
  return "border-muted bg-muted/60 text-foreground"
}

function slaBadgeClass(status?: string | null): string {
  const value = String(status || "").toLowerCase()
  if (value === "breached") return "border-red-200 bg-red-500/10 text-red-700"
  if (value === "at_risk") return "border-amber-200 bg-amber-500/10 text-amber-700"
  if (value === "ok" || value === "completed") return "border-emerald-200 bg-emerald-500/10 text-emerald-700"
  if (value === "paused") return "border-slate-200 bg-slate-500/10 text-slate-700"
  return "border-muted bg-muted/60 text-foreground"
}

function slaStatusLabel(status: string | null | undefined, locale: string): string {
  const value = String(status || "").toLowerCase()
  if (value === "breached") return locale === "fr" ? "SLA depassee" : "SLA breached"
  if (value === "at_risk") return locale === "fr" ? "SLA a risque" : "SLA at risk"
  if (value === "ok") return locale === "fr" ? "SLA ok" : "SLA ok"
  if (value === "completed") return locale === "fr" ? "SLA terminee" : "SLA completed"
  if (value === "paused") return locale === "fr" ? "SLA en pause" : "SLA paused"
  return locale === "fr" ? "SLA inconnue" : "SLA unknown"
}

function formatMessageTime(value: string, locale: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleTimeString(locale === "fr" ? "fr-FR" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  })
}

function isCriticalDigestHeader(header: string): boolean {
  const value = (header || "").toLowerCase()
  return value.includes("critical") || value.includes("critiq")
}

function extractMoreCount(extra: string | null): number {
  if (!extra) return 0
  const match = extra.match(/\d+/)
  if (!match) return 0
  const parsed = Number(match[0])
  return Number.isFinite(parsed) ? parsed : 0
}

function hasSuggestions(bundle?: SuggestionBundle): boolean {
  if (!bundle) return false
  return (
    bundle.tickets.length > 0 ||
    bundle.problems.length > 0 ||
    bundle.kb_articles.length > 0 ||
    (bundle.solution_recommendations || []).length > 0
  )
}

function resolutionModeLabel(mode: ResolutionAdvice["display_mode"], locale: string): string {
  if (mode === "evidence_action") {
    return locale === "fr" ? "Resolution etayee" : "Evidence-backed resolution"
  }
  if (mode === "tentative_diagnostic") {
    return locale === "fr" ? "Diagnostic prudent" : "Tentative diagnostic"
  }
  if (mode === "service_request") {
    return locale === "fr" ? "Guidage de demande de service" : "Service request guidance"
  }
  if (mode === "llm_general_knowledge") {
    return locale === "fr" ? "Connaissance generale" : "General knowledge"
  }
  return locale === "fr" ? "Pas de correspondance forte" : "No strong match"
}

function ticketResultsTitle(results: TicketResultsPayload, locale: string): string {
  if (results.kind === "sla_risk") {
    return locale === "fr" ? "Tickets a risque SLA eleve" : "High SLA risk tickets"
  }
  if (results.kind === "critical") {
    return locale === "fr" ? "Tickets critiques" : "Critical tickets"
  }
  return results.header
}

function ticketCountLabel(count: number, locale: string): string {
  if (locale === "fr") {
    return `${count} ticket${count > 1 ? "s" : ""}`
  }
  return `${count} ticket${count === 1 ? "" : "s"}`
}

function moreTicketsLabel(results: TicketResultsPayload, count: number, locale: string): string {
  if (results.kind === "sla_risk") {
    return locale === "fr" ? `Voir ${count} tickets SLA de plus` : `View ${count} more SLA-risk tickets`
  }
  return locale === "fr" ? `Voir ${count} de plus` : `View ${count} more`
}

type TicketResultButtonProps = {
  row: ChatTicketResult
  locale: string
  compact?: boolean
  onOpenTicket: (ticketId: string) => void
}

function TicketResultButton({ row, locale, compact = false, onOpenTicket }: TicketResultButtonProps) {
  const metadataRows = [
    { label: locale === "fr" ? "Statut" : "Status", value: row.status },
    { label: locale === "fr" ? "Priorite" : "Priority", value: row.priority },
    { label: locale === "fr" ? "Assigne" : "Assignee", value: row.assignee },
    row.ticket_type ? { label: locale === "fr" ? "Type" : "Type", value: row.ticket_type } : null,
    row.category ? { label: locale === "fr" ? "Categorie" : "Category", value: row.category } : null,
    row.sla_status ? { label: "SLA", value: slaStatusLabel(row.sla_status, locale) } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item?.value))

  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onOpenTicket(row.id)
          }}
          className={`w-full rounded-xl border border-border bg-background/70 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-accent/40 focus:outline-none focus:ring-2 focus:ring-primary/30 ${
            compact ? "p-2.5" : "p-3"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className={`font-semibold text-foreground ${compact ? "text-xs" : "text-sm"}`}>{row.id}</p>
              <p className={`mt-1 line-clamp-2 text-foreground/90 ${compact ? "text-xs" : "text-[13px]"}`}>{row.title}</p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-primary">
              {locale === "fr" ? "Ouvrir" : "Open"}
              <ArrowUpRight className="h-3.5 w-3.5" />
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(row.priority)}`}>
              {row.priority}
            </Badge>
            <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(row.status)}`}>
              {row.status}
            </Badge>
            {row.ticket_type ? (
              <Badge variant="outline" className="border-emerald-200 bg-emerald-500/10 text-[10px] text-emerald-700">
                {row.ticket_type}
              </Badge>
            ) : null}
            {row.category ? (
              <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-[10px] text-sky-700">
                {row.category}
              </Badge>
            ) : null}
            {row.sla_status ? (
              <Badge variant="outline" className={`text-[10px] ${slaBadgeClass(row.sla_status)}`}>
                {slaStatusLabel(row.sla_status, locale)}
              </Badge>
            ) : null}
            <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
              {row.assignee}
            </Badge>
          </div>
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="start" className="w-[22rem] space-y-3 p-4">
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {locale === "fr" ? "Apercu du ticket" : "Ticket preview"}
          </p>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">{row.id}</p>
            <p className="text-sm leading-6 text-foreground/90">{row.title}</p>
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {metadataRows.map((item) => (
            <div key={`${row.id}-${item.label}`} className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{item.label}</p>
              <p className="mt-1 text-xs text-foreground">{item.value}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          {locale === "fr" ? "Cliquez pour ouvrir la fiche complete du ticket." : "Click to open the full ticket page."}
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}

type TicketResultsMessageProps = {
  results: TicketResultsPayload
  locale: string
  onOpenTicket: (ticketId: string) => void
}

function TicketResultsMessage({ results, locale, onOpenTicket }: TicketResultsMessageProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const title = ticketResultsTitle(results, locale)
  const visibleRows = results.tickets.slice(0, 3)
  const overflowRows = results.tickets.slice(3)
  const previewRows = overflowRows.slice(0, 5)

  return (
    <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
        <Badge variant="outline" className="text-[10px]">
          {ticketCountLabel(results.total_count, locale)}
        </Badge>
      </div>
      {results.scope ? <p className="text-[11px] text-muted-foreground">{results.scope}</p> : null}
      <div className="space-y-2">
        {visibleRows.map((row) => (
          <TicketResultButton key={`ticket-result-${row.id}`} row={row} locale={locale} onOpenTicket={onOpenTicket} />
        ))}
      </div>
      {overflowRows.length > 0 ? (
        <div className="pt-0.5">
          <HoverCard openDelay={100} closeDelay={90}>
            <HoverCardTrigger asChild>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  setDialogOpen(true)
                }}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                {moreTicketsLabel(results, overflowRows.length, locale)}
              </button>
            </HoverCardTrigger>
            <HoverCardContent align="start" className="w-[26rem] space-y-2 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Apercu rapide" : "Quick preview"}
              </p>
              <div className="space-y-2">
                {previewRows.map((row) => (
                  <TicketResultButton
                    key={`ticket-preview-${row.id}`}
                    row={row}
                    locale={locale}
                    compact
                    onOpenTicket={onOpenTicket}
                  />
                ))}
              </div>
              {overflowRows.length > previewRows.length ? (
                <p className="text-[11px] text-muted-foreground">
                  {locale === "fr"
                    ? `Cliquez pour voir les ${overflowRows.length} tickets restants.`
                    : `Click to view all ${overflowRows.length} remaining tickets.`}
                </p>
              ) : null}
            </HoverCardContent>
          </HoverCard>

          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogContent className="max-w-3xl gap-0 overflow-hidden p-0">
              <DialogHeader className="border-b border-border/70 px-6 py-4">
                <DialogTitle className="text-base">{title}</DialogTitle>
                <DialogDescription>
                  {locale === "fr"
                    ? `${overflowRows.length} ticket${overflowRows.length > 1 ? "s" : ""} supplementaire${overflowRows.length > 1 ? "s" : ""}`
                    : `${overflowRows.length} additional ticket${overflowRows.length === 1 ? "" : "s"}`}
                </DialogDescription>
              </DialogHeader>
              <div className="px-6 pb-6 pt-4">
                <ScrollArea className="max-h-[60vh] pr-4">
                  {overflowRows.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {locale === "fr" ? "Aucun ticket supplementaire." : "No additional tickets."}
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {overflowRows.map((row) => (
                        <TicketResultButton
                          key={`ticket-dialog-${row.id}`}
                          row={row}
                          locale={locale}
                          onOpenTicket={(ticketId) => {
                            setDialogOpen(false)
                            onOpenTicket(ticketId)
                          }}
                        />
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      ) : null}
    </div>
  )
}


function ProblemListMessage({
  payload,
  locale,
  onOpenProblem,
}: {
  payload: ProblemListPayload
  locale: string
  onOpenProblem: (problemId: string) => void
}) {
  const [showAll, setShowAll] = useState(false)
  const visibleProblems = showAll ? payload.problems : payload.problems.slice(0, 5)

  return (
    <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {payload.title || (locale === "fr" ? "Problemes" : "Problems")}
        </p>
        <Badge variant="outline" className="text-[10px]">{payload.total_count}</Badge>
        {payload.status_filter ? <Badge variant="outline" className="text-[10px]">{payload.status_filter}</Badge> : null}
      </div>
      {payload.scope ? <p className="text-[11px] text-muted-foreground">{payload.scope}</p> : null}
      <div className="overflow-x-auto rounded-lg border border-border/70">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border/70 bg-muted/30">
              <th className="px-3 py-2 text-left font-semibold text-muted-foreground">ID</th>
              <th className="px-3 py-2 text-left font-semibold text-muted-foreground">{locale === "fr" ? "Titre" : "Title"}</th>
              <th className="px-3 py-2 text-left font-semibold text-muted-foreground">{locale === "fr" ? "Statut" : "Status"}</th>
              <th className="px-3 py-2 text-right font-semibold text-muted-foreground">{locale === "fr" ? "Occurrences" : "Occurrences"}</th>
            </tr>
          </thead>
          <tbody>
            {visibleProblems.map((problem) => (
              <tr
                key={`pl-row-${problem.id}`}
                className="cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/20"
                onClick={() => onOpenProblem(problem.id)}
              >
                <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">{problem.id}</td>
                <td className="px-3 py-2 max-w-[200px] text-foreground">
                  <div className="truncate">{problem.title}</div>
                </td>
                <td className="px-3 py-2">
                  <span className={getBadgeStyle("problem_status", problem.status)}>{problem.status}</span>
                </td>
                <td className="px-3 py-2 text-right text-muted-foreground">{problem.occurrences_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!showAll && payload.problems.length > 5 ? (
        <button
          type="button"
          className="text-[11px] text-muted-foreground transition-colors hover:text-foreground hover:underline underline-offset-2"
          onClick={() => setShowAll(true)}
        >
          {locale === "fr" ? `Voir ${payload.problems.length - 5} probleme(s) de plus` : `View ${payload.problems.length - 5} more problems`}
        </button>
      ) : null}
    </div>
  )
}


function ProblemLinkedTicketsMessage({
  payload,
  locale,
  onOpenTicket,
}: {
  payload: ProblemLinkedTicketsPayload
  locale: string
  onOpenTicket: (route: string) => void
}) {
  const [showAll, setShowAll] = useState(false)
  const visibleTickets = showAll ? payload.tickets : payload.tickets.slice(0, 5)

  return (
    <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {payload.title || (locale === "fr" ? "Tickets lies au probleme" : "Problem linked tickets")}
        </p>
        <Badge variant="outline" className="text-[10px]">{payload.problem_id}</Badge>
        <Badge variant="outline" className="text-[10px]">{payload.total_count}</Badge>
      </div>
      <div className="space-y-2">
        {visibleTickets.map((ticket) => (
          <TicketResultButton
            key={`problem-linked-${ticket.id}`}
            row={{
              id: ticket.id,
              title: ticket.title,
              status: ticket.status,
              priority: ticket.priority,
              assignee: ticket.assignee,
            }}
            locale={locale}
            onOpenTicket={() => onOpenTicket(ticket.route)}
          />
        ))}
      </div>
      {!showAll && payload.tickets.length > 5 ? (
        <button
          type="button"
          className="text-[11px] text-muted-foreground transition-colors hover:text-foreground hover:underline underline-offset-2"
          onClick={() => setShowAll(true)}
        >
          {locale === "fr" ? `Voir ${payload.tickets.length - 5} ticket(s) de plus` : `View ${payload.tickets.length - 5} more tickets`}
        </button>
      ) : null}
    </div>
  )
}


function RecommendationListMessage({
  payload,
  locale,
  onOpenRecommendations,
}: {
  payload: RecommendationListPayload
  locale: string
  onOpenRecommendations: () => void
}) {
  const [showAll, setShowAll] = useState(false)
  const visibleRecommendations = showAll ? payload.recommendations : payload.recommendations.slice(0, 5)

  function getConfidenceBand(c: number): "high" | "medium" | "low" | "general_knowledge" {
    if (c <= 0.25) return "general_knowledge"
    if (c >= 0.78) return "high"
    if (c >= 0.52) return "medium"
    return "low"
  }

  return (
    <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {payload.title || (locale === "fr" ? "Recommandations" : "Recommendations")}
        </p>
        <Badge variant="outline" className="text-[10px]">{payload.total_count}</Badge>
      </div>
      {payload.scope ? <p className="text-[11px] text-muted-foreground">{payload.scope}</p> : null}
      <div className="space-y-2">
        {visibleRecommendations.map((rec) => (
          <div key={`rl-rec-${rec.id}`} className="space-y-2 rounded-lg border border-border bg-background/70 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-[13px] font-semibold text-foreground">{rec.title}</p>
              <Badge variant="outline" className="text-[10px]">{rec.type}</Badge>
              <Badge variant="outline" className="text-[10px]">{rec.impact}</Badge>
            </div>
            <p className="line-clamp-2 text-[12px] text-muted-foreground">{rec.description}</p>
            <ConfidenceBar confidence={rec.confidence} band={getConfidenceBand(rec.confidence)} size="sm" />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {!showAll && payload.recommendations.length > 5 ? (
          <button
            type="button"
            className="text-[11px] text-muted-foreground transition-colors hover:text-foreground hover:underline underline-offset-2"
            onClick={() => setShowAll(true)}
          >
            {locale === "fr" ? `Voir ${payload.recommendations.length - 5} recommandation(s) de plus` : `View ${payload.recommendations.length - 5} more recommendations`}
          </button>
        ) : null}
        <button
          type="button"
          className="text-[12px] text-blue-600 transition-colors hover:text-blue-800"
          onClick={onOpenRecommendations}
        >
          {locale === "fr" ? "Voir toutes les recommandations" : "View all recommendations"} →
        </button>
      </div>
    </div>
  )
}

function confidenceBadgeClass(level: ChatConfidence["level"]): string {
  if (level === "high") return "border-emerald-200 bg-emerald-500/10 text-emerald-700"
  if (level === "medium") return "border-amber-200 bg-amber-500/10 text-amber-700"
  return "border-red-200 bg-red-500/10 text-red-700"
}

function likelihoodBadgeClass(level: ChatCauseCandidate["likelihood"]): string {
  if (level === "high") return "border-red-200 bg-red-500/10 text-red-700"
  if (level === "medium") return "border-amber-200 bg-amber-500/10 text-amber-700"
  return "border-slate-200 bg-slate-500/10 text-slate-700"
}

function structuredDateLabel(value: string | null | undefined, locale: string): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString(locale === "fr" ? "fr-FR" : "en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function StructuredSection({
  title,
  items,
}: {
  title: string
  items: string[]
}) {
  if (!items.length) return null
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <ul className="list-disc space-y-1 pl-4 text-[13px] leading-6 text-foreground/95">
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function ActionLinks({
  links,
  onOpenRoute,
}: {
  links: ChatActionLink[]
  onOpenRoute: (route: string) => void
}) {
  if (!links.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {links.map((link) => (
        <Button
          key={`${link.label}-${link.route}`}
          type="button"
          size="sm"
          variant="outline"
          className="h-8 rounded-full"
          onClick={(event) => {
            event.stopPropagation()
            onOpenRoute(link.route)
          }}
        >
          {link.label}
        </Button>
      ))}
    </div>
  )
}

function RelatedTicketChips({
  tickets,
  onOpenRoute,
}: {
  tickets: ChatRelatedTicketRef[]
  onOpenRoute: (route: string) => void
}) {
  if (!tickets.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {tickets.map((ticket) => (
        <button
          key={`${ticket.ticket_id}-${ticket.route}`}
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onOpenRoute(ticket.route)
          }}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1 text-xs text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
        >
          <span className="font-semibold">{ticket.ticket_id}</span>
          <ArrowUpRight className="h-3 w-3 text-primary" />
        </button>
      ))}
    </div>
  )
}

type AssistantTextBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }

function parseAssistantTextBlocks(content: string): AssistantTextBlock[] {
  const lines = String(content || "").replace(/\r/g, "").split("\n")
  const blocks: AssistantTextBlock[] = []
  let i = 0

  const bulletPattern = /^[-*\u2022]\s+(.+)$/
  const orderedPattern = /^\d+[\.\)]\s+(.+)$/

  while (i < lines.length) {
    const line = lines[i].trim()
    if (!line) {
      i += 1
      continue
    }

    const bulletMatch = line.match(bulletPattern)
    const orderedMatch = line.match(orderedPattern)
    if (bulletMatch || orderedMatch) {
      const ordered = Boolean(orderedMatch)
      const items: string[] = []
      while (i < lines.length) {
        const current = lines[i].trim()
        const match = ordered ? current.match(orderedPattern) : current.match(bulletPattern)
        if (!match) break
        const value = String(match[1] || "").trim()
        if (value) items.push(value)
        i += 1
      }
      if (items.length) {
        blocks.push({ kind: "list", ordered, items })
      }
      continue
    }

    const paragraphLines: string[] = [line]
    i += 1
    while (i < lines.length) {
      const current = lines[i].trim()
      if (!current) break
      if (bulletPattern.test(current) || orderedPattern.test(current)) break
      paragraphLines.push(current)
      i += 1
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") })
  }

  return blocks
}

/**
 * Formats chat messages as plain text for export.
 * Handles both plain content and structured response payloads.
 *
 * @param messages - Array of ChatMessage objects
 * @param ticketId - Optional ticket ID for the filename context
 * @returns Formatted plain-text string
 */
function formatChatAsText(messages: ChatMessage[], ticketId: string | null): string {
  const date = new Date().toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" })
  const lines = [`--- Conversation IA exportée le ${date} ---`, ""]
  for (const msg of messages) {
    const time = msg.createdAt
      ? new Date(msg.createdAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
      : ""
    const role = msg.role === "user" ? "Agent" : "IA"
    let text = ""
    if (msg.content && msg.content.trim()) {
      text = msg.content
    } else if (msg.responsePayload && "summary" in msg.responsePayload) {
      text = `[Structured] ${msg.responsePayload.summary}`
    } else {
      text = JSON.stringify(msg.responsePayload || "").slice(0, 200)
    }
    lines.push(`[${time}] ${role}: ${text}`)
  }
  return lines.join("\n")
}

/**
 * Triggers a browser download of the chat as a .txt file.
 *
 * @param messages - Array of ChatMessage objects
 * @param ticketId - Optional ticket ID for the filename
 */
function downloadChatTxt(messages: ChatMessage[], ticketId: string | null) {
  const text = formatChatAsText(messages, ticketId)
  const date = new Date().toISOString().split("T")[0]
  const filename = ticketId ? `chat-${ticketId}-${date}.txt` : `chat-${date}.txt`
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function TicketChatbot() {
  const { t, locale } = useI18n()
  const { user, hasPermission } = useAuth()
  const router = useRouter()
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [exportSuccess, setExportSuccess] = useState(false)
  // pendingSuggestion holds the suggestion awaiting explicit user confirmation
  // before it is applied to the ticket draft.  null means no confirmation is
  // currently shown.  This gate exists because this is a copilot, not an agent
  // — no action should be taken on the user's behalf without confirmation.
  const [pendingSuggestion, setPendingSuggestion] = useState<{
    messageId: string
    solution: string
    sourceId: string
  } | null>(null)
  const [criticalOverflowRows, setCriticalOverflowRows] = useState<TicketDigestRow[]>([])
  const [criticalOverflowLoaded, setCriticalOverflowLoaded] = useState(false)
  const [criticalOverflowLoading, setCriticalOverflowLoading] = useState(false)
  const [feedbackSubmitting, setFeedbackSubmitting] = useState<Record<string, boolean>>({})
  const [cmdOpen, setCmdOpen] = useState(false)
  const [cmdQuery, setCmdQuery] = useState("")
  const [cmdIndex, setCmdIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const endOfMessagesRef = useRef<HTMLDivElement>(null)
  const chatAbortRef = useRef<AbortController | null>(null)

  // Derive the last mentioned ticket ID from structured response payloads
  const lastTicketId: string | null = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const payload = messages[i].responsePayload
      if (!payload) continue
      if ("ticket_id" in payload && typeof payload.ticket_id === "string") {
        return payload.ticket_id
      }
    }
    return null
  })()

  function resolveSourceQuery(messageId: string): string {
    const index = messages.findIndex((message) => message.id === messageId)
    if (index === -1) return ""
    const current = messages[index]
    if (current.sourceQuery) return current.sourceQuery
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        return messages[i].content || ""
      }
    }
    return ""
  }

  async function copyToComments(msgs: ChatMessage[], ticketId: string) {
    const text = formatChatAsText(msgs, ticketId)
    try {
      const res = await fetch(`/api/tickets/${ticketId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text, author: "IA Export" }),
      })
      if (res.ok) {
        setExportSuccess(true)
        setTimeout(() => setExportSuccess(false), 3000)
      }
    } catch {
      console.warn("[chatExport] copy to comments failed")
    }
  }

  async function loadCriticalOverflowRows() {
    if (criticalOverflowLoaded || criticalOverflowLoading) return
    setCriticalOverflowLoading(true)
    try {
      const rows = await apiFetch<
        Array<{
          id: string
          title: string
          priority: "critical" | "high" | "medium" | "low"
          status:
            | "open"
            | "in-progress"
            | "waiting-for-customer"
            | "waiting-for-support-vendor"
            | "pending"
            | "resolved"
            | "closed"
          assignee: string
          created_at?: string
          updated_at: string
        }>
      >("/tickets")
      const active = new Set([
        "open",
        "in-progress",
        "waiting-for-customer",
        "waiting-for-support-vendor",
        "pending",
      ])
      const mapped = rows
        .filter((ticket) => ticket.priority === "critical" && active.has(ticket.status))
        .sort((left, right) => {
          const leftTs = new Date(left.created_at || left.updated_at).getTime()
          const rightTs = new Date(right.created_at || right.updated_at).getTime()
          return rightTs - leftTs
        })
        .slice(3, 12)
        .map((ticket) => ({
          id: ticket.id,
          title: ticket.title,
          priority: t("priority.critical"),
          status:
            ticket.status === "open"
              ? t("status.open")
              : ticket.status === "in-progress"
                ? t("status.inProgress")
                : ticket.status === "waiting-for-customer"
                  ? t("status.waitingForCustomer")
                  : ticket.status === "waiting-for-support-vendor"
                    ? t("status.waitingForSupportVendor")
                : ticket.status === "pending"
                  ? t("status.pending")
                  : ticket.status === "resolved"
                    ? t("status.resolved")
                    : t("status.closed"),
          assignee: ticket.assignee,
        }))
      setCriticalOverflowRows(mapped)
    } catch {
      setCriticalOverflowRows([])
    } finally {
      setCriticalOverflowLoaded(true)
      setCriticalOverflowLoading(false)
    }
  }

  /**
   * Initiates the apply flow for a chat-suggested fix.
   * Does NOT apply immediately — sets pendingSuggestion to trigger an inline
   * confirmation UI.  The actual application only happens after explicit user
   * confirmation via _doApplySuggestion.
   *
   * Also clears any in-progress confirmation if the source changes, so that
   * sending a new chat message (which triggers a new suggestion) automatically
   * dismisses a stale confirmation row.
   *
   * This gate exists because this is a copilot, not an agent.  No action
   * should be taken on the user's behalf without confirmation.
   */
  function handleApplySuggestion(messageId: string, solution: string, sourceId: string) {
    const normalized = solution.trim()
    if (!normalized) return
    setPendingSuggestion({ messageId, solution: normalized, sourceId })
  }

  /**
   * Performs the actual draft mutation after the user has confirmed the apply.
   * Contains the original apply logic moved from handleApplySuggestion.
   *
   * Called only from the inline confirmation "Confirm" button, never directly.
   */
  function _doApplySuggestion(messageId: string, solution: string, sourceId: string) {
    setPendingSuggestion(null)
    setMessages((prev) =>
      prev.map((item) => {
        if (item.id !== messageId) return item
        if (item.ticketDraft) {
          const marker = `Suggested fix (from ${sourceId}):`
          if (item.ticketDraft.description.includes(marker)) return item
          return {
            ...item,
            ticketDraft: {
              ...item.ticketDraft,
              description: `${item.ticketDraft.description}\n\n${marker}\n${solution}`.trim(),
            },
          }
        }
        return item
      }),
    )
    setInput((current) => {
      if (current.trim()) return current
      return `Create a ticket for this issue. Suggested fix: ${solution}`
    })
  }

  function getChatErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 401) {
        return locale === "fr" ? "Session expiree. Reconnectez-vous." : "Session expired. Please sign in again."
      }
      if (error.status === 422) {
        return locale === "fr"
          ? "Message invalide ou conversation trop longue. Reinitialisez le chat."
          : "Invalid message or conversation too long. Reset the chat."
      }
    }
    return t("chat.errorReply")
  }

  async function submitSolutionFeedback(
    messageId: string,
    recommendation: SolutionRecommendation,
    vote: "helpful" | "not_helpful",
    query: string,
  ) {
    const key = `${messageId}-${recommendation.source}-${recommendation.source_id || recommendation.text.slice(0, 24)}-${vote}`
    if (feedbackSubmitting[key]) return
    setFeedbackSubmitting((prev) => ({ ...prev, [key]: true }))
    try {
      await apiFetch("/ai/feedback", {
        method: "POST",
        body: JSON.stringify({
          query,
          recommendation_text: recommendation.text,
          source: recommendation.source,
          source_id: recommendation.source_id || null,
          vote,
          context: {
            ui: "ticket_chatbot",
            quality_score: recommendation.quality_score,
            confidence: recommendation.confidence,
          },
        }),
      })
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== messageId || !msg.suggestions?.solution_recommendations) return msg
          const nextRows = msg.suggestions.solution_recommendations.map((row) => {
            if (row.text !== recommendation.text || row.source !== recommendation.source || (row.source_id || "") !== (recommendation.source_id || "")) {
              return row
            }
            return {
              ...row,
              helpful_votes: (row.helpful_votes || 0) + (vote === "helpful" ? 1 : 0),
              not_helpful_votes: (row.not_helpful_votes || 0) + (vote === "not_helpful" ? 1 : 0),
            }
          })
          return { ...msg, suggestions: { ...msg.suggestions, solution_recommendations: nextRows } }
        }),
      )
    } catch {
      // no-op
    } finally {
      setFeedbackSubmitting((prev) => ({ ...prev, [key]: false }))
    }
  }

  function chatFeedbackTarget(message: ChatMessage): { ticketId: string; answerType: "resolution_advice" | "cause_analysis" } | null {
    const payload = message.responsePayload
    if (payload?.type === "resolution_advice" && payload.ticket_id) {
      return { ticketId: payload.ticket_id, answerType: "resolution_advice" }
    }
    if (payload?.type === "cause_analysis" && payload.ticket_id) {
      return { ticketId: payload.ticket_id, answerType: "cause_analysis" }
    }
    return null
  }

  async function submitChatAgentFeedback(message: ChatMessage, feedbackType: RecommendationFeedbackType) {
    const target = chatFeedbackTarget(message)
    if (!target) return
    const key = `${message.id}-agent-feedback`
    if (feedbackSubmitting[key]) return
    const payload = message.responsePayload
    const advice = message.suggestions?.resolution_advice
    const recommendedAction =
      advice?.recommended_action ||
      advice?.fallback_action ||
      (payload?.type === "resolution_advice" ? payload.recommended_actions[0]?.text : null) ||
      (payload?.type === "cause_analysis" ? payload.recommended_checks[0] : null) ||
      null
    const reasoning =
      advice?.reasoning ||
      (payload?.type === "cause_analysis" ? payload.summary : payload?.type === "resolution_advice" ? payload.summary : null) ||
      null
    const displayMode =
      advice?.display_mode ||
      (payload?.type === "cause_analysis" ? "cause_analysis" : payload?.type === "resolution_advice" ? "resolution_advice" : null) ||
      null
    const confidence =
      advice?.confidence ||
      (payload?.type === "cause_analysis" || payload?.type === "resolution_advice" ? Math.max(0, Math.min(1, payload.confidence?.level === "high" ? 0.85 : payload.confidence?.level === "medium" ? 0.6 : 0.35)) : null)
    const evidenceCount =
      advice?.evidence_sources?.length ||
      (payload?.type === "resolution_advice"
        ? payload.recommended_actions.reduce((count, step) => count + step.evidence.length, 0)
        : payload?.type === "cause_analysis"
          ? payload.possible_causes.reduce((count, cause) => count + cause.evidence.length, 0)
          : 0)

    setFeedbackSubmitting((prev) => ({ ...prev, [key]: true }))
    try {
      const result = await submitChatTicketRecommendationFeedback({
        ticketId: target.ticketId,
        answerType: target.answerType,
        feedbackType,
        recommendedAction,
        displayMode,
        confidence,
        reasoning,
        matchSummary: payload?.type === "resolution_advice" || payload?.type === "cause_analysis" ? payload.summary : advice?.match_summary || null,
        evidenceCount,
        metadata: {
          recommendation_mode: advice?.recommendation_mode || (payload?.type === "cause_analysis" ? "cause_analysis" : "resolution_advice"),
          source_label: advice?.source_label || "ticket_chatbot",
          confidence_band: advice?.confidence_band || (payload?.type === "resolution_advice" || payload?.type === "cause_analysis" ? payload.confidence?.level : "unknown"),
        },
      })
      setMessages((prev) =>
        prev.map((entry) =>
          entry.id === message.id
            ? {
                ...entry,
                currentFeedback: result.currentFeedback,
                feedbackSummary: result.feedbackSummary,
                feedbackMessage: locale === "fr" ? "Retour enregistre" : "Feedback saved",
              }
            : entry,
        ),
      )
    } catch {
      setMessages((prev) =>
        prev.map((entry) =>
          entry.id === message.id
            ? {
                ...entry,
                feedbackMessage: locale === "fr" ? "Echec de l'enregistrement" : "Could not save feedback",
              }
            : entry,
        ),
      )
    } finally {
      setFeedbackSubmitting((prev) => ({ ...prev, [key]: false }))
    }
  }

  function renderAssistantMessage(message: ChatMessage) {
    const isUserMessage = message.role === "user"
    const payload = message.responsePayload
    if (payload) {
      if (payload.type === "ticket_status") {
        const updatedAt = structuredDateLabel(payload.updated_at, locale)
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.ticket_id}</p>
              <p className="text-sm font-semibold text-foreground">{payload.title}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(payload.status)}`}>
                {payload.status}
              </Badge>
              <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(payload.priority)}`}>
                {payload.priority}
              </Badge>
              {payload.sla_state ? (
                <Badge variant="outline" className={`text-[10px] ${slaBadgeClass(payload.sla_state)}`}>
                  {slaStatusLabel(payload.sla_state, locale)}
                </Badge>
              ) : null}
              <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                {payload.assignee}
              </Badge>
            </div>
            <p className="text-[13px] leading-6 text-foreground/95">{payload.summary}</p>
            {updatedAt ? <p className="text-[11px] text-muted-foreground">{locale === "fr" ? `Mis a jour: ${updatedAt}` : `Updated: ${updatedAt}`}</p> : null}
            <ActionLinks links={payload.actions} onOpenRoute={(route) => router.push(route)} />
          </div>
        )
      }

      if (payload.type === "ticket_details") {
        const createdAt = structuredDateLabel(payload.created_at, locale)
        const updatedAt = structuredDateLabel(payload.updated_at, locale)
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.ticket_id}</p>
              <p className="text-sm font-semibold text-foreground">{payload.title}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(payload.status)}`}>
                {payload.status}
              </Badge>
              <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(payload.priority)}`}>
                {payload.priority}
              </Badge>
              {payload.ticket_type ? (
                <Badge variant="outline" className="text-[10px] border-emerald-200 bg-emerald-500/10 text-emerald-700">
                  {payload.ticket_type}
                </Badge>
              ) : null}
              {payload.sla?.state ? (
                <Badge variant="outline" className={`text-[10px] ${slaBadgeClass(payload.sla.state)}`}>
                  {slaStatusLabel(payload.sla.state, locale)}
                </Badge>
              ) : null}
              <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                {payload.assignee}
              </Badge>
              {payload.reporter ? (
                <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                  {payload.reporter}
                </Badge>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Description" : "Description"}
              </p>
              <p className="whitespace-pre-wrap text-[13px] leading-6 text-foreground/95">{payload.description}</p>
            </div>
            <div className="grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-2">
              {payload.ticket_type ? <p>{locale === "fr" ? `Type: ${payload.ticket_type}` : `Type: ${payload.ticket_type}`}</p> : null}
              {payload.category ? <p>{locale === "fr" ? `Categorie: ${payload.category}` : `Category: ${payload.category}`}</p> : null}
              {createdAt ? <p>{locale === "fr" ? `Cree: ${createdAt}` : `Created: ${createdAt}`}</p> : null}
              {updatedAt ? <p>{locale === "fr" ? `Mis a jour: ${updatedAt}` : `Updated: ${updatedAt}`}</p> : null}
              {payload.sla?.remaining_human ? (
                <p>{locale === "fr" ? `SLA restant: ${payload.sla.remaining_human}` : `SLA remaining: ${payload.sla.remaining_human}`}</p>
              ) : null}
            </div>
            {payload.recent_comments.length ? (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr" ? "Commentaires recents" : "Recent comments"}
                </p>
                <div className="space-y-2">
                  {payload.recent_comments.map((comment, index) => (
                    <div key={`comment-${index}`} className="rounded-xl border border-border/70 bg-background/70 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        {comment.author ? <span className="font-medium text-foreground/85">{comment.author}</span> : null}
                        {comment.created_at ? <span>{structuredDateLabel(comment.created_at, locale)}</span> : null}
                      </div>
                      <p className="mt-1.5 text-[13px] leading-6 text-foreground/95">{comment.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {payload.related_entities.length ? (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr" ? "Entites liees" : "Related entities"}
                </p>
                <div className="flex flex-wrap gap-2">
                  {payload.related_entities.map((entity) => (
                    <button
                      key={`${entity.entity_type}-${entity.entity_id}`}
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        router.push(entity.route)
                      }}
                      className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1 text-xs text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
                    >
                      <span className="font-semibold">{entity.entity_id}</span>
                      <span className="text-muted-foreground">{entity.relation || entity.entity_type}</span>
                      <ArrowUpRight className="h-3 w-3 text-primary" />
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <ActionLinks links={payload.actions} onOpenRoute={(route) => router.push(route)} />
          </div>
        )
      }

      if (payload.type === "ticket_list") {
        const results = ticketListPayloadToResults(payload)
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="text-[10px]">
                {locale === "fr" ? `${payload.summary_metrics.open_count} actifs` : `${payload.summary_metrics.open_count} active`}
              </Badge>
              <Badge variant="outline" className="text-[10px]">
                {locale === "fr" ? `${payload.summary_metrics.critical_count} critiques` : `${payload.summary_metrics.critical_count} critical`}
              </Badge>
            </div>
            {payload.top_recommendation ? (
              <div className="rounded-xl border border-border/70 bg-background/70 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr" ? "Recommandation principale" : "Top recommendation"}
                </p>
                <p className="mt-1 text-[13px] leading-6 text-foreground/95">{payload.top_recommendation.summary}</p>
                <Badge variant="outline" className="mt-2 text-[10px]">
                  {locale === "fr" ? "Confiance" : "Confidence"} {Math.round(payload.top_recommendation.confidence * 100)}%
                </Badge>
              </div>
            ) : null}
            <TicketResultsMessage results={results} locale={locale} onOpenTicket={(ticketId) => router.push(`/tickets/${ticketId}`)} />
          </div>
        )
      }

      if (payload.type === "resolution_advice") {
        const feedbackKey = `${message.id}-agent-feedback`
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            {payload.ticket_id ? <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.ticket_id}</p> : null}
            <div className="rounded-xl border border-border/70 bg-background/70 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Resume" : "Summary"}
              </p>
              <p className="mt-1 text-[13px] leading-6 text-foreground/95">{payload.summary}</p>
            </div>
            {payload.recommended_actions.length ? (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr" ? "Actions recommandees" : "Recommended actions"}
                </p>
                <div className="space-y-2">
                  {payload.recommended_actions.map((step) => (
                    <div key={`advice-step-${step.step}`} className="rounded-xl border border-border/70 bg-background/70 p-3">
                      <p className="text-[13px] font-semibold text-foreground">
                        {locale === "fr" ? `Etape ${step.step}` : `Step ${step.step}`} - {step.text}
                      </p>
                      {step.reason ? <p className="mt-1 text-[12px] leading-6 text-muted-foreground">{step.reason}</p> : null}
                      {step.evidence.length ? (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {step.evidence.map((evidence, index) => (
                            <Badge key={`evidence-${step.step}-${index}`} variant="outline" className="text-[10px]">
                              {evidence}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <StructuredSection title={locale === "fr" ? "Pourquoi cela correspond" : "Why this matches"} items={payload.why_this_matches} />
            <StructuredSection title={locale === "fr" ? "Validation" : "Validation"} items={payload.validation_steps} />
            <StructuredSection title={locale === "fr" ? "Etapes suivantes" : "Next steps"} items={payload.next_steps} />
            {payload.related_tickets.length ? (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr" ? "Tickets lies" : "Related tickets"}
                </p>
                <RelatedTicketChips tickets={payload.related_tickets} onOpenRoute={(route) => router.push(route)} />
              </div>
            ) : null}
            {payload.confidence?.level && (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={`text-[10px] ${confidenceBadgeClass(payload.confidence.level)}`}>
                  {locale === "fr" ? "Confiance" : "Confidence"}: {payload.confidence.level}
                </Badge>
                {payload.confidence.reason && (
                  <p className="text-[12px] text-muted-foreground">{payload.confidence.reason}</p>
                )}
              </div>
            )}
            {payload.ticket_id ? (
              <RecommendationFeedbackControls
                locale={locale}
                compact
                currentFeedback={message.currentFeedback}
                feedbackSummary={message.feedbackSummary}
                successMessage={message.feedbackMessage}
                submitting={Boolean(feedbackSubmitting[feedbackKey])}
                onSubmit={(feedbackType) => submitChatAgentFeedback(message, feedbackType)}
              />
            ) : null}
          </div>
        )
      }

      if (payload.type === "cause_analysis") {
        const feedbackKey = `${message.id}-agent-feedback`
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            {payload.ticket_id ? <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.ticket_id}</p> : null}
            <div className="rounded-xl border border-border/70 bg-background/70 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Analyse" : "Analysis"}
              </p>
              <p className="mt-1 text-[13px] leading-6 text-foreground/95">{payload.summary}</p>
            </div>
            <div className="space-y-2">
              {payload.possible_causes.map((cause, index) => (
                <div key={`cause-${index}`} className="rounded-xl border border-border/70 bg-background/70 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-[13px] font-semibold text-foreground">{cause.title}</p>
                    <Badge variant="outline" className={`text-[10px] ${likelihoodBadgeClass(cause.likelihood)}`}>
                      {locale === "fr" ? "Probabilite" : "Likelihood"}: {cause.likelihood}
                    </Badge>
                  </div>
                  <p className="mt-1 text-[12px] leading-6 text-muted-foreground">{cause.explanation}</p>
                  {cause.evidence.length ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {cause.evidence.map((evidence, evidenceIndex) => (
                        <Badge key={`cause-evidence-${index}-${evidenceIndex}`} variant="outline" className="text-[10px]">
                          {evidence}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  {cause.related_tickets.length ? (
                    <div className="mt-2">
                      <RelatedTicketChips tickets={cause.related_tickets} onOpenRoute={(route) => router.push(route)} />
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            <StructuredSection title={locale === "fr" ? "Controles recommandes" : "Recommended checks"} items={payload.recommended_checks} />
            <StructuredSection title={locale === "fr" ? "Validation" : "Validation"} items={payload.validation_steps} />
            {payload.confidence?.level && (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={`text-[10px] ${confidenceBadgeClass(payload.confidence.level)}`}>
                  {locale === "fr" ? "Confiance" : "Confidence"}: {payload.confidence.level}
                </Badge>
                {payload.confidence.reason && (
                  <p className="text-[12px] text-muted-foreground">{payload.confidence.reason}</p>
                )}
              </div>
            )}
            {payload.ticket_id ? (
              <RecommendationFeedbackControls
                locale={locale}
                compact
                currentFeedback={message.currentFeedback}
                feedbackSummary={message.feedbackSummary}
                successMessage={message.feedbackMessage}
                submitting={Boolean(feedbackSubmitting[feedbackKey])}
                onSubmit={(feedbackType) => submitChatAgentFeedback(message, feedbackType)}
              />
            ) : null}
          </div>
        )
      }

      if (payload.type === "similar_tickets") {
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            {payload.source_ticket_id ? <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.source_ticket_id}</p> : null}
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {locale === "fr" ? "Tickets similaires" : "Similar tickets"}
            </p>
            <div className="space-y-2">
              {payload.matches.map((match) => (
                <button
                  key={`similar-${match.ticket_id}`}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    router.push(match.route)
                  }}
                  className="w-full rounded-xl border border-border bg-background/70 p-3 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-accent/40"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-foreground">{match.ticket_id}</p>
                    <Badge variant="outline" className="text-[10px]">
                      {locale === "fr" ? "Score" : "Score"} {Math.round(match.match_score * 100)}%
                    </Badge>
                  </div>
                  <p className="mt-1 text-[13px] text-foreground/95">{match.title}</p>
                  <p className="mt-1 text-[12px] leading-6 text-muted-foreground">{match.match_reason}</p>
                  {match.status ? (
                    <Badge variant="outline" className={`mt-2 text-[10px] ${statusBadgeClass(match.status)}`}>
                      {match.status}
                    </Badge>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        )
      }

      if (payload.type === "assignment_recommendation") {
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            {payload.ticket_id ? <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{payload.ticket_id}</p> : null}
            <div className="flex flex-wrap gap-2">
              {payload.current_assignee ? (
                <Badge variant="outline" className="text-[10px]">
                  {locale === "fr" ? `Actuel: ${payload.current_assignee}` : `Current: ${payload.current_assignee}`}
                </Badge>
              ) : null}
              {payload.recommended_assignee ? (
                <Badge variant="outline" className="text-[10px]">
                  {locale === "fr" ? `Recommande: ${payload.recommended_assignee}` : `Recommended: ${payload.recommended_assignee}`}
                </Badge>
              ) : null}
            </div>
            <StructuredSection title={locale === "fr" ? "Raisonnement" : "Reasoning"} items={payload.reasoning} />
            {payload.confidence?.level && (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={`text-[10px] ${confidenceBadgeClass(payload.confidence.level)}`}>
                  {locale === "fr" ? "Confiance" : "Confidence"}: {payload.confidence.level}
                </Badge>
                {payload.confidence.reason && (
                  <p className="text-[12px] text-muted-foreground">{payload.confidence.reason}</p>
                )}
              </div>
            )}
          </div>
        )
      }

      if (payload.type === "insufficient_evidence") {
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="rounded-xl border border-amber-200 bg-amber-500/10 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">
                {locale === "fr" ? "Preuves insuffisantes" : "Insufficient evidence"}
              </p>
              <p className="mt-1 text-[13px] leading-6 text-foreground/95">{payload.summary}</p>
            </div>
            <StructuredSection title={locale === "fr" ? "Faits connus" : "Known facts"} items={payload.known_facts} />
            <StructuredSection title={locale === "fr" ? "Signaux manquants" : "Missing signals"} items={payload.missing_signals} />
            <StructuredSection title={locale === "fr" ? "Controles recommandes" : "Recommended next checks"} items={payload.recommended_next_checks} />
            {payload.confidence?.level && (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={`text-[10px] ${confidenceBadgeClass(payload.confidence.level)}`}>
                  {locale === "fr" ? "Confiance" : "Confidence"}: {payload.confidence.level}
                </Badge>
                {payload.confidence.reason && (
                  <p className="text-[12px] text-muted-foreground">{payload.confidence.reason}</p>
                )}
              </div>
            )}
          </div>
        )
      }
    }

    if (payload) {
      if (payload.type === "problem_detail") {
        const pd = payload as ProblemDetailPayload
        const lastSeen = pd.last_seen_at ? structuredDateLabel(pd.last_seen_at, locale) : null
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-mono text-gray-600">{pd.problem_id}</span>
              <p className="text-sm font-semibold text-foreground">{pd.title}</p>
              <span className={getBadgeStyle("problem_status", pd.status)}>{pd.status}</span>
            </div>
            <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
              <span>{locale === "fr" ? `Occurrences: ${pd.occurrences_count}` : `Occurrences: ${pd.occurrences_count}`}</span>
              <span>{locale === "fr" ? `Actifs: ${pd.active_count}` : `Active: ${pd.active_count}`}</span>
              {lastSeen ? <span>{locale === "fr" ? `Dernier vu: ${lastSeen}` : `Last seen: ${lastSeen}`}</span> : null}
            </div>
            {pd.root_cause ? (
              <div className="border-l-[3px] border-teal-500 pl-3 py-2 bg-teal-50 dark:bg-teal-900/20 rounded-r">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-400">{locale === "fr" ? "Cause racine" : "Root cause"}</p>
                <p className="mt-0.5 text-[12px] text-teal-900 dark:text-teal-200">{pd.root_cause}</p>
              </div>
            ) : pd.ai_probable_cause ? (
              <div className="border-l-[3px] border-dashed border-gray-400 dark:border-gray-600 pl-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">{locale === "fr" ? "Cause probable IA" : "AI probable cause"}</p>
                <p className="mt-0.5 text-[12px] text-gray-700 dark:text-gray-300">{pd.ai_probable_cause}</p>
              </div>
            ) : null}
            {pd.workaround ? (
              <div className="border-l-[3px] border-amber-500 pl-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded-r">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">{locale === "fr" ? "Contournement" : "Workaround"}</p>
                <p className="mt-0.5 text-[12px] text-amber-900 dark:text-amber-200">{pd.workaround}</p>
              </div>
            ) : null}
            {pd.permanent_fix ? (
              <div className="border-l-[3px] border-green-500 pl-3 py-2 bg-green-50 dark:bg-green-900/20 rounded-r">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-green-700 dark:text-green-400">{locale === "fr" ? "Correction permanente" : "Permanent fix"}</p>
                <p className="mt-0.5 text-[12px] text-green-900 dark:text-green-200">{pd.permanent_fix}</p>
              </div>
            ) : null}
            <p className="text-[11px] text-muted-foreground">
              {locale === "fr" ? `${pd.linked_ticket_count} ticket(s) lié(s)` : `${pd.linked_ticket_count} linked ticket(s)`}
            </p>
            {pd.action_links && pd.action_links.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {pd.action_links.map((link, i) => (
                  <Button
                    key={`pd-link-${i}`}
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 rounded-full text-[10px]"
                    onClick={(event) => {
                      event.stopPropagation()
                      if (link.route) {
                        router.push(link.route)
                        return
                      }
                      if (link.intent === "problem_linked_tickets") {
                        sendMessage(`show linked tickets for ${pd.problem_id}`)
                      }
                    }}
                  >
                    {link.label}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        )
      }

      if (payload.type === "problem_list") {
        const pl = payload as ProblemListPayload
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Problèmes" : "Problems"}
              </p>
              <Badge variant="outline" className="text-[10px]">{pl.total_count}</Badge>
              {pl.status_filter ? <Badge variant="outline" className="text-[10px]">{pl.status_filter}</Badge> : null}
            </div>
            <div className="overflow-x-auto rounded-lg border border-border/70">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-border/70 bg-muted/30">
                    <th className="px-3 py-2 text-left font-semibold text-muted-foreground">ID</th>
                    <th className="px-3 py-2 text-left font-semibold text-muted-foreground">{locale === "fr" ? "Titre" : "Title"}</th>
                    <th className="px-3 py-2 text-left font-semibold text-muted-foreground">{locale === "fr" ? "Statut" : "Status"}</th>
                    <th className="px-3 py-2 text-right font-semibold text-muted-foreground">{locale === "fr" ? "Occurrences" : "Occurrences"}</th>
                  </tr>
                </thead>
                <tbody>
                  {pl.problems.slice(0, 5).map((problem) => (
                    <tr
                      key={`pl-row-${problem.id}`}
                      className="cursor-pointer border-b border-border/40 hover:bg-muted/20 transition-colors"
                      onClick={() => sendMessage(`tell me about ${problem.id}`)}
                    >
                      <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">{problem.id}</td>
                      <td className="px-3 py-2 text-foreground line-clamp-1 max-w-[200px]">{problem.title}</td>
                      <td className="px-3 py-2">
                        <span className={getBadgeStyle("problem_status", problem.status)}>{problem.status}</span>
                      </td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{problem.occurrences_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pl.problems.length > 5 ? (
              <button
                type="button"
                className="text-[11px] text-muted-foreground hover:text-foreground underline-offset-2 hover:underline transition-colors"
                onClick={() => sendMessage(locale === "fr" ? `voir les problemes page 2` : `show problems page 2`)}
              >
                {locale === "fr" ? `+${pl.problems.length - 5} autres problèmes` : `+${pl.problems.length - 5} more problems`}
              </button>
            ) : null}
          </div>
        )
      }

      if (payload.type === "problem_linked_tickets") {
        const linked = payload as ProblemLinkedTicketsPayload
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Tickets lies au probleme" : "Problem linked tickets"}
              </p>
              <Badge variant="outline" className="text-[10px]">{linked.problem_id}</Badge>
              <Badge variant="outline" className="text-[10px]">{linked.total_count}</Badge>
            </div>
            <div className="space-y-2">
              {linked.tickets.slice(0, 5).map((ticket) => (
                <TicketResultButton
                  key={`problem-linked-${ticket.id}`}
                  row={{
                    id: ticket.id,
                    title: ticket.title,
                    status: ticket.status,
                    priority: ticket.priority,
                    assignee: ticket.assignee,
                  }}
                  locale={locale}
                  onOpenTicket={() => router.push(ticket.route)}
                />
              ))}
            </div>
            {linked.tickets.length > 5 ? (
              <button
                type="button"
                className="text-[11px] text-muted-foreground hover:text-foreground underline-offset-2 hover:underline transition-colors"
                onClick={() => sendMessage(locale === "fr" ? `montre les tickets lies a ${linked.problem_id}` : `show linked tickets for ${linked.problem_id}`)}
              >
                {locale === "fr" ? `+${linked.tickets.length - 5} tickets de plus` : `+${linked.tickets.length - 5} more tickets`}
              </button>
            ) : null}
          </div>
        )
      }

      if (payload.type === "recommendation_list") {
        const rl = payload as RecommendationListPayload
        function getConfidenceBand(c: number): "high" | "medium" | "low" | "general_knowledge" {
          if (c <= 0.25) return "general_knowledge"
          if (c >= 0.78) return "high"
          if (c >= 0.52) return "medium"
          return "low"
        }
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {locale === "fr" ? "Recommandations" : "Recommendations"}
              </p>
              <Badge variant="outline" className="text-[10px]">{rl.total_count}</Badge>
            </div>
            <div className="space-y-2">
              {rl.recommendations.map((rec) => (
                <div key={`rl-rec-${rec.id}`} className="rounded-lg border border-border bg-background/70 p-3 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-[13px] font-semibold text-foreground flex-1">{rec.title}</p>
                    <Badge variant="outline" className="text-[10px]">{rec.type}</Badge>
                    <Badge variant="outline" className="text-[10px]">{rec.impact}</Badge>
                  </div>
                  <p className="text-[12px] text-muted-foreground line-clamp-2">{rec.description}</p>
                  <ConfidenceBar confidence={rec.confidence} band={getConfidenceBand(rec.confidence)} size="sm" />
                </div>
              ))}
            </div>
            <button
              type="button"
              className="text-[12px] text-blue-600 hover:text-blue-800 transition-colors"
              onClick={() => router.push("/recommendations")}
            >
              {locale === "fr" ? "Voir toutes les recommandations" : "View all recommendations"} →
            </button>
          </div>
        )
      }

      if (payload.type === "ticket_thread") {
        const tt = payload as TicketThreadPayload
        return (
          <div className="space-y-3" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {tt.ticket_id}
              </p>
              <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(tt.status)}`}>{tt.status}</Badge>
              {tt.is_resolved && (
                <Badge variant="outline" className="text-[10px] bg-green-50 text-green-700 border-green-200">
                  {locale === "fr" ? "Résolu" : "Resolved"}
                </Badge>
              )}
            </div>
            <p className="text-[13px] font-semibold text-foreground">{tt.title}</p>
            {tt.is_resolved && tt.resolution && (
              <div className="rounded-lg border border-green-200 bg-green-50/60 p-3 space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-green-700">
                  {locale === "fr" ? "Résolution" : "Resolution"}
                </p>
                <p className="text-[12px] text-foreground whitespace-pre-wrap">{tt.resolution}</p>
              </div>
            )}
            {tt.comments.length > 0 && (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {locale === "fr"
                    ? `${tt.comment_count} commentaire(s)`
                    : `${tt.comment_count} comment(s)`}
                </p>
                {tt.comments.map((c, i) => (
                  <div key={`thread-c-${i}`} className="rounded-lg border border-border bg-background/70 p-3 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-semibold text-foreground">{c.author}</span>
                      {c.created_at && (
                        <span className="text-[10px] text-muted-foreground">{c.created_at}</span>
                      )}
                      {c.source === "jira" && (
                        <Badge variant="outline" className="text-[9px] ml-auto">Jira</Badge>
                      )}
                    </div>
                    <p className="text-[12px] text-muted-foreground whitespace-pre-wrap">{c.content}</p>
                  </div>
                ))}
              </div>
            )}
            {!tt.is_resolved && tt.comments.length === 0 && (
              <p className="text-[12px] text-muted-foreground italic">
                {locale === "fr" ? "Aucun commentaire ni résolution." : "No comments or resolution yet."}
              </p>
            )}
          </div>
        )
      }
    }

    if (message.ticketAction === "show_ticket") {
      if (message.ticketResults?.tickets?.length) {
        return (
          <TicketResultsMessage
            results={message.ticketResults}
            locale={locale}
            onOpenTicket={(ticketId) => router.push(`/tickets/${ticketId}`)}
          />
        )
      }
      const parsed = parseTicketDigest(message.content)
      if (parsed) {
        const isCriticalDigest = isCriticalDigestHeader(parsed.header)
        const visibleRows = parsed.rows.slice(0, 3)
        const overflowRows = parsed.rows.slice(3)
        const hoverRows = overflowRows.length > 0 ? overflowRows : criticalOverflowRows
        const moreCount = extractMoreCount(parsed.extra)

        return (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{parsed.header}</p>
            <div className="space-y-2">
              {visibleRows.map((row) => (
                <div key={`${row.id}-${row.title}`} className="rounded-lg border border-border bg-background/60 p-2.5">
                  <div className="text-xs font-semibold text-foreground">
                    {row.id}
                    <span className="mx-1 text-muted-foreground">-</span>
                    <span className="font-medium">{row.title}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(row.priority)}`}>
                      {row.priority}
                    </Badge>
                    <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(row.status)}`}>
                      {row.status}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] border-border bg-muted/60">
                      {row.assignee}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
            {parsed.extra && isCriticalDigest ? (
              <div className="pt-0.5" onClick={(event) => event.stopPropagation()}>
                <HoverCard
                  openDelay={90}
                  closeDelay={80}
                  onOpenChange={(open) => {
                    if (open && !overflowRows.length) {
                      loadCriticalOverflowRows().catch(() => {})
                    }
                  }}
                >
                  <HoverCardTrigger asChild>
                    <button type="button" className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
                      {parsed.extra}
                    </button>
                  </HoverCardTrigger>
                  <HoverCardContent className="w-96 space-y-2 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Autres tickets critiques" : "Other critical tickets"}
                    </p>
                    {criticalOverflowLoading ? (
                      <p className="text-xs text-muted-foreground">{locale === "fr" ? "Chargement..." : "Loading..."}</p>
                    ) : hoverRows.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        {locale === "fr" ? "Aucun ticket critique supplementaire." : "No additional critical tickets."}
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {hoverRows.slice(0, moreCount > 0 ? moreCount : 8).map((row) => (
                          <div key={`overflow-${row.id}-${row.title}`} className="rounded-lg border border-border/70 bg-background/60 p-2">
                            <p className="line-clamp-1 text-xs font-semibold text-foreground">
                              {row.id} - {row.title}
                            </p>
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(row.priority)}`}>
                                {row.priority}
                              </Badge>
                              <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(row.status)}`}>
                                {row.status}
                              </Badge>
                              <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                                {row.assignee}
                              </Badge>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </HoverCardContent>
                </HoverCard>
              </div>
            ) : parsed.extra ? (
              <p className="text-xs text-muted-foreground">{parsed.extra}</p>
            ) : null}
            {isCriticalDigest && (
              <p className="text-[11px] text-primary/85">
                {locale === "fr" ? "Cliquez sur la reponse pour ouvrir la vue des tickets critiques." : "Click this response to open critical tickets view."}
              </p>
            )}
          </div>
        )
      }
    }
    const blocks = parseAssistantTextBlocks(message.content)
    if (!blocks.length) {
      return <div className={`whitespace-pre-wrap ${isUserMessage ? "text-white" : ""}`}>{message.content}</div>
    }
    return (
      <div className={`space-y-2.5 break-words text-[13px] leading-6 ${isUserMessage ? "text-white" : ""}`}>
        {blocks.map((block, index) => {
          if (block.kind === "list") {
            if (block.ordered) {
              return (
                <ol
                  key={`assistant-block-ordered-${index}`}
                  className={`list-decimal space-y-1.5 pl-5 ${isUserMessage ? "text-white" : "text-foreground/95"}`}
                >
                  {block.items.map((item, itemIndex) => (
                    <li key={`assistant-block-ordered-item-${index}-${itemIndex}`}>{item}</li>
                  ))}
                </ol>
              )
            }
            return (
              <ul
                key={`assistant-block-bullet-${index}`}
                className={`list-disc space-y-1.5 pl-5 ${isUserMessage ? "text-white" : "text-foreground/95"}`}
              >
                {block.items.map((item, itemIndex) => (
                  <li key={`assistant-block-bullet-item-${index}-${itemIndex}`}>{item}</li>
                ))}
              </ul>
            )
          }
          const isHeadingLine = block.text.endsWith(":")
          return (
            <p
              key={`assistant-block-paragraph-${index}`}
              className={
                isHeadingLine
                  ? isUserMessage
                    ? "font-semibold text-white"
                    : "font-semibold text-foreground"
                  : isUserMessage
                    ? "text-white"
                    : "text-foreground/95"
              }
            >
              {block.text}
            </p>
          )
        })}
      </div>
    )
  }

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, loading])

  useEffect(() => {
    setCriticalOverflowRows([])
    setCriticalOverflowLoaded(false)
    setCriticalOverflowLoading(false)
  }, [locale])

  // Abort any in-flight chat request when the component unmounts (navigation away)
  useEffect(() => {
    return () => {
      chatAbortRef.current?.abort()
    }
  }, [])

  async function sendMessage(text: string) {
    const normalized = text.trim()
    if (!normalized || loading) return
    // Abort any previous in-flight request before starting a new one
    chatAbortRef.current?.abort()
    chatAbortRef.current = new AbortController()
    // Dismiss any pending apply-confirmation when the user sends a new message.
    // The stale confirmation would no longer be actionable after context changes.
    setPendingSuggestion(null)
    const userMessage: ChatMessage = {
      id: `m-${Date.now()}`,
      role: "user",
      content: normalized.slice(0, MAX_CHAT_CONTENT_LEN),
      createdAt: new Date().toISOString(),
    }
    const nextMessages: ChatMessage[] = [...messages, userMessage]
    setMessages(nextMessages)
    setInput("")
    setLoading(true)
    try {
      const payloadMessages = nextMessages
        .slice(-MAX_CHAT_MESSAGES)
        .map((m) => ({
          role: m.role,
          content: m.content.slice(0, MAX_CHAT_CONTENT_LEN),
          response_payload_type: m.responsePayload?.type ?? null,
          entity_kind: payloadEntityKind(m.responsePayload ?? null),
          entity_id: payloadEntityId(m.responsePayload ?? null),
          inventory_kind: payloadInventoryKind(m.responsePayload ?? null),
          listed_entity_ids: payloadListedEntityIds(m.responsePayload ?? null),
        }))
      const result = await apiFetch<{
        reply: string
        message?: string
        action?: string
        ticket?: TicketDraft
        ticket_results?: TicketResultsPayload | null
        response_payload?: ChatResponsePayload | null
        rag_grounding?: boolean
        suggestions?: SuggestionBundle
        draft_context?: DraftContext | null
        actions?: string[]
      }>("/ai/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: payloadMessages,
          locale,
        }),
        signal: chatAbortRef.current?.signal,
      })
      const ticketDraft = result.ticket
        ? {
            ...result.ticket,
            ticket_type: result.ticket.ticket_type || "service_request",
            description: result.draft_context?.pre_filled_description || result.ticket.description,
          }
        : undefined
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-bot`,
          role: "assistant",
          content: normalizeAssistantReply(result.message || result.reply, locale),
          createdAt: new Date().toISOString(),
          sourceQuery: normalized,
          ticketDraft,
          ticketAction: result.action ?? null,
          ragGrounding: Boolean(result.rag_grounding),
          suggestions: result.suggestions,
          draftContext: result.draft_context ?? null,
          actions: result.actions || [],
          ticketResults: result.ticket_results ?? null,
          responsePayload: normalizeResponsePayload(result.response_payload),
        },
      ])
    } catch (error) {
      // Ignore abort errors — they happen on intentional navigation or new message send
      if (error instanceof DOMException && error.name === "AbortError") return
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-bot`,
          role: "assistant",
          content: getChatErrorMessage(error),
          createdAt: new Date().toISOString(),
          sourceQuery: normalized,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleSend() {
    sendMessage(input)
  }

  function handleQuickPrompt(prompt: string) {
    sendMessage(prompt)
  }

  // ── Command palette (/ and @ trigger) ────────────────────────────────────
  const ALL_COMMANDS: { label: string; desc: string; msg: string; group: string }[] =
    locale === "fr"
      ? [
          { group: "Tickets", label: "/critiques", desc: "Tickets critiques", msg: "Tickets critiques" },
          { group: "Tickets", label: "/haute-priorite", desc: "Tickets haute priorité", msg: "Tickets haute priorité" },
          { group: "Tickets", label: "/ouverts", desc: "Tickets ouverts", msg: "Tickets ouverts" },
          { group: "Tickets", label: "/en-cours", desc: "Tickets en cours", msg: "Tickets en cours" },
          { group: "Tickets", label: "/recents", desc: "Tickets récents", msg: "Tickets récents" },
          { group: "Tickets", label: "/resolus", desc: "Tickets résolus", msg: "Tickets résolus" },
          { group: "Catégories", label: "/reseau", desc: "Tickets réseau", msg: "Tickets réseau" },
          { group: "Catégories", label: "/email", desc: "Tickets email", msg: "Tickets email" },
          { group: "Catégories", label: "/securite", desc: "Tickets sécurité", msg: "Tickets sécurité" },
          { group: "Catégories", label: "/materiel", desc: "Tickets matériel", msg: "Tickets matériel" },
          { group: "Catégories", label: "/application", desc: "Tickets application", msg: "Tickets application" },
          { group: "Catégories", label: "/infrastructure", desc: "Tickets infrastructure", msg: "Tickets infrastructure" },
          { group: "SLA & Risques", label: "/sla-risque", desc: "Tickets SLA à risque", msg: "Tickets SLA à risque" },
          { group: "SLA & Risques", label: "/sla-depasse", desc: "Tickets SLA dépassée", msg: "Tickets SLA dépassée" },
          { group: "SLA & Risques", label: "/sla-resume", desc: "Résumé SLA", msg: "Résumé SLA" },
          { group: "Problèmes & IA", label: "/problemes", desc: "Tous les problèmes", msg: "Quels sont les problèmes ?" },
          { group: "Problèmes & IA", label: "/problemes-ouverts", desc: "Problèmes ouverts", msg: "Problèmes ouverts" },
          { group: "Problèmes & IA", label: "/erreurs-connues", desc: "Erreurs connues", msg: "Erreurs connues" },
          { group: "Problèmes & IA", label: "/recurrents", desc: "Solutions récurrentes", msg: "Solutions récurrentes" },
          { group: "Problèmes & IA", label: "/recommandations", desc: "Mes recommandations", msg: "Mes recommandations" },
          { group: "Analytiques", label: "/semaine", desc: "Résumé de la semaine", msg: "Résumé de la semaine" },
          { group: "Analytiques", label: "/frequents", desc: "Types de tickets les plus fréquents", msg: "Tickets les plus fréquents" },
          { group: "Analytiques", label: "/combien", desc: "Combien de tickets ouverts ?", msg: "Combien de tickets ouverts ?" },
          { group: "Analytiques", label: "/creer", desc: "Créer un nouveau ticket", msg: "Créer un ticket" },
        ]
      : [
          { group: "Tickets", label: "/critical", desc: "Critical tickets", msg: "Critical tickets" },
          { group: "Tickets", label: "/high-priority", desc: "High priority tickets", msg: "High priority tickets" },
          { group: "Tickets", label: "/open", desc: "Open tickets", msg: "Open tickets" },
          { group: "Tickets", label: "/in-progress", desc: "In progress tickets", msg: "In progress tickets" },
          { group: "Tickets", label: "/recent", desc: "Recent tickets", msg: "Recent tickets" },
          { group: "Tickets", label: "/resolved", desc: "Resolved tickets", msg: "Resolved tickets" },
          { group: "Categories", label: "/network", desc: "Network tickets", msg: "Network tickets" },
          { group: "Categories", label: "/email", desc: "Email tickets", msg: "Email tickets" },
          { group: "Categories", label: "/security", desc: "Security tickets", msg: "Security tickets" },
          { group: "Categories", label: "/hardware", desc: "Hardware tickets", msg: "Hardware tickets" },
          { group: "Categories", label: "/application", desc: "Application tickets", msg: "Application tickets" },
          { group: "Categories", label: "/infrastructure", desc: "Infrastructure tickets", msg: "Infrastructure tickets" },
          { group: "SLA & Risk", label: "/sla-risk", desc: "SLA at risk tickets", msg: "SLA at risk tickets" },
          { group: "SLA & Risk", label: "/sla-breached", desc: "SLA breached tickets", msg: "SLA breached tickets" },
          { group: "SLA & Risk", label: "/sla-summary", desc: "SLA summary", msg: "SLA summary" },
          { group: "Problems & AI", label: "/problems", desc: "All problems", msg: "Show problems" },
          { group: "Problems & AI", label: "/open-problems", desc: "Open problems", msg: "Open problems" },
          { group: "Problems & AI", label: "/known-errors", desc: "Known errors", msg: "Known errors" },
          { group: "Problems & AI", label: "/recurring", desc: "Recurring solutions", msg: "Recurring solutions" },
          { group: "Problems & AI", label: "/recommendations", desc: "My recommendations", msg: "My recommendations" },
          { group: "Analytics", label: "/weekly", desc: "Weekly summary", msg: "Weekly summary" },
          { group: "Analytics", label: "/frequent", desc: "Most common ticket types", msg: "Most common ticket types" },
          { group: "Analytics", label: "/count", desc: "How many open tickets?", msg: "How many open tickets?" },
          { group: "Analytics", label: "/create", desc: "Create a new ticket", msg: "Create a ticket" },
        ]

  const filteredCommands = cmdOpen
    ? ALL_COMMANDS.filter((c) => {
        const q = cmdQuery.toLowerCase()
        return !q || c.label.includes(q) || c.desc.toLowerCase().includes(q) || c.group.toLowerCase().includes(q)
      })
    : []

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    setInput(val)
    const trigger = val === "/" || val === "@" || val.startsWith("/") || val.startsWith("@")
    if (trigger) {
      setCmdOpen(true)
      setCmdQuery(val.slice(1).toLowerCase())
      setCmdIndex(0)
    } else {
      setCmdOpen(false)
      setCmdQuery("")
    }
  }

  function selectCommand(cmd: { msg: string }) {
    setCmdOpen(false)
    setCmdQuery("")
    setInput("")
    sendMessage(cmd.msg)
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (cmdOpen && filteredCommands.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setCmdIndex((i) => Math.min(i + 1, filteredCommands.length - 1))
        return
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setCmdIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        selectCommand(filteredCommands[cmdIndex])
        return
      }
      if (e.key === "Escape") {
        e.preventDefault()
        setCmdOpen(false)
        return
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <Card className="surface-card flex h-[calc(100vh-13rem)] flex-col overflow-hidden rounded-2xl border border-border/60 shadow-sm">
      {/* Top accent bar */}
      <div className="h-1 bg-gradient-to-r from-primary via-emerald-500 to-amber-400 shrink-0" />

      {/* Header */}
      <CardHeader className="shrink-0 border-b border-border/60 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2.5 text-sm font-semibold text-foreground">
            <div className="relative">
              <AssistantMascot locale={locale} compact speaking={loading} />
              <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-background" />
            </div>
            <div>
              <p className="leading-tight">{t("chat.title")}</p>
              <p className="text-[10px] font-normal text-muted-foreground leading-tight">
                {messages.length > 0
                  ? (locale === "fr" ? `${messages.filter(m => m.role === "user").length} message${messages.filter(m => m.role === "user").length > 1 ? "s" : ""}` : `${messages.filter(m => m.role === "user").length} message${messages.filter(m => m.role === "user").length > 1 ? "s" : ""}`)
                  : (locale === "fr" ? "Prêt" : "Ready")}
              </p>
            </div>
          </CardTitle>

          <div className="flex items-center gap-1.5">
            {messages.length > 0 && (
              <button
                type="button"
                onClick={() => setMessages([])}
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/60 text-muted-foreground hover:border-border hover:text-foreground transition-colors"
                title={locale === "fr" ? "Nouvelle conversation" : "New conversation"}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            )}
            {messages.length > 0 && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setExportMenuOpen((o) => !o)}
                  className="flex h-7 items-center gap-1.5 rounded-lg border border-border/60 px-2 text-[11px] text-muted-foreground hover:border-border hover:text-foreground transition-colors"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-3 h-3">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  {locale === "fr" ? "Export" : "Export"}
                </button>
                {exportMenuOpen && (
                  <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-border bg-background shadow-lg z-50 overflow-hidden">
                    {lastTicketId && (
                      <button
                        type="button"
                        onClick={() => { void copyToComments(messages, lastTicketId); setExportMenuOpen(false); }}
                        className="w-full text-left text-[12px] px-3 py-2 hover:bg-accent transition-colors"
                      >
                        {locale === "fr" ? "Copier vers les commentaires" : "Copy to ticket comments"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => { downloadChatTxt(messages, lastTicketId); setExportMenuOpen(false); }}
                      className="w-full text-left text-[12px] px-3 py-2 hover:bg-accent transition-colors"
                    >
                      {locale === "fr" ? "Télécharger (.txt)" : "Download (.txt)"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        {exportSuccess && (
          <p className="mt-1 text-[11px] text-emerald-600 font-medium">
            {locale === "fr" ? "Conversation ajoutée aux commentaires ✓" : "Conversation added to comments ✓"}
          </p>
        )}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        <ScrollArea className="flex-1 px-4 py-4 sm:px-5" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="flex flex-col gap-6 py-5 px-1">
              {/* Welcome */}
              <div className="flex flex-col items-center gap-2 text-center px-2">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-emerald-500/10 ring-1 ring-primary/20 shadow-sm">
                  <Sparkles className="h-5 w-5 text-primary" />
                </div>
                <p className="text-[15px] font-semibold text-foreground">
                  {locale === "fr" ? "Bonjour, que puis-je faire pour vous ?" : "Hi, what can I help you with?"}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {locale === "fr"
                    ? "Choisissez un raccourci ou tapez / dans la zone de saisie"
                    : "Pick a shortcut below or type / in the input"}
                </p>
              </div>

              {/* Quick shortcuts */}
              <div className="flex flex-wrap justify-center gap-2 px-1">
                {(locale === "fr" ? [
                  { label: "Tickets critiques",  msg: "Tickets critiques" },
                  { label: "SLA à risque",       msg: "Tickets SLA à risque" },
                  { label: "Problèmes",          msg: "Quels sont les problèmes ?" },
                  { label: "Recommandations",    msg: "Mes recommandations" },
                  { label: "Résumé semaine",     msg: "Résumé de la semaine" },
                ] : [
                  { label: "Critical tickets",  msg: "Critical tickets" },
                  { label: "SLA at risk",       msg: "SLA at risk tickets" },
                  { label: "Problems",          msg: "Show problems" },
                  { label: "Recommendations",   msg: "My recommendations" },
                  { label: "Weekly summary",    msg: "Weekly summary" },
                ]).map(({ label, msg }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => sendMessage(msg)}
                    className="rounded-full border border-border/60 bg-card px-4 py-2 text-[12px] font-medium text-foreground/75 shadow-sm transition-all hover:-translate-y-px hover:border-primary/30 hover:bg-primary/5 hover:text-foreground hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.length === 0 && (
                <div className="rounded-3xl border border-border/70 bg-background/70 px-5 py-5 shadow-sm">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                    <AssistantMascot locale={locale} speaking className="shrink-0" />
                    <div className="space-y-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary/80">
                        {locale === "fr" ? "Assistant guide" : "Assistant guide"}
                      </p>
                      <p className="text-sm text-foreground">
                        {locale === "fr"
                          ? "Demandez le statut, les details, les commentaires recents ou les tickets critiques. Les reponses structurees s'affichent directement dans le chat."
                          : "Ask for status, details, recent comments, or critical tickets. Structured answers render directly inside the chat."}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {[
                          locale === "fr" ? "Montre les commentaires de TW-1001" : "Show comments for TW-1001",
                          locale === "fr" ? "Quels tickets critiques sont ouverts ?" : "Which critical tickets are open?",
                          locale === "fr" ? "Details de TW-1001" : "Details for TW-1001",
                        ].map((prompt) => (
                          <button
                            key={prompt}
                            type="button"
                            onClick={() => setInput(prompt)}
                            className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
                          >
                            {prompt}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {messages.map((message) => {
                const isUser = message.role === "user"
                const parsedDigest = !isUser && message.ticketAction === "show_ticket"
                  ? parseTicketDigest(message.content)
                  : null
                const criticalResponse = Boolean(parsedDigest && isCriticalDigestHeader(parsedDigest.header) && !message.ticketResults)
                const timestamp = formatMessageTime(message.createdAt, locale)

                return (
                  <div key={message.id} className="space-y-2">
                    <div className={`flex gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}>
                      {!isUser && (
                        <AssistantMascot locale={locale} compact className="mt-0.5 shrink-0" />
                      )}

                      <div className={`flex max-w-[88%] flex-col sm:max-w-[82%] ${isUser ? "items-end" : "items-start"}`}>
                        <div
                          className={`break-words text-sm leading-relaxed shadow-sm ${
                            isUser
                              ? "rounded-2xl rounded-tr-sm bg-gradient-to-br from-primary to-primary/80 px-3.5 py-2.5 text-primary-foreground"
                              : `rounded-2xl rounded-tl-sm border border-border/60 bg-card px-3.5 py-2.5 text-foreground ${criticalResponse ? "cursor-pointer hover:border-primary/40" : ""}`
                          }`}
                          onClick={() => {
                            if (criticalResponse) {
                              router.push("/tickets?view=critical")
                            }
                          }}
                          role={criticalResponse ? "button" : undefined}
                          tabIndex={criticalResponse ? 0 : undefined}
                          onKeyDown={(event) => {
                            if (!criticalResponse) return
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault()
                              router.push("/tickets?view=critical")
                            }
                          }}
                        >
                          {renderAssistantMessage(message)}
                        </div>
                        {timestamp && (
                          <p className="mt-1 px-1 text-[10px] text-muted-foreground">{timestamp}</p>
                        )}
                        {!isUser && hasSuggestions(message.suggestions) && (
                          <div className="mt-2 w-full space-y-2 rounded-xl border border-border/70 bg-card/80 p-2.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant="outline" className="text-[10px]">
                                {message.ragGrounding ? "RAG grounded" : "Related suggestions"}
                              </Badge>
                              {message.suggestions?.confidence !== undefined && (
                                <Badge variant="outline" className="text-[10px]">
                                  Confidence {Math.round((message.suggestions.confidence || 0) * 100)}%
                                </Badge>
                              )}
                              {message.suggestions?.tickets?.length ? (
                                <div className="flex flex-wrap gap-1.5">
                                  {message.suggestions.tickets.slice(0, 3).map((row) => (
                                    <HoverCard key={`chip-${message.id}-${row.id}`} openDelay={80} closeDelay={80}>
                                      <HoverCardTrigger asChild>
                                        <button
                                          type="button"
                                          className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-foreground hover:border-primary/50"
                                          onClick={() => router.push(`/tickets/${row.id}`)}
                                        >
                                          #{row.id}
                                        </button>
                                      </HoverCardTrigger>
                                      <HoverCardContent className="w-80 space-y-1 p-3">
                                        <p className="text-xs font-semibold">{row.title}</p>
                                        <p className="text-xs text-muted-foreground">{row.resolution_snippet || "No resolution snippet available."}</p>
                                      </HoverCardContent>
                                    </HoverCard>
                                  ))}
                                </div>
                              ) : null}
                            </div>

                            {message.suggestions?.resolution_advice ? (
                              message.suggestions.resolution_advice.display_mode === "llm_general_knowledge" &&
                              message.suggestions.resolution_advice.llm_general_advisory ? (
                                // llm_general_knowledge bubble — blue/info scheme, no Apply button
                                <div className="rounded-lg border border-sky-200 bg-sky-50/80 p-3">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <Badge variant="outline" className="border-sky-300 bg-sky-100 text-[10px] text-sky-700">
                                      {resolutionModeLabel(message.suggestions.resolution_advice.display_mode, locale)}
                                    </Badge>
                                  </div>
                                  {/* Probable causes */}
                                  {message.suggestions.resolution_advice.llm_general_advisory.probable_causes?.length ? (
                                    <div className="mt-2">
                                      <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-700">
                                        {locale === "fr" ? "Causes probables" : "Probable causes"}
                                      </p>
                                      <ul className="mt-1 space-y-1">
                                        {message.suggestions.resolution_advice.llm_general_advisory.probable_causes.slice(0, 3).map((cause, idx) => (
                                          <li key={`llm-cause-${message.id}-${idx}`} className="flex gap-2 text-[11px] leading-relaxed text-sky-900">
                                            <span className="select-none text-sky-400">•</span>
                                            <span>{cause}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  ) : null}
                                  {/* Suggested diagnostic steps */}
                                  {message.suggestions.resolution_advice.llm_general_advisory.suggested_checks?.length ? (
                                    <div className="mt-2">
                                      <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-700">
                                        {locale === "fr" ? "Etapes de diagnostic" : "Diagnostic steps"}
                                      </p>
                                      <ol className="mt-1 space-y-1">
                                        {message.suggestions.resolution_advice.llm_general_advisory.suggested_checks.slice(0, 4).map((check, idx) => (
                                          <li key={`llm-check-${message.id}-${idx}`} className="flex gap-2 text-[11px] leading-relaxed text-sky-900">
                                            <span className="font-semibold text-sky-500">{idx + 1}.</span>
                                            <span>{check}</span>
                                          </li>
                                        ))}
                                      </ol>
                                    </div>
                                  ) : null}
                                  {/* Escalation hint */}
                                  {message.suggestions.resolution_advice.llm_general_advisory.escalation_hint ? (
                                    <div className="mt-2 rounded border border-amber-200 bg-amber-50/80 p-2">
                                      <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                                        {locale === "fr" ? "Conseil d'escalade" : "Escalation guidance"}
                                      </p>
                                      <p className="mt-0.5 text-[11px] leading-relaxed text-amber-900">
                                        {message.suggestions.resolution_advice.llm_general_advisory.escalation_hint}
                                      </p>
                                    </div>
                                  ) : null}
                                  {/* Disclaimer */}
                                  <p className="mt-2 text-[10px] italic text-muted-foreground">
                                    {locale === "fr"
                                      ? "Avis basé sur les connaissances générales en IT — pas sur votre historique de tickets."
                                      : "Advisory based on general IT knowledge — not your ticket history."}
                                  </p>
                                </div>
                              ) : (
                                // Standard resolution advice bubble (evidence_action, tentative_diagnostic, no_strong_match)
                                <div className="rounded-lg border border-border bg-background/70 p-3">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <Badge variant="outline" className="text-[10px]">
                                      {resolutionModeLabel(message.suggestions.resolution_advice.display_mode, locale)}
                                    </Badge>
                                    <Badge variant="outline" className="text-[10px]">
                                      {Math.round((message.suggestions.resolution_advice.confidence || 0) * 100)}%
                                    </Badge>
                                    <Badge variant="outline" className="text-[10px]">
                                      {message.suggestions.resolution_advice.recommendation_mode}
                                    </Badge>
                                  </div>
                                  <p className="mt-2 text-xs font-semibold text-foreground">
                                    <Sparkles className="mr-1 inline h-3.5 w-3.5 text-emerald-500" />
                                    {message.suggestions.resolution_advice.recommended_action ||
                                      message.suggestions.resolution_advice.fallback_action ||
                                      (locale === "fr" ? "Aucune action prioritaire" : "No primary action")}
                                  </p>
                                  {message.suggestions.resolution_advice.reasoning ? (
                                    <p className="mt-1 text-[11px] text-muted-foreground">
                                      {message.suggestions.resolution_advice.reasoning}
                                    </p>
                                  ) : null}
                                  {message.suggestions.resolution_advice.validation_steps?.length ? (
                                    <div className="mt-2 space-y-1">
                                      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                        {locale === "fr" ? "Validation" : "Validation"}
                                      </p>
                                      {message.suggestions.resolution_advice.validation_steps.slice(0, 2).map((step, idx) => (
                                        <p key={`validation-${message.id}-${idx}`} className="text-[11px] text-foreground/90">
                                          <CheckCircle2 className="mr-1 inline h-3.5 w-3.5 text-emerald-600" />
                                          {step}
                                        </p>
                                      ))}
                                    </div>
                                  ) : null}
                                  {message.suggestions.resolution_advice.next_best_actions?.length ? (
                                    <div className="mt-2 space-y-1">
                                      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                        {locale === "fr" ? "Etapes suivantes" : "Next steps"}
                                      </p>
                                      {message.suggestions.resolution_advice.next_best_actions.slice(0, 2).map((step, idx) => (
                                        <p key={`next-step-${message.id}-${idx}`} className="text-[11px] text-foreground/90">
                                          <AlertCircle className="mr-1 inline h-3.5 w-3.5 text-amber-600" />
                                          {step}
                                        </p>
                                      ))}
                                    </div>
                                  ) : null}
                                  {message.suggestions.resolution_advice.evidence_sources?.length ? (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      {message.suggestions.resolution_advice.evidence_sources.slice(0, 3).map((evidence, idx) => (
                                        <Badge key={`evidence-${message.id}-${idx}`} variant="outline" className="text-[10px]">
                                          {evidence.reference}
                                        </Badge>
                                      ))}
                                    </div>
                                  ) : null}
                                  {message.suggestions.resolution_advice.missing_information?.length ? (
                                    <p className="mt-2 text-[11px] text-muted-foreground">
                                      {locale === "fr" ? "Informations manquantes :" : "Missing information:"}{" "}
                                      {message.suggestions.resolution_advice.missing_information.slice(0, 2).join(" ; ")}
                                    </p>
                                  ) : null}
                                </div>
                              )
                            ) : null}
                            {message.suggestions?.tickets?.slice(0, 2).map((row) => (
                              <div key={`ticket-sug-${message.id}-${row.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-semibold text-foreground">
                                      <Lightbulb className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
                                      {row.id} - {row.title}
                                    </p>
                                    <p className="mt-1 text-[11px] text-muted-foreground">{row.resolution_snippet || "No resolution summary."}</p>
                                  </div>
                                  <div className="flex shrink-0 gap-1.5">
                                    <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => router.push(`/tickets/${row.id}`)}>
                                      Open
                                    </Button>
                                    {row.resolution_snippet ? (
                                      <Button
                                        type="button"
                                        size="sm"
                                        className="h-7 px-2 text-[10px]"
                                        onClick={() => handleApplySuggestion(message.id, row.resolution_snippet || "", row.id)}
                                      >
                                        Apply
                                      </Button>
                                    ) : null}
                                  </div>
                                </div>
                              </div>
                            ))}

                            {(message.suggestions?.solution_recommendations || []).slice(0, 2).map((rec, idx) => {
                              const userQuery = resolveSourceQuery(message.id)
                              const upKey = `${message.id}-${rec.source}-${rec.source_id || rec.text.slice(0, 24)}-helpful`
                              const downKey = `${message.id}-${rec.source}-${rec.source_id || rec.text.slice(0, 24)}-not_helpful`
                              return (
                                <div key={`solution-rec-${message.id}-${idx}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                  <p className="text-xs font-semibold text-foreground">
                                    <Lightbulb className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
                                    {locale === "fr" ? "Recommendation de solution" : "Solution recommendation"}
                                  </p>
                                  <p className="mt-1 text-[11px] text-muted-foreground">{rec.text}</p>
                                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                    <Badge variant="outline" className="text-[10px]">{rec.source}</Badge>
                                    <Badge variant="outline" className="text-[10px]">Q {Math.round((rec.quality_score || 0) * 100)}%</Badge>
                                    <Badge variant="outline" className="text-[10px]">C {Math.round((rec.confidence || 0) * 100)}%</Badge>
                                    <Badge variant="outline" className="text-[10px]">
                                      {rec.helpful_votes || 0} / {rec.not_helpful_votes || 0}
                                    </Badge>
                                  </div>
                                  <div className="mt-2 flex gap-1.5">
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      className="h-7 px-2 text-[10px]"
                                      disabled={feedbackSubmitting[upKey]}
                                      onClick={() => submitSolutionFeedback(message.id, rec, "helpful", userQuery)}
                                    >
                                      <ThumbsUp className="mr-1 h-3.5 w-3.5" />
                                      Helpful
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      className="h-7 px-2 text-[10px]"
                                      disabled={feedbackSubmitting[downKey]}
                                      onClick={() => submitSolutionFeedback(message.id, rec, "not_helpful", userQuery)}
                                    >
                                      <ThumbsDown className="mr-1 h-3.5 w-3.5" />
                                      Not helpful
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      className="h-7 px-2 text-[10px]"
                                      onClick={() => handleApplySuggestion(message.id, rec.text, rec.source_id || rec.source)}
                                    >
                                      Apply
                                    </Button>
                                  </div>
                                </div>
                              )
                            })}

                            {message.suggestions?.problems?.slice(0, 1).map((problem) => (
                              <div key={`problem-sug-${message.id}-${problem.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <p className="text-xs font-semibold text-foreground">
                                  <AlertCircle className="mr-1 inline h-3.5 w-3.5 text-orange-500" />
                                  {problem.id} - {problem.title}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">{problem.match_reason}</p>
                                <div className="mt-2">
                                  <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => router.push("/problems")}>
                                    View Problem
                                  </Button>
                                </div>
                              </div>
                            ))}

                            {message.suggestions?.kb_articles?.slice(0, 1).map((kb) => (
                              <div key={`kb-sug-${message.id}-${kb.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <p className="text-xs font-semibold text-foreground">
                                  <BookOpen className="mr-1 inline h-3.5 w-3.5 text-blue-500" />
                                  {kb.title}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">{kb.excerpt}</p>
                                <div className="mt-2 flex gap-1.5">
                                  <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => setInput(`Use this KB guidance: ${kb.excerpt}`)}>
                                    Use This Solution
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {isUser && (
                        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 ring-1 ring-primary/10">
                          <User className="h-3.5 w-3.5 text-primary" />
                        </div>
                      )}
                    </div>

                  </div>
                )
              })}

              {loading && (
                <div className="flex items-start gap-2.5">
                  <AssistantMascot locale={locale} compact speaking className="mt-0.5 shrink-0" />
                  <div className="rounded-2xl rounded-tl-sm border border-border/60 bg-card px-4 py-3 shadow-sm flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-bounce" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-bounce-delay-1" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-bounce-delay-2" />
                  </div>
                </div>
              )}
              <div ref={endOfMessagesRef} />
            </div>
          )}
        </ScrollArea>

        {/* Inline apply-confirmation row.
            Shown when the user clicks "Apply" on a suggestion card.
            Requires explicit Confirm before the draft is mutated.
            Dismissed automatically when the user sends a new message. */}
        {pendingSuggestion ? (
          <div className="shrink-0 border-t border-amber-200 bg-amber-50/80 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-[11px] text-amber-900">
                <span className="font-semibold">
                  {locale === "fr" ? "Appliquer au brouillon ?" : "Apply to draft?"}
                </span>
                {" — "}
                {pendingSuggestion.solution.length > 80
                  ? `${pendingSuggestion.solution.slice(0, 80)}…`
                  : pendingSuggestion.solution}
              </p>
              <div className="flex shrink-0 gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  className="h-7 px-2 text-[10px]"
                  onClick={() =>
                    _doApplySuggestion(
                      pendingSuggestion.messageId,
                      pendingSuggestion.solution,
                      pendingSuggestion.sourceId,
                    )
                  }
                >
                  {locale === "fr" ? "Confirmer" : "Confirm"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[10px]"
                  onClick={() => setPendingSuggestion(null)}
                >
                  {locale === "fr" ? "Annuler" : "Cancel"}
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {/* Input area + command palette */}
        <div className="shrink-0 border-t border-border/60 bg-card/80 px-3 py-2.5">
          {/* Command palette dropdown — renders above the input */}
          {cmdOpen && filteredCommands.length > 0 && (
            <div className="mb-2 overflow-hidden rounded-xl border border-border/70 bg-background shadow-lg">
              {/* Header hint */}
              <div className="flex items-center justify-between border-b border-border/50 px-3 py-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                  {locale === "fr" ? "Raccourcis" : "Shortcuts"}
                </p>
                <p className="text-[10px] text-muted-foreground/60">
                  {locale === "fr" ? "↑↓ naviguer · ↵ sélectionner · Esc fermer" : "↑↓ navigate · ↵ select · Esc close"}
                </p>
              </div>
              <div className="max-h-56 overflow-y-auto scrollbar-hide">
                {(() => {
                  let lastGroup = ""
                  return filteredCommands.map((cmd, idx) => {
                    const showGroup = cmd.group !== lastGroup
                    lastGroup = cmd.group
                    return (
                      <div key={cmd.label}>
                        {showGroup && (
                          <p className="px-3 pt-2 pb-0.5 text-[9px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                            {cmd.group}
                          </p>
                        )}
                        <button
                          type="button"
                          onMouseDown={(e) => { e.preventDefault(); selectCommand(cmd) }}
                          onMouseEnter={() => setCmdIndex(idx)}
                          className={`flex w-full items-center gap-3 px-3 py-2 text-left transition-colors ${
                            idx === cmdIndex
                              ? "bg-primary/10 text-foreground"
                              : "text-foreground/80 hover:bg-muted/60"
                          }`}
                        >
                          <span className="w-32 shrink-0 font-mono text-[11px] font-semibold text-primary">
                            {cmd.label}
                          </span>
                          <span className="truncate text-[12px]">{cmd.desc}</span>
                        </button>
                      </div>
                    )
                  })
                })()}
              </div>
            </div>
          )}

          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Input
                ref={inputRef}
                placeholder={loading
                  ? (locale === "fr" ? "Traitement en cours…" : "Processing…")
                  : (locale === "fr" ? "Posez une question, tapez / ou @ pour les raccourcis…" : "Ask a question, or type / or @ for shortcuts…")}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleInputKeyDown}
                onBlur={() => setTimeout(() => setCmdOpen(false), 150)}
                onFocus={() => {
                  if (input === "/" || input === "@") {
                    setCmdOpen(true)
                    setCmdIndex(0)
                  }
                }}
                disabled={loading}
                className="h-9 rounded-xl bg-background/90 pr-8 text-[13px] placeholder:text-muted-foreground/60"
              />
              {input.trim() && !loading && (
                <button
                  type="button"
                  onClick={() => { setInput(""); setCmdOpen(false) }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                  tabIndex={-1}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
                    <path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
                  </svg>
                </button>
              )}
            </div>
            <Button
              type="button"
              onClick={handleSend}
              disabled={(!input.trim() && !cmdOpen) || loading}
              size="sm"
              className="h-9 w-9 shrink-0 rounded-xl bg-primary p-0 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {loading
                ? <span className="h-3.5 w-3.5 rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground animate-spin" />
                : <Send className="h-3.5 w-3.5" />}
              <span className="sr-only">{t("chat.send")}</span>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
