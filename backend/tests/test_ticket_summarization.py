"""
Tests for the AI ticket summarization service.

Coverage:
  1. Summary generated on first load (no cache)
  2. Summary returned from cache (within TTL)
  3. Summary regenerated when stale (outside TTL)
  4. Summary invalidated on comment — summary_generated_at cleared
  5. Summary fallback on LLM failure — deterministic non-empty summary, no exception
  6. Similar tickets used in context — similar_ticket_count populated
  7. Summary max length enforced — truncated to SUMMARY_MAX_LENGTH_CHARS
  8. force_regenerate bypasses cache
"""
from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import MagicMock, patch

from app.services.ai.calibration import SUMMARY_CACHE_TTL_MINUTES, SUMMARY_MAX_LENGTH_CHARS
from app.services.ai.summarization import SummaryResult, generate_ticket_summary, invalidate_ticket_summary


_TICKET = {
    "id": "TW-TEST-001",
    "title": "VPN not connecting",
    "description": "User cannot connect to the corporate VPN since this morning.",
    "category": "network",
    "priority": "high",
    "status": "open",
    "assignee": "alice",
    "reporter": "bob",
    "ai_summary": None,
    "summary_generated_at": None,
}

_LLM_SUMMARY = "VPN connectivity issue reported by bob. Assigned to alice for investigation. Similar past incidents were resolved by restarting the VPN client."


# ---------------------------------------------------------------------------
# 1. Summary generated on first load
# ---------------------------------------------------------------------------


def test_summary_generated_on_first_load():
    """With ai_summary=None, the LLM is called and summary is non-empty."""
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value=_LLM_SUMMARY),
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert result.summary != ""
    assert result.is_cached is False


def test_summary_retrieval_excludes_current_ticket():
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True) as mock_retrieve,
        patch("app.services.ai.llm.ollama_generate", return_value=_LLM_SUMMARY),
    ):
        asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert mock_retrieve.call_args.kwargs["exclude_ids"] == [_TICKET["id"]]


# ---------------------------------------------------------------------------
# 2. Summary returned from cache
# ---------------------------------------------------------------------------


def test_summary_returned_from_cache():
    """When summary_generated_at is fresh, cached summary is returned without LLM."""
    fresh_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = "Cached summary text."
    mock_db_ticket.summary_generated_at = fresh_time
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with patch("app.services.ai.llm.ollama_generate") as mock_llm:
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))
        mock_llm.assert_not_called()

    assert result.is_cached is True
    assert result.summary == "Cached summary text."


# ---------------------------------------------------------------------------
# 3. Summary regenerated when stale
# ---------------------------------------------------------------------------


def test_summary_regenerated_when_stale():
    """When summary_generated_at is outside TTL, LLM is called."""
    stale_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=SUMMARY_CACHE_TTL_MINUTES + 10)
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = "Old summary."
    mock_db_ticket.summary_generated_at = stale_time
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value=_LLM_SUMMARY) as mock_llm,
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))
        mock_llm.assert_called_once()

    assert result.is_cached is False


# ---------------------------------------------------------------------------
# 4. Summary invalidated — summary_generated_at cleared
# ---------------------------------------------------------------------------


def test_summary_invalidated_on_comment():
    """invalidate_ticket_summary clears summary_generated_at, keeps ai_summary."""
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = "Existing summary."
    mock_db_ticket.summary_generated_at = dt.datetime.now(dt.timezone.utc)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    invalidate_ticket_summary("TW-TEST-001", db=mock_db)

    assert mock_db_ticket.summary_generated_at is None
    # ai_summary not cleared
    assert mock_db_ticket.ai_summary == "Existing summary."
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Summary fallback on LLM failure
# ---------------------------------------------------------------------------


def test_summary_fallback_on_llm_failure():
    """When LLM raises, a deterministic summary is returned, no exception."""
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", side_effect=RuntimeError("LLM offline")),
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert result.summary != ""
    assert "vpn" in result.summary.lower()
    assert result.is_cached is False


def test_summary_fallback_on_blank_llm_response():
    """Blank LLM output falls back to a deterministic summary."""
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value="   "),
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert result.summary != ""
    assert "statut" in result.summary.lower() or "status" in result.summary.lower()


# ---------------------------------------------------------------------------
# 6. Similar tickets used in context
# ---------------------------------------------------------------------------


def test_summary_similar_tickets_used():
    """When retrieval returns resolved tickets, they appear in used_ticket_ids."""
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    fake_candidates = [
        {"id": "TW-RESOLVED-001", "title": "VPN issue", "status": "resolved", "description": "Fixed by restarting."},
        {"id": "TW-RESOLVED-002", "title": "Another VPN issue", "status": "closed", "description": "Cleared DNS cache."},
    ]
    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": fake_candidates}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value=_LLM_SUMMARY),
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert result.similar_ticket_count == 2
    assert "TW-RESOLVED-001" in result.used_ticket_ids
    assert "TW-RESOLVED-002" in result.used_ticket_ids


# ---------------------------------------------------------------------------
# 7. Summary max length enforced
# ---------------------------------------------------------------------------


def test_summary_max_length_enforced():
    """LLM response over SUMMARY_MAX_LENGTH_CHARS is truncated."""
    long_summary = "x" * 600
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = None
    mock_db_ticket.summary_generated_at = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value=long_summary),
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db))

    assert len(result.summary) <= SUMMARY_MAX_LENGTH_CHARS


# ---------------------------------------------------------------------------
# 8. force_regenerate bypasses cache
# ---------------------------------------------------------------------------


def test_force_regenerate_bypasses_cache():
    """Even with fresh cache, force_regenerate=True calls LLM."""
    fresh_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)
    mock_db_ticket = MagicMock()
    mock_db_ticket.ai_summary = "Fresh cached summary."
    mock_db_ticket.summary_generated_at = fresh_time
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_db_ticket

    with (
        patch("app.services.ai.summarization.unified_retrieve", return_value={"similar_tickets": []}, create=True),
        patch("app.services.ai.llm.ollama_generate", return_value=_LLM_SUMMARY) as mock_llm,
    ):
        result = asyncio.run(generate_ticket_summary(_TICKET, db=mock_db, force_regenerate=True))
        mock_llm.assert_called_once()

    assert result.is_cached is False
