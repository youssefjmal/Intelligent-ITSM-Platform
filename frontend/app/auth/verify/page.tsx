// Email verification page that exchanges a token for account activation.
"use client"

import { useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { apiFetch } from "@/lib/api"
import { CheckCircle2, AlertTriangle, LogIn, Loader2 } from "lucide-react"

export default function VerifyEmailPage() {
  const { t } = useI18n()
  const params = useSearchParams()
  const token = params.get("token")
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [redirecting, setRedirecting] = useState(false)

  useEffect(() => {
    const run = async () => {
      if (!token) {
        setStatus("error")
        return
      }
      try {
        const result = await apiFetch<{ auto_logged_in?: boolean }>("/auth/verify", {
          method: "POST",
          body: JSON.stringify({ token }),
        })
        setStatus("success")
        if (result.auto_logged_in) {
          setRedirecting(true)
          window.setTimeout(() => {
            window.location.assign("/")
          }, 1200)
        }
      } catch {
        setStatus("error")
      }
    }
    run()
  }, [token])

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 sm:p-6">
      <div className="pointer-events-none absolute -top-28 -right-20 h-72 w-72 rounded-full bg-primary/20 blur-3xl" />
      <div className="pointer-events-none absolute -left-16 bottom-10 h-64 w-64 rounded-full bg-amber-300/20 blur-3xl" />

      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>

      <div className="relative z-10 w-full max-w-md space-y-6 fade-slide-in">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/80 shadow-sm ring-1 ring-border/80 backdrop-blur">
            <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-12 w-12 object-contain" />
          </div>
        </div>

        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
          <CardContent className="pt-8 pb-8">
            <div className="flex flex-col items-center text-center space-y-4">
              {status === "loading" && (
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                  <Loader2 className="h-8 w-8 text-primary animate-spin" />
                </div>
              )}
              {status === "success" && (
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                  <CheckCircle2 className="h-8 w-8 text-primary" />
                </div>
              )}
              {status === "error" && (
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
                  <AlertTriangle className="h-8 w-8 text-destructive" />
                </div>
              )}

              <div className="space-y-2">
                <h1 className="text-xl font-bold text-foreground text-balance">
                  {t("auth.verifyTitle")}
                </h1>
                <p className="text-sm text-muted-foreground leading-relaxed max-w-sm">
                  {status === "loading" && t("auth.verifyInProgress")}
                  {status === "success" && t("auth.verifySuccess")}
                  {status === "error" && t("auth.verifyError")}
                </p>
                {status === "success" && redirecting && (
                  <p className="text-xs text-muted-foreground">{t("auth.verifyRedirecting")}</p>
                )}
              </div>

              <Link href="/auth/login" className="w-full">
                <Button className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2">
                  <LogIn className="h-4 w-4" />
                  {t("auth.goToLogin")}
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
