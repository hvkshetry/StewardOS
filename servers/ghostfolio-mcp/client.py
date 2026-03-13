from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

import httpx


GHOSTFOLIO_URL = os.environ.get("GHOSTFOLIO_URL", "http://localhost:3333")
GHOSTFOLIO_TOKEN = os.environ.get("GHOSTFOLIO_TOKEN", "")
ACCOUNT_TAG_MAP_ENV = "GHOSTFOLIO_ACCOUNT_TAG_MAP"
BLOCKED_MARKET_DATA_SOURCES = frozenset(
    source.strip().upper()
    for source in os.environ.get("GHOSTFOLIO_BLOCKED_MARKET_DATA_SOURCES", "").split(",")
    if source.strip()
)

VALID_RANGES = {"1d", "1w", "1m", "3m", "6m", "1y", "5y", "ytd", "max"}
VALID_ENTITY = {"personal", "trust"}
VALID_WRAPPER = {"taxable", "tax_deferred", "tax_exempt"}
VALID_ACCOUNT_TYPES = {
    "brokerage",
    "roth_ira",
    "trad_ira",
    "401k",
    "403b",
    "457b",
    "solo_401k",
    "sep_ira",
    "simple_ira",
    "hsa",
    "529",
    "esa",
    "custodial_utma",
    "custodial_ugma",
    "equity_comp",
    "trust_taxable",
    "trust_exempt",
    "trust_irrevocable",
    "trust_revocable",
    "trust_qsst",
    "other",
}
ScopeAccountType = Literal[
    "brokerage",
    "roth_ira",
    "trad_ira",
    "401k",
    "403b",
    "457b",
    "solo_401k",
    "sep_ira",
    "simple_ira",
    "hsa",
    "529",
    "esa",
    "custodial_utma",
    "custodial_ugma",
    "equity_comp",
    "trust_taxable",
    "trust_exempt",
    "trust_irrevocable",
    "trust_revocable",
    "trust_qsst",
    "other",
]
VALID_COMP_PLANS = {"rsu", "iso", "nso", "psu", "espp", "other"}
VALID_OWNER = {"Principal", "Spouse", "joint"}
ACCOUNT_UPDATE_REQUIRED_FIELDS = ("id", "name", "balance", "currency", "platformId")
TAXONOMY_TAG_KEYS = {"entity", "tax_wrapper", "account_type", "comp_plan", "owner_person", "employer_ticker"}
LEGACY_TAXONOMY_TAG_KEYS = {"owner"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if GHOSTFOLIO_TOKEN:
        headers["Authorization"] = f"Bearer {GHOSTFOLIO_TOKEN}"
    return headers


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GHOSTFOLIO_URL,
        headers=_headers(),
        timeout=30.0,
    )


def _normalize_data_source(data_source: str) -> str:
    return data_source.strip().upper()


def _required_capability_hint(method: str, path: str) -> str:
    method_upper = method.strip().upper()
    endpoint = path.strip()

    if endpoint.startswith("/api/v1/import"):
        return "admin import capability"
    if endpoint.startswith("/api/v1/export"):
        return "admin export capability"
    if endpoint.startswith("/api/v1/platform"):
        return "platform administration capability"
    if endpoint.startswith("/api/v1/account"):
        return "account management capability" if method_upper != "GET" else "account read capability"
    if endpoint.startswith("/api/v1/order"):
        return "order/activity management capability" if method_upper != "GET" else "order/activity read capability"
    if endpoint.startswith("/api/v1/portfolio"):
        return "portfolio management capability" if method_upper != "GET" else "portfolio read capability"
    if endpoint.startswith("/api/v1/market-data") or endpoint.startswith("/api/v1/symbol") or endpoint.startswith("/api/v1/asset"):
        return "market data capability"
    if endpoint.startswith("/api/v1/tags"):
        return "tag administration capability" if method_upper != "GET" else "tag read capability"
    if endpoint.startswith("/api/v1/watchlist") or endpoint.startswith("/api/v1/benchmarks"):
        return "watchlist/benchmark management capability" if method_upper != "GET" else "watchlist/benchmark read capability"

    return "write capability" if method_upper in {"POST", "PUT", "PATCH", "DELETE"} else "read capability"


def _is_blocked_market_data_source(data_source: str | None) -> bool:
    if not data_source:
        return False
    return _normalize_data_source(data_source) in BLOCKED_MARKET_DATA_SOURCES


def _blocked_market_source_message(data_source: str) -> str:
    source = _normalize_data_source(data_source)
    return (
        f"Data source '{source}' is blocked for Ghostfolio market operations by policy. "
        "Use market-intel-direct for live market data."
    )


def _symbol_resolution_error_code(message: str) -> str:
    if "blocked for Ghostfolio market operations by policy" in (message or ""):
        return "policy_blocked"
    return "symbol_resolution_error"


def _normalize_success_response(resp: httpx.Response) -> Any:
    body = resp.text.strip()
    if not body:
        return {"ok": True, "status_code": resp.status_code}

    try:
        parsed = resp.json()
    except ValueError:
        return {
            "ok": True,
            "status_code": resp.status_code,
            "text": body,
        }

    return parsed


