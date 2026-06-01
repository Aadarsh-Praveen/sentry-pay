"""
SentryPay — Unit Tests: Agent Tools
======================================
Tests each of the three Elastic tool functions in isolation
using mocked Elasticsearch responses.

These tests verify tool logic (scoring, anomaly detection,
result parsing) without making live API calls, so they run
fast and can be used in CI/CD without credentials.

Run:
    pytest tests/test_tools.py -v
    pytest tests/test_tools.py -v --tb=short  # shorter tracebacks
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_elastic_client():
    """Mock Elasticsearch client for all tests."""
    with patch("agent.tools._es") as mock_es:
        yield mock_es


@pytest.fixture
def mock_embedding_model():
    """Mock Vertex AI embedding model."""
    with patch("agent.tools._embedding_model") as mock_model:
        mock_embedding       = MagicMock()
        mock_embedding.values = [0.1] * 768
        mock_model.get_embeddings.return_value = [mock_embedding]
        yield mock_model


# ── Tool 1: search_scam_typologies ───────────────────────────────────────────

class TestSearchScamTypologies:

    def test_returns_matches_on_success(self, mock_elastic_client, mock_embedding_model):
        """Should return top matches when Elastic returns results."""
        from agent.tools import search_scam_typologies

        mock_elastic_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_score": 0.92,
                        "_source": {
                            "typology_name":      "Business Email Compromise",
                            "description":        "Fraudster impersonates vendor...",
                            "red_flags":          ["new account", "urgent tone"],
                            "target_victim":      "SMB finance teams",
                            "typical_payment_type": "Wire",
                            "avg_loss_usd":       48000
                        }
                    }
                ]
            }
        }

        result = search_scam_typologies(
            email_text      = "Please update our bank details",
            payment_context = "Amount: $47,000, Wire transfer"
        )

        assert result["search_successful"] is True
        assert result["top_match"]  == "Business Email Compromise"
        assert result["top_score"]  == 0.92
        assert len(result["matches"]) == 1

    def test_returns_empty_on_no_results(self, mock_elastic_client, mock_embedding_model):
        """Should return empty matches when Elastic returns no hits."""
        from agent.tools import search_scam_typologies

        mock_elastic_client.search.return_value = {
            "hits": {"hits": []}
        }

        result = search_scam_typologies(
            email_text      = "Regular invoice attached",
            payment_context = "Amount: $500, ACH"
        )

        assert result["search_successful"] is True
        assert result["top_match"]  is None
        assert result["top_score"]  == 0.0
        assert result["matches"]    == []

    def test_handles_elastic_error_gracefully(self, mock_elastic_client, mock_embedding_model):
        """Should return search_successful=False on Elastic error."""
        from agent.tools import search_scam_typologies

        mock_elastic_client.search.side_effect = Exception("Connection timeout")

        result = search_scam_typologies(
            email_text      = "test email",
            payment_context = "test payment"
        )

        assert result["search_successful"] is False
        assert result["top_match"]         is None
        assert "error" in result

    def test_similarity_score_in_result(self, mock_elastic_client, mock_embedding_model):
        """Similarity score should be rounded to 4 decimal places."""
        from agent.tools import search_scam_typologies

        mock_elastic_client.search.return_value = {
            "hits": {
                "hits": [{
                    "_score": 0.847812345,
                    "_source": {
                        "typology_name":      "Investment Fraud",
                        "description":        "Guaranteed returns scam",
                        "red_flags":          ["guaranteed returns"],
                        "target_victim":      "investors",
                        "typical_payment_type": "Wire",
                        "avg_loss_usd":       50000
                    }
                }]
            }
        }

        result = search_scam_typologies("invest now", "50000 wire")
        assert result["top_score"] == 0.8478


# ── Tool 2: check_beneficiary_account ────────────────────────────────────────

class TestCheckBeneficiaryAccount:

    def test_flagged_account_returns_high_risk(self, mock_elastic_client):
        """Should return is_flagged=True and HIGH risk for flagged accounts."""
        from agent.tools import check_beneficiary_account

        mock_elastic_client.esql.query.return_value = {
            "columns": [
                {"name": "entity_name"},
                {"name": "risk_score"},
                {"name": "risk_category"},
                {"name": "flag_reason"},
                {"name": "is_flagged"},
                {"name": "datasets"}
            ],
            "values": [
                ["Suspicious Entity Ltd", 0.95, "HIGH",
                 "Appeared in 3 fraud reports", True, "sentry_pay_community"]
            ]
        }

        result = check_beneficiary_account(
            account_number = "GB94METRO00000087654321",
            recipient_name = "Suspicious Entity Ltd"
        )

        assert result["is_flagged"]    is True
        assert result["risk_score"]    == 0.95
        assert result["risk_category"] == "HIGH"
        assert result["account_found"] is True

    def test_unknown_account_returns_low_risk(self, mock_elastic_client):
        """Account not in database should return UNKNOWN risk, not flagged."""
        from agent.tools import check_beneficiary_account

        mock_elastic_client.esql.query.return_value = {
            "columns": [],
            "values": []
        }

        result = check_beneficiary_account(
            account_number = "GB82WEST12345698765432",
            recipient_name = "City Office Supplies"
        )

        assert result["is_flagged"]    is False
        assert result["risk_category"] == "UNKNOWN"
        assert result["account_found"] is False
        assert result["risk_score"]    == 0.20

    def test_name_match_detection(self, mock_elastic_client):
        """Should detect when recipient name matches database entity."""
        from agent.tools import check_beneficiary_account

        mock_elastic_client.esql.query.return_value = {
            "columns": [
                {"name": "entity_name"},
                {"name": "risk_score"},
                {"name": "risk_category"},
                {"name": "flag_reason"},
                {"name": "is_flagged"},
                {"name": "datasets"}
            ],
            "values": [
                ["Apex Scaffolding Ltd", 0.1, "LOW", None, False, ""]
            ]
        }

        result = check_beneficiary_account(
            account_number = "GB29NWBK60161331926819",
            recipient_name = "Apex Scaffolding"
        )

        # "Apex Scaffolding" should match "Apex Scaffolding Ltd"
        assert result["name_match"] is True

    def test_handles_elastic_error(self, mock_elastic_client):
        """Should return safe defaults on Elastic error."""
        from agent.tools import check_beneficiary_account

        mock_elastic_client.esql.query.side_effect = Exception("ES|QL error")

        result = check_beneficiary_account("test_account", "test_name")

        assert result["is_flagged"]    is False
        assert result["account_found"] is False
        assert "error" in result["flag_reason"]


# ── Tool 3: check_payment_velocity ───────────────────────────────────────────

class TestCheckPaymentVelocity:

    def test_anomalous_amount_detected(self, mock_elastic_client):
        """Payment above max_normal threshold should be flagged as anomalous."""
        from agent.tools import check_payment_velocity

        mock_elastic_client.esql.query.return_value = {
            "columns": [
                {"name": "mean_payment"},
                {"name": "std_payment"},
                {"name": "max_normal"},
                {"name": "known_accounts"},
                {"name": "known_vendors"},
                {"name": "preferred_rail"}
            ],
            "values": [[8500.0, 3200.0, 18000.0,
                        ["GB29NWBK60161331926819"],
                        ["Apex Scaffolding Ltd"],
                        "ACH"]]
        }

        result = check_payment_velocity(
            user_id        = "demo_user_001",
            amount         = 47000.0,    # well above max_normal of 18000
            recipient_name = "New Vendor",
            account_number = "NEW_ACCOUNT",
            payment_type   = "Wire"
        )

        assert result["is_amount_anomalous"] is True
        assert result["z_score"]             > 3.0
        assert result["is_new_account"]      is True
        assert result["is_new_vendor"]       is True
        assert result["anomaly_count"]       >= 3

    def test_normal_payment_not_anomalous(self, mock_elastic_client):
        """Known vendor, known account, normal amount should not be anomalous."""
        from agent.tools import check_payment_velocity

        mock_elastic_client.esql.query.return_value = {
            "columns": [
                {"name": "mean_payment"},
                {"name": "std_payment"},
                {"name": "max_normal"},
                {"name": "known_accounts"},
                {"name": "known_vendors"},
                {"name": "preferred_rail"}
            ],
            "values": [[800.0, 150.0, 1200.0,
                        ["GB82WEST12345698765432"],
                        ["City Office Supplies"],
                        "ACH"]]
        }

        result = check_payment_velocity(
            user_id        = "demo_user_001",
            amount         = 847.50,    # within normal range
            recipient_name = "City Office Supplies",
            account_number = "GB82WEST12345698765432",
            payment_type   = "ACH"
        )

        assert result["is_amount_anomalous"] is False
        assert result["is_new_account"]      is False
        assert result["is_new_vendor"]       is False
        assert result["anomaly_count"]       == 0

    def test_no_baseline_returns_unknown(self, mock_elastic_client):
        """Missing user baseline should return safe defaults with note."""
        from agent.tools import check_payment_velocity

        mock_elastic_client.esql.query.return_value = {
            "columns": [],
            "values": []
        }

        result = check_payment_velocity(
            user_id        = "unknown_user",
            amount         = 5000.0,
            recipient_name = "Some Vendor",
            account_number = "SOME_ACCOUNT",
            payment_type   = "ACH"
        )

        assert "note" in result
        assert result["anomaly_count"] == 1

    def test_z_score_calculation(self, mock_elastic_client):
        """Z-score should be (amount - mean) / std."""
        from agent.tools import check_payment_velocity

        mock_elastic_client.esql.query.return_value = {
            "columns": [
                {"name": "mean_payment"},
                {"name": "std_payment"},
                {"name": "max_normal"},
                {"name": "known_accounts"},
                {"name": "known_vendors"},
                {"name": "preferred_rail"}
            ],
            "values": [[1000.0, 200.0, 1500.0, [], [], "ACH"]]
        }

        result = check_payment_velocity(
            user_id="u1", amount=1400.0,
            recipient_name="V", account_number="A", payment_type="ACH"
        )

        # z = (1400 - 1000) / 200 = 2.0
        assert abs(result["z_score"] - 2.0) < 0.01

    def test_handles_elastic_error(self, mock_elastic_client):
        """Should return safe defaults on Elastic error."""
        from agent.tools import check_payment_velocity

        mock_elastic_client.esql.query.side_effect = Exception("timeout")

        result = check_payment_velocity(
            "user", 1000.0, "vendor", "account", "ACH"
        )

        assert "error" in result
        assert result["anomaly_count"] == 1


# ── Retry decorator ───────────────────────────────────────────────────────────

class TestRetryDecorator:

    def test_retries_on_connection_error(self):
        """Should retry on ConnectionError and succeed on second attempt."""
        from agent.tools import with_retry

        attempt_count = {"n": 0}

        @with_retry(max_attempts=3, delay_seconds=0.01)
        def flaky_function():
            attempt_count["n"] += 1
            if attempt_count["n"] < 2:
                raise ConnectionError("Connection reset")
            return {"success": True}

        result = flaky_function()
        assert result == {"success": True}
        assert attempt_count["n"] == 2

    def test_raises_non_transient_errors_immediately(self):
        """Should not retry on non-network errors like ValueError."""
        from agent.tools import with_retry

        attempt_count = {"n": 0}

        @with_retry(max_attempts=3, delay_seconds=0.01)
        def bad_function():
            attempt_count["n"] += 1
            raise ValueError("Bad input")

        with pytest.raises(ValueError):
            bad_function()

        # Should only be called once — no retry on ValueError
        assert attempt_count["n"] == 1

    def test_exhausts_retries_and_returns_error(self):
        """Should return error dict after all retries exhausted."""
        from agent.tools import with_retry

        @with_retry(max_attempts=2, delay_seconds=0.01)
        def always_fails():
            raise ConnectionError("Always down")

        result = always_fails()
        assert result.get("retry_exhausted") is True
        assert "error" in result