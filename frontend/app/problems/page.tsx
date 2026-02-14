"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { Activity, ExternalLink, Repeat2, Search, ShieldCheck, Users } from "lucide-react"
import { AppShell } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
import { useI18n } from "@/lib/i18n"
import { CATEGORY_CONFIG } from "@/lib/ticket-data"
import { fetchProblems, type ProblemListItem, type ProblemStatus } from "@/lib/problems-api"

const PROBLEM_STATUS_CONFIG: Record<ProblemStatus, { color: string; labelFr: string; labelEn: string }> = {
  open: { color: "bg-blue-100 text-blue-800", labelFr: "Ouvert", labelEn: "Open" },
  investigating: { color: "bg-amber-100 text-amber-800", labelFr: "En investigation", labelEn: "Investigating" },
  known_error: { color: "bg-orange-100 text-orange-800", labelFr: "Erreur connue", labelEn: "Known error" },
  resolved: { color: "bg-emerald-100 text-emerald-800", labelFr: "Resolu", labelEn: "Resolved" },
  closed: { color: "bg-slate-100 text-slate-700", labelFr: "Ferme", labelEn: "Closed" },
}

function statusLabel(status: ProblemStatus, locale: string): string {
  const config = PROBLEM_STATUS_CONFIG[status]
  return locale === "fr" ? config.labelFr : config.labelEn
}

function isActiveProblem(status: ProblemStatus): boolean {
  return status === "open" || status === "investigating" || status === "known_error"
}

