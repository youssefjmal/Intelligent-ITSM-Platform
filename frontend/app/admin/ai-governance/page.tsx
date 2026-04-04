"use client"

import { useState, useEffect, useCallback, Fragment } from "react"
import { AppShell } from "@/components/app-shell"
import { apiFetch } from "@/lib/api"
import { Shield, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import Link from "next/link"

interface ClassificationLog {
  id: string
  ticket_id: string | null
  trigger: string
  title: string
  suggested_priority: string | null
  suggested_category: string | null
  suggested_ticket_type: string | null
  confidence: number | null
  confidence_band: string | null
  decision_source: string
  strong_match_count: number | null
  recommendation_mode: string | null
  reasoning: string
  model_version: string
  created_at: string
}

interface LogsResponse {
  total: number
  offset: number
  limit: number
  items: ClassificationLog[]
}

const PAGE_SIZE = 20

function ConfidenceBadge({ band }: { band: string | null }) {
  if (!band) return <span className="text-muted-foreground text-xs">—</span>
  const styles: Record<string, string> = {
    high: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300",
    medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
    low: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[band] ?? "bg-muted text-muted-foreground"}`}>
      {band}
    </span>
  )
}

function SourceBadge({ source }: { source: string }) {
  const styles: Record<string, string> = {
    llm: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
    semantic: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
    fallback: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[source] ?? "bg-muted text-muted-foreground"}`}>
      {source}
    </span>
  )
}

function TriggerBadge({ trigger }: { trigger: string }) {
  const labels: Record<string, string> = {
    draft: "Draft",
    creation: "Création",
    jira_sync: "Jira Sync",
    manual: "Manuel",
  }
  return (
    <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
      {labels[trigger] ?? trigger}
    </span>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  )
}

