"""MCP server for Ghostfolio with a consolidated, operation-based tool surface."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP


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
ACCOUNT_UPDATE_REQUIRED_FIELDS = ("id", "name", "balance", "currency", "platformId")
TAXONOMY_TAG_KEYS = {"entity", "tax_wrapper", "account_type", "comp_plan"}


mcp = FastMCP(
    "ghostfolio-mcp",
    instructions=(
        "Ghostfolio consolidated MCP server. Exposes operation-based tools for account, "
        "portfolio, order, market, reference, and system endpoints with taxonomy helpers."
    ),
)


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


# ---------- Taxonomy helpers ----------

def _load_env_account_tag_map() -> dict[str, list[str]]:
    raw = os.getenv(ACCOUNT_TAG_MAP_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, list):
            tags = [str(v).strip().lower() for v in value if str(v).strip()]
            normalized[key] = tags
    return normalized


def _parse_comment_tags(comment: str | None) -> list[str]:
    if not comment:
        return []
    parts = re.split(r"[;,\s]+", comment)
    return [p.strip().lower() for p in parts if ":" in p.strip()]


def _strip_taxonomy_tokens(comment: str | None) -> str:
    if not isinstance(comment, str):
        return ""
    raw_tokens = re.split(r"\s+", comment.strip())
    kept: list[str] = []
    for token in raw_tokens:
        candidate = token.strip().strip(",;").lower()
        if ":" in candidate:
            key = candidate.split(":", 1)[0]
            if key in TAXONOMY_TAG_KEYS:
                continue
        kept.append(token)
    return " ".join(kept).strip()


def _build_taxonomy_comment(
    entity: str,
    tax_wrapper: str,
    account_type: str,
    comp_plan: str | None,
    existing_comment: str | None,
    preserve_existing_comment: bool,
) -> str:
    taxonomy = f"entity:{entity} tax_wrapper:{tax_wrapper} account_type:{account_type}"
    if comp_plan:
        taxonomy = f"{taxonomy} comp_plan:{comp_plan}"
    if not preserve_existing_comment:
        return taxonomy
    preserved = _strip_taxonomy_tokens(existing_comment)
    return f"{preserved} {taxonomy}".strip() if preserved else taxonomy


def _extract_account_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("id"), str):
        return payload
    if isinstance(payload, dict):
        nested = payload.get("account")
        if isinstance(nested, dict) and isinstance(nested.get("id"), str):
            return nested
        items = payload.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            if isinstance(items[0].get("id"), str):
                return items[0]
    return None


def _build_account_update_payload(account: dict[str, Any], comment: str) -> dict[str, Any] | str:
    missing = [field for field in ACCOUNT_UPDATE_REQUIRED_FIELDS if field not in account]
    if missing:
        return "Account payload missing required update fields: " + ", ".join(sorted(missing))

    account_id = account.get("id")
    name = account.get("name")
    balance = account.get("balance")
    currency = account.get("currency")
    platform_id = account.get("platformId")

    if not isinstance(account_id, str) or not account_id.strip():
        return "Account field 'id' must be a non-empty string."
    if not isinstance(name, str) or not name.strip():
        return "Account field 'name' must be a non-empty string."
    if not isinstance(currency, str) or not currency.strip():
        return "Account field 'currency' must be a non-empty string."
    if not isinstance(balance, (int, float)):
        return "Account field 'balance' must be numeric."
    if platform_id is not None and not isinstance(platform_id, str):
        return "Account field 'platformId' must be null or string."

    payload: dict[str, Any] = {
        "id": account_id,
        "name": name,
        "balance": balance,
        "currency": currency,
        "platformId": platform_id,
        "comment": comment,
    }

    is_excluded = account.get("isExcluded")
    if isinstance(is_excluded, bool):
        payload["isExcluded"] = is_excluded

    return payload


def _extract_account_id(account: dict[str, Any]) -> str:
    for key in ("id", "accountId", "account_id"):
        value = account.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_account_tags(account: dict[str, Any], env_map: dict[str, list[str]]) -> list[str]:
    tag_set: set[str] = set()

    tags = account.get("tags")
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, str) and ":" in item:
                tag_set.add(item.strip().lower())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and ":" in name:
                    tag_set.add(name.strip().lower())

    comment = account.get("comment")
    if isinstance(comment, str):
        for token in _parse_comment_tags(comment):
            tag_set.add(token)

    account_id = _extract_account_id(account)
    if account_id and account_id in env_map:
        for token in env_map[account_id]:
            if ":" in token:
                tag_set.add(token)

    return sorted(tag_set)


def _classify_account_tags(tags: list[str]) -> dict[str, Any]:
    entity = None
    wrapper = None
    account_type = None
    comp_plan = None
    errors: list[str] = []

    for tag in tags:
        if not isinstance(tag, str) or ":" not in tag:
            continue
        key, value = tag.split(":", 1)
        key = key.strip().lower()
        value = value.strip().lower()
        if key == "entity":
            entity = value
        elif key == "tax_wrapper":
            wrapper = value
        elif key == "account_type":
            account_type = value
        elif key == "comp_plan":
            comp_plan = value

    if entity not in VALID_ENTITY:
        errors.append("missing_or_invalid_entity_tag")
    if wrapper not in VALID_WRAPPER:
        errors.append("missing_or_invalid_tax_wrapper_tag")
    if account_type not in VALID_ACCOUNT_TYPES:
        errors.append("missing_or_invalid_account_type_tag")
    if comp_plan is not None and comp_plan not in VALID_COMP_PLANS:
        errors.append("invalid_comp_plan_tag")
    if account_type == "equity_comp" and comp_plan not in VALID_COMP_PLANS:
        errors.append("missing_or_invalid_comp_plan_tag_for_equity_comp")

    return {
        "entity": entity,
        "tax_wrapper": wrapper,
        "account_type": account_type,
        "comp_plan": comp_plan,
        "valid": len(errors) == 0,
        "errors": errors,
    }


def _classification_summary(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(accounts)
    invalid = sum(1 for a in accounts if not a.get("classification", {}).get("valid", False))

    by_entity: dict[str, int] = {}
    by_wrapper: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_comp_plan: dict[str, int] = {}

    for account in accounts:
        c = account.get("classification", {})
        entity = c.get("entity")
        wrapper = c.get("tax_wrapper")
        account_type = c.get("account_type")
        comp_plan = c.get("comp_plan")
        if isinstance(entity, str):
            by_entity[entity] = by_entity.get(entity, 0) + 1
        if isinstance(wrapper, str):
            by_wrapper[wrapper] = by_wrapper.get(wrapper, 0) + 1
        if isinstance(account_type, str):
            by_type[account_type] = by_type.get(account_type, 0) + 1
        if isinstance(comp_plan, str):
            by_comp_plan[comp_plan] = by_comp_plan.get(comp_plan, 0) + 1

    return {
        "total_accounts": total,
        "valid_accounts": total - invalid,
        "invalid_accounts": invalid,
        "by_entity": by_entity,
        "by_tax_wrapper": by_wrapper,
        "by_account_type": by_type,
        "by_comp_plan": by_comp_plan,
    }


def _normalize_scope_list(scope_account_types: list[ScopeAccountType] | None) -> set[str] | None:
    if scope_account_types is None:
        return None
    if not isinstance(scope_account_types, list):
        raise ValueError("scope_account_types must be a list of account type codes.")

    cleaned = [str(s).strip().lower() for s in scope_account_types if str(s).strip()]
    if not cleaned:
        return None

    invalid = sorted({value for value in cleaned if value not in VALID_ACCOUNT_TYPES})
    if invalid:
        allowed = ", ".join(sorted(VALID_ACCOUNT_TYPES))
        raise ValueError(
            f"scope_account_types contains invalid values: {', '.join(invalid)}. "
            f"Allowed values: {allowed}"
        )

    return set(cleaned)


def _matches_scope(
    classification: dict[str, Any],
    scope_entity: str,
    scope_wrapper: str,
    scope_account_types: set[str] | None,
) -> bool:
    entity = classification.get("entity")
    wrapper = classification.get("tax_wrapper")
    account_type = classification.get("account_type")

    if scope_entity != "all" and entity != scope_entity:
        return False
    if scope_wrapper != "all" and wrapper != scope_wrapper:
        return False
    if scope_account_types is not None and account_type not in scope_account_types:
        return False
    return True


async def _get_accounts_raw() -> dict[str, Any]:
    result = await _request("GET", "/api/v1/account")
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", {}),
            "status_code": result.get("status_code"),
            "accounts": [],
        }

    body = result.get("body")
    accounts: list[dict[str, Any]] = []
    if isinstance(body, dict) and isinstance(body.get("accounts"), list):
        accounts = [a for a in body["accounts"] if isinstance(a, dict)]
    elif isinstance(body, dict) and isinstance(body.get("items"), list):
        accounts = [a for a in body["items"] if isinstance(a, dict)]
    elif isinstance(body, list):
        accounts = [a for a in body if isinstance(a, dict)]

    return {
        "ok": True,
        "accounts": accounts,
    }


async def _get_accounts_with_classification(strict: bool = False) -> dict[str, Any]:
    raw = await _get_accounts_raw()
    if not raw.get("ok"):
        return {
            "ok": False,
            "error": raw.get("error", {}),
            "status_code": raw.get("status_code"),
            "accounts": [],
            "summary": {
                "total_accounts": 0,
                "valid_accounts": 0,
                "invalid_accounts": 0,
            },
            "invalid_accounts": [],
        }

    env_map = _load_env_account_tag_map()
    accounts: list[dict[str, Any]] = []
    invalid_accounts: list[dict[str, Any]] = []

    for account in raw.get("accounts", []):
        account_id = _extract_account_id(account)
        tags = _extract_account_tags(account, env_map)
        classification = _classify_account_tags(tags)
        enriched = {
            **account,
            "account_id": account_id,
            "classification_tags": tags,
            "classification": classification,
        }
        accounts.append(enriched)
        if not classification.get("valid", False):
            invalid_accounts.append(
                {
                    "account_id": account_id,
                    "name": account.get("name"),
                    "errors": classification.get("errors", []),
                    "tags": tags,
                }
            )

    summary = _classification_summary(accounts)
    ok = (not strict) or len(invalid_accounts) == 0

    return {
        "ok": ok,
        "accounts": accounts,
        "summary": summary,
        "invalid_accounts": invalid_accounts,
        "taxonomy": {
            "required_tags": [
                "entity:personal|trust",
                "tax_wrapper:taxable|tax_deferred|tax_exempt",
                "account_type:brokerage|roth_ira|trad_ira|401k|403b|457b|solo_401k|sep_ira|simple_ira|hsa|529|esa|custodial_utma|custodial_ugma|equity_comp|trust_taxable|trust_exempt|trust_irrevocable|trust_revocable|trust_qsst|other",
                "comp_plan:rsu|iso|nso|psu|espp|other (required if account_type:equity_comp)",
            ]
        },
    }


def _extract_holding_account_id(holding: dict[str, Any]) -> str | None:
    for key in ("accountId", "account_id", "account"):
        value = holding.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("accountId")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _holding_symbol(row: dict[str, Any]) -> str:
    symbol = row.get("symbol") or row.get("ticker")
    if not isinstance(symbol, str):
        return ""
    return symbol.strip().upper()


def _holding_value(row: dict[str, Any]) -> float:
    for key in ("valueInBaseCurrency", "value", "marketValue", "currentValue"):
        value = _to_float(row.get(key), default=float("nan"))
        if value == value:  # NaN check
            return value
    quantity = _to_float(row.get("quantity", row.get("shares", 0.0)), 0.0)
    market_price = _to_float(row.get("marketPrice", row.get("price", 0.0)), 0.0)
    return quantity * market_price


def _extract_activity_account_id(activity: dict[str, Any]) -> str | None:
    for key in ("accountId", "account_id", "account"):
        value = activity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("accountId")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _extract_activity_symbol(activity: dict[str, Any]) -> str:
    for key in ("symbol", "ticker"):
        value = activity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    profile = activity.get("SymbolProfile") or activity.get("symbolProfile")
    if isinstance(profile, dict):
        symbol = profile.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip().upper()
    return ""


def _extract_activity_data_source(activity: dict[str, Any]) -> str | None:
    profile = activity.get("SymbolProfile") or activity.get("symbolProfile")
    if isinstance(profile, dict):
        source = profile.get("dataSource")
        if isinstance(source, str) and source.strip():
            return source.strip().upper()
    source = activity.get("dataSource")
    if isinstance(source, str) and source.strip():
        return source.strip().upper()
    return None


def _activity_trade_sign(activity_type: str, quantity: float) -> int:
    t = (activity_type or "").strip().upper()
    if t in {"SELL", "WITHDRAWAL", "CASH_OUT", "DELIVERY_OUT"}:
        return -1
    if t in {"BUY", "DEPOSIT", "CASH_IN", "DELIVERY_IN"}:
        return 1
    if quantity < 0:
        return -1
    return 1


def _build_holdings_symbol_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _holding_symbol(row)
        if not symbol:
            continue
        entry = out.setdefault(
            symbol,
            {
                "value": 0.0,
                "quantity": 0.0,
                "assetClass": row.get("assetClass"),
                "assetSubClass": row.get("assetSubClass"),
                "currency": row.get("currency"),
                "dataSource": row.get("dataSource"),
                "marketPrice": 0.0,
            },
        )
        entry["value"] += max(_holding_value(row), 0.0)
        entry["quantity"] += max(_to_float(row.get("quantity", row.get("shares", 0.0)), 0.0), 0.0)
        market_price = _to_float(row.get("marketPrice"), 0.0)
        if market_price > 0:
            entry["marketPrice"] = market_price
    for payload in out.values():
        if payload.get("marketPrice", 0.0) <= 0:
            qty = _to_float(payload.get("quantity"), 0.0)
            value = _to_float(payload.get("value"), 0.0)
            payload["marketPrice"] = (value / qty) if qty > 0 else 0.0
    return out


# ---------- Symbol resolution helpers ----------

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


def _extract_lookup_symbol_profile_id(payload: dict[str, Any], source: str, symbol: str) -> str | None:
    items = payload.get("items")
    if not isinstance(items, list):
        return None

    source_norm = _normalize_data_source(source)
    symbol_norm = symbol.strip().lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        data_source = item.get("dataSource")
        item_symbol = item.get("symbol")
        if not isinstance(data_source, str) or not isinstance(item_symbol, str):
            continue
        if _normalize_data_source(data_source) != source_norm or item_symbol.strip().lower() != symbol_norm:
            continue
        profile_id = item.get("symbolProfileId") or item.get("id")
        if isinstance(profile_id, str) and profile_id.strip():
            return profile_id.strip()
    return None


def _find_existing_benchmark(payload: Any, source: str, symbol: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, list):
        return None

    source_norm = _normalize_data_source(source)
    symbol_norm = symbol.strip().lower()
    for benchmark in benchmarks:
        if not isinstance(benchmark, dict):
            continue
        data_source = benchmark.get("dataSource")
        item_symbol = benchmark.get("symbol")
        if not isinstance(data_source, str) or not isinstance(item_symbol, str):
            continue
        if _normalize_data_source(data_source) == source_norm and item_symbol.strip().lower() == symbol_norm:
            return benchmark
    return None


async def _add_benchmark_with_fallback(source: str, symbol: str) -> dict[str, Any]:
    payload = {"dataSource": _normalize_data_source(source), "symbol": symbol.strip()}
    first = await _request("POST", "/api/v1/benchmarks", json=payload)
    if first.get("ok"):
        return first

    status_code = first.get("status_code")
    if not isinstance(status_code, int) or status_code < 500:
        return first

    # Prime symbol metadata once, then retry benchmark creation.
    await _request(
        "GET",
        f"/api/v1/symbol/{payload['dataSource']}/{payload['symbol']}",
        params={"includeHistoricalData": 0},
    )
    second = await _request("POST", "/api/v1/benchmarks", json=payload)
    if second.get("ok"):
        return second

    # If create raced with another request, treat existing benchmark as success.
    listed = await _request("GET", "/api/v1/benchmarks")
    if listed.get("ok"):
        existing = _find_existing_benchmark(listed.get("body"), payload["dataSource"], payload["symbol"])
        if existing is not None:
            return {"ok": True, "status_code": 200, "body": existing}

    # Some Ghostfolio builds accept symbolProfileId rather than source/symbol.
    lookup = await _request("GET", "/api/v1/symbol/lookup", params={"query": payload["symbol"]})
    if lookup.get("ok"):
        profile_id = _extract_lookup_symbol_profile_id(
            lookup.get("body") if isinstance(lookup.get("body"), dict) else {},
            payload["dataSource"],
            payload["symbol"],
        )
        if profile_id:
            by_id = await _request("POST", "/api/v1/benchmarks", json={"symbolProfileId": profile_id})
            if by_id.get("ok"):
                return by_id

    return second


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


# ---------- Operation helpers ----------

def _merge_params(base: dict[str, Any] | None, extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in extra.items():
        if value is None:
            continue
        merged[key] = value
    return merged


def _filter_lookup_items_blocked_sources(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    items = payload.get("items")
    if not isinstance(items, list):
        return payload

    filtered = [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and _is_blocked_market_data_source(
                item.get("dataSource") if isinstance(item.get("dataSource"), str) else None
            )
        )
    ]
    output = dict(payload)
    output["items"] = filtered
    if BLOCKED_MARKET_DATA_SOURCES:
        output["blocked_data_sources"] = sorted(BLOCKED_MARKET_DATA_SOURCES)
    return output


async def _set_account_taxonomy_tags_internal(
    account_id: str,
    entity: str,
    tax_wrapper: str,
    account_type: str,
    comp_plan: str | None,
    preserve_existing_comment: bool,
) -> dict[str, Any]:
    account_id = account_id.strip()
    entity = entity.strip().lower()
    tax_wrapper = tax_wrapper.strip().lower()
    account_type = account_type.strip().lower()
    comp_plan = comp_plan.strip().lower() if isinstance(comp_plan, str) and comp_plan.strip() else None

    if not account_id:
        return {"ok": False, "code": "invalid_input", "message": "account_id is required."}
    if entity not in VALID_ENTITY:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid entity '{entity}'. Valid values: {', '.join(sorted(VALID_ENTITY))}",
        }
    if tax_wrapper not in VALID_WRAPPER:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid tax_wrapper '{tax_wrapper}'. Valid values: {', '.join(sorted(VALID_WRAPPER))}",
        }
    if account_type not in VALID_ACCOUNT_TYPES:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": (
                f"Invalid account_type '{account_type}'. "
                f"Valid values: {', '.join(sorted(VALID_ACCOUNT_TYPES))}"
            ),
        }
    if comp_plan is not None and comp_plan not in VALID_COMP_PLANS:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": (
                f"Invalid comp_plan '{comp_plan}'. "
                f"Valid values: {', '.join(sorted(VALID_COMP_PLANS))}"
            ),
        }
    if account_type == "equity_comp" and comp_plan is None:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": "comp_plan is required when account_type is 'equity_comp'.",
        }

    current_result = await _request("GET", f"/api/v1/account/{account_id}")
    if not current_result.get("ok"):
        return {
            "ok": False,
            "code": current_result.get("error", {}).get("code", "request_failed"),
            "message": current_result.get("error", {}).get("message", "Account fetch failed."),
            "details": {"status_code": current_result.get("status_code")},
        }

    account = _extract_account_record(current_result.get("body"))
    if account is None:
        return {
            "ok": False,
            "code": "response_parse_error",
            "message": f"Could not parse account payload for '{account_id}'.",
        }

    next_comment = _build_taxonomy_comment(
        entity=entity,
        tax_wrapper=tax_wrapper,
        account_type=account_type,
        comp_plan=comp_plan,
        existing_comment=account.get("comment") if isinstance(account.get("comment"), str) else None,
        preserve_existing_comment=preserve_existing_comment,
    )

    update_payload = _build_account_update_payload(account, next_comment)
    if isinstance(update_payload, str):
        return {
            "ok": False,
            "code": "invalid_update_payload",
            "message": update_payload,
        }

    put_result = await _request(
        "PUT",
        f"/api/v1/account/{account_id}",
        json=update_payload,
    )
    if not put_result.get("ok"):
        return {
            "ok": False,
            "code": put_result.get("error", {}).get("code", "request_failed"),
            "message": put_result.get("error", {}).get("message", "Account update failed."),
            "details": {"status_code": put_result.get("status_code")},
        }

    refreshed = await _request("GET", f"/api/v1/account/{account_id}")
    if not refreshed.get("ok"):
        return {
            "ok": True,
            "account_id": account_id,
            "comment": next_comment,
            "classification_tags": [
                f"entity:{entity}",
                f"tax_wrapper:{tax_wrapper}",
                f"account_type:{account_type}",
                *([f"comp_plan:{comp_plan}"] if comp_plan else []),
            ],
            "classification": {
                "entity": entity,
                "tax_wrapper": tax_wrapper,
                "account_type": account_type,
                "comp_plan": comp_plan,
                "valid": True,
                "errors": [],
            },
            "warning": (
                "Account updated, but refresh failed: "
                + str(refreshed.get("error", {}).get("message", "unknown error"))
            ),
            "update_status_code": put_result.get("status_code"),
        }

    updated = _extract_account_record(refreshed.get("body"))
    if updated is None:
        return {
            "ok": True,
            "account_id": account_id,
            "comment": next_comment,
            "warning": "Account updated, but refreshed payload was not parseable.",
            "update_status_code": put_result.get("status_code"),
        }

    tags = _extract_account_tags(updated, _load_env_account_tag_map())
    classification = _classify_account_tags(tags)
    return {
        "ok": True,
        "account_id": updated.get("id", account_id),
        "name": updated.get("name"),
        "comment": updated.get("comment"),
        "classification_tags": tags,
        "classification": classification,
        "update_status_code": put_result.get("status_code"),
    }


@mcp.tool()
async def account(
    operation: str,
    account_id: str | None = None,
    account_name: str | None = None,
    record_id: str | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    entity: str | None = None,
    tax_wrapper: str | None = None,
    account_type: str | None = None,
    comp_plan: str | None = None,
    preserve_existing_comment: bool = True,
    strict: bool = True,
) -> dict[str, Any]:
    """Consolidated account operations (CRUD, balances, transfers, taxonomy)."""
    tool = "account"
    op = _clean_operation(operation)
    valid = [
        "list",
        "get",
        "balances",
        "create",
        "update",
        "delete",
        "create_balance",
        "delete_balance",
        "transfer_balance",
        "classify",
        "validate_taxonomy",
        "set_taxonomy_tags",
        "set_taxonomy_tags_by_name",
    ]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    data = data or {}
    params = params or {}

    if op == "list":
        result = await _request("GET", "/api/v1/account", params=params)
        return _from_request(tool, op, "GET", "/api/v1/account", result)

    if op == "get":
        if not account_id:
            return _failure(tool, op, "GET", "/api/v1/account/:id", "invalid_input", "account_id is required.")
        result = await _request("GET", f"/api/v1/account/{account_id}")
        return _from_request(tool, op, "GET", f"/api/v1/account/{account_id}", result)

    if op == "balances":
        if not account_id:
            return _failure(tool, op, "GET", "/api/v1/account/:id/balances", "invalid_input", "account_id is required.")
        result = await _request("GET", f"/api/v1/account/{account_id}/balances", params=params)
        return _from_request(tool, op, "GET", f"/api/v1/account/{account_id}/balances", result)

    if op == "create":
        payload = dict(data)
        if "value" in payload and "balance" not in payload:
            payload["balance"] = payload.pop("value")
        payload.setdefault("balance", 0)
        payload.setdefault("currency", "USD")
        if payload.get("platformId") is None:
            payload["platformId"] = ""
        payload.setdefault("platformId", "")
        result = await _request("POST", "/api/v1/account", json=payload)
        return _from_request(tool, op, "POST", "/api/v1/account", result)

    if op == "update":
        if not account_id:
            return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_id is required.")
        payload = dict(data)
        if "value" in payload and "balance" not in payload:
            payload["balance"] = payload.pop("value")
        current_result = await _request("GET", f"/api/v1/account/{account_id}")
        current_account = current_result.get("body") if current_result.get("ok") else None
        if isinstance(current_account, dict):
            payload.setdefault("name", current_account.get("name"))
            payload.setdefault("currency", current_account.get("currency") or "USD")
            payload.setdefault("balance", current_account.get("balance", 0))
            payload.setdefault("platformId", current_account.get("platformId") or "")
            payload.setdefault("isExcluded", current_account.get("isExcluded", False))
            if preserve_existing_comment and "comment" not in payload:
                if current_account.get("comment") is not None:
                    payload["comment"] = current_account.get("comment")
        else:
            payload.setdefault("currency", "USD")
            payload.setdefault("balance", 0)
            if payload.get("platformId") is None:
                payload["platformId"] = ""
            payload.setdefault("platformId", "")
        payload.setdefault("id", account_id)
        result = await _request("PUT", f"/api/v1/account/{account_id}", json=payload)
        return _from_request(tool, op, "PUT", f"/api/v1/account/{account_id}", result)

    if op == "delete":
        if not account_id:
            return _failure(tool, op, "DELETE", "/api/v1/account/:id", "invalid_input", "account_id is required.")
        result = await _request("DELETE", f"/api/v1/account/{account_id}")
        return _from_request(tool, op, "DELETE", f"/api/v1/account/{account_id}", result)

    if op == "create_balance":
        payload = dict(data)
        if "value" in payload and "balance" not in payload:
            payload["balance"] = payload.pop("value")
        result = await _request("POST", "/api/v1/account-balance", json=payload)
        return _from_request(tool, op, "POST", "/api/v1/account-balance", result)

    if op == "delete_balance":
        target = record_id or account_id
        if not target:
            return _failure(tool, op, "DELETE", "/api/v1/account-balance/:id", "invalid_input", "record_id is required (or use account_id).")
        result = await _request("DELETE", f"/api/v1/account-balance/{target}")
        return _from_request(tool, op, "DELETE", f"/api/v1/account-balance/{target}", result)

    if op == "transfer_balance":
        payload = dict(data)
        if "fromAccountId" in payload and "accountIdFrom" not in payload:
            payload["accountIdFrom"] = payload.pop("fromAccountId")
        if "toAccountId" in payload and "accountIdTo" not in payload:
            payload["accountIdTo"] = payload.pop("toAccountId")
        if "value" in payload and "balance" not in payload:
            payload["balance"] = payload.pop("value")
        payload.pop("date", None)
        result = await _request("POST", "/api/v1/account/transfer-balance", json=payload)
        return _from_request(tool, op, "POST", "/api/v1/account/transfer-balance", result)

    if op == "classify":
        payload = await _get_accounts_with_classification(strict=False)
        if not payload.get("ok") and payload.get("error"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                payload.get("error", {}).get("code", "request_failed"),
                payload.get("error", {}).get("message", "Failed to load accounts."),
                details={"status_code": payload.get("status_code")},
            )
        return _success(tool, op, "GET", "/api/v1/account", payload)

    if op == "validate_taxonomy":
        payload = await _get_accounts_with_classification(strict=False)
        if not payload.get("ok") and payload.get("error"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                payload.get("error", {}).get("code", "request_failed"),
                payload.get("error", {}).get("message", "Failed to load accounts."),
                details={"status_code": payload.get("status_code")},
            )

        invalid_accounts = payload.get("invalid_accounts", [])
        if strict and invalid_accounts:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                "taxonomy_validation_failed",
                "Account taxonomy validation failed.",
                details={
                    "summary": payload.get("summary", {}),
                    "invalid_accounts": invalid_accounts,
                    "taxonomy": payload.get("taxonomy", {}),
                },
            )

        return _success(
            tool,
            op,
            "GET",
            "/api/v1/account",
            {
                "ok": len(invalid_accounts) == 0,
                "summary": payload.get("summary", {}),
                "invalid_accounts": invalid_accounts,
                "taxonomy": payload.get("taxonomy", {}),
            },
        )

    if op == "set_taxonomy_tags":
        if not account_id:
            return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_id is required.")
        if not entity or not tax_wrapper or not account_type:
            return _failure(
                tool,
                op,
                "PUT",
                "/api/v1/account/:id",
                "invalid_input",
                "entity, tax_wrapper, and account_type are required.",
            )

        result = await _set_account_taxonomy_tags_internal(
            account_id=account_id,
            entity=entity,
            tax_wrapper=tax_wrapper,
            account_type=account_type,
            comp_plan=comp_plan,
            preserve_existing_comment=preserve_existing_comment,
        )
        if not result.get("ok"):
            return _failure(
                tool,
                op,
                "PUT",
                f"/api/v1/account/{account_id}",
                result.get("code", "update_failed"),
                result.get("message", "Failed to set taxonomy tags."),
                details=result.get("details"),
            )
        return _success(tool, op, "PUT", f"/api/v1/account/{account_id}", result)

    if op == "set_taxonomy_tags_by_name":
        if not account_name:
            return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_name is required.")
        if not entity or not tax_wrapper or not account_type:
            return _failure(
                tool,
                op,
                "PUT",
                "/api/v1/account/:id",
                "invalid_input",
                "entity, tax_wrapper, and account_type are required.",
            )

        raw = await _get_accounts_raw()
        if not raw.get("ok"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                raw.get("error", {}).get("code", "request_failed"),
                raw.get("error", {}).get("message", "Failed to load accounts."),
                details={"status_code": raw.get("status_code")},
            )

        target = account_name.strip().lower()
        rows = [a for a in raw.get("accounts", []) if isinstance(a, dict)]
        exact = [
            a for a in rows
            if isinstance(a.get("name"), str) and a.get("name", "").strip().lower() == target
        ]
        partial = [
            a for a in rows
            if isinstance(a.get("name"), str) and target in a.get("name", "").strip().lower()
        ]
        matches = exact if exact else partial

        if not matches:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                "not_found",
                f"No account found for name '{account_name}'.",
                details={
                    "available_accounts": [
                        {"account_id": _extract_account_id(a), "name": a.get("name")}
                        for a in rows
                    ]
                },
            )
        if len(matches) > 1:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                "ambiguous_match",
                f"Multiple accounts matched '{account_name}'. Use account_id instead.",
                details={
                    "matches": [
                        {"account_id": _extract_account_id(a), "name": a.get("name")}
                        for a in matches
                    ]
                },
            )

        chosen = matches[0]
        chosen_id = _extract_account_id(chosen)
        if not chosen_id:
            return _failure(tool, op, "GET", "/api/v1/account", "invalid_data", "Matched account is missing an account id.")

        result = await _set_account_taxonomy_tags_internal(
            account_id=chosen_id,
            entity=entity,
            tax_wrapper=tax_wrapper,
            account_type=account_type,
            comp_plan=comp_plan,
            preserve_existing_comment=preserve_existing_comment,
        )
        if not result.get("ok"):
            return _failure(
                tool,
                op,
                "PUT",
                f"/api/v1/account/{chosen_id}",
                result.get("code", "update_failed"),
                result.get("message", "Failed to set taxonomy tags."),
                details=result.get("details"),
            )

        result["resolved_account_name"] = chosen.get("name")
        return _success(tool, op, "PUT", f"/api/v1/account/{chosen_id}", result)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


@mcp.tool()
async def portfolio(
    operation: str,
    data_source: str | None = None,
    symbol: str | None = None,
    range: str = "1y",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Consolidated portfolio operations (state, performance, scoped snapshot, tag updates)."""
    tool = "portfolio"
    op = _clean_operation(operation)
    valid = [
        "capabilities",
        "summary",
        "details",
        "holdings",
        "holding",
        "performance",
        "dividends",
        "investments",
        "report",
        "set_holding_tags",
        "snapshot",
        "snapshot_v2",
    ]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    params = params or {}
    data = data or {}

    if op == "capabilities":
        return _success(
            tool,
            op,
            "N/A",
            "N/A",
            {
                "operations": valid,
                "snapshot_contracts": {
                    "snapshot": "legacy scoped holdings snapshot (accountId may be missing)",
                    "snapshot_v2": "account-aware snapshot reconstructed from /api/v1/order + /api/v1/portfolio/holdings",
                },
                "strict_scope_min_coverage_pct": 0.99,
            },
        )

    if op == "summary":
        result = await _request("GET", "/api/v1/portfolio/details", params=params)
        if not result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v1/portfolio/details", result)

        body = result.get("body")
        if isinstance(body, dict) and isinstance(body.get("summary"), dict):
            transformed = {
                "summary": body.get("summary"),
                "createdAt": body.get("createdAt"),
                "accountCount": len(body.get("accounts", {})) if isinstance(body.get("accounts"), dict) else None,
                "holdingCount": len(body.get("holdings", {})) if isinstance(body.get("holdings"), dict) else None,
            }
            return _success(tool, op, "GET", "/api/v1/portfolio/details", transformed)

        return _success(tool, op, "GET", "/api/v1/portfolio/details", body)

    if op == "details":
        result = await _request("GET", "/api/v1/portfolio/details", params=params)
        return _from_request(tool, op, "GET", "/api/v1/portfolio/details", result)

    if op == "holdings":
        result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
        return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", result)

    if op == "holding":
        if not symbol:
            return _failure(tool, op, "GET", "/api/v1/portfolio/holding/:dataSource/:symbol", "invalid_input", "symbol is required.")
        resolved = await _resolve_symbol_context(symbol, data_source)
        if isinstance(resolved, str):
            return _failure(tool, op, "GET", "/api/v1/portfolio/holding/:dataSource/:symbol", "symbol_resolution_error", resolved)
        resolved_source, resolved_symbol = resolved
        result = await _request("GET", f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}")
        return _from_request(tool, op, "GET", f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}", result)

    if op == "performance":
        if range not in VALID_RANGES:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v2/portfolio/performance",
                "invalid_input",
                f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
            )
        req_params = _merge_params(params, {"range": range})
        result = await _request("GET", "/api/v2/portfolio/performance", params=req_params)
        return _from_request(tool, op, "GET", "/api/v2/portfolio/performance", result)

    if op == "dividends":
        if range not in VALID_RANGES:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/portfolio/dividends",
                "invalid_input",
                f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
            )
        req_params = _merge_params(params, {"range": range})
        result = await _request("GET", "/api/v1/portfolio/dividends", params=req_params)
        if (not result.get("ok")) and result.get("status_code") == 500:
            # Ghostfolio can return 500 for empty/new portfolios; normalize to deterministic empty payload.
            return _success(
                tool,
                op,
                "GET",
                "/api/v1/portfolio/dividends",
                {
                    "dividends": [],
                    "range": range,
                    "note": "Upstream returned HTTP 500; normalized to empty dividends payload.",
                },
            )
        return _from_request(tool, op, "GET", "/api/v1/portfolio/dividends", result)

    if op == "investments":
        if range not in VALID_RANGES:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/portfolio/investments",
                "invalid_input",
                f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
            )
        req_params = _merge_params(params, {"range": range})
        result = await _request("GET", "/api/v1/portfolio/investments", params=req_params)
        return _from_request(tool, op, "GET", "/api/v1/portfolio/investments", result)

    if op == "report":
        result = await _request("GET", "/api/v1/portfolio/report")
        return _from_request(tool, op, "GET", "/api/v1/portfolio/report", result)

    if op == "set_holding_tags":
        if not symbol:
            return _failure(tool, op, "PUT", "/api/v1/portfolio/holding/:dataSource/:symbol/tags", "invalid_input", "symbol is required.")
        resolved = await _resolve_symbol_context(symbol, data_source)
        if isinstance(resolved, str):
            return _failure(tool, op, "PUT", "/api/v1/portfolio/holding/:dataSource/:symbol/tags", "symbol_resolution_error", resolved)
        resolved_source, resolved_symbol = resolved
        result = await _request(
            "PUT",
            f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}/tags",
            json=data,
        )
        return _from_request(
            tool,
            op,
            "PUT",
            f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}/tags",
            result,
        )

    if op == "snapshot_v2":
        if range not in VALID_RANGES:
            return _failure(
                tool,
                op,
                "GET",
                "MULTI",
                "invalid_input",
                f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
            )

        scope_entity = scope_entity.strip().lower()
        scope_wrapper = scope_wrapper.strip().lower()
        try:
            scope_types = _normalize_scope_list(scope_account_types)
        except ValueError as exc:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", str(exc))

        if scope_entity not in {"all", *VALID_ENTITY}:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_entity '{scope_entity}'.")
        if scope_wrapper not in {"all", *VALID_WRAPPER}:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_wrapper '{scope_wrapper}'.")

        account_payload = await _get_accounts_with_classification(strict=False)
        if not account_payload.get("ok") and account_payload.get("error"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                account_payload.get("error", {}).get("code", "request_failed"),
                account_payload.get("error", {}).get("message", "Failed to load accounts."),
                details={"status_code": account_payload.get("status_code")},
            )
        if strict and account_payload.get("invalid_accounts"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                "taxonomy_validation_failed",
                "Account taxonomy validation failed in strict mode.",
                details={
                    "summary": account_payload.get("summary", {}),
                    "invalid_accounts": account_payload.get("invalid_accounts", []),
                },
            )

        accounts = account_payload.get("accounts", [])
        account_by_id = {
            account.get("account_id"): account
            for account in accounts
            if isinstance(account, dict) and isinstance(account.get("account_id"), str)
        }
        in_scope_account_ids = {
            account.get("account_id")
            for account in accounts
            if isinstance(account.get("account_id"), str)
            and _matches_scope(account.get("classification", {}), scope_entity, scope_wrapper, scope_types)
        }

        order_result = await _request("GET", "/api/v1/order", params=params)
        if not order_result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v1/order", order_result)
        order_body = order_result.get("body", {})
        activities = []
        if isinstance(order_body, dict) and isinstance(order_body.get("activities"), list):
            activities = [row for row in order_body.get("activities", []) if isinstance(row, dict)]
        elif isinstance(order_body, dict) and isinstance(order_body.get("items"), list):
            activities = [row for row in order_body.get("items", []) if isinstance(row, dict)]

        holdings_result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
        if not holdings_result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", holdings_result)
        holdings_body = holdings_result.get("body", {})
        holdings_rows: list[dict[str, Any]] = []
        if isinstance(holdings_body, dict) and isinstance(holdings_body.get("holdings"), list):
            holdings_rows = [row for row in holdings_body.get("holdings", []) if isinstance(row, dict)]
        elif isinstance(holdings_body, list):
            holdings_rows = [row for row in holdings_body if isinstance(row, dict)]
        holdings_symbol_map = _build_holdings_symbol_map(holdings_rows)

        position_map: dict[tuple[str, str], dict[str, Any]] = {}
        skipped_missing = 0
        skipped_zero_quantity = 0

        for activity in sorted(
            activities,
            key=lambda row: (
                str(row.get("date") or row.get("createdAt") or row.get("updatedAt") or ""),
                str(row.get("id") or ""),
            ),
        ):
            if bool(activity.get("isDraft")):
                continue
            account_id = _extract_activity_account_id(activity)
            symbol_value = _extract_activity_symbol(activity)
            if not account_id or not symbol_value:
                skipped_missing += 1
                continue

            raw_quantity = _to_float(activity.get("quantity"), 0.0)
            if abs(raw_quantity) <= 1e-12:
                skipped_zero_quantity += 1
                continue

            activity_type = str(activity.get("type", "BUY")).strip().upper()
            sign = _activity_trade_sign(activity_type, raw_quantity)
            quantity = abs(raw_quantity)
            quantity_delta = quantity * sign

            trade_value = _to_float(activity.get("valueInBaseCurrency"), float("nan"))
            if trade_value != trade_value:
                trade_value = _to_float(activity.get("value"), float("nan"))
            if trade_value != trade_value:
                unit_price_fallback = _to_float(
                    activity.get("unitPriceInAssetProfileCurrency"),
                    _to_float(activity.get("unitPrice"), 0.0),
                )
                trade_value = abs(quantity * unit_price_fallback)
            trade_value = max(trade_value, 0.0)

            fee = max(
                0.0,
                _to_float(
                    activity.get("feeInBaseCurrency"),
                    _to_float(activity.get("fee"), 0.0),
                ),
            )
            unit_price = _to_float(
                activity.get("unitPriceInAssetProfileCurrency"),
                _to_float(activity.get("unitPrice"), 0.0),
            )

            key = (account_id, symbol_value)
            entry = position_map.setdefault(
                key,
                {
                    "accountId": account_id,
                    "symbol": symbol_value,
                    "quantity": 0.0,
                    "cost": 0.0,
                    "last_trade_price": 0.0,
                    "currency": activity.get("currency") or "USD",
                    "dataSource": _extract_activity_data_source(activity),
                },
            )

            if quantity_delta > 0:
                entry["quantity"] += quantity_delta
                entry["cost"] += trade_value + fee
            else:
                if entry["quantity"] <= 1e-12:
                    continue
                sell_qty = min(entry["quantity"], abs(quantity_delta))
                avg_cost = (entry["cost"] / entry["quantity"]) if entry["quantity"] > 0 else 0.0
                entry["quantity"] -= sell_qty
                if entry["quantity"] <= 1e-12:
                    entry["quantity"] = 0.0
                    entry["cost"] = 0.0
                else:
                    entry["cost"] = max(0.0, entry["cost"] - (avg_cost * sell_qty))

            if unit_price > 0:
                entry["last_trade_price"] = unit_price

        positions: list[dict[str, Any]] = []
        for (account_id, symbol_value), entry in position_map.items():
            quantity = max(_to_float(entry.get("quantity"), 0.0), 0.0)
            if quantity <= 1e-9:
                continue
            holdings_meta = holdings_symbol_map.get(symbol_value, {})
            market_price = _to_float(holdings_meta.get("marketPrice"), 0.0)
            if market_price <= 0:
                market_price = max(_to_float(entry.get("last_trade_price"), 0.0), 0.0)
            value = quantity * market_price
            cost = max(_to_float(entry.get("cost"), 0.0), 0.0)
            account = account_by_id.get(account_id, {})
            classification = account.get("classification", {}) if isinstance(account, dict) else {}
            positions.append(
                {
                    "accountId": account_id,
                    "symbol": symbol_value,
                    "quantity": quantity,
                    "investment": cost,
                    "costBasisInBaseCurrency": cost,
                    "marketPrice": market_price,
                    "valueInBaseCurrency": value,
                    "currency": holdings_meta.get("currency") or entry.get("currency") or "USD",
                    "assetClass": holdings_meta.get("assetClass"),
                    "assetSubClass": holdings_meta.get("assetSubClass"),
                    "dataSource": holdings_meta.get("dataSource") or entry.get("dataSource"),
                    "entity": classification.get("entity"),
                    "tax_wrapper": classification.get("tax_wrapper"),
                    "account_type": classification.get("account_type"),
                }
            )

        for account in accounts:
            if not isinstance(account, dict):
                continue
            account_id = account.get("account_id")
            if not isinstance(account_id, str) or not account_id:
                continue
            balance = _to_float(account.get("balance"), 0.0)
            if abs(balance) <= 1e-9:
                continue
            classification = account.get("classification", {})
            positions.append(
                {
                    "accountId": account_id,
                    "symbol": "USD",
                    "quantity": balance,
                    "investment": balance,
                    "costBasisInBaseCurrency": balance,
                    "marketPrice": 1.0,
                    "valueInBaseCurrency": balance,
                    "currency": account.get("currency") or "USD",
                    "assetClass": "LIQUIDITY",
                    "assetSubClass": "CASH",
                    "dataSource": "MANUAL",
                    "entity": classification.get("entity"),
                    "tax_wrapper": classification.get("tax_wrapper"),
                    "account_type": classification.get("account_type"),
                }
            )

        holdings_total_value = sum(max(_holding_value(row), 0.0) for row in holdings_rows)
        reconstructed_total_value = sum(max(_holding_value(row), 0.0) for row in positions)
        position_value_by_symbol: dict[str, float] = {}
        for row in positions:
            symbol_key = _holding_symbol(row)
            if not symbol_key:
                continue
            position_value_by_symbol[symbol_key] = position_value_by_symbol.get(symbol_key, 0.0) + max(_holding_value(row), 0.0)

        covered_value = 0.0
        for symbol_key, payload in holdings_symbol_map.items():
            holdings_value = max(_to_float(payload.get("value"), 0.0), 0.0)
            covered_value += min(holdings_value, position_value_by_symbol.get(symbol_key, 0.0))
        coverage_pct = (covered_value / holdings_total_value) if holdings_total_value > 0 else 1.0
        reconciliation_drift_pct = (
            abs(reconstructed_total_value - holdings_total_value) / holdings_total_value
            if holdings_total_value > 0
            else 0.0
        )

        is_scoped = (
            scope_entity != "all"
            or scope_wrapper != "all"
            or (scope_types is not None and len(scope_types) > 0)
        )
        included_positions: list[dict[str, Any]] = []
        excluded_count = 0
        for row in positions:
            if not is_scoped:
                included_positions.append(row)
                continue
            account_id = _extract_holding_account_id(row)
            if account_id in in_scope_account_ids:
                included_positions.append(row)
            else:
                excluded_count += 1

        min_coverage_pct = 0.99
        if strict and is_scoped and coverage_pct < min_coverage_pct:
            return _failure(
                tool,
                op,
                "GET",
                "MULTI",
                "strict_scope_error",
                (
                    f"Account-aware coverage is {coverage_pct:.2%}, below strict minimum "
                    f"{min_coverage_pct:.2%}."
                ),
                details={"coverage_pct": coverage_pct, "minimum_required_pct": min_coverage_pct},
            )

        warnings: list[str] = []
        if skipped_missing > 0:
            warnings.append(f"{skipped_missing} activities were skipped due to missing accountId or symbol.")
        if skipped_zero_quantity > 0:
            warnings.append(f"{skipped_zero_quantity} zero-quantity activities were skipped.")
        if excluded_count > 0:
            warnings.append(f"{excluded_count} positions were excluded by account scope.")
        if coverage_pct < min_coverage_pct:
            warnings.append(
                f"Account-aware coverage is {coverage_pct:.2%}, below target {min_coverage_pct:.2%}."
            )

        payload = {
            "snapshot_id": f"snap_v2_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{len(positions)}",
            "as_of": _now_iso(),
            "scope": {
                "entity": scope_entity,
                "tax_wrapper": scope_wrapper,
                "account_types": sorted(list(scope_types)) if scope_types is not None else "all",
                "strict": strict,
            },
            "classification_summary": account_payload.get("summary", {}),
            "accounts": accounts,
            "positions": {
                "rows": included_positions,
                "count": len(included_positions),
                "excluded_count": excluded_count,
            },
            "coverage": {
                "account_aware_coverage_pct": coverage_pct,
                "reconciliation_drift_pct": reconciliation_drift_pct,
                "holdings_total_value": holdings_total_value,
                "reconstructed_total_value": reconstructed_total_value,
            },
            "warnings": warnings,
            "provenance": {
                "position_sources": ["ghostfolio:/api/v1/order", "ghostfolio:/api/v1/portfolio/holdings"],
                "account_source": "ghostfolio:/api/v1/account",
            },
        }
        return _success(tool, op, "GET", "MULTI", payload)

    if op == "snapshot":
        if range not in VALID_RANGES:
            return _failure(
                tool,
                op,
                "GET",
                "MULTI",
                "invalid_input",
                f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
            )

        scope_entity = scope_entity.strip().lower()
        scope_wrapper = scope_wrapper.strip().lower()
        try:
            scope_types = _normalize_scope_list(scope_account_types)
        except ValueError as exc:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", str(exc))

        if scope_entity not in {"all", *VALID_ENTITY}:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_entity '{scope_entity}'.")
        if scope_wrapper not in {"all", *VALID_WRAPPER}:
            return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_wrapper '{scope_wrapper}'.")

        account_payload = await _get_accounts_with_classification(strict=False)
        if not account_payload.get("ok") and account_payload.get("error"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                account_payload.get("error", {}).get("code", "request_failed"),
                account_payload.get("error", {}).get("message", "Failed to load accounts."),
                details={"status_code": account_payload.get("status_code")},
            )
        if strict and account_payload.get("invalid_accounts"):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/account",
                "taxonomy_validation_failed",
                "Account taxonomy validation failed in strict mode.",
                details={
                    "summary": account_payload.get("summary", {}),
                    "invalid_accounts": account_payload.get("invalid_accounts", []),
                },
            )

        accounts = account_payload.get("accounts", [])
        in_scope_account_ids = {
            account.get("account_id")
            for account in accounts
            if isinstance(account.get("account_id"), str)
            and _matches_scope(account.get("classification", {}), scope_entity, scope_wrapper, scope_types)
        }

        holdings_result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
        if not holdings_result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", holdings_result)

        raw_holdings = holdings_result.get("body", {})
        rows: list[dict[str, Any]] = []
        if isinstance(raw_holdings, dict) and isinstance(raw_holdings.get("holdings"), list):
            rows = [r for r in raw_holdings.get("holdings", []) if isinstance(r, dict)]
        elif isinstance(raw_holdings, list):
            rows = [r for r in raw_holdings if isinstance(r, dict)]

        is_scoped = (
            scope_entity != "all"
            or scope_wrapper != "all"
            or (scope_types is not None and len(scope_types) > 0)
        )

        included: list[dict[str, Any]] = []
        excluded_count = 0
        unscoped_count = 0
        inferred_count = 0
        scoped_known_accounts = {
            a.get("account_id")
            for a in accounts
            if isinstance(a.get("account_id"), str)
        }
        can_infer_single_account_scope = (
            is_scoped
            and len(in_scope_account_ids) == 1
            and len(scoped_known_accounts) == 1
        )

        for row in rows:
            if not is_scoped:
                included.append(row)
                continue

            account_id = _extract_holding_account_id(row)
            if account_id is None:
                if can_infer_single_account_scope:
                    included.append(row)
                    inferred_count += 1
                    continue
                unscoped_count += 1
                continue

            if account_id in in_scope_account_ids:
                included.append(row)
            else:
                excluded_count += 1

        if strict and is_scoped and unscoped_count > 0:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/portfolio/holdings",
                "strict_scope_error",
                (
                    f"{unscoped_count} holdings had no account identifier and could not "
                    "be scoped in strict mode."
                ),
            )

        warnings: list[str] = []
        if inferred_count > 0:
            warnings.append(
                f"{inferred_count} holdings missing account identifier were included by single-account scope inference."
            )
        if is_scoped and unscoped_count > 0:
            warnings.append(
                f"{unscoped_count} holdings had no account identifier and could not be scoped."
            )

        details_result = await _request("GET", "/api/v1/portfolio/details", params=params)
        if not details_result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v1/portfolio/details", details_result)

        perf_params = _merge_params(params, {"range": range})
        perf_result = await _request("GET", "/api/v2/portfolio/performance", params=perf_params)
        if not perf_result.get("ok"):
            return _from_request(tool, op, "GET", "/api/v2/portfolio/performance", perf_result)

        payload = {
            "asof": _now_iso(),
            "scope": {
                "entity": scope_entity,
                "tax_wrapper": scope_wrapper,
                "account_types": sorted(list(scope_types)) if scope_types is not None else "all",
                "strict": strict,
            },
            "classification_summary": account_payload.get("summary", {}),
            "accounts": accounts,
            "positions": {
                "holdings": included,
                "count": len(included),
                "excluded_holdings_count": excluded_count,
                "classification_warnings": warnings,
            },
            "portfolio_details": details_result.get("body"),
            "portfolio_performance": perf_result.get("body"),
        }
        return _success(tool, op, "GET", "MULTI", payload)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


