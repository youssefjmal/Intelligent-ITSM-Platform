from __future__ import annotations

import re

LOCAL_TICKET_PREFIX_RE = re.compile(r"^(?:\[(TW-\d+)\]\s*)+", re.IGNORECASE)
LEADING_BRACKET_PREFIX_RE = re.compile(r"^\[(?P<token>[A-Za-z0-9-]+)\]\s*")


def normalize_local_ticket_title(title: str | None) -> str:
    original = (title or "").strip()
    if not original:
        return ""

    raw = LOCAL_TICKET_PREFIX_RE.sub("", original).strip() or original
    prefixes: list[tuple[str, str]] = []
    remainder = raw
    while True:
        match = LEADING_BRACKET_PREFIX_RE.match(remainder)
        if match is None:
            break
        token = str(match.group("token") or "").strip()
        if not token:
            break
        prefixes.append((token.casefold(), f"[{token}]"))
        remainder = remainder[match.end() :].lstrip()

    if not prefixes:
        return raw

    deduped_prefixes: list[str] = []
    last_token = ""
    for token, prefix in prefixes:
        if token != last_token:
            deduped_prefixes.append(prefix)
        last_token = token

    if remainder:
        return " ".join([*deduped_prefixes, remainder]).strip()
    return " ".join(deduped_prefixes).strip() or raw
