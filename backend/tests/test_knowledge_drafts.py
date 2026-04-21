from __future__ import annotations

import datetime as dt
import asyncio

from app.services.ai.knowledge_drafts import generate_ticket_knowledge_draft


def test_generate_ticket_knowledge_draft_falls_back_without_llm(monkeypatch) -> None:
    monkeypatch.setattr("app.services.ai.knowledge_drafts.ollama_generate", lambda *args, **kwargs: "")

    draft = asyncio.run(
        generate_ticket_knowledge_draft(
            ticket={
                "id": "TKT-42",
                "title": "VPN login fails after MFA reset",
                "description": "Users cannot connect after an MFA reset and see a certificate mismatch.",
                "category": "network",
                "priority": "high",
                "status": "resolved",
                "resolution": "Reissued the VPN certificate, refreshed the MFA binding, and confirmed connectivity.",
                "tags": ["vpn", "mfa"],
            },
            comments=[
                {
                    "body": "Temporary workaround was to use a backup access profile while waiting for the certificate refresh.",
                    "created_at": str(dt.datetime.now(dt.timezone.utc)),
                    "author": "Agent One",
                }
            ],
            lang="en",
        )
    )

    assert draft.ticket_id == "TKT-42"
    assert draft.title
    assert draft.summary
    assert draft.source == "fallback"
    assert draft.review_note
    assert draft.resolution_steps
    assert "vpn" in [tag.lower() for tag in draft.tags]
