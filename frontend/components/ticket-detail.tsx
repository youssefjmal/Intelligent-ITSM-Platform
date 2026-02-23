"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
} from "lucide-react"
import {
  type Ticket,
  type TicketCategory,
  type TicketPriority,
  type TicketStatus,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { ApiError, apiFetch } from "@/lib/api"
import {
  fetchTicket,
  fetchTicketAiSlaRiskLatest,
  fetchTicketAIRecommendations,
  fetchSimilarTickets,
  type SimilarTicket,
  type TicketAiSlaRiskLatest,
  type TicketAIRecommendationsPayload,
} from "@/lib/tickets-api"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"

interface TicketDetailProps {
  ticket: Ticket
}

type Assignee = {
  id: string
  name: string
  role: string
}

export function TicketDetail({ ticket }: TicketDetailProps) {
  const { hasPermission } = useAuth()
  const { t, locale } = useI18n()
  const [ticketData, setTicketData] = useState<Ticket>(ticket)
  const [status, setStatus] = useState<TicketStatus>(ticket.status)
  const [selectedAssignee, setSelectedAssignee] = useState(ticket.assignee)
  const [selectedPriority, setSelectedPriority] = useState<TicketPriority>(ticket.priority)
  const [selectedCategory, setSelectedCategory] = useState<TicketCategory>(ticket.category)
  const [assignees, setAssignees] = useState<Assignee[]>([])
  const [updating, setUpdating] = useState(false)
  const [triageUpdating, setTriageUpdating] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [triageError, setTriageError] = useState<string | null>(null)
  const [statusComment, setStatusComment] = useState("")
  const [aiSuggestions, setAiSuggestions] = useState<TicketAIRecommendationsPayload | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState(false)
  const [aiSlaRisk, setAiSlaRisk] = useState<TicketAiSlaRiskLatest>(null)
  const [aiSlaRiskLoading, setAiSlaRiskLoading] = useState(false)
  const [similarTickets, setSimilarTickets] = useState<SimilarTicket[]>([])
  const [similarTicketsLoading, setSimilarTicketsLoading] = useState(false)
  const [similarTicketsError, setSimilarTicketsError] = useState(false)
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"

  const assigneeOptions = (() => {
    if (!selectedAssignee) return assignees
    if (assignees.some((member) => member.name === selectedAssignee)) return assignees
    return [{ id: "current-assignee", name: selectedAssignee, role: "current" }, ...assignees]
  })()

  const triageLabels = {
    assignee: locale === "fr" ? "Reaffecter a" : "Reassign to",
    priority: locale === "fr" ? "Priorite" : "Priority",
    category: locale === "fr" ? "Categorie" : "Category",
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

  const canResolve = hasPermission("resolve_ticket")
  const canEditTriage = hasPermission("edit_ticket_triage")

  useEffect(() => {
    setTicketData(ticket)
    setStatus(ticket.status)
    setSelectedAssignee(ticket.assignee)
    setSelectedPriority(ticket.priority)
    setSelectedCategory(ticket.category)
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

  const loadAiRecommendations = useCallback(async (force = false) => {
    setAiLoading(true)
    setAiError(false)
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
    } catch {
      setAiSuggestions(null)
      setAiError(true)
    } finally {
      setAiLoading(false)
    }
  }, [locale, ticketData.id, ticketData.title, ticketData.description])

  useEffect(() => {
    setAiSuggestions(null)
    setAiError(false)
    loadAiRecommendations().catch(() => {})
  }, [loadAiRecommendations])

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

  function statusLabelForRow(value: TicketStatus): string {
    if (value === "open") return t("status.open")
    if (value === "in-progress") return t("status.inProgress")
    if (value === "waiting-for-customer") return t("status.waitingForCustomer")
    if (value === "waiting-for-support-vendor") return t("status.waitingForSupportVendor")
    if (value === "pending") return t("status.pending")
    if (value === "resolved") return t("status.resolved")
    return t("status.closed")
  }

  async function handleStatusChange(newStatus: string) {
    if (newStatus === status) return

    const comment = statusComment.trim()
    if (newStatus === "resolved" && !comment) {
      setStatusError(triageLabels.resolutionCommentRequired)
      return
    }
    if (newStatus === "closed" && !ticketData.resolution && !comment) {
      setStatusError(triageLabels.closureCommentRequired)
      return
    }

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

  async function updateTriage(payload: {
    assignee?: string
    priority?: TicketPriority
    category?: TicketCategory
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
      setSelectedCategory(refreshed.category)
      setStatus(refreshed.status)
      setTriageError(null)
    } catch {
      setTriageError(triageLabels.updateFailed)
    } finally {
      setTriageUpdating(false)
    }
  }

  function handleAssigneeChange(newAssignee: string) {
    if (!newAssignee || newAssignee === selectedAssignee) return
    setSelectedAssignee(newAssignee)
    updateTriage({ assignee: newAssignee }).catch(() => {})
  }

  function handlePriorityChange(newPriority: string) {
    const casted = newPriority as TicketPriority
    if (casted === selectedPriority) return
    setSelectedPriority(casted)
    updateTriage({ priority: casted }).catch(() => {})
  }

  function handleCategoryChange(newCategory: string) {
    const casted = newCategory as TicketCategory
    if (casted === selectedCategory) return
    setSelectedCategory(casted)
    updateTriage({ category: casted }).catch(() => {})
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
                    {CATEGORY_CONFIG[ticketData.category].label}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
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
                  <div className="grid grid-cols-1 gap-2">
                    <div className="rounded-lg border border-border/70 bg-background/70 p-2.5">
                      <p className="text-[11px] font-semibold text-muted-foreground">{t("detail.aiSuggestedPriority")}</p>
                      <div className="mt-1">
                        <Badge className={`${PRIORITY_CONFIG[aiSuggestions.priority].color} border-0 text-[10px]`}>
                          {t(`priority.${aiSuggestions.priority}` as "priority.medium")}
                        </Badge>
                      </div>
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

                  <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-primary">
                        {t("form.recommendedSolutions")}
                      </p>
                    {aiSuggestions.recommendations.length === 0 ? (
                      <p className="text-xs text-muted-foreground">{t("detail.aiRecommendationsEmpty")}</p>
                    ) : (
                      <div className="space-y-2">
                        {aiSuggestions.recommendations.map((recommendation, index) => (
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
              <CardTitle className="text-sm font-semibold text-foreground">AI SLA Risk (Advisory)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {aiSlaRiskLoading ? (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading AI SLA risk...
                </div>
              ) : null}

              {!aiSlaRiskLoading && !aiSlaRisk ? (
                <p className="text-xs text-muted-foreground">No AI risk evaluation available.</p>
              ) : null}

              {!aiSlaRiskLoading && aiSlaRisk ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      className={
                        (aiSlaRisk.riskScore ?? 0) >= 80
                          ? "border-0 bg-red-100 text-red-700"
                          : (aiSlaRisk.riskScore ?? 0) >= 50
                            ? "border-0 bg-amber-100 text-amber-700"
                            : "border-0 bg-emerald-100 text-emerald-700"
                      }
                    >
                      Risk {(aiSlaRisk.riskScore ?? 0) >= 80 ? "High" : (aiSlaRisk.riskScore ?? 0) >= 50 ? "Medium" : "Low"}
                      {aiSlaRisk.riskScore != null ? ` (${aiSlaRisk.riskScore})` : ""}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      Confidence {aiSlaRisk.confidence != null ? `${Math.round(aiSlaRisk.confidence * 100)}%` : "N/A"}
                    </Badge>
                  </div>
                  {aiSlaRisk.suggestedPriority ? (
                    <p className="text-xs text-foreground">
                      Suggested priority: <span className="font-semibold">{aiSlaRisk.suggestedPriority}</span>
                    </p>
                  ) : null}
                  <p className="rounded-lg border border-border/70 bg-background/70 p-2.5 text-xs text-muted-foreground">
                    {aiSlaRisk.reasoningSummary}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {new Date(aiSlaRisk.createdAt).toLocaleString(localeCode)} · {aiSlaRisk.modelVersion}
                  </p>
                </>
              ) : null}
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

              <Separator />

              <InfoRow icon={User} label={t("detail.assignedTo")} value={ticketData.assignee} />
              <InfoRow icon={User} label={t("detail.reportedBy")} value={ticketData.reporter} />
              <InfoRow icon={Tag} label={t("tickets.category")} value={CATEGORY_CONFIG[ticketData.category].label} />
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
        </div>
      </div>
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
