"use client"

import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { CheckCircle2, Mail, LogIn, BadgeCheck } from "lucide-react"

export default function SignUpSuccessPage() {
  const { t } = useI18n()
  const params = useSearchParams()
  const token = params.get("token")

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="absolute top-4 right-4 flex items-center gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>

      <div className="w-full max-w-md space-y-6">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
            <img src="/logo.svg" alt="TeamWill logo" className="h-12 w-12 object-contain" />
          </div>
        </div>

        <Card className="border border-border">
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
                  {t("auth.checkEmail")}
                </p>
              </div>

              <div className="flex items-center gap-2 rounded-lg bg-accent/50 border border-border px-4 py-3">
                <Mail className="h-4 w-4 text-primary shrink-0" />
                <p className="text-xs text-foreground">
                  {t("auth.checkEmail")}
                </p>
              </div>

              {token && (
                <div className="w-full space-y-2">
                  <Link href={`/auth/verify?token=${token}`} className="w-full">
                    <Button className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2">
                      <BadgeCheck className="h-4 w-4" />
                      {t("auth.verifyNow")}
                    </Button>
                  </Link>
                  <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("auth.devToken")}:</span>{" "}
                    <span className="font-mono break-all">{token}</span>
                  </div>
                </div>
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
