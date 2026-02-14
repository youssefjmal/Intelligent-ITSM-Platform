"""Input sanitization helpers for request payloads."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_WHITESPACE_RE = re.compile(r"\s+")


def _strip_control_chars(value: str, *, allow_newlines: bool) -> str:
    cleaned: list[str] = []
    for ch in value:
        if ch == "\n" and allow_newlines:
            cleaned.append(ch)
            continue
        if unicodedata.category(ch) == "Cc":
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def clean_text(value: str | None, *, allow_newlines: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _strip_control_chars(value, allow_newlines=allow_newlines)
    value = value.strip()
    if not allow_newlines:
        value = _WHITESPACE_RE.sub(" ", value)
    else:
        value = "\n".join(line.strip() for line in value.split("\n"))
        value = re.sub(r"\n{3,}", "\n\n", value)
    return value


def clean_single_line(value: str | None) -> str:
    return clean_text(value, allow_newlines=False)


def clean_multiline(value: str | None) -> str:
    return clean_text(value, allow_newlines=True)


def clean_email(value: str | None) -> str:
    return clean_single_line(value).lower()


def clean_list(
    values: Iterable[str] | str | None,
    *,
    max_items: int | None = None,
    item_max_length: int | None = None,
    allow_newlines: bool = False,
) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item is None:
            continue
        item_clean = clean_text(str(item), allow_newlines=allow_newlines)
        if not item_clean:
            continue
        if item_max_length and len(item_clean) > item_max_length:
            raise ValueError("item_too_long")
        key = item_clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item_clean)
    if max_items is not None and len(cleaned) > max_items:
        raise ValueError("too_many_items")
    return cleaned
