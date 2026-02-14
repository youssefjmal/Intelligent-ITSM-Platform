"use client"

import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { type Ticket, STATUS_CONFIG, PRIORITY_CONFIG } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"

export function RecentActivity({ tickets }: { tickets: Ticket[] }) {
  const { t, locale } = useI18n()
  const recent = [...tickets]
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    .slice(0, 6)

  return (
    <Card className="surface-card rounded-2xl">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-foreground">
          {t("activity.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {recent.map((ticket) => (
          <Link
            key={ticket.id}
            href={`/tickets/${ticket.id}`}
            className="flex items-start gap-3 rounded-lg p-2.5 transition-colors hover:bg-muted/50 group"
          >
            <div
              className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                ticket.priority === "critical"
                  ? "bg-red-500"
                  : ticket.priority === "high"
                    ? "bg-amber-500"
                    : ticket.priority === "medium"
                      ? "bg-emerald-500"
                      : "bg-slate-400"
              }`}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground group-hover:text-primary transition-colors line-clamp-1">
                {ticket.title}
              </p>
              <div className="mt-1 flex items-center gap-2">
                <span className="text-xs font-mono text-muted-foreground">
                  {ticket.id}
                </span>
                <Badge
                  className={`${STATUS_CONFIG[ticket.status].color} border-0 text-[10px] font-medium px-1.5 py-0`}
                >
                  {STATUS_CONFIG[ticket.status].label}
                </Badge>
              </div>
            </div>
            <span className="text-[10px] text-muted-foreground whitespace-nowrap mt-0.5">
              {formatTimeAgo(ticket.updatedAt, locale)}
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}

function formatTimeAgo(dateStr: string, locale: "fr" | "en"): string {
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now.getTime() - date.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffHours / 24)
  const localeCode = locale === "fr" ? "fr-FR" : "en-US"

  if (diffDays > 7) {
    return date.toLocaleDateString(localeCode, { day: "2-digit", month: "short" })
  }
  if (diffDays > 0) return locale === "fr" ? `il y a ${diffDays}j` : `${diffDays}d ago`
  if (diffHours > 0) return locale === "fr" ? `il y a ${diffHours}h` : `${diffHours}h ago`
  return locale === "fr" ? "A l'instant" : "Just now"
}
