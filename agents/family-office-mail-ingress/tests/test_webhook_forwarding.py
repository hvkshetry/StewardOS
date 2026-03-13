# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

agent_root = str(Path(__file__).resolve().parents[1])
if agent_root not in sys.path:
    sys.path.insert(0, agent_root)

import src.main as main


def test_webhook_gmail_forwards_synchronously(monkeypatch):
    forwarded: list[dict] = []

    async def _fake_forward(payload: dict) -> None:
        forwarded.append(payload)

    monkeypatch.setattr(main, "_verify_pubsub_jwt", lambda request: None)
    monkeypatch.setattr(main, "_forward_to_worker", _fake_forward)

    payload = {"message": {"data": "abc"}}

    with TestClient(main.app) as client:
        response = client.post("/webhooks/gmail", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert forwarded == [payload]


def test_webhook_gmail_surfaces_worker_transport_failure(monkeypatch):
    async def _fake_forward(payload: dict) -> None:
        raise HTTPException(status_code=502, detail="Worker rejected notification")

    monkeypatch.setattr(main, "_verify_pubsub_jwt", lambda request: None)
    monkeypatch.setattr(main, "_forward_to_worker", _fake_forward)

    payload = {"message": {"data": "abc"}}

    with TestClient(main.app) as client:
        response = client.post("/webhooks/gmail", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"] == "Worker rejected notification"
