from __future__ import annotations

import asyncio
import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import server


class _FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, content_type: str = "application/json"):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method: str, path: str, **kwargs):
        return _FakeResponse({"items": [1, 2, 3]})


def test_homebox_request_returns_envelope(monkeypatch):
    monkeypatch.setattr(server, "_token", "token")
    monkeypatch.setattr(server, "_client", lambda auth=True: _FakeClient())

    result = asyncio.run(server._request("GET", "/api/v1/items"))

    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["data"]["items"] == [1, 2, 3]
