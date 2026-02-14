"""Quick-fix heuristics used by AI chat orchestration."""

from __future__ import annotations

from app.services.ai.prompts import EASY_FIXES, HIGH_RISK_KEYWORDS, TICKET_REQUEST_KEYWORDS


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def is_high_risk(text: str) -> bool:
    return contains_any(text, HIGH_RISK_KEYWORDS)


def suggest_quick_fix(question: str, *, lang: str) -> str | None:
    text = question.lower()
    if is_high_risk(text):
        return None
    for fix in EASY_FIXES:
        if contains_any(text, fix["patterns"]):
            return str(fix[lang])
    return None


def explicit_ticket_request(question: str) -> bool:
    text = question.lower()
    return contains_any(text, TICKET_REQUEST_KEYWORDS)


def append_solution(reply: str, solution: str, *, lang: str) -> str:
    if not solution:
        return reply
    label = "Solution rapide" if lang == "fr" else "Quick fix"
    if reply:
        return f"{reply}\n\n{label}:\n- {solution}"
    return f"{label}:\n- {solution}"
