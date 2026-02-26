"use client"

import { FormEvent, useMemo, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { apiFetch, ApiError } from "@/lib/api"
import { CheckCircle2, Mail, LogIn, KeyRound, Loader2 } from "lucide-react"

export default function SignUpSuccessPage() {
  const { t } = useI18n()
  const params = useSearchParams()
  const email = (params.get("email") ?? "").trim().toLowerCase()
  const [code, setCode] = useState("")
  const [codeStatus, setCodeStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [redirecting, setRedirecting] = useState(false)
  const [codeError, setCodeError] = useState("")

  const canSubmitCode = useMemo(() => email.length > 3 && code.length === 6, [email, code])

  async function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCodeError("")

    if (!email) {
      setCodeStatus("error")
      setCodeError(t("auth.emailMissingForCode"))
      return
    }

    if (code.length !== 6) {
      setCodeStatus("error")
      setCodeError(t("auth.invalidVerificationCode"))
      return
    }

    try {
      setCodeStatus("loading")
      const result = await apiFetch<{ auto_logged_in?: boolean }>("/auth/verify-code", {
        method: "POST",
        body: JSON.stringify({ email, code }),
      })
      setCodeStatus("success")
      if (result.auto_logged_in) {
        setRedirecting(true)
        window.setTimeout(() => {
          window.location.assign("/")
        }, 1200)
      }
    } catch (err) {
      setCodeStatus("error")
      if (err instanceof ApiError && err.detail === "invalid_or_expired_verification_code") {
        setCodeError(t("auth.invalidVerificationCode"))
      } else {
        setCodeError(t("auth.verifyCodeError"))
      }
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 sm:p-6">
      <div className="pointer-events-none absolute -top-28 -left-20 h-72 w-72 rounded-full bg-primary/20 blur-3xl" />
      <div className="pointer-events-none absolute -right-16 bottom-10 h-64 w-64 rounded-full bg-amber-300/20 blur-3xl" />

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
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                <CheckCircle2 className="h-8 w-8 text-primary" />
              </div>

              <div className="space-y-2">
                <h1 className="text-xl font-bold text-foreground text-balance">
                  {t("auth.signUpSuccess")}
                </h1>
                <p className="text-sm text-muted-foreground leading-relaxed max-w-sm">
                  {t("auth.verifyCodeHint")}
                </p>
              </div>

              <div className="flex items-center gap-2 rounded-lg bg-accent/50 border border-border px-4 py-3">
                <Mail className="h-4 w-4 text-primary shrink-0" />
                <p className="text-xs text-foreground">
                  {t("auth.checkEmail")}
                </p>
              </div>

              {email && (
                <form onSubmit={submitCode} className="w-full space-y-3 rounded-lg border border-border bg-muted/30 px-4 py-4 text-left">
                  <Label htmlFor="verification-code" className="text-xs font-medium tracking-wide text-muted-foreground">
                    {t("auth.verifyCodeLabel")}
                  </Label>
                  <Input
                    id="verification-code"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    value={code}
                    onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder={t("auth.verifyCodePlaceholder")}
                    className="text-center font-mono text-lg tracking-[0.35em]"
                  />
                  {codeError && <p className="text-xs text-destructive">{codeError}</p>}
                  {codeStatus === "success" && (
                    <p className="text-xs text-primary">{t("auth.verifyCodeSuccess")}</p>
                  )}
                  {redirecting && (
                    <p className="text-xs text-muted-foreground">{t("auth.verifyRedirecting")}</p>
                  )}
                  <Button
                    type="submit"
                    disabled={!canSubmitCode || codeStatus === "loading" || codeStatus === "success"}
                    className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
                  >
                    {codeStatus === "loading" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <KeyRound className="h-4 w-4" />
                    )}
                    {codeStatus === "loading" ? t("auth.verifyingCode") : t("auth.verifyCodeBtn")}
                  </Button>
                </form>
              )}

              <Link href="/auth/login" className="w-full">
                <Button variant="outline" className="w-full gap-2 bg-transparent">
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
