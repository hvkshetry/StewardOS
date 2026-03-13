"""MCP server for read-only Peloton workout access."""

import asyncio
import base64
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


PELOTON_API_BASE_URL = os.environ.get("PELOTON_API_BASE_URL", "https://api.onepeloton.com")
PELOTON_BEARER_TOKEN = os.environ.get("PELOTON_BEARER_TOKEN", "")
PELOTON_OAUTH_CLIENT_ID = os.environ.get("PELOTON_OAUTH_CLIENT_ID", "")
PELOTON_OAUTH_CLIENT_SECRET = os.environ.get("PELOTON_OAUTH_CLIENT_SECRET", "")
PELOTON_OAUTH_REFRESH_TOKEN = os.environ.get("PELOTON_OAUTH_REFRESH_TOKEN", "")
PELOTON_OAUTH_TOKEN_URL = os.environ.get(
    "PELOTON_OAUTH_TOKEN_URL", "https://auth.onepeloton.com/oauth/token"
)
PELOTON_OAUTH_AUDIENCE = os.environ.get("PELOTON_OAUTH_AUDIENCE", "https://api.onepeloton.com/")
PELOTON_OAUTH_SCOPE = os.environ.get("PELOTON_OAUTH_SCOPE", "openid offline_access")
PELOTON_OAUTH_REFRESH_SKEW_SEC = int(os.environ.get("PELOTON_OAUTH_REFRESH_SKEW_SEC", "60"))
PELOTON_OAUTH_TOKEN_STORE_PATH = os.environ.get("PELOTON_OAUTH_TOKEN_STORE_PATH", "").strip()
PELOTON_REQUIRE_OAUTH = os.environ.get("PELOTON_REQUIRE_OAUTH", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
PELOTON_USERNAME = os.environ.get("PELOTON_USERNAME", "")
PELOTON_PASSWORD = os.environ.get("PELOTON_PASSWORD", "")
PELOTON_SESSION_ID = os.environ.get("PELOTON_SESSION_ID", "")
PELOTON_PLATFORM = os.environ.get("PELOTON_PLATFORM", "web")
PELOTON_TIMEOUT_SEC = float(os.environ.get("PELOTON_TIMEOUT_SEC", "30"))

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP(
    "peloton-mcp",
    instructions=(
        "Read-only Peloton data connector. Provides workout list, workout detail, "
        "performance graph, and ride/class metadata. Uses unofficial Peloton API."
    ),
)

_oauth_token_lock = asyncio.Lock()
_oauth_token_cache: dict[str, Any] = {
    "access_token": "",
    "expires_at_epoch": 0,
}
_oauth_refresh_token_current = PELOTON_OAUTH_REFRESH_TOKEN
_oauth_store_loaded = False


def _load_oauth_store_once() -> None:
    global _oauth_store_loaded, _oauth_refresh_token_current
    if _oauth_store_loaded:
        return
    _oauth_store_loaded = True
    if not PELOTON_OAUTH_TOKEN_STORE_PATH:
        return
    try:
        path = Path(PELOTON_OAUTH_TOKEN_STORE_PATH)
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
        stored_refresh = payload.get("refresh_token")
        if isinstance(stored_refresh, str) and stored_refresh:
            _oauth_refresh_token_current = stored_refresh
        stored_access = payload.get("access_token")
        stored_exp = payload.get("expires_at_epoch")
        if isinstance(stored_access, str) and stored_access and isinstance(stored_exp, int):
            _oauth_token_cache["access_token"] = stored_access
            _oauth_token_cache["expires_at_epoch"] = stored_exp
    except Exception:
        # Ignore token-store read issues; env fallback remains available.
        return


def _write_oauth_store(payload: dict[str, Any]) -> None:
    if not PELOTON_OAUTH_TOKEN_STORE_PATH:
        return
    try:
        path = Path(PELOTON_OAUTH_TOKEN_STORE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, separators=(",", ":"))
        path.write_text(serialized, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        # Do not fail auth flow for persistence errors.
        return


def _base_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "peloton-platform": PELOTON_PLATFORM,
    }


def _extract_session_id_from_response(resp: httpx.Response) -> str:
    sid = resp.cookies.get("peloton_session_id")
    if sid:
        return sid
    payload = resp.json() if resp.content else {}
    if isinstance(payload, dict):
        maybe = payload.get("session_id")
        if isinstance(maybe, str) and maybe:
            return maybe
    return ""


def _oauth_refresh_enabled() -> bool:
    _load_oauth_store_once()
    return bool(PELOTON_OAUTH_CLIENT_ID and _oauth_refresh_token_current)


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


async def _get_oauth_access_token() -> tuple[str, dict[str, Any]]:
    global _oauth_refresh_token_current
    _load_oauth_store_once()
    now = int(time.time())
    cached_token = _oauth_token_cache.get("access_token")
    cached_exp = int(_oauth_token_cache.get("expires_at_epoch") or 0)
    if isinstance(cached_token, str) and cached_token and cached_exp - now > PELOTON_OAUTH_REFRESH_SKEW_SEC:
        return cached_token, {
            "auth_mode": "oauth_refresh_token",
            "token_source": "cache",
            "expires_at_epoch": cached_exp,
        }

    async with _oauth_token_lock:
        now = int(time.time())
        cached_token = _oauth_token_cache.get("access_token")
        cached_exp = int(_oauth_token_cache.get("expires_at_epoch") or 0)
        if isinstance(cached_token, str) and cached_token and cached_exp - now > PELOTON_OAUTH_REFRESH_SKEW_SEC:
            return cached_token, {
                "auth_mode": "oauth_refresh_token",
                "token_source": "cache",
                "expires_at_epoch": cached_exp,
            }

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": _oauth_refresh_token_current,
            "client_id": PELOTON_OAUTH_CLIENT_ID,
        }
        if PELOTON_OAUTH_AUDIENCE:
            form_data["audience"] = PELOTON_OAUTH_AUDIENCE
        if PELOTON_OAUTH_SCOPE:
            form_data["scope"] = PELOTON_OAUTH_SCOPE

        auth: tuple[str, str] | None = None
        if PELOTON_OAUTH_CLIENT_SECRET:
            # Confidential client flow.
            auth = (PELOTON_OAUTH_CLIENT_ID, PELOTON_OAUTH_CLIENT_SECRET)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            async with httpx.AsyncClient(timeout=PELOTON_TIMEOUT_SEC) as client:
                resp = await client.post(
                    PELOTON_OAUTH_TOKEN_URL,
                    data=form_data,
                    headers=headers,
                    auth=auth,
                )
                resp.raise_for_status()
                payload = resp.json() if resp.content else {}

            if not isinstance(payload, dict):
                return "", {"error": "OAuth token endpoint returned non-object response"}

            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                return "", {"error": "OAuth refresh response missing access_token"}
            rotated_refresh = payload.get("refresh_token")
            if isinstance(rotated_refresh, str) and rotated_refresh:
                _oauth_refresh_token_current = rotated_refresh

            expires_in = payload.get("expires_in")
            try:
                ttl = int(expires_in) if expires_in is not None else 3600
            except Exception:
                ttl = 3600

            exp_claim = _decode_jwt_exp_epoch(token)
            exp_from_ttl = int(time.time()) + max(ttl, 60)
            expires_at = min(exp_claim, exp_from_ttl) if isinstance(exp_claim, int) else exp_from_ttl

            _oauth_token_cache["access_token"] = token
            _oauth_token_cache["expires_at_epoch"] = expires_at
            _write_oauth_store(
                {
                    "refresh_token": _oauth_refresh_token_current,
                    "access_token": token,
                    "expires_at_epoch": expires_at,
                    "updated_at_epoch": int(time.time()),
                }
            )

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
        token, oauth_meta = await _get_oauth_access_token()
        if token:
            return {"headers": {"Authorization": f"Bearer {token}"}}, oauth_meta
        oauth_error = oauth_meta.get("error")
        if PELOTON_REQUIRE_OAUTH:
            return {}, {
                "error": oauth_error
                or "OAuth refresh-token auth required but token refresh failed"
            }
    elif PELOTON_REQUIRE_OAUTH:
        return {}, {
            "error": (
                "OAuth refresh-token auth required but missing "
                "PELOTON_OAUTH_CLIENT_ID and/or PELOTON_OAUTH_REFRESH_TOKEN"
            )
        }

    if PELOTON_BEARER_TOKEN:
        meta: dict[str, Any] = {"auth_mode": "bearer_token_env"}
        if oauth_error:
            meta["warning"] = oauth_error
        return {"headers": {"Authorization": f"Bearer {PELOTON_BEARER_TOKEN}"}}, meta

    if PELOTON_SESSION_ID:
        return {"cookies": {"peloton_session_id": PELOTON_SESSION_ID}}, {
            "auth_mode": "session_cookie_env"
        }

    if not PELOTON_USERNAME or not PELOTON_PASSWORD:
        if oauth_error:
            return {}, {"error": oauth_error}
        return {}, {
            "error": (
                "Missing credentials. Set PELOTON_OAUTH_CLIENT_ID + PELOTON_OAUTH_REFRESH_TOKEN "
                "(recommended), or PELOTON_BEARER_TOKEN, or PELOTON_USERNAME/PELOTON_PASSWORD, "
                "or PELOTON_SESSION_ID"
            )
        }

    try:
        async with httpx.AsyncClient(
            base_url=PELOTON_API_BASE_URL,
            headers=_base_headers(),
            timeout=PELOTON_TIMEOUT_SEC,
        ) as client:
            resp = await client.post(
                "/auth/login",
                json={
                    "username_or_email": PELOTON_USERNAME,
                    "password": PELOTON_PASSWORD,
                },
            )
            resp.raise_for_status()
            sid = _extract_session_id_from_response(resp)
            if not sid:
                return {}, {
                    "error": "Login succeeded but no peloton_session_id was returned"
                }

            body = resp.json() if resp.content else {}
            profile = body.get("user_data") if isinstance(body, dict) else None
            out = {
                "auth_mode": "username_password",
                "profile_id": profile.get("id") if isinstance(profile, dict) else None,
            }
            return {"cookies": {"peloton_session_id": sid}}, out
    except httpx.HTTPStatusError as exc:
        return {}, {
            "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
        }
    except httpx.RequestError as exc:
        return {}, {"error": f"Request failed: {exc}"}


