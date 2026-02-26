"use client"

import { useEffect, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Gauge, Shuffle, Clock3, CheckCircle2, Bot, AlertTriangle } from "lucide-react"
import { useI18n } from "@/lib/i18n"
import { fetchTicketPerformance, type TicketPerformancePayload } from "@/lib/tickets-api"
import { type Ticket, type TicketCategory } from "@/lib/ticket-data"

type Scope = "all" | "before" | "after"
type CategoryFilter = TicketCategory | "all"

type PerformanceMetricsProps = {
  performance: TicketPerformancePayload
  assignees: string[]
  tickets: Ticket[]
}

function formatHours(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "N/A"
  return `${value.toFixed(1)}h`
}

function formatPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "N/A"
  return `${value.toFixed(1)}%`
}

function formatDelta(before: number | null, after: number | null): string {
  if (before === null || after === null || before <= 0) return "N/A"
  const ratio = ((before - after) / before) * 100
  const sign = ratio >= 0 ? "+" : ""
  return `${sign}${ratio.toFixed(1)}%`
}

function toMs(value?: string): number | null {
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : null
}

function computeLocalPerformance(
  tickets: Ticket[],
  filters: {
    scope: Scope
    category: CategoryFilter
    assignee: string
    dateFrom: string
    dateTo: string
  },
): TicketPerformancePayload {
  const isIATicket = (ticket: Ticket) => Boolean(ticket.autoAssignmentApplied || ticket.autoPriorityApplied)
  const fromMs = filters.dateFrom ? toMs(`${filters.dateFrom}T00:00:00.000Z`) : null
  const toMsLimit = filters.dateTo ? toMs(`${filters.dateTo}T23:59:59.999Z`) : null
  const assigneeFilter = filters.assignee === "all" ? "" : filters.assignee.trim().toLowerCase()

  const filtered = tickets.filter((ticket) => {
    const createdMs = toMs(ticket.createdAt)
    if (createdMs === null) return false
    if (fromMs !== null && createdMs < fromMs) return false
    if (toMsLimit !== null && createdMs > toMsLimit) return false
    if (filters.category !== "all" && ticket.category !== filters.category) return false
    if (assigneeFilter && ticket.assignee.trim().toLowerCase() !== assigneeFilter) return false
    if (filters.scope === "before" && isIATicket(ticket)) return false
    if (filters.scope === "after" && !isIATicket(ticket)) return false
    return true
  })

  const durationHours = (start?: string, end?: string): number => {
    const startMs = toMs(start)
    const endMs = toMs(end)
    if (startMs === null || endMs === null) return 0
    return Math.max((endMs - startMs) / 3600000, 0)
  }
  const avg = (values: number[]): number | null => {
    if (!values.length) return null
    return Number((values.reduce((acc, v) => acc + v, 0) / values.length).toFixed(2))
  }

  const resolvedStatuses = new Set(["resolved", "closed"])
  const resolved = filtered.filter((ticket) => resolvedStatuses.has(ticket.status))
  const beforeGroup = resolved.filter((ticket) => !isIATicket(ticket))
  const afterGroup = resolved.filter((ticket) => isIATicket(ticket))
  const mttrBefore = avg(beforeGroup.map((ticket) => durationHours(ticket.createdAt, ticket.resolvedAt || ticket.updatedAt)))
  const mttrAfter = avg(afterGroup.map((ticket) => durationHours(ticket.createdAt, ticket.resolvedAt || ticket.updatedAt)))

  const reassignedTickets = filtered.filter((ticket) => (ticket.assignmentChangeCount || 0) > 0).length
  const reassignmentRate = filtered.length ? Number(((reassignedTickets / filtered.length) * 100).toFixed(2)) : 0

  const firstActionAvg = avg(
    filtered
      .filter((ticket) => Boolean(ticket.firstActionAt))
      .map((ticket) => durationHours(ticket.createdAt, ticket.firstActionAt)),
  )

  const autoAssigned = filtered.filter((ticket) => isIATicket(ticket))
  const autoAssignmentSamples = autoAssigned.length
  const autoAssignmentCorrect = autoAssigned.filter((ticket) => (ticket.assignmentChangeCount || 0) === 0).length
  const autoAssignmentAccuracyRate = autoAssignmentSamples
    ? Number(((autoAssignmentCorrect / autoAssignmentSamples) * 100).toFixed(2))
    : null

  const classified = filtered.filter((ticket) => Boolean(ticket.predictedPriority || ticket.predictedCategory))
  const classificationSamples = classified.length
  let classificationCorrect = 0
  for (const ticket of classified) {
    let checks = 0
    let matches = 0
    if (ticket.predictedPriority) {
      checks += 1
      if (ticket.predictedPriority === ticket.priority) matches += 1
    }
    if (ticket.predictedCategory) {
      checks += 1
      if (ticket.predictedCategory === ticket.category) matches += 1
    }
    if (checks > 0 && checks === matches) classificationCorrect += 1
  }
  const classificationAccuracyRate = classificationSamples
    ? Number(((classificationCorrect / classificationSamples) * 100).toFixed(2))
    : null

  return {
    total_tickets: filtered.length,
    resolved_tickets: resolved.length,
    mttr_hours: {
      before: mttrBefore,
      after: mttrAfter,
    },
    mttr_global_hours: avg(resolved.map((ticket) => durationHours(ticket.createdAt, ticket.resolvedAt || ticket.updatedAt))),
    mttr_p90_hours: (() => {
      const values = resolved
        .map((ticket) => durationHours(ticket.createdAt, ticket.resolvedAt || ticket.updatedAt))
        .sort((a, b) => a - b)
      if (!values.length) return null
      const pos = (values.length - 1) * 0.9
      const low = Math.floor(pos)
      const high = Math.min(low + 1, values.length - 1)
      const weight = pos - low
      return Number((values[low] * (1 - weight) + values[high] * weight).toFixed(2))
    })(),
    mttr_by_priority_hours: {},
    mttr_by_category_hours: {},
    throughput_resolved_per_week: resolved.filter((ticket) => {
      const resolvedMs = toMs(ticket.resolvedAt || ticket.updatedAt)
      if (resolvedMs === null) return false
      const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
      return resolvedMs >= cutoff
    }).length,
    backlog_open_over_days: filtered.filter((ticket) => {
      const active = new Set(["open", "in-progress", "waiting-for-customer", "waiting-for-support-vendor", "pending"])
      if (!active.has(ticket.status)) return false
      const createdMs = toMs(ticket.createdAt)
      if (createdMs === null) return false
      const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
      return createdMs < cutoff
    }).length,
    backlog_threshold_days: 7,
    reassignment_rate: reassignmentRate,
    reassigned_tickets: reassignedTickets,
    avg_time_to_first_action_hours: firstActionAvg,
    median_time_to_first_action_hours: (() => {
      const values = filtered
        .filter((ticket) => Boolean(ticket.firstActionAt))
        .map((ticket) => durationHours(ticket.createdAt, ticket.firstActionAt))
        .sort((a, b) => a - b)
      if (!values.length) return null
      const n = values.length
      const mid = Math.floor(n / 2)
      if (n % 2 === 1) return Number(values[mid].toFixed(2))
      return Number(((values[mid - 1] + values[mid]) / 2).toFixed(2))
    })(),
    classification_accuracy_rate: classificationAccuracyRate,
    classification_samples: classificationSamples,
    auto_assignment_accuracy_rate: autoAssignmentAccuracyRate,
    auto_assignment_samples: autoAssignmentSamples,
    auto_triage_no_correction_rate: autoAssignmentAccuracyRate,
    auto_triage_no_correction_count: autoAssignmentCorrect,
    auto_triage_samples: autoAssignmentSamples,
    sla_breach_rate: null,
    sla_breached_tickets: 0,
    sla_tickets_with_due: 0,
    first_response_sla_breach_rate: null,
    first_response_sla_breached_count: 0,
    first_response_sla_eligible: 0,
    resolution_sla_breach_rate: null,
    resolution_sla_breached_count: 0,
    resolution_sla_eligible: 0,
    reopen_rate: null,
    first_contact_resolution_rate: null,
    csat_score: null,
  }
}

