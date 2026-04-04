"use client"

import type { ComponentType } from "react"
import { CheckCircle2, CircleOff, ThumbsDown, ThumbsUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import type {
  RecommendationCurrentFeedback,
  RecommendationFeedbackSummary,
  RecommendationFeedbackType,
} from "@/lib/ai-feedback-api"
import { cn } from "@/lib/utils"

type RecommendationFeedbackControlsProps = {
  locale: "fr" | "en"
  currentFeedback?: RecommendationCurrentFeedback | null
  feedbackSummary?: RecommendationFeedbackSummary | null
  submitting?: boolean
  successMessage?: string | null
  className?: string
  compact?: boolean
  onSubmit: (feedbackType: RecommendationFeedbackType) => void
}

type FeedbackOption = {
  type: RecommendationFeedbackType
  labelFr: string
  labelEn: string
  icon: ComponentType<{ className?: string }>
  activeClassName: string
}

const OPTIONS: FeedbackOption[] = [
  {
    type: "useful",
    labelFr: "Utile",
    labelEn: "Useful",
    icon: ThumbsUp,
    activeClassName: "border-emerald-300 bg-emerald-100 text-emerald-800",
  },
  {
    type: "not_relevant",
    labelFr: "Pas pertinent",
    labelEn: "Not relevant",
    icon: CircleOff,
    activeClassName: "border-amber-300 bg-amber-100 text-amber-800",
  },
  {
    type: "applied",
    labelFr: "Appliquee",
    labelEn: "Applied",
    icon: CheckCircle2,
    activeClassName: "border-blue-300 bg-blue-100 text-blue-800",
  },
  {
    type: "rejected",
    labelFr: "Rejetee",
    labelEn: "Rejected",
    icon: ThumbsDown,
    activeClassName: "border-rose-300 bg-rose-100 text-rose-800",
  },
]

function summaryLine(summary: RecommendationFeedbackSummary | null | undefined, locale: "fr" | "en"): string | null {
  if (!summary || summary.totalFeedback <= 0) {
    return null
  }
  if (locale === "fr") {
    return `${summary.totalFeedback} retours | ${summary.usefulCount} utiles | ${summary.appliedCount} appliquees`
  }
  return `${summary.totalFeedback} feedback entries | ${summary.usefulCount} useful | ${summary.appliedCount} applied`
}

export function RecommendationFeedbackControls({
  locale,
  currentFeedback,
  feedbackSummary,
  submitting = false,
  successMessage,
  className,
  compact = false,
  onSubmit,
}: RecommendationFeedbackControlsProps) {
  const activeType = currentFeedback?.feedbackType || null
  const summary = summaryLine(feedbackSummary, locale)

  return (
    <div className={cn("rounded-lg border border-border/60 bg-background/60 p-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {locale === "fr" ? "Retour agent" : "Agent feedback"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {summary ||
              (locale === "fr"
                ? "Dites si cette recommandation a ete utile, appliquee ou a rejeter."
                : "Mark whether this recommendation was useful, applied, or should be rejected.")}
          </p>
        </div>
        {successMessage ? (
          <span className="text-[11px] font-medium text-muted-foreground">{successMessage}</span>
        ) : null}
      </div>

      <div className={cn("mt-3 flex flex-wrap gap-2", compact ? "gap-1.5" : "gap-2")}>
        {OPTIONS.map((option) => {
          const Icon = option.icon
          const selected = activeType === option.type
          return (
            <Button
              key={option.type}
              type="button"
              variant="outline"
              size="sm"
              disabled={submitting}
              onClick={() => onSubmit(option.type)}
              className={cn(
                "gap-1.5 rounded-full bg-card/80 text-xs transition-colors",
                selected ? option.activeClassName : "border-border/70 hover:border-primary/40 hover:bg-accent/50"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {locale === "fr" ? option.labelFr : option.labelEn}
            </Button>
          )
        })}
      </div>
    </div>
  )
}
