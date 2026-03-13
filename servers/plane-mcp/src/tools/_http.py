"""Shared HTTP helpers for direct Plane REST API calls.

Used for endpoints not yet covered by plane-sdk (pages, history, views).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_API_PREFIX = "/api/v1"


def _base_url() -> str:
    return os.environ.get("PLANE_BASE_URL", "http://localhost:8082")


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("PLANE_API_TOKEN", "")
    return {
        "X-API-Key": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def api_get(path: str) -> Any:
    """Direct GET against the Plane REST API."""
    url = f"{_base_url()}{_API_PREFIX}{path}"
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(url, headers=_auth_headers())
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, json_data: dict[str, Any]) -> Any:
    """Direct POST against the Plane REST API."""
    url = f"{_base_url()}{_API_PREFIX}{path}"
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(url, headers=_auth_headers(), json=json_data)
        resp.raise_for_status()
        return resp.json()


async def api_patch(path: str, json_data: dict[str, Any]) -> Any:
    """Direct PATCH against the Plane REST API."""
    url = f"{_base_url()}{_API_PREFIX}{path}"
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.patch(url, headers=_auth_headers(), json=json_data)
        resp.raise_for_status()
        return resp.json()


async def api_delete(path: str) -> None:
    """Direct DELETE against the Plane REST API."""
    url = f"{_base_url()}{_API_PREFIX}{path}"
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.delete(url, headers=_auth_headers())
        resp.raise_for_status()
