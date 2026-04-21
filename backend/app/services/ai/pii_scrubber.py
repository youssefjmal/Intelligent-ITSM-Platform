"""PII scrubber for AI prompt content.

Replaces recognisable PII patterns with neutral placeholders before
ticket content is sent to an external LLM (Groq).  The scrubber is
regex-only — no external NLP model required — so it adds no latency
and no extra dependency.

Patterns covered
----------------
- Email addresses                    → [EMAIL]
- IPv4 addresses                     → [IP_ADDRESS]
- International phone (E.164)        → [PHONE]
- French 10-digit phone numbers      → [PHONE]

Patterns deliberately NOT covered
----------------------------------
- Personal names: indistinguishable from hostnames, product names, or
  team names without a NER model — regex would produce too many false
  positives and break technical signals the LLM needs.
- Passwords / API keys: should never appear in ticket content; if they
  do that is a user-training / intake-form problem, not a scrubber problem.

ISO 27001 / ISO 42001 note
--------------------------
Applying this scrubber before every LLM call implements the data
minimisation principle: only the information necessary for classification
and resolution assistance reaches the external inference provider.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Strict IPv4 — avoids matching version numbers like "1.0.0.1"
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# E.164 international:  +33 6 12 34 56 78  /  +1-800-555-0199
_PHONE_INTL_RE = re.compile(
    r"\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{1,4}[\s.\-]?\d{1,4}[\s.\-]?\d{1,9}\b"
)

# French 10-digit:  0612345678  /  06 12 34 56 78  /  06.12.34.56.78
_PHONE_FR_RE = re.compile(
    r"\b0[1-9](?:[\s.\-]?\d{2}){4}\b"
)

_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (_EMAIL_RE, "[EMAIL]"),
    (_PHONE_INTL_RE, "[PHONE]"),   # run before IPv4 — French dot-format phones
    (_PHONE_FR_RE, "[PHONE]"),     # (e.g. 06.12.34.56.78) would otherwise be
    (_IPV4_RE, "[IP_ADDRESS]"),    # partially consumed by the IPv4 pattern first
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrub_pii(text: str) -> str:
    """Return *text* with recognised PII patterns replaced by placeholders.

    Safe to call on empty strings or None-equivalent input — returns the
    input unchanged in those cases.

    Example
    -------
    >>> scrub_pii("Contact john.doe@company.com or call +33 6 12 34 56 78")
    'Contact [EMAIL] or call [PHONE]'
    """
    if not text:
        return text
    for pattern, placeholder in _REPLACEMENTS:
        text = pattern.sub(placeholder, text)
    return text
