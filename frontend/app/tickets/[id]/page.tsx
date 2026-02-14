"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { TicketDetail } from "@/components/ticket-detail"
import { type Ticket } from "@/lib/ticket-data"
import { fetchTicket } from "@/lib/tickets-api"
import { useI18n } from "@/lib/i18n"

export default function TicketDetailPage() {
  const params = useParams()
  const ticketId = params.id as string
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(true)
  const { t } = useI18n()

  useEffect(() => {
    fetchTicket(ticketId)
      .then(setTicket)
      .catch(() => setTicket(null))
      .finally(() => setLoading(false))
  }, [ticketId])

  if (loading) {
    return (
      <AppShell>
        <div className="flex h-[60vh] flex-col items-center justify-center">
          <p className="text-lg font-semibold text-foreground">{t("general.loading")}</p>
        </div>
      </AppShell>
    )
  }

  if (!ticket) {
    return (
      <AppShell>
        <div className="flex h-[60vh] flex-col items-center justify-center">
          <p className="text-lg font-semibold text-foreground">{t("detail.notFound")}</p>
          <p className="text-sm text-muted-foreground mt-1">
            {t("detail.notFoundDesc", { id: ticketId })}
          </p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("tickets.view")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {ticket.id}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">{ticket.title}</p>
        </div>
        <TicketDetail ticket={ticket} />
      </div>
    </AppShell>
  )
}
