"use client"

import React from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { Bell, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

const ROLE_BADGE: Record<string, string> = {
  admin: "bg-red-100 text-red-800",
  agent: "bg-blue-100 text-blue-800",
  viewer: "bg-slate-100 text-slate-700",
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth()
  const { t } = useI18n()

  const initials = user
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "??"

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <AppSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="flex h-14 items-center justify-between border-b border-border bg-card px-6 shrink-0">
          <div className="flex items-center gap-4 flex-1">
            <h1 className="text-sm font-semibold text-foreground hidden sm:block">
              {t("app.title")}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <ThemeToggle />

            <Button variant="ghost" size="sm" className="relative h-8 w-8 p-0">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <span className="absolute -top-0.5 -right-0.5 h-3.5 w-3.5 rounded-full bg-primary text-[9px] font-bold text-primary-foreground flex items-center justify-center">
                3
              </span>
              <span className="sr-only">{t("app.notifications")}</span>
            </Button>

            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                {initials}
              </div>
              <div className="hidden md:flex flex-col">
                <span className="text-sm font-medium text-foreground leading-tight">
                  {user?.name || t("app.user")}
                </span>
                {user && (
                  <Badge className={`${ROLE_BADGE[user.role]} border-0 text-[9px] px-1.5 py-0 w-fit`}>
                    {t(`auth.${user.role}` as "auth.admin")}
                  </Badge>
                )}
              </div>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={signOut}
              className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
            >
              <LogOut className="h-4 w-4" />
              <span className="sr-only">{t("app.logout")}</span>
            </Button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  )
}
