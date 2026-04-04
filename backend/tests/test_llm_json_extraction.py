"""Tests for llm.extract_json — verifies that ast.literal_eval is NOT used
and that the fallback chain handles edge cases safely.

Change 1 guard: any regression that re-introduces ast.literal_eval would allow
arbitrary Python expressions to be evaluated against LLM output, which is a
code-execution risk.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.services.ai.llm import _parse_candidate, extract_json


# ---------------------------------------------------------------------------
# _parse_candidate — unit tests
# ---------------------------------------------------------------------------


class TestParseCandidate:
    def test_valid_json_returns_dict(self):
        """Standard valid JSON string is parsed correctly via json.loads."""
        result = _parse_candidate('{"key": "value", "count": 3}')
        assert result == {"key": "value", "count": 3}

    def test_trailing_comma_cleaned_and_parsed(self):
        """Trailing comma is stripped before json.loads so it parses successfully."""
        result = _parse_candidate('{"key": "value",}')
        assert result == {"key": "value"}

    def test_python_expression_is_not_evaluated(self):
        """A Python expression that ast.literal_eval could evaluate must return None.

        This is the core security regression guard for Change 1.
        The string below looks like a dict literal in Python but is not valid
        JSON, so json.loads will raise and _parse_candidate must return None
        instead of evaluating it.
        """
        python_expr = "__import__('os').system('id')"
        result = _parse_candidate(python_expr)
        assert result is None, (
            "Python expression was evaluated — ast.literal_eval may have been "
            "re-introduced.  This is a security regression."
        )

    def test_python_dict_literal_not_evaluated(self):
        """A Python dict literal with single quotes is NOT valid JSON.

        ast.literal_eval would parse {'key': 'value'} successfully.
        json.loads rejects it.  _parse_candidate must return None.
        """
        python_dict = "{'key': 'value'}"
        result = _parse_candidate(python_dict)
        assert result is None, (
            "Python dict literal was parsed — ast.literal_eval may have been "
            "re-introduced.  Only json.loads should be used."
        )

    def test_empty_string_returns_none(self):
        assert _parse_candidate("") is None

    def test_none_returns_none(self):
        assert _parse_candidate(None) is None  # type: ignore[arg-type]

    def test_non_dict_json_returns_none(self):
        """JSON arrays and scalars are not dicts; should return None."""
        assert _parse_candidate("[1, 2, 3]") is None
        assert _parse_candidate('"just a string"') is None

    def test_nested_dict_returns_correctly(self):
        payload = '{"outer": {"inner": 1}, "list": [1, 2]}'
        result = _parse_candidate(payload)
        assert result == {"outer": {"inner": 1}, "list": [1, 2]}


# ---------------------------------------------------------------------------
# extract_json — integration tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_clean_json_string(self):
        raw = '{"priority": "high", "category": "network"}'
        result = extract_json(raw)
        assert result == {"priority": "high", "category": "network"}

    def test_fenced_json_block(self):
        raw = 'Sure, here is the result:\n```json\n{"label": "guidance"}\n```'
        result = extract_json(raw)
        assert result is not None
        assert result["label"] == "guidance"

    def test_embedded_in_prose(self):
        raw = 'The classification result is {"intent": "creation", "confidence": 0.9} based on the input.'
        result = extract_json(raw)
        assert result is not None
        assert result["intent"] == "creation"

    def test_python_expression_returns_none_and_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Python expressions in LLM output must return None and log a warning.

        This ensures that: (1) nothing is evaluated, and (2) the failure is
        visible in logs so operators know the LLM returned unparseable output.
        """
        with caplog.at_level(logging.WARNING, logger="app.services.ai.llm"):
            result = extract_json("__import__('os').system('id')")
        assert result is None
        # A warning must be logged so operators can see the parse failure.
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("extract_json" in msg or "parse" in msg.lower() for msg in warning_messages), (
            "No warning was logged for the parse failure.  "
            "Structured warnings are required so failures are visible in production logs."
        )

    def test_empty_string_returns_none(self):
        assert extract_json("") is None

    def test_think_block_stripped_before_parse(self):
        raw = "<think>Let me reason about this.</think>\n{\"result\": \"ok\"}"
        result = extract_json(raw)
        assert result is not None
        assert result["result"] == "ok"
