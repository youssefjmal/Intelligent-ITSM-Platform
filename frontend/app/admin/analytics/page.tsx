"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { AIFeedbackAnalytics } from "@/components/ai-feedback-analytics"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import {
  Shield,
  TrendingUp,
  Clock,
  AlertTriangle,
  CheckCircle,
  Activity,
  Target,
  Zap,
  RefreshCw,
  BarChart2,
} from "lucide-react"
import { apiFetch } from "@/lib/api"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts"

interface TicketStats {
  total: number
  open: number
  in_progress: number
  pending: number
  resolved: number
  closed: number
  critical: number
  high: number
  resolution_rate: number
  avg_resolution_days: number
}

interface TicketPerformance {
  total_tickets: number
  resolved_tickets: number
  mttr_global_hours: number | null
  mttr_p90_hours: number | null
  mttr_by_category_hours: Record<string, number | null>
  throughput_resolved_per_week: number
  reassignment_rate: number
  classification_accuracy_rate: number | null
  classification_samples: number
  high_confidence_rate: number | null
  low_confidence_rate: number | null
  classification_correction_count: number
  auto_assignment_accuracy_rate: number | null
}

interface TicketInsights {
  weekly: Array<{ week: string; opened: number; closed: number; pending: number }>
  category: Array<{ category: string; count: number }>
  priority: Array<{ priority: string; count: number; color: string }>
}

interface SlaMetrics {
  total_tickets: number
  sla_breakdown: { breached: number; at_risk: number; ok: number; unknown: number }
  breach_rate: number
  at_risk_rate: number
  avg_remaining_minutes: number | null
}

interface RecoAnalytics {
  total_feedback: number
  useful_rate: number
  applied_rate: number
}

