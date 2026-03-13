#!/usr/bin/env python3
"""Strict usefulness gate for Peloton API data vs Apple summary-level baseline."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

API_BASE = os.environ.get("PELOTON_API_BASE_URL", "https://api.onepeloton.com")
BEARER_TOKEN = os.environ.get("PELOTON_BEARER_TOKEN", "")
OAUTH_CLIENT_ID = os.environ.get("PELOTON_OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("PELOTON_OAUTH_CLIENT_SECRET", "")
OAUTH_REFRESH_TOKEN = os.environ.get("PELOTON_OAUTH_REFRESH_TOKEN", "")
OAUTH_TOKEN_URL = os.environ.get("PELOTON_OAUTH_TOKEN_URL", "https://auth.onepeloton.com/oauth/token")
OAUTH_AUDIENCE = os.environ.get("PELOTON_OAUTH_AUDIENCE", "https://api.onepeloton.com/")
OAUTH_SCOPE = os.environ.get("PELOTON_OAUTH_SCOPE", "openid offline_access")
OAUTH_TOKEN_STORE_PATH = os.environ.get("PELOTON_OAUTH_TOKEN_STORE_PATH", "").strip()
REQUIRE_OAUTH = os.environ.get("PELOTON_REQUIRE_OAUTH", "0").strip().lower() in {"1", "true", "yes"}
USERNAME = os.environ.get("PELOTON_USERNAME", "")
PASSWORD = os.environ.get("PELOTON_PASSWORD", "")
SESSION_ID = os.environ.get("PELOTON_SESSION_ID", "")
TIMEOUT = float(os.environ.get("PELOTON_TIMEOUT_SEC", "30"))
PLATFORM = os.environ.get("PELOTON_PLATFORM", "web")

_refresh_token_current = OAUTH_REFRESH_TOKEN


def _load_store_refresh_token() -> None:
    global _refresh_token_current
    if not OAUTH_TOKEN_STORE_PATH:
        return
    try:
        path = Path(OAUTH_TOKEN_STORE_PATH)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        token = payload.get("refresh_token")
        if isinstance(token, str) and token:
            _refresh_token_current = token
    except Exception:
        return


def _write_store_tokens(refresh_token: str, access_token: str, expires_at_epoch: int) -> None:
    if not OAUTH_TOKEN_STORE_PATH:
        return
    try:
        path = Path(OAUTH_TOKEN_STORE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "refresh_token": refresh_token,
            "access_token": access_token,
            "expires_at_epoch": expires_at_epoch,
            "updated_at_epoch": int(time.time()),
        }
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        return

logging.getLogger("httpx").setLevel(logging.WARNING)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "peloton-platform": PLATFORM,
    }


def _extract_workouts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "workouts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _extract_user_id(session_payload: dict[str, Any]) -> str:
    user_data = session_payload.get("user_data")
    if isinstance(user_data, dict):
        for key in ("id", "user_id"):
            val = user_data.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


def _as_date(raw: Any) -> str:
    if not raw:
        return ""
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            # Peloton payloads typically use unix seconds; support millis defensively.
            if ts > 1_000_000_000_000:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()

        if not isinstance(raw, str):
            return ""

        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).date().isoformat()
    except Exception:
        return raw[:10] if isinstance(raw, str) else ""


def _workout_date(item: dict[str, Any]) -> str:
    for key in (
        "created",
        "created_at",
        "created_at_ts",
        "start_time",
        "start_time_utc",
        "start",
        "startDate",
    ):
        value = item.get(key)
        if isinstance(value, (str, int, float)) and value:
            return _as_date(value)
    return ""


def _walk_keys(value: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            current = f"{prefix}.{k}" if prefix else k
            yield current.lower()
            yield from _walk_keys(v, current)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item, prefix)


def _contains_any_key(value: Any, candidates: tuple[str, ...]) -> bool:
    keys = set(_walk_keys(value))
    return any(any(candidate in key for key in keys) for candidate in candidates)


def _oauth_refresh_enabled() -> bool:
    _load_store_refresh_token()
    return bool(OAUTH_CLIENT_ID and _refresh_token_current)


def _decode_jwt_exp_epoch(access_token: str) -> int | None:
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        data = json.loads(decoded.decode("utf-8"))
        exp = data.get("exp")
        if isinstance(exp, int):
            return exp
    except Exception:
        return None
    return None


async def _refresh_access_token() -> tuple[str, dict[str, Any]]:
    global _refresh_token_current
    _load_store_refresh_token()
    form_data = {
        "grant_type": "refresh_token",
        "refresh_token": _refresh_token_current,
        "client_id": OAUTH_CLIENT_ID,
    }
    if OAUTH_AUDIENCE:
        form_data["audience"] = OAUTH_AUDIENCE
    if OAUTH_SCOPE:
        form_data["scope"] = OAUTH_SCOPE

    auth: tuple[str, str] | None = None
    if OAUTH_CLIENT_SECRET:
        auth = (OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(OAUTH_TOKEN_URL, data=form_data, headers=headers, auth=auth)
            resp.raise_for_status()
            payload = resp.json() if resp.content else {}

        if not isinstance(payload, dict):
            return "", {"error": "OAuth token endpoint returned non-object response"}

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return "", {"error": "OAuth refresh response missing access_token"}
        rotated_refresh = payload.get("refresh_token")
        if isinstance(rotated_refresh, str) and rotated_refresh:
            _refresh_token_current = rotated_refresh

        expires_in = payload.get("expires_in")
        try:
            ttl = int(expires_in) if expires_in is not None else 3600
        except Exception:
            ttl = 3600
        exp_claim = _decode_jwt_exp_epoch(token)
        exp_from_ttl = int(time.time()) + max(ttl, 60)
        expires_at = min(exp_claim, exp_from_ttl) if isinstance(exp_claim, int) else exp_from_ttl
        _write_store_tokens(_refresh_token_current, token, expires_at)

        return token, {
            "auth_mode": "oauth_refresh_token",
            "token_source": "refresh",
            "expires_at_epoch": expires_at,
        }
    except httpx.HTTPStatusError as exc:
        return "", {"error": f"OAuth refresh failed HTTP {exc.response.status_code}: {exc.response.text}"}
    except httpx.RequestError as exc:
        return "", {"error": f"OAuth refresh request failed: {exc}"}


async def _authenticate() -> tuple[dict[str, Any], dict[str, Any]]:
    oauth_error: str | None = None
    if _oauth_refresh_enabled():
        token, oauth_meta = await _refresh_access_token()
        if token:
            return {"headers": {"Authorization": f"Bearer {token}"}}, oauth_meta
        oauth_error = oauth_meta.get("error")
        if REQUIRE_OAUTH:
            return {}, {
                "error": oauth_error
                or "OAuth refresh-token auth required but token refresh failed"
            }
    elif REQUIRE_OAUTH:
        return {}, {
            "error": (
                "OAuth refresh-token auth required but missing "
                "PELOTON_OAUTH_CLIENT_ID and/or PELOTON_OAUTH_REFRESH_TOKEN"
            )
        }

    if BEARER_TOKEN:
        meta: dict[str, Any] = {"auth_mode": "bearer_token_env"}
        if oauth_error:
            meta["warning"] = oauth_error
        return {"headers": {"Authorization": f"Bearer {BEARER_TOKEN}"}}, meta

    if SESSION_ID:
        return {"cookies": {"peloton_session_id": SESSION_ID}}, {"auth_mode": "session_cookie_env"}

    if not USERNAME or not PASSWORD:
        if oauth_error:
            return {}, {"error": oauth_error}
        return {}, {
            "error": (
                "Set PELOTON_OAUTH_CLIENT_ID + PELOTON_OAUTH_REFRESH_TOKEN (recommended), "
                "or PELOTON_BEARER_TOKEN, or PELOTON_USERNAME/PELOTON_PASSWORD, or "
                "PELOTON_SESSION_ID"
            )
        }

    try:
        async with httpx.AsyncClient(base_url=API_BASE, headers=_headers(), timeout=TIMEOUT) as client:
            resp = await client.post(
                "/auth/login",
                json={
                    "username_or_email": USERNAME,
                    "password": PASSWORD,
                },
            )
            resp.raise_for_status()
            sid = resp.cookies.get("peloton_session_id")
            if not sid:
                body = resp.json() if resp.content else {}
                sid = body.get("session_id") if isinstance(body, dict) else ""
            if not sid:
                return {}, {"error": "Login succeeded but no session cookie was returned"}
            return {"cookies": {"peloton_session_id": sid}}, {"auth_mode": "username_password"}
    except httpx.HTTPStatusError as exc:
        return {}, {"error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except httpx.RequestError as exc:
        return {}, {"error": f"Request failed: {exc}"}


async def _request(
    auth_ctx: dict[str, Any],
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = _headers()
    headers.update(auth_ctx.get("headers", {}))
    async with httpx.AsyncClient(
        base_url=API_BASE,
        headers=headers,
        cookies=auth_ctx.get("cookies", {}),
        timeout=TIMEOUT,
    ) as client:
        resp = await client.request(method=method, url=path, params=params)
        resp.raise_for_status()
        if not resp.content:
            return {}
        payload = resp.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}


async def run_probe(start_date: str, end_date: str, sample_size: int) -> dict[str, Any]:
    auth_ctx, auth_meta = await _authenticate()
    if not auth_ctx:
        return {
            "status": "failed",
            "reason": auth_meta.get("error", "authentication failed"),
            "pass": False,
            "pass_criteria": {
                "success_rate": ">=0.90",
                "additive_metric_families": ">=4",
            },
        }

    user_id = ""
    if auth_meta.get("auth_mode") in {"bearer_token_env", "oauth_refresh_token"}:
        # Token includes user_id claim; use API /me response to get canonical profile id.
        me_payload = await _request(auth_ctx, "GET", "/api/me")
        if isinstance(me_payload, dict):
            candidate = me_payload.get("id")
            if isinstance(candidate, str) and candidate:
                user_id = candidate
    else:
        session_payload = await _request(auth_ctx, "GET", "/auth/check_session")
        user_id = _extract_user_id(session_payload)

    if not user_id:
        return {
            "status": "failed",
            "reason": "could not resolve user id",
            "pass": False,
            "auth": auth_meta,
        }

    workouts_payload = await _request(
        auth_ctx,
        "GET",
        f"/api/user/{user_id}/workouts",
        params={
            "limit": max(sample_size * 3, 30),
            "page": 0,
        },
    )
    workouts = _extract_workouts(workouts_payload)
    filtered = [row for row in workouts if (w_date := _workout_date(row)) and start_date <= w_date <= end_date]
    sample = filtered[:sample_size]

    detail_success = 0
    graph_success = 0
    detail_attempted = 0
    graph_attempted = 0

    families = {
        "cadence": False,
        "power": False,
        "resistance": False,
        "output": False,
        "class_metadata": False,
        "instructor": False,
    }

    failures: list[str] = []

    for workout in sample:
        workout_id = workout.get("id") or workout.get("workout_id")
        if not isinstance(workout_id, str) or not workout_id:
            failures.append("sample workout missing id")
            continue

        detail_attempted += 1
        try:
            detail = await _request(
                auth_ctx,
                "GET",
                f"/api/workout/{workout_id}",
                params={"joins": "ride,ride.instructor,user"},
            )
            detail_success += 1

            if _contains_any_key(detail, ("ride", "title", "class_type", "description")):
                families["class_metadata"] = True
            if _contains_any_key(detail, ("instructor", "instructor_name")):
                families["instructor"] = True
        except Exception as exc:  # pragma: no cover
            failures.append(f"detail {workout_id}: {exc}")
            detail = {}

        graph_attempted += 1
        try:
            graph = await _request(
                auth_ctx,
                "GET",
                f"/api/workout/{workout_id}/performance_graph",
                params={"every_n": 1},
            )
            graph_success += 1

            if _contains_any_key(graph, ("cadence",)):
                families["cadence"] = True
            if _contains_any_key(graph, ("power", "watts", "watt")):
                families["power"] = True
            if _contains_any_key(graph, ("resistance",)):
                families["resistance"] = True
            if _contains_any_key(graph, ("output", "kj", "kilojoule")):
                families["output"] = True
        except Exception as exc:  # pragma: no cover
            failures.append(f"graph {workout_id}: {exc}")

    detail_rate = detail_success / detail_attempted if detail_attempted else 0.0
    graph_rate = graph_success / graph_attempted if graph_attempted else 0.0
    additive_count = sum(1 for value in families.values() if value)

    gate_pass = min(detail_rate, graph_rate) >= 0.90 and additive_count >= 4

    return {
        "status": "completed",
        "auth": auth_meta,
        "window": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "counts": {
            "raw_workouts": len(workouts),
            "filtered_workouts": len(filtered),
            "sampled_workouts": len(sample),
        },
        "success_rates": {
            "detail": detail_rate,
            "performance_graph": graph_rate,
        },
        "additive_metric_families": families,
        "additive_family_count": additive_count,
        "pass_criteria": {
            "detail_and_graph_success_rate": ">= 0.90",
            "additive_metric_families": ">= 4",
        },
        "pass": gate_pass,
        "failures": failures[:30],
        "recommendation": (
            "Proceed with full peloton-mcp wrapper implementation"
            if gate_pass
            else "Do not promote peloton-mcp yet; keep Apple/Peloton via existing paths"
        ),
    }


def _default_window() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=90)
    return start.isoformat(), end.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Peloton data usefulness gate")
    default_start, default_end = _default_window()
    parser.add_argument("--start-date", default=default_start)
    parser.add_argument("--end-date", default=default_end)
    parser.add_argument("--sample-size", type=int, default=20)
    args = parser.parse_args()

    report = asyncio.run(run_probe(args.start_date, args.end_date, args.sample_size))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
