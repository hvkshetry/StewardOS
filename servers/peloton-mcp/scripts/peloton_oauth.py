#!/usr/bin/env python3
"""Helpers for Peloton Authorization Code + PKCE and token refresh."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

DEFAULT_AUTH_URL = "https://auth.onepeloton.com/authorize"
DEFAULT_TOKEN_URL = "https://auth.onepeloton.com/oauth/token"
DEFAULT_AUDIENCE = "https://api.onepeloton.com/"
DEFAULT_SCOPE = "openid offline_access"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _make_code_verifier(size_bytes: int = 64) -> str:
    # PKCE verifier must be between 43 and 128 chars.
    verifier = _b64url(secrets.token_bytes(size_bytes))
    if len(verifier) < 43:
        verifier += "A" * (43 - len(verifier))
    return verifier[:128]


def _make_code_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())


def cmd_start_pkce(args: argparse.Namespace) -> None:
    verifier = args.code_verifier or _make_code_verifier()
    state = args.state or secrets.token_urlsafe(24)
    challenge = _make_code_challenge(verifier)

    query = {
        "client_id": args.client_id,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "scope": args.scope,
        "audience": args.audience,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    authorize_url = f"{args.auth_url}?{urlencode(query)}"
    print(
        json.dumps(
            {
                "authorize_url": authorize_url,
                "code_verifier": verifier,
                "code_challenge": challenge,
                "state": state,
                "next_step": (
                    "Open authorize_url in browser, complete login, then run exchange-code "
                    "with returned code and this code_verifier."
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _post_token(
    token_url: str,
    payload: dict[str, Any],
    client_id: str,
    client_secret: str,
    timeout_sec: float,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    auth = (client_id, client_secret) if client_secret else None
    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(token_url, data=payload, headers=headers, auth=auth)
        resp.raise_for_status()
        out = resp.json() if resp.content else {}
    if not isinstance(out, dict):
        raise RuntimeError("Token endpoint returned non-object response")
    return out


def _maybe_write_store(
    token_store_path: str,
    token_response: dict[str, Any],
) -> None:
    if not token_store_path:
        return
    refresh_token = token_response.get("refresh_token")
    access_token = token_response.get("access_token")
    expires_in = token_response.get("expires_in")
    if not isinstance(refresh_token, str) or not refresh_token:
        return
    if not isinstance(access_token, str) or not access_token:
        return
    try:
        ttl = int(expires_in) if expires_in is not None else 3600
    except Exception:
        ttl = 3600
    payload = {
        "refresh_token": refresh_token,
        "access_token": access_token,
        "expires_at_epoch": int(time.time()) + max(ttl, 60),
        "updated_at_epoch": int(time.time()),
    }
    path = Path(token_store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def cmd_exchange_code(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "grant_type": "authorization_code",
        "client_id": args.client_id,
        "code": args.code,
        "code_verifier": args.code_verifier,
        "redirect_uri": args.redirect_uri,
    }
    if args.audience:
        payload["audience"] = args.audience

    out = _post_token(args.token_url, payload, args.client_id, args.client_secret, args.timeout_sec)
    _maybe_write_store(args.token_store_path, out)
    print(json.dumps(out, indent=2, sort_keys=True))


def cmd_refresh_token(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "grant_type": "refresh_token",
        "client_id": args.client_id,
        "refresh_token": args.refresh_token,
    }
    if args.audience:
        payload["audience"] = args.audience
    if args.scope:
        payload["scope"] = args.scope

    out = _post_token(args.token_url, payload, args.client_id, args.client_secret, args.timeout_sec)
    _maybe_write_store(args.token_store_path, out)
    print(json.dumps(out, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Peloton OAuth helpers")
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start-pkce", help="Generate PKCE verifier/challenge and authorize URL")
    start.add_argument("--client-id", required=True)
    start.add_argument("--redirect-uri", required=True)
    start.add_argument("--auth-url", default=DEFAULT_AUTH_URL)
    start.add_argument("--audience", default=DEFAULT_AUDIENCE)
    start.add_argument("--scope", default=DEFAULT_SCOPE)
    start.add_argument("--state", default="")
    start.add_argument("--code-verifier", default="")
    start.set_defaults(func=cmd_start_pkce)

    exchange = sub.add_parser("exchange-code", help="Exchange auth code + verifier for tokens")
    exchange.add_argument("--client-id", required=True)
    exchange.add_argument("--client-secret", default="")
    exchange.add_argument("--redirect-uri", required=True)
    exchange.add_argument("--code", required=True)
    exchange.add_argument("--code-verifier", required=True)
    exchange.add_argument("--token-url", default=DEFAULT_TOKEN_URL)
    exchange.add_argument("--audience", default=DEFAULT_AUDIENCE)
    exchange.add_argument("--token-store-path", default="")
    exchange.set_defaults(func=cmd_exchange_code)

    refresh = sub.add_parser("refresh-token", help="Refresh access token using refresh token")
    refresh.add_argument("--client-id", required=True)
    refresh.add_argument("--client-secret", default="")
    refresh.add_argument("--refresh-token", required=True)
    refresh.add_argument("--token-url", default=DEFAULT_TOKEN_URL)
    refresh.add_argument("--audience", default=DEFAULT_AUDIENCE)
    refresh.add_argument("--scope", default=DEFAULT_SCOPE)
    refresh.add_argument("--token-store-path", default="")
    refresh.set_defaults(func=cmd_refresh_token)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
