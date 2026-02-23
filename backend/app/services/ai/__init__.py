"""AI service public API."""

from __future__ import annotations

__all__ = ["classify_ticket", "score_recommendations", "build_chat_reply"]


def classify_ticket(*args, **kwargs):
    from app.services.ai.classifier import classify_ticket as _classify_ticket

    return _classify_ticket(*args, **kwargs)


def score_recommendations(*args, **kwargs):
    from app.services.ai.classifier import score_recommendations as _score_recommendations

    return _score_recommendations(*args, **kwargs)


def build_chat_reply(*args, **kwargs):
    from app.services.ai.orchestrator import build_chat_reply as _build_chat_reply

    return _build_chat_reply(*args, **kwargs)
