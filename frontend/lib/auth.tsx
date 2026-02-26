// Client-side auth context that talks to the FastAPI backend.
"use client"

import React, { createContext, useCallback, useContext, useEffect, useState } from "react"
import { apiFetch, ApiError } from "@/lib/api"

export type UserRole = "admin" | "agent" | "user" | "viewer"
export type UserSeniority = "intern" | "junior" | "middle" | "senior"

export interface User {
  id: string
  email: string
  name: string
  role: UserRole
  isVerified: boolean
  createdAt: string
  specializations: string[]
  seniorityLevel: UserSeniority
  isAvailable: boolean
  maxConcurrentTickets: number
}

interface AuthContextType {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<{ error?: string }>
  continueWithEmail: (
    email: string,
    password: string
  ) => Promise<{ error?: string; requiresVerification?: boolean }>
  signUp: (data: { email: string; password: string; name: string; specializations: string[] }) => Promise<{ error?: string }>
  signOut: () => Promise<void>
  getAllUsers: () => Promise<User[]>
  updateUserRole: (userId: string, role: UserRole) => Promise<void>
  updateUserSeniority: (userId: string, seniorityLevel: UserSeniority) => Promise<void>
  deleteUser: (userId: string) => Promise<void>
  hasPermission: (action: Permission) => boolean
}

export type Permission =
  | "view_dashboard"
  | "view_tickets"
  | "view_ticket_analytics"
  | "create_ticket"
  | "comment_ticket"
  | "resolve_ticket"
  | "reassign_ticket"
  | "edit_ticket_triage"
  | "use_chat"
  | "view_recommendations"
  | "manage_users"
  | "view_email_logs"
  | "configure_integrations"
  | "view_admin"

const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  admin: [
    "view_dashboard",
    "view_tickets",
    "view_ticket_analytics",
    "create_ticket",
    "comment_ticket",
    "resolve_ticket",
    "reassign_ticket",
    "edit_ticket_triage",
    "use_chat",
    "view_recommendations",
    "manage_users",
    "view_email_logs",
    "configure_integrations",
    "view_admin",
  ],
  agent: [
    "view_dashboard",
    "view_tickets",
    "view_ticket_analytics",
    "create_ticket",
    "comment_ticket",
    "resolve_ticket",
    "reassign_ticket",
    "edit_ticket_triage",
    "use_chat",
    "view_recommendations",
  ],
  user: [
    "view_dashboard",
    "view_tickets",
    "view_ticket_analytics",
    "create_ticket",
    "comment_ticket",
    "use_chat",
    "view_recommendations",
  ],
  viewer: [
    "view_dashboard",
    "view_tickets",
    "view_ticket_analytics",
    "use_chat",
    "view_recommendations",
  ],
}

const AuthContext = createContext<AuthContextType | null>(null)

function mapUser(data: {
  id: string
  email: string
  name: string
  role: UserRole
  is_verified: boolean
  created_at: string
  specializations: string[]
  seniority_level: UserSeniority
  is_available: boolean
  max_concurrent_tickets: number
}): User {
  return {
    id: data.id,
    email: data.email,
    name: data.name,
    role: data.role,
    isVerified: data.is_verified,
    createdAt: data.created_at,
    specializations: data.specializations ?? [],
    seniorityLevel: data.seniority_level ?? "middle",
    isAvailable: data.is_available ?? true,
    maxConcurrentTickets: data.max_concurrent_tickets ?? 10,
  }
}

