"""Central Prometheus metric definitions.

All application metrics are declared here so they are registered exactly once.
Declaring metrics in individual modules can cause duplicate-registration errors
when Uvicorn reloads modules in ``--reload`` mode or when multiple workers
share a process-level registry.

Metrics are scraped by Prometheus via ``GET /metrics`` (token-protected).
Grafana reads from Prometheus to build the operations dashboard.

Label cardinality note
----------------------
Keep label values low-cardinality (a fixed set of known strings, not user IDs
or ticket IDs).  High-cardinality labels create millions of time-series and
can crash Prometheus.
"""
from prometheus_client import Counter, Histogram

# ── Cache ──────────────────────────────────────────────────────────────────
# Labeled by ``resource`` (e.g. "stats", "insights", "embedding") so ops can
# see per-resource hit rates and tune TTLs individually.
cache_hits_total = Counter(
    "itsm_cache_hits_total",
    "Number of Redis cache hits",
    ["resource"],
)
cache_misses_total = Counter(
    "itsm_cache_misses_total",
    "Number of Redis cache misses (key absent or Redis unavailable)",
    ["resource"],
)

# ── Rate limiting ──────────────────────────────────────────────────────────
# Labeled by ``scope`` ("default" | "auth" | "ai") — auth and AI routes have
# stricter limits than general API calls.
rate_limit_exceeded_total = Counter(
    "itsm_rate_limit_exceeded_total",
    "Number of requests rejected by the rate limiter",
    ["scope"],
)

# ── AI pipeline ────────────────────────────────────────────────────────────
# Histogram buckets are tuned for typical LLM latency (100 ms – 30 s).
# The ``operation`` label distinguishes chat rounds, batch classification, and
# draft suggestions so slow operations can be identified individually.
ai_pipeline_duration_seconds = Histogram(
    "itsm_ai_pipeline_duration_seconds",
    "End-to-end duration of AI orchestrator calls",
    ["operation"],  # "chat" | "classify" | "suggest"
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ── n8n machine-auth boundary ──────────────────────────────────────────────
# Counts every inbound webhook authentication attempt from n8n.
# ``outcome`` is one of: "accepted" | "rejected" | "config_missing".
# An alert on ``rejected`` spikes detects misconfigured or hijacked webhooks.
n8n_machine_auth_total = Counter(
    "itsm_n8n_machine_auth_total",
    "Inbound n8n machine-auth outcomes",
    ["endpoint", "outcome"],
)
