"use client"

import Link from "next/link"
import { type ReactNode, useState } from "react"
import { CircleOff, ThumbsUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

// ---------------------------------------------------------------------------
// Display-mode tooltip copy — defined here so copy changes never require
// hunting through JSX.  Update in one place; all badge tooltips update.
// ---------------------------------------------------------------------------

/**
 * Tooltip text for the display mode badges shown on recommendation cards.
 * Locale-keyed so the same object drives both EN and FR tooltips.
 * This is defined at module level (not inline in JSX) so copy can be updated
 * without touching markup, and so the strings are visible during code review.
 */
const DISPLAY_MODE_TOOLTIPS: Record<
  "evidence_action" | "tentative_diagnostic",
  { en: string; fr: string }
> = {
  evidence_action: {
    en: "Evidence-backed: this suggestion is grounded in resolved tickets or knowledge base articles. Still verify before applying.",
    fr: "Fondé sur des preuves : cette suggestion s'appuie sur des tickets résolus ou des articles de base de connaissances. Vérifiez avant d'appliquer.",
  },
  tentative_diagnostic: {
    en: "Tentative: evidence exists but is not conclusive. Treat this as a starting point, not a confirmed fix. Verify before applying.",
    fr: "Provisoire : des indices existent mais ne sont pas concluants. Utilisez ceci comme point de départ. Vérifiez avant d'appliquer.",
  },
}

/**
 * Guidance shown in the no_strong_match panel.
 * Informational — NOT an error state.  Uses text-muted-foreground styling.
 * Each item is an independent numbered action, not a prose paragraph.
 */
const NO_STRONG_MATCH_STEPS: { en: string[]; fr: string[] } = {
  en: [
    "Add more detail to the ticket description to improve analysis",
    "Check whether a related problem record exists",
    "Escalate if the issue is active and exceeding your SLA threshold",
  ],
  fr: [
    "Ajoutez des détails à la description du ticket pour affiner l'analyse",
    "Vérifiez si un problème lié existe dans la liste des problèmes",
    "Escaladez si le problème est actif et dépasse votre seuil SLA",
  ],
}

// Display strings for llm_general_knowledge card.
// Update here when copy changes — do not hardcode in JSX.
const LLM_ADVISORY_STRINGS = {
  headerFr: "Avis général — aucune donnée locale disponible",
  headerEn: "General advisory — no local data available",
  actionTitleFr: "Action recommandee",
  actionTitleEn: "Recommended action",
  nextActionsTitleFr: "Prochaines actions",
  nextActionsTitleEn: "Next best actions",
  validationTitleFr: "Validation",
  validationTitleEn: "Validation",
  causesTitleFr: "Causes probables",
  causesTitleEn: "Probable causes",
  checksTitleFr: "Étapes de diagnostic suggérées",
  checksTitleEn: "Suggested diagnostic steps",
  disclaimerFr:
    "Cet avis est basé sur les connaissances générales en IT, pas sur l'historique de vos tickets. Vérifiez avant d'appliquer.",
  disclaimerEn:
    "This advisory is based on general IT knowledge, not your ticket history. Verify before applying.",
  confidenceLabelFr: "Connaissance générale",
  confidenceLabelEn: "General knowledge",
  escalationTitleFr: "Conseil d'escalade",
  escalationTitleEn: "Escalation guidance",
} as const

export type RecommendationLocale = "fr" | "en"
export type RecommendationDisplayMode =
  | "evidence_action"
  | "tentative_diagnostic"
  | "service_request"
  | "llm_general_knowledge"
  | "no_strong_match"

export type RecommendationEvidenceItem = {
  evidenceType: string
  reference: string
  excerpt: string | null
  sourceId?: string | null
  title?: string | null
  relevance?: number
  whyRelevant?: string | null
}

export type RecommendationClusterInsight = {
  count: number
  windowHours: number
  summary: string
}

type RecommendationSectionProps = {
  label: string
  children: ReactNode
  className?: string
  labelClassName?: string
  bodyClassName?: string
}

export function formatConfidencePercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  if (value <= 1) return Math.round(Math.max(0, Math.min(1, value)) * 100)
  return Math.round(Math.max(0, Math.min(100, value)))
}

