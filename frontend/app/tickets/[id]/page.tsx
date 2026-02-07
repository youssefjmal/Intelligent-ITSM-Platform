"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { TicketDetail } from "@/components/ticket-detail"
import { type Ticket } from "@/lib/ticket-data"
import { fetchTicket } from "@/lib/tickets-api"

export default function TicketDetailPage() {
  const params = useParams()
  const ticketId = params.id as string
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchTicket(ticketId)
      .then(setTicket)
      .catch(() => setTicket(null))
      .finally(() => setLoading(false))
  }, [ticketId])

  if (loading) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center h-[60vh]">
          <p className="text-lg font-semibold text-foreground">Chargement...</p>
        </div>
      </AppShell>
    )
  }

  if (!ticket) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center h-[60vh]">
          <p className="text-lg font-semibold text-foreground">Ticket non trouve</p>
          <p className="text-sm text-muted-foreground mt-1">
            Le ticket {ticketId} n'existe pas ou a ete supprime.
          </p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <TicketDetail ticket={ticket} />
    </AppShell>
  )
}
