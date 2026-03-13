"""Tests for the Gmail webhook ingress endpoint."""

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_settings():
    """Ensure settings are in a known state for each test."""
    from src.config import settings

    original_audience = settings.pubsub_audience
    original_email = settings.pubsub_service_account_email
    yield
    settings.pubsub_audience = original_audience
    settings.pubsub_service_account_email = original_email


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


def _make_pubsub_payload(email="user@gmail.com", history_id=12345):
    data = json.dumps({"emailAddress": email, "historyId": history_id})
    encoded = base64.urlsafe_b64encode(data.encode()).decode()
    return {
        "message": {"data": encoded, "messageId": "123"},
        "subscription": "projects/test/subscriptions/gmail-push",
    }


class TestWebhookNoAuth:
    """Tests when pubsub_audience is not configured (JWT verification skipped)."""

    def test_valid_payload_accepted(self, client):
        from src.config import settings

        settings.pubsub_audience = ""
        with patch("src.main._forward_to_worker", new=AsyncMock()) as forwarder:
            resp = client.post("/webhooks/gmail", json=_make_pubsub_payload())
        forwarder.assert_awaited_once()
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_missing_message_data_returns_400(self, client):
        from src.config import settings

        settings.pubsub_audience = ""
        resp = client.post("/webhooks/gmail", json={"message": {}})
        assert resp.status_code == 400

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "family-office-mail-ingress"
        assert resp.json()["pubsub_auth_configured"] is False


class TestWebhookWithAuth:
    """Tests when pubsub_audience is configured (JWT verification enabled)."""

    def test_missing_auth_header_returns_401(self, client):
        from src.config import settings

        settings.pubsub_audience = "https://example.com"
        resp = client.post("/webhooks/gmail", json=_make_pubsub_payload())
        assert resp.status_code == 401

    def test_invalid_jwt_returns_401(self, client):
        from src.config import settings

        settings.pubsub_audience = "https://example.com"
        resp = client.post(
            "/webhooks/gmail",
            json=_make_pubsub_payload(),
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_valid_jwt_accepted(self, client):
        from src.config import settings

        settings.pubsub_audience = "https://example.com"
        settings.pubsub_service_account_email = "test@test.iam.gserviceaccount.com"

        mock_claim = {
            "email": "test@test.iam.gserviceaccount.com",
            "aud": "https://example.com",
        }
        with patch(
            "src.main.id_token.verify_oauth2_token", return_value=mock_claim
        ), patch("src.main._forward_to_worker", new=AsyncMock()) as forwarder:
            resp = client.post(
                "/webhooks/gmail",
                json=_make_pubsub_payload(),
                headers={"Authorization": "Bearer valid-token"},
            )
        forwarder.assert_awaited_once()
        assert resp.status_code == 200

    def test_health_check_reports_auth_enabled(self, client):
        from src.config import settings

        settings.pubsub_audience = "https://example.com"
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["pubsub_auth_configured"] is True

    def test_wrong_service_account_returns_401(self, client):
        from src.config import settings

        settings.pubsub_audience = "https://example.com"
        settings.pubsub_service_account_email = "expected@test.iam.gserviceaccount.com"

        mock_claim = {
            "email": "wrong@other.iam.gserviceaccount.com",
            "aud": "https://example.com",
        }
        with patch(
            "src.main.id_token.verify_oauth2_token", return_value=mock_claim
        ):
            resp = client.post(
                "/webhooks/gmail",
                json=_make_pubsub_payload(),
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 401
