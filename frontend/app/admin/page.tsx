"use client"

import { useState, useEffect, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { useAuth, type UserRole, type User, type UserSeniority } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Shield, Users, Trash2, Mail, History, RefreshCw } from "lucide-react"
import Link from "next/link"
import { apiFetch, buildApiUrl } from "@/lib/api"
import { fetchTicketHistory, type TicketHistoryEvent } from "@/lib/tickets-api"

const SENIORITY_OPTIONS: UserSeniority[] = ["intern", "junior", "middle", "senior"]

interface JiraSyncStatus {
  configured: boolean
  project_key: string | null
  base_url: string | null
  auto_reconcile_enabled: boolean
  total_synced_tickets: number
  projects: Array<{
    project_key: string
    last_synced_at: string | null
    last_error: string | null
    updated_at: string | null
  }>
}

interface EmailRecord {
  to: string
  subject: string
  body: string
  sent_at: string
  kind: string
}

function historyActionLabel(event: TicketHistoryEvent, locale: "fr" | "en"): string {
  const action = (event.action || "").toLowerCase()
  if (action === "created") return locale === "fr" ? "Ticket cree" : "Ticket created"
  if (action === "resolved") return locale === "fr" ? "Ticket resolu" : "Ticket resolved"
  if (action === "closed") return locale === "fr" ? "Ticket cloture" : "Ticket closed"
  if (action === "status_changed") return locale === "fr" ? "Statut modifie" : "Status changed"
  if (action === "triage_updated") return locale === "fr" ? "Triage modifie" : "Triage updated"
  if (action === "comment_added") return locale === "fr" ? "Commentaire ajoute" : "Comment added"
  if (action === "status_aligned_from_jira") return locale === "fr" ? "Statut aligne depuis Jira" : "Status aligned from Jira"
  return event.eventType.replace(/_/g, " ").toLowerCase()
}

function historyFieldLabel(field: string, locale: "fr" | "en"): string {
  const map: Record<string, { fr: string; en: string }> = {
    status: { fr: "Statut", en: "Status" },
    priority: { fr: "Priorite", en: "Priority" },
    category: { fr: "Categorie", en: "Category" },
    assignee: { fr: "Assigne", en: "Assignee" },
    problem_id: { fr: "Probleme", en: "Problem" },
    resolution: { fr: "Resolution", en: "Resolution" },
    tags: { fr: "Tags", en: "Tags" },
    assignment_change_count: { fr: "Nb reaffectations", en: "Reassignment count" },
  }
  const key = map[field]
  if (key) return locale === "fr" ? key.fr : key.en
  return field.replace(/_/g, " ")
}

function historyValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-"
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ")
  return String(value)
}

function dateRangeStartMs(value: string): number | null {
  if (!value) return null
  const parsed = new Date(`${value}T00:00:00`).getTime()
  return Number.isNaN(parsed) ? null : parsed
}

function dateRangeEndMs(value: string): number | null {
  if (!value) return null
  const parsed = new Date(`${value}T23:59:59.999`).getTime()
  return Number.isNaN(parsed) ? null : parsed
}

function GrafanaMark({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={className} fill="none">
      <defs>
        <linearGradient id="grafana-mark-gradient" x1="14" y1="10" x2="52" y2="54" gradientUnits="userSpaceOnUse">
          <stop stopColor="#F59E0B" />
          <stop offset="1" stopColor="#F97316" />
        </linearGradient>
      </defs>
      <path
        d="M31.8 10c4.5 0 8.3 3.2 9.2 7.5 1.1-.5 2.3-.8 3.6-.8 4.9 0 8.9 4 8.9 8.9 0 .9-.1 1.8-.4 2.6 3.5 1.5 5.9 5 5.9 9 0 5.4-4.4 9.8-9.8 9.8H17.5c-4.7 0-8.5-3.8-8.5-8.5 0-4.1 2.9-7.6 6.9-8.3-.2-.7-.2-1.4-.2-2.1 0-5.5 4.5-10 10-10 .8 0 1.5.1 2.2.2C28.8 13.4 30.1 10 31.8 10Z"
        fill="url(#grafana-mark-gradient)"
      />
      <circle cx="32" cy="38" r="11" fill="#fff" />
      <circle cx="32" cy="38" r="5.5" fill="#F97316" />
      <circle cx="22.5" cy="24" r="3.4" fill="#F59E0B" />
    </svg>
  )
}

