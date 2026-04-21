"""Tests for the intent routing improvements:

- detect_language(): heuristic FR/EN detection without external libs
- _is_knowledge_query(): ITSM definitional question detector
- _is_clearly_offtopic(): embedding-based off-topic guard (mocked)
- detect_intent_with_confidence(): new 3-tuple return + offtopic_guard flag
- detect_intent_hybrid_details(): new 5-tuple return
- parse_chat_intent_details(): offtopic_guard stored in filter_meta
"""

from __future__ import annotations

import pytest

from app.services.ai import orchestrator
from app.services.ai.intents import (
    ChatIntent,
    IntentConfidence,
    _is_clearly_offtopic,
    _is_knowledge_query,
    detect_intent_hybrid_details,
    detect_intent_with_confidence,
    detect_language,
    parse_chat_intent_details,
)


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_french_with_accent_detected(self):
        assert detect_language("qu'est-ce que le SLA ?") == "fr"

    def test_french_with_cedilla(self):
        assert detect_language("création d'un ticket réseau") == "fr"

    def test_french_stopwords_no_accent(self):
        # "les" + "de" = 2 FR stopwords, no EN-only articles → fr
        assert detect_language("montre les tickets de la semaine") == "fr"

    def test_french_single_stopword_no_en_articles(self):
        # Only 1 FR stopword ("les") but zero EN-only articles → still "fr"
        assert detect_language("montre les tickets critiques") == "fr"

    def test_english_clear(self):
        assert detect_language("show me the latest critical tickets") == "en"

    def test_english_with_the(self):
        # "the" is EN-only article; no FR stopwords → en
        assert detect_language("what is the status of my ticket") == "en"

    def test_empty_string_returns_en(self):
        assert detect_language("") == "en"

    def test_none_like_empty(self):
        # Should not raise
        result = detect_language("   ")
        assert result in {"fr", "en"}

    def test_mixed_tech_english(self):
        # No accent, no FR stopwords → en
        assert detect_language("VPN connection issue on user laptop") == "en"

    def test_french_greeting(self):
        assert detect_language("bonjour") == "fr"

    def test_english_greeting(self):
        assert detect_language("hello") == "en"

    def test_french_explicit_stopword_merci(self):
        assert detect_language("merci pour votre aide") == "fr"


# ---------------------------------------------------------------------------
# _is_knowledge_query
# ---------------------------------------------------------------------------


class TestIsKnowledgeQuery:
    def test_what_is_mfa_en(self):
        assert _is_knowledge_query("what is mfa") is True

    def test_what_is_crm_en(self):
        assert _is_knowledge_query("what is crm") is True

    def test_what_is_vpn_en(self):
        assert _is_knowledge_query("what is vpn") is True

    def test_what_is_sla_en(self):
        assert _is_knowledge_query("what is sla") is True

    def test_explain_itil(self):
        assert _is_knowledge_query("explain itil") is True

    def test_how_does_dns_work(self):
        assert _is_knowledge_query("how does dns work") is True

    def test_tell_me_about_incident_management(self):
        assert _is_knowledge_query("tell me about incident management") is True

    def test_french_qu_est_ce_que_sla(self):
        # Note: _normalize_intent_text strips accents, so test normalized form
        assert _is_knowledge_query("qu'est-ce que le sla") is True

    def test_french_comment_fonctionne_vpn(self):
        assert _is_knowledge_query("comment fonctionne le vpn") is True

    def test_non_itsm_what_is_football(self):
        # Prefix present but no ITSM term → False
        assert _is_knowledge_query("what is football") is False

    def test_non_itsm_explain_cooking(self):
        assert _is_knowledge_query("explain cooking techniques") is False

    def test_no_prefix_ticket_query(self):
        # No knowledge prefix → False even if ITSM term present
        assert _is_knowledge_query("show me my tickets") is False

    def test_empty_returns_false(self):
        assert _is_knowledge_query("") is False

    def test_what_is_ai(self):
        assert _is_knowledge_query("what is ai") is True

    def test_define_sso(self):
        assert _is_knowledge_query("define sso") is True


# ---------------------------------------------------------------------------
# _is_clearly_offtopic (with mocked embeddings)
# ---------------------------------------------------------------------------


