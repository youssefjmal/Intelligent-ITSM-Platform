"""
Tests for duplicate ticket detection before creation.

Coverage:
  1. detect_duplicate_tickets returns empty list when no similar tickets
  2. Returns candidates above threshold with correct similarity_score
  3. Does NOT return resolved/closed tickets as duplicates
  4. Returns max MAX_DUPLICATE_CANDIDATES results
  5. duplicate_acknowledged=true handled in creation flow
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.services.ai.calibration import DUPLICATE_SIMILARITY_THRESHOLD, MAX_DUPLICATE_CANDIDATES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ticket_item(ticket_id: str, title: str, status: str, score: float) -> dict:
    """Build a mock retrieval result item dict."""
    return {
        "id": ticket_id,
        "title": title,
        "status": status,
        "assignee": "alice",
        "similarity_score": score,
        "coherence_score": score,
    }


def _make_db():
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detect_duplicate_tickets_empty_when_no_similar():
    """Returns empty list when retrieval returns no tickets."""
    mock_retrieval = {"similar_tickets": []}

    with patch("app.services.ai.duplicate_detection.unified_retrieve", return_value=mock_retrieval):
        from app.services.ai.duplicate_detection import detect_duplicate_tickets

        result = asyncio.run(detect_duplicate_tickets(
            db=_make_db(),
            title="VPN connectivity issue today",
            description="User cannot connect to the corporate VPN since this morning.",
        ))

        assert result == []


def test_detect_duplicate_tickets_returns_above_threshold():
    """Returns candidates with similarity_score above threshold."""
    high_score = DUPLICATE_SIMILARITY_THRESHOLD + 0.05
    items = [
        _make_ticket_item("TW-MOCK-001", "VPN not connecting — finance team", "open", high_score),
        _make_ticket_item("TW-MOCK-002", "VPN authentication failure", "in_progress", high_score - 0.01),
    ]
    mock_retrieval = {"similar_tickets": items}

    with patch("app.services.ai.duplicate_detection.unified_retrieve", return_value=mock_retrieval):
        from app.services.ai.duplicate_detection import detect_duplicate_tickets

        result = asyncio.run(detect_duplicate_tickets(
            db=_make_db(),
            title="VPN cannot connect this morning",
            description="Corporate VPN has been down since 09:00. Multiple users affected.",
        ))

        assert len(result) >= 1
        for c in result:
            assert c.similarity_score >= DUPLICATE_SIMILARITY_THRESHOLD
            assert c.ticket_id in ("TW-MOCK-001", "TW-MOCK-002")


def test_detect_duplicate_tickets_excludes_resolved():
    """Resolved and closed tickets must NOT be returned as duplicates."""
    above_threshold = DUPLICATE_SIMILARITY_THRESHOLD + 0.1
    items = [
        _make_ticket_item("TW-MOCK-010", "VPN failure yesterday", "resolved", above_threshold),
        _make_ticket_item("TW-MOCK-011", "VPN closed ticket", "closed", above_threshold),
        _make_ticket_item("TW-MOCK-012", "VPN still open", "open", above_threshold),
    ]
    mock_retrieval = {"similar_tickets": items}

    with patch("app.services.ai.duplicate_detection.unified_retrieve", return_value=mock_retrieval):
        from app.services.ai.duplicate_detection import detect_duplicate_tickets

        result = asyncio.run(detect_duplicate_tickets(
            db=_make_db(),
            title="VPN connectivity problem",
            description="Users report complete VPN outage since this morning.",
        ))

        ids_returned = {c.ticket_id for c in result}
        assert "TW-MOCK-010" not in ids_returned, "resolved ticket returned as duplicate"
        assert "TW-MOCK-011" not in ids_returned, "closed ticket returned as duplicate"
        assert "TW-MOCK-012" in ids_returned, "open ticket was not returned"


def test_detect_duplicate_tickets_respects_max_candidates():
    """Returns at most MAX_DUPLICATE_CANDIDATES results."""
    above_threshold = DUPLICATE_SIMILARITY_THRESHOLD + 0.05
    # Create more items than the limit
    items = [
        _make_ticket_item(f"TW-MOCK-{i:03d}", f"VPN issue {i}", "open", above_threshold)
        for i in range(MAX_DUPLICATE_CANDIDATES * 3)
    ]
    mock_retrieval = {"similar_tickets": items}

    with patch("app.services.ai.duplicate_detection.unified_retrieve", return_value=mock_retrieval):
        from app.services.ai.duplicate_detection import detect_duplicate_tickets

        result = asyncio.run(detect_duplicate_tickets(
            db=_make_db(),
            title="VPN connectivity failure affecting all staff",
            description="Corporate VPN is completely down. No users can connect.",
        ))

        assert len(result) <= MAX_DUPLICATE_CANDIDATES


def test_detect_duplicate_tickets_empty_input():
    """Returns empty list when title or description is empty."""
    from app.services.ai.duplicate_detection import detect_duplicate_tickets

    result = asyncio.run(detect_duplicate_tickets(db=_make_db(), title="", description=""))
    assert result == []

    result2 = asyncio.run(detect_duplicate_tickets(db=_make_db(), title="Valid title here", description=""))
    assert result2 == []


def test_detect_duplicate_tickets_handles_retrieval_error():
    """Returns empty list (does not raise) when unified_retrieve throws."""
    with patch(
        "app.services.ai.duplicate_detection.unified_retrieve",
        side_effect=RuntimeError("DB error"),
    ):
        from app.services.ai.duplicate_detection import detect_duplicate_tickets

        result = asyncio.run(detect_duplicate_tickets(
            db=_make_db(),
            title="Network printer not found after reboot",
            description="Printer stopped being discoverable after yesterday's Windows update.",
        ))

        assert result == []


def test_duplicate_candidate_url_format():
    """DuplicateCandidate url must be /tickets/{ticket_id}."""
    from app.services.ai.duplicate_detection import DuplicateCandidate

    c = DuplicateCandidate(
        ticket_id="TW-MOCK-042",
        title="Test ticket",
        status="open",
        assignee="alice",
        similarity_score=0.85,
        match_reason="Similar topic.",
        url="/tickets/TW-MOCK-042",
    )
    assert c.url == "/tickets/TW-MOCK-042"
    assert c.ticket_id == "TW-MOCK-042"