export default function ProblemsPage() {
  const { t, locale } = useI18n()
  const [problems, setProblems] = useState<ProblemListItem[]>([])
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [categoryFilter, setCategoryFilter] = useState<string>("all")
  const [assigneeFilter, setAssigneeFilter] = useState<string>("all")

  useEffect(() => {
    fetchProblems().then(setProblems).catch(() => {})
  }, [])

  const assigneeOptions = useMemo(() => {
    return Array.from(new Set(problems.map((problem) => (problem.assignee || "").trim()).filter(Boolean))).sort((a, b) =>
      a.localeCompare(b),
    )
  }, [problems])

  const filteredProblems = useMemo(() => {
    let rows = [...problems]
    const q = search.trim().toLowerCase()
    if (q) {
      rows = rows.filter((problem) => {
        const assignee = (problem.assignee || "").toLowerCase()
        return problem.id.toLowerCase().includes(q) || problem.title.toLowerCase().includes(q) || assignee.includes(q)
      })
    }
    if (statusFilter !== "all") {
      rows = rows.filter((problem) => problem.status === statusFilter)
    }
    if (categoryFilter !== "all") {
      rows = rows.filter((problem) => problem.category === categoryFilter)
    }
    if (assigneeFilter !== "all") {
      rows = rows.filter((problem) => (problem.assignee || "").trim() === assigneeFilter)
    }
    rows.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    return rows
  }, [assigneeFilter, categoryFilter, problems, search, statusFilter])

  const summary = useMemo(() => {
    return {
      activeProblems: filteredProblems.filter((problem) => isActiveProblem(problem.status)).length,
      resolvedProblems: filteredProblems.filter((problem) => !isActiveProblem(problem.status)).length,
      activeTickets: filteredProblems.reduce((sum, problem) => sum + (problem.activeCount || 0), 0),
      occurrences: filteredProblems.reduce((sum, problem) => sum + (problem.occurrencesCount || 0), 0),
    }
  }, [filteredProblems])

  const hasFilters = Boolean(search.trim()) || statusFilter !== "all" || categoryFilter !== "all" || assigneeFilter !== "all"

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero overflow-hidden">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(46,148,97,0.18),transparent_45%),radial-gradient(circle_at_20%_90%,rgba(217,119,6,0.15),transparent_45%)]" />
          <div className="relative">
            <p className="section-caption">{t("nav.problems")}</p>
            <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">{t("problems.title")}</h2>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">{t("problems.subtitle")}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            icon={Activity}
            label={locale === "fr" ? "Problemes actifs" : "Active problems"}
            value={summary.activeProblems}
            tone="emerald"
          />
          <SummaryCard
            icon={ShieldCheck}
            label={locale === "fr" ? "Problemes resolus" : "Resolved problems"}
            value={summary.resolvedProblems}
            tone="slate"
          />
          <SummaryCard
            icon={Users}
            label={locale === "fr" ? "Tickets actifs lies" : "Linked active tickets"}
            value={summary.activeTickets}
            tone="amber"
          />
          <SummaryCard
            icon={Repeat2}
            label={locale === "fr" ? "Occurrences total" : "Total occurrences"}
            value={summary.occurrences}
            tone="blue"
          />
        </div>

        <div className="space-y-4">
          <div className="surface-card rounded-xl p-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <div className="relative min-w-[220px] flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder={t("tickets.search")}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-full sm:w-44">
                  <SelectValue placeholder={t("tickets.status")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("tickets.allStatuses")}</SelectItem>
                  <SelectItem value="open">{statusLabel("open", locale)}</SelectItem>
                  <SelectItem value="investigating">{statusLabel("investigating", locale)}</SelectItem>
                  <SelectItem value="known_error">{statusLabel("known_error", locale)}</SelectItem>
                  <SelectItem value="resolved">{statusLabel("resolved", locale)}</SelectItem>
                  <SelectItem value="closed">{statusLabel("closed", locale)}</SelectItem>
                </SelectContent>
              </Select>
              <Select value={assigneeFilter} onValueChange={setAssigneeFilter}>
                <SelectTrigger className="w-full sm:w-44">
                  <SelectValue placeholder={t("tickets.assignee")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{locale === "fr" ? "Tous les assignes" : "All assignees"}</SelectItem>
                  {assigneeOptions.map((name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                <SelectTrigger className="w-full sm:w-48">
                  <SelectValue placeholder={t("tickets.category")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("tickets.allCategories")}</SelectItem>
                  {Object.entries(CATEGORY_CONFIG).map(([key, value]) => (
                    <SelectItem key={key} value={key}>
                      {value.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {hasFilters && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9"
                  onClick={() => {
                    setSearch("")
                    setStatusFilter("all")
                    setCategoryFilter("all")
                    setAssigneeFilter("all")
                  }}
                >
                  {t("general.clear")}
                </Button>
              )}
            </div>
          </div>

          <Card className="surface-card overflow-hidden rounded-2xl">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="w-24 text-foreground font-semibold">{t("tickets.id")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("tickets.titleCol")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("tickets.status")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("tickets.assignee")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("tickets.category")}</TableHead>
                    <TableHead className="text-foreground font-semibold">
                      {locale === "fr" ? "Occurrences" : "Occurrences"}
                    </TableHead>
                    <TableHead className="text-foreground font-semibold">{t("tickets.date")}</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredProblems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="py-12 text-center text-muted-foreground">
                        {t("problems.noData")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredProblems.map((problem) => (
                      <TableRow key={problem.id} className="transition-colors hover:bg-muted/30">
                        <TableCell className="font-mono text-xs font-medium text-primary">{problem.id}</TableCell>
                        <TableCell className="max-w-xs">
                          <Link
                            href={`/problems/${problem.id}`}
                            className="font-medium text-foreground hover:text-primary transition-colors line-clamp-1"
                          >
                            {problem.title}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge className={`${PROBLEM_STATUS_CONFIG[problem.status].color} border-0 text-xs font-medium`}>
                            {statusLabel(problem.status, locale)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-foreground">{problem.assignee || (locale === "fr" ? "Non assigne" : "Unassigned")}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {CATEGORY_CONFIG[problem.category]?.label || problem.category}
                        </TableCell>
                        <TableCell className="text-xs text-foreground">
                          {problem.occurrencesCount} | {problem.activeCount} {locale === "fr" ? "actifs" : "active"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(problem.lastSeenAt || problem.updatedAt).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })}
                        </TableCell>
                        <TableCell>
                          <Link href={`/problems/${problem.id}`}>
                            <Button variant="ghost" size="sm" className="h-8 w-8 rounded-full p-0 hover:bg-primary/10">
                              <ExternalLink className="h-3.5 w-3.5" />
                              <span className="sr-only">Open problem {problem.id}</span>
                            </Button>
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </Card>

          <p className="text-xs text-muted-foreground text-right">
            {filteredProblems.length} {locale === "fr" ? "probleme(s) affiche(s)" : "problem(s) shown"}
          </p>
        </div>
      </div>
    </AppShell>
  )
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  tone: "emerald" | "slate" | "amber" | "blue"
}) {
  const toneMap: Record<string, string> = {
    emerald: "from-emerald-500/20 to-emerald-300/5 border-emerald-400/30",
    slate: "from-slate-400/20 to-slate-200/5 border-slate-400/30",
    amber: "from-amber-500/20 to-amber-300/5 border-amber-400/30",
    blue: "from-sky-500/20 to-sky-300/5 border-sky-400/30",
  }
  return (
    <Card className={`surface-card overflow-hidden rounded-xl border bg-gradient-to-br ${toneMap[tone]}`}>
      <div className="flex items-center justify-between px-4 py-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-bold text-foreground">{value}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/60 p-2">
          <Icon className="h-4 w-4 text-primary" />
        </div>
      </div>
    </Card>
  )
}
