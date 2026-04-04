"use client"

import React from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import {
  getNotifications,
  getUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/lib/notifications-api"
import { apiFetch } from "@/lib/api"
import { globalSearch, type SearchResponse } from "@/lib/search-api"
import { Bell, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import Link from "next/link"

const ROLE_BADGE: Record<string, string> = {
  admin: "bg-red-100 text-red-800 border border-red-200",
  agent: "bg-sky-100 text-sky-800 border border-sky-200",
  user: "bg-emerald-100 text-emerald-800 border border-emerald-200",
  viewer: "bg-slate-100 text-slate-700 border border-slate-200",
}
const SIDEBAR_COLLAPSE_STORAGE_KEY = "teamwil.sidebar.collapsed"

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth()
  const { t } = useI18n()
  const router = useRouter()
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false)
  const [notifOpen, setNotifOpen] = React.useState(false)
  const [unreadCount, setUnreadCount] = React.useState(0)
  const [notifications, setNotifications] = React.useState<NotificationItem[]>([])
  const [loadingNotifications, setLoadingNotifications] = React.useState(false)
  const [markingAll, setMarkingAll] = React.useState(false)
  const [markingId, setMarkingId] = React.useState<string | null>(null)
  const [mediumLowExpanded, setMediumLowExpanded] = React.useState(false)
  const seenCriticalRef = React.useRef<Set<string>>(new Set())

  // Feature 6: Global search state
  const [searchQuery, setSearchQuery] = React.useState("")
  const [searchResults, setSearchResults] = React.useState<SearchResponse | null>(null)
  const [searchOpen, setSearchOpen] = React.useState(false)
  const [searchLoading, setSearchLoading] = React.useState(false)
  const searchRef = React.useRef<HTMLInputElement>(null)
  const searchContainerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (typeof window === "undefined") return
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY)
    if (stored === "1") {
      setSidebarCollapsed(true)
    }
  }, [])

  React.useEffect(() => {
    if (typeof window === "undefined") return
    window.localStorage.setItem(SIDEBAR_COLLAPSE_STORAGE_KEY, sidebarCollapsed ? "1" : "0")
  }, [sidebarCollapsed])

  const initials = user
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "??"

  const loadUnreadCount = React.useCallback(async () => {
    if (!user) return
    try {
      const data = await getUnreadNotificationCount()
      setUnreadCount(data.count)
    } catch {
      // keep existing value on transient failures
    }
  }, [user])

  const loadNotifications = React.useCallback(async () => {
    if (!user) return
    setLoadingNotifications(true)
    try {
      const data = await getNotifications({ limit: 10 })
      setNotifications(data)
    } catch {
      setNotifications([])
    } finally {
      setLoadingNotifications(false)
    }
  }, [user])

  React.useEffect(() => {
    if (!user) return
    loadUnreadCount()
    const timer = window.setInterval(loadUnreadCount, 30_000)
    return () => window.clearInterval(timer)
  }, [user, loadUnreadCount])

  React.useEffect(() => {
    if (!user) return
    const onFocus = () => {
      loadUnreadCount().catch(() => {})
    }
    window.addEventListener("focus", onFocus)
    return () => window.removeEventListener("focus", onFocus)
  }, [user, loadUnreadCount])

  React.useEffect(() => {
    if (!user) return
    const onNotificationsChanged = () => {
      loadUnreadCount().catch(() => {})
      if (notifOpen) {
        loadNotifications().catch(() => {})
      }
    }
    window.addEventListener("notifications:changed", onNotificationsChanged as EventListener)
    return () => window.removeEventListener("notifications:changed", onNotificationsChanged as EventListener)
  }, [user, notifOpen, loadUnreadCount, loadNotifications])

  // Feature 6: Cmd+K / Ctrl+K keyboard shortcut to open search
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setSearchOpen(true)
        setTimeout(() => searchRef.current?.focus(), 50)
      }
      if (e.key === "Escape") {
        setSearchOpen(false)
        setSearchQuery("")
        setSearchResults(null)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [])

  // Feature 6: Debounced search effect (300ms)
  React.useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults(null)
      return
    }
    const timeout = setTimeout(async () => {
      setSearchLoading(true)
      try {
        const r = await globalSearch(searchQuery, ["tickets", "problems"], 5)
        setSearchResults(r)
      } finally {
        setSearchLoading(false)
      }
    }, 300)
    return () => clearTimeout(timeout)
  }, [searchQuery])

  // Feature 6: Click outside to close search dropdown
  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setSearchOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const severityClasses: Record<string, string> = {
    info: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-900/80 dark:text-slate-100 dark:border-slate-600",
    high: "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-950/80 dark:text-orange-100 dark:border-orange-500/50",
    warning: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/80 dark:text-amber-100 dark:border-amber-500/50",
    critical: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950/80 dark:text-red-100 dark:border-red-500/50",
  }

  const formatRelativeTime = (iso: string) => {
    const dt = new Date(iso).getTime()
    const now = Date.now()
    const diffSec = Math.max(1, Math.floor((now - dt) / 1000))
    if (diffSec < 60) return `${diffSec}s ago`
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour}h ago`
    const diffDay = Math.floor(diffHour / 24)
    return `${diffDay}d ago`
  }

  const onOpenNotifications = async (open: boolean) => {
    setNotifOpen(open)
    if (open) {
      setMediumLowExpanded(false)
      await Promise.all([loadNotifications(), loadUnreadCount()])
    }
  }

  React.useEffect(() => {
    if (!notifications.length) return
    if (typeof window === "undefined" || !("Notification" in window)) return

    const criticalUnread = notifications.filter((item) => item.severity === "critical" && !item.read_at)
    if (!criticalUnread.length) return

    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => {})
      return
    }
    if (Notification.permission !== "granted") return

    for (const item of criticalUnread) {
      if (seenCriticalRef.current.has(item.id)) continue
      seenCriticalRef.current.add(item.id)
      new Notification(item.title, {
        body: item.body || "Critical alert",
      })
    }
  }, [notifications])

  const onNotificationClick = async (item: NotificationItem) => {
    if (!item.read_at) {
      try {
        setMarkingId(item.id)
        await markNotificationRead(item.id)
      } catch {
        // keep UX moving even if mark-read fails
      } finally {
        setMarkingId(null)
      }
    }

    setNotifications((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)))
    loadUnreadCount().catch(() => {})
    loadNotifications().catch(() => {})
    if (item.link) {
      router.push(item.link)
      setNotifOpen(false)
    }
  }

  const markNotificationReadSilently = async (item: NotificationItem) => {
    if (item.read_at) return
    try {
      setMarkingId(item.id)
      await markNotificationRead(item.id)
    } catch {
      // keep UX moving even if mark-read fails
    } finally {
      setMarkingId(null)
    }
    setNotifications((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)))
    loadUnreadCount().catch(() => {})
  }

  const onMarkAllAsRead = async () => {
    try {
      setMarkingAll(true)
      await markAllNotificationsRead()
      await Promise.all([loadNotifications(), loadUnreadCount()])
    } finally {
      setMarkingAll(false)
    }
  }

  const ticketIdFromNotification = (item: NotificationItem): string | null => {
    const fromPayload = String(item.action_payload?.ticket_id || item.metadata_json?.ticket_id || "").trim()
    if (fromPayload) return fromPayload
    const link = String(item.link || "")
    const match = link.match(/\/tickets\/([^/?#]+)/)
    return match?.[1] || null
  }

  const assigneeFromNotification = (item: NotificationItem): string | null => {
    const value = String(item.action_payload?.assignee || item.metadata_json?.assignee || "").trim()
    return value || null
  }

  const actionLabel = (actionType: string | null | undefined): string => {
    const normalized = String(actionType || "").toLowerCase()
    if (normalized === "reassign") return "Reassign"
    if (normalized === "approve") return "Approve"
    if (normalized === "escalate") return "Escalate"
    if (normalized === "dismiss") return "Dismiss"
    return normalized || "Action"
  }

  const eventLabel = (eventType: string | null | undefined): string => {
    const normalized = String(eventType || "").replace(/_/g, " ").trim()
    if (!normalized) return "update"
    return normalized.charAt(0).toUpperCase() + normalized.slice(1)
  }

  const onInlineAction = async (item: NotificationItem, actionType: string) => {
    const normalized = String(actionType || "").toLowerCase()
    if (normalized === "dismiss") {
      await markNotificationReadSilently(item)
      return
    }
    const ticketId = ticketIdFromNotification(item)
    if (!ticketId) return
    try {
      if (normalized === "reassign") {
        const assignee = assigneeFromNotification(item)
        if (!assignee) return
        await apiFetch(`/tickets/${ticketId}/triage`, {
          method: "PATCH",
          body: JSON.stringify({
            assignee,
            comment: "Applied from SLA high-risk notification action.",
          }),
        })
      } else {
        const endpoint = normalized === "approve" ? `/tickets/${ticketId}/approve` : `/tickets/${ticketId}/escalate`
        await apiFetch(endpoint, { method: "PATCH" })
      }
      await markNotificationReadSilently(item)
    } catch {
      // no-op; keep item visible if action endpoint is unavailable
    }
  }

  const criticalItems = React.useMemo(() => notifications.filter((n) => n.severity === "critical"), [notifications])
  const highItems = React.useMemo(
    () => notifications.filter((n) => n.severity === "high" || n.severity === "warning"),
    [notifications]
  )
  const mediumLowItems = React.useMemo(
    () => notifications.filter((n) => n.severity !== "critical" && n.severity !== "high" && n.severity !== "warning"),
    [notifications]
  )

  return (
    <div className="relative flex h-screen overflow-hidden bg-transparent">
      <AppSidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((prev) => !prev)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="relative z-20 flex h-[4.25rem] shrink-0 items-center justify-between border-b border-border/70 bg-card/85 px-4 backdrop-blur md:px-6">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-primary/25 to-transparent" />
          <div className="flex flex-1 items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              className="h-9 w-9 rounded-full p-0 hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
              <span className="sr-only">{t("nav.collapse")}</span>
            </Button>
            <h1 className="hidden text-sm font-semibold tracking-wide text-foreground/90 sm:block">
              {t("app.title")}
            </h1>
            {/* Feature 6: Global search input */}
            <div className="relative hidden md:block" ref={searchContainerRef}>
              <input
                ref={searchRef}
                type="search"
                value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); setSearchOpen(true); }}
                onFocus={() => setSearchOpen(true)}
                placeholder={`Rechercher tickets, problèmes...`}
                className="w-64 text-sm px-3 py-1.5 pr-16 rounded-lg border border-border bg-background/80 focus:outline-none focus:ring-2 focus:ring-ring"
                aria-label="Recherche globale"
              />
              <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border-secondary)] bg-[var(--color-background-secondary)] font-mono">⌘K</kbd>
              {searchOpen && (searchResults || searchLoading) && (
                <div
                  className="absolute top-full left-0 mt-1 w-96 rounded-xl border border-border bg-background shadow-xl z-50 overflow-hidden"
                  onMouseDown={(e) => e.preventDefault()}
                >
                  {searchLoading && (
                    <div className="px-4 py-3 text-sm text-muted-foreground">Recherche en cours...</div>
                  )}
                  {searchResults && !searchLoading && searchResults.total_count === 0 && (
                    <div className="px-4 py-3 text-sm text-muted-foreground">
                      Aucun résultat pour « {searchQuery} »
                    </div>
                  )}
                  {searchResults && !searchLoading && searchResults.total_count > 0 && (
                    <>
                      {searchResults.results.tickets.length > 0 && (
                        <div>
                          <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Tickets</div>
                          {searchResults.results.tickets.map((r) => (
                            <a
                              key={r.id}
                              href={r.url}
                              onClick={() => { setSearchOpen(false); setSearchQuery(""); }}
                              className="flex items-start gap-2 px-3 py-2 hover:bg-accent transition-colors"
                            >
                              <span className="mt-0.5 text-muted-foreground">🎫</span>
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{r.title}</div>
                                <div className="text-xs text-muted-foreground truncate">{r.excerpt}</div>
                                {r.status && <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground mt-0.5 inline-block">{r.status}</span>}
                              </div>
                            </a>
                          ))}
                        </div>
                      )}
                      {searchResults.results.problems.length > 0 && (
                        <div className="border-t border-border">
                          <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Problèmes</div>
                          {searchResults.results.problems.map((r) => (
                            <a
                              key={r.id}
                              href={r.url}
                              onClick={() => { setSearchOpen(false); setSearchQuery(""); }}
                              className="flex items-start gap-2 px-3 py-2 hover:bg-accent transition-colors"
                            >
                              <span className="mt-0.5 text-muted-foreground">⚠️</span>
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{r.title}</div>
                                <div className="text-xs text-muted-foreground truncate">{r.excerpt}</div>
                              </div>
                            </a>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <ThemeToggle />

            <DropdownMenu open={notifOpen} onOpenChange={onOpenNotifications}>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="relative h-9 w-9 rounded-full p-0 hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-primary/40">
                  <Bell className="h-4 w-4 text-muted-foreground" />
                  {unreadCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-bold text-primary-foreground ring-2 ring-card/80">
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  )}
                  <span className="sr-only">{t("app.notifications")}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-[360px] p-0" align="end">
                <div className="flex items-center justify-between p-3">
                  <DropdownMenuLabel className="p-0 text-sm">Notifications</DropdownMenuLabel>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={onMarkAllAsRead}
                    disabled={markingAll || unreadCount === 0}
                  >
                    {markingAll ? "Marking..." : "Mark all as read"}
                  </Button>
                </div>
                <DropdownMenuSeparator className="m-0" />
                <div className="max-h-[420px] overflow-y-auto p-2">
                  {loadingNotifications ? (
                    <div className="px-2 py-6 text-center text-sm text-muted-foreground">Loading notifications...</div>
                  ) : notifications.length === 0 ? (
                    <div className="px-2 py-6 text-center text-sm text-muted-foreground">No notifications</div>
                  ) : (
                    <TooltipProvider delayDuration={180}>
                    <div className="space-y-3">
                      <div className="rounded-md border border-red-200 bg-red-50/70 p-1.5 dark:border-red-500/40 dark:bg-red-950/25">
                        <p className="px-1 pb-1 text-[11px] font-semibold text-red-700 dark:text-red-200">Critical ({criticalItems.length})</p>
                        <div className="space-y-1">
                        {criticalItems.length === 0 ? <p className="px-2 py-1 text-[11px] text-muted-foreground">No critical alerts</p> : null}
                        {criticalItems.map((item) => {
                        const unread = !item.read_at
                        return (
                          <Tooltip key={item.id}>
                          <TooltipTrigger asChild>
                          <button
                            type="button"
                            onClick={() => onNotificationClick(item)}
                            disabled={markingId === item.id}
                            className={cn(
                              "w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-accent/50",
                              unread
                                ? "border-primary/30 bg-primary/5 dark:border-emerald-400/50 dark:bg-emerald-500/10"
                                : "border-border/60 bg-background dark:border-slate-600 dark:bg-slate-900/40"
                            )}
                          >
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
                              <Badge className={cn("border text-[10px]", severityClasses[item.severity] || severityClasses.info)}>
                                {item.severity}
                              </Badge>
                            </div>
                            {item.body && <p className="line-clamp-2 text-xs text-muted-foreground dark:text-slate-300">{item.body}</p>}
                            <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground dark:text-slate-400">
                              <span>{formatRelativeTime(item.created_at)}</span>
                              {unread ? (
                                <span className="inline-flex items-center gap-1 font-semibold text-primary dark:text-emerald-300">
                                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary dark:bg-emerald-400" />
                                  Unread
                                </span>
                              ) : null}
                            </div>
                          </button>
                          </TooltipTrigger>
                          <TooltipContent side="left" className="max-w-sm text-xs leading-relaxed">
                            <p className="font-semibold">{item.title}</p>
                            {item.body && <p className="mt-1 text-muted-foreground">{item.body}</p>}
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              Event: {eventLabel(item.event_type)} - Severity: {item.severity}
                              {item.source ? ` - Source: ${item.source}` : ""}
                            </p>
                          </TooltipContent>
                          </Tooltip>
                        )
                      })}
                        </div>
                      </div>

                      <div className="rounded-md border border-orange-200 bg-orange-50/70 p-1.5 dark:border-orange-500/40 dark:bg-orange-950/25">
                        <p className="px-1 pb-1 text-[11px] font-semibold text-orange-700 dark:text-orange-200">High ({highItems.length})</p>
                        <div className="space-y-1">
                        {highItems.length === 0 ? <p className="px-2 py-1 text-[11px] text-muted-foreground">No high alerts</p> : null}
                        {highItems.map((item) => {
                        const unread = !item.read_at
                        return (
                          <Tooltip key={item.id}>
                          <TooltipTrigger asChild>
                          <button
                            type="button"
                            onClick={() => onNotificationClick(item)}
                            disabled={markingId === item.id}
                            className={cn(
                              "w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-accent/50",
                              unread
                                ? "border-primary/30 bg-primary/5 dark:border-emerald-400/50 dark:bg-emerald-500/10"
                                : "border-border/60 bg-background dark:border-slate-600 dark:bg-slate-900/40"
                            )}
                          >
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
                              <Badge className={cn("border text-[10px]", severityClasses[item.severity] || severityClasses.info)}>
                                {item.severity}
                              </Badge>
                            </div>
                            {item.body && <p className="line-clamp-2 text-xs text-muted-foreground dark:text-slate-300">{item.body}</p>}
                            <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground dark:text-slate-400">
                              <span>{formatRelativeTime(item.created_at)}</span>
                              {unread ? (
                                <span className="inline-flex items-center gap-1 font-semibold text-primary dark:text-emerald-300">
                                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary dark:bg-emerald-400" />
                                  Unread
                                </span>
                              ) : null}
                            </div>
                            {item.action_type && item.action_type !== "view" ? (
                              <div className="mt-2 flex justify-end">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-6 px-2 text-[10px]"
                                  onClick={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    onInlineAction(item, item.action_type || "view").catch(() => {})
                                  }}
                                >
                                  {actionLabel(item.action_type)}
                                </Button>
                              </div>
                            ) : null}
                          </button>
                          </TooltipTrigger>
                          <TooltipContent side="left" className="max-w-sm text-xs leading-relaxed">
                            <p className="font-semibold">{item.title}</p>
                            {item.body && <p className="mt-1 text-muted-foreground">{item.body}</p>}
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              Event: {eventLabel(item.event_type)} - Severity: {item.severity}
                              {item.source ? ` - Source: ${item.source}` : ""}
                            </p>
                          </TooltipContent>
                          </Tooltip>
                        )
                      })}
                        </div>
                    </div>

                      <div className="rounded-md border border-slate-200 bg-slate-50/70 p-1.5 dark:border-slate-600 dark:bg-slate-900/30">
                        <button
                          type="button"
                          className="flex w-full items-center justify-between px-1 pb-1 text-left text-[11px] font-semibold text-slate-700 dark:text-slate-200"
                          onClick={() => setMediumLowExpanded((prev) => !prev)}
                        >
                          <span>Medium/Low ({mediumLowItems.length})</span>
                          <span>{mediumLowExpanded ? "Hide" : "Show"}</span>
                        </button>
                        {mediumLowExpanded ? (
                          <div className="space-y-1">
                            {mediumLowItems.length === 0 ? <p className="px-2 py-1 text-[11px] text-muted-foreground">No medium/low alerts</p> : null}
                            {mediumLowItems.map((item) => {
                              const unread = !item.read_at
                              return (
                                <button
                                  key={item.id}
                                  type="button"
                                  onClick={() => onNotificationClick(item)}
                                  disabled={markingId === item.id}
                                  className={cn(
                                    "w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-accent/50",
                                    unread
                                      ? "border-primary/30 bg-primary/5 dark:border-emerald-400/50 dark:bg-emerald-500/10"
                                      : "border-border/60 bg-background dark:border-slate-600 dark:bg-slate-900/40"
                                  )}
                                >
                                  <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
                                    <Badge className={cn("border text-[10px]", severityClasses[item.severity] || severityClasses.info)}>
                                      {item.severity}
                                    </Badge>
                                  </div>
                                  {item.body && <p className="line-clamp-2 text-xs text-muted-foreground dark:text-slate-300">{item.body}</p>}
                                  <div className="mt-1 text-[11px] text-muted-foreground dark:text-slate-400">{formatRelativeTime(item.created_at)}</div>
                                </button>
                              )
                            })}
                          </div>
                        ) : null}
                      </div>
                    </div>
                    </TooltipProvider>
                  )}
                </div>
                <DropdownMenuSeparator className="m-0" />
                <div className="p-2">
                  <Button asChild variant="ghost" size="sm" className="w-full justify-center text-xs">
                    <Link href="/notifications">View all notifications</Link>
                  </Button>
                </div>
              </DropdownMenuContent>
            </DropdownMenu>

            <div className="flex items-center gap-2 rounded-full border border-border/70 bg-card/80 px-1.5 py-1 shadow-sm">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary to-emerald-700 text-xs font-bold text-primary-foreground">
                {initials}
              </div>
              <div className="hidden flex-col md:flex">
                <span className="leading-tight text-sm font-medium text-foreground">
                  {user?.name || t("app.user")}
                </span>
                {user && (
                  <Badge className={`${ROLE_BADGE[user.role]} w-fit px-1.5 py-0 text-[9px]`}>
                    {t(`auth.${user.role}` as "auth.admin")}
                  </Badge>
                )}
              </div>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={signOut}
              className="h-9 w-9 rounded-full p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <LogOut className="h-4 w-4" />
              <span className="sr-only">{t("app.logout")}</span>
            </Button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-5 md:p-6">
          <div className="mx-auto w-full max-w-[1480px]">{children}</div>
        </main>
      </div>
    </div>
  )
}
