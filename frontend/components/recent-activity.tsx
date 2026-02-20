"use client"

import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { CATEGORY_CONFIG, PRIORITY_CONFIG, type Ticket, STATUS_CONFIG } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"

export function RecentActivity({ tickets }: { tickets: Ticket[] }) {
  const { t, locale } = useI18n()
  const recent = [...tickets]
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    .slice(0, 6)

  return (
    <Card className="surface-card rounded-2xl">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold text-foreground">
            {t("activity.title")}
          </CardTitle>
          <Link href="/tickets">
            <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-[11px]">
              {locale === "fr" ? "Voir tout" : "View all"}
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {recent.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/70 bg-muted/25 p-4 text-center">
            <p className="text-sm text-muted-foreground">{locale === "fr" ? "Aucune activite recente." : "No recent activity."}</p>
          </div>
        ) : (
          recent.map((ticket) => (
            <HoverCard key={ticket.id} openDelay={90} closeDelay={70}>
              <HoverCardTrigger asChild>
                <Link
                  href={`/tickets/${ticket.id}`}
                  className="group flex items-start gap-3 rounded-xl border border-border/60 bg-card/50 p-3 transition-colors hover:bg-muted/40"
                >
                  <div
                    className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                      ticket.priority === "critical"
                        ? "bg-red-500"
                        : ticket.priority === "high"
                          ? "bg-amber-500"
                          : ticket.priority === "medium"
                            ? "bg-emerald-500"
                            : "bg-slate-400"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-1 text-sm font-medium text-foreground transition-colors group-hover:text-primary">
                      {ticket.title}
                    </p>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="text-xs font-mono text-muted-foreground">
                        {ticket.id}
                      </span>
                      <Badge
                        className={`${STATUS_CONFIG[ticket.status].color} border-0 px-1.5 py-0 text-[10px] font-medium`}
                      >
                        {STATUS_CONFIG[ticket.status].label}
                      </Badge>
                    </div>
                  </div>
                  <span className="mt-0.5 whitespace-nowrap text-[10px] text-muted-foreground">
                    {formatTimeAgo(ticket.updatedAt, locale)}
                  </span>
                </Link>
              </HoverCardTrigger>
              <HoverCardContent side="left" align="start" className="w-80 border-border/80 bg-background/95 p-0 shadow-xl backdrop-blur">
                <div className="rounded-lg border border-border/70 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="line-clamp-1 text-sm font-semibold text-foreground">{ticket.title}</p>
                    <span className="text-[10px] font-mono text-muted-foreground">{ticket.id}</span>
                  </div>
                  <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                    {ticket.description || (locale === "fr" ? "Sans description." : "No description.")}
                  </p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <MiniDetail label={locale === "fr" ? "Priorite" : "Priority"} value={PRIORITY_CONFIG[ticket.priority].label} />
                    <MiniDetail label={locale === "fr" ? "Categorie" : "Category"} value={CATEGORY_CONFIG[ticket.category].label} />
                    <MiniDetail label={locale === "fr" ? "Assigne" : "Assignee"} value={ticket.assignee || "-"} />
                    <MiniDetail label={locale === "fr" ? "Mise a jour" : "Updated"} value={formatDateTime(ticket.updatedAt, locale)} />
                  </div>
                </div>
              </HoverCardContent>
            </HoverCard>
          ))
        )}
      </CardContent>
    </Card>
  )
}

function MiniDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 px-2 py-1.5">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="line-clamp-1 text-xs font-medium text-foreground">{value}</p>
    </div>
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

function formatDateTime(dateStr: string, locale: "fr" | "en"): string {
  const date = new Date(dateStr)
  return date.toLocaleString(locale === "fr" ? "fr-FR" : "en-US", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}
