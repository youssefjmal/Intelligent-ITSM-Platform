"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { ArrowLeft, ExternalLink, Loader2, RefreshCw, Sparkles } from "lucide-react"
import { AppShell } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
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
import { ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { CATEGORY_CONFIG } from "@/lib/ticket-data"
import {
  assignProblemAssignee,
  fetchProblemAssignees,
  fetchProblem,
  fetchProblemAISuggestions,
  resolveProblemLinkedTickets,
  scoreProblemSuggestions,
  updateProblem,
  type ProblemAISuggestions,
  type ProblemAssigneeOption,
  type ProblemDetail,
  type ProblemStatus,
} from "@/lib/problems-api"

const PROBLEM_STATUS_CONFIG: Record<ProblemStatus, { color: string; labelFr: string; labelEn: string }> = {
  open: { color: "border border-blue-200 bg-blue-100 text-blue-800", labelFr: "Ouvert", labelEn: "Open" },
  investigating: { color: "border border-amber-200 bg-amber-100 text-amber-800", labelFr: "En investigation", labelEn: "Investigating" },
  known_error: { color: "border border-orange-200 bg-orange-100 text-orange-800", labelFr: "Erreur connue", labelEn: "Known error" },
  resolved: { color: "border border-emerald-200 bg-emerald-100 text-emerald-800", labelFr: "Resolu", labelEn: "Resolved" },
  closed: { color: "border border-slate-200 bg-slate-100 text-slate-700", labelFr: "Ferme", labelEn: "Closed" },
}

const PROBLEM_STATUSES: ProblemStatus[] = ["open", "investigating", "known_error", "resolved", "closed"]
const ASSIGNMENT_MODE_AUTO = "auto"
const ASSIGNMENT_MODE_MANUAL = "manual"
const ASSIGNMENT_MODE_MANUAL_PREFIX = "manual:"
const CURRENT_ASSIGNEE_OPTION_ID = "current-assignee"
type PendingAssignmentValue = typeof ASSIGNMENT_MODE_AUTO | `${typeof ASSIGNMENT_MODE_MANUAL_PREFIX}${string}`

const PROBLEM_API_ERROR_DETAIL = {
  resolutionCommentRequired: "resolution_comment_required",
  resolutionNeedsAnalysis: "problem_resolution_requires_root_cause_and_permanent_fix",
  invalidStatusTransition: "invalid_problem_status_transition",
  assigneeRequiredForManualMode: "assignee_required_for_manual_mode",
  assigneeNotAssignable: "assignee_not_assignable",
  assigneeUnavailable: "assignee_unavailable",
} as const

function statusLabel(status: ProblemStatus, locale: string): string {
  const config = PROBLEM_STATUS_CONFIG[status]
  return locale === "fr" ? config.labelFr : config.labelEn
}

function toManualAssignmentValue(assigneeId: string): PendingAssignmentValue {
  return `${ASSIGNMENT_MODE_MANUAL_PREFIX}${assigneeId}` as PendingAssignmentValue
}

function getManualAssigneeId(selection: PendingAssignmentValue): string | undefined {
  if (selection === ASSIGNMENT_MODE_AUTO) return undefined
  return selection.slice(ASSIGNMENT_MODE_MANUAL_PREFIX.length)
}

function getStatusUpdateErrorMessage(detail: string | undefined, locale: string): string {
  if (detail === PROBLEM_API_ERROR_DETAIL.resolutionCommentRequired) {
    return locale === "fr"
      ? "Un commentaire est obligatoire pour resoudre ou fermer un probleme."
      : "A comment is required to resolve or close a problem."
  }
  if (detail === PROBLEM_API_ERROR_DETAIL.resolutionNeedsAnalysis) {
    return locale === "fr"
      ? "La cause racine et le correctif permanent sont requis avant la resolution."
      : "Root cause and permanent fix are required before resolving."
  }
  if (detail === PROBLEM_API_ERROR_DETAIL.invalidStatusTransition) {
    return locale === "fr" ? "Transition de statut invalide." : "Invalid status transition."
  }
  return locale === "fr" ? "Impossible de mettre a jour le statut." : "Could not update status."
}

function getAssignmentUpdateErrorMessage(detail: string | undefined, locale: string): string {
  if (detail === PROBLEM_API_ERROR_DETAIL.assigneeRequiredForManualMode) {
    return locale === "fr" ? "Selectionnez un assigne manuel." : "Select a manual assignee."
  }
  if (detail === PROBLEM_API_ERROR_DETAIL.assigneeNotAssignable) {
    return locale === "fr" ? "Assigne non disponible." : "Selected assignee is not available."
  }
  if (detail === PROBLEM_API_ERROR_DETAIL.assigneeUnavailable) {
    return locale === "fr" ? "Aucun assigne auto disponible." : "No auto-assignee available."
  }
  return locale === "fr" ? "Impossible de mettre a jour l'affectation." : "Could not update assignment."
}

type ConfirmationDialogState = {
  title: string
  description: string
  onConfirm: () => void
}

export default function ProblemDetailPage() {
  const params = useParams<{ id: string }>()
  const problemId = String(params?.id || "")
  const { t, locale } = useI18n()
  const { hasPermission } = useAuth()

  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [pendingStatus, setPendingStatus] = useState<ProblemStatus>("open")
  const [statusComment, setStatusComment] = useState("")
  const [rootCause, setRootCause] = useState("")
  const [workaround, setWorkaround] = useState("")
  const [permanentFix, setPermanentFix] = useState("")
  const [statusUpdating, setStatusUpdating] = useState(false)
  const [analysisSaving, setAnalysisSaving] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [aiSuggestions, setAiSuggestions] = useState<Array<{ text: string; confidence: number }>>([])
  const [aiAssignee, setAiAssignee] = useState<string | undefined>(undefined)
  const [fieldSuggestions, setFieldSuggestions] = useState<{
    rootCause?: string
    rootCauseConfidence?: number
    workaround?: string
    workaroundConfidence?: number
    permanentFix?: string
    permanentFixConfidence?: number
  }>({})
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState(false)
  const [assigneeOptions, setAssigneeOptions] = useState<ProblemAssigneeOption[]>([])
  const [pendingAssignment, setPendingAssignment] = useState<PendingAssignmentValue>(ASSIGNMENT_MODE_AUTO)
  const [assignmentUpdating, setAssignmentUpdating] = useState(false)
  const [assignmentError, setAssignmentError] = useState<string | null>(null)
  const [confirmationDialog, setConfirmationDialog] = useState<ConfirmationDialogState | null>(null)

  const canResolve = hasPermission("resolve_ticket")
  const canEditProblem = hasPermission("edit_ticket_triage")
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"
  const assigneeLabel = problem?.assignee || (locale === "fr" ? "Non assigne" : "Unassigned")
  const isMutating = statusUpdating || analysisSaving || assignmentUpdating
  const assigneeSelectOptions = (() => {
    if (!problem?.assignee) return assigneeOptions
    if (assigneeOptions.some((member) => member.name === problem.assignee)) return assigneeOptions
    return [{ id: CURRENT_ASSIGNEE_OPTION_ID, name: problem.assignee, role: "current" }, ...assigneeOptions]
  })()

  function openConfirmationDialog(params: ConfirmationDialogState) {
    setConfirmationDialog(params)
  }

  const refreshProblem = useCallback(
    async (showLoader = false) => {
      if (!problemId) return
      if (showLoader) setLoading(true)
      try {
        const data = await fetchProblem(problemId)
        setProblem(data)
        setPendingStatus(data.status)
        setRootCause(data.rootCause || "")
        setWorkaround(data.workaround || "")
        setPermanentFix(data.permanentFix || "")
        setAiSuggestions(scoreProblemSuggestions(data.aiSuggestions || []))
        setStatusError(null)
        setAnalysisError(null)
        setAssignmentError(null)
      } catch {
        setProblem(null)
      } finally {
        setLoading(false)
      }
    },
    [problemId],
  )

  const loadAiSuggestions = useCallback(
    async (force = false) => {
      if (!problemId) return
      setAiLoading(true)
      setAiError(false)
      try {
        const payload: ProblemAISuggestions = await fetchProblemAISuggestions(problemId)
        setAiSuggestions(payload.suggestions)
        setAiAssignee(payload.assignee)
        setFieldSuggestions({
          rootCause: payload.rootCauseSuggestion,
          rootCauseConfidence: payload.rootCauseConfidence,
          workaround: payload.workaroundSuggestion,
          workaroundConfidence: payload.workaroundConfidence,
          permanentFix: payload.permanentFixSuggestion,
          permanentFixConfidence: payload.permanentFixConfidence,
        })
      } catch {
        if (force) {
          setAiSuggestions([])
          setFieldSuggestions({})
        }
        setAiError(true)
      } finally {
        setAiLoading(false)
      }
    },
    [problemId],
  )

  useEffect(() => {
    refreshProblem(true).catch(() => {})
  }, [refreshProblem])

  useEffect(() => {
    let mounted = true
    fetchProblemAssignees()
      .then((rows) => {
        if (!mounted) return
        setAssigneeOptions(rows)
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    if (!problem) return
    if (!problem.assignee) {
      setPendingAssignment(ASSIGNMENT_MODE_AUTO)
      return
    }
    const matched = assigneeOptions.find((member) => member.name === problem.assignee)
    if (matched) {
      setPendingAssignment(toManualAssignmentValue(matched.id))
      return
    }
    setPendingAssignment(toManualAssignmentValue(CURRENT_ASSIGNEE_OPTION_ID))
  }, [problem, assigneeOptions])

  useEffect(() => {
    loadAiSuggestions().catch(() => {})
  }, [loadAiSuggestions])

  async function handleSaveAnalysis() {
    if (!problem || !canEditProblem || isMutating) return
    setAnalysisSaving(true)
    try {
      await updateProblem(problem.id, {
        rootCause,
        workaround,
        permanentFix,
      })
      await refreshProblem()
      setAnalysisError(null)
    } catch {
      setAnalysisError(locale === "fr" ? "Impossible d'enregistrer l'analyse." : "Could not save analysis.")
    } finally {
      setAnalysisSaving(false)
    }
  }

  async function applyStatusUpdate(statusToApply: ProblemStatus, comment: string, requiresComment: boolean) {
    if (!problem) return
    setStatusUpdating(true)
    try {
      await updateProblem(problem.id, {
        status: statusToApply,
        rootCause,
        workaround,
        permanentFix,
        resolutionComment: comment || undefined,
      })
      if (requiresComment && comment) {
        await resolveProblemLinkedTickets(problem.id, comment)
      }
      await refreshProblem()
      await loadAiSuggestions(true)
      setStatusComment("")
      setStatusError(null)
    } catch (error) {
      if (error instanceof ApiError) {
        setStatusError(getStatusUpdateErrorMessage(error.detail, locale))
      } else {
        setStatusError(getStatusUpdateErrorMessage(undefined, locale))
      }
    } finally {
      setStatusUpdating(false)
    }
  }

  function handleStatusUpdate() {
    if (!problem || !canResolve || pendingStatus === problem.status || isMutating) return
    const comment = statusComment.trim()
    const requiresComment = pendingStatus === "resolved" || pendingStatus === "closed"
    if (requiresComment && !comment) {
      setStatusError(getStatusUpdateErrorMessage(PROBLEM_API_ERROR_DETAIL.resolutionCommentRequired, locale))
      return
    }

    const statusToApply = pendingStatus
    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer le changement de statut" : "Confirm status change",
      description:
        locale === "fr"
          ? `Voulez-vous vraiment changer le statut du probleme vers "${statusLabel(statusToApply, locale)}" ?`
          : `Are you sure you want to change the problem status to "${statusLabel(statusToApply, locale)}"?`,
      onConfirm: () => {
        void applyStatusUpdate(statusToApply, comment, requiresComment)
      },
    })
  }

  async function applyAssignmentUpdate(manualAssignee: string | undefined) {
    if (!problem) return
    setAssignmentUpdating(true)
    setAssignmentError(null)
    try {
      if (!manualAssignee) {
        await assignProblemAssignee(problem.id, { mode: ASSIGNMENT_MODE_AUTO })
      } else {
        await assignProblemAssignee(problem.id, { mode: ASSIGNMENT_MODE_MANUAL, assignee: manualAssignee })
      }
      await refreshProblem()
      await loadAiSuggestions(true)
      setAssignmentError(null)
    } catch (error) {
      if (error instanceof ApiError) {
        setAssignmentError(getAssignmentUpdateErrorMessage(error.detail, locale))
      } else {
        setAssignmentError(getAssignmentUpdateErrorMessage(undefined, locale))
      }
    } finally {
      setAssignmentUpdating(false)
    }
  }

  function handleAssignmentUpdate() {
    if (!problem || !canEditProblem) return
    let manualAssignee: string | undefined
    if (pendingAssignment !== ASSIGNMENT_MODE_AUTO) {
      const assigneeKey = getManualAssigneeId(pendingAssignment)
      manualAssignee =
        assigneeKey === CURRENT_ASSIGNEE_OPTION_ID
          ? problem.assignee
          : assigneeOptions.find((member) => member.id === assigneeKey)?.name
      if (!manualAssignee) {
        setAssignmentError(
          locale === "fr" ? "Selection d'assigne invalide." : "Invalid assignee selection.",
        )
        return
      }
    }

    openConfirmationDialog({
      title: locale === "fr" ? "Confirmer l'affectation" : "Confirm assignment",
      description: !manualAssignee
        ? locale === "fr"
          ? "Voulez-vous vraiment appliquer l'affectation automatique (IA) ?"
          : "Are you sure you want to apply auto-assignment (AI)?"
        : locale === "fr"
          ? `Voulez-vous vraiment affecter ce probleme a "${manualAssignee}" ?`
          : `Are you sure you want to assign this problem to "${manualAssignee}"?`,
      onConfirm: () => {
        void applyAssignmentUpdate(manualAssignee)
      },
    })
  }

  if (loading) {
    return (
      <AppShell>
        <div className="page-shell">
          <div className="surface-card rounded-2xl border-dashed p-8 text-center text-sm text-muted-foreground">
            {t("general.loading")}
          </div>
        </div>
      </AppShell>
    )
  }

  if (!problem) {
    return (
      <AppShell>
        <div className="page-shell">
          <div className="surface-card rounded-2xl border-dashed p-8 text-center">
            <p className="text-lg font-semibold text-foreground">
              {locale === "fr" ? "Probleme introuvable." : "Problem not found."}
            </p>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/problems">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <ArrowLeft className="h-4 w-4" />
              {t("detail.back")}
            </Button>
          </Link>
          <span className="text-sm font-mono text-muted-foreground">{problem.id}</span>
        </div>

        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_85%_10%,rgba(46,148,97,0.2),transparent_40%),radial-gradient(circle_at_18%_95%,rgba(217,119,6,0.12),transparent_40%)]" />
          <CardContent className="relative px-5 py-5 sm:px-6 sm:py-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="section-caption">{locale === "fr" ? "Probleme" : "Problem"}</p>
                <h2 className="mt-1 text-2xl font-bold text-foreground sm:text-3xl">{problem.title}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {CATEGORY_CONFIG[problem.category]?.label || problem.category} | {assigneeLabel}
                </p>
              </div>
              <Badge className={`${PROBLEM_STATUS_CONFIG[problem.status].color} border-0`}>
                {statusLabel(problem.status, locale)}
              </Badge>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Metric label={locale === "fr" ? "Occurrences" : "Occurrences"} value={String(problem.occurrencesCount)} />
              <Metric label={locale === "fr" ? "Actifs" : "Active"} value={String(problem.activeCount)} />
              <Metric
                label={locale === "fr" ? "Derniere occurrence" : "Last seen"}
                value={problem.lastSeenAt ? new Date(problem.lastSeenAt).toLocaleDateString(localeCode) : "-"}
              />
            </div>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card className="surface-card overflow-hidden rounded-2xl">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">{locale === "fr" ? "Analyse de probleme" : "Problem analysis"}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-xl border border-border/70 bg-background/50 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    {locale === "fr" ? "Cause racine" : "Root cause"}
                  </p>
                  <Textarea
                    value={rootCause}
                    onChange={(event) => setRootCause(event.target.value)}
                    className="min-h-[90px] text-sm"
                    placeholder={
                      fieldSuggestions.rootCause ||
                      (locale === "fr" ? "Decrire la cause racine..." : "Describe the root cause...")
                    }
                    disabled={!canEditProblem || isMutating}
                  />
                  <FieldSuggestionRow
                    label={locale === "fr" ? "Suggestion IA" : "AI suggestion"}
                    suggestion={fieldSuggestions.rootCause}
                    confidence={fieldSuggestions.rootCauseConfidence}
                    onApply={() => {
                      if (!fieldSuggestions.rootCause) return
                      setRootCause(fieldSuggestions.rootCause)
                    }}
                    applyLabel={locale === "fr" ? "Appliquer" : "Apply"}
                    disabled={!canEditProblem || isMutating}
                  />
                </div>
                <div className="rounded-xl border border-border/70 bg-background/50 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    {locale === "fr" ? "Contournement" : "Workaround"}
                  </p>
                  <Textarea
                    value={workaround}
                    onChange={(event) => setWorkaround(event.target.value)}
                    className="min-h-[90px] text-sm"
                    placeholder={
                      fieldSuggestions.workaround ||
                      (locale === "fr" ? "Decrire le contournement..." : "Describe a workaround...")
                    }
                    disabled={!canEditProblem || isMutating}
                  />
                  <FieldSuggestionRow
                    label={locale === "fr" ? "Suggestion IA" : "AI suggestion"}
                    suggestion={fieldSuggestions.workaround}
                    confidence={fieldSuggestions.workaroundConfidence}
                    onApply={() => {
                      if (!fieldSuggestions.workaround) return
                      setWorkaround(fieldSuggestions.workaround)
                    }}
                    applyLabel={locale === "fr" ? "Appliquer" : "Apply"}
                    disabled={!canEditProblem || isMutating}
                  />
                </div>
                <div className="rounded-xl border border-border/70 bg-background/50 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    {locale === "fr" ? "Correctif permanent" : "Permanent fix"}
                  </p>
                  <Textarea
                    value={permanentFix}
                    onChange={(event) => setPermanentFix(event.target.value)}
                    className="min-h-[90px] text-sm"
                    placeholder={
                      fieldSuggestions.permanentFix ||
                      (locale === "fr" ? "Decrire le correctif permanent..." : "Describe the permanent fix...")
                    }
                    disabled={!canEditProblem || isMutating}
                  />
                  <FieldSuggestionRow
                    label={locale === "fr" ? "Suggestion IA" : "AI suggestion"}
                    suggestion={fieldSuggestions.permanentFix}
                    confidence={fieldSuggestions.permanentFixConfidence}
                    onApply={() => {
                      if (!fieldSuggestions.permanentFix) return
                      setPermanentFix(fieldSuggestions.permanentFix)
                    }}
                    applyLabel={locale === "fr" ? "Appliquer" : "Apply"}
                    disabled={!canEditProblem || isMutating}
                  />
                </div>

                {analysisError && <p className="text-xs text-destructive">{analysisError}</p>}
                {canEditProblem && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleSaveAnalysis}
                    disabled={isMutating}
                  >
                    {analysisSaving ? (locale === "fr" ? "Enregistrement..." : "Saving...") : (locale === "fr" ? "Enregistrer l'analyse" : "Save analysis")}
                  </Button>
                )}
              </CardContent>
            </Card>

            <Card className="surface-card">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Sparkles className="h-4 w-4 text-primary" />
                    {locale === "fr" ? "Suggestions IA de resolution" : "AI resolution suggestions"}
                  </CardTitle>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 text-[11px]"
                    onClick={() => loadAiSuggestions(true)}
                    disabled={aiLoading}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${aiLoading ? "animate-spin" : ""}`} />
                    {t("detail.aiRefresh")}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {aiLoading && (
                  <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {t("detail.aiRecommendationsLoading")}
                  </div>
                )}

                {!aiLoading && aiError && <p className="text-xs text-destructive">{t("detail.aiRecommendationsError")}</p>}

                {!aiLoading && !aiError && (
                  <>
                    <div className="rounded-lg border border-primary/25 bg-primary/5 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
                        {locale === "fr" ? "Assigne suggere" : "Suggested assignee"}
                      </p>
                      <p className="mt-1 text-sm font-medium text-foreground">{aiAssignee || assigneeLabel}</p>
                    </div>

                    {aiSuggestions.length === 0 ? (
                      <p className="text-xs text-muted-foreground">{t("detail.aiRecommendationsEmpty")}</p>
                    ) : (
                      <div className="space-y-2">
                        {aiSuggestions.map((suggestion, index) => (
                          <div
                            key={`${problem.id}-ai-suggestion-${index}`}
                            className="rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs text-foreground"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <span>{suggestion.text}</span>
                              <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                                {suggestion.confidence}%
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="surface-card">
              <CardHeader>
                <CardTitle className="text-base">{locale === "fr" ? "Tickets lies" : "Linked tickets"}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {problem.tickets.length === 0 && (
                  <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
                    {locale === "fr" ? "Aucun ticket lie." : "No linked tickets."}
                  </div>
                )}
                {problem.tickets.map((ticket) => (
                  <div key={ticket.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-card/70 p-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {ticket.id} - {ticket.title}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {ticket.assignee} | {new Date(ticket.updated_at).toLocaleDateString(localeCode)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="border-border bg-background/70 text-[10px]">
                        {ticket.status}
                      </Badge>
                      <Link href={`/tickets/${ticket.id}`}>
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 rounded-lg">
                          <ExternalLink className="h-3.5 w-3.5" />
                          Ticket
                        </Button>
                      </Link>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
            <Card className="surface-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-foreground">
                  {locale === "fr" ? "Gestion du probleme" : "Problem controls"}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {!canResolve && (
                  <p className="text-xs text-muted-foreground">
                    {locale === "fr"
                      ? "Mode lecture seule: seuls les agents/admins peuvent changer le statut."
                      : "Read-only mode: only agent/admin roles can change status."}
                  </p>
                )}

                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">{t("tickets.status")}</p>
                  <Select
                    value={pendingStatus}
                    onValueChange={(value) => {
                      setPendingStatus(value as ProblemStatus)
                      setStatusError(null)
                    }}
                    disabled={!canResolve || isMutating}
                  >
                    <SelectTrigger className="h-8 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROBLEM_STATUSES.map((status) => (
                        <SelectItem key={status} value={status}>
                          {statusLabel(status, locale)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">
                    {locale === "fr" ? "Commentaire de resolution" : "Resolution comment"}
                  </p>
                  <Textarea
                    value={statusComment}
                    onChange={(event) => setStatusComment(event.target.value)}
                    className="min-h-[96px] text-sm"
                    placeholder={locale === "fr" ? "Obligatoire pour Resolu/Ferme" : "Required for Resolved/Closed"}
                    disabled={!canResolve || isMutating}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    {locale === "fr"
                      ? "Commentaire obligatoire pour resoudre/fermer et pour mettre a jour les tickets lies."
                      : "Comment is required for resolve/close and linked ticket updates."}
                  </p>
                </div>

                {statusError && <p className="text-xs text-destructive">{statusError}</p>}

                <Button
                  type="button"
                  size="sm"
                  className="w-full"
                  onClick={handleStatusUpdate}
                  disabled={!canResolve || isMutating || pendingStatus === problem.status}
                >
                  {statusUpdating
                    ? locale === "fr"
                      ? "Mise a jour..."
                      : "Updating..."
                    : locale === "fr"
                      ? "Mettre a jour le statut"
                      : "Update status"}
                </Button>

                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">{locale === "fr" ? "Affectation" : "Assignment"}</p>
                  <Select
                    value={pendingAssignment}
                    onValueChange={(value) => setPendingAssignment(value as PendingAssignmentValue)}
                    disabled={!canEditProblem || isMutating}
                  >
                    <SelectTrigger className="h-8 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ASSIGNMENT_MODE_AUTO}>{locale === "fr" ? "Auto (IA)" : "Auto (AI)"}</SelectItem>
                      {assigneeSelectOptions.map((member) => (
                        <SelectItem key={member.id} value={toManualAssignmentValue(member.id)}>
                          {member.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-[11px] text-muted-foreground">
                    {locale === "fr" ? "Suggestion IA" : "AI suggestion"}: {aiAssignee || assigneeLabel}
                  </p>
                </div>

                {assignmentError && <p className="text-xs text-destructive">{assignmentError}</p>}

                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={handleAssignmentUpdate}
                  disabled={!canEditProblem || isMutating}
                >
                  {assignmentUpdating
                    ? locale === "fr"
                      ? "Mise a jour..."
                      : "Updating..."
                    : locale === "fr"
                      ? "Mettre a jour l'affectation"
                      : "Update assignment"}
                </Button>

                <Separator />

                <InfoRow label={t("tickets.assignee")} value={assigneeLabel} />
                <InfoRow label={t("tickets.category")} value={CATEGORY_CONFIG[problem.category]?.label || problem.category} />
                <InfoRow label={t("tickets.status")} value={statusLabel(problem.status, locale)} />
              </CardContent>
            </Card>
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
    </AppShell>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value}</p>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="text-sm text-foreground">{value}</p>
    </div>
  )
}

function FieldSuggestionRow({
  label,
  suggestion,
  confidence,
  onApply,
  applyLabel,
  disabled = false,
}: {
  label: string
  suggestion?: string
  confidence?: number
  onApply: () => void
  applyLabel: string
  disabled?: boolean
}) {
  if (!suggestion) return null
  return (
    <div className="mt-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{label}</p>
            {typeof confidence === "number" && (
              <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                {Math.max(0, Math.min(100, Math.round(confidence)))}%
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-foreground">{suggestion}</p>
        </div>
        <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]" onClick={onApply} disabled={disabled}>
          {applyLabel}
        </Button>
      </div>
    </div>
  )
}