export function confidenceBandLabel(band: string, locale: RecommendationLocale): string {
  const labels: Record<string, { fr: string; en: string }> = {
    high: { fr: "Elevee", en: "High" },
    medium: { fr: "Moyenne", en: "Medium" },
    low: { fr: "Faible", en: "Low" },
  }
  const entry = labels[band] || labels.low
  return locale === "fr" ? entry.fr : entry.en
}

export function confidenceBandClass(band: string): string {
  if (band === "high") return "border-emerald-300 bg-emerald-50 text-emerald-700"
  if (band === "medium") return "border-amber-300 bg-amber-50 text-amber-700"
  return "border-rose-300 bg-rose-50 text-rose-700"
}

export function recommendationModeLabel(mode: string, locale: RecommendationLocale): string {
  const labels: Record<string, { fr: string; en: string }> = {
    resolved_ticket_grounded: { fr: "Ticket resolu", en: "Resolved ticket" },
    kb_grounded: { fr: "Base de connaissance", en: "Knowledge base" },
    comment_grounded: { fr: "Commentaire confirme", en: "Confirmed comment" },
    evidence_grounded: { fr: "Evidence terrain", en: "Grounded evidence" },
    service_request: { fr: "Runbook de fulfilment", en: "Fulfillment runbook" },
    fallback_diagnostic: { fr: "Diagnostic prudent", en: "Cautious diagnostic" },
    fallback_rules: { fr: "Repli deterministe", en: "Deterministic fallback" },
    llm_assisted: { fr: "LLM assiste", en: "LLM assisted" },
  }
  const entry = labels[mode] || { fr: mode || "Repli deterministe", en: mode || "Deterministic fallback" }
  return locale === "fr" ? entry.fr : entry.en
}

export function sourceLabelText(label: string, locale: RecommendationLocale): string {
  const labels: Record<string, { fr: string; en: string }> = {
    hybrid_jira_local: { fr: "Jira + local", en: "Jira + local" },
    jira_semantic: { fr: "Jira semantique", en: "Jira semantic" },
    local_semantic: { fr: "Local semantique", en: "Local semantic" },
    local_lexical: { fr: "Local lexical", en: "Local lexical" },
    service_request: { fr: "Workflow planifie", en: "Planned workflow" },
    kb_empty: { fr: "KB vide", en: "KB empty" },
    fallback_rules: { fr: "Sans evidence forte", en: "No strong evidence" },
    problem_record: { fr: "Fiche probleme", en: "Problem record" },
    legacy_store: { fr: "Flux legacy", en: "Legacy feed" },
  }
  const entry = labels[label] || { fr: label || "Inconnu", en: label || "Unknown" }
  return locale === "fr" ? entry.fr : entry.en
}

export function evidenceTypeLabel(type: string, locale: RecommendationLocale): string {
  const labels: Record<string, { fr: string; en: string }> = {
    "resolved ticket": { fr: "ticket resolu", en: "resolved ticket" },
    "similar ticket": { fr: "ticket similaire", en: "similar ticket" },
    "KB article": { fr: "article KB", en: "KB article" },
    comment: { fr: "commentaire", en: "comment" },
    "related problem": { fr: "probleme lie", en: "related problem" },
  }
  const entry = labels[type] || { fr: type || "evidence", en: type || "evidence" }
  return locale === "fr" ? entry.fr : entry.en
}

export function confidenceBadgeClass(value: number): string {
  if (value >= 80) return "border-emerald-300 bg-emerald-50 text-emerald-700"
  if (value >= 60) return "border-amber-300 bg-amber-50 text-amber-700"
  return "border-rose-300 bg-rose-50 text-rose-700"
}

export function recommendationStatusLabel(
  tentative: boolean,
  locale: RecommendationLocale,
  displayMode?: RecommendationDisplayMode | string,
): string {
  if (displayMode === "service_request") {
    return locale === "fr" ? "Workflow planifie" : "Planned workflow"
  }
  if (displayMode === "llm_general_knowledge") {
    return locale === "fr" ? "Avis general prudent" : "Low-trust advisory"
  }
  if (tentative) return locale === "fr" ? "Tentative" : "Tentative"
  return locale === "fr" ? "Validee" : "Validated"
}

