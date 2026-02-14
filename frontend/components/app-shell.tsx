"use client"

import React from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { Bell, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

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
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false)

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

  return (
    <div className="flex min-h-screen overflow-hidden bg-transparent">
      <AppSidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((prev) => !prev)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="relative z-20 flex h-16 items-center justify-between border-b border-border/70 bg-card/80 px-4 backdrop-blur md:px-6 shrink-0">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-primary/25 to-transparent" />
          <div className="flex items-center gap-4 flex-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              className="h-9 w-9 rounded-full p-0 hover:bg-primary/10"
            >
              {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
              <span className="sr-only">{t("nav.collapse")}</span>
            </Button>
            <h1 className="hidden text-sm font-semibold tracking-wide text-foreground sm:block">
              {t("app.title")}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <ThemeToggle />

            <Button variant="ghost" size="sm" className="relative h-9 w-9 rounded-full p-0 hover:bg-primary/10">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground ring-2 ring-card/80">
                3
              </span>
              <span className="sr-only">{t("app.notifications")}</span>
            </Button>

            <div className="flex items-center gap-2 rounded-full border border-border/70 bg-card/75 px-1.5 py-1 shadow-sm">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary to-emerald-700 text-xs font-bold text-primary-foreground">
                {initials}
              </div>
              <div className="hidden md:flex flex-col">
                <span className="text-sm font-medium text-foreground leading-tight">
                  {user?.name || t("app.user")}
                </span>
                {user && (
                  <Badge className={`${ROLE_BADGE[user.role]} text-[9px] px-1.5 py-0 w-fit`}>
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
        <main className="flex-1 overflow-auto p-4 md:p-6">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>
      </div>
    </div>
  )
}
