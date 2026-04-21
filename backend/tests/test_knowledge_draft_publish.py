"""
Tests for the knowledge draft persist + publish pipeline.

Coverage:
  1. POST generates draft and persists a new KnowledgeDraft row
  2. POST upserts (updates) on re-generate — no duplicate row
  3. GET returns the persisted draft
  4. GET returns 404 when no draft exists
  5. Publish creates a Jira KB article (when Jira is configured)
  6. Publish inserts a KBChunk with source_type="local_kb_draft"
  7. Publish is idempotent — second call returns same data without duplicating Jira call
  8. Publish sets published_at and jira_issue_key on the draft row
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_ticket(ticket_id: str = "TW-TEST-KB-001") -> SimpleNamespace:
    return SimpleNamespace(
        id=ticket_id,
        title="CRM sync fails after token rotation",
        description="The CRM sync job throws a 401 since last Thursday's token rotation.",
        status="resolved",
        priority="high",
        ticket_type="incident",
        category="application",
        assignee="alice",
        reporter="bob",
        resolution="Rotated OAuth token and restarted sync job.",
        tags=["crm", "oauth"],
    )


def _make_draft_row(ticket_id: str = "TW-TEST-KB-001") -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        title="CRM sync 401 after token rotation",
        summary="CRM sync job fails with 401 after OAuth token rotation. Resolved by re-issuing token.",
        symptoms=["401 on sync"],
        root_cause="OAuth token not refreshed after rotation",
        workaround="Manually restart sync",
        resolution_steps=["Rotate token", "Restart sync job"],
        tags=["crm", "oauth"],
        review_note="High confidence — exact root cause confirmed.",
        confidence=0.92,
        source="llm",
        generated_at=dt.datetime(2026, 4, 21, 10, 0, tzinfo=dt.timezone.utc),
        published_at=None,
        jira_issue_key=None,
        created_by_user_id="user-001",
        created_at=dt.datetime(2026, 4, 21, 10, 0, tzinfo=dt.timezone.utc),
    )


_MOCK_LLM_DRAFT = SimpleNamespace(
    title="CRM sync 401 after token rotation",
    summary="CRM sync job fails with 401 after OAuth token rotation.",
    symptoms=["401 on sync"],
    root_cause="OAuth token not refreshed",
    workaround="Restart sync",
    resolution_steps=["Rotate token", "Restart job"],
    tags=["crm"],
    review_note="Validated.",
    confidence=0.88,
    source="llm",
    generated_at=dt.datetime(2026, 4, 21, 10, 0, tzinfo=dt.timezone.utc),
)


# ---------------------------------------------------------------------------
# 1. POST generates draft and persists a new row
# ---------------------------------------------------------------------------


def test_generate_draft_persists_to_db(monkeypatch) -> None:
    """POST /knowledge-draft calls generate + inserts a KnowledgeDraft row."""
    from app.routers.tickets import generate_ticket_knowledge_draft_endpoint

    inserted: list[object] = []
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # no existing row

    def mock_add(obj):
        inserted.append(obj)
    mock_db.add = mock_add

    mock_ticket = _make_ticket()
    mock_user = SimpleNamespace(id="user-001", role="agent")

    monkeypatch.setattr(
        "app.routers.tickets.get_ticket_for_user",
        lambda db, tid, user: mock_ticket,
    )
    async def _mock_generate(**kwargs):
        return _MOCK_LLM_DRAFT

    monkeypatch.setattr(
        "app.services.ai.knowledge_drafts.generate_ticket_knowledge_draft",
        _mock_generate,
    )

    result = asyncio.run(
        generate_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            language="fr",
            db=mock_db,
            current_user=mock_user,
        )
    )

    assert result.ticket_id == "TW-TEST-KB-001"
    assert result.title == _MOCK_LLM_DRAFT.title
    assert result.confidence == _MOCK_LLM_DRAFT.confidence
    assert len(inserted) == 1, "Expected exactly one KnowledgeDraft row to be inserted"


# ---------------------------------------------------------------------------
# 2. POST upserts on re-generate — updates existing row, no duplicate
# ---------------------------------------------------------------------------


def test_generate_draft_upserts_on_regenerate(monkeypatch) -> None:
    """Second POST updates the existing draft row (no new insert)."""
    from app.routers.tickets import generate_ticket_knowledge_draft_endpoint

    existing_row = _make_draft_row()
    inserted: list[object] = []

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = existing_row
    mock_db.add = lambda obj: inserted.append(obj)

    async def _mock_generate(**kwargs):
        return _MOCK_LLM_DRAFT

    monkeypatch.setattr("app.routers.tickets.get_ticket_for_user", lambda db, tid, user: _make_ticket())
    monkeypatch.setattr(
        "app.services.ai.knowledge_drafts.generate_ticket_knowledge_draft",
        _mock_generate,
    )

    result = asyncio.run(
        generate_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            language="fr",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert len(inserted) == 0, "Should update the existing row, not insert a new one"
    assert result.title == _MOCK_LLM_DRAFT.title
    # The in-place update mutates existing_row
    assert existing_row.title == _MOCK_LLM_DRAFT.title


# ---------------------------------------------------------------------------
# 3. GET returns persisted draft
# ---------------------------------------------------------------------------


def test_get_draft_returns_persisted(monkeypatch) -> None:
    """GET /knowledge-draft returns the stored row."""
    from app.routers.tickets import get_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    monkeypatch.setattr("app.routers.tickets.get_ticket_for_user", lambda db, tid, user: _make_ticket())

    result = get_ticket_knowledge_draft_endpoint(
        ticket_id="TW-TEST-KB-001",
        db=mock_db,
        current_user=SimpleNamespace(id="user-001", role="agent"),
    )

    assert result.ticket_id == "TW-TEST-KB-001"
    assert result.title == row.title
    assert result.confidence == row.confidence
    assert result.status == "draft"


# ---------------------------------------------------------------------------
# 4. GET returns 404 when no draft exists
# ---------------------------------------------------------------------------


def test_get_draft_404_if_missing(monkeypatch) -> None:
    """GET /knowledge-draft raises NotFoundError when no row in DB."""
    from app.core.exceptions import NotFoundError
    from app.routers.tickets import get_ticket_knowledge_draft_endpoint

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    monkeypatch.setattr("app.routers.tickets.get_ticket_for_user", lambda db, tid, user: _make_ticket())

    try:
        get_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
        assert False, "Expected NotFoundError"
    except NotFoundError as exc:
        assert "no_knowledge_draft" in str(exc)


# ---------------------------------------------------------------------------
# 5. Publish creates a Jira KB article
# ---------------------------------------------------------------------------


def test_publish_creates_jira_article(monkeypatch) -> None:
    """Publish calls jira.create_kb_article with correct project key and title."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    jira_calls: list[dict] = []

    class MockJiraClient:
        def create_kb_article(self, project_key, title, body_text, source_ticket_id):
            jira_calls.append({"project_key": project_key, "title": title})
            return {"key": "KB-99"}

    monkeypatch.setattr("app.core.config.settings.JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_EMAIL", "test@example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_API_TOKEN", "token-abc")
    monkeypatch.setattr("app.core.config.settings.JIRA_PROJECT_KEY", "HP")
    monkeypatch.setattr("app.core.config.settings.JIRA_KB_ARTICLE_PROJECT_KEY", "KB")
    monkeypatch.setattr("app.integrations.jira.client.JiraClient", MockJiraClient)
    monkeypatch.setattr("app.routers.tickets._insert_kb_chunk_for_draft", lambda db, row, jira_key: 42)

    result = asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert len(jira_calls) == 1
    assert jira_calls[0]["project_key"] == "KB"
    assert jira_calls[0]["title"] == row.title
    assert result.jira_issue_key == "KB-99"


