"""LLM adapter helpers (Ollama)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


def ollama_generate(prompt: str, *, json_mode: bool = False) -> str:
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
            chat_response = client.post(chat_url, json=chat_payload)
            chat_response.raise_for_status()
            data = chat_response.json()
            message = data.get("message") if isinstance(data, dict) else None
            if isinstance(message, dict):
                return str(message.get("content", "")).strip()
            return ""
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
