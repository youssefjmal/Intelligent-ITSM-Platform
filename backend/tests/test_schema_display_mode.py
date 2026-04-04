"""Tests for mode vs display_mode schema debt resolution (Change 7).

Verifies that:
1. AIResolutionAdvice always returns display_mode correctly.
2. The deprecated `mode` field is backfilled from display_mode when omitted.
3. When both fields are present, display_mode is canonical and mode is preserved.
"""

from __future__ import annotations

import pytest

from app.schemas.ai import AIResolutionAdvice


MINIMAL_ADVICE_KWARGS = {
    "reasoning": "Test reasoning",
    "response_text": "Test response",
}


class TestDisplayModeCanonical:
    def test_display_mode_set_mode_backfilled(self):
        """When only display_mode is provided, mode is backfilled from it."""
        advice = AIResolutionAdvice(
            display_mode="tentative_diagnostic",
            **MINIMAL_ADVICE_KWARGS,
        )
        assert advice.display_mode == "tentative_diagnostic"
        # mode must be backfilled to match display_mode
        assert advice.mode == "tentative_diagnostic", (
            "mode was not backfilled from display_mode.  "
            "The model_validator may not be running."
        )

    def test_mode_none_triggers_backfill(self):
        """Explicitly setting mode=None causes it to be backfilled from display_mode."""
        advice = AIResolutionAdvice(
            mode=None,
            display_mode="evidence_action",
            **MINIMAL_ADVICE_KWARGS,
        )
        assert advice.display_mode == "evidence_action"
        assert advice.mode == "evidence_action"

    def test_both_fields_set_display_mode_is_canonical(self):
        """When both fields are present, display_mode holds the canonical value."""
        advice = AIResolutionAdvice(
            mode="evidence_action",
            display_mode="no_strong_match",
            **MINIMAL_ADVICE_KWARGS,
        )
        # display_mode is the authoritative field; mode is kept as-is for compat.
        assert advice.display_mode == "no_strong_match"
        assert advice.mode == "evidence_action"

    def test_default_display_mode_is_evidence_action(self):
        """Default display_mode is 'evidence_action' (unchanged behaviour)."""
        advice = AIResolutionAdvice(**MINIMAL_ADVICE_KWARGS)
        assert advice.display_mode == "evidence_action"
        # mode must also be backfilled to 'evidence_action' by the validator
        assert advice.mode == "evidence_action"

    def test_no_strong_match_backfill(self):
        advice = AIResolutionAdvice(
            display_mode="no_strong_match",
            **MINIMAL_ADVICE_KWARGS,
        )
        assert advice.display_mode == "no_strong_match"
        assert advice.mode == "no_strong_match"

    def test_service_request_backfill(self):
        advice = AIResolutionAdvice(
            display_mode="service_request",
            **MINIMAL_ADVICE_KWARGS,
        )
        assert advice.display_mode == "service_request"
        assert advice.mode == "service_request"

    def test_mode_field_is_optional_str(self):
        """mode is Optional[str] and can be None before the validator runs."""
        # Constructing without mode should not raise
        advice = AIResolutionAdvice(display_mode="evidence_action", **MINIMAL_ADVICE_KWARGS)
        assert advice.mode is not None  # backfilled by validator
