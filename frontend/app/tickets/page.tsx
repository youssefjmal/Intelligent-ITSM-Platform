"use client"

import { useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { TicketTable } from "@/components/ticket-table"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import Link from "next/link"
import { type Ticket } from "@/lib/ticket-data"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { fetchTickets } from "@/lib/tickets-api"
import { ApiError } from "@/lib/api"

export default function TicketsPage() {
  const { user } = useAuth()
  const { t, locale } = useI18n()
  const searchParams = useSearchParams()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loadState, setLoadState] = useState<"loading" | "ready" | "auth" | "error">("loading")

  useEffect(() => {
    let mounted = true
    setLoadState("loading")
    fetchTickets()
      .then((rows) => {
        if (!mounted) return
        setTickets(rows)
        setLoadState("ready")
      })
      .catch((error) => {
        if (!mounted) return
        setTickets([])
        if (error instanceof ApiError && error.status === 401) {
          setLoadState("auth")
          return
        }
        setLoadState("error")
      })
    return () => {
      mounted = false
    }
  }, [])

  const view = (searchParams.get("view") || "").toLowerCase()
  const ticketTypeParam = (searchParams.get("ticketType") || "").toLowerCase()
  const initialSearch = searchParams.get("q") || ""
  const resolvedTicketType =
    view === "incident"
      ? "incident"
      : view === "service-request" || view === "service_request"
        ? "service_request"
        : ticketTypeParam === "incident"
          ? "incident"
          : ticketTypeParam === "service-request" || ticketTypeParam === "service_request"
            ? "service_request"
            : "all"
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
    if (view === "mine") {
      return {
        label: locale === "fr" ? "Assignes a moi" : "Assigned to me",
        status: "all",
        priority: "all",
        category: "all",
        assignedToMe: true,
        staleDays: 0,
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
        ticketType: "all",
        category: "all",
        staleDays: 0,
      }
    }
    if (resolvedTicketType === "incident") {
      return {
        label: ticketTypeFocusLabel("incident", t),
        status: "all",
        priority: "all",
        ticketType: "incident",
        category: "all",
        staleDays: 0,
      }
    }
    if (resolvedTicketType === "service_request") {
      return {
        label: ticketTypeFocusLabel("service_request", t),
        status: "all",
        priority: "all",
        ticketType: "service_request",
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
          loadState={loadState}
          initialStatusFilter={focusConfig?.status ?? "all"}
          initialPriorityFilter={focusConfig?.priority ?? "all"}
          initialTicketTypeFilter={focusConfig?.ticketType ?? resolvedTicketType}
          initialCategoryFilter={focusConfig?.category ?? "all"}
          initialAssignedToMe={focusConfig?.assignedToMe ?? false}
          initialSearch={initialSearch}
          minInactiveDays={focusConfig?.staleDays ?? 0}
          currentUser={user ? { name: user.name, email: user.email } : null}
        />
      </div>
    </AppShell>
  )
}

function ticketTypeFocusLabel(
  ticketType: "incident" | "service_request",
  t: (key: "type.incident" | "type.service_request") => string
): string {
  if (ticketType === "incident") {
    return t("type.incident")
  }
  return t("type.service_request")
}