def _patch_embeddings(monkeypatch, fake_embed_fn):
    """Patch compute_embedding at its source module so the lazy import inside
    _is_clearly_offtopic picks up the mock."""
    import importlib
    emb = importlib.import_module("app.services.embeddings")
    monkeypatch.setattr(emb, "compute_embedding", fake_embed_fn)


class TestIsOfftopic:
    def test_returns_false_when_embeddings_unavailable(self, monkeypatch):
        """Guard degrades gracefully if embedding service is down."""
        def broken_embed(text):
            raise RuntimeError("ollama unavailable")

        _patch_embeddings(monkeypatch, broken_embed)
        # Should not raise, should return False (pass-through)
        try:
            result = _is_clearly_offtopic("who won the champions league")
        except Exception:
            pytest.fail("_is_clearly_offtopic raised when embeddings unavailable")
        assert result is False

    def test_itsm_message_not_offtopic(self, monkeypatch):
        """A message with high cosine similarity to anchors → False."""
        anchor_vec = [1.0, 0.0, 0.0]
        query_vec = [0.99, 0.0, 0.0]  # cosine ≈ 1.0 → not off-topic
        call_count = [0]

        def fake_embed(text):
            call_count[0] += 1
            return query_vec if call_count[0] == 1 else anchor_vec

        _patch_embeddings(monkeypatch, fake_embed)
        from app.core.config import settings
        monkeypatch.setattr(settings, "OFFTOPIC_SIMILARITY_THRESHOLD", 0.28)

        result = _is_clearly_offtopic("how do I create an incident ticket")
        assert result is False

    def test_sports_message_is_offtopic(self, monkeypatch):
        """A message with low cosine similarity to all anchors → True."""
        query_vec = [0.0, 0.0, 1.0]
        anchor_vec = [1.0, 0.0, 0.0]  # cosine = 0.0 → off-topic
        call_count = [0]

        def fake_embed(text):
            call_count[0] += 1
            return query_vec if call_count[0] == 1 else anchor_vec

        _patch_embeddings(monkeypatch, fake_embed)
        from app.core.config import settings
        monkeypatch.setattr(settings, "OFFTOPIC_SIMILARITY_THRESHOLD", 0.28)

        result = _is_clearly_offtopic("who won the champions league this season")
        assert result is True


# ---------------------------------------------------------------------------
# detect_intent_with_confidence — 3-tuple contract
# ---------------------------------------------------------------------------


class TestDetectIntentWithConfidenceContract:
    def test_returns_3_tuple(self):
        result = detect_intent_with_confidence("show me my tickets")
        assert len(result) == 3, "Must return a 3-tuple (intent, confidence, offtopic_guard)"

    def test_third_element_is_bool(self):
        _, _, offtopic = detect_intent_with_confidence("show me my tickets")
        assert isinstance(offtopic, bool)

    def test_offtopic_false_for_itsm_message(self):
        _, _, offtopic = detect_intent_with_confidence("show me my recent tickets")
        assert offtopic is False

    def test_knowledge_query_routes_to_chitchat(self):
        intent, confidence, offtopic = detect_intent_with_confidence("what is mfa")
        assert intent == ChatIntent.chitchat
        assert confidence == IntentConfidence.high
        assert offtopic is False  # knowledge query path, not off-topic guard

    def test_knowledge_query_fr_routes_to_chitchat(self):
        # Normalized text (accent-stripped by _normalize_intent_text): "qu'est-ce que le sla"
        intent, confidence, offtopic = detect_intent_with_confidence("qu'est-ce que le sla")
        assert intent == ChatIntent.chitchat
        assert confidence == IntentConfidence.high

    def test_problem_listing_not_affected(self):
        intent, confidence, offtopic = detect_intent_with_confidence("show me problems")
        assert intent == ChatIntent.problem_listing
        assert offtopic is False

    def test_create_ticket_not_affected(self):
        intent, confidence, offtopic = detect_intent_with_confidence("create a new ticket for VPN issue")
        assert intent == ChatIntent.create_ticket
        assert offtopic is False

    def test_offtopic_guard_fires_for_sports_with_mocked_embeddings(self, monkeypatch):
        """Long sports message triggers the embedding guard when embeddings return low similarity."""
        query_vec = [0.0, 0.0, 1.0]
        anchor_vec = [1.0, 0.0, 0.0]
        call_count = [0]

        def fake_embed(text):
            call_count[0] += 1
            return query_vec if call_count[0] == 1 else anchor_vec

        _patch_embeddings(monkeypatch, fake_embed)
        from app.core.config import settings
        monkeypatch.setattr(settings, "OFFTOPIC_SIMILARITY_THRESHOLD", 0.28)

        # Message > 40 chars to bypass the length gate
        intent, confidence, offtopic = detect_intent_with_confidence(
            "what do you think about harry maguire and manchester united performance"
        )
        assert intent == ChatIntent.chitchat
        assert confidence == IntentConfidence.high
        assert offtopic is True

    def test_long_structured_ticket_query_skips_offtopic_guard(self, monkeypatch):
        def should_not_run(_text):
            raise AssertionError("Embedding off-topic guard should not run for explicit ticket queries")

        monkeypatch.setattr("app.services.ai.intents._is_clearly_offtopic", should_not_run)

        intent, confidence, offtopic = detect_intent_with_confidence(
            "please show me the full current status and latest updates for ticket SEED-DB-005"
        )
        assert intent != ChatIntent.chitchat
        assert confidence in {IntentConfidence.high, IntentConfidence.medium}
        assert offtopic is False


