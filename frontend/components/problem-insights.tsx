"use client"

import Link from "next/link"
import { AlertTriangle, ArrowRight, Flame, Repeat2, ShieldAlert } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { useI18n } from "@/lib/i18n"

type ProblemInsight = {
  title: string
  occurrences: number
  active_count: number
  problem_count: number
  highest_priority: "critical" | "high" | "medium" | "low"
  latest_ticket_id: string
  latest_updated_at: string
  ticket_ids: string[]
  problem_triggered: boolean
  trigger_reasons: string[]
  recent_occurrences_7d: number
  same_day_peak: number
  same_day_peak_date: string | null
  ai_recommendation: string
  ai_recommendation_confidence?: number
}

function priorityBadgeClass(priority: ProblemInsight["highest_priority"]): string {
  if (priority === "critical") return "border-red-200 bg-red-100 text-red-800 dark:border-red-400/60 dark:bg-red-900/70 dark:text-red-100"
  if (priority === "high") return "border-amber-200 bg-amber-100 text-amber-800 dark:border-amber-400/60 dark:bg-amber-900/70 dark:text-amber-100"
  if (priority === "medium") return "border-emerald-200 bg-emerald-100 text-emerald-800 dark:border-emerald-400/60 dark:bg-emerald-900/70 dark:text-emerald-100"
  return "border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-400/60 dark:bg-slate-700/80 dark:text-slate-100"
}

function triggerReasonLabel(
  reason: string,
  t: (key: "dashboard.problemTrigger5in7" | "dashboard.problemTrigger4sameDay", params?: Record<string, string | number>) => string,
): string {
  if (reason === "5_in_7_days") return t("dashboard.problemTrigger5in7")
  if (reason === "4_same_day") return t("dashboard.problemTrigger4sameDay")
  return reason
}