function mapAuthError(detail: string): string {
  switch (detail) {
    case "invalid_credentials":
      return "invalidCredentials"
    case "email_exists":
      return "emailExists"
    case "email_not_verified":
      return "emailNotVerified"
    case "password_too_short":
      return "passwordTooShort"
    default:
      return "invalidCredentials"
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadUser = async () => {
      try {
      const data = await apiFetch<{
        id: string
        email: string
        name: string
        role: UserRole
        is_verified: boolean
        created_at: string
        specializations: string[]
        seniority_level: UserSeniority
        is_available: boolean
        max_concurrent_tickets: number
      }>("/auth/me")
      setUser(mapUser(data))
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    }
    loadUser()
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const data = await apiFetch<{
        id: string
        email: string
        name: string
        role: UserRole
        is_verified: boolean
        created_at: string
        specializations: string[]
        seniority_level: UserSeniority
        is_available: boolean
        max_concurrent_tickets: number
      }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })
      setUser(mapUser(data))
      return {}
    } catch (err) {
      if (err instanceof ApiError) {
        return { error: mapAuthError(err.detail) }
      }
      return { error: "invalidCredentials" }
    }
  }, [])

  const signUp = useCallback(
    async (data: { email: string; password: string; name: string; specializations: string[] }) => {
      try {
        await apiFetch<{ message: string }>("/auth/register", {
          method: "POST",
          body: JSON.stringify(data),
        })
        return {}
      } catch (err) {
        if (err instanceof ApiError) {
          return { error: mapAuthError(err.detail) }
        }
        return { error: "emailExists" }
      }
    },
    []
  )

  const signOut = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" })
    } finally {
      setUser(null)
    }
  }, [])

  const getAllUsers = useCallback(async () => {
    const users = await apiFetch<
      Array<{
        id: string
        email: string
        name: string
        role: UserRole
        is_verified: boolean
        created_at: string
        specializations: string[]
        seniority_level: UserSeniority
        is_available: boolean
        max_concurrent_tickets: number
      }>
    >("/users")
    return users.map(mapUser)
  }, [])

  const updateUserRole = useCallback(async (userId: string, role: UserRole) => {
    const updated = await apiFetch<{
      id: string
      email: string
      name: string
      role: UserRole
      is_verified: boolean
      created_at: string
      specializations: string[]
      seniority_level: UserSeniority
      is_available: boolean
      max_concurrent_tickets: number
    }>(
      `/users/${userId}/role`,
      {
        method: "PATCH",
        body: JSON.stringify({ role }),
      }
    )
    setUser((prev) => {
      if (prev && prev.id === updated.id) {
        return mapUser(updated)
      }
      return prev
    })
  }, [])

  const continueWithEmail = useCallback(async (email: string, password: string) => {
    try {
      const result = await apiFetch<{
        message: string
        user?: {
          id: string
          email: string
          name: string
          role: UserRole
          is_verified: boolean
          created_at: string
          specializations: string[]
          seniority_level: UserSeniority
          is_available: boolean
          max_concurrent_tickets: number
        }
        requires_verification?: boolean
      }>("/auth/email-login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })

      if (result.user) {
        setUser(mapUser(result.user))
      }

      return {
        requiresVerification: result.requires_verification ?? false,
      }
    } catch (err) {
      if (err instanceof ApiError) {
        return { error: mapAuthError(err.detail) }
      }
      return { error: "invalidCredentials" }
    }
  }, [])

  const updateUserSeniority = useCallback(async (userId: string, seniorityLevel: UserSeniority) => {
    const updated = await apiFetch<{
      id: string
      email: string
      name: string
      role: UserRole
      is_verified: boolean
      created_at: string
      specializations: string[]
      seniority_level: UserSeniority
      is_available: boolean
      max_concurrent_tickets: number
    }>(
      `/users/${userId}/seniority`,
      {
        method: "PATCH",
        body: JSON.stringify({ seniority_level: seniorityLevel }),
      }
    )
    setUser((prev) => {
      if (prev && prev.id === updated.id) {
        return mapUser(updated)
      }
      return prev
    })
  }, [])

  const deleteUser = useCallback(async (userId: string) => {
    await apiFetch(`/users/${userId}`, { method: "DELETE" })
    setUser((prev) => (prev && prev.id === userId ? null : prev))
  }, [])

  const hasPermission = useCallback(
    (action: Permission) => {
      if (!user) return false
      return ROLE_PERMISSIONS[user.role].includes(action)
    },
    [user]
  )

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signIn,
        continueWithEmail,
        signUp,
        signOut,
        getAllUsers,
        updateUserRole,
        updateUserSeniority,
        deleteUser,
        hasPermission,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
