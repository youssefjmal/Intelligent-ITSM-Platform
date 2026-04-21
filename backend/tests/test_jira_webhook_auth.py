"""Unit tests for validate_webhook_secret in app.integrations.jira.service

WHY THIS FILE EXISTS
--------------------
validate_webhook_secret() is the first line of defence against forged Jira
webhooks.  If an attacker can bypass it, they can inject arbitrary ticket
data into the platform.  These tests verify every acceptance/rejection branch
so a future refactor cannot accidentally break the guard.

HOW WE MOCK THE SETTINGS
-------------------------
validate_webhook_secret() reads settings.JIRA_WEBHOOK_SECRET at call time.
We use monkeypatch to override ONLY that one attribute on the already-created
settings singleton — no database, no HTTP calls, no file reads.

This is a standard unit-test technique: replace the external dependency
(configuration) with a controlled value, then test the pure logic.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.integrations.jira.service import validate_webhook_secret


# ---------------------------------------------------------------------------
# When no webhook secret is configured
# ---------------------------------------------------------------------------


class TestNoSecretConfigured:
    """Missing configuration must fail closed unless insecure dev mode is explicit."""

    def test_no_header_fails_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="", allow_insecure=False),
        )
        assert validate_webhook_secret(None) is False

    def test_wrong_header_still_fails_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="", allow_insecure=False),
        )
        assert validate_webhook_secret("totally-wrong") is False

    def test_explicit_insecure_mode_allows_unconfigured_requests(self, monkeypatch):
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="", allow_insecure=True),
        )
        assert validate_webhook_secret(None) is True


# ---------------------------------------------------------------------------
# Direct secret header match (simple token comparison)
# ---------------------------------------------------------------------------


class TestDirectSecretHeader:
    """The simplest mode: Jira sends the raw secret in X-Jira-Webhook-Secret."""

    def test_correct_secret_header_passes(self, monkeypatch):
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="my-webhook-secret"),
        )
        assert validate_webhook_secret("my-webhook-secret") is True

    def test_wrong_secret_header_fails(self, monkeypatch):
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="my-webhook-secret"),
        )
        assert validate_webhook_secret("wrong-secret") is False

    def test_empty_secret_header_fails(self, monkeypatch):
        """An empty header value must NOT match a configured secret."""
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="my-webhook-secret"),
        )
        assert validate_webhook_secret("") is False

    def test_none_header_fails(self, monkeypatch):
        """No header at all (None) must fail when a secret is configured."""
        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret="my-webhook-secret"),
        )
        assert validate_webhook_secret(None) is False


# ---------------------------------------------------------------------------
# HMAC-SHA256 signature verification (legacy header mode)
# ---------------------------------------------------------------------------


class TestHMACSignatureVerification:
    """Legacy mode: Jira sends an HMAC-SHA256 signature in X-Signature.

    This is how some older Jira webhook configurations work.
    The signature is HMAC-SHA256(secret, body).hexdigest().
    """

    def _make_signature(self, secret: str, body: bytes) -> str:
        """Helper: compute the correct HMAC-SHA256 signature for a body."""
        return hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

    def test_valid_hmac_signature_passes(self, monkeypatch):
        """A correctly computed HMAC signature must be accepted."""
        secret = "shared-secret-key"
        body = b'{"issue": {"key": "TW-1"}, "webhookEvent": "jira:issue_updated"}'
        signature = self._make_signature(secret, body)

        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret=secret),
        )
        result = validate_webhook_secret(
            None,  # no direct header
            signature_header=signature,
            raw_body=body,
        )
        assert result is True

    def test_tampered_body_fails_hmac(self, monkeypatch):
        """If the body was modified in transit, the HMAC must not match.

        This is the core security property: an attacker who intercepts and
        modifies the payload cannot forge a valid signature.
        """
        secret = "shared-secret-key"
        original_body = b'{"issue": {"key": "TW-1"}}'
        tampered_body = b'{"issue": {"key": "TW-999"}}'
        signature = self._make_signature(secret, original_body)

        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret=secret),
        )
        result = validate_webhook_secret(
            None,
            signature_header=signature,
            raw_body=tampered_body,  # body doesn't match the signature
        )
        assert result is False

    def test_wrong_hmac_signature_fails(self, monkeypatch):
        """An HMAC computed with the wrong secret must be rejected."""
        real_secret = "real-secret"
        attacker_secret = "attacker-secret"
        body = b'{"issue": {"key": "TW-1"}}'
        forged_signature = self._make_signature(attacker_secret, body)

        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret=real_secret),
        )
        result = validate_webhook_secret(
            None,
            signature_header=forged_signature,
            raw_body=body,
        )
        assert result is False

    def test_hmac_without_body_fails(self, monkeypatch):
        """A valid-looking signature with no body to verify against must fail."""
        secret = "shared-secret"
        body = b'{"issue": {"key": "TW-1"}}'
        signature = self._make_signature(secret, body)

        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret=secret),
        )
        result = validate_webhook_secret(
            None,
            signature_header=signature,
            raw_body=None,  # no body provided
        )
        assert result is False


# ---------------------------------------------------------------------------
# Priority: direct header wins over HMAC
# ---------------------------------------------------------------------------


class TestPriority:
    """When both header types are present, the direct secret header is checked first."""

    def test_correct_direct_header_wins_even_with_wrong_hmac(self, monkeypatch):
        """If the direct header is correct, the request passes regardless of the HMAC."""
        secret = "my-secret"
        body = b'{"issue": {"key": "TW-1"}}'

        monkeypatch.setattr(
            "app.integrations.jira.service.settings",
            _fake_settings(webhook_secret=secret),
        )
        result = validate_webhook_secret(
            secret,  # correct direct header
            signature_header="wrong-hmac",
            raw_body=body,
        )
        assert result is True


# ---------------------------------------------------------------------------
# Private helper — fake settings object
# ---------------------------------------------------------------------------


def _fake_settings(*, webhook_secret: str, allow_insecure: bool = False):
    """Create a minimal settings-like object with only the field we need.

    Using a SimpleNamespace is simpler than monkeypatching every field
    on the real Settings singleton.
    """
    from types import SimpleNamespace
    return SimpleNamespace(
        JIRA_WEBHOOK_SECRET=webhook_secret,
        ALLOW_INSECURE_JIRA_WEBHOOKS=allow_insecure,
    )
