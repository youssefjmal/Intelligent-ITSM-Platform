"""LLM adapter helpers (Ollama).

Role:
    This module provides low-level communication with the Ollama inference
    endpoint and JSON extraction utilities used throughout the AI service layer.

LLM target:
    Ollama-hosted models configured via ``settings.OLLAMA_MODEL``.
    The module tries the ``/api/generate`` endpoint first; if the model only
    supports the chat API it falls back automatically to ``/api/chat``.

Output contract:
    All callers expect structured JSON back from the model.
    ``extract_json`` is the single entry point for parsing raw model output
    into a Python dict.  It NEVER uses ``ast.literal_eval`` — only
    ``json.loads`` with strict exception handling so that malicious or
    malformed model output cannot execute code.

Security note:
    ``ast.literal_eval`` was previously used as a fallback parser for LLM
    output.  It has been removed because even "safe" Python literal syntax
    accepted by ``ast.literal_eval`` can be crafted to exploit edge cases in
    CPython or third-party patched interpreters.  ``json.loads`` is the only
    parser used here; all parse failures are logged as warnings.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def ollama_generate(prompt: str, *, json_mode: bool = False) -> str:
    model_name = str(settings.OLLAMA_MODEL or "").strip().lower()
    disable_thinking = json_mode and model_name.startswith("qwen3")
    with httpx.Client(timeout=60) as client:
        generate_url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        generate_payload: dict[str, Any] = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            generate_payload["format"] = "json"
        if disable_thinking:
            generate_payload["think"] = False
        response = client.post(generate_url, json=generate_payload)
        if response.status_code == 404:
            chat_url = f"{settings.OLLAMA_BASE_URL}/api/chat"
            chat_payload: dict[str, Any] = {
                "model": settings.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1},
            }
            if json_mode:
                chat_payload["format"] = "json"
            if disable_thinking:
                chat_payload["think"] = False
            chat_response = client.post(chat_url, json=chat_payload)
            chat_response.raise_for_status()
            data = chat_response.json()
            message = data.get("message") if isinstance(data, dict) else None
            if isinstance(message, dict):
                content = str(message.get("content", "")).strip()
                if content:
                    return content
            if isinstance(data, dict):
                thinking = str(data.get("thinking", "")).strip()
                if thinking:
                    return thinking
            return ""
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            response_text = str(data.get("response", "")).strip()
            if response_text:
                return response_text
            thinking = str(data.get("thinking", "")).strip()
            if thinking:
                return thinking
        return ""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_model_meta(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub(" ", str(text or ""))
    cleaned = cleaned.replace("<think>", " ").replace("</think>", " ")
    return cleaned.strip()


def _balanced_json_objects(text: str) -> list[str]:
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : idx + 1])
                start = -1
    return candidates


def _parse_candidate(candidate: str) -> dict[str, Any] | None:
    """Attempt to parse a single JSON candidate string into a dict.

    Tries two variants of the candidate: the original string and a
    trailing-comma-cleaned version.  Only ``json.loads`` is used; the
    former ``ast.literal_eval`` fallback has been removed because
    evaluating arbitrary LLM-generated Python-like expressions is a
    code-execution risk even when the input appears safe.

    Args:
        candidate: Raw string that may contain a JSON object.

    Returns:
        Parsed dict on success, or None if all attempts fail.
    """
    normalized = str(candidate or "").strip()
    if not normalized:
        return None

    attempts = [normalized, _TRAILING_COMMA_RE.sub(r"\1", normalized)]

    # Only json.loads is used here.
    # ast.literal_eval was removed: it can evaluate Python expressions
    # embedded in LLM output and is therefore a code-execution risk.
    # If json.loads fails, we log a warning at the call site in extract_json
    # and return None so the caller can try the next candidate.
    for raw in attempts:
        try:
            loaded = json.loads(raw)
        except (ValueError, TypeError):
            loaded = None
        if isinstance(loaded, dict):
            return loaded

    return None


def extract_json(text: str) -> dict[str, Any] | None:
    """Parse structured JSON from raw LLM output using a multi-strategy fallback chain.

    Strategies tried in order:
    1. Parse the cleaned full string directly via json.loads.
    2. Extract fenced code blocks (```json ... ```) and parse each one.
    3. Extract balanced ``{...}`` objects from the cleaned string.
    4. Slice between the first ``{`` and last ``}`` and parse.

    If every strategy fails, a structured WARNING is logged that includes the
    calling function name and the first 120 characters of the raw output so
    that parse failures are visible without logging full (potentially large)
    LLM responses.

    Security note:
        ``ast.literal_eval`` is NOT used anywhere in this function or its
        helpers.  Only ``json.loads`` is used to avoid code-execution risks
        from malformed or adversarial LLM output.

    Args:
        text: Raw string returned by the LLM, possibly with preamble,
              think-blocks, fenced code, or trailing text.

    Returns:
        Parsed dict on success, or None if all strategies fail.
    """
    cleaned = _strip_model_meta(text)
    if not cleaned:
        return None

    # Strategy 1: parse the cleaned full string directly.
    parsed = _parse_candidate(cleaned)
    if parsed is not None:
        return parsed

    # Strategy 2: extract fenced code blocks and try each (most-recent first).
    fenced = _JSON_FENCE_RE.findall(cleaned)
    for snippet in reversed(fenced):
        parsed = _parse_candidate(snippet)
        if parsed is not None:
            return parsed

    # Strategy 3: extract balanced {…} objects and try each (most-recent first).
    for snippet in reversed(_balanced_json_objects(cleaned)):
        parsed = _parse_candidate(snippet)
        if parsed is not None:
            return parsed

    # Strategy 4: slice between first { and last } as a last resort.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning(
            "extract_json: all parse strategies failed — no JSON object found. "
            "Raw output prefix (120 chars): %r",
            cleaned[:120],
        )
        return None

    result = _parse_candidate(cleaned[start : end + 1])
    if result is None:
        logger.warning(
            "extract_json: all parse strategies failed — last-resort slice also failed. "
            "Raw output prefix (120 chars): %r",
            cleaned[:120],
        )
    return result
