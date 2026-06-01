"""
SentryPay — Unit Tests: Agent Core
=====================================
Tests agent utility functions — input sanitization, verdict parsing,
account masking — without making live Gemini or Elastic API calls.

Run:
    pytest tests/test_agent.py -v
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Input sanitization ────────────────────────────────────────────────────────

class TestSanitizeInput:

    def test_removes_control_characters(self):
        """Should strip null bytes and control characters."""
        from agent.gemini_agent import sanitize_input

        dirty = "Hello\x00World\x07"
        clean = sanitize_input(dirty)
        assert "\x00" not in clean
        assert "\x07" not in clean
        assert "Hello" in clean
        assert "World" in clean

    def test_preserves_newlines_and_tabs(self):
        """Should keep newlines and tabs (needed for email formatting)."""
        from agent.gemini_agent import sanitize_input

        text  = "Line 1\nLine 2\tTabbed"
        clean = sanitize_input(text)
        assert "\n" in clean
        assert "\t" in clean

    def test_truncates_to_max_length(self):
        """Should truncate text exceeding max_length."""
        from agent.gemini_agent import sanitize_input

        long_text = "A" * 10000
        clean     = sanitize_input(long_text, max_length=5000)
        assert len(clean) <= 5100  # some padding for truncation message
        assert "truncated" in clean

    def test_short_text_unchanged(self):
        """Short clean text should pass through unchanged."""
        from agent.gemini_agent import sanitize_input

        text  = "Please send $1,000 to our account."
        clean = sanitize_input(text)
        assert clean == text

    def test_collapses_excessive_newlines(self):
        """More than 3 consecutive newlines should be collapsed to 3."""
        from agent.gemini_agent import sanitize_input

        text  = "Line 1\n\n\n\n\n\nLine 2"
        clean = sanitize_input(text)
        assert "\n\n\n\n" not in clean


class TestSanitizeAccountNumber:

    def test_removes_injection_characters(self):
        """Should remove special chars that could be used for ES|QL injection."""
        from agent.gemini_agent import sanitize_account_number

        # Attempt to inject ES|QL via account number
        dirty = "GB29NWBK\" | FROM malicious_index | LIMIT 1 --"
        clean = sanitize_account_number(dirty)
        assert '"' not in clean
        assert '|' not in clean
        assert '--' not in clean

    def test_keeps_valid_account_format(self):
        """Should preserve alphanumeric account numbers."""
        from agent.gemini_agent import sanitize_account_number

        account = "GB29NWBK60161331926819"
        clean   = sanitize_account_number(account)
        assert clean == account

    def test_truncates_to_50_chars(self):
        """Should truncate to 50 characters maximum."""
        from agent.gemini_agent import sanitize_account_number

        long_account = "A" * 100
        clean        = sanitize_account_number(long_account)
        assert len(clean) <= 50


# ── Verdict parsing ───────────────────────────────────────────────────────────

class TestParseVerdict:

    def setup_method(self):
        """Create agent instance with mocked dependencies."""
        with patch("agent.gemini_agent.genai"), \
             patch("agent.tools._embedding_model"), \
             patch("agent.tools._es"), \
             patch("agent.bigquery_logger.get_bigquery_client"), \
             patch("agent.observability._langfuse"):
            from agent.gemini_agent import SentryPayAgent
            self.agent = SentryPayAgent.__new__(SentryPayAgent)
            self.agent.model = "gemini-2.5-flash"

    def test_parses_clean_json(self):
        """Should parse a clean JSON verdict correctly."""
        verdict_json = json.dumps({
            "verdict":            "BLOCK",
            "confidence":         0.90,
            "typology_matched":   "Business Email Compromise",
            "reasoning":          "Strong BEC match detected.",
            "red_flags":          ["new account", "urgent tone"],
            "recommended_action": "Block and verify",
            "sar_required":       True
        })

        result = self.agent._parse_verdict(verdict_json)

        assert result is not None
        assert result["verdict"]          == "BLOCK"
        assert result["confidence"]       == 0.90
        assert result["typology_matched"] == "Business Email Compromise"
        assert result["sar_required"]     is True

    def test_parses_json_with_markdown_fences(self):
        """Should strip markdown code fences before parsing."""
        verdict = """```json
{
  "verdict": "FRICTION",
  "confidence": 0.65,
  "typology_matched": null,
  "reasoning": "New vendor detected.",
  "red_flags": ["new vendor"],
  "recommended_action": "Verify",
  "sar_required": false
}
```"""
        result = self.agent._parse_verdict(verdict)

        assert result is not None
        assert result["verdict"]    == "FRICTION"
        assert result["confidence"] == 0.65

    def test_parses_json_embedded_in_text(self):
        """Should extract JSON even when surrounded by extra text."""
        verdict = """After analysis, here is my verdict:
{
  "verdict": "ALLOW",
  "confidence": 0.88,
  "typology_matched": null,
  "reasoning": "Known vendor, normal amount.",
  "red_flags": [],
  "recommended_action": "Proceed",
  "sar_required": false
}
That concludes my analysis."""

        result = self.agent._parse_verdict(verdict)
        assert result is not None
        assert result["verdict"] == "ALLOW"

    def test_returns_none_on_invalid_json(self):
        """Should return None when no valid JSON can be extracted."""
        result = self.agent._parse_verdict("This is not JSON at all.")
        assert result is None

    def test_returns_none_on_empty_response(self):
        """Should return None on empty string."""
        assert self.agent._parse_verdict("") is None
        assert self.agent._parse_verdict(None) is None


# ── Account masking ───────────────────────────────────────────────────────────

class TestMaskAccount:

    def test_masks_standard_account(self):
        """Should show only last 4 digits."""
        from agent.bigquery_logger import mask_account

        assert mask_account("GB29NWBK60161331926819") == "****6819"
        assert mask_account("US12345678901234567890") == "****7890"

    def test_masks_short_account(self):
        """Should handle short account numbers."""
        from agent.bigquery_logger import mask_account

        assert mask_account("1234")  == "****1234"
        assert mask_account("123")   == "****"
        assert mask_account("")      == "****"
        assert mask_account(None)    == "****"

    def test_last_four_always_visible(self):
        """The last 4 characters should always be in the output."""
        from agent.bigquery_logger import mask_account

        account = "ABCDEFGHIJ1234"
        masked  = mask_account(account)
        assert masked.endswith("1234")
        assert masked.startswith("****")


# ── BigQuery logger ───────────────────────────────────────────────────────────

class TestBigQueryLogger:

    @patch("agent.bigquery_logger.get_bigquery_client")
    def test_account_masked_before_storage(self, mock_bq_client):
        """Account number should be masked in the BigQuery row."""
        from agent.bigquery_logger import log_decision

        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        mock_bq_client.return_value = mock_client

        log_decision(
            user_id          = "user_001",
            verdict          = "BLOCK",
            confidence       = 0.9,
            typology_matched = "BEC",
            reasoning        = "Test",
            red_flags        = ["test"],
            amount           = 47000.0,
            recipient_name   = "Apex Scaffolding",
            account_number   = "GB29NWBK60161331926819",  # full account
            email_text       = "Test email",
            sar_required     = True,
            processing_ms    = 5000
        )

        # Get the row that was inserted
        call_args = mock_client.insert_rows_json.call_args
        rows      = call_args[0][1]  # second positional arg
        row       = rows[0]

        # Account should be masked
        assert row["account_number"] == "****6819"
        assert "GB29NWBK" not in row["account_number"]

    @patch("agent.bigquery_logger.get_bigquery_client")
    def test_email_truncated_to_500_chars(self, mock_bq_client):
        """Email snippet should be max 500 characters."""
        from agent.bigquery_logger import log_decision

        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        mock_bq_client.return_value = mock_client

        long_email = "E" * 2000

        log_decision(
            user_id="u", verdict="ALLOW", confidence=0.9,
            typology_matched=None, reasoning="test", red_flags=[],
            amount=100.0, recipient_name="Vendor",
            account_number="ACC123", email_text=long_email,
            sar_required=False, processing_ms=1000
        )

        call_args = mock_client.insert_rows_json.call_args
        row       = call_args[0][1][0]

        assert len(row["email_snippet"]) <= 500