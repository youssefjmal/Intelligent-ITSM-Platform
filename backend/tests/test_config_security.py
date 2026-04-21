"""Unit tests for app.core.config.Settings.validate_runtime_security

WHY THIS FILE EXISTS
--------------------
validate_runtime_security() is the gate that prevents the application from
starting in production with dangerous defaults (empty JWT secret, wildcard
CORS, missing Prometheus token, etc.).  If this function has a bug, a
misconfigured production deployment would start silently with no warnings —
a direct ISO 27001 / security audit failure.

These tests prove each guard works correctly by creating a Settings object
with controlled values (no .env file read) and calling the method directly.

HOW WE ISOLATE THE TESTS (no .env, no side-effects)
----------------------------------------------------
Settings reads its values from environment variables and a .env file.
We bypass both by passing values directly to the constructor:
    s = Settings(JWT_SECRET="...", ENV="production", ...)
This creates an isolated, predictable object — like a mock, but without
needing any mock library.  The actual .env file on the developer's machine
is completely ignored.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


# ---------------------------------------------------------------------------
# Helper — build a Settings object with safe production defaults
# so individual tests only need to override the one field they're testing.
# ---------------------------------------------------------------------------

def _prod(**overrides) -> Settings:
    """Return a production-mode Settings with a safe baseline.

    Any kwarg overrides the corresponding field.
    Example: _prod(JWT_SECRET="weak") → production settings with a weak JWT.
    """
    defaults = dict(
        ENV="production",
        JWT_SECRET="a-very-strong-secret-that-is-at-least-32-chars-long",
        JWT_ALGORITHM="HS256",
        CORS_ORIGINS="https://app.teamwill.com",
        ALLOWED_HOSTS="app.teamwill.com",
        PROMETHEUS_METRICS_ENABLED=False,   # disabled by default to keep tests simple
        N8N_INBOUND_SECRET="secret-for-n8n",
        # Required by pydantic-settings but not tested here
        DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _dev(**overrides) -> Settings:
    """Return a development-mode Settings."""
    defaults = dict(
        ENV="development",
        JWT_SECRET="",
        JWT_ALGORITHM="HS256",
        CORS_ORIGINS="http://localhost:3000",
        ALLOWED_HOSTS="localhost",
        PROMETHEUS_METRICS_ENABLED=False,
        N8N_INBOUND_SECRET="",
        DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# JWT Algorithm guard
# ---------------------------------------------------------------------------


class TestJWTAlgorithmGuard:
    """The 'none' algorithm attack and unknown algorithms must be rejected."""

    def test_none_algorithm_raises(self):
        """Algorithm 'none' must always raise — it disables signature verification.

        This is a known JWT attack vector (CVE-2015-9235-style).
        """
        s = _prod(JWT_ALGORITHM="none")
        with pytest.raises(ValueError, match="not allowed"):
            s.validate_runtime_security()

    def test_none_algorithm_uppercase_raises(self):
        """'NONE' (uppercase) must also be rejected — case-insensitive check."""
        s = _prod(JWT_ALGORITHM="NONE")
        with pytest.raises(ValueError, match="not allowed"):
            s.validate_runtime_security()

    def test_unknown_algorithm_raises(self):
        """An invented algorithm name must be rejected to prevent misconfiguration."""
        s = _prod(JWT_ALGORITHM="MD5")
        with pytest.raises(ValueError, match="not allowed"):
            s.validate_runtime_security()

    def test_valid_algorithm_hs256_passes(self):
        """HS256 is a safe, supported algorithm and must pass validation."""
        s = _prod(JWT_ALGORITHM="HS256")
        s.validate_runtime_security()  # must not raise

    def test_valid_algorithm_rs256_passes(self):
        """RS256 (asymmetric) is also a valid algorithm."""
        s = _prod(JWT_ALGORITHM="RS256")
        s.validate_runtime_security()  # must not raise


# ---------------------------------------------------------------------------
# JWT Secret strength guard
# ---------------------------------------------------------------------------


class TestJWTSecretGuard:
    """Weak JWT secrets must be blocked in production."""

    def test_empty_secret_raises_in_production(self):
        """An empty JWT_SECRET in production must raise — tokens would be forgeable."""
        s = _prod(JWT_SECRET="")
        with pytest.raises(ValueError, match="Insecure JWT_SECRET"):
            s.validate_runtime_security()

    def test_known_default_changeme_raises_in_production(self):
        """'changeme' is a known-weak value that must be rejected."""
        s = _prod(JWT_SECRET="changeme")
        with pytest.raises(ValueError, match="Insecure JWT_SECRET"):
            s.validate_runtime_security()

    def test_short_secret_under_32_chars_raises_in_production(self):
        """A secret shorter than 32 characters is too weak for production."""
        s = _prod(JWT_SECRET="short")
        with pytest.raises(ValueError, match="Insecure JWT_SECRET"):
            s.validate_runtime_security()

    def test_strong_secret_passes(self):
        """A 40-character random secret must pass validation."""
        strong = "x" * 40
        s = _prod(JWT_SECRET=strong)
        s.validate_runtime_security()  # must not raise

    def test_weak_secret_only_warns_in_development(self):
        """In development mode, a weak secret must NOT raise — only warn.

        Developers often run with empty secrets locally.
        Raising would make local development impossible.
        """
        s = _dev(JWT_SECRET="")
        # Must not raise — just emits a log warning
        s.validate_runtime_security()


# ---------------------------------------------------------------------------
# CORS wildcard guard
# ---------------------------------------------------------------------------


class TestCORSGuard:
    """CORS wildcard '*' must be blocked in production."""

    def test_wildcard_cors_raises_in_production(self):
        """'*' in CORS_ORIGINS exposes the API to any browser origin — not allowed in prod."""
        s = _prod(CORS_ORIGINS="*")
        with pytest.raises(ValueError, match="CORS wildcard"):
            s.validate_runtime_security()

    def test_explicit_origin_passes_in_production(self):
        """A specific origin like the frontend URL must be accepted."""
        s = _prod(CORS_ORIGINS="https://app.teamwill.com")
        s.validate_runtime_security()  # must not raise

    def test_multiple_explicit_origins_pass(self):
        """Multiple comma-separated origins (no wildcard) must pass."""
        s = _prod(CORS_ORIGINS="https://app.teamwill.com,https://admin.teamwill.com")
        s.validate_runtime_security()  # must not raise


# ---------------------------------------------------------------------------
# Prometheus token guard
# ---------------------------------------------------------------------------


class TestPrometheusTokenGuard:
    """Prometheus /metrics endpoint must require a strong scrape token in production."""

    def test_missing_token_raises_in_production(self):
        """PROMETHEUS_METRICS_TOKEN must be set when metrics are enabled in production."""
        s = _prod(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="")
        with pytest.raises(ValueError, match="PROMETHEUS_METRICS_TOKEN"):
            s.validate_runtime_security()

    def test_weak_default_token_raises_in_production(self):
        """Known-weak tokens like 'change-me' must be rejected."""
        s = _prod(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="change-me")
        with pytest.raises(ValueError, match="too weak"):
            s.validate_runtime_security()

    def test_short_token_raises_in_production(self):
        """Tokens shorter than 24 characters are rejected in production."""
        s = _prod(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="abc123")
        with pytest.raises(ValueError, match="too weak"):
            s.validate_runtime_security()

    def test_strong_token_passes(self):
        """A 32-character token that is not a known default must pass."""
        strong_token = "prometheus-scrape-token-abcdefgh"  # 32 chars, unique
        s = _prod(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN=strong_token)
        s.validate_runtime_security()  # must not raise

    def test_disabled_metrics_no_token_required(self):
        """When PROMETHEUS_METRICS_ENABLED=False, no token is required."""
        s = _prod(PROMETHEUS_METRICS_ENABLED=False, PROMETHEUS_METRICS_TOKEN="")
        s.validate_runtime_security()  # must not raise


# ---------------------------------------------------------------------------
# prometheus_metrics_token_matches — timing-safe comparison
# ---------------------------------------------------------------------------


class TestPrometheusTokenMatch:
    """The token comparison must use a timing-safe digest (secrets.compare_digest)."""

    def test_correct_token_matches(self):
        s = _prod(PROMETHEUS_METRICS_ENABLED=False, PROMETHEUS_METRICS_TOKEN="correct-token-abcdefghij")
        assert s.prometheus_metrics_token_matches("correct-token-abcdefghij") is True

    def test_wrong_token_does_not_match(self):
        s = _prod(PROMETHEUS_METRICS_ENABLED=False, PROMETHEUS_METRICS_TOKEN="correct-token-abcdefghij")
        assert s.prometheus_metrics_token_matches("wrong-token") is False

    def test_empty_candidate_does_not_match(self):
        s = _prod(PROMETHEUS_METRICS_ENABLED=False, PROMETHEUS_METRICS_TOKEN="some-token-abcdefghij")
        assert s.prometheus_metrics_token_matches("") is False
        assert s.prometheus_metrics_token_matches(None) is False

    def test_empty_configured_token_does_not_match(self):
        """If no token is configured, no candidate should match (fail closed)."""
        s = _dev(PROMETHEUS_METRICS_ENABLED=False, PROMETHEUS_METRICS_TOKEN="")
        assert s.prometheus_metrics_token_matches("anything") is False


# ---------------------------------------------------------------------------
# Jira config readiness helpers
# ---------------------------------------------------------------------------


class TestJiraConfigReadiness:
    """jira_ready and jira_config_error must correctly detect misconfiguration."""

    def test_missing_base_url_detected(self):
        s = _dev(JIRA_BASE_URL="", JIRA_EMAIL="a@b.com", JIRA_API_TOKEN="tok")
        assert s.jira_config_error == "missing_jira_base_url"
        assert s.jira_ready is False

    def test_invalid_base_url_detected(self):
        """A URL without http:// or https:// must be rejected."""
        s = _dev(JIRA_BASE_URL="jira.teamwill.com", JIRA_EMAIL="a@b.com", JIRA_API_TOKEN="tok")
        assert s.jira_config_error == "invalid_jira_base_url"

    def test_missing_email_detected(self):
        s = _dev(JIRA_BASE_URL="https://jira.example.com", JIRA_EMAIL="", JIRA_API_TOKEN="tok")
        assert s.jira_config_error == "missing_jira_email"

    def test_missing_api_token_detected(self):
        s = _dev(JIRA_BASE_URL="https://jira.example.com", JIRA_EMAIL="a@b.com", JIRA_API_TOKEN="")
        assert s.jira_config_error == "missing_jira_api_token"

    def test_fully_configured_jira_is_ready(self):
        s = _dev(
            JIRA_BASE_URL="https://jira.example.com",
            JIRA_EMAIL="admin@example.com",
            JIRA_API_TOKEN="token-abc",
        )
        assert s.jira_config_error is None
        assert s.jira_ready is True
