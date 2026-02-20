"use client"

import React from "react"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  Ticket,
  PlusCircle,
  MessageSquareText,
  BrainCircuit,
  AlertOctagon,
  Shield,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth, type Permission } from "@/lib/auth"
import { useI18n, type TranslationKey } from "@/lib/i18n"

interface NavItem {
  nameKey: TranslationKey
  href: string
  icon: React.ComponentType<{ className?: string }>
  permission: Permission
}

const navigation: NavItem[] = [
  { nameKey: "nav.dashboard", href: "/", icon: LayoutDashboard, permission: "view_dashboard" },
  { nameKey: "nav.tickets", href: "/tickets", icon: Ticket, permission: "view_tickets" },
  { nameKey: "nav.newTicket", href: "/tickets/new", icon: PlusCircle, permission: "create_ticket" },
  { nameKey: "nav.chat", href: "/chat", icon: MessageSquareText, permission: "use_chat" },
  { nameKey: "nav.recommendations", href: "/recommendations", icon: BrainCircuit, permission: "view_recommendations" },
  { nameKey: "nav.problems", href: "/problems", icon: AlertOctagon, permission: "view_tickets" },
  { nameKey: "nav.admin", href: "/admin", icon: Shield, permission: "view_admin" },
]

interface AppSidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export function AppSidebar({ collapsed, onToggle }: AppSidebarProps) {
  const pathname = usePathname()
  const { hasPermission } = useAuth()
  const { t } = useI18n()

  const visibleNav = navigation.filter((item) => hasPermission(item.permission))

  return (
    <aside
      className={cn(
        "relative flex flex-col border-r border-sidebar-border/80 bg-sidebar text-sidebar-foreground shadow-2xl shadow-black/15 transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/10 to-transparent" />
      <div className="relative flex items-center gap-3 border-b border-sidebar-border/70 px-4 py-5">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white/95 shadow-md ring-1 ring-black/10">
          <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-10 w-10 object-contain" />
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-sm font-bold leading-tight tracking-wide">Teamwil</span>
            <span className="text-xs text-sidebar-foreground/75">Consulting Ops Suite</span>
          </div>
        )}
      </div>

      <nav className="relative flex-1 space-y-1.5 px-2 py-4">
        {visibleNav.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href)
          return (
            <Link
              key={item.nameKey}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm ring-1 ring-white/10"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )}
            >
              <span
                className={cn(
                  "absolute left-0 top-1/2 h-7 w-1 -translate-y-1/2 rounded-r-full bg-sidebar-primary transition-opacity",
                  isActive ? "opacity-100" : "opacity-0 group-hover:opacity-60"
                )}
              />
              <item.icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span>{t(item.nameKey)}</span>}
            </Link>
          )
        })}
      </nav>

      <div className="border-t border-sidebar-border/70 p-2">
        <button
          type="button"
          onClick={onToggle}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="h-4 w-4" />
              <span>{t("nav.collapse")}</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