export default function AdminPage() {
  const { user, hasPermission, getAllUsers, updateUserRole, updateUserSeniority, deleteUser } = useAuth()
  const { t, locale } = useI18n()
  const [users, setUsers] = useState<User[]>([])
  const [emails, setEmails] = useState<EmailRecord[]>([])
  const [history, setHistory] = useState<TicketHistoryEvent[]>([])
  const [actionError, setActionError] = useState<string | null>(null)
  const [jiraStatus, setJiraStatus] = useState<JiraSyncStatus | null>(null)
  const [jiraStatusLoading, setJiraStatusLoading] = useState(false)
  const [userSearch, setUserSearch] = useState("")
  const [userRoleFilter, setUserRoleFilter] = useState<"all" | UserRole>("all")
  const [userSeniorityFilter, setUserSeniorityFilter] = useState<"all" | UserSeniority>("all")
  const [historySearch, setHistorySearch] = useState("")
  const [historyDateFrom, setHistoryDateFrom] = useState("")
  const [historyDateTo, setHistoryDateTo] = useState("")

  useEffect(() => {
    getAllUsers().then(setUsers).catch(() => {})
  }, [getAllUsers])

  useEffect(() => {
    apiFetch<EmailRecord[]>("/emails")
      .then(setEmails)
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!hasPermission("view_admin")) {
      setHistory([])
      return
    }
    fetchTicketHistory({ limit: 150 })
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [hasPermission])

  const loadJiraStatus = useCallback(() => {
    setJiraStatusLoading(true)
    apiFetch<JiraSyncStatus>("/integrations/jira/status")
      .then(setJiraStatus)
      .catch(() => setJiraStatus(null))
      .finally(() => setJiraStatusLoading(false))
  }, [])

  useEffect(() => {
    if (hasPermission("view_admin")) loadJiraStatus()
  }, [hasPermission, loadJiraStatus])

  const normalizedUserSearch = userSearch.trim().toLowerCase()
  const filteredUsers = users.filter((candidate) => {
    if (userRoleFilter !== "all" && candidate.role !== userRoleFilter) return false
    if (userSeniorityFilter !== "all" && candidate.seniorityLevel !== userSeniorityFilter) return false
    if (!normalizedUserSearch) return true

    const haystack = [
      candidate.name,
      candidate.email,
      candidate.role,
      candidate.seniorityLevel,
      ...candidate.specializations,
    ]
      .join(" ")
      .toLowerCase()

    return haystack.includes(normalizedUserSearch)
  })

  const historyFromMs = dateRangeStartMs(historyDateFrom)
  const historyToMs = dateRangeEndMs(historyDateTo)
  const normalizedHistorySearch = historySearch.trim().toLowerCase()
  const filteredHistory = history.filter((event) => {
    const createdAtMs = new Date(event.createdAt).getTime()
    if (historyFromMs !== null && !Number.isNaN(createdAtMs) && createdAtMs < historyFromMs) return false
    if (historyToMs !== null && !Number.isNaN(createdAtMs) && createdAtMs > historyToMs) return false
    if (!normalizedHistorySearch) return true

    const changesText = event.changes
      .map((change) => `${change.field} ${historyValue(change.before)} ${historyValue(change.after)}`)
      .join(" ")
      .toLowerCase()
    const haystack = [
      event.ticketId,
      event.actor,
      event.action || "",
      event.eventType,
      historyActionLabel(event, locale),
      changesText,
    ]
      .join(" ")
      .toLowerCase()

    return haystack.includes(normalizedHistorySearch)
  })

  const hasUserFilters = Boolean(normalizedUserSearch) || userRoleFilter !== "all" || userSeniorityFilter !== "all"
  const hasHistoryFilters = Boolean(normalizedHistorySearch) || Boolean(historyDateFrom) || Boolean(historyDateTo)

  if (!hasPermission("view_admin")) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center h-[60vh] text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10 mb-4">
            <Shield className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-xl font-bold text-foreground">{t("admin.accessDenied")}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t("admin.accessDeniedDesc")}</p>
          <Link href="/" className="mt-4">
            <Button variant="outline" className="bg-transparent">
              {t("admin.backToDashboard")}
            </Button>
          </Link>
        </div>
      </AppShell>
    )
  }

  async function handleRoleChange(userId: string, newRole: UserRole) {
    try {
      setActionError(null)
      await updateUserRole(userId, newRole)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de mise a jour du role. Verifiez que le backend est accessible."
          : "Failed to update role. Check backend connectivity."
      )
    }
  }

  async function handleSeniorityChange(userId: string, seniorityLevel: UserSeniority) {
    try {
      setActionError(null)
      await updateUserSeniority(userId, seniorityLevel)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de mise a jour de la seniorite."
          : "Failed to update seniority."
      )
    }
  }

  async function handleDelete(userId: string) {
    try {
      setActionError(null)
      await deleteUser(userId)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de suppression de l'utilisateur."
          : "Failed to delete user."
      )
    }
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("nav.admin")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">{t("admin.title")}</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">{t("admin.subtitle")}</p>
          <div className="mt-3 flex gap-2 flex-wrap">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/analytics">Tableau de bord analytique</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/ai-governance">Gouvernance IA</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/security">Sécurité & Conformité</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/notifications-debug">Notifications debug</Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => window.open(buildApiUrl("/admin/monitoring/grafana"), "_blank", "noopener,noreferrer")}
            >
              <GrafanaMark className="mr-1.5 h-3.5 w-3.5" />
              {locale === "fr" ? "Ouvrir Grafana" : "Open Grafana"}
            </Button>
          </div>
          {actionError && <p className="mt-2 text-sm text-destructive">{actionError}</p>}
        </div>

        {/* Jira Sync Status */}
        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <svg className="h-5 w-5 text-primary" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M11.571 11.429L6 5.857 7.857 4l5.571 5.571 5.572-5.571L21 5.857l-5.572 5.572L21 17l-1.857 1.857-5.572-5.571L8 18.857 6.143 17l5.571-5.571L6 5.857z" fillRule="evenodd" clipRule="evenodd" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {locale === "fr" ? "Intégration Jira" : "Jira Integration"}
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 text-xs"
                onClick={loadJiraStatus}
                disabled={jiraStatusLoading}
              >
                <RefreshCw className={`h-3 w-3 ${jiraStatusLoading ? "animate-spin" : ""}`} />
                {locale === "fr" ? "Actualiser" : "Refresh"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {jiraStatusLoading ? (
              <div className="space-y-2">
                <div className="h-4 w-48 animate-pulse rounded bg-muted/40" />
                <div className="h-4 w-64 animate-pulse rounded bg-muted/40" />
              </div>
            ) : jiraStatus === null ? (
              <p className="text-sm text-muted-foreground py-2">
                {locale === "fr" ? "Impossible de charger le statut Jira." : "Could not load Jira sync status."}
              </p>
            ) : !jiraStatus.configured ? (
              <div className="flex items-center gap-2 py-2">
                <span className="h-2 w-2 rounded-full bg-muted-foreground/40 inline-block" />
                <p className="text-sm text-muted-foreground">
                  {locale === "fr" ? "Variables JIRA_BASE_URL / JIRA_API_TOKEN non configurées." : "JIRA_BASE_URL / JIRA_API_TOKEN not set."}
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-3">
                  <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                    <p className="text-xs text-muted-foreground">{locale === "fr" ? "Tickets synchronisés" : "Synced tickets"}</p>
                    <p className="text-xl font-bold text-foreground mt-0.5">{jiraStatus.total_synced_tickets}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                    <p className="text-xs text-muted-foreground">{locale === "fr" ? "Projet" : "Project"}</p>
                    <p className="text-xl font-bold text-foreground mt-0.5">{jiraStatus.project_key}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                    <p className="text-xs text-muted-foreground">{locale === "fr" ? "Réconciliation auto" : "Auto reconcile"}</p>
                    <p className={`text-sm font-semibold mt-0.5 ${jiraStatus.auto_reconcile_enabled ? "text-[#1D9E75]" : "text-muted-foreground"}`}>
                      {jiraStatus.auto_reconcile_enabled ? (locale === "fr" ? "Activée" : "Enabled") : (locale === "fr" ? "Désactivée" : "Disabled")}
                    </p>
                  </div>
                </div>
                {jiraStatus.projects.length > 0 ? (
                  <div className="space-y-2">
                    {jiraStatus.projects.map((p) => (
                      <div key={p.project_key} className="rounded-lg border border-border bg-muted/10 p-3">
                        <div className="flex items-center justify-between gap-3 flex-wrap">
                          <div className="flex items-center gap-2">
                            <span className={`h-2 w-2 rounded-full inline-block shrink-0 ${p.last_error ? "bg-destructive" : "bg-[#1D9E75]"}`} />
                            <span className="text-sm font-medium text-foreground">{p.project_key}</span>
                          </div>
                          {p.last_synced_at && (
                            <span className="text-xs text-muted-foreground">
                              {locale === "fr" ? "Dernière sync." : "Last sync:"}{" "}
                              {new Date(p.last_synced_at).toLocaleString(locale === "fr" ? "fr-FR" : "en-US")}
                            </span>
                          )}
                        </div>
                        {p.last_error && (
                          <p className="mt-1.5 text-xs text-destructive truncate">{p.last_error}</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {locale === "fr"
                      ? "Aucune réconciliation effectuée. Lancez une sync. manuelle pour initialiser l'état."
                      : "No reconcile run yet. Trigger a manual sync to initialize state."}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Users Table */}
        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Users className="h-5 w-5 text-primary" />
                {t("admin.users")}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {filteredUsers.length}/{users.length} {t("admin.totalUsers")}
              </p>
            </div>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3 sm:flex-row sm:flex-wrap sm:items-center">
              <Input
                value={userSearch}
                onChange={(event) => setUserSearch(event.target.value)}
                placeholder={locale === "fr" ? "Rechercher nom, email ou specialisation" : "Search name, email, or specialization"}
                className="h-9 w-full sm:max-w-sm"
              />
              <Select value={userRoleFilter} onValueChange={(value) => setUserRoleFilter(value as "all" | UserRole)}>
                <SelectTrigger className="h-9 w-full sm:w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{locale === "fr" ? "Tous les roles" : "All roles"}</SelectItem>
                  <SelectItem value="admin">{t("auth.admin")}</SelectItem>
                  <SelectItem value="agent">{t("auth.agent")}</SelectItem>
                  <SelectItem value="user">{t("auth.user")}</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={userSeniorityFilter}
                onValueChange={(value) => setUserSeniorityFilter(value as "all" | UserSeniority)}
              >
                <SelectTrigger className="h-9 w-full sm:w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{locale === "fr" ? "Toutes seniorites" : "All seniority levels"}</SelectItem>
                  {SENIORITY_OPTIONS.map((level) => (
                    <SelectItem key={`filter-${level}`} value={level}>
                      {t(`seniority.${level}` as "seniority.intern")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {hasUserFilters && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9"
                  onClick={() => {
                    setUserSearch("")
                    setUserRoleFilter("all")
                    setUserSeniorityFilter("all")
                  }}
                >
                  {t("general.clear")}
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="text-foreground font-semibold">{t("admin.name")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.email")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.role")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.seniority")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.specializations")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.created")}</TableHead>
                    <TableHead className="text-foreground font-semibold text-right">{t("admin.actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUsers.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-6 text-center text-sm text-muted-foreground">
                        {locale === "fr" ? "Aucun utilisateur ne correspond aux filtres." : "No users match the current filters."}
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredUsers.map((u) => (
                      <TableRow key={u.id} className="hover:bg-[var(--color-background-secondary)] transition-all duration-150">
                        <TableCell className="font-medium text-foreground">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full inline-block flex-shrink-0 ${(u as any).is_available !== false ? "bg-[#1D9E75]" : "bg-[#888780]"}`} title={(u as any).is_available !== false ? "Disponible" : "Indisponible"} />
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold shrink-0">
                              {u.name
                                .split(" ")
                                .map((n) => n[0])
                                .join("")
                                .toUpperCase()
                                .slice(0, 2)}
                            </div>
                            <div>
                              <p className="text-sm font-medium text-foreground">{u.name}</p>
                              {user?.id === u.id && (
                                <span className="text-[10px] text-primary font-medium">({t("admin.you")})</span>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground font-mono">
                          {u.email}
                        </TableCell>
                        <TableCell>
                          <Select
                            value={u.role}
                            onValueChange={(v) => handleRoleChange(u.id, v as UserRole)}
                            disabled={u.id === user?.id}
                          >
                            <SelectTrigger className="w-36 h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="admin">{t("auth.admin")}</SelectItem>
                              <SelectItem value="agent">{t("auth.agent")}</SelectItem>
                              <SelectItem value="user">{t("auth.user")}</SelectItem>
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell>
                          <Select
                            value={u.seniorityLevel}
                            onValueChange={(v) => handleSeniorityChange(u.id, v as UserSeniority)}
                          >
                            <SelectTrigger className="w-36 h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {SENIORITY_OPTIONS.map((level) => (
                                <SelectItem key={`${u.id}-${level}`} value={level}>
                                  {t(`seniority.${level}` as "seniority.intern")}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {u.specializations.length === 0 ? (
                            "-"
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {u.specializations.map((spec) => (
                                <Badge key={`${u.id}-${spec}`} variant="secondary" className="text-[10px]">
                                  {spec.replace(/_/g, " ")}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(u.createdAt).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })}
                        </TableCell>
                        <TableCell className="text-right">
                          {u.id !== user?.id && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive hover:text-destructive">
                                  <Trash2 className="h-3.5 w-3.5" />
                                  <span className="sr-only">{t("admin.deleteUser")}</span>
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>{t("admin.deleteUser")} {u.name} ?</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    {t("admin.deleteConfirm")}
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>{t("form.cancel")}</AlertDialogCancel>
                                  <AlertDialogAction
                                    onClick={() => handleDelete(u.id)}
                                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                  >
                                    {t("general.confirm")}
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <div className="border-t border-[var(--color-border-tertiary)] pt-6 mt-6" />

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <History className="h-5 w-5 text-primary" />
                {locale === "fr" ? "Historique tickets" : "Ticket history"}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {filteredHistory.length}/{history.length}
              </p>
            </div>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3 sm:flex-row sm:flex-wrap sm:items-center">
              <Input
                value={historySearch}
                onChange={(event) => setHistorySearch(event.target.value)}
                placeholder={locale === "fr" ? "Rechercher ticket, acteur ou changement" : "Search ticket, actor, or change"}
                className="h-9 w-full sm:max-w-sm"
              />
              <Input
                type="date"
                value={historyDateFrom}
                onChange={(event) => setHistoryDateFrom(event.target.value)}
                className="h-9 w-full sm:w-44"
              />
              <Input
                type="date"
                value={historyDateTo}
                onChange={(event) => setHistoryDateTo(event.target.value)}
                className="h-9 w-full sm:w-44"
              />
              {hasHistoryFilters && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9"
                  onClick={() => {
                    setHistorySearch("")
                    setHistoryDateFrom("")
                    setHistoryDateTo("")
                  }}
                >
                  {t("general.clear")}
                </Button>
              )}
            </div>
            {filteredHistory.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {locale === "fr" ? "Aucun evenement ne correspond aux filtres." : "No ticket events match the current filters."}
              </p>
            ) : (
              <div className="space-y-3">
                {filteredHistory.map((event) => {
                  const _action = (event.action || "").toLowerCase()
                  const _historyBorder =
                    _action === "resolved" || _action === "closed"
                      ? "border-l-[3px] border-l-[#1D9E75]"
                      : _action === "status_changed" || _action === "status_aligned_from_jira" || _action === "triage_updated"
                      ? "border-l-[3px] border-l-[#378ADD]"
                      : _action.includes("problem") || event.changes?.some((c) => c.field === "problem_id")
                      ? "border-l-[3px] border-l-[#534AB7]"
                      : ""
                  return (
                  <div key={event.id} className={`rounded-lg border border-border bg-muted/20 p-3 ${_historyBorder}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium text-foreground">
                        <Link href={`/tickets/${event.ticketId}`} className="text-primary hover:underline">
                          {event.ticketId}
                        </Link>{" "}
                        - {historyActionLabel(event, locale)}
                      </p>
                      <span className="text-[12px] text-muted-foreground">
                        {new Date(event.createdAt).toLocaleString(locale === "fr" ? "fr-FR" : "en-US")}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {locale === "fr" ? "Par" : "By"} {event.actor}
                    </p>
                    {event.changes.length > 0 && (
                      <div className="mt-2 space-y-1 rounded-md border border-border/70 bg-background/60 p-2">
                        {event.changes.slice(0, 6).map((change, idx) => (
                          <p key={`${event.id}-${change.field}-${idx}`} className="text-[11px] text-muted-foreground">
                            <span className="font-medium text-foreground">{historyFieldLabel(change.field, locale)}</span>:{" "}
                            {historyValue(change.before)} {"->"} {historyValue(change.after)}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Email Log */}
        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Mail className="h-5 w-5 text-primary" />
              {t("admin.emailLogTitle")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {emails.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t("admin.emailLogEmpty")}
              </p>
            ) : (
              <div className="space-y-3">
                {emails.map((em, i) => (
                  <div key={`email-${i}`} className="rounded-lg border border-border p-3 bg-muted/30">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-foreground">{em.to}</span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(em.sent_at).toLocaleString(locale === "fr" ? "fr-FR" : "en-US")}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground font-medium">{em.subject}</p>
                    <pre className="mt-2 text-[11px] text-muted-foreground whitespace-pre-wrap leading-relaxed bg-background rounded p-2 border border-border max-h-40 overflow-auto">
                      {em.body}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
