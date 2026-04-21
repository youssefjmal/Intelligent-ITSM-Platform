"""Unit tests for app.services.ai.pii_scrubber.scrub_pii

WHY THIS FILE EXISTS
--------------------
Every ticket description is passed through scrub_pii() before being sent
to the external Groq LLM.  If a regex is broken, real email addresses,
phone numbers, or IP addresses leak to a third-party API — a direct ISO 27001
violation.  These tests act as a safety net: any change to the regex patterns
that breaks PII removal will be caught here before it reaches production.

WHAT IS A UNIT TEST?
--------------------
A unit test checks one small piece of code in complete isolation.
  - No database, no network, no real LLM calls.
  - We call scrub_pii() directly with a string we control.
  - We check that the output string is exactly what we expect.
  - If the test passes, we KNOW the function does the right thing for that input.
  - Each test covers one specific scenario (email, IP, phone, etc.) so that
    when a test fails you know EXACTLY what broke.
"""

from __future__ import annotations

import pytest

from app.services.ai.pii_scrubber import scrub_pii


# ---------------------------------------------------------------------------
# Email addresses
# ---------------------------------------------------------------------------


class TestEmailScrubbing:
    """Email addresses must be replaced with [EMAIL] before reaching the LLM."""

    def test_simple_email_is_replaced(self):
        """The most common case: a plain email address in the ticket body."""
        result = scrub_pii("Contact john.doe@teamwill.com for help.")
        # The email must be gone
        assert "john.doe@teamwill.com" not in result
        # The placeholder must be there
        assert "[EMAIL]" in result

    def test_email_with_plus_sign(self):
        """Gmail-style tags like user+tag@domain.com are still email addresses."""
        result = scrub_pii("Send to support+urgent@company.org")
        assert "support+urgent@company.org" not in result
        assert "[EMAIL]" in result

    def test_email_with_subdomain(self):
        """Addresses on subdomains (john@mail.teamwill.com) must also be scrubbed."""
        result = scrub_pii("Reply to john@mail.teamwill.com")
        assert "john@mail.teamwill.com" not in result
        assert "[EMAIL]" in result

    def test_multiple_emails_all_replaced(self):
        """If a ticket contains two email addresses, both must be scrubbed."""
        text = "CC: alice@example.com and bob@example.org please."
        result = scrub_pii(text)
        assert "alice@example.com" not in result
        assert "bob@example.org" not in result
        # Both placeholders should appear
        assert result.count("[EMAIL]") == 2

    def test_surrounding_text_is_preserved(self):
        """Non-PII text around the email must not be changed."""
        result = scrub_pii("Hello, contact admin@company.com for the VPN issue.")
        assert result == "Hello, contact [EMAIL] for the VPN issue."

    def test_no_email_in_text_unchanged(self):
        """If there is no email in the text, scrub_pii must return it unchanged."""
        text = "The VPN tunnel dropped after a Windows update."
        assert scrub_pii(text) == text


# ---------------------------------------------------------------------------
# IPv4 addresses
# ---------------------------------------------------------------------------


class TestIPAddressScrubbing:
    """IP addresses in ticket descriptions (e.g. server IPs) must be masked."""

    def test_standard_ipv4_replaced(self):
        """A standard server IP address like 192.168.1.100 must be replaced."""
        result = scrub_pii("Server 192.168.1.100 is unreachable.")
        assert "192.168.1.100" not in result
        assert "[IP_ADDRESS]" in result

    def test_public_ip_replaced(self):
        """Public IPs such as 203.0.113.42 must also be scrubbed."""
        result = scrub_pii("The attacker IP was 203.0.113.42 according to the firewall log.")
        assert "203.0.113.42" not in result
        assert "[IP_ADDRESS]" in result

    def test_version_number_not_replaced(self):
        """Version strings like '1.0.0' must NOT be replaced — they are not IP addresses.

        The regex uses a strict range (0-255 per octet) to avoid false positives.
        '1.0.0' only has 3 octets so it should not match.
        """
        result = scrub_pii("Updated to version 1.0.0 of the agent.")
        assert "[IP_ADDRESS]" not in result

    def test_multiple_ips_all_replaced(self):
        result = scrub_pii("Source: 10.0.0.1, Destination: 10.0.0.2")
        assert "10.0.0.1" not in result
        assert "10.0.0.2" not in result
        assert result.count("[IP_ADDRESS]") == 2


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------


class TestPhoneScrubbing:
    """Phone numbers (international and French format) must be masked."""

    def test_international_e164_replaced(self):
        """Standard international format +33 6 12 34 56 78 must be replaced."""
        result = scrub_pii("Call me at +33 6 12 34 56 78 after 2pm.")
        assert "+33 6 12 34 56 78" not in result
        assert "[PHONE]" in result

    def test_us_number_replaced(self):
        """US numbers in E.164 format like +1-800-555-0199 must be replaced."""
        result = scrub_pii("Hotline: +1-800-555-0199")
        assert "+1-800-555-0199" not in result
        assert "[PHONE]" in result

    def test_french_10digit_replaced(self):
        """French domestic format '06 12 34 56 78' must be replaced."""
        result = scrub_pii("Mon numéro est 06 12 34 56 78.")
        assert "06 12 34 56 78" not in result
        assert "[PHONE]" in result

    def test_french_dot_format_replaced(self):
        """French number with dots: 06.12.34.56.78 must also be replaced."""
        result = scrub_pii("Contactez le 06.12.34.56.78 pour le support.")
        assert "06.12.34.56.78" not in result
        assert "[PHONE]" in result

    def test_french_no_separator_replaced(self):
        """French number with no separator: 0612345678."""
        result = scrub_pii("Appelez le 0612345678 svp.")
        assert "0612345678" not in result
        assert "[PHONE]" in result


# ---------------------------------------------------------------------------
# Mixed PII — multiple types in one text
# ---------------------------------------------------------------------------


class TestMixedPII:
    """Real tickets often contain several PII types at once."""

    def test_email_and_ip_in_same_text(self):
        text = "User john@corp.com reported that server 10.0.1.5 is down."
        result = scrub_pii(text)
        assert "john@corp.com" not in result
        assert "10.0.1.5" not in result
        assert "[EMAIL]" in result
        assert "[IP_ADDRESS]" in result

    def test_all_three_pii_types_in_one_call(self):
        text = (
            "From: user@example.com | IP: 192.168.0.10 | "
            "Phone: +33 6 00 11 22 33"
        )
        result = scrub_pii(text)
        assert "user@example.com" not in result
        assert "192.168.0.10" not in result
        assert "+33 6 00 11 22 33" not in result
        assert "[EMAIL]" in result
        assert "[IP_ADDRESS]" in result
        assert "[PHONE]" in result


# ---------------------------------------------------------------------------
# Edge cases — the function must never crash
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """scrub_pii must be safe to call on unusual inputs without crashing."""

    def test_empty_string_returns_empty(self):
        """An empty string in, empty string out — no crash."""
        assert scrub_pii("") == ""

    def test_none_returns_none(self):
        """None input returns None — callers that pass None must not get an exception."""
        assert scrub_pii(None) is None  # type: ignore[arg-type]

    def test_plain_text_no_pii_unchanged(self):
        """A normal ticket description with no PII must come back exactly as-is."""
        text = "The printer on floor 3 is jammed and needs toner replacement."
        assert scrub_pii(text) == text

    def test_very_long_text_does_not_crash(self):
        """Performance check: a 10 000-character string must not crash or timeout."""
        long_text = "The network switch failed. " * 400  # ~10 000 chars, no PII
        result = scrub_pii(long_text)
        assert result == long_text  # unchanged because no PII