const CATEGORY_FILL: Record<string, string> = {
  Infrastructure: "#6366f1",
  Reseau: "#3b82f6",
  Securite: "#ef4444",
  Application: "#0ea5e9",
  "Demande de service": "#14b8a6",
  Materiel: "#f59e0b",
  Email: "#8b5cf6",
  Probleme: "#dc2626",
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  colorClasses,
  tooltip,
  href,
}: {
  label: string
  value: string
  sub?: string
  icon: React.FC<{ className?: string }>
  colorClasses: string
  tooltip?: string
  href?: string
}) {
  const inner = (
    <Card className={`surface-card transition-all duration-150 ${href ? "cursor-pointer hover:ring-2 hover:ring-primary/30 hover:shadow-md" : ""}`}>
      <CardContent className="pt-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-bold text-foreground">{value}</p>
            {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
            {tooltip && <p className="mt-1.5 text-[11px] text-muted-foreground/70 italic leading-snug">{tooltip}</p>}
          </div>
          <div className={`flex h-9 w-9 items-center justify-center rounded-full ${colorClasses}`}>
            <Icon className="h-4 w-4" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
  if (href) return <Link href={href}>{inner}</Link>
  return inner
}

export default function AnalyticsPage() {
  const { hasPermission } = useAuth()
  const { locale } = useI18n()
  const router = useRouter()

  const [stats, setStats] = useState<TicketStats | null>(null)
  const [perf, setPerf] = useState<TicketPerformance | null>(null)
  const [insights, setInsights] = useState<TicketInsights | null>(null)
  const [sla, setSla] = useState<SlaMetrics | null>(null)
  const [reco, setReco] = useState<RecoAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, p, i, slaRes, recoRes] = await Promise.allSettled([
        apiFetch<TicketStats>("/tickets/stats"),
        apiFetch<TicketPerformance>("/tickets/performance"),
        apiFetch<TicketInsights>("/tickets/insights"),
        apiFetch<SlaMetrics>("/sla/metrics"),
        apiFetch<RecoAnalytics>("/recommendations/analytics"),
      ])
      if (s.status === "fulfilled") setStats(s.value)
      if (p.status === "fulfilled") setPerf(p.value)
      if (i.status === "fulfilled") setInsights(i.value)
      if (slaRes.status === "fulfilled") setSla(slaRes.value)
      if (recoRes.status === "fulfilled") setReco(recoRes.value)
    } catch {
      setError(locale === "fr" ? "Erreur de chargement des données." : "Failed to load analytics data.")
    } finally {
      setLoading(false)
    }
  }, [locale])

  useEffect(() => {
    load()
  }, [load])

  if (!hasPermission("view_admin")) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center h-[60vh] text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10 mb-4">
            <Shield className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-xl font-bold text-foreground">
            {locale === "fr" ? "Accès refusé" : "Access denied"}
          </h2>
          <Link href="/" className="mt-4">
            <Button variant="outline" className="bg-transparent">
              {locale === "fr" ? "Tableau de bord" : "Dashboard"}
            </Button>
          </Link>
        </div>
      </AppShell>
    )
  }

  const openCount = (stats?.open ?? 0) + (stats?.in_progress ?? 0) + (stats?.pending ?? 0)
  const mttrDisplay = (() => {
    const h = perf?.mttr_global_hours ?? null
    if (h === null) return "—"
    return h < 24 ? `${h.toFixed(1)}h` : `${(h / 24).toFixed(1)}j`
  })()
  const mttrP90Display = (() => {
    const h = perf?.mttr_p90_hours ?? null
    if (h === null) return undefined
    return `P90: ${h < 24 ? `${h.toFixed(1)}h` : `${(h / 24).toFixed(1)}j`}`
  })()
  const classDisplay =
    perf?.classification_accuracy_rate != null
      ? `${perf.classification_accuracy_rate.toFixed(1)}%`
      : "—"
  const classSubDisplay = (() => {
    const high = perf?.high_confidence_rate
    const low = perf?.low_confidence_rate
    const corrections = perf?.classification_correction_count ?? 0
    if (high != null) return `${high.toFixed(0)}% haute confiance · ${corrections} correction${corrections !== 1 ? "s" : ""}`
    if (corrections > 0) return `${corrections} correction${corrections !== 1 ? "s" : ""} agent`
    return perf?.classification_samples ? `${perf.classification_samples} échantillons` : undefined
  })()
  const breachDisplay = sla?.breach_rate != null ? `${sla.breach_rate}%` : "—"
  const resDisplay = stats?.resolution_rate != null ? `${stats.resolution_rate}%` : "—"
  const recoDisplay =
    reco?.useful_rate != null ? `${Math.round(reco.useful_rate * 100)}%` : "—"

  const categoryChartData = (insights?.category ?? [])
    .filter((c) => c.count > 0)
    .sort((a, b) => b.count - a.count)
    .map((c) => ({
      name: c.category,
      count: c.count,
      fill: CATEGORY_FILL[c.category] ?? "#6b7280",
    }))

  const weeklyChartData = (insights?.weekly ?? []).slice(-8)

  const slaBreakdownData = sla
    ? [
        { name: locale === "fr" ? "Conforme" : "OK", value: sla.sla_breakdown.ok ?? 0, fill: "#1D9E75" },
        { name: locale === "fr" ? "À risque" : "At risk", value: sla.sla_breakdown.at_risk ?? 0, fill: "#f59e0b" },
        { name: locale === "fr" ? "Dépassé" : "Breached", value: sla.sla_breakdown.breached ?? 0, fill: "#ef4444" },
        { name: locale === "fr" ? "Inconnu" : "Unknown", value: sla.sla_breakdown.unknown ?? 0, fill: "#9ca3af" },
      ].filter((d) => d.value > 0)
    : []

  const mttrByCategoryData = perf?.mttr_by_category_hours
    ? Object.entries(perf.mttr_by_category_hours)
        .filter(([, v]) => v !== null)
        .map(([cat, hours]) => ({
          name: cat.replace(/_/g, " "),
          hours: typeof hours === "number" ? parseFloat(hours.toFixed(1)) : 0,
          fill: CATEGORY_FILL[cat] ?? "#6b7280",
        }))
        .sort((a, b) => b.hours - a.hours)
    : []

  const tooltipStyle = {
    contentStyle: {
      background: "var(--color-background, #fff)",
      border: "1px solid var(--color-border, #e5e7eb)",
      borderRadius: "8px",
      fontSize: 12,
    },
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        {/* Page header */}
        <div className="page-hero">
          <p className="section-caption">
            {locale === "fr" ? "Administration" : "Administration"}
          </p>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
                {locale === "fr" ? "Tableau de bord analytique" : "Analytics Dashboard"}
              </h2>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
                {locale === "fr"
                  ? "KPIs opérationnels, tendances de volume, conformité SLA et performance de la classification IA."
                  : "Operational KPIs, volume trends, SLA compliance, and AI classification performance."}
              </p>
            </div>
            <Button onClick={load} variant="outline" size="sm" disabled={loading} className="gap-2 shrink-0">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {locale === "fr" ? "Actualiser" : "Refresh"}
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin">{locale === "fr" ? "Administration" : "Administration"}</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/performance">{locale === "fr" ? "Performance agents" : "Agent performance"}</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/ai-governance">Gouvernance IA</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/security">Sécurité & Conformité</Link>
            </Button>
          </div>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </div>

        {/* KPI row 1 */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label={locale === "fr" ? "Tickets total" : "Total tickets"}
            value={loading ? "…" : String(stats?.total ?? 0)}
            sub={`${openCount} ${locale === "fr" ? "ouverts" : "open"}`}
            icon={Activity}
            colorClasses="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
            tooltip={locale === "fr" ? "Cliquer pour voir tous les tickets du système" : "Click to view all tickets"}
            href="/tickets"
          />
          <StatCard
            label="MTTR"
            value={loading ? "…" : mttrDisplay}
            sub={mttrP90Display}
            icon={Clock}
            colorClasses="bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400"
            tooltip={locale === "fr" ? "Temps Moyen de Résolution — cliquer pour comparer par agent" : "Mean Time To Resolve — click to compare by agent"}
            href="/admin/performance"
          />
          <StatCard
            label={locale === "fr" ? "Taux de résolution" : "Resolution rate"}
            value={loading ? "…" : resDisplay}
            sub={`${stats?.resolved ?? 0} ${locale === "fr" ? "résolus" : "resolved"}`}
            icon={CheckCircle}
            colorClasses="bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400"
            tooltip={locale === "fr" ? "% tickets résolus ou fermés — cliquer pour voir les tickets résolus" : "% resolved or closed tickets — click to view resolved tickets"}
            href="/tickets?status=resolved"
          />
          <StatCard
            label={locale === "fr" ? "Dépassements SLA" : "SLA breach rate"}
            value={loading ? "…" : breachDisplay}
            sub={sla?.at_risk_rate !== undefined ? `${sla.at_risk_rate}% ${locale === "fr" ? "à risque" : "at risk"}` : undefined}
            icon={AlertTriangle}
            colorClasses="bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
            tooltip={locale === "fr" ? "Taux de tickets ayant dépassé leur délai SLA Jira — cliquer pour la vue conformité SLA" : "% tickets that exceeded their Jira SLA — click for SLA compliance view"}
            href="/sla"
          />
        </div>

        {/* KPI row 2 */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label={locale === "fr" ? "Tickets critiques" : "Critical tickets"}
            value={loading ? "…" : String(stats?.critical ?? 0)}
            sub={`${stats?.high ?? 0} ${locale === "fr" ? "haute priorité" : "high priority"}`}
            icon={AlertTriangle}
            colorClasses="bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400"
            tooltip={locale === "fr" ? "Tickets de priorité critique — cliquer pour les voir filtrés" : "Critical priority tickets — click to view filtered"}
            href="/tickets?priority=critical"
          />
          <StatCard
            label={locale === "fr" ? "Précision classification IA" : "AI classification accuracy"}
            value={loading ? "…" : classDisplay}
            sub={loading ? undefined : classSubDisplay}
            icon={Target}
            colorClasses="bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400"
            tooltip={
              locale === "fr"
                ? `Prédiction IA vs valeur finale agent · ${perf?.low_confidence_rate != null ? `${perf.low_confidence_rate.toFixed(0)}% faible confiance` : ""}`.trimEnd().replace(/·\s*$/, "")
                : `AI prediction vs agent final value · ${perf?.low_confidence_rate != null ? `${perf.low_confidence_rate.toFixed(0)}% low-confidence` : ""}`.trimEnd().replace(/·\s*$/, "")
            }
            href="/admin/ai-governance"
          />
          <StatCard
            label={locale === "fr" ? "Résolutions / semaine" : "Resolved / week"}
            value={loading ? "…" : String(perf?.throughput_resolved_per_week ?? 0)}
            sub={locale === "fr" ? "débit de résolution" : "throughput"}
            icon={TrendingUp}
            colorClasses="bg-cyan-100 text-cyan-600 dark:bg-cyan-900/30 dark:text-cyan-400"
            tooltip={locale === "fr" ? "Nombre moyen de tickets résolus par semaine — cliquer pour les performances agents" : "Average tickets resolved per week — click for agent performance"}
            href="/admin/performance"
          />
          <StatCard
            label={locale === "fr" ? "Utilité reco. IA" : "AI reco. usefulness"}
            value={loading ? "…" : recoDisplay}
            sub={
              reco?.total_feedback
                ? `${reco.total_feedback} ${locale === "fr" ? "retours" : "feedbacks"}`
                : undefined
            }
            icon={Zap}
            colorClasses="bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400"
            tooltip={locale === "fr" ? "% de retours positifs sur les recommandations IA — cliquer pour voir les recommandations" : "% positive feedback on AI recommendations — click to view recommendations"}
            href="/recommendations"
          />
        </div>

        {/* AI confidence distribution strip */}
        {!loading && perf?.high_confidence_rate != null && (
          <Card className="surface-card">
            <CardContent className="pt-4 pb-4">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <p className="text-sm font-medium text-foreground">
                  {locale === "fr" ? "Distribution de confiance IA" : "AI confidence distribution"}
                </p>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-teal-500" />
                    {locale === "fr" ? "Haute" : "High"} ≥70% — {perf.high_confidence_rate.toFixed(0)}%
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                    {locale === "fr" ? "Faible" : "Low"} &lt;40% — {(perf.low_confidence_rate ?? 0).toFixed(0)}%
                  </span>
                  {perf.classification_correction_count > 0 && (
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-full bg-rose-400" />
                      {perf.classification_correction_count} {locale === "fr" ? "correction(s) agent" : "agent correction(s)"}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted/30">
                <div
                  className="bg-teal-500 transition-all"
                  style={{ width: `${perf.high_confidence_rate}%` }}
                  title={`${locale === "fr" ? "Haute confiance" : "High confidence"}: ${perf.high_confidence_rate.toFixed(1)}%`}
                />
                <div
                  className="bg-amber-400 transition-all"
                  style={{ width: `${perf.low_confidence_rate ?? 0}%` }}
                  title={`${locale === "fr" ? "Faible confiance" : "Low confidence"}: ${(perf.low_confidence_rate ?? 0).toFixed(1)}%`}
                />
                <div className="flex-1 bg-indigo-300/40" title={locale === "fr" ? "Confiance moyenne" : "Medium confidence"} />
              </div>
            </CardContent>
          </Card>
        )}

        {/* Charts row 1: weekly volume + category breakdown */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="surface-card">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Activity className="h-4 w-4 text-primary" />
                {locale === "fr" ? "Volume hebdomadaire" : "Weekly volume"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="h-52 animate-pulse rounded bg-muted/30" />
              ) : weeklyChartData.length === 0 ? (
                <p className="flex h-52 items-center justify-center text-sm text-muted-foreground">
                  {locale === "fr" ? "Données insuffisantes." : "Not enough data."}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={weeklyChartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gradOpened" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="gradClosed" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#1D9E75" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#1D9E75" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary, #e5e7eb)" />
                    <XAxis dataKey="week" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip {...tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Area
                      type="monotone"
                      dataKey="opened"
                      name={locale === "fr" ? "Ouverts" : "Opened"}
                      stroke="#3b82f6"
                      fill="url(#gradOpened)"
                      strokeWidth={2}
                    />
                    <Area
                      type="monotone"
                      dataKey="closed"
                      name={locale === "fr" ? "Fermés" : "Closed"}
                      stroke="#1D9E75"
                      fill="url(#gradClosed)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card className="surface-card">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <BarChart2 className="h-4 w-4 text-primary" />
                {locale === "fr" ? "Répartition par catégorie" : "Tickets by category"}
              </CardTitle>
              <p className="text-[11px] text-muted-foreground/70 italic">
                {locale === "fr" ? "Cliquer sur une barre pour filtrer les tickets par catégorie" : "Click a bar to filter tickets by category"}
              </p>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="h-52 animate-pulse rounded bg-muted/30" />
              ) : categoryChartData.length === 0 ? (
                <p className="flex h-52 items-center justify-center text-sm text-muted-foreground">
                  {locale === "fr" ? "Données insuffisantes." : "Not enough data."}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={categoryChartData}
                    margin={{ top: 4, right: 4, left: -20, bottom: 0 }}
                    style={{ cursor: "pointer" }}
                    onClick={(data) => {
                      if (data?.activePayload?.[0]?.payload?.name) {
                        router.push(`/tickets?category=${encodeURIComponent(data.activePayload[0].payload.name.toLowerCase())}`)
                      }
                    }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary, #e5e7eb)" />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      {...tooltipStyle}
                      formatter={(value: number, _name: string, props) => [
                        `${value} ticket${value !== 1 ? "s" : ""}`,
                        props.payload?.name ?? "",
                      ]}
                      cursor={{ fill: "var(--color-muted, #f3f4f6)", opacity: 0.5 }}
                    />
                    <Bar dataKey="count" name={locale === "fr" ? "Tickets" : "Tickets"} radius={[4, 4, 0, 0]}>
                      {categoryChartData.map((entry, idx) => (
                        <Cell key={`cat-${idx}`} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Charts row 2: SLA compliance pie + MTTR by category */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="surface-card">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <AlertTriangle className="h-4 w-4 text-primary" />
                {locale === "fr" ? "Conformité SLA" : "SLA compliance"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="h-52 animate-pulse rounded bg-muted/30" />
              ) : slaBreakdownData.length === 0 ? (
                <p className="flex h-52 items-center justify-center text-sm text-muted-foreground">
                  {locale === "fr"
                    ? "Aucun ticket Jira avec données SLA."
                    : "No Jira-linked tickets with SLA data."}
                </p>
              ) : (
                <div className="flex flex-col items-center gap-4">
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie
                        data={slaBreakdownData}
                        cx="50%"
                        cy="50%"
                        innerRadius={48}
                        outerRadius={78}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {slaBreakdownData.map((entry, idx) => (
                          <Cell key={`sla-${idx}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip {...tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="grid w-full grid-cols-2 gap-3">
                    <div className="rounded-lg bg-teal-50 p-3 text-center dark:bg-teal-950/30">
                      <p className="text-xs text-teal-700 dark:text-teal-400">
                        {locale === "fr" ? "Conformes" : "Compliant"}
                      </p>
                      <p className="text-xl font-bold text-teal-700 dark:text-teal-400">
                        {sla?.sla_breakdown.ok ?? 0}
                      </p>
                    </div>
                    <div className="rounded-lg bg-red-50 p-3 text-center dark:bg-red-950/30">
                      <p className="text-xs text-red-600">
                        {locale === "fr" ? "Dépassés" : "Breached"}
                      </p>
                      <p className="text-xl font-bold text-red-600">
                        {sla?.sla_breakdown.breached ?? 0}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="surface-card">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Clock className="h-4 w-4 text-primary" />
                {locale === "fr" ? "MTTR par catégorie (h)" : "MTTR by category (h)"}
              </CardTitle>
              <p className="text-[11px] text-muted-foreground/70 italic">
                {locale === "fr" ? "Cliquer pour voir la performance agents" : "Click to view agent performance"}
              </p>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="h-52 animate-pulse rounded bg-muted/30" />
              ) : mttrByCategoryData.length === 0 ? (
                <p className="flex h-52 items-center justify-center text-sm text-muted-foreground">
                  {locale === "fr" ? "Données insuffisantes." : "Not enough data."}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={mttrByCategoryData}
                    layout="vertical"
                    margin={{ top: 4, right: 16, left: 4, bottom: 0 }}
                    style={{ cursor: "pointer" }}
                    onClick={(data) => {
                      if (data?.activePayload?.[0]?.payload?.name) {
                        router.push(`/admin/performance`)
                      }
                    }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary, #e5e7eb)" />
                    <XAxis type="number" tick={{ fontSize: 11 }} unit="h" />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={90} />
                    <Tooltip
                      {...tooltipStyle}
                      formatter={(value: number) => [`${value}h`, "MTTR"]}
                      cursor={{ fill: "var(--color-muted, #f3f4f6)", opacity: 0.5 }}
                    />
                    <Bar dataKey="hours" name="MTTR" radius={[0, 4, 4, 0]}>
                      {mttrByCategoryData.map((entry, idx) => (
                        <Cell key={`mttr-${idx}`} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        <section className="section-block">
          <div>
            <h3 className="section-title">
              {locale === "fr" ? "Feedback sur les recommandations IA" : "AI recommendation feedback"}
            </h3>
            <p className="section-subtitle">
              {locale === "fr"
                ? "Ces KPIs sont reserves a l'administration pour suivre l'adoption et la pertinence des recommandations."
                : "These KPIs stay in the admin area so only administrators see recommendation adoption and usefulness signals."}
            </p>
          </div>
          <AIFeedbackAnalytics />
        </section>
      </div>
    </AppShell>
  )
}
