"use client"

import React from "react"

import { useEffect } from "react"
import { useRouter, usePathname } from "next/navigation"
import { useAuth, type Permission } from "@/lib/auth"
import { Loader2 } from "lucide-react"

const PUBLIC_PATHS = ["/auth/login", "/auth/signup", "/auth/signup-success", "/auth/verify"]

// Map routes to required permissions
const ROUTE_PERMISSIONS: Record<string, Permission> = {
  "/": "view_dashboard",
  "/tickets": "view_tickets",
  "/tickets/new": "create_ticket",
  "/chat": "use_chat",
  "/recommendations": "view_recommendations",
  "/admin": "view_admin",
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p))

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
  }, [user, loading, isPublic, router, pathname])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <img src="/logo.svg" alt="TeamWill logo" className="h-10 w-10 object-contain" />
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

  return <>{children}</>
}