export default function AIGovernancePage() {
  const [data, setData] = useState<LogsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [ticketFilter, setTicketFilter] = useState("")
  const [sourceFilter, setSourceFilter] = useState("all")
  const [bandFilter, setBandFilter] = useState("all")
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      })
      if (ticketFilter.trim()) params.set("ticket_id", ticketFilter.trim())
      if (sourceFilter !== "all") params.set("decision_source", sourceFilter)
      if (bandFilter !== "all") params.set("confidence_band", bandFilter)
      const result = await apiFetch<LogsResponse>(`/ai/classification-logs?${params}`)
      setData(result)
    } catch {
      setError("Impossible de charger les journaux de classification.")
    } finally {
      setLoading(false)
    }
  }, [page, ticketFilter, sourceFilter, bandFilter])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  // Reset to page 0 when filters change
  useEffect(() => { setPage(0) }, [ticketFilter, sourceFilter, bandFilter])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  // Derived stats from current page
  const llmCount = data?.items.filter(i => i.decision_source === "llm").length ?? 0
  const semanticCount = data?.items.filter(i => i.decision_source === "semantic").length ?? 0
  const fallbackCount = data?.items.filter(i => i.decision_source === "fallback").length ?? 0
  const highConfCount = data?.items.filter(i => i.confidence_band === "high").length ?? 0

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">Administration</p>
          <div className="flex items-center gap-3 mt-2">
            <Shield className="h-7 w-7 text-primary" />
            <h2 className="text-3xl font-bold text-foreground">Gouvernance IA</h2>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Journal d'audit de toutes les décisions de classification IA — priorité, catégorie, type de ticket,
            source de décision et niveau de confiance.
          </p>
          <div className="mt-3 flex gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin">← Retour Admin</Link>
            </Button>
            <Button variant="outline" size="sm" onClick={fetchLogs} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} />
              Actualiser
            </Button>
          </div>
        </div>

        {/* Stats row */}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard label="Total décisions" value={String(data.total)} />
            <StatCard label="LLM" value={String(llmCount)} sub="Décisions via modèle" />
            <StatCard label="Sémantique" value={String(semanticCount)} sub="Correspondance forte" />
            <StatCard label="Haute confiance" value={String(highConfCount)} sub="Sur cette page" />
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <Input
            placeholder="Filtrer par ticket ID…"
            value={ticketFilter}
            onChange={e => setTicketFilter(e.target.value)}
            className="h-9 w-48"
          />
          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="h-9 w-40">
              <SelectValue placeholder="Source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes les sources</SelectItem>
              <SelectItem value="llm">LLM</SelectItem>
              <SelectItem value="semantic">Sémantique</SelectItem>
              <SelectItem value="fallback">Fallback</SelectItem>
            </SelectContent>
          </Select>
          <Select value={bandFilter} onValueChange={setBandFilter}>
            <SelectTrigger className="h-9 w-40">
              <SelectValue placeholder="Confiance" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toute confiance</SelectItem>
              <SelectItem value="high">Haute</SelectItem>
              <SelectItem value="medium">Moyenne</SelectItem>
              <SelectItem value="low">Basse</SelectItem>
            </SelectContent>
          </Select>
          {(ticketFilter || sourceFilter !== "all" || bandFilter !== "all") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setTicketFilter(""); setSourceFilter("all"); setBandFilter("all") }}
            >
              Réinitialiser
            </Button>
          )}
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive mb-4">
            {error}
          </div>
        )}

        {loading && (
          <div className="text-sm text-muted-foreground py-8 text-center">Chargement…</div>
        )}

        {!loading && data && (
          <>
            <div className="rounded-xl border border-border overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40">
                    <TableHead className="text-xs">Date</TableHead>
                    <TableHead className="text-xs">Ticket</TableHead>
                    <TableHead className="text-xs">Déclencheur</TableHead>
                    <TableHead className="text-xs">Priorité</TableHead>
                    <TableHead className="text-xs">Catégorie</TableHead>
                    <TableHead className="text-xs">Type</TableHead>
                    <TableHead className="text-xs">Confiance</TableHead>
                    <TableHead className="text-xs">Source</TableHead>
                    <TableHead className="text-xs">Correspondances</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={9} className="text-center text-sm text-muted-foreground py-10">
                        Aucune décision de classification enregistrée pour ces filtres.
                      </TableCell>
                    </TableRow>
                  )}
                  {data.items.map(row => (
                    <Fragment key={row.id}>
                      <TableRow
                        key={row.id}
                        className="cursor-pointer hover:bg-muted/30 transition-colors"
                        onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}
                      >
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {new Date(row.created_at).toLocaleString("fr-FR", {
                            day: "2-digit", month: "2-digit", year: "2-digit",
                            hour: "2-digit", minute: "2-digit",
                          })}
                        </TableCell>
                        <TableCell className="text-xs font-mono">
                          {row.ticket_id ?? <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell><TriggerBadge trigger={row.trigger} /></TableCell>
                        <TableCell className="text-xs capitalize">{row.suggested_priority ?? "—"}</TableCell>
                        <TableCell className="text-xs">{row.suggested_category ?? "—"}</TableCell>
                        <TableCell className="text-xs">{row.suggested_ticket_type ?? "—"}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <ConfidenceBadge band={row.confidence_band} />
                            {row.confidence != null && (
                              <span className="text-xs text-muted-foreground">
                                {Math.round(row.confidence * 100)}%
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell><SourceBadge source={row.decision_source} /></TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {row.strong_match_count ?? 0}
                        </TableCell>
                      </TableRow>

                      {/* Expanded reasoning row */}
                      {expandedId === row.id && (
                        <TableRow className="bg-muted/20">
                          <TableCell colSpan={9} className="py-3 px-4">
                            <div className="space-y-2">
                              <div>
                                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Titre analysé</span>
                                <p className="text-sm mt-0.5">{row.title || "—"}</p>
                              </div>
                              <div>
                                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Raisonnement IA</span>
                                <p className="text-sm mt-0.5 text-muted-foreground">{row.reasoning || "—"}</p>
                              </div>
                              <div className="flex gap-4 text-xs text-muted-foreground">
                                <span>Mode: <strong>{row.recommendation_mode ?? "—"}</strong></span>
                                <span>Modèle: <strong>{row.model_version || "—"}</strong></span>
                                <span>ID: <span className="font-mono">{row.id}</span></span>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-xs text-muted-foreground">
                  {data.offset + 1}–{Math.min(data.offset + PAGE_SIZE, data.total)} sur {data.total} entrées
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => p - 1)}
                    disabled={page === 0}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="flex items-center text-sm px-2">
                    {page + 1} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => p + 1)}
                    disabled={page >= totalPages - 1}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  )
}
