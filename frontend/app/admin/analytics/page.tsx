"use client";

/**
 * Recommendation feedback analytics page.
 *
 * Visualizes AI recommendation feedback data:
 * - Summary stats (total, useful rate, applied rate)
 * - Breakdown by display_mode
 * - Useful rate by category
 * - Daily trend
 */

import { useState, useEffect, useCallback } from "react";

interface AnalyticsResponse {
  period_days: number;
  total_feedback_count: number;
  by_feedback_type: {
    useful: number;
    not_relevant: number;
    applied: number;
    rejected: number;
  };
  useful_rate: number;
  applied_rate: number;
  by_display_mode: Record<string, Record<string, number>>;
  by_category: Record<string, number>;
  top_useful_recommendations: unknown[];
  top_rejected_recommendations: unknown[];
  trend: Array<{ date: string; useful_count: number; applied_count: number }>;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState(30);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/recommendations/analytics?period_days=${period}`);
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const modeLabels: Record<string, string> = {
    evidence_action: "Evidence Action",
    tentative_diagnostic: "Diagnostic Tentatif",
    llm_general_knowledge: "LLM Général",
    no_strong_match: "Aucune correspondance",
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Analytique des recommandations IA</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Feedback utilisateur sur les recommandations générées
        </p>
      </div>

      {/* Period selector */}
      <div className="flex items-center gap-3 mb-6">
        <label className="text-sm font-medium">Période :</label>
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setPeriod(d)}
            className={`text-sm px-3 py-1 rounded-lg border transition-colors ${
              period === d
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border hover:bg-muted"
            }`}
          >
            {d}j
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-muted-foreground">Chargement...</p>}

      {data && !loading && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <StatCard label="Total feedbacks" value={String(data.total_feedback_count)} />
            <StatCard
              label="Taux d'utilité"
              value={`${Math.round(data.useful_rate * 100)}%`}
              sub={`${data.by_feedback_type.useful + data.by_feedback_type.applied} utiles`}
            />
            <StatCard
              label="Taux d'application"
              value={`${Math.round(data.applied_rate * 100)}%`}
              sub={`${data.by_feedback_type.applied} appliquées`}
            />
            <StatCard
              label="Rejetées"
              value={String(data.by_feedback_type.rejected)}
              sub={`${data.by_feedback_type.not_relevant} non pertinentes`}
            />
          </div>

          {/* By display mode */}
          {Object.keys(data.by_display_mode).length > 0 && (
            <div className="rounded-xl border border-border p-4 mb-6">
              <h2 className="text-base font-semibold mb-3">Feedback par mode d'affichage</h2>
              {Object.entries(data.by_display_mode).map(([mode, counts]) => {
                const total = Object.values(counts).reduce((a, b) => a + b, 0);
                const useful = (counts["useful"] || 0) + (counts["applied"] || 0);
                const pct = total ? Math.round((useful / total) * 100) : 0;
                return (
                  <div key={mode} className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium">{modeLabels[mode] || mode}</span>
                      <span className="text-xs text-muted-foreground">{pct}% utile · {total} feedbacks</span>
                    </div>
                    <div className="flex gap-1 h-3 rounded-full overflow-hidden bg-muted">
                      {useful > 0 && <div className="bg-teal-400 h-full" style={{ width: `${pct}%` }} />}
                      {(counts["rejected"] || 0) > 0 && (
                        <div className="bg-red-300 h-full" style={{ width: `${total ? Math.round((counts["rejected"] / total) * 100) : 0}%` }} />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* By category */}
          {Object.keys(data.by_category).length > 0 && (
            <div className="rounded-xl border border-border p-4 mb-6">
              <h2 className="text-base font-semibold mb-3">Utilité par catégorie</h2>
              {Object.entries(data.by_category)
                .sort(([, a], [, b]) => b - a)
                .map(([cat, rate]) => (
                  <div key={cat} className="flex items-center gap-3 mb-2">
                    <span className="text-sm w-32 capitalize">{cat}</span>
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full ${rate >= 0.7 ? "bg-teal-400" : rate >= 0.4 ? "bg-amber-400" : "bg-red-400"}`}
                        style={{ width: `${Math.round(rate * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground w-10 text-right">{Math.round(rate * 100)}%</span>
                  </div>
                ))}
            </div>
          )}

          {/* Trend */}
          {data.trend.length > 0 && (
            <div className="rounded-xl border border-border p-4">
              <h2 className="text-base font-semibold mb-3">Tendance sur la période</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground">
                      <th className="text-left py-1 px-2">Date</th>
                      <th className="text-right py-1 px-2">Utiles</th>
                      <th className="text-right py-1 px-2">Appliquées</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trend.slice(-14).map((row) => (
                      <tr key={row.date} className="border-t border-border">
                        <td className="py-1 px-2">{row.date}</td>
                        <td className="py-1 px-2 text-right text-teal-600">{row.useful_count}</td>
                        <td className="py-1 px-2 text-right text-blue-600">{row.applied_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.total_feedback_count === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-4xl mb-3">📊</p>
              <p>Aucun feedback reçu sur cette période.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