# ---------------------------------------------------------------------------
# 6. Publish inserts a KBChunk with source_type="local_kb_draft"
# ---------------------------------------------------------------------------


def test_publish_inserts_kb_chunk(monkeypatch) -> None:
    """Publish inserts a KBChunk row and returns its id."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    inserted_chunks: list[object] = []

    def fake_insert(db, draft_row, jira_key):
        inserted_chunks.append(draft_row)
        return 77

    monkeypatch.setattr("app.core.config.settings.JIRA_BASE_URL", "")
    monkeypatch.setattr("app.routers.tickets._insert_kb_chunk_for_draft", fake_insert)

    result = asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert len(inserted_chunks) == 1
    assert result.kb_chunk_id == 77


# ---------------------------------------------------------------------------
# 7. Publish is idempotent — second call returns same data, no duplicate Jira
# ---------------------------------------------------------------------------


def test_publish_idempotent(monkeypatch) -> None:
    """Second publish call returns the already-published state without calling Jira again."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    already_published = _make_draft_row()
    already_published.published_at = dt.datetime(2026, 4, 21, 12, 0, tzinfo=dt.timezone.utc)
    already_published.jira_issue_key = "KB-42"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = already_published

    jira_calls: list[str] = []
    monkeypatch.setattr(
        "app.integrations.jira.client.JiraClient.create_kb_article",
        lambda *args, **kwargs: jira_calls.append("called") or {"key": "KB-NEW"},
    )

    result = asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert len(jira_calls) == 0, "Should not call Jira for an already-published draft"
    assert result.jira_issue_key == "KB-42"
    assert result.published_at == already_published.published_at


# ---------------------------------------------------------------------------
# 8. Publish sets published_at and jira_issue_key on the draft row
# ---------------------------------------------------------------------------


