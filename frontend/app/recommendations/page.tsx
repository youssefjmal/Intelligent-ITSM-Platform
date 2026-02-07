"use client"

import { AppShell } from "@/components/app-shell"
import { RecommendationsPanel } from "@/components/recommendations"
import { useI18n } from "@/lib/i18n"

export default function RecommendationsPage() {
  const { t } = useI18n()

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-foreground text-balance">
            {t("recs.title")}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {t("recs.subtitle")}
          </p>
        </div>

        <RecommendationsPanel />
      </div>
    </AppShell>
  )
}