async def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    try:
        async with _client() as client:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            return {
                "ok": True,
                "status_code": resp.status_code,
                "body": _normalize_success_response(resp),
            }
    except httpx.HTTPStatusError as exc:
        body = exc.response.text.strip() or exc.response.reason_phrase
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            capability = _required_capability_hint(method, path)
            return {
                "ok": False,
                "status_code": status_code,
                "body": None,
                "error": {
                    "code": "permission_denied",
                    "message": (
                        f"Permission denied for {method.upper()} {path}. "
                        f"Required capability: {capability}."
                    ),
                    "details": {
                        "endpoint": path,
                        "method": method.upper(),
                        "required_capability": capability,
                        "upstream_message": body,
                    },
                },
            }
        return {
            "ok": False,
            "status_code": status_code,
            "body": None,
            "error": {
                "code": "http_error",
                "message": body,
            },
        }
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": None,
            "error": {
                "code": "request_error",
                "message": str(exc),
            },
        }


def _success(
    tool: str,
    operation: str,
    method: str,
    endpoint: str,
    data: Any,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "tool": tool,
        "operation": operation,
        "as_of": _now_iso(),
        "data": data,
        "error": None,
        "provenance": {
            "method": method,
            "endpoint": endpoint,
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _failure(
    tool: str,
    operation: str,
    method: str,
    endpoint: str,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    valid_operations: list[str] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    merged_details: dict[str, Any] = details.copy() if isinstance(details, dict) else {}
    if valid_operations:
        merged_details["valid_operations"] = valid_operations
    if merged_details:
        error["details"] = merged_details

    return {
        "ok": False,
        "tool": tool,
        "operation": operation,
        "as_of": _now_iso(),
        "data": None,
        "error": error,
        "provenance": {
            "method": method,
            "endpoint": endpoint,
        },
    }


def _from_request(
    tool: str,
    operation: str,
    method: str,
    endpoint: str,
    result: dict[str, Any],
    *,
    transform: Any = None,
) -> dict[str, Any]:
    if not result.get("ok"):
        error_payload = result.get("error", {}) if isinstance(result.get("error"), dict) else {}
        merged_details: dict[str, Any] = {}
        if isinstance(error_payload.get("details"), dict):
            merged_details.update(error_payload["details"])
        if result.get("status_code") is not None:
            merged_details["status_code"] = result.get("status_code")
        return _failure(
            tool,
            operation,
            method,
            endpoint,
            code=error_payload.get("code", "request_failed"),
            message=error_payload.get("message", "Request failed."),
            details=merged_details if merged_details else None,
        )

    body = result.get("body")
    if callable(transform):
        try:
            body = transform(body)
        except Exception as exc:  # pragma: no cover - defensive
            return _failure(
                tool,
                operation,
                method,
                endpoint,
                code="response_transform_error",
                message=str(exc),
            )

    return _success(tool, operation, method, endpoint, body)


def _clean_operation(value: str) -> str:
    return (value or "").strip().lower()


def _merge_params(base: dict[str, Any] | None, extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in extra.items():
        if value is None:
            continue
        merged[key] = value
    return merged


def _extract_lookup_candidates(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    candidates: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        data_source = item.get("dataSource")
        symbol = item.get("symbol")
        name = item.get("name")
        if isinstance(data_source, str) and isinstance(symbol, str):
            candidates.append((_normalize_data_source(data_source), symbol, name if isinstance(name, str) else symbol))
    return candidates


async def _resolve_symbol_context(
    symbol: str,
    data_source: str | None = None,
    blocked_sources: set[str] | None = None,
) -> tuple[str, str] | str:
    symbol = (symbol or "").strip()
    blocked = {s.upper() for s in (blocked_sources or set()) if isinstance(s, str) and s.strip()}
    if not symbol:
        return "symbol is required"

    if data_source:
        source = _normalize_data_source(data_source)
        if source in blocked:
            return _blocked_market_source_message(source)
        return (source, symbol)

    lookup_payload = await _request(
        "GET",
        "/api/v1/symbol/lookup",
        params={"query": symbol},
    )
    if not lookup_payload.get("ok"):
        return (
            "Symbol lookup failed: "
            + str(lookup_payload.get("error", {}).get("message", "unknown error"))
        )

    body = lookup_payload.get("body")
    candidates = _extract_lookup_candidates(body if isinstance(body, dict) else {})
    allowed_candidates = [entry for entry in candidates if entry[0] not in blocked]
    exact = [entry for entry in allowed_candidates if entry[1].lower() == symbol.lower()]

    if candidates and not allowed_candidates:
        blocked_values = ", ".join(sorted({source for source, _, _ in candidates if source in blocked}))
        return (
            "Symbol candidates exist but only in blocked data sources "
            f"({blocked_values}). Use market-intel-direct for live market data."
        )

    if len(exact) == 1:
        source, resolved_symbol, _ = exact[0]
        return (source, resolved_symbol)

    if len(exact) > 1:
        values = ", ".join(f"{source}:{sym}" for source, sym, _ in exact[:5])
        return (
            "Ambiguous symbol resolution. Provide data_source explicitly. "
            f"Matching candidates: {values}"
        )

    if allowed_candidates:
        preview = ", ".join(f"{source}:{sym}" for source, sym, _ in allowed_candidates[:5])
        return (
            "No exact symbol match found in Ghostfolio lookup. "
            f"Closest candidates: {preview}. Provide data_source and exact symbol."
        )

    for source in ("COINGECKO", "YAHOO"):
        if source in blocked:
            continue
        probe = await _request(
            "GET",
            f"/api/v1/symbol/{source}/{symbol}",
            params={"includeHistoricalData": 0},
        )
        if probe.get("ok"):
            return (source, symbol)

    return "No symbol candidates returned by Ghostfolio lookup."


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
