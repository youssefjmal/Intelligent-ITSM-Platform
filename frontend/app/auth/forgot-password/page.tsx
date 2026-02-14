"use client"

import React, { useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { apiFetch, ApiError } from "@/lib/api"
import { Loader2, Mail, ArrowLeft } from "lucide-react"

export default function ForgotPasswordPage() {
  const { t } = useI18n()
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [sent, setSent] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await apiFetch<{ message: string }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      })
      setSent(true)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(t(`auth.${err.detail}` as "auth.resetError"))
      } else {
        setError(t("auth.resetError"))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 sm:p-6">
      <div className="pointer-events-none absolute -top-24 -left-20 h-64 w-64 rounded-full bg-primary/20 blur-3xl" />
      <div className="pointer-events-none absolute -right-16 bottom-8 h-60 w-60 rounded-full bg-amber-300/20 blur-3xl" />

      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>

      <div className="relative z-10 w-full max-w-md space-y-6 fade-slide-in">
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="section-caption">{t("auth.forgotPassword")}</p>
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/80 shadow-sm ring-1 ring-border/80 backdrop-blur">
            <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-12 w-12 object-contain" />
          </div>
          <h1 className="text-3xl font-bold text-foreground text-balance">{t("auth.forgotPasswordTitle")}</h1>
          <p className="max-w-sm text-sm text-muted-foreground">{t("auth.forgotPasswordDesc")}</p>
        </div>

        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
          <CardHeader className="pb-4">
            <CardTitle className="text-center text-lg font-semibold text-foreground">
              {t("auth.forgotPassword")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5">
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}

              {sent && (
                <div className="rounded-lg border border-primary/20 bg-primary/10 px-3 py-2.5">
                  <p className="text-sm text-foreground">{t("auth.resetEmailSent")}</p>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="email" className="text-foreground">{t("auth.email")}</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder={t("auth.emailPlaceholder")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                />
              </div>

              <Button
                type="submit"
                disabled={loading || !email}
                className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                {loading ? t("auth.sendingResetEmail") : t("auth.sendResetLink")}
              </Button>

              <Link href="/auth/login" className="w-full">
                <Button variant="outline" className="w-full gap-2 bg-transparent">
                  <ArrowLeft className="h-4 w-4" />
                  {t("auth.backToLogin")}
                </Button>
              </Link>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
