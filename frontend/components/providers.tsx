"use client"

import React from "react"

import { I18nProvider } from "@/lib/i18n"
import { AuthProvider } from "@/lib/auth"
import { AuthGuard } from "@/components/auth-guard"
import { ThemeProvider } from "@/components/theme-provider"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <I18nProvider>
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}
