"use client"

import { useState, useEffect, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { apiFetch } from "@/lib/api"
import {
  ShieldCheck, RefreshCw, ChevronLeft, ChevronRight,
  Lock, LogIn, LogOut, UserCog, Download, AlertTriangle, KeyRound,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"

// ── types ────────────────────────────────────────────────────────────────────

interface SecurityEvent {
  id: string
  event_type: string
  user_id: string | null
  actor_id: string | null
  ip_address: string | null
  user_agent: string | null
  metadata: Record<string, unknown>
  note: string | null
  created_at: string
}

interface EventsResponse {
  total: number
  offset: number
  limit: number
  items: SecurityEvent[]
}

interface ComplianceSummary {
  iso_27001: {
    audit_log_retention_days: number
    total_security_events: number
    events_last_30d: Record<string, number>
    data_classification: Record<string, string>
    controls_implemented: string[]
  }
  iso_42001: {
    standard: string
    total_ai_classification_decisions: number
    human_reviewed: number
    human_overridden: number
    human_review_rate_pct: number
    decisions_by_source: Record<string, number>
    decisions_by_confidence: Record<string, number>
    controls_implemented: string[]
  }
}

// ── helpers ──────────────────────────────────────────────────────────────────

const PAGE_SIZE = 25

const EVENT_TYPES = [
  "login_success", "login_failed", "login_blocked",
  "account_locked", "account_unlocked",
  "logout", "token_refreshed",
  "password_reset_requested", "password_reset_success",
  "role_changed", "user_created", "user_deleted",
  "data_export", "admin_data_access",
  "suspicious_activity", "rate_limit_breach",
]

const EVENT_COLORS: Record<string, string> = {
  login_success: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300",
  login_failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  login_blocked: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  account_locked: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  account_unlocked: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  logout: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  token_refreshed: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  password_reset_requested: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  password_reset_success: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300",
  role_changed: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  user_created: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300",
  user_deleted: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  data_export: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  admin_data_access: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  suspicious_activity: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  rate_limit_breach: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
}

const EVENT_ICONS: Record<string, React.ReactNode> = {
  login_success: <LogIn className="h-3.5 w-3.5" />,
  login_failed: <LogIn className="h-3.5 w-3.5" />,
  login_blocked: <Lock className="h-3.5 w-3.5" />,
  account_locked: <Lock className="h-3.5 w-3.5" />,
  account_unlocked: <Lock className="h-3.5 w-3.5" />,
  logout: <LogOut className="h-3.5 w-3.5" />,
  role_changed: <UserCog className="h-3.5 w-3.5" />,
  data_export: <Download className="h-3.5 w-3.5" />,
  suspicious_activity: <AlertTriangle className="h-3.5 w-3.5" />,
  password_reset_requested: <KeyRound className="h-3.5 w-3.5" />,
  password_reset_success: <KeyRound className="h-3.5 w-3.5" />,
}

function shortId(id: string | null) {
  if (!id) return "—"
  return id.slice(0, 8) + "…"
}

function fmtDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" })
    + " " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

// ── sub-components ───────────────────────────────────────────────────────────

function EventTypeBadge({ type }: { type: string }) {
  const cls = EVENT_COLORS[type] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
  const icon = EVENT_ICONS[type]
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {icon}
      {type.replace(/_/g, " ")}
    </span>
  )
}

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className={`rounded-xl border p-4 ${accent ?? "border-border"}`}>
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  )
}

function ClassificationBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    PUBLIC: "bg-slate-100 text-slate-600",
    INTERNAL: "bg-blue-100 text-blue-700",
    CONFIDENTIAL: "bg-amber-100 text-amber-700",
    RESTRICTED: "bg-red-100 text-red-700",
  }
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${styles[level] ?? "bg-slate-100"}`}>
      {level}
    </span>
  )
}

// ── main page ────────────────────────────────────────────────────────────────

export default function SecurityPage() {
  const [events, setEvents] = useState<EventsResponse | null>(null)
  const [compliance, setCompliance] = useState<ComplianceSummary | null>(null)
  const [loadingEvents, setLoadingEvents] = useState(true)
  const [loadingCompliance, setLoadingCompliance] = useState(true)

  // filters
  const [eventType, setEventType] = useState<string>("all")
  const [userId, setUserId] = useState("")
  const [ipAddress, setIpAddress] = useState("")
  const [page, setPage] = useState(0)

  const fetchEvents = useCallback(async () => {
    setLoadingEvents(true)
    try {
      const params = new URLSearchParams()
      if (eventType && eventType !== "all") params.set("event_type", eventType)
      if (userId.trim()) params.set("user_id", userId.trim())
      if (ipAddress.trim()) params.set("ip_address", ipAddress.trim())
      params.set("limit", String(PAGE_SIZE))
      params.set("offset", String(page * PAGE_SIZE))
      const data = await apiFetch<EventsResponse>(`/admin/security-events?${params}`)
      setEvents(data)
    } catch {
      setEvents(null)
    } finally {
      setLoadingEvents(false)
    }
  }, [eventType, userId, ipAddress, page])

  const fetchCompliance = useCallback(async () => {
    setLoadingCompliance(true)
    try {
      const data = await apiFetch<ComplianceSummary>("/admin/compliance-summary")
      setCompliance(data)
    } catch {
      setCompliance(null)
    } finally {
      setLoadingCompliance(false)
    }
  }, [])

  useEffect(() => { fetchEvents() }, [fetchEvents])
  useEffect(() => { fetchCompliance() }, [fetchCompliance])

  const totalPages = events ? Math.ceil(events.total / PAGE_SIZE) : 0

  return (
    <AppShell>
      <div className="main-content space-y-6">

        {/* Header */}
        <div className="page-hero">
          <p className="section-caption">Administration</p>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="mt-2 text-3xl font-bold text-foreground text-balance">Sécurité & Conformité</h2>
              <p className="mt-2 text-sm text-muted-foreground max-w-2xl">
                Journal d'audit des événements de sécurité et tableau de bord de conformité ISO 27001 / ISO 42001.
              </p>
            </div>
            <Button
              variant="outline" size="sm"
              onClick={() => { fetchEvents(); fetchCompliance() }}
              className="shrink-0 gap-2"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Actualiser
            </Button>
          </div>
        </div>

        {/* ── Compliance Summary ─────────────────────────────────────────── */}
        {compliance && (
          <div className="space-y-4">
            {/* ISO 27001 */}
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <ShieldCheck className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-sm">ISO 27001 — Sécurité de l'information</h3>
                <Badge variant="outline" className="ml-auto text-xs">
                  Rétention {compliance.iso_27001.audit_log_retention_days}j
                </Badge>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                <StatCard
                  label="Événements totaux"
                  value={compliance.iso_27001.total_security_events.toLocaleString()}
                />
                <StatCard
                  label="Derniers 30 jours"
                  value={Object.values(compliance.iso_27001.events_last_30d).reduce((a, b) => a + b, 0)}
                />
                <StatCard
                  label="Types d'événements"
                  value={Object.keys(compliance.iso_27001.events_last_30d).length}
                  sub="sur 30 jours"
                />
                <StatCard
                  label="Rétention audit"
                  value={`${compliance.iso_27001.audit_log_retention_days}j`}
                  sub="AUDIT_LOG_RETENTION_DAYS"
                />
              </div>

              {/* Events last 30d breakdown */}
              {Object.keys(compliance.iso_27001.events_last_30d).length > 0 && (
                <div className="mb-5">
                  <p className="text-xs text-muted-foreground font-medium mb-2">Répartition sur 30 jours</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(compliance.iso_27001.events_last_30d)
                      .sort(([, a], [, b]) => b - a)
                      .map(([type, count]) => (
                        <div key={type} className="flex items-center gap-1.5">
                          <EventTypeBadge type={type} />
                          <span className="text-xs font-semibold text-foreground">{count}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Data classification */}
              <div className="mb-5">
                <p className="text-xs text-muted-foreground font-medium mb-2">Classification des données (A.8.2)</p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {Object.entries(compliance.iso_27001.data_classification).map(([asset, level]) => (
                    <div key={asset} className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-xs">
                      <span className="text-muted-foreground capitalize">{asset.replace(/_/g, " ")}</span>
                      <ClassificationBadge level={level} />
                    </div>
                  ))}
                </div>
              </div>

              {/* Controls */}
              <div>
                <p className="text-xs text-muted-foreground font-medium mb-2">Contrôles implémentés</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                  {compliance.iso_27001.controls_implemented.map((ctrl) => (
                    <div key={ctrl} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                      {ctrl}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ISO 42001 */}
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <ShieldCheck className="h-4 w-4 text-purple-500" />
                <h3 className="font-semibold text-sm">ISO 42001 — Gouvernance de l'IA</h3>
                <Badge variant="outline" className="ml-auto text-xs text-purple-600 border-purple-300">
                  {compliance.iso_42001.human_review_rate_pct}% supervisé
                </Badge>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                <StatCard
                  label="Décisions IA totales"
                  value={compliance.iso_42001.total_ai_classification_decisions.toLocaleString()}
                />
                <StatCard
                  label="Supervisées par humain"
                  value={compliance.iso_42001.human_reviewed}
                  sub={`${compliance.iso_42001.human_review_rate_pct}% du total`}
                  accent={compliance.iso_42001.human_review_rate_pct >= 50 ? "border-teal-300 dark:border-teal-700" : "border-amber-300 dark:border-amber-700"}
                />
                <StatCard
                  label="Corrigées par humain"
                  value={compliance.iso_42001.human_overridden}
                  sub="avec raison de correction"
                />
                <StatCard
                  label="Sources de décision"
                  value={Object.keys(compliance.iso_42001.decisions_by_source).length}
                  sub="llm · semantic · fallback"
                />
              </div>

              {/* By source + confidence */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
                <div>
                  <p className="text-xs text-muted-foreground font-medium mb-2">Par source de décision</p>
                  {Object.entries(compliance.iso_42001.decisions_by_source).map(([src, n]) => {
                    const total = Object.values(compliance.iso_42001.decisions_by_source).reduce((a, b) => a + b, 0)
                    const pct = total ? Math.round((n / total) * 100) : 0
                    return (
                      <div key={src} className="flex items-center gap-2 mb-1.5">
                        <span className="w-20 text-xs capitalize">{src}</span>
                        <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                          <div className="h-full bg-purple-400 rounded-full" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-xs text-muted-foreground w-12 text-right">{n} ({pct}%)</span>
                      </div>
                    )
                  })}
                </div>
                <div>
                  <p className="text-xs text-muted-foreground font-medium mb-2">Par bande de confiance</p>
                  {Object.entries(compliance.iso_42001.decisions_by_confidence).map(([band, n]) => {
                    const total = Object.values(compliance.iso_42001.decisions_by_confidence).reduce((a, b) => a + b, 0)
                    const pct = total ? Math.round((n / total) * 100) : 0
                    const color = band === "high" ? "bg-teal-400" : band === "medium" ? "bg-amber-400" : "bg-red-400"
                    return (
                      <div key={band} className="flex items-center gap-2 mb-1.5">
                        <span className="w-20 text-xs capitalize">{band}</span>
                        <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                          <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-xs text-muted-foreground w-12 text-right">{n} ({pct}%)</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Controls */}
              <div>
                <p className="text-xs text-muted-foreground font-medium mb-2">Contrôles implémentés</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                  {compliance.iso_42001.controls_implemented.map((ctrl) => (
                    <div key={ctrl} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-purple-500" />
                      {ctrl}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {loadingCompliance && !compliance && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            Chargement du résumé de conformité…
          </div>
        )}

        {/* ── Security Events Log ────────────────────────────────────────── */}
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <h3 className="font-semibold text-sm">Journal des événements de sécurité</h3>
              {events && (
                <p className="text-xs text-muted-foreground mt-0.5">
                  {events.total.toLocaleString()} événements au total
                </p>
              )}
            </div>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-border bg-muted/30">
            <Select value={eventType} onValueChange={(v) => { setEventType(v); setPage(0) }}>
              <SelectTrigger className="h-8 w-48 text-xs">
                <SelectValue placeholder="Type d'événement" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les types</SelectItem>
                {EVENT_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Input
              placeholder="User ID (UUID)"
              value={userId}
              onChange={(e) => { setUserId(e.target.value); setPage(0) }}
              className="h-8 w-56 text-xs"
            />

            <Input
              placeholder="Adresse IP"
              value={ipAddress}
              onChange={(e) => { setIpAddress(e.target.value); setPage(0) }}
              className="h-8 w-36 text-xs"
            />

            {(eventType !== "all" || userId || ipAddress) && (
              <Button
                variant="ghost" size="sm"
                onClick={() => { setEventType("all"); setUserId(""); setIpAddress(""); setPage(0) }}
                className="h-8 text-xs text-muted-foreground"
              >
                Réinitialiser
              </Button>
            )}
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-40">Horodatage</TableHead>
                  <TableHead className="w-52">Événement</TableHead>
                  <TableHead className="w-28">User ID</TableHead>
                  <TableHead className="w-28">Actor ID</TableHead>
                  <TableHead className="w-32">IP</TableHead>
                  <TableHead>Métadonnées / Note</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loadingEvents && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">
                      Chargement…
                    </TableCell>
                  </TableRow>
                )}
                {!loadingEvents && events?.items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">
                      Aucun événement trouvé pour ces filtres.
                    </TableCell>
                  </TableRow>
                )}
                {!loadingEvents && events?.items.map((ev) => (
                  <TableRow key={ev.id} className="text-xs">
                    <TableCell className="font-mono text-muted-foreground whitespace-nowrap">
                      {fmtDate(ev.created_at)}
                    </TableCell>
                    <TableCell>
                      <EventTypeBadge type={ev.event_type} />
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground" title={ev.user_id ?? ""}>
                      {shortId(ev.user_id)}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground" title={ev.actor_id ?? ""}>
                      {ev.actor_id && ev.actor_id !== ev.user_id ? shortId(ev.actor_id) : "—"}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      {ev.ip_address ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground max-w-xs truncate">
                      {ev.note
                        ? ev.note
                        : Object.keys(ev.metadata).length > 0
                          ? Object.entries(ev.metadata)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(" · ")
                          : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-border">
              <span className="text-xs text-muted-foreground">
                Page {page + 1} / {totalPages} · {events?.total} événements
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline" size="sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline" size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>

      </div>
    </AppShell>
  )
}