@mcp.tool()
async def order(
    operation: str,
    order_id: str | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidated order/activity operations."""
    tool = "order"
    op = _clean_operation(operation)
    valid = ["list", "get", "create", "update", "delete", "delete_filtered"]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    data = data or {}
    params = params or {}

    if op == "list":
        result = await _request("GET", "/api/v1/order", params=params)
        return _from_request(tool, op, "GET", "/api/v1/order", result)

    if op == "get":
        if not order_id:
            return _failure(tool, op, "GET", "/api/v1/order/:id", "invalid_input", "order_id is required.")
        result = await _request("GET", f"/api/v1/order/{order_id}")
        return _from_request(tool, op, "GET", f"/api/v1/order/{order_id}", result)

    if op == "create":
        result = await _request("POST", "/api/v1/order", json=data)
        return _from_request(tool, op, "POST", "/api/v1/order", result)

    if op == "update":
        if not order_id:
            return _failure(tool, op, "PUT", "/api/v1/order/:id", "invalid_input", "order_id is required.")
        payload = dict(data)
        payload.setdefault("id", order_id)
        result = await _request("PUT", f"/api/v1/order/{order_id}", json=payload)
        return _from_request(tool, op, "PUT", f"/api/v1/order/{order_id}", result)

    if op == "delete":
        if not order_id:
            return _failure(tool, op, "DELETE", "/api/v1/order/:id", "invalid_input", "order_id is required.")
        result = await _request("DELETE", f"/api/v1/order/{order_id}")
        return _from_request(tool, op, "DELETE", f"/api/v1/order/{order_id}", result)

    if op == "delete_filtered":
        result = await _request("DELETE", "/api/v1/order", params=params)
        return _from_request(tool, op, "DELETE", "/api/v1/order", result)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


@mcp.tool()
async def market(
    operation: str,
    symbol: str | None = None,
    data_source: str | None = None,
    query: str | None = None,
    date: str | None = None,
    include_historical_data: int | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidated market and symbol operations."""
    tool = "market"
    op = _clean_operation(operation)
    blocked_sources = set(BLOCKED_MARKET_DATA_SOURCES)
    valid = [
        "lookup",
        "quote",
        "quote_at_date",
        "asset",
        "market_data",
        "update_market_data",
        "markets_overview",
        "exchange_rate",
    ]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    params = params or {}
    data = data or {}

    if op == "lookup":
        q = (query or "").strip()
        if not q:
            return _failure(tool, op, "GET", "/api/v1/symbol/lookup", "invalid_input", "query is required.")
        req_params = _merge_params(params, {"query": q})
        result = await _request("GET", "/api/v1/symbol/lookup", params=req_params)
        return _from_request(
            tool,
            op,
            "GET",
            "/api/v1/symbol/lookup",
            result,
            transform=_filter_lookup_items_blocked_sources,
        )

    if op in {"quote", "asset", "market_data", "update_market_data"} and not symbol:
        return _failure(tool, op, "GET", "N/A", "invalid_input", "symbol is required.")

    if op == "quote":
        resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
        if isinstance(resolved, str):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/symbol/:dataSource/:symbol",
                _symbol_resolution_error_code(resolved),
                resolved,
                details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
            )
        source, resolved_symbol = resolved
        req_params = _merge_params(params, {"includeHistoricalData": include_historical_data})
        result = await _request("GET", f"/api/v1/symbol/{source}/{resolved_symbol}", params=req_params)
        return _from_request(tool, op, "GET", f"/api/v1/symbol/{source}/{resolved_symbol}", result)

    if op == "quote_at_date":
        if not date:
            return _failure(tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol/:date", "invalid_input", "date is required (YYYY-MM-DD).")
        if not data_source:
            return _failure(tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol/:date", "invalid_input", "data_source is required.")
        if _is_blocked_market_data_source(data_source):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/symbol/:dataSource/:symbol/:date",
                "policy_blocked",
                _blocked_market_source_message(data_source),
                details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
            )
        source = _normalize_data_source(data_source)
        result = await _request("GET", f"/api/v1/symbol/{source}/{symbol}/{date}", params=params)
        return _from_request(tool, op, "GET", f"/api/v1/symbol/{source}/{symbol}/{date}", result)

    if op == "asset":
        resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
        if isinstance(resolved, str):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/asset/:dataSource/:symbol",
                _symbol_resolution_error_code(resolved),
                resolved,
                details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
            )
        source, resolved_symbol = resolved
        result = await _request("GET", f"/api/v1/asset/{source}/{resolved_symbol}", params=params)
        return _from_request(tool, op, "GET", f"/api/v1/asset/{source}/{resolved_symbol}", result)

    if op == "market_data":
        resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
        if isinstance(resolved, str):
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/market-data/:dataSource/:symbol",
                _symbol_resolution_error_code(resolved),
                resolved,
                details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
            )
        source, resolved_symbol = resolved
        result = await _request("GET", f"/api/v1/market-data/{source}/{resolved_symbol}", params=params)
        if (not result.get("ok")) and result.get("status_code") == 404:
            return _failure(
                tool,
                op,
                "GET",
                f"/api/v1/market-data/{source}/{resolved_symbol}",
                "unsupported_endpoint",
                "Market-data read endpoint is not available on this Ghostfolio deployment.",
                details={
                    "hint": "Use market-intel-direct for live market data. Upgrade Ghostfolio if read-through is required.",
                    "status_code": 404,
                },
            )
        return _from_request(tool, op, "GET", f"/api/v1/market-data/{source}/{resolved_symbol}", result)

    if op == "update_market_data":
        resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
        if isinstance(resolved, str):
            return _failure(
                tool,
                op,
                "POST",
                "/api/v1/market-data/:dataSource/:symbol",
                _symbol_resolution_error_code(resolved),
                resolved,
                details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
            )
        source, resolved_symbol = resolved
        result = await _request("POST", f"/api/v1/market-data/{source}/{resolved_symbol}", json=data)
        if (not result.get("ok")) and result.get("status_code") == 404:
            return _failure(
                tool,
                op,
                "POST",
                f"/api/v1/market-data/{source}/{resolved_symbol}",
                "unsupported_endpoint",
                "Market-data write endpoint is not available on this Ghostfolio deployment.",
                details={
                    "hint": "Use market-intel-direct for live market data. Upgrade Ghostfolio if write-back is required.",
                    "status_code": 404,
                },
            )
        return _from_request(tool, op, "POST", f"/api/v1/market-data/{source}/{resolved_symbol}", result)

    if op == "markets_overview":
        req_params = _merge_params(params, {"includeHistoricalData": include_historical_data})
        result = await _request("GET", "/api/v1/market-data/markets", params=req_params)
        return _from_request(tool, op, "GET", "/api/v1/market-data/markets", result)

    if op == "exchange_rate":
        if not symbol:
            return _failure(tool, op, "GET", "/api/v1/exchange-rate/:symbol/:date", "invalid_input", "symbol is required.")
        if not date:
            return _failure(tool, op, "GET", "/api/v1/exchange-rate/:symbol/:date", "invalid_input", "date is required (YYYY-MM-DD).")
        result = await _request("GET", f"/api/v1/exchange-rate/{symbol}/{date}")
        if (not result.get("ok")) and result.get("status_code") == 404:
            return _failure(
                tool,
                op,
                "GET",
                f"/api/v1/exchange-rate/{symbol}/{date}",
                "not_found",
                "Exchange rate was not found for the requested symbol/date, or the endpoint is unavailable.",
                details={"symbol": symbol, "date": date, "status_code": 404},
            )
        return _from_request(tool, op, "GET", f"/api/v1/exchange-rate/{symbol}/{date}", result)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