export function PerformanceMetrics({ performance: initialPerformance, assignees, tickets }: PerformanceMetricsProps) {
  const { locale, t } = useI18n()
  const isFr = locale === "fr"
  const defaultScope: Scope = "after"
  const [scope, setScope] = useState<Scope>(defaultScope)
  const [category, setCategory] = useState<CategoryFilter>("all")
  const [assignee, setAssignee] = useState<string>("all")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [performance, setPerformance] = useState<TicketPerformancePayload>(initialPerformance)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<"api" | "local">("api")

  const categoryOptions: Array<{ value: CategoryFilter; label: string }> = [
    { value: "all", label: isFr ? "Toutes categories" : "All categories" },
    { value: "infrastructure", label: t("category.infrastructure") },
    { value: "network", label: t("category.network") },
    { value: "security", label: t("category.security") },
    { value: "application", label: t("category.application") },
    { value: "service_request", label: t("category.service_request") },
    { value: "hardware", label: t("category.hardware") },
    { value: "email", label: t("category.email") },
    { value: "problem", label: t("category.problem") },
  ]

  async function loadMetrics(filters: {
    scope: Scope
    category: CategoryFilter
    assignee: string
    dateFrom: string
    dateTo: string
  }) {
    if (filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo) {
      setError(isFr ? "Plage de dates invalide." : "Invalid date range.")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await fetchTicketPerformance({
        scope: filters.scope,
        dateFrom: filters.dateFrom || undefined,
        dateTo: filters.dateTo || undefined,
        category: filters.category === "all" ? undefined : filters.category,
        assignee: filters.assignee === "all" ? undefined : filters.assignee,
      })
      setPerformance(data)
      setSource("api")
      setError(null)
    } catch {
      const fallback = computeLocalPerformance(tickets, filters)
      setPerformance(fallback)
      setSource("local")
      setError(isFr ? "Mode local actif (API indisponible)." : "Local fallback mode active (API unavailable).")
    } finally {
      setLoading(false)
    }
  }

  async function refreshMetrics() {
    await loadMetrics({ scope, category, assignee, dateFrom, dateTo })
  }

  useEffect(() => {
    const handle = window.setTimeout(() => {
      refreshMetrics().catch(() => {})
    }, 180)
    return () => window.clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, category, assignee, dateFrom, dateTo, tickets])

  function resetFilters() {
    const defaults = {
      scope: defaultScope,
      category: "all" as CategoryFilter,
      assignee: "all",
      dateFrom: "",
      dateTo: "",
    }
    setScope(defaults.scope)
    setCategory(defaults.category)
    setAssignee(defaults.assignee)
    setDateFrom(defaults.dateFrom)
    setDateTo(defaults.dateTo)
    loadMetrics(defaults).catch(() => {})
  }

  const cards = [
    {
      title: isFr ? "MTTR (avant)" : "MTTR (before)",
      value: formatHours(performance.mttr_hours.before),
      subtitle: isFr ? "Tickets non auto-assignes" : "Non auto-assigned tickets",
      icon: Gauge,
      iconColor: "text-slate-300",
      iconBg: "bg-slate-700/70",
    },
    {
      title: isFr ? "MTTR apres (smart)" : "MTTR after (smart)",
      value: formatHours(performance.mttr_hours.after),
      subtitle: isFr ? "Tickets auto-assignes" : "Auto-assigned tickets",
      icon: Bot,
      iconColor: "text-emerald-200",
      iconBg: "bg-emerald-900/70",
    },
    {
      title: isFr ? "Taux de reassignation" : "Reassignment rate",
      value: formatPercent(performance.reassignment_rate),
      subtitle: `${performance.reassigned_tickets} ${isFr ? "tickets reassignes" : "tickets reassigned"}`,
      icon: Shuffle,
      iconColor: "text-amber-200",
      iconBg: "bg-amber-900/70",
    },
    {
      title: isFr ? "Temps 1re action" : "Time to first action",
      value: formatHours(performance.avg_time_to_first_action_hours),
      subtitle: isFr ? "Moyenne globale" : "Global average",
      icon: Clock3,
      iconColor: "text-blue-200",
      iconBg: "bg-blue-900/70",
    },
    {
      title: isFr ? "Taux de breach SLA" : "SLA breach rate",
      value: formatPercent(performance.sla_breach_rate),
      subtitle:
        performance.sla_tickets_with_due > 0
          ? `${performance.sla_breached_tickets}/${performance.sla_tickets_with_due} ${isFr ? "tickets" : "tickets"}`
          : isFr
            ? "Aucune donnee SLA"
            : "No SLA data",
      icon: AlertTriangle,
      iconColor: "text-rose-200",
      iconBg: "bg-rose-900/70",
    },
    {
      title: isFr ? "Classification correcte" : "Correct classification",
      value: formatPercent(performance.classification_accuracy_rate),
      subtitle: `${performance.classification_samples} ${isFr ? "echantillons" : "samples"}`,
      icon: CheckCircle2,
      iconColor: "text-cyan-200",
      iconBg: "bg-cyan-900/70",
    },
  ]

  const activeFilters: string[] = []
  if (scope !== defaultScope) {
    activeFilters.push(scope === "all" ? (isFr ? "Portee: tous" : "Scope: all") : scope === "before" ? (isFr ? "Portee: avant IA" : "Scope: before AI") : (isFr ? "Portee: apres IA" : "Scope: after AI"))
  }
  if (category !== "all") {
    const matched = categoryOptions.find((item) => item.value === category)
    activeFilters.push(`${isFr ? "Categorie" : "Category"}: ${matched?.label ?? category}`)
  }
  if (assignee !== "all") {
    activeFilters.push(`${isFr ? "Assigne" : "Assignee"}: ${assignee}`)
  }
  if (dateFrom || dateTo) {
    activeFilters.push(`${isFr ? "Dates" : "Dates"}: ${dateFrom || "..."} - ${dateTo || "..."}`)
  }

  return (
    <section className="surface-card fade-slide-in space-y-4 rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-foreground">
            {isFr ? "Mesures IA avant / apres" : "AI before/after metrics"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {isFr
              ? `Amelioration MTTR: ${formatDelta(performance.mttr_hours.before, performance.mttr_hours.after)}`
              : `MTTR improvement: ${formatDelta(performance.mttr_hours.before, performance.mttr_hours.after)}`}
          </p>
        </div>
        <Badge variant="outline" className="border-primary/25 bg-primary/5 text-[11px] text-primary">
          {isFr ? "Filtres: section IA uniquement" : "Filters: AI section only"}
        </Badge>
      </div>

      <div className="rounded-xl border border-border/70 bg-muted/15 p-3">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-6">
          <Select value={scope} onValueChange={(value) => setScope(value as Scope)}>
            <SelectTrigger className="h-10 rounded-xl bg-background/70">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="after">{isFr ? "Apres IA" : "After AI"}</SelectItem>
              <SelectItem value="before">{isFr ? "Avant IA" : "Before AI"}</SelectItem>
              <SelectItem value="all">{isFr ? "Tous" : "All"}</SelectItem>
            </SelectContent>
          </Select>
          <Input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="h-10 rounded-xl bg-background/70"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="h-10 rounded-xl bg-background/70"
          />
          <Select value={category} onValueChange={(value) => setCategory(value as CategoryFilter)}>
            <SelectTrigger className="h-10 rounded-xl bg-background/70">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {categoryOptions.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={assignee} onValueChange={setAssignee}>
            <SelectTrigger className="h-10 rounded-xl bg-background/70">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{isFr ? "Tous assignees" : "All assignees"}</SelectItem>
              {assignees.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2">
            <Button size="sm" className="h-10 rounded-xl px-4" onClick={() => refreshMetrics().catch(() => {})} disabled={loading}>
              {loading ? (isFr ? "Chargement..." : "Loading...") : (isFr ? "Appliquer" : "Apply")}
            </Button>
            <Button size="sm" variant="outline" className="h-10 rounded-xl px-4" onClick={resetFilters} disabled={loading}>
              {isFr ? "Reset" : "Reset"}
            </Button>
          </div>
        </div>

        {activeFilters.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {activeFilters.map((filter) => (
              <Badge key={filter} variant="outline" className="border-border bg-background/70 text-[11px]">
                {filter}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <p>
          {isFr
            ? `Tickets filtres: ${performance.total_tickets} | Resolus: ${performance.resolved_tickets}`
            : `Filtered tickets: ${performance.total_tickets} | Resolved: ${performance.resolved_tickets}`}
        </p>
        <p>
          {isFr
            ? `Source: ${source === "api" ? "API backend" : "calcul local frontend"}`
            : `Source: ${source === "api" ? "backend API" : "local frontend computation"}`}
        </p>
      </div>

      {performance.total_tickets === 0 && (
        <p className="text-xs text-amber-500">
          {isFr
            ? "Aucun ticket ne correspond aux filtres selectionnes."
            : "No tickets match the selected filters."}
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}

      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={`perf-card-skeleton-${index}`} className="rounded-2xl border border-border/70 bg-card/70 p-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-2 h-7 w-16" />
              <Skeleton className="mt-3 h-3 w-28" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
          {cards.map((card) => (
            <Card key={card.title} className="surface-card overflow-hidden rounded-2xl border-border/70">
              <CardContent className="p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{card.title}</p>
                    <p className="text-xl font-bold text-foreground">{card.value}</p>
                  </div>
                  <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${card.iconBg}`}>
                    <card.icon className={`h-4 w-4 ${card.iconColor}`} />
                  </div>
                </div>
                <p className="mt-2.5 text-[11px] text-muted-foreground">{card.subtitle}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <p className="text-[11px] text-muted-foreground">
        {isFr
          ? "Condition (Classification correcte): seuls les tickets avec prediction IA (priorite et/ou categorie) sont echantillonnes. Un ticket est compte 'correct' si toutes les valeurs predites presentes correspondent aux valeurs finales du ticket."
          : "Condition (Correct classification): only tickets with AI prediction (priority and/or category) are sampled. A ticket is counted as correct only if all predicted fields present match the ticket final values."}
      </p>
    </section>
  )
}
