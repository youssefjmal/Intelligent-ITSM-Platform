"use client";

/**
 * Agent performance dashboard page.
 *
 * Shows per-agent MTTR, resolution rate, and SLA breach rate.
 * Sortable table with color coding by performance tier.
 * Period selector: 7 / 30 / 90 days. Category filter.
 */

import { useState, useEffect, useCallback } from "react";

interface AgentRecord {
  agent_name: string;
  agent_email: string | null;
  tickets_assigned: number;
  tickets_resolved: number;
  resolution_rate: number;
  mttr_hours: number | null;
  mttr_p90_hours: number | null;
  sla_breach_rate: number | null;
  avg_first_action_hours: number | null;
  open_ticket_count: number;
}

interface PerformanceResponse {
  period_days: number;
  agents: AgentRecord[];
  generated_at: string;
}

type SortKey = keyof AgentRecord;

function formatHours(h: number | null): string {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  return `${h.toFixed(1)}h`;
}

function formatRate(r: number | null): string {
  if (r === null || r === undefined) return "—";
  return `${Math.round(r * 100)}%`;
}

function slaColor(rate: number | null): string {
  if (rate === null) return "";
  if (rate > 0.3) return "text-red-600 dark:text-red-400 font-medium";
  if (rate > 0.1) return "text-amber-600 dark:text-amber-400 font-medium";
  return "text-teal-600 dark:text-teal-400 font-medium";
}

function resolutionColor(rate: number): string {
  if (rate >= 0.8) return "text-teal-600 dark:text-teal-400 font-medium";
  if (rate >= 0.5) return "";
  return "text-amber-600 dark:text-amber-400 font-medium";
}

export default function AgentPerformancePage() {
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState(30);
  const [category, setCategory] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("sla_breach_rate");
  const [sortAsc, setSortAsc] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ period_days: String(period) });
      if (category) params.set("category", category);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/tickets/agent-performance?${params}`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, [period, category]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const sorted = data
    ? [...data.agents].sort((a, b) => {
        const av = a[sortKey] as number | null;
        const bv = b[sortKey] as number | null;
        if (av === null && bv === null) return 0;
        if (av === null) return 1;
        if (bv === null) return -1;
        return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
      })
    : [];

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(false); }
  };

  const thClass = (key: SortKey) =>
    `px-3 py-2 text-left text-xs font-semibold cursor-pointer select-none hover:bg-muted/50 ${sortKey === key ? "text-primary" : "text-muted-foreground"}`;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Performance des agents</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Métriques par agent — MTTR, taux de résolution, SLA
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
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
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="ml-4 text-sm px-2 py-1 rounded border border-border bg-background"
        >
          <option value="">Toutes catégories</option>
          {["infrastructure", "network", "security", "application", "email", "hardware"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {loading && <p className="text-sm text-muted-foreground">Chargement...</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {data && !loading && (
        <div className="rounded-xl border border-border overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b border-border">
              <tr>
                <th className={thClass("agent_name")} onClick={() => handleSort("agent_name")}>Agent</th>
                <th className={thClass("tickets_assigned")} onClick={() => handleSort("tickets_assigned")}>Assignés</th>
                <th className={thClass("tickets_resolved")} onClick={() => handleSort("tickets_resolved")}>Résolus</th>
                <th className={thClass("resolution_rate")} onClick={() => handleSort("resolution_rate")}>Taux résolution</th>
                <th className={thClass("mttr_hours")} onClick={() => handleSort("mttr_hours")}>MTTR moy.</th>
                <th className={thClass("mttr_p90_hours")} onClick={() => handleSort("mttr_p90_hours")}>MTTR P90</th>
                <th className={thClass("sla_breach_rate")} onClick={() => handleSort("sla_breach_rate")}>Taux breach SLA</th>
                <th className={thClass("avg_first_action_hours")} onClick={() => handleSort("avg_first_action_hours")}>1ère action moy.</th>
                <th className={thClass("open_ticket_count")} onClick={() => handleSort("open_ticket_count")}>En cours</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((a, i) => (
                <tr key={a.agent_name} className={`border-b border-border ${i % 2 === 0 ? "" : "bg-muted/30"}`}>
                  <td className="px-3 py-2.5 font-medium">{a.agent_name}</td>
                  <td className="px-3 py-2.5 text-center">{a.tickets_assigned}</td>
                  <td className="px-3 py-2.5 text-center">{a.tickets_resolved}</td>
                  <td className={`px-3 py-2.5 text-center ${resolutionColor(a.resolution_rate)}`}>{formatRate(a.resolution_rate)}</td>
                  <td className="px-3 py-2.5 text-center">{formatHours(a.mttr_hours)}</td>
                  <td className="px-3 py-2.5 text-center">{formatHours(a.mttr_p90_hours)}</td>
                  <td className={`px-3 py-2.5 text-center ${slaColor(a.sla_breach_rate)}`}>{formatRate(a.sla_breach_rate)}</td>
                  <td className="px-3 py-2.5 text-center">{formatHours(a.avg_first_action_hours)}</td>
                  <td className="px-3 py-2.5 text-center">{a.open_ticket_count}</td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                    Aucune donnée pour cette période.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <p className="text-xs text-muted-foreground mt-2">
          Généré le {new Date(data.generated_at).toLocaleString("fr-FR")}
        </p>
      )}
    </div>
  );
}
