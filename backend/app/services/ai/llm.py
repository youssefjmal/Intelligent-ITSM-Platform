"""LLM adapter helpers (Ollama)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


def ollama_generate(prompt: str, *, json_mode: bool = False) -> str:
    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload: dict[str, Any] = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if json_mode:
        payload["format"] = "json"
    with httpx.Client(timeout=60) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", "")).strip()


def extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None