export function recommendationDisplayTitle(
  displayMode: RecommendationDisplayMode,
  locale: RecommendationLocale,
): string {
  if (displayMode === "service_request") {
    return locale === "fr" ? "Etape de fulfilment suggeree" : "Suggested fulfillment step"
  }
  if (displayMode === "tentative_diagnostic") {
    return locale === "fr" ? "Etape diagnostique suggeree" : "Suggested diagnostic step"
  }
  if (displayMode === "no_strong_match") {
    return locale === "fr" ? "Aucune solution forte" : "No strong match"
  }
  if (displayMode === "llm_general_knowledge") {
    return locale === "fr"
      ? LLM_ADVISORY_STRINGS.headerFr
      : LLM_ADVISORY_STRINGS.headerEn
  }
  return locale === "fr" ? "Action recommandee" : "Recommended action"
}

export function noStrongMatchMessage(locale: RecommendationLocale): string {
  return locale === "fr"
    ? "Aucune solution appuyee par des preuves fortes n'est disponible pour l'instant."
    : "No strong evidence-backed solution available yet."
}

export function primaryEvidenceType(
  evidenceSources: RecommendationEvidenceItem[],
): string | null {
  return evidenceSources[0]?.evidenceType || null
}

export function recommendationDisplayText(
  displayMode: RecommendationDisplayMode,
  locale: RecommendationLocale,
  action?: string | null,
  fallback?: string | null,
): string {
  if (displayMode === "no_strong_match") {
    return noStrongMatchMessage(locale)
  }
  return String(action || fallback || "").trim()
}

function RecommendationSection({
  label,
  children,
  className,
  labelClassName,
  bodyClassName,
}: RecommendationSectionProps) {
  return (
    <div className={cn("rounded-md border border-border/60 bg-card/70 p-3", className)}>
      <p className={cn("text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground", labelClassName)}>
        {label}
      </p>
      <div className={cn("mt-2 text-xs leading-relaxed text-muted-foreground", bodyClassName)}>
        {children}
      </div>
    </div>
  )
}

function evidenceReferenceHref(reference: string): string | null {
  const normalized = String(reference || "").trim()
  if (!normalized) return null
  if (/^TW-[A-Z0-9-]+$/i.test(normalized)) return `/tickets/${normalized}`
  if (/^PB-[A-Z0-9-]+$/i.test(normalized)) return `/problems/${normalized}`
  return null
}

function evidenceReferenceHint(reference: string, locale: RecommendationLocale): string | null {
  const normalized = String(reference || "").trim()
  if (/^TW-[A-Z0-9-]+$/i.test(normalized)) {
    return locale === "fr" ? "Cliquez pour ouvrir le ticket." : "Click to open the ticket."
  }
  if (/^PB-[A-Z0-9-]+$/i.test(normalized)) {
    return locale === "fr" ? "Cliquez pour ouvrir le probleme." : "Click to open the problem."
  }
  return null
}

