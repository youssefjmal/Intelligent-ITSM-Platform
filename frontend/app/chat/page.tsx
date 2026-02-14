"use client"

import { AppShell } from "@/components/app-shell"
import { TicketChatbot } from "@/components/ticket-chatbot"
import { useI18n } from "@/lib/i18n"

export default function ChatPage() {
  const { t } = useI18n()

  return (
    <AppShell>
      <div className="page-shell fade-slide-in mx-auto max-w-5xl">
        <div className="page-hero">
          <p className="section-caption">{t("nav.chat")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {t("chat.title")}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {t("chat.subtitle")}
          </p>
        </div>
        <TicketChatbot />
      </div>
    </AppShell>
  )
}
