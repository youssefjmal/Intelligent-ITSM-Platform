"use client"

import { useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
} from "recharts"
import { useI18n } from "@/lib/i18n"
import { ArrowRight } from "lucide-react"

const COLORS_CATEGORY = ["#dc2626", "#2e9461", "#3b82f6", "#8b5cf6", "#f59e0b", "#0ea5e9", "#14b8a6"]

export function DashboardCharts({
  weeklyData,
  categoryData,
  priorityData,
}: {
  weeklyData: Array<{ week: string; opened: number; closed: number; pending: number }>
  categoryData: Array<{ category: string; count: number }>
  priorityData: Array<{ priority: string; count: number; fill: string }>
}) {
  const { t, locale } = useI18n()
  const [weeklyHover, setWeeklyHover] = useState<{
    week: string
    opened: number
    closed: number
    pending: number
  } | null>(null)
  const [priorityHover, setPriorityHover] = useState<{ priority: string; count: number } | null>(null)
  const [categoryHover, setCategoryHover] = useState<{ category: string; count: number } | null>(null)

  const weeklyChartConfig = {
    opened: { label: t("chart.opened"), color: "#2e9461" },
    closed: { label: t("chart.closed"), color: "#64748b" },
    pending: { label: t("chart.pending"), color: "#f59e0b" },
  }

  const categoryChartConfig = {
    count: { label: "Tickets" },
  }

  const priorityChartConfig = {
    count: { label: "Tickets" },
  }

  const latestWeek = weeklyData[weeklyData.length - 1]
  const totalPriorities = priorityData.reduce((sum, row) => sum + row.count, 0)
  const totalCategories = categoryData.reduce((sum, row) => sum + row.count, 0)
  const topPriority = [...priorityData].sort((a, b) => b.count - a.count)[0]
  const topCategory = [...categoryData].sort((a, b) => b.count - a.count)[0]
  const categoryRowHeight = 42
  const categoryChartHeight = Math.max(220, categoryData.length * categoryRowHeight)
  const categoryNeedsScroll = categoryChartHeight > 360
  const weeklyRef = weeklyHover || latestWeek
  const priorityRef = priorityHover || topPriority || null
  const categoryRef = categoryHover || topCategory || null
  const priorityPercent = priorityRef && totalPriorities > 0 ? Math.round((priorityRef.count / totalPriorities) * 100) : 0
  const categoryPercent = categoryRef && totalCategories > 0 ? Math.round((categoryRef.count / totalCategories) * 100) : 0

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
      {/* Ticket Trends */}
      <CursorHoverLinkCard
        href="/tickets?view=total"
        className="group block xl:col-span-2"
        title={t("chart.trends")}
        rows={[
          { label: locale === "fr" ? "Semaine" : "Week", value: weeklyRef?.week ?? "-" },
          { label: t("chart.opened"), value: weeklyRef?.opened ?? 0 },
          { label: t("chart.closed"), value: weeklyRef?.closed ?? 0 },
          { label: t("chart.pending"), value: weeklyRef?.pending ?? 0 },
        ]}
        note={
          locale === "fr"
            ? "Survolez une semaine du graphique pour voir les valeurs exactes."
            : "Hover a week in the chart to see exact values."
        }
      >
            <Card className="surface-card rounded-2xl transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm font-semibold text-foreground">
                    {t("chart.trends")}
                  </CardTitle>
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-primary/80 group-hover:text-primary">
                    {locale === "fr" ? "Ouvrir" : "Open"}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <ChartContainer config={weeklyChartConfig} className="h-[280px] w-full">
                  <AreaChart
                    data={weeklyData}
                    onMouseMove={(state: unknown) => {
                      const payload = (state as { activePayload?: Array<{ payload?: { week?: string; opened?: number; closed?: number; pending?: number } }> } | undefined)?.activePayload
                      const row = payload?.[0]?.payload
                      if (!row) return
                      setWeeklyHover({
                        week: row.week || "",
                        opened: Number(row.opened || 0),
                        closed: Number(row.closed || 0),
                        pending: Number(row.pending || 0),
                      })
                    }}
                    onMouseLeave={() => setWeeklyHover(null)}
                  >
                    <defs>
                      <linearGradient id="fillOpened" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2e9461" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#2e9461" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="fillClosed" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#64748b" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#64748b" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="week" tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Area
                      type="monotone"
                      dataKey="opened"
                      stroke="#2e9461"
                      fill="url(#fillOpened)"
                      strokeWidth={2}
                    />
                    <Area
                      type="monotone"
                      dataKey="closed"
                      stroke="#64748b"
                      fill="url(#fillClosed)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ChartContainer>
              </CardContent>
            </Card>
      </CursorHoverLinkCard>

      {/* Priority Distribution */}
      <CursorHoverLinkCard
        href="/tickets?view=critical"
        className="group block"
        title={t("chart.priorityDist")}
        rows={[
          { label: locale === "fr" ? "Total tickets" : "Total tickets", value: totalPriorities },
          {
            label: locale === "fr" ? "Priorite survolee" : "Hovered priority",
            value: priorityRef ? `${priorityRef.priority} (${priorityRef.count})` : "-",
          },
          { label: locale === "fr" ? "Part" : "Share", value: `${priorityPercent}%` },
        ]}
        note={
          locale === "fr"
            ? "Survolez une section du donut pour voir son poids exact."
            : "Hover a donut segment to see its exact share."
        }
      >
            <Card className="surface-card rounded-2xl transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm font-semibold text-foreground">
                    {t("chart.priorityDist")}
                  </CardTitle>
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-primary/80 group-hover:text-primary">
                    {locale === "fr" ? "Ouvrir" : "Open"}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <ChartContainer config={priorityChartConfig} className="h-[280px] w-full">
                  <PieChart>
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Pie
                      data={priorityData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      paddingAngle={4}
                      dataKey="count"
                      nameKey="priority"
                      onMouseEnter={(_, index) => {
                        const row = priorityData[index]
                        if (row) setPriorityHover({ priority: row.priority, count: row.count })
                      }}
                      onMouseLeave={() => setPriorityHover(null)}
                    >
                      {priorityData.map((entry) => (
                        <Cell key={entry.priority} fill={entry.fill} />
                      ))}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                <div className="mt-2 flex flex-wrap justify-center gap-3">
                  {priorityData.map((item) => (
                    <div key={item.priority} className="flex items-center gap-1.5 text-xs">
                      <div
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: item.fill }}
                      />
                      <span className="text-muted-foreground">
                        {item.priority} ({item.count})
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
      </CursorHoverLinkCard>

      {/* Category Breakdown */}
      <CursorHoverLinkCard
        href="/tickets"
        className="group block xl:col-span-3"
        popupSide="left"
        title={t("chart.categoryBreak")}
        rows={[
          { label: locale === "fr" ? "Categories" : "Categories", value: categoryData.length },
          { label: locale === "fr" ? "Total tickets" : "Total tickets", value: totalCategories },
          {
            label: locale === "fr" ? "Categorie survolee" : "Hovered category",
            value: categoryRef ? `${categoryRef.category} (${categoryRef.count})` : "-",
          },
          { label: locale === "fr" ? "Part categorie" : "Category share", value: `${categoryPercent}%` },
        ]}
        note={
          locale === "fr"
            ? "Survolez une barre pour voir le volume exact."
            : "Hover a bar to see the exact volume."
        }
      >
            <Card className="surface-card rounded-2xl transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm font-semibold text-foreground">
                    {t("chart.categoryBreak")}
                  </CardTitle>
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-primary/80 group-hover:text-primary">
                    {locale === "fr" ? "Ouvrir" : "Open"}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                {categoryNeedsScroll ? (
                  <ScrollArea className="h-[360px] w-full pr-2">
                    <ChartContainer config={categoryChartConfig} className="w-full" style={{ height: `${categoryChartHeight}px` }}>
                      <BarChart
                        data={categoryData}
                        layout="vertical"
                        onMouseMove={(state: unknown) => {
                          const payload = (state as { activePayload?: Array<{ payload?: { category?: string; count?: number } }> } | undefined)?.activePayload
                          const row = payload?.[0]?.payload
                          if (!row) return
                          setCategoryHover({
                            category: row.category || "",
                            count: Number(row.count || 0),
                          })
                        }}
                        onMouseLeave={() => setCategoryHover(null)}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
                        <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 12 }} />
                        <YAxis
                          dataKey="category"
                          type="category"
                          width={110}
                          tick={{ fill: "#6b7280", fontSize: 12 }}
                        />
                        <ChartTooltip content={<ChartTooltipContent />} />
                        <Bar dataKey="count" radius={[0, 6, 6, 0]}>
                          {categoryData.map((_, index) => (
                            <Cell
                              key={`cell-${index}`}
                              fill={COLORS_CATEGORY[index % COLORS_CATEGORY.length]}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ChartContainer>
                  </ScrollArea>
                ) : (
                  <ChartContainer config={categoryChartConfig} className="w-full" style={{ height: `${categoryChartHeight}px` }}>
                    <BarChart
                      data={categoryData}
                      layout="vertical"
                      onMouseMove={(state: unknown) => {
                        const payload = (state as { activePayload?: Array<{ payload?: { category?: string; count?: number } }> } | undefined)?.activePayload
                        const row = payload?.[0]?.payload
                        if (!row) return
                        setCategoryHover({
                          category: row.category || "",
                          count: Number(row.count || 0),
                        })
                      }}
                      onMouseLeave={() => setCategoryHover(null)}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
                      <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 12 }} />
                      <YAxis
                        dataKey="category"
                        type="category"
                        width={110}
                        tick={{ fill: "#6b7280", fontSize: 12 }}
                      />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar dataKey="count" radius={[0, 6, 6, 0]}>
                        {categoryData.map((_, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={COLORS_CATEGORY[index % COLORS_CATEGORY.length]}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ChartContainer>
                )}
              </CardContent>
            </Card>
      </CursorHoverLinkCard>
    </div>
  )
}

function StatPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/35 px-2 py-1.5">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold text-foreground">{value}</p>
    </div>
  )
}

function CursorHoverLinkCard({
  href,
  className,
  popupSide = "right",
  title,
  rows,
  note,
  children,
}: {
  href: string
  className: string
  popupSide?: "left" | "right"
  title: string
  rows: Array<{ label: string; value: string | number }>
  note: string
  children: ReactNode
}) {
  const [hovered, setHovered] = useState(false)
  const [pointer, setPointer] = useState({ x: 0, y: 0 })

  return (
    <>
      <Link
        href={href}
        className={className}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onMouseMove={(event) => setPointer({ x: event.clientX + 14, y: event.clientY + 14 })}
      >
        {children}
      </Link>
      {hovered && typeof window !== "undefined"
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[9999] hidden w-80 border-border/80 bg-background/95 p-0 shadow-xl backdrop-blur md:block"
              style={{
                left: popupSide === "left" ? pointer.x - 334 : pointer.x + 14,
                top: pointer.y,
              }}
            >
              <div className="rounded-lg border border-border/70 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
                <div className={`mt-3 grid gap-2 ${rows.length >= 3 ? "grid-cols-3" : "grid-cols-2"}`}>
                  {rows.map((row) => (
                    <StatPill key={`${title}-${row.label}`} label={row.label} value={row.value} />
                  ))}
                </div>
                <p className="mt-3 text-[11px] text-muted-foreground">{note}</p>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  )
}
