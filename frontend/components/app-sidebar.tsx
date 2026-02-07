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
  Shield,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useState } from "react"
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
  { nameKey: "nav.admin", href: "/admin", icon: Shield, permission: "view_admin" },
]

export function AppSidebar() {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)
  const { hasPermission } = useAuth()
  const { t } = useI18n()

  const visibleNav = navigation.filter((item) => hasPermission(item.permission))

  return (
    <aside
      className={cn(
        "flex flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div className="flex items-center gap-3 px-4 py-5 border-b border-sidebar-border">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground font-bold text-sm">
          TW
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="font-bold text-sm leading-tight">TeamWill</span>
            <span className="text-xs text-sidebar-foreground/70">Consulting</span>
          </div>
        )}
      </div>

      <nav className="flex-1 px-2 py-4 space-y-1">
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
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
              )}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span>{t(item.nameKey)}</span>}
            </Link>
          )
        })}
      </nav>

      <div className="p-2 border-t border-sidebar-border">
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground transition-colors"
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
