"use client"

import React from "react"
import Link from "next/link"
import { AppShell } from "@/components/app-shell"
import { useAuth } from "@/lib/auth"
import {
  getNotificationAnalytics,
  getNotificationDebugRecent,
  runNotificationDigest,
  sendNotificationEmail,
  type NotificationAnalytics,
  type NotificationDebugItem,
} from "@/lib/notifications-api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Shield } from "lucide-react"

function prettyTime(iso: string): string {
  const ts = new Date(iso).getTime()
  const diff = Math.max(1, Math.floor((Date.now() - ts) / 1000))
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function NotificationDebugPage() {
  const { hasPermission } = useAuth()
  const [rows, setRows] = React.useState<NotificationDebugItem[]>([])
  const [analytics, setAnalytics] = React.useState<NotificationAnalytics | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [workflow, setWorkflow] = React.useState("")
  const [userId, setUserId] = React.useState("")
  const [status, setStatus] = React.useState("")
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const [digestBusy, setDigestBusy] = React.useState(false)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [debugRows, metrics] = await Promise.all([
        getNotificationDebugRecent({
          workflow: workflow || undefined,
          user_id: userId || undefined,
          delivery_status: status || undefined,
          limit: 20,
        }),
        getNotificationAnalytics(),
      ])
      setRows(debugRows)
      setAnalytics(metrics)
    } finally {
      setLoading(false)
    }
  }, [workflow, userId, status])

  React.useEffect(() => {
    load().catch(() => {})
  }, [load])

  if (!hasPermission("view_admin")) {
    return (
      <AppShell>
        <div className="flex h-[60vh] flex-col items-center justify-center text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <Shield className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-xl font-bold text-foreground">Access denied</h2>
          <p className="mt-1 text-sm text-muted-foreground">Admin role required.</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in space-y-4">
        <div className="page-hero">
          <p className="section-caption">Admin</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground sm:text-4xl">Notifications Debug</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
            Trace n8n workflow outputs to in-app and email delivery states.
          </p>
          <div className="mt-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin">Back to admin</Link>
            </Button>
          </div>
        </div>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">Filters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={workflow}
                onChange={(e) => setWorkflow(e.target.value)}
                placeholder="Workflow name"
                className="h-8 w-[220px] text-xs"
              />
              <Input
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="User UUID"
                className="h-8 w-[260px] text-xs"
              />
              <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
                <SelectTrigger className="h-8 w-[180px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="in-app">in-app</SelectItem>
                  <SelectItem value="email-sent">email-sent</SelectItem>
                  <SelectItem value="email-failed">email-failed</SelectItem>
                  <SelectItem value="n8n-sent">n8n-sent</SelectItem>
                  <SelectItem value="n8n-failed">n8n-failed</SelectItem>
                  <SelectItem value="digest-sent">digest-sent</SelectItem>
                  <SelectItem value="digest-failed">digest-failed</SelectItem>
                  <SelectItem value="pending-digest">pending-digest</SelectItem>
                  <SelectItem value="suppressed">suppressed</SelectItem>
                </SelectContent>
              </Select>
              <Button size="sm" className="h-8 text-xs" onClick={() => load().catch(() => {})} disabled={loading}>
                {loading ? "Loading..." : "Apply"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={async () => {
                  setDigestBusy(true)
                  try {
                    await runNotificationDigest()
                    await load()
                  } finally {
                    setDigestBusy(false)
                  }
                }}
                disabled={digestBusy}
              >
                {digestBusy ? "Running..." : "Run hourly digest now"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">Recent Delivery Events</CardTitle>
          </CardHeader>
          <CardContent>
            {rows.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">No rows found.</p>
            ) : (
              <div className="space-y-2">
                {rows.map((row) => (
                  <div key={`${row.notification_id}-${row.created_at}`} className="rounded-lg border border-border/60 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold">{row.title}</p>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-muted-foreground">{row.delivery_status}</span>
                        {row.delivery_status === "email-failed" ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={busyId === row.notification_id}
                            onClick={async () => {
                              setBusyId(row.notification_id)
                              try {
                                await sendNotificationEmail(row.notification_id)
                                await load()
                              } finally {
                                setBusyId(null)
                              }
                            }}
                          >
                            Re-send
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-1 grid gap-1 text-[11px] text-muted-foreground">
                      <p>Severity: {row.severity} | Event: {row.event_type || "system_alert"} | Source: {row.source || "system"} | {prettyTime(row.created_at)}</p>
                      <p>Workflow: {row.workflow_name || "n/a"} | Trace: {row.trace_id || "n/a"}</p>
                      <p>Recipients: {row.recipients.length ? row.recipients.join(", ") : "n/a"}</p>
                      <p>Duplicate suppression: {row.duplicate_suppression || "none"}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">Analytics Snapshot</CardTitle>
          </CardHeader>
          <CardContent>
            {!analytics ? (
              <p className="text-sm text-muted-foreground">No analytics available.</p>
            ) : (
              <div className="grid gap-2 text-xs text-muted-foreground">
                <p>Created totals: {Object.keys(analytics.notifications_created_total).length}</p>
                <p>
                  Read rates: 1h {analytics.notifications_read_rate.read_within_1h_pct ?? 0}% | 24h{" "}
                  {analytics.notifications_read_rate.read_within_24h_pct ?? 0}% | never{" "}
                  {analytics.notifications_read_rate.never_read_pct ?? 0}%
                </p>
                <p>Email statuses tracked: {Object.keys(analytics.email_delivery_rate).join(", ") || "none"}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
