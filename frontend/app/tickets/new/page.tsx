"use client"

import { AppShell } from "@/components/app-shell"
import { TicketForm } from "@/components/ticket-form"
import { useI18n } from "@/lib/i18n"

export default function NewTicketPage() {
  const { t } = useI18n()

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-foreground text-balance">
            {t("newTicket.title")}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {t("newTicket.subtitle")}
          </p>
        </div>

        <TicketForm />
      </div>
    </AppShell>
  )
}