def test_publish_sets_published_at_and_jira_key(monkeypatch) -> None:
    """After publish, the draft row has published_at and jira_issue_key populated."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    monkeypatch.setattr("app.core.config.settings.JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_EMAIL", "test@example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_API_TOKEN", "token-abc")
    monkeypatch.setattr("app.core.config.settings.JIRA_PROJECT_KEY", "HP")
    monkeypatch.setattr("app.core.config.settings.JIRA_KB_ARTICLE_PROJECT_KEY", "KB")

    class MockJira:
        def create_kb_article(self, project_key, title, body_text, source_ticket_id):
            return {"key": "KB-55"}

    monkeypatch.setattr("app.integrations.jira.client.JiraClient", MockJira)
    monkeypatch.setattr("app.routers.tickets._insert_kb_chunk_for_draft", lambda db, r, jk: 10)

    asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert row.published_at is not None, "published_at should be set"
    assert row.jira_issue_key == "KB-55"


# ---------------------------------------------------------------------------
# 9. Publish via Confluence — creates native page in JSM KB space
# ---------------------------------------------------------------------------


def test_publish_confluence_creates_page(monkeypatch) -> None:
    """When CONFLUENCE_SPACE_KEY is set, publish calls create_confluence_kb_article."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    confluence_calls: list[dict] = []

    class MockJira:
        def create_confluence_kb_article(self, space_key, title, body_html, source_ticket_id):
            confluence_calls.append({"space_key": space_key, "title": title})
            return {"id": "654321", "url": "https://example.atlassian.net/wiki/spaces/TWC/pages/654321"}

    monkeypatch.setattr("app.core.config.settings.JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr("app.core.config.settings.JIRA_EMAIL", "test@example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_API_TOKEN", "token-abc")
    monkeypatch.setattr("app.core.config.settings.JIRA_PROJECT_KEY", "TEAMWILL")
    monkeypatch.setattr("app.core.config.settings.CONFLUENCE_SPACE_KEY", "TWC")
    monkeypatch.setattr("app.integrations.jira.client.JiraClient", MockJira)
    monkeypatch.setattr("app.routers.tickets._insert_kb_chunk_for_draft", lambda db, r, jk: 5)

    result = asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert len(confluence_calls) == 1, "Should call create_confluence_kb_article exactly once"
    assert confluence_calls[0]["space_key"] == "TWC"
    assert confluence_calls[0]["title"] == row.title
    assert result.jira_issue_key == "654321"
    assert result.confluence_url == "https://example.atlassian.net/wiki/spaces/TWC/pages/654321"


# ---------------------------------------------------------------------------
# 10. Publish via Confluence — page ID stored, confluence_url returned
# ---------------------------------------------------------------------------


def test_publish_confluence_stores_url(monkeypatch) -> None:
    """After Confluence publish, jira_issue_key holds the page ID and confluence_url is set."""
    from app.routers.tickets import publish_ticket_knowledge_draft_endpoint

    row = _make_draft_row()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = row

    class MockJira:
        def create_confluence_kb_article(self, space_key, title, body_html, source_ticket_id):
            return {"id": "999888", "url": "https://example.atlassian.net/wiki/spaces/TWC/pages/999888"}

    monkeypatch.setattr("app.core.config.settings.JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr("app.core.config.settings.JIRA_EMAIL", "test@example.com")
    monkeypatch.setattr("app.core.config.settings.JIRA_API_TOKEN", "token-abc")
    monkeypatch.setattr("app.core.config.settings.JIRA_PROJECT_KEY", "TEAMWILL")
    monkeypatch.setattr("app.core.config.settings.CONFLUENCE_SPACE_KEY", "TWC")
    monkeypatch.setattr("app.integrations.jira.client.JiraClient", MockJira)
    monkeypatch.setattr("app.routers.tickets._insert_kb_chunk_for_draft", lambda db, r, jk: 7)

    asyncio.run(
        publish_ticket_knowledge_draft_endpoint(
            ticket_id="TW-TEST-KB-001",
            db=mock_db,
            current_user=SimpleNamespace(id="user-001", role="agent"),
        )
    )

    assert row.jira_issue_key == "999888"
    assert row.published_at is not None


# ---------------------------------------------------------------------------
# 11. Confluence HTML formatter produces required sections
# ---------------------------------------------------------------------------


def test_draft_to_confluence_html_structure() -> None:
    """_draft_to_confluence_html produces sections for all non-empty draft fields."""
    from app.routers.tickets import _draft_to_confluence_html

    row = _make_draft_row()
    html = _draft_to_confluence_html(row)

    assert "<h2>Summary</h2>" in html
    assert row.summary in html
    assert "<h2>Root Cause</h2>" in html
    assert "<h2>Resolution Steps</h2>" in html
    assert "<ol>" in html
    assert row.ticket_id in html
    # Confidence percentage should appear
    assert "92%" in html
