"use client"

import { Button } from "@/components/ui/button"
import { useI18n, type Locale } from "@/lib/i18n"
import { Languages } from "lucide-react"

export function LanguageSwitcher() {
  const { locale, setLocale } = useI18n()

  function toggle() {
    setLocale(locale === "fr" ? "en" : "fr")
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={toggle}
      className="gap-1.5 h-8 text-xs font-medium bg-transparent"
    >
      <Languages className="h-3.5 w-3.5" />
      {locale === "fr" ? "EN" : "FR"}
    </Button>
  )
}
