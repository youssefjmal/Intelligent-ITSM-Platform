"use client"

import React, { useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { buildApiUrl } from "@/lib/api"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { GoogleMark } from "@/components/google-mark"
import { Loader2, LogIn } from "lucide-react"

export default function LoginPage() {
  const { continueWithEmail } = useAuth()
  const { t } = useI18n()
  const router = useRouter()
  const params = useSearchParams()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const oauthErrorCode = params.get("oauth_error")
  const oauthError = oauthErrorCode ? t(`auth.${oauthErrorCode}` as "auth.oauthFailed") : ""

  function handleGoogleLogin() {
    window.location.assign(buildApiUrl("/auth/google/start"))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    const result = await continueWithEmail(email, password)
    if (result.error) {
      setError(t(`auth.${result.error}` as "auth.invalidCredentials"))
      setLoading(false)
    } else if (result.requiresVerification) {
      const params = new URLSearchParams({ email })
      router.push(`/auth/signup-success?${params.toString()}`)
    } else {
      router.push("/")
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
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="section-caption">{t("auth.signIn")}</p>
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/80 shadow-sm ring-1 ring-border/80 backdrop-blur">
            <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-12 w-12 object-contain" />
          </div>
          <h1 className="text-3xl font-bold text-foreground text-balance">{t("auth.welcome")}</h1>
          <p className="max-w-sm text-sm text-muted-foreground">{t("auth.welcomeDesc")}</p>
        </div>

        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
          <CardHeader className="pb-4">
            <CardTitle className="text-center text-lg font-semibold text-foreground">
              {t("auth.signIn")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {oauthError && (
                <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5">
                  <p className="text-sm text-destructive">{oauthError}</p>
                </div>
              )}
              {error && (
                <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5">
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}

              <Button
                type="button"
                variant="outline"
                onClick={handleGoogleLogin}
                className="w-full gap-2 bg-transparent"
              >
                <GoogleMark />
                {t("auth.continueWithGoogle")}
              </Button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-card px-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {t("auth.orContinueWithEmail")}
                  </span>
                </div>
              </div>

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

              <div className="space-y-2">
                <Label htmlFor="password" className="text-foreground">{t("auth.password")}</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder={t("auth.passwordPlaceholder")}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
                <div className="text-right">
                  <Link href="/auth/forgot-password" className="text-xs text-primary hover:underline">
                    {t("auth.forgotPassword")}
                  </Link>
                </div>
              </div>

              <Button
                type="submit"
                disabled={loading || !email || !password}
                className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LogIn className="h-4 w-4" />
                )}
                {loading ? t("auth.signingIn") : t("auth.signInBtn")}
              </Button>

              <p className="text-sm text-center text-muted-foreground">
                {t("auth.noAccount")}{" "}
                <Link href="/auth/signup" className="text-primary font-medium hover:underline">
                  {t("auth.signUp")}
                </Link>
              </p>
              <p className="text-xs text-center text-muted-foreground">
                {t("auth.autoEmailSignupHint")}
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