export function RecommendationActionBlock({
  locale,
  displayMode,
  action,
  fallback,
  className,
}: {
  locale: RecommendationLocale
  displayMode: RecommendationDisplayMode
  action?: string | null
  fallback?: string | null
  className?: string
}) {
  const body = recommendationDisplayText(displayMode, locale, action, fallback)

  // For evidence_action and tentative_diagnostic, the mode title is wrapped in
  // a tooltip explaining what the mode means and what the user should do.
  // no_strong_match has no tooltip — its body text carries the guidance directly.
  const tooltipCopy =
    displayMode === "evidence_action" || displayMode === "tentative_diagnostic"
      ? DISPLAY_MODE_TOOLTIPS[displayMode][locale]
      : null

  const titleEl = (
    <p
      className={cn(
        "text-[10px] font-semibold uppercase tracking-[0.08em]",
        displayMode === "no_strong_match"
          ? "text-slate-600"
          : displayMode === "service_request"
            ? "text-sky-800"
          : displayMode === "tentative_diagnostic"
            ? "text-amber-800"
            : "text-muted-foreground",
        // Underline hint so users discover the tooltip.
        tooltipCopy ? "cursor-help underline decoration-dotted underline-offset-2" : undefined,
      )}
    >
      {recommendationDisplayTitle(displayMode, locale)}
    </p>
  )

  return (
    <div
      className={cn(
        "rounded-md p-3",
        displayMode === "no_strong_match"
          ? "border border-slate-200 bg-slate-50/80"
          : displayMode === "service_request"
            ? "border border-sky-200 bg-sky-50/70"
          : displayMode === "tentative_diagnostic"
            ? "border border-amber-200 bg-amber-50/70"
            : "border border-primary/20 bg-primary/5",
        className,
      )}
    >
      {tooltipCopy ? (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>{titleEl}</TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-xs text-[11px] leading-relaxed"
            >
              {tooltipCopy}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        titleEl
      )}

      {/* For no_strong_match, show the fallback action text when available,
          followed by numbered guidance steps.
          For llm_general_knowledge, the body text is not shown here — the
          full advisory card is rendered separately via LLMAdvisoryBlock. */}
      {displayMode === "no_strong_match" ? (
        <>
          {action ? (
            <p className="mt-2 text-sm font-medium leading-relaxed text-foreground">
              {action}
            </p>
          ) : null}
          <ol className={`space-y-1.5 pl-0 ${action ? "mt-3" : "mt-2"}`}>
            {NO_STRONG_MATCH_STEPS[locale].map((step, index) => (
              <li key={`nsm-step-${index}`} className="flex gap-2 text-xs leading-relaxed text-muted-foreground">
                <span className="font-semibold">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </>
      ) : displayMode === "llm_general_knowledge" ? null : (
        <p className="mt-2 text-sm font-medium leading-relaxed text-foreground">
          {body}
        </p>
      )}
    </div>
  )
}

export function RecommendationReasoningBlock({
  locale,
  reasoning,
  className,
}: {
  locale: RecommendationLocale
  reasoning?: string | null
  className?: string
}) {
  const [expanded, setExpanded] = useState(false)
  if (!reasoning) return null
  const isLong = reasoning.length > 180
  return (
    <RecommendationSection
      label={locale === "fr" ? "Justification" : "Reasoning"}
      className={className}
    >
      <span className={expanded || !isLong ? undefined : "line-clamp-3"}>
        {reasoning}
      </span>
      {isLong && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v) }}
          className="mt-1 text-[11px] font-medium text-primary hover:underline"
        >
          {expanded
            ? (locale === "fr" ? "Réduire" : "Show less")
            : (locale === "fr" ? "Lire plus" : "Read more")}
        </button>
      )}
    </RecommendationSection>
  )
}

export function RecommendationMatchBlock({
  locale,
  matchSummary,
  className,
}: {
  locale: RecommendationLocale
  matchSummary?: string | null
  className?: string
}) {
  if (!matchSummary) return null
  return (
    <RecommendationSection
      label={locale === "fr" ? "Pourquoi ce match" : "Why it matched"}
      className={cn("border-sky-200 bg-sky-50/70", className)}
      labelClassName="text-sky-800"
      bodyClassName="text-xs text-sky-900"
    >
      {matchSummary}
    </RecommendationSection>
  )
}

export function RecommendationWhyMatchesBlock({
  locale,
  whyThisMatches,
  className,
}: {
  locale: RecommendationLocale
  whyThisMatches?: string[]
  className?: string
}) {
  const items = Array.isArray(whyThisMatches) ? whyThisMatches.filter(Boolean) : []
  if (!items.length) return null
  return (
    <RecommendationSection
      label={locale === "fr" ? "Pourquoi ce match est fiable" : "Why this match is trustworthy"}
      className={cn("border-sky-200 bg-sky-50/70", className)}
      labelClassName="text-sky-800"
      bodyClassName="text-xs text-sky-900"
    >
      <ul className="space-y-2">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex gap-2">
            <span className="font-semibold text-sky-700">{index + 1}.</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </RecommendationSection>
  )
}

export function RecommendationRootCauseBlock({
  locale,
  probableRootCause,
  className,
}: {
  locale: RecommendationLocale
  probableRootCause?: string | null
  className?: string
}) {
  if (!probableRootCause) return null
  return (
    <RecommendationSection
      label={locale === "fr" ? "Cause probable" : "Probable root cause"}
      className={className}
      bodyClassName="text-xs text-foreground"
    >
      {probableRootCause}
    </RecommendationSection>
  )
}

