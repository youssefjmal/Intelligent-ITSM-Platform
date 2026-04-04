"""Prompt builders and constants for AI workflows."""

from __future__ import annotations

import json

from app.services.ai.prompt_policy import (
    CHAT_KNOWLEDGE_FIRST_POLICY,
    CHAT_SIGNAL_POLICY,
    CLASSIFICATION_SIGNAL_POLICY,
    EASY_FIXES,
    GROUNDED_FORMATTER_POLICY,
    HIGH_RISK_KEYWORDS,
    KNOWLEDGE_FIRST_CLASSIFICATION_POLICY,
    TICKET_REQUEST_KEYWORDS,
)


def build_classification_prompt(
    *,
    title: str,
    description: str,
    knowledge_section: str,
    recommendations_mode: str = "llm_general",
) -> str:
    if recommendations_mode == "comments_strong":
        mode_hint = "Knowledge Section contient des correspondances Jira fortes."
    else:
        mode_hint = "Knowledge Section peut etre partielle; reste strict sur le grounding."

    return (
        "Tu es un assistant ITSM. Reponds avec JSON valide uniquement, sans texte hors JSON.\n"
        f"{CLASSIFICATION_SIGNAL_POLICY}"
        f"{KNOWLEDGE_FIRST_CLASSIFICATION_POLICY}"
        f"- Contexte: {mode_hint}\n"
        "Schema JSON strict:\n"
        "{\n"
        '  "priority": "critical|high|medium|low",\n'
        '  "ticket_type": "incident|service_request",\n'
        '  "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '  "technical_signals": ["3-8 signaux techniques issus du ticket et/ou Jira"],\n'
        '  "recommendations": ["2-4 actions courtes"] | [],\n'
        '  "notes": "explication courte du grounding Jira ou insuffisance",\n'
        '  "sources": ["Jira keys presentes dans Knowledge Section"]\n'
        "}\n"
        "Regles sources:\n"
        "- Si Knowledge Section utilisee, remplir sources avec les Jira keys utilisees (depuis [KEY]).\n"
        "- Si Knowledge Section vide/insuffisante, sources=[].\n\n"
        f"{knowledge_section}"
        f"Titre: {title}\n"
        f"Description: {description}\n"
    )


def build_chat_prompt(
    *,
    question: str,
    knowledge_section: str,
    lang: str,
    greeting: str,
    assignee_list: list[str],
    stats: dict,
    top_tickets: list[str],
) -> str:
    return (
        "You are an ITSM assistant. Return ONLY valid JSON.\n"
        f"{CHAT_SIGNAL_POLICY}"
        f"{CHAT_KNOWLEDGE_FIRST_POLICY}"
        "JSON schema:\n"
        "{\n"
        '  "reply": "string",\n'
        '  "confidence": "low" | "medium" | "high",\n'
        '  "sources": ["Jira keys like ABC-123"],\n'
        '  "classification": {\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "ticket_type": "incident|service_request",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email"\n'
        "  },\n"
        '  "technical_signals": ["3-8 short technical signals"],\n'
        '  "recommendations": ["2-4 short concrete actions"] | [],\n'
        '  "notes": "short grounding explanation (Jira used or insufficient)",\n'
        '  "action": "create_ticket" | "none",\n'
        '  "solution": "string | null",\n'
        '  "ticket": {\n'
        '    "title": "string",\n'
        '    "description": "string",\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "ticket_type": "incident|service_request",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '    "tags": ["string"],\n'
        '    "assignee": "one of available assignees or null"\n'
        "  } | null\n"
        "}\n\n"
        f"{knowledge_section}"
        "Rules:\n"
        "- If Jira matches are strong and consistent, confidence=high.\n"
        "- If Jira matches exist but are partial/unclear, confidence=medium.\n"
        "- If no Jira matches, confidence=low and sources=[].\n"
        "- solution must be one string or null. Do not merge recommendations into solution.\n"
        "- recommendations must be a JSON array of strings.\n"
        "- If the user asks to create/open a ticket, set action=create_ticket and fill ticket.\n"
        "- Otherwise action=none and ticket=null.\n"
        f"- Write reply, recommendations and notes in language: {lang}.\n"
        f"- Write ticket description in language: {lang}.\n"
        f"- Start the reply with this greeting: {greeting}.\n"
        f"- Available assignees: {assignee_list}.\n"
        f"- Stats: {stats}.\n"
        f"- Question: {question}\n"
    )


