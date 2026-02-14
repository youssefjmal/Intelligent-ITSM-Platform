"""Chat orchestration for ITSM assistant."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_chat_prompt
from app.services.ai.quickfix import append_solution, explicit_ticket_request, suggest_quick_fix
from app.services.jira_kb import build_jira_knowledge_block

logger = logging.getLogger(__name__)


def _normalize_locale(locale: str | None) -> str:
    return "en" if (locale or "").lower().startswith("en") else "fr"


def _time_greeting(lang: str) -> str:
    hour = dt.datetime.now().hour
    is_evening = hour >= 18 or hour < 5
    if lang == "fr":
        return "Bonsoir" if is_evening else "Bonjour"
    return "Good evening" if is_evening else "Good morning"


def build_chat_reply(
    question: str,
    stats: dict,
    top_tickets: list[str],
    *,
    locale: str | None = None,
    assignees: list[str] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    lang = _normalize_locale(locale)
    greeting = _time_greeting(lang)
    assignee_list = assignees or []
    wants_ticket = explicit_ticket_request(question)
    knowledge_block = build_jira_knowledge_block(question, lang=lang)
    knowledge_section = f"{knowledge_block}\n\n" if knowledge_block else ""
    prompt = build_chat_prompt(
        question=question,
        knowledge_section=knowledge_section,
        lang=lang,
        greeting=greeting,
        assignee_list=assignee_list,
        stats=stats,
        top_tickets=top_tickets,
    )

    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if data and "reply" in data:
            reply_text = str(data.get("reply", ""))
            action = data.get("action")
            solution = data.get("solution")
            quick_fix = suggest_quick_fix(question, lang=lang)
            if quick_fix and action == "create_ticket" and not wants_ticket:
                action = "none"
                data["ticket"] = None
                reply_text = append_solution(reply_text, quick_fix, lang=lang)
            if isinstance(solution, list):
                solution = " ".join(str(item) for item in solution if item)
            if isinstance(solution, str) and solution.strip() and action in {None, "none"}:
                reply_text = append_solution(reply_text, solution.strip(), lang=lang)
            elif action in {None, "none"} and quick_fix:
                reply_text = append_solution(reply_text, quick_fix, lang=lang)
            return reply_text, action, data.get("ticket")

        quick_fix = suggest_quick_fix(question, lang=lang)
        if quick_fix:
            reply = append_solution(str(reply), quick_fix, lang=lang)
        return reply, None, None
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        error_reply = "LLM is unavailable. Please try again." if lang == "en" else "LLM indisponible. Reessayez."
        quick_fix = suggest_quick_fix(question, lang=lang)
        if quick_fix:
            error_reply = append_solution(error_reply, quick_fix, lang=lang)
        return error_reply, None, None
