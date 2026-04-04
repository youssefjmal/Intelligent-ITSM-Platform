"""Tests for intent detection word-boundary matching (Change 2).

Guards against false-positive intent classifications caused by substring
matching (e.g. "open" matching "open_source_vulnerability").

Also verifies that the LLM fallback confidence returns "low" rather than
inheriting an ambiguous rule-based confidence level.
"""

from __future__ import annotations

import pytest

from app.services.ai.intents import (
    LLM_FALLBACK_DEFAULT_CONFIDENCE,
    IntentConfidence,
    _contains_any,
    _matches_keyword,
    detect_intent,
    detect_intent_hybrid_details,
    detect_intent_with_confidence,
    ChatIntent,
)
from app.services.ai.conversation_policy import OPEN_TICKET_KEYWORDS


# ---------------------------------------------------------------------------
# _matches_keyword — unit tests
# ---------------------------------------------------------------------------


class TestMatchesKeyword:
    def test_single_word_matches_whole_word(self):
        """'open' must match 'open ticket' (whole-word context)."""
        assert _matches_keyword("open ticket please", "open") is True

    def test_single_word_does_not_match_substring(self):
        """'open' must NOT match 'open_source_vulnerability' (substring)."""
        assert _matches_keyword("open_source_vulnerability reported", "open") is False

    def test_single_word_does_not_match_reopen(self):
        """'open' must NOT match 'reopen' (prefixed token)."""
        assert _matches_keyword("please reopen the case", "open") is False

    def test_multi_word_phrase_matches_substring(self):
        """Multi-word phrases use substring match since boundaries are implicit."""
        assert _matches_keyword("show all open tickets please", "open tickets") is True

    def test_multi_word_phrase_not_found(self):
        assert _matches_keyword("close this incident", "open tickets") is False

    def test_empty_keyword_returns_false(self):
        assert _matches_keyword("some text", "") is False

    def test_empty_text_returns_false(self):
        assert _matches_keyword("", "open") is False

    def test_case_insensitive_match(self):
        assert _matches_keyword("OPEN a new ticket", "open") is True

    def test_close_does_not_match_enclose(self):
        """'close' must NOT match 'enclose'."""
        assert _matches_keyword("please enclose the document", "close") is False


# ---------------------------------------------------------------------------
# _contains_any — unit tests
# ---------------------------------------------------------------------------


class TestContainsAny:
    def test_returns_true_on_first_keyword_match(self):
        assert _contains_any("open ticket for me", ["open", "create"]) is True

    def test_returns_false_when_no_keywords_match(self):
        assert _contains_any("show recent tickets", ["open", "create"]) is False

    def test_substring_false_positive_is_prevented(self):
        """open_source must not trigger the open keyword match."""
        assert _contains_any("open_source_vulnerability found", ["open"]) is False

    def test_multi_word_phrase_still_matches(self):
        assert _contains_any("please open tickets for review", ["open tickets"]) is True


# ---------------------------------------------------------------------------
# Full intent detection — false-positive regression tests
# ---------------------------------------------------------------------------


class TestIntentFalsePositives:
    def test_open_source_vulnerability_does_not_trigger_open_intent(self):
        """open_source_vulnerability must not trigger the open-ticket route."""
        text = "open_source_vulnerability in our auth library needs patching"
        intent, _ = detect_intent_with_confidence(text)
        # Must not classify as create_ticket due to "open" substring
        assert intent != ChatIntent.create_ticket, (
            "'open' in 'open_source_vulnerability' triggered create_ticket intent — "
            "word-boundary matching regression."
        )

    def test_reopen_triggers_correct_intent_not_false_create(self):
        """'reopen this ticket' should NOT trigger create_ticket via 'open' substring."""
        # 'reopen' alone should not match the open-ticket keyword 'open'
        # (the word 'open' is not present as a standalone word here)
        text = "can you reopen this incident"
        intent, _ = detect_intent_with_confidence(text)
        # 'reopen' should not drive a create_ticket classification
        assert intent != ChatIntent.create_ticket

    def test_close_the_connection_does_not_trigger_close_intent(self):
        """'close the connection' should be general, not a ticket-close action."""
        text = "close the database connection before running the migration"
        intent, _ = detect_intent_with_confidence(text)
        # Should be general/data_query, not a ticket status close action
        assert intent in {ChatIntent.general, ChatIntent.data_query}


# ---------------------------------------------------------------------------
# LLM fallback confidence
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Negation check in problem listing intent
# ---------------------------------------------------------------------------


class TestProblemListingNegation:
    def test_no_problems_does_not_trigger_listing(self):
        """
        "there are no problems" contains "problems" but the negation
        "no" within 3 tokens should prevent problem listing intent.
        """
        result = detect_intent("there are no problems with this implementation")
        assert result != ChatIntent.problem_listing, (
            "'there are no problems' triggered problem_listing intent — "
            "negation check regression."
        )

    def test_problems_alone_triggers_listing(self):
        """
        "quels sont les problèmes" should still trigger problem listing.
        """
        result = detect_intent("quels sont les problèmes")
        assert result == ChatIntent.problem_listing, (
            "'quels sont les problèmes' did not trigger problem_listing intent."
        )


class TestLlmFallbackConfidence:
    def test_fallback_default_confidence_is_low(self):
        """The module-level constant must be 'low', not 'medium'."""
        assert LLM_FALLBACK_DEFAULT_CONFIDENCE == "low", (
            "LLM_FALLBACK_DEFAULT_CONFIDENCE was changed from 'low'.  "
            "Setting it to 'medium' would over-trust ambiguous LLM results."
        )

    def test_fallback_confidence_is_valid_intent_confidence_value(self):
        """LLM_FALLBACK_DEFAULT_CONFIDENCE must be a valid IntentConfidence value."""
        assert LLM_FALLBACK_DEFAULT_CONFIDENCE in {c.value for c in IntentConfidence}


class TestProblemListingInventoryPhrasing:
    def test_descriptive_problems_statement_does_not_trigger_listing(self):
        result = detect_intent("there are problems with the deployment pipeline")
        assert result != ChatIntent.problem_listing, (
            "'there are problems with the deployment pipeline' triggered problem_listing intent."
        )
