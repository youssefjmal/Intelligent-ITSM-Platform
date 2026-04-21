"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import secrets
import warnings
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "Jira Ticket Management"
    ENV: str = "development"

    DATABASE_URL: str = "postgresql+psycopg://postgres@localhost:5432/jira_tickets"

    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour — was 24h; stolen tokens expire quickly
    COOKIE_NAME: str = "tw_access"
    REFRESH_COOKIE_NAME: str = "tw_refresh"
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    LOG_LEVEL: str = "INFO"

    EMAIL_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 2

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True
    
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"
    N8N_INBOUND_SECRET: str = ""
    N8N_OUTBOUND_SECRET: str = ""
    N8N_WEBHOOK_BASE_URL: str = ""
    #google login using oauth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    # Groq provider credentials for text generation
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    # Ollama — used for embeddings only (nomic-embed-text)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "nomic-embed-text"  # kept for reference; text-generation calls go to Groq
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_EMBEDDING_DIM: int = 768
    OLLAMA_EMBED_TIMEOUT_SECONDS: int = 60
    # -1 means "use Ollama default placement" (typically GPU when available).
    OLLAMA_EMBED_NUM_GPU: int = -1
    AI_SLA_RISK_ENABLED: bool = True
    AI_SLA_RISK_MODE: str = "active"
    SLA_AT_RISK_MINUTES: int = 30
    SLA_ESCALATE_HIGH_MINUTES: int = 10
    SLA_ESCALATE_STEP_MINUTES: int = 30
    SLA_STALE_STATUS_MINUTES: int = 120
    SLA_DEADLINE_ALERT_MINUTES: int = 30
    SLA_AI_HIGH_RISK_SCORE_THRESHOLD: float = 0.8
    SLA_ADVISOR_RAG_TOP_K: int = 4
    AI_CLASSIFY_SEMANTIC_TOP_K: int = 5
    AI_CLASSIFY_STRONG_SIMILARITY_THRESHOLD: float = 0.72
    AI_CLASSIFY_MAX_RECOMMENDATIONS: int = 4
    OFFTOPIC_SIMILARITY_THRESHOLD: float = 0.28
    # jira credentials
    JIRA_BASE_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = ""
    JIRA_SERVICE_DESK_ID: str = ""
    JIRA_DEFAULT_REQUEST_TYPE_ID: str = ""
    JIRA_DEFAULT_REQUEST_TYPE_NAME: str = "Emailed request"
    JIRA_REQUEST_TYPE_FIELD: str = "customfield_10010"
    JIRA_KB_ENABLED: bool = True
    JIRA_KB_MAX_ISSUES: int = 60
    JIRA_KB_MAX_COMMENTS_PER_ISSUE: int = 5
    JIRA_KB_TOP_MATCHES: int = 5
    JIRA_KB_CACHE_SECONDS: int = 300
    JIRA_KB_ARTICLE_PROJECT_KEY: str = ""   # KB project for published articles (defaults to JIRA_PROJECT_KEY)
    JIRA_KB_ARTICLE_ISSUE_TYPE: str = "Story"  # Issue type used when creating KB articles
    # Confluence Knowledge Base — space key of the JSM-linked Confluence space.
    # When set, published drafts create a real Confluence page (visible in JSM KB sidebar).
    # Same JIRA_EMAIL + JIRA_API_TOKEN are used for auth — no extra credentials needed.
    CONFLUENCE_SPACE_KEY: str = ""  # e.g. "TWC"

    # Redis cache
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_ENABLED: bool = True
    CACHE_TTL_STATS: int = 300         # 5 min  — GET /tickets/stats
    CACHE_TTL_INSIGHTS: int = 300      # 5 min  — GET /tickets/insights
    CACHE_TTL_PERFORMANCE: int = 900   # 15 min — GET /tickets/performance
    CACHE_TTL_AGENT_PERF: int = 1200   # 20 min — GET /tickets/agent-performance
    CACHE_TTL_SIMILAR: int = 600       # 10 min — GET /tickets/{id}/similar
    CACHE_TTL_RECOMMENDATIONS: int = 900   # 15 min — GET /recommendations/
    CACHE_TTL_SLA_STRATEGIES: int = 1200   # 20 min — GET /recommendations/sla-strategies
    CACHE_TTL_EMBEDDING: int = 86400   # 24 h   — embedding vectors
    JIRA_SYNC_PAGE_SIZE: int = 50
    JIRA_WEBHOOK_SECRET: str = ""
    ALLOW_INSECURE_JIRA_WEBHOOKS: bool = False
    JIRA_AUTO_RECONCILE_ENABLED: bool = True
    JIRA_AUTO_RECONCILE_INTERVAL_SECONDS: int = 300
    JIRA_AUTO_RECONCILE_LOOKBACK_DAYS: int = 30
    JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS: int = 10

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 120
    RATE_LIMIT_AUTH_MAX_REQUESTS: int = 20
    RATE_LIMIT_AI_MAX_REQUESTS: int = 30
    PROMETHEUS_METRICS_ENABLED: bool = True
    PROMETHEUS_METRICS_TOKEN: str = ""
    PROMETHEUS_METRICS_WEAK_TOKENS: str = "local-prom-scrape-token,change-me,changeme,default,metrics-secret"
    # External monitoring dashboard URLs (surfaced to admin via GET /api/admin/monitoring/dashboards)
    GRAFANA_BASE_URL: str = "http://localhost:3003"
    PROMETHEUS_BASE_URL: str = "http://localhost:9090"

    # Proxy trust — only set TRUST_PROXY=true when running behind a known
    # reverse proxy (nginx, Caddy, AWS ALB).  When false, the rate limiter
    # uses request.client.host and never reads X-Forwarded-For.
    TRUST_PROXY: bool = False
    TRUSTED_PROXY_DEPTH: int = 1  # how many rightmost hops to trust

    # Per-account brute-force lockout
    LOGIN_MAX_ATTEMPTS: int = 5        # failures before lockout
    LOGIN_LOCKOUT_MINUTES: int = 15    # how long the account is locked

    # ── ISO 27001 compliance settings (A.12.4 — logging & monitoring) ─────────
    # How long to retain security_events rows (days). 0 = keep forever.
    # ISO 27001 recommends a minimum of 1 year; set to 365 in production.
    AUDIT_LOG_RETENTION_DAYS: int = 365

    # ── ISO 27001 data classification (A.8.2) ─────────────────────────────────
    # These are configuration-level labels — they describe what is held in each
    # category so the ISMS documentation can reference concrete settings.
    # Levels: PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED
    DATA_CLASS_TICKET_CONTENT: str = "CONFIDENTIAL"   # title, description, comments
    DATA_CLASS_USER_PII: str = "CONFIDENTIAL"          # email, name, role
    DATA_CLASS_AUDIT_LOGS: str = "RESTRICTED"          # security_events table
    DATA_CLASS_AI_LOGS: str = "CONFIDENTIAL"           # ai_classification_logs

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]
        return hosts or ["localhost", "127.0.0.1"]

    @property
    def jira_config_error(self) -> str | None:
        base_url = self.JIRA_BASE_URL.strip()
        if not base_url:
            return "missing_jira_base_url"
        if not base_url.lower().startswith(("http://", "https://")):
            return "invalid_jira_base_url"
        if not self.JIRA_EMAIL.strip():
            return "missing_jira_email"
        if not self.JIRA_API_TOKEN.strip():
            return "missing_jira_api_token"
        return None

    @property
    def jira_ready(self) -> bool:
        return self.jira_config_error is None

    @property
    def jira_kb_ready(self) -> bool:
        return bool(self.JIRA_KB_ENABLED and self.jira_ready)

    @property
    def confluence_ready(self) -> bool:
        """True when Jira credentials + Confluence space key are all set."""
        return bool(self.jira_ready and self.CONFLUENCE_SPACE_KEY.strip())

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() in {"prod", "production"}

    _ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}

    @property
    def weak_prometheus_metrics_tokens(self) -> set[str]:
        return {
            token.strip()
            for token in self.PROMETHEUS_METRICS_WEAK_TOKENS.split(",")
            if token.strip()
        }

    def validate_runtime_security(self) -> None:
        # Reject dangerous algorithm values including the "none" attack vector
        algo = self.JWT_ALGORITHM.strip()
        if algo.lower() == "none" or algo not in self._ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"JWT_ALGORITHM '{algo}' is not allowed. "
                f"Choose one of: {sorted(self._ALLOWED_JWT_ALGORITHMS)}"
            )

        jwt_secret = self.JWT_SECRET.strip()
        weak_secret = jwt_secret in {"", "change-me", "changeme", "secret", "default"} or len(jwt_secret) < 32

        if self.is_production and weak_secret:
            raise ValueError("Insecure JWT_SECRET for production. Use a strong secret (>= 32 chars).")

        if self.is_production and "*" in self.cors_origins:
            raise ValueError("CORS wildcard is not allowed in production. Set explicit origins.")
        if self.is_production and "*" in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS wildcard is not allowed in production. Set explicit hosts.")
        if self.is_production and self.ALLOW_INSECURE_JIRA_WEBHOOKS:
            raise ValueError("ALLOW_INSECURE_JIRA_WEBHOOKS is not allowed in production.")

        if weak_secret and not self.is_production:
            logging.getLogger(__name__).warning(
                "Weak JWT_SECRET detected for non-production environment. Use a strong secret before deployment."
            )

        if self.PROMETHEUS_METRICS_ENABLED and not self.PROMETHEUS_METRICS_TOKEN.strip():
            message = (
                "PROMETHEUS_METRICS_TOKEN is required when PROMETHEUS_METRICS_ENABLED=true. "
                "Set a dedicated scrape token for Prometheus."
            )
            if self.is_production:
                raise ValueError(message)
            warnings.warn(message, stacklevel=2)
        elif self.PROMETHEUS_METRICS_ENABLED:
            metrics_token = self.PROMETHEUS_METRICS_TOKEN.strip()
            weak_metrics_token = (
                metrics_token in self.weak_prometheus_metrics_tokens
                or len(metrics_token) < 24
            )
            if weak_metrics_token:
                message = (
                    "PROMETHEUS_METRICS_TOKEN is too weak or uses a known default. "
                    "Set a long, unique scrape token before exposing /metrics."
                )
                if self.is_production:
                    raise ValueError(message)
                warnings.warn(message, stacklevel=2)

        if not self.N8N_INBOUND_SECRET.strip() and self.is_production:
            warnings.warn(
                "N8N_INBOUND_SECRET is not set. "
                "POST /api/notifications/system is disabled.",
                stacklevel=2,
            )

    def prometheus_metrics_token_matches(self, candidate: str | None) -> bool:
        expected = self.PROMETHEUS_METRICS_TOKEN.strip()
        provided = (candidate or "").strip()
        if not expected or not provided:
            return False
        return secrets.compare_digest(expected, provided)


settings = Settings()