async def _authed_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    auth_ctx, auth_meta = await _authenticate()
    if not auth_ctx:
        return auth_meta.get("error", "Authentication failed")

    try:
        headers = _base_headers()
        headers.update(auth_ctx.get("headers", {}))
        async with httpx.AsyncClient(
            base_url=PELOTON_API_BASE_URL,
            headers=headers,
            cookies=auth_ctx.get("cookies", {}),
            timeout=PELOTON_TIMEOUT_SEC,
        ) as client:
            resp = await client.request(method=method, url=path, params=params, json=json_body)
            resp.raise_for_status()
            payload = resp.json() if resp.content else {}
            if isinstance(payload, dict):
                payload["_auth"] = auth_meta
                return payload
            return {
                "data": payload,
                "_auth": auth_meta,
            }
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


def _extract_user_id(payload: dict[str, Any]) -> str:
    for key in ("id", "user_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_workouts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "workouts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _workout_date_value(workout: dict[str, Any]) -> str | int | float:
    for key in (
        "created",
        "created_at",
        "created_at_ts",
        "start_time",
        "start_time_utc",
        "start",
        "startDate",
    ):
        value = workout.get(key)
        if isinstance(value, (str, int, float)) and value:
            return value
    return ""


def _as_date(value: Any) -> str:
    if not value:
        return ""
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            # Peloton endpoints return unix seconds; allow millis defensively.
            if ts > 1_000_000_000_000:
                ts = ts / 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.date().isoformat()

        if not isinstance(value, str):
            return ""

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        return dt.date().isoformat()
    except Exception:
        return value[:10] if isinstance(value, str) else ""


async def _resolve_user_id(auth_meta: dict[str, Any]) -> tuple[str, str | None]:
    if auth_meta.get("auth_mode") in {"bearer_token_env", "oauth_refresh_token"}:
        me_result = await _authed_request("GET", "/api/me")
        if isinstance(me_result, str):
            return "", me_result
        return _extract_user_id(me_result if isinstance(me_result, dict) else {}), None

    session_result = await _authed_request("GET", "/auth/check_session")
    if isinstance(session_result, str):
        return "", session_result
    udata = session_result.get("user_data") if isinstance(session_result, dict) else {}
    return _extract_user_id(udata if isinstance(udata, dict) else {}), None


@mcp.tool()
async def peloton_auth_diagnostics() -> dict[str, Any]:
    """Validate Peloton auth configuration and resolve current user."""
    auth_ctx, auth_meta = await _authenticate()
    if not auth_ctx:
        return {
            "ok": False,
            "error": auth_meta.get("error", "Authentication failed"),
        }

    user_id, resolve_error = await _resolve_user_id(auth_meta)
    if resolve_error:
        return {
            "ok": False,
            "error": resolve_error,
            "auth": auth_meta,
        }

    return {
        "ok": bool(user_id),
        "auth": auth_meta,
        "user_id": user_id or None,
        "today": date.today().isoformat(),
    }


@mcp.tool()
async def peloton_get_workouts(
    start_date: str,
    end_date: str,
    limit: int = 50,
    page: int = 0,
    user_id: str = "",
) -> dict[str, Any] | str:
    """Fetch Peloton workouts in a date range.

    Args:
        start_date: YYYY-MM-DD inclusive
        end_date: YYYY-MM-DD inclusive
        limit: page size
        page: page index
        user_id: optional Peloton user ID; auto-resolved if omitted
    """
    resolved_user_id = user_id
    if not resolved_user_id:
        auth_ctx, auth_meta = await _authenticate()
        if not auth_ctx:
            return auth_meta.get("error", "Authentication failed")
        resolved_user_id, resolve_error = await _resolve_user_id(auth_meta)
        if resolve_error:
            return resolve_error
        if not resolved_user_id:
            return "Unable to resolve user_id from authentication context"

    raw = await _authed_request(
        "GET",
        f"/api/user/{resolved_user_id}/workouts",
        params={
            "page": page,
            "limit": limit,
        },
    )
    if isinstance(raw, str):
        return raw

    workouts = _extract_workouts(raw)
    filtered: list[dict[str, Any]] = []
    for item in workouts:
        w_date = _as_date(_workout_date_value(item))
        if not w_date:
            filtered.append(item)
            continue
        if start_date <= w_date <= end_date:
            filtered.append(item)

    return {
        "user_id": resolved_user_id,
        "start_date": start_date,
        "end_date": end_date,
        "page": page,
        "limit": limit,
        "raw_count": len(workouts),
        "filtered_count": len(filtered),
        "workouts": filtered,
    }


@mcp.tool()
async def peloton_get_workout_detail(
    workout_id: str,
    joins: str = "ride,ride.instructor,user",
) -> dict[str, Any] | str:
    """Fetch one Peloton workout detail payload."""
    return await _authed_request(
        "GET",
        f"/api/workout/{workout_id}",
        params={"joins": joins},
    )


@mcp.tool()
async def peloton_get_performance_graph(
    workout_id: str,
    every_n_seconds: int = 1,
) -> dict[str, Any] | str:
    """Fetch time-series performance graph for a workout."""
    return await _authed_request(
        "GET",
        f"/api/workout/{workout_id}/performance_graph",
        params={"every_n": every_n_seconds},
    )


@mcp.tool()
async def peloton_get_class_metadata(ride_id: str) -> dict[str, Any] | str:
    """Fetch class/ride metadata including instructor and class attributes."""
    return await _authed_request("GET", f"/api/ride/{ride_id}/details")


if __name__ == "__main__":
    mcp.run()
