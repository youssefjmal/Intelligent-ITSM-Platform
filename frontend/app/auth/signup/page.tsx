"use client"

import React, { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Check, ChevronsUpDown, Loader2, UserPlus } from "lucide-react"

export default function SignUpPage() {
  const { signUp } = useAuth()
  const { t, locale } = useI18n()
  const router = useRouter()
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [specializations, setSpecializations] = useState<string[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [specializationsOpen, setSpecializationsOpen] = useState(false)

  function handleGoogleSignUp() {
    window.location.assign(buildApiUrl("/auth/google/start"))
  }

  const specializationGroups = [
    {
      title: t("category.infrastructure"),
      options: [
        { value: "server_maintenance", label: { fr: "Maintenance serveurs", en: "Server maintenance" } },
        { value: "cloud", label: { fr: "Cloud (AWS/Azure)", en: "Cloud (AWS/Azure)" } },
        { value: "virtualization", label: { fr: "Virtualisation", en: "Virtualization" } },
      ],
    },
    {
      title: t("category.network"),
      options: [
        { value: "routers", label: { fr: "Routeurs", en: "Routers" } },
        { value: "switches", label: { fr: "Switchs", en: "Switches" } },
        { value: "vpn", label: { fr: "VPN", en: "VPN" } },
        { value: "wifi", label: { fr: "Wi-Fi", en: "Wi-Fi" } },
        { value: "firewalls", label: { fr: "Pare-feux", en: "Firewalls" } },
      ],
    },
    {
      title: t("category.security"),
      options: [
        { value: "threat_detection", label: { fr: "Detection de menaces", en: "Threat detection" } },
        { value: "access_management", label: { fr: "Gestion des acces", en: "Access management" } },
        { value: "compliance", label: { fr: "Conformite", en: "Compliance" } },
      ],
    },
    {
      title: t("category.application"),
      options: [
        { value: "software_bugs", label: { fr: "Bugs logiciels", en: "Software bugs" } },
        { value: "database_issues", label: { fr: "Problemes base de donnees", en: "Database issues" } },
        { value: "internal_tools", label: { fr: "Outils internes", en: "Internal tools" } },
      ],
    },
    {
      title: t("category.service_request"),
      options: [
        { value: "onboarding", label: { fr: "Onboarding", en: "Onboarding" } },
        { value: "software_installs", label: { fr: "Installations logiciels", en: "Software installs" } },
        { value: "permissions", label: { fr: "Permissions", en: "Permissions" } },
      ],
    },
    {
      title: t("category.hardware"),
      options: [
        { value: "laptops", label: { fr: "Laptops", en: "Laptops" } },
        { value: "printers", label: { fr: "Imprimantes", en: "Printers" } },
        { value: "peripherals", label: { fr: "Peripheriques", en: "Peripherals" } },
      ],
    },
    {
      title: t("category.email"),
      options: [
        { value: "mailbox_issues", label: { fr: "Boites mail", en: "Mailbox issues" } },
        { value: "distribution_lists", label: { fr: "Listes de diffusion", en: "Distribution lists" } },
        { value: "outlook_workspace", label: { fr: "Outlook/Workspace", en: "Outlook/Workspace" } },
      ],
    },
  ]

  function toggleSpecialization(value: string) {
    setSpecializations((prev) =>
      prev.includes(value) ? prev.filter((spec) => spec !== value) : [...prev, value]
    )
  }

  const optionLabelMap = specializationGroups.reduce((acc, group) => {
    group.options.forEach((opt) => {
      acc[opt.value] = opt.label[locale]
    })
    return acc
  }, {} as Record<string, string>)

  const selectedLabelText =
    specializations.length === 0
      ? t("auth.specializationsPlaceholder")
      : [
          ...specializations
            .map((value) => optionLabelMap[value] ?? value)
            .slice(0, 2),
          ...(specializations.length > 2 ? [`+${specializations.length - 2}`] : []),
        ].join(", ")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")

    if (password !== confirmPassword) {
      setError(t("auth.passwordMismatch"))
      return
    }
    if (password.length < 6) {
      setError(t("auth.passwordTooShort"))
      return
    }

    setLoading(true)
    const result = await signUp({ email, password, name, specializations })
    if (result.error) {
      setError(t(`auth.${result.error}` as "auth.emailExists"))
      setLoading(false)
    } else {
      const params = new URLSearchParams({ email })
      if (result.verificationToken) params.set("token", result.verificationToken)
      if (result.verificationCode) params.set("code", result.verificationCode)
      router.push(`/auth/signup-success?${params.toString()}`)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 sm:p-6">
      <div className="pointer-events-none absolute -top-28 -right-20 h-72 w-72 rounded-full bg-primary/20 blur-3xl" />
      <div className="pointer-events-none absolute -left-20 bottom-10 h-64 w-64 rounded-full bg-amber-300/20 blur-3xl" />

      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>

      <div className="relative z-10 w-full max-w-md space-y-6 fade-slide-in">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="section-caption">{t("auth.signUp")}</p>
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/80 shadow-sm ring-1 ring-border/80 backdrop-blur">
            <img src="/logo.png" alt="Teamwil logo" className="logo-emphasis h-12 w-12 object-contain" />
          </div>
          <h1 className="text-3xl font-bold text-foreground text-balance">{t("auth.createAccount")}</h1>
          <p className="max-w-sm text-sm text-muted-foreground">{t("auth.createDesc")}</p>
        </div>

        <Card className="surface-card overflow-hidden rounded-2xl">
          <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold text-foreground text-center">
              {t("auth.signUp")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5">
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}

              <Button
                type="button"
                variant="outline"
                onClick={handleGoogleSignUp}
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
                    {t("auth.orCreateWithEmail")}
                  </span>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="name" className="text-foreground">{t("auth.fullName")}</Label>
                <Input
                  id="name"
                  placeholder={t("auth.namePlaceholder")}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  autoComplete="name"
                />
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
                <Label className="text-foreground">{t("auth.specializations")}</Label>
                <Popover open={specializationsOpen} onOpenChange={setSpecializationsOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full justify-between bg-transparent font-normal"
                    >
                      <span className="truncate">{selectedLabelText}</span>
                      <ChevronsUpDown className="ml-2 h-4 w-4 opacity-60" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-[360px] p-0">
                    <Command>
                      <CommandInput placeholder={t("auth.specializationsSearch")} />
                      <CommandList>
                        <CommandEmpty>{t("auth.specializationsEmpty")}</CommandEmpty>
                        {specializationGroups.map((group) => (
                          <CommandGroup key={group.title} heading={group.title}>
                            {group.options.map((opt) => {
                              const selected = specializations.includes(opt.value)
                              return (
                                <CommandItem
                                  key={opt.value}
                                  value={`${group.title} ${opt.label[locale]}`}
                                  onSelect={() => toggleSpecialization(opt.value)}
                                >
                                  <Check className={`h-4 w-4 ${selected ? "opacity-100" : "opacity-0"}`} />
                                  <span>{opt.label[locale]}</span>
                                </CommandItem>
                              )
                            })}
                          </CommandGroup>
                        ))}
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
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
                  autoComplete="new-password"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirmPassword" className="text-foreground">{t("auth.confirmPassword")}</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder={t("auth.confirmPasswordPlaceholder")}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                />
              </div>

              <Button
                type="submit"
                disabled={loading || !name || !email || !password || !confirmPassword || specializations.length === 0}
                className="w-full bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <UserPlus className="h-4 w-4" />
                )}
                {loading ? t("auth.signingUp") : t("auth.signUpBtn")}
              </Button>

              <p className="text-sm text-center text-muted-foreground">
                {t("auth.haveAccount")}{" "}
                <Link href="/auth/login" className="text-primary font-medium hover:underline">
                  {t("auth.signIn")}
                </Link>
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
