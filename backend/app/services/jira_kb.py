"""Compatibility wrapper for Jira KB package API."""

from __future__ import annotations

from app.services.jira_kb import build_jira_knowledge_block, kb_has_data, refresh_jira_kb_index

__all__ = ["build_jira_knowledge_block", "refresh_jira_kb_index", "kb_has_data"]
