"""Central Prometheus metric definitions.

Import from here — declaring metrics in one place prevents duplicate
registration errors when Uvicorn reloads modules in --reload mode.
"""
from prometheus_client import Counter, Histogram

# ── Cache ──────────────────────────────────────────────────────────────────
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
rate_limit_exceeded_total = Counter(
    "itsm_rate_limit_exceeded_total",
    "Number of requests rejected by the rate limiter",
    ["scope"],
)

# ── AI pipeline ────────────────────────────────────────────────────────────
ai_pipeline_duration_seconds = Histogram(
    "itsm_ai_pipeline_duration_seconds",
    "End-to-end duration of AI orchestrator calls",
    ["operation"],  # "chat" | "classify" | "suggest"
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# n8n / machine-auth boundary metrics
n8n_machine_auth_total = Counter(
    "itsm_n8n_machine_auth_total",
    "Inbound n8n machine-auth outcomes",
    ["endpoint", "outcome"],  # "accepted" | "rejected" | "config_missing"
)
