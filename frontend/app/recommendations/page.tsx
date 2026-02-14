"use client"

import { AppShell } from "@/components/app-shell"
import { RecommendationsPanel } from "@/components/recommendations"
import { useI18n } from "@/lib/i18n"

export default function RecommendationsPage() {
  const { t } = useI18n()

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("nav.recommendations")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
            {t("recs.title")}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            {t("recs.subtitle")}
          </p>
        </div>

        <RecommendationsPanel />
      </div>
    </AppShell>
  )
}