@mcp.tool()
async def reference(
    operation: str,
    reference_id: str | None = None,
    data_source: str | None = None,
    symbol: str | None = None,
    start_date: str | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidated reference/admin operations (watchlist, benchmarks, tags, platforms, info)."""
    tool = "reference"
    op = _clean_operation(operation)
    valid = [
        "watchlist_list",
        "watchlist_add",
        "watchlist_remove",
        "benchmarks_list",
        "benchmark_add",
        "benchmark_remove",
        "benchmark_series",
        "tags_list",
        "tag_create",
        "tag_update",
        "tag_delete",
        "platform_list",
        "platform_create",
        "platform_update",
        "platform_delete",
        "info",
    ]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    data = data or {}
    params = params or {}

    if op == "watchlist_list":
        result = await _request("GET", "/api/v1/watchlist")
        return _from_request(tool, op, "GET", "/api/v1/watchlist", result)

    if op == "watchlist_add":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        if not source or not sym:
            return _failure(tool, op, "POST", "/api/v1/watchlist", "invalid_input", "data_source and symbol are required.")
        payload = {"dataSource": _normalize_data_source(str(source)), "symbol": str(sym)}
        result = await _request("POST", "/api/v1/watchlist", json=payload)
        return _from_request(tool, op, "POST", "/api/v1/watchlist", result)

    if op == "watchlist_remove":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        if not source or not sym:
            return _failure(tool, op, "DELETE", "/api/v1/watchlist/:dataSource/:symbol", "invalid_input", "data_source and symbol are required.")
        source = _normalize_data_source(str(source))
        result = await _request("DELETE", f"/api/v1/watchlist/{source}/{sym}")
        return _from_request(tool, op, "DELETE", f"/api/v1/watchlist/{source}/{sym}", result)

    if op == "benchmarks_list":
        result = await _request("GET", "/api/v1/benchmarks")
        return _from_request(tool, op, "GET", "/api/v1/benchmarks", result)

    if op == "benchmark_add":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        if not source or not sym:
            return _failure(tool, op, "POST", "/api/v1/benchmarks", "invalid_input", "data_source and symbol are required.")
        result = await _add_benchmark_with_fallback(str(source), str(sym))
        return _from_request(tool, op, "POST", "/api/v1/benchmarks", result)

    if op == "benchmark_remove":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        if not source or not sym:
            return _failure(tool, op, "DELETE", "/api/v1/benchmarks/:dataSource/:symbol", "invalid_input", "data_source and symbol are required.")
        source = _normalize_data_source(str(source))
        result = await _request("DELETE", f"/api/v1/benchmarks/{source}/{sym}")
        return _from_request(tool, op, "DELETE", f"/api/v1/benchmarks/{source}/{sym}", result)

    if op == "benchmark_series":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        started = start_date or data.get("startDate")
        if not source or not sym or not started:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/benchmarks/:dataSource/:symbol/:startDate",
                "invalid_input",
                "data_source, symbol, and start_date are required.",
            )
        source = _normalize_data_source(str(source))
        result = await _request(
            "GET",
            f"/api/v1/benchmarks/{source}/{sym}/{started}",
            params=params,
        )
        return _from_request(tool, op, "GET", f"/api/v1/benchmarks/{source}/{sym}/{started}", result)

    if op == "tags_list":
        result = await _request("GET", "/api/v1/tags")
        return _from_request(tool, op, "GET", "/api/v1/tags", result)

    if op == "tag_create":
        result = await _request("POST", "/api/v1/tags", json=data)
        return _from_request(tool, op, "POST", "/api/v1/tags", result)

    if op == "tag_update":
        target = reference_id or data.get("id")
        if not target:
            return _failure(tool, op, "PUT", "/api/v1/tags/:id", "invalid_input", "reference_id (tag id) is required.")
        payload = dict(data)
        payload.setdefault("id", target)
        result = await _request("PUT", f"/api/v1/tags/{target}", json=payload)
        return _from_request(tool, op, "PUT", f"/api/v1/tags/{target}", result)

    if op == "tag_delete":
        target = reference_id or data.get("id")
        if not target:
            return _failure(tool, op, "DELETE", "/api/v1/tags/:id", "invalid_input", "reference_id (tag id) is required.")
        result = await _request("DELETE", f"/api/v1/tags/{target}")
        return _from_request(tool, op, "DELETE", f"/api/v1/tags/{target}", result)

    if op == "platform_list":
        result = await _request("GET", "/api/v1/platform")
        return _from_request(tool, op, "GET", "/api/v1/platform", result)

    if op == "platform_create":
        result = await _request("POST", "/api/v1/platform", json=data)
        return _from_request(tool, op, "POST", "/api/v1/platform", result)

    if op == "platform_update":
        target = reference_id or data.get("id")
        if not target:
            return _failure(tool, op, "PUT", "/api/v1/platform/:id", "invalid_input", "reference_id (platform id) is required.")
        payload = dict(data)
        payload.setdefault("id", target)
        result = await _request("PUT", f"/api/v1/platform/{target}", json=payload)
        return _from_request(tool, op, "PUT", f"/api/v1/platform/{target}", result)

    if op == "platform_delete":
        target = reference_id or data.get("id")
        if not target:
            return _failure(tool, op, "DELETE", "/api/v1/platform/:id", "invalid_input", "reference_id (platform id) is required.")
        result = await _request("DELETE", f"/api/v1/platform/{target}")
        return _from_request(tool, op, "DELETE", f"/api/v1/platform/{target}", result)

    if op == "info":
        result = await _request("GET", "/api/v1/info")
        return _from_request(tool, op, "GET", "/api/v1/info", result)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


@mcp.tool()
async def system(
    operation: str,
    data_source: str | None = None,
    symbol: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidated system operations (health, import/export)."""
    tool = "system"
    op = _clean_operation(operation)
    valid = ["health", "data_provider_health", "export", "import", "import_dividends"]
    if op not in valid:
        return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

    params = params or {}
    data = data or {}

    if op == "health":
        result = await _request("GET", "/api/v1/health")
        return _from_request(tool, op, "GET", "/api/v1/health", result)

    if op == "data_provider_health":
        source = data_source or data.get("dataSource")
        if not source:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/health/data-provider/:dataSource",
                "invalid_input",
                "data_source is required.",
            )
        source = _normalize_data_source(str(source))
        result = await _request("GET", f"/api/v1/health/data-provider/{source}")
        return _from_request(tool, op, "GET", f"/api/v1/health/data-provider/{source}", result)

    if op == "export":
        result = await _request("GET", "/api/v1/export", params=params)
        return _from_request(tool, op, "GET", "/api/v1/export", result)

    if op == "import":
        result = await _request("POST", "/api/v1/import", json=data)
        return _from_request(tool, op, "POST", "/api/v1/import", result)

    if op == "import_dividends":
        source = data_source or data.get("dataSource")
        sym = symbol or data.get("symbol")
        if not source or not sym:
            return _failure(
                tool,
                op,
                "GET",
                "/api/v1/import/dividends/:dataSource/:symbol",
                "invalid_input",
                "data_source and symbol are required.",
            )
        source = _normalize_data_source(str(source))
        result = await _request("GET", f"/api/v1/import/dividends/{source}/{sym}")
        return _from_request(tool, op, "GET", f"/api/v1/import/dividends/{source}/{sym}", result)

    return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio", show_banner=False)
    except TypeError:
        # Compatibility fallback for older FastMCP versions without show_banner.
        mcp.run(transport="stdio")
