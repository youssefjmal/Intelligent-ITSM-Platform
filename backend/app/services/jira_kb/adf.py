"""ADF parsing helpers for Jira comment/description normalization."""

from __future__ import annotations

from typing import Any

from app.services.jira_kb.constants import _SPACE_RE


def _text_from_adf(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(part for part in (_text_from_adf(child) for child in node) if part)
    if not isinstance(node, dict):
        return str(node)

    parts: list[str] = []
    text = node.get("text")
    if isinstance(text, str):
        parts.append(text)
    content = node.get("content")
    if isinstance(content, list):
        for child in content:
            child_text = _text_from_adf(child)
            if child_text:
                parts.append(child_text)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _normalize_comment_text(raw_body: Any) -> str:
    if isinstance(raw_body, str):
        text = raw_body
    else:
        text = _text_from_adf(raw_body)
    return _SPACE_RE.sub(" ", text).strip()


def _adf_contains_type(node: Any, expected_type: str) -> bool:
    if node is None:
        return False
    if isinstance(node, list):
        return any(_adf_contains_type(child, expected_type) for child in node)
    if not isinstance(node, dict):
        return False
    if str(node.get("type") or "").strip() == expected_type:
        return True
    content = node.get("content")
    if isinstance(content, list):
        return any(_adf_contains_type(child, expected_type) for child in content)
    return False
