"""Tests for negation detection in resolver._extract_attempted_steps (Change 3).

Guards against the bug where "I haven't restarted the service" caused 'restart'
to be added to the attempted-steps list, which would cause the resolver to skip
recommending a restart that was never actually tried.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.resolver import (
    NEGATION_MARKERS,
    NEGATION_WINDOW_SIZE,
    _extract_attempted_steps,
    _has_negation_near_match,
)


# ---------------------------------------------------------------------------
# _has_negation_near_match — unit tests
# ---------------------------------------------------------------------------


class TestHasNegationNearMatch:
    def test_negation_immediately_before_keyword(self):
        """"not restarted" — negation at index 0, keyword at index 1."""
        tokens = ["not", "restarted", "service"]
        assert _has_negation_near_match(tokens, match_index=1) is True

    def test_negation_within_window(self):
        """Negation 3 tokens before the keyword — inside default window of 4."""
        tokens = ["i", "have", "never", "tried", "restarting", "this"]
        # 'restarting' is at index 4; 'never' is at index 2 (distance 2)
        assert _has_negation_near_match(tokens, match_index=4) is True

    def test_negation_outside_window_not_detected(self):
        """Negation too far away (distance > NEGATION_WINDOW_SIZE) is ignored."""
        tokens = ["never", "mind", "please", "do", "it", "restart", "now"]
        # 'restart' is at index 5; 'never' is at index 0 (distance 5 > 4)
        assert _has_negation_near_match(tokens, match_index=5) is False

    def test_no_negation_present(self):
        tokens = ["i", "already", "restarted", "the", "service"]
        assert _has_negation_near_match(tokens, match_index=2) is False

    def test_contraction_negation(self):
        """Contractions like "haven't" must be detected."""
        tokens = ["i", "haven't", "restarted", "yet"]
        assert _has_negation_near_match(tokens, match_index=2) is True

    def test_empty_tokens_returns_false(self):
        """Edge case: empty token list returns False (conservative)."""
        assert _has_negation_near_match([], match_index=0) is False

    def test_out_of_range_index_returns_false(self):
        """Out-of-range match_index returns False (conservative)."""
        assert _has_negation_near_match(["restart", "service"], match_index=10) is False


# ---------------------------------------------------------------------------
# _extract_attempted_steps — integration tests
# ---------------------------------------------------------------------------


def _make_state(messages: list[tuple[str, str]]) -> SimpleNamespace:
    """Build a minimal conversation_state compatible with resolver helpers."""
    return SimpleNamespace(
        messages=[
            SimpleNamespace(role=role, content=content)
            for role, content in messages
        ]
    )


class TestExtractAttemptedSteps:
    def test_negated_restart_not_added(self):
        """'I haven't restarted the service yet' must NOT add restart to attempted list."""
        state = _make_state([
            ("user", "I haven't restarted the service yet."),
        ])
        result = _extract_attempted_steps(state)
        assert result == [], (
            "Negated restart was added to the attempted list.  "
            "The negation detector failed to suppress it."
        )

    def test_confirmed_restart_is_added(self):
        """'I already restarted the service' MUST add the sentence to the attempted list."""
        state = _make_state([
            ("user", "I already restarted the service twice."),
        ])
        result = _extract_attempted_steps(state)
        assert len(result) == 1, (
            "Confirmed attempted step was not detected."
        )
        assert "restarted" in result[0].lower()

    def test_negated_password_reset_not_added(self):
        """'I never tried resetting the password' must NOT add reset to attempted list."""
        state = _make_state([
            ("user", "I never tried resetting the password on that account."),
        ])
        result = _extract_attempted_steps(state)
        assert result == [], (
            "Negated password reset was incorrectly added to the attempted list."
        )

    def test_single_token_sentence_without_negation_is_added(self):
        """A short sentence with an attempt keyword and no negation IS added (conservative)."""
        state = _make_state([
            ("user", "Restarted."),
        ])
        result = _extract_attempted_steps(state)
        # "Restarted." contains "restarted" with no negation; should be recorded.
        assert len(result) == 1

    def test_multiple_sentences_mixed_negation(self):
        """Only the affirmative sentence is added when both are present."""
        state = _make_state([
            ("user", "I already cleared the cache. I haven't tried resetting the token yet."),
        ])
        result = _extract_attempted_steps(state)
        # Only 'cleared the cache' should appear
        assert len(result) == 1
        assert "cleared" in result[0].lower()

    def test_assistant_messages_are_ignored(self):
        """Attempted step detection only operates on user messages."""
        state = _make_state([
            ("assistant", "I already restarted the service on my end."),
        ])
        result = _extract_attempted_steps(state)
        assert result == []

    def test_empty_conversation_returns_empty_list(self):
        assert _extract_attempted_steps(None) == []
        assert _extract_attempted_steps(_make_state([])) == []


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------


class TestNegationConstants:
    def test_negation_markers_is_frozenset(self):
        assert isinstance(NEGATION_MARKERS, frozenset)

    def test_core_negation_markers_present(self):
        for marker in ("not", "never", "haven't", "didn't", "no", "n't", "cannot"):
            assert marker in NEGATION_MARKERS, f"Expected '{marker}' in NEGATION_MARKERS"

    def test_negation_window_size_is_positive_int(self):
        assert isinstance(NEGATION_WINDOW_SIZE, int)
        assert NEGATION_WINDOW_SIZE > 0