export function RecommendationSupportingContextBlock({
  locale,
  supportingContext,
  className,
}: {
  locale: RecommendationLocale
  supportingContext?: string | null
  className?: string
}) {
  if (!supportingContext) return null
  return (
    <RecommendationSection
      label={locale === "fr" ? "Contexte de support" : "Supporting context"}
      className={cn("border-violet-200 bg-violet-50/70", className)}
      labelClassName="text-violet-800"
      bodyClassName="text-xs text-violet-900"
    >
      {supportingContext}
    </RecommendationSection>
  )
}

export function RecommendationClusterImpactBlock({
  locale,
  clusterInsight,
  impactSummary,
  className,
}: {
  locale: RecommendationLocale
  clusterInsight?: RecommendationClusterInsight | null
  impactSummary?: string | null
  className?: string
}) {
  if (!clusterInsight && !impactSummary) return null
  return (
    <div className={cn("grid grid-cols-1 gap-2 md:grid-cols-2", className)}>
      {clusterInsight ? (
        <div className="rounded-md border border-amber-200 bg-amber-50/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-800">
            {locale === "fr" ? "Signal de cluster" : "Cluster signal"}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-amber-900">{clusterInsight.summary}</p>
        </div>
      ) : null}
      {impactSummary ? (
        <div className="rounded-md border border-indigo-200 bg-indigo-50/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-indigo-800">
            {locale === "fr" ? "Impact potentiel" : "Potential impact"}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-indigo-900">{impactSummary}</p>
        </div>
      ) : null}
    </div>
  )
}

export function RecommendationNextActionsBlock({
  locale,
  actions,
  className,
}: {
  locale: RecommendationLocale
  actions: string[]
  className?: string
}) {
  if (!actions.length) return null
  return (
    <RecommendationSection
      label={locale === "fr" ? "Prochaines actions" : "Next Best Actions"}
      className={className}
      bodyClassName="text-xs text-foreground"
    >
      <ol className="space-y-2">
        {actions.map((item, index) => (
          <li key={`${item}-${index}`} className="flex gap-2">
            <span className="font-semibold text-primary">{index + 1}.</span>
            <span>{item}</span>
          </li>
        ))}
      </ol>
    </RecommendationSection>
  )
}

export function RecommendationEvidenceAccordion({
  locale,
  evidenceSources,
  className,
  countBadge = false,
}: {
  locale: RecommendationLocale
  evidenceSources: RecommendationEvidenceItem[]
  className?: string
  countBadge?: boolean
}) {
  if (!evidenceSources.length) return null

  return (
    <details className={cn("rounded-md border border-border/60 bg-background/60 p-2.5", className)}>
      <summary className="cursor-pointer list-none">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {locale === "fr" ? "Evidence utilisee" : "Evidence used"}
          </span>
          {countBadge ? (
            <Badge variant="outline" className="text-[10px]">
              {evidenceSources.length}
            </Badge>
          ) : null}
        </div>
      </summary>
      <div className="mt-2 space-y-2">
        {evidenceSources.map((source, index) => {
          const href = evidenceReferenceHref(source.reference)
          const hint = evidenceReferenceHint(source.reference, locale)
          const preview =
            source.excerpt ||
            source.whyRelevant ||
            (locale === "fr"
              ? "Aucun extrait detaille n'est disponible pour cette evidence."
              : "No detailed excerpt is available for this evidence.")

          const triggerClassName = cn(
            "block rounded-md border border-border/60 bg-card/70 p-2 text-xs transition-colors",
            href ? "cursor-pointer hover:border-primary/40 hover:bg-card" : "cursor-default",
          )

          const triggerContent = (
            <div className="min-w-0">
              <p className={cn("font-medium", href ? "text-primary" : "text-foreground")}>
                {evidenceTypeLabel(source.evidenceType, locale)}: {source.reference}
              </p>
              {source.title ? <p className="mt-1 text-[11px] text-foreground/80">{source.title}</p> : null}
              <p className="mt-1 line-clamp-2 leading-relaxed text-muted-foreground">{preview}</p>
              {typeof source.relevance === "number" ? (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {locale === "fr" ? "Pertinence" : "Relevance"}: {Math.round(Math.max(0, Math.min(1, source.relevance)) * 100)}%
                </p>
              ) : null}
              {hint ? <p className="mt-2 text-[11px] text-muted-foreground">{hint}</p> : null}
            </div>
          )

          return (
            <HoverCard key={`${source.reference}-${index}`} openDelay={100} closeDelay={80}>
              <HoverCardTrigger asChild>
                {href ? (
                  <Link href={href} className={triggerClassName}>
                    {triggerContent}
                  </Link>
                ) : (
                  <div className={triggerClassName}>{triggerContent}</div>
                )}
              </HoverCardTrigger>
              <HoverCardContent className="w-[28rem] border-border/70 bg-background/95 p-3 shadow-xl backdrop-blur">
                <p className="text-sm font-semibold text-foreground">
                  {evidenceTypeLabel(source.evidenceType, locale)}: {source.reference}
                </p>
                {source.title ? <p className="mt-1 text-xs font-medium text-foreground/80">{source.title}</p> : null}
                <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{preview}</p>
                {source.whyRelevant ? (
                  <p className="mt-3 text-xs leading-relaxed text-foreground/80">
                    {locale === "fr" ? "Pourquoi cette evidence compte: " : "Why this evidence matters: "}
                    {source.whyRelevant}
                  </p>
                ) : null}
                {hint ? <p className="mt-3 text-[11px] text-primary">{hint}</p> : null}
              </HoverCardContent>
            </HoverCard>
          )
        })}
      </div>
    </details>
  )
}

