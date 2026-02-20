"use client"

import { useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { TicketTable } from "@/components/ticket-table"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { PlusCircle } from "lucide-react"
import Link from "next/link"
import { type Ticket } from "@/lib/ticket-data"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { fetchTickets } from "@/lib/tickets-api"

export default function TicketsPage() {
  const { hasPermission } = useAuth()
  const { t } = useI18n()
  const searchParams = useSearchParams()
  const [tickets, setTickets] = useState<Ticket[]>([])

  useEffect(() => {
    fetchTickets().then(setTickets).catch(() => {})
  }, [])

  const view = (searchParams.get("view") || "").toLowerCase()
  const focusConfig = (() => {
    if (view === "in-progress") {
      return {
        label: t("tickets.focusInProgress"),
        status: "in-progress",
        priority: "all",
        category: "all",
        staleDays: 0,
      }
    }
    if (view === "resolved") {
      return {
        label: t("tickets.focusResolved"),
        status: "resolved_or_closed",
        priority: "all",
        category: "all",
        staleDays: 0,
      }
    }
    if (view === "critical") {
      return {
        label: t("tickets.focusCritical"),
        status: "all",
        priority: "critical",
        category: "all",
        staleDays: 0,
      }
    }
    if (view === "problem") {
      return {
        label: t("tickets.focusProblem"),
        status: "all",
        priority: "all",
        category: "problem",
        staleDays: 0,
      }
    }
    if (view === "stale") {
      return {
        label: t("tickets.focusStale"),
        status: "all",
        priority: "all",
        category: "all",
        staleDays: 5,
      }
    }
    if (view === "avg-time") {
      return {
        label: t("tickets.focusAvgTime"),
        status: "resolved_or_closed",
        priority: "all",
        category: "all",
        staleDays: 0,
      }
    }
    if (view === "resolution-rate") {
      return {
        label: t("tickets.focusResolutionRate"),
        status: "resolved_or_closed",
        priority: "all",
        category: "all",
        staleDays: 0,
      }
    }
    if (view === "total") {
      return {
        label: t("tickets.focusTotal"),
        status: "all",
        priority: "all",
        category: "all",
        staleDays: 0,
      }
    }
    return null
  })()

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="section-caption">{t("nav.tickets")}</p>
              <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
                {t("tickets.title")}
              </h2>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
                {t("tickets.subtitle")}
              </p>
            </div>
            {hasPermission("create_ticket") && (
              <Link href="/tickets/new">
                <Button className="h-11 gap-2 rounded-xl bg-primary px-5 text-primary-foreground shadow-sm hover:bg-primary/90">
                  <PlusCircle className="h-4 w-4" />
                  {t("tickets.new")}
                </Button>
              </Link>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between rounded-xl border border-border/70 bg-card/70 px-4 py-3">
          <p className="text-sm font-medium text-muted-foreground">{t("tickets.search")}</p>
          <p className="text-xs text-muted-foreground">
            {t("tickets.title")}
          </p>
        </div>

        {focusConfig && (
          <div className="surface-card flex items-center justify-between rounded-xl px-3 py-2.5">
            <Badge variant="secondary" className="border border-border/60 bg-secondary/80 text-xs">
              {focusConfig.label}
            </Badge>
            <Link href="/tickets">
              <Button variant="ghost" size="sm" className="h-8 rounded-lg text-xs">
                {t("general.clear")}
              </Button>
            </Link>
          </div>
        )}

        <TicketTable
          tickets={tickets}
          initialStatusFilter={focusConfig?.status ?? "all"}
          initialPriorityFilter={focusConfig?.priority ?? "all"}
          initialCategoryFilter={focusConfig?.category ?? "all"}
          minInactiveDays={focusConfig?.staleDays ?? 0}
        />
      </div>
    </AppShell>
  )
}
