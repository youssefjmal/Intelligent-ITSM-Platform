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
import { Search, ArrowUpDown, ExternalLink, X } from "lucide-react"
import {
  type Ticket,
  type TicketStatus,
  type TicketPriority,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

interface TicketTableProps {
  tickets: Ticket[]
  initialStatusFilter?: string
  initialPriorityFilter?: string
  initialCategoryFilter?: string
  minInactiveDays?: number
}

const ACTIVE_STATUSES: TicketStatus[] = [
  "open",
  "in-progress",
  "waiting-for-customer",
  "waiting-for-support-vendor",
  "pending",
]

function inactiveDaysFrom(dateValue: string): number {
  const now = Date.now()
  const date = new Date(dateValue).getTime()
  if (Number.isNaN(date)) return 0
  return Math.max(0, Math.floor((now - date) / (1000 * 60 * 60 * 24)))
}

export function TicketTable({
  tickets,
  initialStatusFilter = "all",
  initialPriorityFilter = "all",
  initialCategoryFilter = "all",
  minInactiveDays = 0,
}: TicketTableProps) {
  const { t, locale } = useI18n()
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>(initialStatusFilter)
  const [priorityFilter, setPriorityFilter] = useState<string>(initialPriorityFilter)
  const [categoryFilter, setCategoryFilter] = useState<string>(initialCategoryFilter)
  const [sortField, setSortField] = useState<"createdAt" | "priority">("createdAt")
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc")
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const isFr = locale === "fr"

  useEffect(() => {
    setStatusFilter(initialStatusFilter)
  }, [initialStatusFilter])

  useEffect(() => {
    setPriorityFilter(initialPriorityFilter)
  }, [initialPriorityFilter])

  useEffect(() => {
    setCategoryFilter(initialCategoryFilter)
  }, [initialCategoryFilter])

  useEffect(() => {
    setCurrentPage(1)
  }, [search, statusFilter, priorityFilter, categoryFilter, sortField, sortOrder, minInactiveDays, pageSize])

  const filteredTickets = useMemo(() => {
    let result = [...tickets]

    if (search) {
      const q = search.toLowerCase()
      result = result.filter(
        (t) =>
          t.title.toLowerCase().includes(q) ||
          t.id.toLowerCase().includes(q) ||
          t.reporter.toLowerCase().includes(q) ||
          t.assignee.toLowerCase().includes(q)
      )
    }

    if (statusFilter === "resolved_or_closed") {
      result = result.filter((t) => t.status === "resolved" || t.status === "closed")
    } else if (statusFilter !== "all") {
      result = result.filter((t) => t.status === statusFilter)
    }

    if (priorityFilter !== "all") {
      result = result.filter((t) => t.priority === priorityFilter)
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
  }, [tickets, search, statusFilter, priorityFilter, categoryFilter, minInactiveDays, sortField, sortOrder])

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
            <Table className="min-w-[980px]">
              <TableHeader className="sticky top-0 z-20 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/85">
                <TableRow className="border-b border-border/80 bg-muted/55 hover:bg-muted/55">
                  <TableHead className="w-24 px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.id")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.titleCol")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.status")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 transition-colors hover:text-primary"
                      onClick={() => toggleSort("priority")}
                    >
                      {t("tickets.priority")}
                      <ArrowUpDown className="h-3.5 w-3.5" />
                    </button>
                  </TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.category")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.assignee")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">{t("tickets.reporter")}</TableHead>
                  <TableHead className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-foreground">
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
                    <TableCell colSpan={9} className="py-14 text-center">
                      <div className="mx-auto max-w-md rounded-xl border border-dashed border-border/70 bg-muted/20 p-6">
                        <p className="text-sm font-medium text-foreground">{t("tickets.noResults")}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {isFr ? "Essayez de modifier les filtres ou la recherche." : "Try adjusting filters or search terms."}
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedTickets.map((ticket, index) => (
                    <TableRow key={ticket.id} className={`${index % 2 === 0 ? "bg-background/65" : "bg-muted/20"} transition-colors hover:bg-primary/5`}>
                      <TableCell className="px-3 py-3 font-mono text-xs font-semibold text-primary">
                        {ticket.id}
                      </TableCell>
                      <TableCell className="max-w-[24rem] px-3 py-3">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Link
                              href={`/tickets/${ticket.id}`}
                              className="block truncate text-sm font-medium text-foreground transition-colors hover:text-primary"
                            >
                              {ticket.title}
                            </Link>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-sm text-xs">{ticket.title}</TooltipContent>
                        </Tooltip>
                      </TableCell>
                      <TableCell className="px-3 py-3">
                        <Badge
                          className={`${STATUS_CONFIG[ticket.status].color} border-0 text-xs font-semibold`}
                        >
                          {STATUS_CONFIG[ticket.status].label}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-3 py-3">
                        <Badge
                          className={`${PRIORITY_CONFIG[ticket.priority].color} border-0 text-xs font-semibold`}
                        >
                          {PRIORITY_CONFIG[ticket.priority].label}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-3 py-3 text-sm text-muted-foreground">
                        {CATEGORY_CONFIG[ticket.category].label}
                      </TableCell>
                      <TableCell className="max-w-[12rem] px-3 py-3 text-sm text-foreground">
                        <TruncatedText value={ticket.assignee} />
                      </TableCell>
                      <TableCell className="max-w-[12rem] px-3 py-3 text-sm text-foreground">
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
                        <Link href={`/tickets/${ticket.id}`}>
                          <Button variant="ghost" size="sm" className="h-8 w-8 rounded-full p-0 hover:bg-primary/10">
                            <ExternalLink className="h-3.5 w-3.5" />
                            <span className="sr-only">Voir le ticket {ticket.id}</span>
                          </Button>
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))
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
