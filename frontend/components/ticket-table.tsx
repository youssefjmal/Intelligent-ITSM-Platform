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
import { Search, ArrowUpDown, ExternalLink } from "lucide-react"
import {
  type Ticket,
  type TicketStatus,
  type TicketPriority,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"

interface TicketTableProps {
  tickets: Ticket[]
  initialStatusFilter?: string
  initialPriorityFilter?: string
  initialCategoryFilter?: string
  minInactiveDays?: number
}

const ACTIVE_STATUSES: TicketStatus[] = ["open", "in-progress", "pending"]

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

  useEffect(() => {
    setStatusFilter(initialStatusFilter)
  }, [initialStatusFilter])

  useEffect(() => {
    setPriorityFilter(initialPriorityFilter)
  }, [initialPriorityFilter])

  useEffect(() => {
    setCategoryFilter(initialCategoryFilter)
  }, [initialCategoryFilter])

  const filteredTickets = useMemo(() => {
    let result = [...tickets]

    if (search) {
      const q = search.toLowerCase()
      result = result.filter(
        (t) =>
          t.title.toLowerCase().includes(q) ||
          t.id.toLowerCase().includes(q) ||
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

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="surface-card rounded-xl p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("tickets.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-40">
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
          <SelectTrigger className="w-full sm:w-40">
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
          <SelectTrigger className="w-full sm:w-44">
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
      </div>

      {/* Table */}
      <Card className="surface-card overflow-hidden rounded-2xl">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="w-24 text-foreground font-semibold">{t("tickets.id")}</TableHead>
                <TableHead className="text-foreground font-semibold">{t("tickets.titleCol")}</TableHead>
                <TableHead className="text-foreground font-semibold">{t("tickets.status")}</TableHead>
                <TableHead className="text-foreground font-semibold">
                  <button
                    type="button"
                    className="flex items-center gap-1 hover:text-primary transition-colors"
                    onClick={() => toggleSort("priority")}
                  >
                    {t("tickets.priority")}
                    <ArrowUpDown className="h-3.5 w-3.5" />
                  </button>
                </TableHead>
                <TableHead className="text-foreground font-semibold">{t("tickets.category")}</TableHead>
                <TableHead className="text-foreground font-semibold">{t("tickets.assignee")}</TableHead>
                <TableHead className="text-foreground font-semibold">
                  <button
                    type="button"
                    className="flex items-center gap-1 hover:text-primary transition-colors"
                    onClick={() => toggleSort("createdAt")}
                  >
                    {t("tickets.date")}
                    <ArrowUpDown className="h-3.5 w-3.5" />
                  </button>
                </TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTickets.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-12 text-center text-muted-foreground">
                    {t("tickets.noResults")}
                  </TableCell>
                </TableRow>
              ) : (
                filteredTickets.map((ticket) => (
                  <TableRow key={ticket.id} className="transition-colors hover:bg-muted/30">
                    <TableCell className="font-mono text-xs font-medium text-primary">
                      {ticket.id}
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <Link
                        href={`/tickets/${ticket.id}`}
                        className="font-medium text-foreground hover:text-primary transition-colors line-clamp-1"
                      >
                        {ticket.title}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={`${STATUS_CONFIG[ticket.status].color} border-0 text-xs font-medium`}
                      >
                        {STATUS_CONFIG[ticket.status].label}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={`${PRIORITY_CONFIG[ticket.priority].color} border-0 text-xs font-medium`}
                      >
                        {PRIORITY_CONFIG[ticket.priority].label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {CATEGORY_CONFIG[ticket.category].label}
                    </TableCell>
                    <TableCell className="text-sm text-foreground">
                      {ticket.assignee}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(ticket.createdAt).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </TableCell>
                    <TableCell>
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

      <p className="text-xs text-muted-foreground text-right">
        {filteredTickets.length} {t("tickets.shown")}
      </p>
    </div>
  )
}