def build_chat_grounded_prompt(
    *,
    question: str,
    grounding: dict,
    lang: str,
    greeting: str,
) -> str:
    return (
        "You are an ITSM assistant formatting a resolver-approved answer.\n"
        "Return ONLY valid JSON.\n"
        f"{GROUNDED_FORMATTER_POLICY}"
        "JSON schema:\n"
        "{\n"
        '  "summary": ["short bullet", "short bullet"] | [],\n'
        '  "why_this_matches": ["short bullet", "short bullet"] | [],\n'
        '  "confidence_note": "short sentence or empty string"\n'
        "}\n"
        f"- Write all strings in language: {lang}.\n"
        f"- Greeting available if useful: {greeting}.\n"
        f"- User question: {question}\n"
        f"- Resolver grounding JSON:\n{json.dumps(grounding, ensure_ascii=True)}\n"
    )


def build_general_advisory_prompt(
    ticket_title: str,
    ticket_description: str,
    ticket_category: str,
    ticket_priority: str,
    attempted_steps: list[str],
    concurrent_families: list[str],
    language: str = "fr",
) -> tuple[str, str]:
    """Build a system + user prompt pair for general-knowledge IT advisory.

    Called only when local evidence retrieval returns no_strong_match.
    The LLM is instructed to reason from general IT knowledge about the
    ticket's category and symptoms — NOT from any local database.

    The prompt enforces:
    - Cautious language: "typically", "may indicate", "commonly" — never "is"
    - No fabricated ticket IDs, system names, user names, or tool names
    - No repeating steps already listed in attempted_steps
    - Structured JSON output matching LLMGeneralAdvisory field names
    - Explicit acknowledgment that no local data is available

    Args:
        ticket_title: Ticket title for symptom context.
        ticket_description: Full description for symptom extraction.
        ticket_category: IT category (network, email, application, etc.)
            Used to guide which domain knowledge the LLM applies.
        ticket_priority: Priority level.  If critical or high, the prompt
            requests an escalation_hint in the output.
        attempted_steps: Steps already tried.  LLM must not repeat these
            in suggested_checks.
        concurrent_families: Topic families detected by retrieval but with
            no dominant cluster (e.g. ["vpn", "login", "mfa"]).
            Included so the LLM can acknowledge the ambiguity.
        language: "fr" or "en".  Controls the language of the response.

    Returns:
        Tuple of (system_prompt, user_prompt) ready to be combined and
        passed to ollama_generate().
    """
    system_prompt = (
        "You are an experienced IT support engineer providing general "
        "diagnostic guidance. "
        "You do NOT have access to this organisation's ticket history, "
        "infrastructure, configuration, or user data. "
        "You are reasoning from general IT knowledge only. "
        "Frame every statement as a possibility, never as a confirmed fact. "
        "Use words like 'typically', 'commonly', 'may indicate', 'often caused by'. "
        "Never fabricate ticket IDs, system names, server names, or user names. "
        "If you are uncertain, say so explicitly rather than inventing "
        "a plausible-sounding answer. "
        "Return ONLY a valid JSON object. No prose before or after the JSON. "
        "No markdown code fences."
    )

    priority_instruction = ""
    if ticket_priority.lower() in ("critical", "high", "critique", "haute"):
        priority_instruction = (
            "Because this ticket is high priority, include an 'escalation_hint' "
            "field suggesting when the agent should escalate rather than "
            "continue diagnosing independently. "
        )

    attempted_instruction = ""
    if attempted_steps:
        attempted_instruction = (
            f"The following steps have already been attempted and must NOT "
            f"appear in suggested_checks: {', '.join(attempted_steps)}. "
        )

    families_instruction = ""
    if concurrent_families:
        families_instruction = (
            f"The system detected signals from multiple incident families "
            f"({', '.join(concurrent_families)}) with no dominant cluster. "
            f"Acknowledge this ambiguity in your probable_causes if relevant. "
        )

    lang_instruction = (
        "Respond in French." if language == "fr" else "Respond in English."
    )

    json_schema = (
        "Return a JSON object with exactly these fields:\n"
        "{\n"
        '  "probable_causes": ["string", "string"],\n'
        '  "suggested_checks": ["string", "string", "string"],\n'
        '  "escalation_hint": "string or null"\n'
        "}\n"
        "probable_causes: 2-3 items maximum.\n"
        "suggested_checks: 2-4 items maximum, ordered least invasive first.\n"
        "escalation_hint: include only if priority is critical or high, "
        "otherwise set to null.\n"
    )

    user_prompt = (
        f"Ticket title: {ticket_title}\n"
        f"Category: {ticket_category}\n"
        f"Priority: {ticket_priority}\n"
        f"Description: {ticket_description[:600]}\n\n"
        f"{families_instruction}"
        f"{attempted_instruction}"
        f"{priority_instruction}"
        f"{lang_instruction}\n\n"
        f"{json_schema}"
    )

    return system_prompt, user_prompt


