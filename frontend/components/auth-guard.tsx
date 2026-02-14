"use client"

import React from "react"

import { useEffect } from "react"
import { useRouter, usePathname } from "next/navigation"
import { useAuth, type Permission } from "@/lib/auth"
import { Loader2 } from "lucide-react"

const PUBLIC_PATHS = [
  "/auth/login",
  "/auth/signup",
  "/auth/signup-success",
  "/auth/verify",
  "/auth/forgot-password",
  "/auth/reset-password",
]

const ROUTE_PERMISSIONS: Array<{ prefix: string; permission: Permission }> = [
  { prefix: "/admin", permission: "view_admin" },
  { prefix: "/tickets/new", permission: "create_ticket" },
  { prefix: "/tickets", permission: "view_tickets" },
  { prefix: "/problems", permission: "view_tickets" },
  { prefix: "/chat", permission: "use_chat" },
  { prefix: "/recommendations", permission: "view_recommendations" },
  { prefix: "/", permission: "view_dashboard" },
]

function getRequiredPermission(pathname: string): Permission | null {
  for (const item of ROUTE_PERMISSIONS) {
    if (item.prefix === "/" && pathname === "/") {
      return item.permission
    }
    if (item.prefix !== "/" && pathname.startsWith(item.prefix)) {
      return item.permission
    }
  }
  return null
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading, hasPermission } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  const requiredPermission = getRequiredPermission(pathname)

  useEffect(() => {
    if (loading) return

    if (!user && !isPublic) {
      router.replace("/auth/login")
      return
    }

    if (user && isPublic) {
      router.replace("/")
      return
    }

    if (user && requiredPermission && !hasPermission(requiredPermission)) {
      router.replace("/403")
    }
  }, [user, loading, isPublic, router, pathname, requiredPermission, hasPermission])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/15 ring-1 ring-primary/25">
            <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-10 w-10 object-contain" />
          </div>
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
        </div>
      </div>
    )
  }

  if (!user && !isPublic) {
    return null
  }

  if (user && isPublic) {
    return null
  }

  if (user && requiredPermission && !hasPermission(requiredPermission)) {
    return null
  }

  return <>{children}</>
}
