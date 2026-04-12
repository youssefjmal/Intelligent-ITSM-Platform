"use client"

import { AppShell } from "@/components/app-shell"
import { AssistantMascot } from "@/components/assistant-mascot"
import { TicketChatbot } from "@/components/ticket-chatbot"
import { useI18n } from "@/lib/i18n"

export default function ChatPage() {
  const { t, locale } = useI18n()

  return (
    <AppShell>
      <div className="page-shell fade-slide-in mx-auto max-w-6xl">
        <div className="page-hero">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="section-caption">{t("nav.chat")}</p>
              <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
                {t("chat.title")}
              </h2>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
                {t("chat.subtitle")}
              </p>
            </div>
            <div className="flex items-center gap-4 rounded-3xl border border-border/70 bg-background/70 px-4 py-3 shadow-sm backdrop-blur">
              <AssistantMascot locale={locale} speaking className="shrink-0" />
              <div className="max-w-xs">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary/80">
                  {locale === "fr" ? "Presence assistant" : "Assistant presence"}
                </p>
                <p className="mt-1 text-sm text-foreground">
                  {locale === "fr"
                    ? "Le copilote reste visible pendant la conversation et met mieux en scene les reponses structurees."
                    : "The copilot stays visible during the conversation and gives the structured answers a stronger presence."}
                </p>
              </div>
            </div>
          </div>
        </div>
        <TicketChatbot />
      </div>
    </AppShell>
  )
}
