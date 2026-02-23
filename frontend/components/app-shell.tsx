"use client"

import React from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { getNotifications, getUnreadNotificationCount, markAllNotificationsRead, markNotificationRead, type NotificationItem } from "@/lib/notifications-api"
import { Bell, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"

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
      const data = await getNotifications({ limit: 20 })
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
    const timer = window.setInterval(loadUnreadCount, 20_000)
    return () => window.clearInterval(timer)
  }, [user, loadUnreadCount])

  const severityClasses: Record<string, string> = {
    info: "bg-slate-100 text-slate-700 border-slate-200",
    warning: "bg-amber-100 text-amber-800 border-amber-200",
    critical: "bg-red-100 text-red-800 border-red-200",
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
      await Promise.all([loadNotifications(), loadUnreadCount()])
    }
  }

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
    setUnreadCount((prev) => Math.max(0, prev - (item.read_at ? 0 : 1)))
    if (item.link) {
      router.push(item.link)
      setNotifOpen(false)
    }
  }

  const onMarkAllAsRead = async () => {
    try {
      setMarkingAll(true)
      await markAllNotificationsRead()
      setNotifications((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: new Date().toISOString() })))
      setUnreadCount(0)
    } finally {
      setMarkingAll(false)
    }
  }

  return (
    <div className="relative flex min-h-screen overflow-hidden bg-transparent">
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
                      {unreadCount > 99 ? "99+" : unreadCount}
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
                    <div className="space-y-1">
                      {notifications.map((item) => {
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
                              unread ? "border-primary/30 bg-primary/5" : "border-border/60 bg-background"
                            )}
                          >
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
                              <Badge className={cn("border text-[10px]", severityClasses[item.severity] || severityClasses.info)}>
                                {item.severity}
                              </Badge>
                            </div>
                            {item.body && <p className="line-clamp-2 text-xs text-muted-foreground">{item.body}</p>}
                            <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                              <span>{formatRelativeTime(item.created_at)}</span>
                              {unread && <span className="font-semibold text-primary">Unread</span>}
                            </div>
                          </button>
                          </TooltipTrigger>
                          <TooltipContent side="left" className="max-w-sm text-xs leading-relaxed">
                            <p className="font-semibold">{item.title}</p>
                            {item.body && <p className="mt-1 text-muted-foreground">{item.body}</p>}
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              Severity: {item.severity} {item.source ? ` - Source: ${item.source}` : ""}
                            </p>
                          </TooltipContent>
                          </Tooltip>
                        )
                      })}
                    </div>
                    </TooltipProvider>
                  )}
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