def build_llm_fallback_action_prompt(
    *,
    ticket_title: str,
    ticket_description: str,
    ticket_category: str,
    ticket_priority: str,
    attempted_steps: list[str],
    concurrent_families: list[str],
    deterministic_fallback: str | None,
    language: str = "fr",
) -> tuple[str, str]:
    """Build a prompt for low-trust incident actions when no strong match exists."""

    system_prompt = (
        "You are an experienced IT support engineer giving cautious next-step guidance "
        "when no reliable historical ticket match is available. "
        "You do NOT have access to the organisation's private configuration or real ticket history. "
        "Reason only from general IT knowledge and the ticket text. "
        "Do not claim a confirmed fix. Do not invent ticket IDs, server names, user names, "
        "internal system names, or environment-specific facts. "
        "Keep recommendations practical, low-risk, and diagnostic-first. "
        "Return ONLY valid JSON with no markdown."
    )

    attempted_instruction = (
        f"The following steps were already attempted and must not be repeated unless you add new value: {', '.join(attempted_steps)}. "
        if attempted_steps
        else ""
    )
    families_instruction = (
        f"Retrieval detected weak signals from these families with no dominant evidence: {', '.join(concurrent_families)}. "
        if concurrent_families
        else ""
    )
    fallback_instruction = (
        f"The current deterministic fallback is: {deterministic_fallback}. Improve on it with more specific but still cautious guidance. "
        if deterministic_fallback
        else ""
    )
    lang_instruction = "Respond in French." if language == "fr" else "Respond in English."

    user_prompt = (
        f"Ticket title: {ticket_title}\n"
        f"Category: {ticket_category}\n"
        f"Priority: {ticket_priority}\n"
        f"Description: {ticket_description[:800]}\n\n"
        f"{families_instruction}"
        f"{attempted_instruction}"
        f"{fallback_instruction}"
        f"{lang_instruction}\n"
        "Return a JSON object with exactly these fields:\n"
        "{\n"
        '  "recommended_action": "string",\n'
        '  "next_best_actions": ["string", "string"],\n'
        '  "validation_steps": ["string", "string"],\n'
        '  "reasoning_note": "short cautious sentence"\n'
        "}\n"
        "Rules:\n"
        "- recommended_action must be a cautious next step, not a confirmed fix.\n"
        "- next_best_actions: 1-4 items, ordered least invasive first.\n"
        "- validation_steps: 1-3 items.\n"
        "- reasoning_note must explain why the advice is low-trust and general.\n"
    )
    return system_prompt, user_prompt


def build_service_request_refinement_prompt(
    *,
    ticket_title: str,
    ticket_description: str,
    profile_metadata: dict[str, object],
    base_recommended_action: str,
    base_next_best_actions: list[str],
    base_validation_steps: list[str],
    language: str = "fr",
) -> tuple[str, str]:
    """Build a prompt for refining deterministic service-request actions."""

    system_prompt = (
        "You are refining a deterministic IT service-request runbook. "
        "Do NOT change the workflow class: this remains a planned fulfillment task, not incident troubleshooting. "
        "Do NOT invent systems, ticket IDs, approvals, teams, users, or environment facts. "
        "Make the wording clearer and more specific while staying aligned to the extracted request profile. "
        "Keep the tone operational and runbook-oriented. "
        "Return ONLY valid JSON with no markdown."
    )

    lang_instruction = "Respond in French." if language == "fr" else "Respond in English."
    profile_bits = json.dumps(profile_metadata or {}, ensure_ascii=True)
    base_payload = json.dumps(
        {
            "base_recommended_action": base_recommended_action,
            "base_next_best_actions": base_next_best_actions,
            "base_validation_steps": base_validation_steps,
        },
        ensure_ascii=True,
    )
    user_prompt = (
        f"Ticket title: {ticket_title}\n"
        f"Description: {ticket_description[:800]}\n"
        f"Structured service-request profile: {profile_bits}\n"
        f"Deterministic base action package: {base_payload}\n\n"
        f"{lang_instruction}\n"
        "Return a JSON object with exactly these fields:\n"
        "{\n"
        '  "recommended_action": "string",\n'
        '  "next_best_actions": ["string", "string"],\n'
        '  "validation_steps": ["string", "string"],\n'
        '  "reasoning_note": "short sentence explaining the refinement"\n'
        "}\n"
        "Rules:\n"
        "- Preserve the same fulfillment family and workflow intent.\n"
        "- Do not switch into root-cause diagnosis.\n"
        "- Keep the action package specific and operational, not vague.\n"
        "- validation_steps must verify fulfillment completion, not incident recovery.\n"
    )
    return system_prompt, user_prompt