// ---------------------------------------------------------------------------
// LLMAdvisoryBlock
// Rendered when display_mode === "llm_general_knowledge".
// Trust level: below tentative_diagnostic — this is general IT knowledge,
// not grounded in the ticket history or the local knowledge base.
// Visual contract: blue/info scheme; no Apply button; persistent disclaimer.
// ---------------------------------------------------------------------------

export type LLMGeneralAdvisoryData = {
  probableCauses?: string[]
  suggestedChecks?: string[]
  escalationHint?: string | null
  knowledgeSource?: string
  probable_causes?: string[]
  suggested_checks?: string[]
  escalation_hint?: string | null
  knowledge_source?: string
  confidence?: number
  language?: string
}

/**
 * Advisory card for recommendations whose display_mode is "llm_general_knowledge".
 *
 * Renders probable causes (bulleted list), suggested diagnostic steps
 * (numbered list), an optional escalation callout, a persistent disclaimer,
 * a fixed "General knowledge" confidence badge, and optional useful /
 * not-relevant feedback buttons.  An Apply button is intentionally absent —
 * this mode offers general guidance only, not a confirmed fix.
 */
export function LLMAdvisoryBlock({
  locale,
  advisory,
  recommendedAction,
  nextBestActions = [],
  validationSteps = [],
  onFeedback,
  currentFeedback,
  className,
}: {
  locale: RecommendationLocale
  advisory: LLMGeneralAdvisoryData
  recommendedAction?: string | null
  nextBestActions?: string[]
  validationSteps?: string[]
  onFeedback?: (type: "useful" | "not_relevant") => void
  currentFeedback?: "useful" | "not_relevant" | null
  className?: string
}) {
  const causes = Array.isArray(advisory.probableCauses)
    ? advisory.probableCauses.filter(Boolean)
    : Array.isArray(advisory.probable_causes)
      ? advisory.probable_causes.filter(Boolean)
      : []
  const checks = Array.isArray(advisory.suggestedChecks)
    ? advisory.suggestedChecks.filter(Boolean)
    : Array.isArray(advisory.suggested_checks)
      ? advisory.suggested_checks.filter(Boolean)
      : []
  const escalationHint = advisory.escalationHint ?? advisory.escalation_hint ?? null
  const action = String(recommendedAction || "").trim()
  const steps = Array.isArray(nextBestActions) ? nextBestActions.filter(Boolean) : []
  const validations = Array.isArray(validationSteps) ? validationSteps.filter(Boolean) : []

  return (
    <div className={cn("rounded-md border border-sky-200 bg-sky-50/80 p-3", className)}>
      {/* Header + confidence badge */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-sky-700">
          {locale === "fr" ? LLM_ADVISORY_STRINGS.headerFr : LLM_ADVISORY_STRINGS.headerEn}
        </p>
        <Badge variant="outline" className="border-sky-300 bg-sky-100 text-[10px] text-sky-700">
          {locale === "fr" ? LLM_ADVISORY_STRINGS.confidenceLabelFr : LLM_ADVISORY_STRINGS.confidenceLabelEn}
        </Badge>
      </div>

      {action ? (
        <div className="mt-3 rounded border border-sky-200 bg-background/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-sky-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.actionTitleFr : LLM_ADVISORY_STRINGS.actionTitleEn}
          </p>
          <p className="mt-2 text-sm font-medium leading-relaxed text-foreground">{action}</p>
        </div>
      ) : null}

      {steps.length > 0 ? (
        <div className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-sky-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.nextActionsTitleFr : LLM_ADVISORY_STRINGS.nextActionsTitleEn}
          </p>
          <ol className="mt-1.5 space-y-1.5 pl-0">
            {steps.map((step, index) => (
              <li key={`llm-next-${index}`} className="flex gap-2 text-xs leading-relaxed text-sky-900">
                <span className="font-semibold text-sky-500">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {validations.length > 0 ? (
        <div className="mt-3 rounded border border-emerald-200 bg-emerald-50/80 p-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.validationTitleFr : LLM_ADVISORY_STRINGS.validationTitleEn}
          </p>
          <ol className="mt-1.5 space-y-1.5 pl-0">
            {validations.map((step, index) => (
              <li key={`llm-validation-${index}`} className="flex gap-2 text-xs leading-relaxed text-emerald-900">
                <span className="font-semibold text-emerald-600">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {/* Probable causes */}
      {causes.length > 0 ? (
        <div className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-sky-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.causesTitleFr : LLM_ADVISORY_STRINGS.causesTitleEn}
          </p>
          <ul className="mt-1.5 space-y-1.5 pl-0">
            {causes.map((cause, index) => (
              <li key={`llm-cause-${index}`} className="flex gap-2 text-xs leading-relaxed text-sky-900">
                <span className="mt-0.5 select-none text-sky-400">•</span>
                <span>{cause}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Suggested diagnostic steps */}
      {checks.length > 0 ? (
        <div className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-sky-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.checksTitleFr : LLM_ADVISORY_STRINGS.checksTitleEn}
          </p>
          <ol className="mt-1.5 space-y-1.5 pl-0">
            {checks.map((check, index) => (
              <li key={`llm-check-${index}`} className="flex gap-2 text-xs leading-relaxed text-sky-900">
                <span className="font-semibold text-sky-500">{index + 1}.</span>
                <span>{check}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {/* Escalation callout — only rendered when the LLM provided a hint */}
      {escalationHint ? (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50/80 p-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-700">
            {locale === "fr" ? LLM_ADVISORY_STRINGS.escalationTitleFr : LLM_ADVISORY_STRINGS.escalationTitleEn}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-amber-900">{escalationHint}</p>
        </div>
      ) : null}

      {/* Persistent disclaimer */}
      <p className="mt-3 text-[11px] italic leading-relaxed text-muted-foreground">
        {locale === "fr" ? LLM_ADVISORY_STRINGS.disclaimerFr : LLM_ADVISORY_STRINGS.disclaimerEn}
      </p>

      {/* Feedback — useful / not relevant only; no Apply or Reject buttons */}
      {onFeedback ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">
            {locale === "fr" ? "Cet avis est-il utile ?" : "Was this helpful?"}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onFeedback("useful")}
            className={cn(
              "gap-1.5 rounded-sm text-xs tracking-[0.03em]",
              currentFeedback === "useful"
                ? "border-emerald-300 bg-emerald-100 text-emerald-800"
                : "border-border/70 hover:border-primary/40 hover:bg-accent/50",
            )}
          >
            <ThumbsUp className="h-3.5 w-3.5" />
            {locale === "fr" ? "Utile" : "Useful"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onFeedback("not_relevant")}
            className={cn(
              "gap-1.5 rounded-sm text-xs tracking-[0.03em]",
              currentFeedback === "not_relevant"
                ? "border-amber-300 bg-amber-100 text-amber-800"
                : "border-border/70 hover:border-primary/40 hover:bg-accent/50",
            )}
          >
            <CircleOff className="h-3.5 w-3.5" />
            {locale === "fr" ? "Pas pertinent" : "Not relevant"}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
