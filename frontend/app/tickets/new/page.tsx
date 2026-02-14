"use client"

import { AppShell } from "@/components/app-shell"
import { TicketForm } from "@/components/ticket-form"
import { useI18n } from "@/lib/i18n"

export default function NewTicketPage() {
  const { t } = useI18n()

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("nav.newTicket")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {t("newTicket.title")}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {t("newTicket.subtitle")}
          </p>
        </div>

        <TicketForm />
      </div>
    </AppShell>
  )
}
