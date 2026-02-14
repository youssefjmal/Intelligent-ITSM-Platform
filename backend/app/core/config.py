"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "Jira Ticket Management"
    ENV: str = "development"

    DATABASE_URL: str = "postgresql+psycopg://postgres@localhost:5432/jira_tickets"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
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
    #google login using oauth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    #ollama credentials
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"
    # jira credentials
    JIRA_BASE_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = ""
    JIRA_SERVICE_DESK_ID: str = ""
    JIRA_KB_ENABLED: bool = True
    JIRA_KB_MAX_ISSUES: int = 60
    JIRA_KB_MAX_COMMENTS_PER_ISSUE: int = 5
    JIRA_KB_TOP_MATCHES: int = 5
    JIRA_KB_CACHE_SECONDS: int = 300
    JIRA_SYNC_PAGE_SIZE: int = 50
    JIRA_WEBHOOK_SECRET: str = ""

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 120
    RATE_LIMIT_AUTH_MAX_REQUESTS: int = 20
    RATE_LIMIT_AI_MAX_REQUESTS: int = 30

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def jira_kb_ready(self) -> bool:
        return bool(
            self.JIRA_KB_ENABLED
            and self.JIRA_BASE_URL.strip()
            and self.JIRA_EMAIL.strip()
            and self.JIRA_API_TOKEN.strip()
        )


settings = Settings()
