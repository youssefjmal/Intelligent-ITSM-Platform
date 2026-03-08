from __future__ import annotations

from app.schemas.translation import TranslationSuggestionRequest
from app.services import translations


def test_translate_bilingual_text_uses_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_ollama_generate(_prompt: str, *, json_mode: bool = False) -> str:
        calls["count"] += 1
        assert json_mode is True
        return '{"en":"Server outage in Tunis","fr":"Panne serveur a Tunis"}'

    monkeypatch.setattr(translations, "ollama_generate", fake_ollama_generate)
    cache = {}

    first = translations.translate_bilingual_text("Panne serveur a Tunis", cache=cache)
    second = translations.translate_bilingual_text("Panne serveur a Tunis", cache=cache)

    assert first.en == "Server outage in Tunis"
    assert first.fr == "Panne serveur a Tunis"
    assert second.en == first.en
    assert second.fr == first.fr
    assert calls["count"] == 1


def test_translate_bilingual_text_falls_back_to_source_text(monkeypatch) -> None:
    def fake_ollama_generate(_prompt: str, *, json_mode: bool = False) -> str:
        raise RuntimeError("ollama_unavailable")

    monkeypatch.setattr(translations, "ollama_generate", fake_ollama_generate)

    text = "Incident VPN timeout agence Tunis"
    translated = translations.translate_bilingual_text(text, cache={})

    assert translated.en == text
    assert translated.fr == text


def test_build_translated_suggestions_dedupes_and_translates(monkeypatch) -> None:
    def fake_translate_bilingual_text(text: str | None, *, cache):  # noqa: ANN001
        value = str(text or "").strip()
        return translations.BilingualTextOut(
            en=f"EN::{value}",
            fr=f"FR::{value}",
        )

    monkeypatch.setattr(translations, "translate_bilingual_text", fake_translate_bilingual_text)

    payload = TranslationSuggestionRequest(
        suggestions=[
            "Restart postfix service",
            "Restart postfix service",
            "Rotate SMTP cert chain",
        ],
        dedupe=True,
    )
    response = translations.build_translated_suggestions(payload)

    assert response.count == 2
    assert response.suggestions[0].source_text == "Restart postfix service"
    assert response.suggestions[0].translations.en == "EN::Restart postfix service"
    assert response.suggestions[1].translations.fr == "FR::Rotate SMTP cert chain"

