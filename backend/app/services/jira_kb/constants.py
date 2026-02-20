"""Constants for Jira KB retrieval and formatting."""

from __future__ import annotations

import re

LOGGER_NAME = "app.services.jira_kb"

_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u00C0-\u024F]{3,}")
_SPACE_RE = re.compile(r"\s+")

MIN_SCORE = 0.15
MIN_SEMANTIC_SCORE = 0.35
INMEMORY_SEMANTIC_EMBEDDING_BUDGET = 6
ISSUE_CONTEXT_DESCRIPTION_EMBED_LIMIT = 3000
ISSUE_CONTEXT_EMBED_LIMIT = 4096
COMMENT_MIN_LENGTH = 20
LOW_SIGNAL_SHORT_COMMENT_MAX_LENGTH = 120
STATUS_COMPLETED_BONUS = 0.05
STATUS_NEW_PENALTY = 0.03
MAX_ISSUE_EMBEDDINGS_PER_REFRESH = 20
MAX_COMMENT_EMBEDDINGS_PER_REFRESH = 50
EMBEDDING_REFRESH_TIME_BUDGET_SECONDS = 5.0

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "your",
    "are",
    "but",
    "les",
    "des",
    "pour",
    "avec",
    "dans",
    "une",
    "sur",
    "est",
    "pas",
    "ticket",
    "incident",
    "comment",
}

_LOW_SIGNAL_SHORT_COMMENT_PHRASES = {
    "thank you",
    "thanks",
    "thx",
    "merci",
    "fixed",
    "same issue",
    "same problem",
    "following",
    "suivi",
}

_HIGH_SIGNAL_COMMENT_KEYWORDS = {
    "root cause",
    "rca",
    "resolution",
    "workaround",
    "steps",
    "reproduce",
    "command",
    "powershell",
    "bash",
    "sql",
    "error",
    "log",
}

_HEX_ERROR_RE = re.compile(r"\b0x[0-9a-f]{3,}\b", re.IGNORECASE)
_STACK_TRACE_RE = re.compile(
    r"(traceback|stack\s*trace|exception(?:\s+in\s+thread)?|\bat\s+[a-z0-9_.$]+\([^)]+\))",
    re.IGNORECASE,
)