# ---------------------------------------------------------------------------
# detect_intent_hybrid_details — 5-tuple contract
# ---------------------------------------------------------------------------


class TestDetectIntentHybridDetailsContract:
    def test_returns_5_tuple(self):
        result = detect_intent_hybrid_details("show me my tickets")
        assert len(result) == 5

    def test_fifth_element_is_bool(self):
        *_, offtopic = detect_intent_hybrid_details("show me my tickets")
        assert isinstance(offtopic, bool)

    def test_offtopic_false_for_normal_message(self):
        *_, offtopic = detect_intent_hybrid_details("create a ticket for VPN issue")
        assert offtopic is False


# ---------------------------------------------------------------------------
# parse_chat_intent_details — offtopic_guard stored in filter_meta
# ---------------------------------------------------------------------------


class TestParseIntentDetailsOfftopicMeta:
    def test_normal_itsm_message_has_offtopic_false_in_meta(self):
        details = parse_chat_intent_details("show me recent tickets")
        assert details.filter_meta.get("offtopic_guard") is False

    def test_knowledge_query_has_offtopic_false(self):
        details = parse_chat_intent_details("what is mfa")
        assert details.filter_meta.get("offtopic_guard") is False
        assert details.intent == ChatIntent.chitchat

    def test_offtopic_guard_true_propagates_to_meta(self, monkeypatch):
        """When embedding guard fires, filter_meta['offtopic_guard'] must be True."""
        query_vec = [0.0, 0.0, 1.0]
        anchor_vec = [1.0, 0.0, 0.0]
        call_count = [0]

        def fake_embed(text):
            call_count[0] += 1
            return query_vec if call_count[0] == 1 else anchor_vec

        _patch_embeddings(monkeypatch, fake_embed)
        from app.core.config import settings
        monkeypatch.setattr(settings, "OFFTOPIC_SIMILARITY_THRESHOLD", 0.28)

        details = parse_chat_intent_details(
            "what do you think about harry maguire and manchester united performance"
        )
        assert details.filter_meta.get("offtopic_guard") is True
        assert details.intent == ChatIntent.chitchat


class TestBuildChatReplyLanguagePropagation:
    def test_lang_override_wins_when_locale_missing(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "build_jira_knowledge_block", lambda *_args, **_kwargs: "")

        captured: dict[str, str] = {}

        def fake_build_chat_prompt(*, lang, greeting, **_kwargs):
            captured["lang"] = lang
            captured["greeting"] = greeting
            return "prompt"

        monkeypatch.setattr(orchestrator, "build_chat_prompt", fake_build_chat_prompt)
        monkeypatch.setattr(orchestrator, "ollama_generate", lambda *_args, **_kwargs: '{"reply":"hello"}')
        monkeypatch.setattr(orchestrator, "extract_json", lambda _reply: {"reply": "hello"})

        reply, action, payload = orchestrator.build_chat_reply(
            "show me the latest critical tickets",
            {},
            [],
            lang="en",
            locale=None,
        )

        assert reply == "hello"
        assert action is None
        assert payload is None
        assert captured["lang"] == "en"
