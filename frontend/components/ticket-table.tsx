"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card } from "@/components/ui/card"
import { Search, ArrowUpDown, ExternalLink, Link2, X, Clock, User, AlertTriangle } from "lucide-react"
import {
  type Ticket,
  type TicketStatus,
  type TicketPriority,
  type SlaStatus,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  TICKET_TYPE_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { fetchProblems, type ProblemListItem, type ProblemStatus } from "@/lib/problems-api"
import { fetchTicketSlaAdvisory, type TicketSlaAdvisory } from "@/lib/tickets-api"

interface TicketTableProps {
  tickets: Ticket[]
  initialStatusFilter?: string
  initialPriorityFilter?: string
  initialTicketTypeFilter?: string
  initialCategoryFilter?: string
  initialSearch?: string
  minInactiveDays?: number
}

const ACTIVE_STATUSES: TicketStatus[] = [
  "open",
  "in-progress",
  "waiting-for-customer",
  "waiting-for-support-vendor",
  "pending",
]

const PROBLEM_STATUS_CONFIG: Record<ProblemStatus, { labelFr: string; labelEn: string; color: string }> = {
  open: { labelFr: "Ouvert", labelEn: "Open", color: "border border-blue-200 bg-blue-100 text-blue-800" },
  investigating: { labelFr: "En investigation", labelEn: "Investigating", color: "border border-amber-200 bg-amber-100 text-amber-800" },
  known_error: { labelFr: "Erreur connue", labelEn: "Known error", color: "border border-orange-200 bg-orange-100 text-orange-800" },
  resolved: { labelFr: "Resolu", labelEn: "Resolved", color: "border border-emerald-200 bg-emerald-100 text-emerald-800" },
  closed: { labelFr: "Ferme", labelEn: "Closed", color: "border border-slate-200 bg-slate-100 text-slate-700" },
}

const SLA_STATUS_CONFIG: Record<
  SlaStatus,
  { labelFr: string; labelEn: string; color: string; hintFr: string; hintEn: string }
> = {
  ok: {
    labelFr: "OK",
    labelEn: "OK",
    color: "bg-emerald-100 text-emerald-800",
    hintFr: "SLA respecte pour le moment.",
    hintEn: "SLA is currently on track.",
  },
  at_risk: {
    labelFr: "A risque",
    labelEn: "At risk",
    color: "bg-amber-100 text-amber-800",
    hintFr: "Attention: risque de breach SLA.",
    hintEn: "Warning: SLA breach risk detected.",
  },
  breached: {
    labelFr: "Breach",
    labelEn: "Breached",
    color: "bg-red-100 text-red-800",
    hintFr: "SLA depasse pour ce ticket.",
    hintEn: "SLA is breached for this ticket.",
  },
  paused: {
    labelFr: "En pause",
    labelEn: "Paused",
    color: "bg-slate-100 text-slate-700",
    hintFr: "SLA en pause.",
    hintEn: "SLA timer is paused.",
  },
  completed: {
    labelFr: "Complete",
    labelEn: "Completed",
    color: "bg-blue-100 text-blue-800",
    hintFr: "Objectif SLA atteint.",
    hintEn: "SLA target completed.",
  },
  unknown: {
    labelFr: "Inconnu",
    labelEn: "Unknown",
    color: "bg-slate-100 text-slate-700",
    hintFr: "Aucune donnee SLA disponible.",
    hintEn: "No SLA data available.",
  },
}

function inactiveDaysFrom(dateValue: string): number {
  const now = Date.now()
  const date = new Date(dateValue).getTime()
  if (Number.isNaN(date)) return 0
  return Math.max(0, Math.floor((now - date) / (1000 * 60 * 60 * 24)))
}

function formatRemainingSla(minutes: number | null | undefined, options: { isFr: boolean }): string {
  const { isFr } = options
  if (!Number.isFinite(minutes)) return isFr ? "Non disponible" : "Not available"
  const rounded = Math.max(0, Math.round(Number(minutes)))
  if (rounded < 60) return isFr ? `${rounded} min` : `${rounded} min`
  if (rounded < 1440) {
    const hours = Math.floor(rounded / 60)
    const mins = rounded % 60
    if (mins === 0) return isFr ? `${hours} h` : `${hours} h`
    return isFr ? `${hours} h ${mins} min` : `${hours}h ${mins}m`
  }
  const days = Math.floor(rounded / 1440)
  const remHours = Math.floor((rounded % 1440) / 60)
  if (remHours === 0) return isFr ? `${days} j` : `${days} d`
  return isFr ? `${days} j ${remHours} h` : `${days}d ${remHours}h`
}

function formatRemainingSlaSeconds(seconds: number | null | undefined, options: { isFr: boolean }): string {
  const { isFr } = options
  if (!Number.isFinite(seconds)) return isFr ? "Non disponible" : "Not available"
  const value = Math.max(0, Math.floor(Number(seconds)))
  if (value < 60) return isFr ? `${value} sec` : `${value}s`
  if (value < 3600) {
    const mins = Math.floor(value / 60)
    const secs = value % 60
    if (secs === 0) return isFr ? `${mins} min` : `${mins}m`
    return isFr ? `${mins} min ${secs} sec` : `${mins}m ${secs}s`
  }
  const hours = Math.floor(value / 3600)
  const mins = Math.floor((value % 3600) / 60)
  if (mins === 0) return isFr ? `${hours} h` : `${hours}h`
  return isFr ? `${hours} h ${mins} min` : `${hours}h ${mins}m`
}

function advisorySnippet(text: string | null | undefined, maxLength = 220): string {
  const normalized = String(text || "").replace(/\s+/g, " ").trim()
  if (!normalized) return ""
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength - 1).trimEnd()}...`
}

export function TicketTable({
  tickets,
  initialStatusFilter = "all",
  initialPriorityFilter = "all",
  initialTicketTypeFilter = "all",
  initialCategoryFilter = "all",
  initialSearch = "",
  minInactiveDays = 0,
}: TicketTableProps) {
  const { t, locale } = useI18n()
  const [search, setSearch] = useState(initialSearch)
  const [statusFilter, setStatusFilter] = useState<string>(initialStatusFilter)
  const [priorityFilter, setPriorityFilter] = useState<string>(initialPriorityFilter)
  const [ticketTypeFilter, setTicketTypeFilter] = useState<string>(initialTicketTypeFilter)
  const [categoryFilter, setCategoryFilter] = useState<string>(initialCategoryFilter)
  const [sortField, setSortField] = useState<"createdAt" | "priority">("createdAt")
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc")
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const [problemsById, setProblemsById] = useState<Record<string, ProblemListItem>>({})
  const [slaAdviceByTicket, setSlaAdviceByTicket] = useState<Record<string, TicketSlaAdvisory | null>>({})
  const [slaAdviceLoading, setSlaAdviceLoading] = useState<Record<string, boolean>>({})
  const isFr = locale === "fr"
  const linkedProblemIds = useMemo(
    () => Array.from(new Set(tickets.map((ticket) => ticket.problemId).filter(Boolean))) as string[],
    [tickets]
  )

  useEffect(() => {
    setStatusFilter(initialStatusFilter)
  }, [initialStatusFilter])

  useEffect(() => {
    setPriorityFilter(initialPriorityFilter)
  }, [initialPriorityFilter])

  useEffect(() => {
    setTicketTypeFilter(initialTicketTypeFilter)
  }, [initialTicketTypeFilter])

  useEffect(() => {
    setCategoryFilter(initialCategoryFilter)
  }, [initialCategoryFilter])

  useEffect(() => {
    setSearch(initialSearch)
  }, [initialSearch])

  useEffect(() => {
    setCurrentPage(1)
  }, [search, statusFilter, priorityFilter, ticketTypeFilter, categoryFilter, sortField, sortOrder, minInactiveDays, pageSize])

  useEffect(() => {
    if (linkedProblemIds.length === 0) {
      setProblemsById({})
      return
    }
    let mounted = true
    fetchProblems()
      .then((rows) => {
        if (!mounted) return
        const allowed = new Set(linkedProblemIds)
        const mapped: Record<string, ProblemListItem> = {}
        for (const row of rows) {
          if (allowed.has(row.id)) {
            mapped[row.id] = row
          }
        }
        setProblemsById(mapped)
      })
      .catch(() => {
        if (!mounted) return
        setProblemsById({})
      })
    return () => {
      mounted = false
    }
  }, [linkedProblemIds])

  async function onSlaPopoverOpenChange(ticketId: string, open: boolean) {
    if (!open) return
    if (ticketId in slaAdviceByTicket) return
    if (slaAdviceLoading[ticketId]) return

    setSlaAdviceLoading((prev) => ({ ...prev, [ticketId]: true }))
    try {
      const advisory = await fetchTicketSlaAdvisory(ticketId)
      setSlaAdviceByTicket((prev) => ({ ...prev, [ticketId]: advisory }))
    } catch {
      setSlaAdviceByTicket((prev) => ({ ...prev, [ticketId]: null }))
    } finally {
      setSlaAdviceLoading((prev) => ({ ...prev, [ticketId]: false }))
    }
  }

  const filteredTickets = useMemo(() => {
    let result = [...tickets]
    const normalizeSearchValue = (value: string) =>
      value
        .toLowerCase()
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()

    const ticketTypeAliases: Record<Ticket["ticketType"], string[]> = {
      incident: ["incident", "incidents"],
      service_request: ["service request", "service requests", "request", "requests", "demande de service", "demandes de service"],
    }

    const statusAliases: Record<Ticket["status"], string[]> = {
      open: [t("status.open"), "open", "opened"],
      "in-progress": [t("status.inProgress"), "in progress", "progress"],
      "waiting-for-customer": [t("status.waitingForCustomer"), "waiting customer", "customer waiting"],
      "waiting-for-support-vendor": [t("status.waitingForSupportVendor"), "waiting support vendor", "vendor waiting"],
      pending: [t("status.pending"), "pending"],
      resolved: [t("status.resolved"), "resolved"],
      closed: [t("status.closed"), "closed"],
    }

    const searchableTextForTicket = (ticket: Ticket) => {
      const parts = [
        ticket.title,
        ticket.description,
        ticket.id,
        ticket.reporter,
        ticket.assignee,
        ticket.dueAt || "",
        ticket.ticketType,
        ticket.ticketType.replace(/_/g, " "),
        ...ticketTypeAliases[ticket.ticketType],
        t(`type.${ticket.ticketType}` as "type.incident"),
        ticket.category,
        ticket.category.replace(/_/g, " "),
        t(`category.${ticket.category}` as "category.application"),
        ticket.priority,
        t(`priority.${ticket.priority}` as "priority.medium"),
        ticket.status,
        ...statusAliases[ticket.status],
        ...(ticket.tags || []),
      ]
      return normalizeSearchValue(parts.filter(Boolean).join(" "))
    }

    if (search) {
      const q = normalizeSearchValue(search)
      result = result.filter((ticket) => searchableTextForTicket(ticket).includes(q))
    }

    if (statusFilter === "resolved_or_closed") {
      result = result.filter((t) => t.status === "resolved" || t.status === "closed")
    } else if (statusFilter !== "all") {
      result = result.filter((t) => t.status === statusFilter)
    }

    if (priorityFilter !== "all") {
      result = result.filter((t) => t.priority === priorityFilter)
    }

    if (ticketTypeFilter !== "all") {
      result = result.filter((t) => t.ticketType === ticketTypeFilter)
    }

    if (categoryFilter !== "all") {
      result = result.filter((t) => t.category === categoryFilter)
    }

    if (minInactiveDays > 0) {
      result = result.filter(
        (t) =>
          ACTIVE_STATUSES.includes(t.status) &&
          inactiveDaysFrom(t.updatedAt) >= minInactiveDays
      )
    }

    const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 }
    result.sort((a, b) => {
      if (sortField === "priority") {
        const diff = priorityOrder[a.priority] - priorityOrder[b.priority]
        return sortOrder === "asc" ? diff : -diff
      }
      const diff = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      return sortOrder === "asc" ? diff : -diff
    })

    return result
  }, [tickets, search, statusFilter, priorityFilter, ticketTypeFilter, categoryFilter, minInactiveDays, sortField, sortOrder])

  function toggleSort(field: "createdAt" | "priority") {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc")
    } else {
      setSortField(field)
      setSortOrder("desc")
    }
  }

  const totalPages = Math.max(1, Math.ceil(filteredTickets.length / pageSize))
  const clampedPage = Math.min(currentPage, totalPages)

  useEffect(() => {
    if (currentPage !== clampedPage) {
      setCurrentPage(clampedPage)
    }
  }, [clampedPage, currentPage])

  const paginatedTickets = useMemo(() => {
    const start = (clampedPage - 1) * pageSize
    return filteredTickets.slice(start, start + pageSize)
  }, [clampedPage, filteredTickets, pageSize])
  const shownFrom = filteredTickets.length === 0 ? 0 : (clampedPage - 1) * pageSize + 1
  const shownTo = Math.min(filteredTickets.length, clampedPage * pageSize)

  const activeFilters: Array<{ key: string; label: string; clear: () => void; dismissible: boolean }> = []
  if (search.trim()) {
    activeFilters.push({
      key: `search-${search}`,
      label: `${isFr ? "Recherche" : "Search"}: ${search.trim()}`,
      clear: () => setSearch(""),
      dismissible: true,
    })
  }
  if (statusFilter !== "all") {
    const statusLabel =
      statusFilter === "resolved_or_closed"
        ? t("tickets.resolvedOrClosed")
        : STATUS_CONFIG[statusFilter as TicketStatus]?.label || statusFilter
    activeFilters.push({
      key: `status-${statusFilter}`,
      label: `${t("tickets.status")}: ${statusLabel}`,
      clear: () => setStatusFilter("all"),
      dismissible: true,
    })
  }
  if (priorityFilter !== "all") {
    const priorityLabel = PRIORITY_CONFIG[priorityFilter as TicketPriority]?.label || priorityFilter
    activeFilters.push({
      key: `priority-${priorityFilter}`,
      label: `${t("tickets.priority")}: ${priorityLabel}`,
      clear: () => setPriorityFilter("all"),
      dismissible: true,
    })
  }
  if (ticketTypeFilter !== "all") {
    activeFilters.push({
      key: `ticket-type-${ticketTypeFilter}`,
      label: `${t("tickets.type")}: ${t(`type.${ticketTypeFilter}` as "type.incident")}`,
      clear: () => setTicketTypeFilter("all"),
      dismissible: true,
    })
  }
  if (categoryFilter !== "all") {
    const categoryLabel = CATEGORY_CONFIG[categoryFilter as keyof typeof CATEGORY_CONFIG]?.label || categoryFilter
    activeFilters.push({
      key: `category-${categoryFilter}`,
      label: `${t("tickets.category")}: ${categoryLabel}`,
      clear: () => setCategoryFilter("all"),
      dismissible: true,
    })
  }
  if (minInactiveDays > 0) {
    activeFilters.push({
      key: `stale-${minInactiveDays}`,
      label: isFr ? `Inactifs >= ${minInactiveDays}j` : `Inactive >= ${minInactiveDays}d`,
      clear: () => {},
      dismissible: false,
    })
  }

  return (
    <TooltipProvider>
      <div className="space-y-4">
        {/* Filters */}
        <div className="surface-card rounded-2xl p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {isFr ? "Filtres" : "Filters"}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 rounded-lg px-3 text-xs"
              onClick={() => {
                setSearch("")
                setStatusFilter("all")
                setPriorityFilter("all")
                setTicketTypeFilter("all")
                setCategoryFilter("all")
              }}
              disabled={!activeFilters.some((item) => item.dismissible)}
            >
              {t("general.clear")}
            </Button>
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder={t("tickets.search")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 rounded-xl bg-background/70 pl-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-10 w-full rounded-xl bg-background/70 sm:w-44">
                <SelectValue placeholder={t("tickets.status")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("tickets.allStatuses")}</SelectItem>
                <SelectItem value="resolved_or_closed">{t("tickets.resolvedOrClosed")}</SelectItem>
                {Object.entries(STATUS_CONFIG).map(([key, val]) => (
                  <SelectItem key={key} value={key}>
                    {val.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={priorityFilter} onValueChange={setPriorityFilter}>
              <SelectTrigger className="h-10 w-full rounded-xl bg-background/70 sm:w-40">
                <SelectValue placeholder={t("tickets.priority")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("tickets.allPriorities")}</SelectItem>
                {Object.entries(PRIORITY_CONFIG).map(([key, val]) => (
                  <SelectItem key={key} value={key}>
                    {val.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={ticketTypeFilter} onValueChange={setTicketTypeFilter}>
              <SelectTrigger className="h-10 w-full rounded-xl bg-background/70 sm:w-44">
                <SelectValue placeholder={t("tickets.type")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("tickets.allTypes")}</SelectItem>
                <SelectItem value="incident">{t("type.incident")}</SelectItem>
                <SelectItem value="service_request">{t("type.service_request")}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="h-10 w-full rounded-xl bg-background/70 sm:w-48">
                <SelectValue placeholder={t("tickets.category")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("tickets.allCategories")}</SelectItem>
                {Object.entries(CATEGORY_CONFIG).map(([key, val]) => (
                  <SelectItem key={key} value={key}>
                    {val.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {activeFilters.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {activeFilters.map((filter) => (
                <Badge
                  key={filter.key}
                  variant="outline"
                  className="flex items-center gap-1 rounded-full border-border bg-background/80 px-2.5 py-1 text-[11px]"
                >
                  <span>{filter.label}</span>
                  {filter.dismissible && (
                    <button
                      type="button"
                      className="rounded-full p-0.5 transition-colors hover:bg-muted"
                      onClick={filter.clear}
                      aria-label={isFr ? "Retirer ce filtre" : "Remove filter"}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </Badge>
              ))}
            </div>
          )}
        </div>

        {/* Table */}
        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="max-h-[66vh] overflow-auto">
            <Table className="table-fixed min-w-[1450px]">
              <TableHeader className="sticky top-0 z-20 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/85">
                <TableRow className="border-b border-border/80 bg-muted/55 hover:bg-muted/55">
                  <TableHead className="w-24 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.id")}</TableHead>
                  <TableHead className="w-44 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">
                    {isFr ? "Lien probleme" : "Problem link"}
                  </TableHead>
                  <TableHead className="w-[24rem] px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.titleCol")}</TableHead>
                  <TableHead className="w-44 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.status")}</TableHead>
                  <TableHead className="w-32 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">SLA</TableHead>
                  <TableHead className="w-28 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 transition-colors hover:text-primary"
                      onClick={() => toggleSort("priority")}
                    >
                      {t("tickets.priority")}
                      <ArrowUpDown className="h-3.5 w-3.5" />
                    </button>
                  </TableHead>
                  <TableHead className="w-32 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.type")}</TableHead>
                  <TableHead className="w-32 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.category")}</TableHead>
                  <TableHead className="w-36 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.assignee")}</TableHead>
                  <TableHead className="w-36 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.reporter")}</TableHead>
                  <TableHead className="w-28 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 transition-colors hover:text-primary"
                      onClick={() => toggleSort("createdAt")}
                    >
                      {t("tickets.date")}
                      <ArrowUpDown className="h-3.5 w-3.5" />
                    </button>
                  </TableHead>
                  <TableHead className="w-12 px-3 py-3" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedTickets.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={12} className="py-14 text-center">
                      <div className="mx-auto max-w-md rounded-xl border border-dashed border-border/70 bg-muted/20 p-6">
                        <p className="text-sm font-medium text-foreground">{t("tickets.noResults")}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {isFr ? "Essayez de modifier les filtres ou la recherche." : "Try adjusting filters or search terms."}
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedTickets.map((ticket, index) => {
                    const linkedProblem = ticket.problemId ? problemsById[ticket.problemId] : undefined
                    const slaStatus = (ticket.slaStatus || null) as SlaStatus | null
                    const slaConfig = slaStatus ? SLA_STATUS_CONFIG[slaStatus] : null
                    const hasSlaPopup = slaStatus !== null && slaStatus !== "unknown"
                    const advisory = slaAdviceByTicket[ticket.id]
                    const advisoryLoading = Boolean(slaAdviceLoading[ticket.id])
                    const clockClass =
                      slaStatus === "breached"
                        ? "text-red-600"
                        : slaStatus === "at_risk"
                          ? "text-amber-500"
                          : "text-slate-500"
                    const remainingLabel = advisory
                      ? formatRemainingSlaSeconds(advisory.remainingSeconds, { isFr })
                      : formatRemainingSla(ticket.slaRemainingMinutes, { isFr })
                    const remainingSeconds = advisory
                      ? Number(advisory.remainingSeconds)
                      : Number.isFinite(ticket.slaRemainingMinutes)
                        ? Math.max(0, Math.floor(Number(ticket.slaRemainingMinutes) * 60))
                        : null
                    const isUrgentCountdown =
                      (slaStatus === "at_risk" || slaStatus === "breached") &&
                      Number.isFinite(remainingSeconds) &&
                      Number(remainingSeconds) > 0 &&
                      Number(remainingSeconds) <= 900
                    return (
                      <TableRow
                        key={ticket.id}
                        className={`group border-b border-border/30 ${index % 2 === 0 ? "bg-background/65" : "bg-muted/20"} transition-all duration-100 hover:shadow-[inset_3px_0_0_rgba(29,158,117,0.4)] ${slaStatus === "breached" ? "shadow-[inset_3px_0_0_#E24B4A]" : slaStatus === "at_risk" ? "border-l-[3px] border-l-[#EF9F27]" : ""}`}
                      >
                        <TableCell className="px-3 py-3">
                          <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-[var(--color-background-secondary)] border border-[var(--color-border-tertiary)] hover:border-[var(--color-border-primary)] cursor-pointer transition-all duration-150 font-semibold text-primary">
                            {ticket.id}
                          </span>
                        </TableCell>
                        <TableCell className="px-3 py-3">
                          {ticket.problemId ? (
                            <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-red-200/70 bg-red-50/70 px-2 py-1 dark:border-red-500/30 dark:bg-red-950/30">
                              <Link2 className="h-3 w-3 text-red-700 dark:text-red-200" />
                              <Link
                                href={`/problems/${ticket.problemId}`}
                                className="truncate font-mono text-[11px] font-semibold text-red-700 transition-colors hover:text-red-800 dark:text-red-100 dark:hover:text-red-50"
                              >
                                {ticket.problemId}
                              </Link>
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="px-3 py-3">
                          {ticket.problemId ? (
                            <HoverCard openDelay={120} closeDelay={80}>
                              <HoverCardTrigger asChild>
                                <Link
                                  href={`/tickets/${ticket.id}`}
                                  className="block truncate text-sm font-medium text-foreground transition-colors hover:text-primary"
                                >
                                  {ticket.title}
                                </Link>
                              </HoverCardTrigger>
                              <HoverCardContent align="start" className="w-80 p-3">
                                <p className="text-xs font-semibold text-foreground">
                                  {isFr ? "Ticket lie a un probleme" : "Ticket linked to a problem"}
                                </p>
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {isFr ? "Probleme associe:" : "Linked problem:"}{" "}
                                  <span className="font-mono font-semibold text-foreground">{ticket.problemId}</span>
                                </p>
                                {linkedProblem ? (
                                  <>
                                    <p className="mt-2 line-clamp-2 text-xs font-medium text-foreground">{linkedProblem.title}</p>
                                    <div className="mt-2 flex flex-wrap items-center gap-2">
                                      <Badge className={`${PROBLEM_STATUS_CONFIG[linkedProblem.status].color} border-0 text-[10px]`}>
                                        {isFr ? PROBLEM_STATUS_CONFIG[linkedProblem.status].labelFr : PROBLEM_STATUS_CONFIG[linkedProblem.status].labelEn}
                                      </Badge>
                                      <Badge variant="outline" className="border-border bg-background/70 text-[10px] text-muted-foreground">
                                        {CATEGORY_CONFIG[linkedProblem.category].label}
                                      </Badge>
                                    </div>
                                  </>
                                ) : (
                                  <p className="mt-2 text-xs text-muted-foreground">
                                    {isFr ? "Chargement des details du probleme..." : "Loading problem details..."}
                                  </p>
                                )}
                                <div className="mt-2">
                                  <Link
                                    href={`/problems/${ticket.problemId}`}
                                    className="inline-flex rounded-md border border-red-300 bg-red-50 px-2.5 py-1 text-[11px] font-semibold text-red-700 transition-colors hover:bg-red-100 dark:border-red-500/40 dark:bg-red-950/40 dark:text-red-100 dark:hover:bg-red-900/50"
                                  >
                                    {isFr ? "Voir probleme" : "View problem"}
                                  </Link>
                                </div>
                              </HoverCardContent>
                            </HoverCard>
                          ) : (
                            <HoverCard openDelay={120} closeDelay={80}>
                              <HoverCardTrigger asChild>
                                <Link
                                  href={`/tickets/${ticket.id}`}
                                  className="block truncate text-sm font-medium text-foreground transition-colors hover:text-primary"
                                >
                                  {ticket.title}
                                </Link>
                              </HoverCardTrigger>
                              <HoverCardContent align="start" className="w-80 p-3">
                                <p className="line-clamp-2 text-sm font-semibold text-foreground">{ticket.title}</p>
                                <div className="mt-2 grid grid-cols-2 gap-2">
                                  <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                    <p className="text-[10px] text-muted-foreground">{isFr ? "Statut" : "Status"}</p>
                                    <p className="text-xs font-semibold text-foreground">{STATUS_CONFIG[ticket.status].label}</p>
                                  </div>
                                  <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                    <p className="text-[10px] text-muted-foreground">{isFr ? "Priorite" : "Priority"}</p>
                                    <p className="text-xs font-semibold text-foreground">{PRIORITY_CONFIG[ticket.priority].label}</p>
                                  </div>
                                  <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                    <p className="text-[10px] text-muted-foreground">{t("tickets.type")}</p>
                                    <p className="text-xs font-semibold text-foreground">
                                      {t(`type.${ticket.ticketType}` as "type.incident")}
                                    </p>
                                  </div>
                                  <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                    <p className="text-[10px] text-muted-foreground">{isFr ? "Categorie" : "Category"}</p>
                                    <p className="text-xs font-semibold text-foreground">{CATEGORY_CONFIG[ticket.category].label}</p>
                                  </div>
                                  <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                    <p className="text-[10px] text-muted-foreground">{isFr ? "Assigne" : "Assignee"}</p>
                                    <p className="truncate text-xs font-semibold text-foreground">{ticket.assignee}</p>
                                  </div>
                                  {ticket.dueAt ? (
                                    <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                      <p className="text-[10px] text-muted-foreground">{isFr ? "Echeance" : "Deadline"}</p>
                                      <p className="text-xs font-semibold text-foreground">
                                        {new Date(ticket.dueAt).toLocaleDateString(isFr ? "fr-FR" : "en-US")}
                                      </p>
                                    </div>
                                  ) : null}
                                </div>
                                {slaStatus && slaConfig ? (
                                  <div className="mt-2 rounded-md border border-border/70 bg-muted/20 p-2">
                                    <p className="text-[10px] text-muted-foreground">SLA</p>
                                    <div className="mt-1 flex items-center gap-2">
                                      <Badge className={`${slaConfig.color} border-0 text-[10px] font-semibold`}>
                                        {isFr ? slaConfig.labelFr : slaConfig.labelEn}
                                      </Badge>
                                      <span className="text-[11px] text-muted-foreground">{remainingLabel}</span>
                                    </div>
                                  </div>
                                ) : null}
                              </HoverCardContent>
                            </HoverCard>
                          )}
                        </TableCell>
                        <TableCell className="overflow-hidden px-3 py-3">
                          <Badge
                            className={`${STATUS_CONFIG[ticket.status].color} max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-0 text-xs font-semibold`}
                            title={STATUS_CONFIG[ticket.status].label}
                          >
                            {STATUS_CONFIG[ticket.status].label}
                          </Badge>
                        </TableCell>
                        <TableCell className="overflow-hidden px-3 py-3">
                          {slaStatus && slaConfig ? (
                            hasSlaPopup ? (
                              <Popover onOpenChange={(open) => onSlaPopoverOpenChange(ticket.id, open)}>
                                <PopoverTrigger asChild>
                                  <button
                                    type="button"
                                    className="inline-flex max-w-full items-center gap-1 rounded-md px-1 py-0.5 transition-colors hover:bg-muted/50"
                                  >
                                    <Clock className={`h-3.5 w-3.5 ${isUrgentCountdown ? "animate-pulse" : ""} ${clockClass}`} />
                                    <Badge
                                      className={`${slaConfig.color} max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-0 text-xs font-semibold`}
                                      title={isFr ? slaConfig.labelFr : slaConfig.labelEn}
                                    >
                                      {isFr ? slaConfig.labelFr : slaConfig.labelEn}
                                    </Badge>
                                  </button>
                                </PopoverTrigger>
                                <PopoverContent align="start" className="w-80 p-3">
                                  <p className="text-xs font-semibold text-foreground">SLA</p>
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {isFr ? slaConfig.hintFr : slaConfig.hintEn}
                                  </p>
                                  <div className="mt-2 grid grid-cols-2 gap-2">
                                    <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                      <p className="text-[10px] text-muted-foreground">{isFr ? "Statut" : "Status"}</p>
                                      <p className="text-xs font-semibold text-foreground">{isFr ? slaConfig.labelFr : slaConfig.labelEn}</p>
                                    </div>
                                    <div className="rounded-md border border-border/70 bg-muted/30 p-2">
                                      <p className="text-[10px] text-muted-foreground">{isFr ? "Temps restant" : "Remaining"}</p>
                                      <p className="text-xs font-semibold text-foreground">
                                        {remainingLabel}
                                      </p>
                                    </div>
                                  </div>
                                  <div className="mt-2 rounded-md border border-border/70 bg-muted/20 p-2">
                                    <p className="text-[10px] text-muted-foreground">{isFr ? "Quick Advice (RAG)" : "Quick Advice (RAG)"}</p>
                                    <p className="mt-1 text-xs text-foreground">
                                      {advisoryLoading
                                        ? isFr
                                          ? "Chargement du conseil SLA..."
                                          : "Loading SLA advice..."
                                        : advisory?.ragAdviceText
                                          ? advisorySnippet(advisory.ragAdviceText)
                                          : isFr
                                            ? "Aucun conseil SLA disponible."
                                            : "No SLA advisory available."}
                                    </p>
                                  </div>
                                  <p className="mt-2 text-[11px] text-muted-foreground">
                                    {isFr ? "Derniere mise a jour:" : "Last update:"}{" "}
                                    {new Date(ticket.updatedAt).toLocaleString(locale === "fr" ? "fr-FR" : "en-US")}
                                  </p>
                                </PopoverContent>
                              </Popover>
                            ) : (
                              <Badge
                                className={`${slaConfig.color} max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-0 text-xs font-semibold`}
                                title={isFr ? slaConfig.labelFr : slaConfig.labelEn}
                              >
                                {isFr ? slaConfig.labelFr : slaConfig.labelEn}
                              </Badge>
                            )
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="overflow-hidden px-3 py-3">
                          <Badge
                            className={`${PRIORITY_CONFIG[ticket.priority].color} max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-0 rounded-none text-[10px] font-semibold uppercase tracking-[0.04em]`}
                            title={PRIORITY_CONFIG[ticket.priority].label}
                          >
                            {PRIORITY_CONFIG[ticket.priority].label}
                          </Badge>
                        </TableCell>
                        <TableCell className="overflow-hidden px-3 py-3">
                          <Badge
                            variant="outline"
                            className="max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-border bg-background/70 text-muted-foreground"
                            title={TICKET_TYPE_CONFIG[ticket.ticketType].label}
                          >
                            {t(`type.${ticket.ticketType}` as "type.incident")}
                          </Badge>
                        </TableCell>
                        <TableCell className="overflow-hidden px-3 py-3">
                          <Badge
                            variant="outline"
                            className={
                              ticket.category === "problem"
                                ? "max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-red-300 bg-red-50 text-red-700 dark:border-red-500/40 dark:bg-red-950/40 dark:text-red-100"
                                : "max-w-full overflow-hidden text-ellipsis whitespace-nowrap border-border bg-background/70 text-muted-foreground"
                            }
                            title={CATEGORY_CONFIG[ticket.category].label}
                          >
                            {CATEGORY_CONFIG[ticket.category].label}
                          </Badge>
                        </TableCell>
                        <TableCell className="px-3 py-3 text-sm text-foreground">
                          <TruncatedText value={ticket.assignee} />
                        </TableCell>
                        <TableCell className="px-3 py-3 text-sm text-foreground">
                          <TruncatedText value={ticket.reporter} />
                        </TableCell>
                        <TableCell className="px-3 py-3 text-xs text-muted-foreground">
                          {new Date(ticket.createdAt).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })}
                        </TableCell>
                        <TableCell className="px-3 py-3">
                          <div className="flex items-center justify-end gap-1">
                            <div className="pointer-events-none flex items-center gap-1 opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100">
                              <Link href={`/tickets/${ticket.id}?focus=assignee`}>
                                <Button variant="ghost" size="sm" className="h-8 w-8 rounded-full p-0 hover:bg-primary/10">
                                  <User className="h-3.5 w-3.5" />
                                  <span className="sr-only">
                                    {isFr ? `Action rapide: assigner ${ticket.id}` : `Quick action: assign ${ticket.id}`}
                                  </span>
                                </Button>
                              </Link>
                              <Link href={`/tickets/${ticket.id}?focus=priority`}>
                                <Button variant="ghost" size="sm" className="h-8 w-8 rounded-full p-0 hover:bg-primary/10">
                                  <AlertTriangle className="h-3.5 w-3.5" />
                                  <span className="sr-only">
                                    {isFr ? `Action rapide: prioriser ${ticket.id}` : `Quick action: prioritize ${ticket.id}`}
                                  </span>
                                </Button>
                              </Link>
                            </div>
                            <Link href={`/tickets/${ticket.id}`}>
                              <Button variant="ghost" size="sm" className="h-8 w-8 rounded-full p-0 hover:bg-primary/10">
                                <ExternalLink className="h-3.5 w-3.5" />
                                <span className="sr-only">Voir le ticket {ticket.id}</span>
                              </Button>
                            </Link>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </Card>

        <div className="surface-card flex flex-col gap-3 rounded-2xl p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-muted-foreground">
            {filteredTickets.length === 0
              ? `${filteredTickets.length} ${t("tickets.shown")}`
              : `${shownFrom}-${shownTo} / ${filteredTickets.length} ${t("tickets.shown")}`}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs text-muted-foreground">{isFr ? "Lignes/page" : "Rows/page"}</p>
            <Select
              value={String(pageSize)}
              onValueChange={(value) => {
                const parsed = Number(value)
                if (Number.isFinite(parsed) && parsed > 0) setPageSize(parsed)
              }}
            >
              <SelectTrigger className="h-9 w-24 rounded-xl bg-background/70">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10</SelectItem>
                <SelectItem value="20">20</SelectItem>
                <SelectItem value="50">50</SelectItem>
              </SelectContent>
            </Select>

            <div className="mx-1 h-5 w-px bg-border/70" />

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl px-3"
              onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
              disabled={clampedPage <= 1}
            >
              {isFr ? "Precedent" : "Previous"}
            </Button>
            <Badge variant="outline" className="h-9 rounded-xl border-border bg-background/80 px-3 text-xs">
              {isFr ? `Page ${clampedPage} / ${totalPages}` : `Page ${clampedPage} / ${totalPages}`}
            </Badge>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl px-3"
              onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
              disabled={clampedPage >= totalPages}
            >
              {isFr ? "Suivant" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

function TruncatedText({ value }: { value: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="block truncate">{value}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">{value}</TooltipContent>
    </Tooltip>
  )
}
