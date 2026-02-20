"""Formatting helpers for Jira KB prompt block output."""

from __future__ import annotations


def _truncate(text: str, *, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _truncate_head_tail(text: str, *, limit: int = 280, head_ratio: float = 0.65) -> str:
    if len(text) <= limit:
        return text
    if limit <= 16:
        return _truncate(text, limit=limit)

    separator = " ... "
    budget = max(1, limit - len(separator))
    ratio = max(0.5, min(0.8, float(head_ratio)))
    head_len = max(1, int(budget * ratio))
    tail_len = max(1, budget - head_len)
    head = text[:head_len].rstrip()
    tail = text[-tail_len:].lstrip()
    if not head or not tail:
        return _truncate(text, limit=limit)
    return f"{head}{separator}{tail}"


def _format_knowledge_block(*, lang: str, matches: list[dict[str, str]]) -> str:
    if not matches:
        return ""

    if lang == "fr":
        header = "Connaissance JSM (tickets similaires via contenu Jira):"
        lines = [
            (
                f"- [{row['issue_key']}] {row['summary']} "
                f"({row.get('priority') or '-'} | {row.get('status') or '-'} | "
                f"Composants: {row.get('components') or '-'}) | "
                f"Desc: {_truncate(row.get('description', ''), limit=180)} | "
                f"Commentaire: {_truncate_head_tail(row.get('comment', ''), limit=220)} "
                f"(auteur: {row.get('author') or 'Unknown'})"
            )
            for row in matches
        ]
    else:
        header = "JSM knowledge (similar tickets from Jira content):"
        lines = [
            (
                f"- [{row['issue_key']}] {row['summary']} "
                f"({row.get('priority') or '-'} | {row.get('status') or '-'} | "
                f"Components: {row.get('components') or '-'}) | "
                f"Desc: {_truncate(row.get('description', ''), limit=180)} | "
                f"Comment: {_truncate_head_tail(row.get('comment', ''), limit=220)} "
                f"(author: {row.get('author') or 'Unknown'})"
            )
            for row in matches
        ]
    return "\n".join([header, *lines])
