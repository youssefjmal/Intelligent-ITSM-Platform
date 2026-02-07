"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

const COLORS_CATEGORY = ["#dc2626", "#2e9461", "#3b82f6", "#8b5cf6", "#f59e0b"]

export function DashboardCharts({
  weeklyData,
  categoryData,
  priorityData,
}: {
  weeklyData: Array<{ week: string; opened: number; closed: number; pending: number }>
  categoryData: Array<{ category: string; count: number }>
  priorityData: Array<{ priority: string; count: number; fill: string }>
}) {
  const { t } = useI18n()

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

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
      {/* Ticket Trends */}
      <Card className="xl:col-span-2 border border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-foreground">
            {t("chart.trends")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={weeklyChartConfig} className="h-[280px] w-full">
            <AreaChart data={weeklyData}>
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

      {/* Priority Distribution */}
      <Card className="border border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-foreground">
            {t("chart.priorityDist")}
          </CardTitle>
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
              >
                {priorityData.map((entry, index) => (
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

      {/* Category Breakdown */}
      <Card className="xl:col-span-3 border border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-foreground">
            {t("chart.categoryBreak")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={categoryChartConfig} className="h-[220px] w-full">
            <BarChart data={categoryData} layout="vertical">
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
        </CardContent>
      </Card>
    </div>
  )
}