export function ProblemInsights({ insights }: { insights: ProblemInsight[] }) {
  const { t, locale } = useI18n()
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"

  const totals = insights.reduce(
    (acc, current) => {
      acc.occurrences += current.occurrences
      acc.active += current.active_count
      acc.promoted += current.problem_count
      return acc
    },
    { occurrences: 0, active: 0, promoted: 0 },
  )

  return (
    <section className="fade-slide-in relative overflow-hidden rounded-2xl border border-red-200/70 bg-gradient-to-br from-red-50 via-amber-50 to-orange-50 p-4 shadow-sm dark:border-red-500/40 dark:bg-gradient-to-br dark:from-red-950/40 dark:via-zinc-900/80 dark:to-orange-950/30 sm:p-6">
      <div className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-red-300/25 blur-3xl dark:bg-red-500/20" />
      <div className="pointer-events-none absolute -bottom-16 left-24 h-40 w-40 rounded-full bg-amber-300/20 blur-3xl dark:bg-amber-500/20" />

      <div className="relative space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-100/75 px-3 py-1 text-xs font-semibold text-red-700 dark:border-red-500/40 dark:bg-red-500/20 dark:text-red-100">
              <AlertTriangle className="h-3.5 w-3.5" />
              {t("dashboard.problemInsightsTitle")}
            </div>
            <p className="mt-2 text-sm text-red-900/80 dark:text-red-100">{t("dashboard.problemInsightsSubtitle")}</p>
          </div>

          <Badge className="h-fit border-red-200 bg-white/80 text-red-700 backdrop-blur dark:border-red-400/60 dark:bg-red-900/70 dark:text-red-100">
            {insights.length} {t("dashboard.problemPatterns")}
          </Badge>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-red-200/70 bg-white/70 p-3 shadow-sm backdrop-blur dark:border-red-500/50 dark:bg-red-950/80">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700/80 dark:text-red-100">{t("dashboard.problemOccurrences")}</p>
            <p className="mt-1 text-xl font-bold text-red-900 dark:text-red-50">{totals.occurrences}</p>
          </div>
          <div className="rounded-xl border border-amber-200/70 bg-white/70 p-3 shadow-sm backdrop-blur dark:border-amber-500/50 dark:bg-amber-950/80">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/80 dark:text-amber-100">{t("dashboard.problemActive")}</p>
            <p className="mt-1 text-xl font-bold text-amber-900 dark:text-amber-50">{totals.active}</p>
          </div>
          <div className="rounded-xl border border-emerald-200/80 bg-white/70 p-3 shadow-sm backdrop-blur dark:border-emerald-500/50 dark:bg-emerald-950/80">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700/80 dark:text-emerald-100">{t("dashboard.problemPromoted")}</p>
            <p className="mt-1 text-xl font-bold text-emerald-900 dark:text-emerald-50">{totals.promoted}</p>
          </div>
        </div>

        {insights.length === 0 ? (
          <div className="rounded-xl border border-red-200/70 bg-white/80 p-4 dark:border-red-500/40 dark:bg-slate-950/70">
            <p className="text-sm text-muted-foreground">{t("dashboard.problemNoData")}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {insights.map((problem) => (
              <HoverCard key={`${problem.latest_ticket_id}-${problem.title}`} openDelay={100} closeDelay={80}>
                <HoverCardTrigger asChild>
                  <Link href={problem.latest_ticket_id ? `/tickets/${problem.latest_ticket_id}` : "/problems"} className="group block">
                    <article className="rounded-xl border border-white/80 bg-white/90 p-4 shadow-sm backdrop-blur transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md dark:border-slate-600/70 dark:bg-slate-900/90 dark:hover:bg-slate-900">
	                      <div className="flex items-start justify-between gap-3">
	                        <div className="min-w-0">
	                          <p className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">{problem.title}</p>
	                          <p className="mt-1 text-xs text-muted-foreground dark:text-slate-300">
	                            {t("dashboard.problemBrief", {
                              occurrences: problem.occurrences,
                              active: problem.active_count,
                              priority: t(`priority.${problem.highest_priority}` as "priority.medium"),
	                            })}
	                          </p>
                            <p className="mt-1 text-xs font-medium text-rose-700 dark:text-rose-200">
                              {problem.problem_triggered
                                ? t("dashboard.problemTriggerSummary", {
                                    count7d: problem.recent_occurrences_7d,
                                    count1d: problem.same_day_peak,
                                  })
                                : t("dashboard.problemTriggerNotReached", {
                                    count7d: problem.recent_occurrences_7d,
                                    count1d: problem.same_day_peak,
                                  })}
                            </p>
	                        </div>
	                        <div className="flex flex-col items-end gap-1">
	                          <Badge className={`border text-[10px] ${priorityBadgeClass(problem.highest_priority)}`}>
	                            {t(`priority.${problem.highest_priority}` as "priority.medium")}
	                          </Badge>
                            <Badge
                              className={
                                problem.problem_triggered
                                  ? "border border-red-300 bg-red-100 text-[10px] font-semibold text-red-800 dark:border-red-400/70 dark:bg-red-950/85 dark:text-red-100"
                                  : "border border-slate-300 bg-slate-100 text-[10px] font-semibold text-slate-700 dark:border-slate-500/80 dark:bg-slate-800/90 dark:text-slate-200"
                              }
                            >
                              {problem.problem_triggered ? t("dashboard.problemTriggered") : t("dashboard.problemWatching")}
                            </Badge>
                          </div>
	                      </div>

                      <div className="mt-3 grid grid-cols-3 gap-2">
                        <div className="rounded-lg border border-red-200/80 bg-red-50 p-2.5 shadow-sm dark:border-red-400/70 dark:bg-red-950/95 dark:ring-1 dark:ring-red-500/30">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-red-700 dark:text-red-100">{t("dashboard.problemOccurrences")}</p>
                          <p className="mt-0.5 text-lg font-extrabold text-red-900 dark:text-red-50">{problem.occurrences}</p>
                        </div>
                        <div className="rounded-lg border border-amber-200/80 bg-amber-50 p-2.5 shadow-sm dark:border-amber-400/70 dark:bg-amber-950/95 dark:ring-1 dark:ring-amber-500/30">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-amber-700 dark:text-amber-100">{t("dashboard.problemActive")}</p>
                          <p className="mt-0.5 text-lg font-extrabold text-amber-900 dark:text-amber-50">{problem.active_count}</p>
                        </div>
                        <div className="rounded-lg border border-emerald-200/80 bg-emerald-50 p-2.5 shadow-sm dark:border-emerald-400/70 dark:bg-emerald-950/95 dark:ring-1 dark:ring-emerald-500/30">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-100">{t("dashboard.problemPromoted")}</p>
                          <p className="mt-0.5 text-lg font-extrabold text-emerald-900 dark:text-emerald-50">{problem.problem_count}</p>
                        </div>
                      </div>

	                      <div className="mt-3 flex flex-wrap items-center gap-1.5">
	                        <span className="inline-flex items-center gap-1 rounded-md border border-slate-300/80 bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700 dark:border-slate-500/80 dark:bg-slate-800/90 dark:text-slate-100">
	                          <Repeat2 className="h-3 w-3" />
	                          {t("dashboard.problemTickets")}
	                        </span>
                        {problem.ticket_ids.slice(0, 4).map((ticketId) => (
                          <Badge
                            key={`${problem.latest_ticket_id}-${ticketId}`}
                            variant="outline"
                            className="border border-emerald-300 bg-emerald-50 text-[11px] font-bold text-emerald-900 dark:border-emerald-300/70 dark:bg-emerald-900/80 dark:text-emerald-50"
                          >
                            {ticketId}
                          </Badge>
	                        ))}
	                      </div>

                        <div className="mt-3 rounded-lg border border-violet-200/80 bg-violet-50/90 p-2.5 dark:border-violet-400/60 dark:bg-violet-950/75">
                          <div className="flex items-center gap-2">
                            <p className="text-[11px] font-bold uppercase tracking-wide text-violet-700 dark:text-violet-100">
                              {t("dashboard.problemRecommendation")}
                            </p>
                            {typeof problem.ai_recommendation_confidence === "number" && (
                              <span className="rounded border border-violet-300 bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold text-violet-800 dark:border-violet-300/60 dark:bg-violet-900/80 dark:text-violet-100">
                                {Math.max(0, Math.min(100, Math.round(problem.ai_recommendation_confidence)))}%
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-xs font-medium text-violet-900 dark:text-violet-100">{problem.ai_recommendation}</p>
                        </div>

	                      <div className="mt-3 flex items-center justify-between">
	                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-700 dark:text-red-300">
	                          <ShieldAlert className="h-3.5 w-3.5" />
                          {t("dashboard.problemViewLatest")}
                        </span>
                        <Badge className="h-7 border-orange-200 bg-orange-100/80 px-2.5 text-[11px] text-orange-800 dark:border-orange-500/50 dark:bg-orange-900/70 dark:text-orange-100">
                          <Flame className="mr-1 h-3.5 w-3.5" />
                          {problem.occurrences}x
                        </Badge>
                      </div>
                    </article>
                  </Link>
                </HoverCardTrigger>

                <HoverCardContent className="w-80 border-border/70 bg-background/95 p-3 shadow-xl backdrop-blur">
                  <p className="text-sm font-semibold text-foreground">{problem.title}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("dashboard.problemLastOccurrence")}:{" "}
                    {new Date(problem.latest_updated_at).toLocaleString(localeCode)}
                  </p>
	                  <div className="mt-3 grid grid-cols-3 gap-2">
	                    <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
	                      <p className="text-[10px] text-muted-foreground">{t("dashboard.problemOccurrences")}</p>
	                      <p className="text-sm font-semibold text-foreground">{problem.occurrences}</p>
	                    </div>
                    <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                      <p className="text-[10px] text-muted-foreground">{t("dashboard.problemActive")}</p>
                      <p className="text-sm font-semibold text-foreground">{problem.active_count}</p>
                    </div>
                    <div className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">
                      <p className="text-[10px] text-muted-foreground">{t("dashboard.problemPromoted")}</p>
	                      <p className="text-sm font-semibold text-foreground">{problem.problem_count}</p>
	                    </div>
	                  </div>
                  <div className="mt-3 rounded-md border border-border/60 bg-muted/40 px-2 py-2">
                    <p className="text-[10px] text-muted-foreground">{t("dashboard.problemTrigger")}</p>
                    {problem.problem_triggered ? (
                      <p className="mt-0.5 text-xs font-semibold text-foreground">
                        {problem.trigger_reasons.length > 0
                          ? problem.trigger_reasons.map((reason) => triggerReasonLabel(reason, t)).join(" + ")
                          : t("dashboard.problemTriggered")}
                      </p>
                    ) : (
                      <p className="mt-0.5 text-xs font-medium text-muted-foreground">
                        {t("dashboard.problemWatching")}
                      </p>
                    )}
                  </div>
                  <div className="mt-2 rounded-md border border-border/60 bg-muted/40 px-2 py-2">
                    <div className="flex items-center gap-2">
                      <p className="text-[10px] text-muted-foreground">{t("dashboard.problemRecommendation")}</p>
                      {typeof problem.ai_recommendation_confidence === "number" && (
                        <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                          {Math.max(0, Math.min(100, Math.round(problem.ai_recommendation_confidence)))}%
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs font-medium text-foreground">{problem.ai_recommendation}</p>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
	                    {problem.ticket_ids.map((ticketId) => (
                        <Link key={`hover-${problem.latest_ticket_id}-${ticketId}`} href={`/tickets/${ticketId}`} className="inline-flex">
                          <Badge variant="secondary" className="text-[10px]">
                            {ticketId}
                          </Badge>
                        </Link>
                      ))}
                  </div>
                  <Link href={problem.latest_ticket_id ? `/tickets/${problem.latest_ticket_id}` : "/problems"} className="mt-3 inline-flex">
                    <Button size="sm" className="h-8 gap-1.5 bg-red-600 text-white hover:bg-red-700 dark:bg-red-500 dark:hover:bg-red-600">
                      {t("dashboard.problemViewLatest")}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </Link>
                </HoverCardContent>
              </HoverCard>
            ))}
          </div>
        )}

        <Link href="/problems" className="inline-flex">
          <Button size="sm" variant="outline" className="gap-1.5 border-red-300 bg-white text-red-800 hover:bg-red-100 dark:border-red-500/40 dark:bg-red-950/30 dark:text-red-100 dark:hover:bg-red-900/40">
            {t("dashboard.viewProblemTickets")}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </Link>
      </div>
    </section>
  )
}
