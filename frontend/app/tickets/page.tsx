"use client"

import { useEffect, useState } from "react"
import { AppShell } from "@/components/app-shell"
import { TicketTable } from "@/components/ticket-table"
import { Button } from "@/components/ui/button"
import { PlusCircle } from "lucide-react"
import Link from "next/link"
import { type Ticket } from "@/lib/ticket-data"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { fetchTickets } from "@/lib/tickets-api"

export default function TicketsPage() {
  const { hasPermission } = useAuth()
  const { t } = useI18n()
  const [tickets, setTickets] = useState<Ticket[]>([])

  useEffect(() => {
    fetchTickets().then(setTickets).catch(() => {})
  }, [])

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-foreground text-balance">
              {t("tickets.title")}
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              {t("tickets.subtitle")}
            </p>
          </div>
          {hasPermission("create_ticket") && (
            <Link href="/tickets/new">
              <Button className="bg-primary text-primary-foreground hover:bg-primary/90 gap-2">
                <PlusCircle className="h-4 w-4" />
                {t("tickets.new")}
              </Button>
            </Link>
          )}
        </div>

        <TicketTable tickets={tickets} />
      </div>
    </AppShell>
  )
}
