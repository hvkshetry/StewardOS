"""Holdings aggregation, symbol mapping, and scoped holdings loading.

Provides register_holdings_tools(server) for account taxonomy tools.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from stewardos_lib.portfolio_snapshot import (
    cash_position_symbol,
    content_addressed_snapshot_id,
    is_cash_like_row,
    normalized_position_symbol,
)


# ── Global config (set by server.py or importable as defaults) ──────────────
GHOSTFOLIO_URL = os.getenv("GHOSTFOLIO_URL", "http://localhost:8224")
GHOSTFOLIO_TOKEN = os.getenv("GHOSTFOLIO_TOKEN", "")
ACCOUNT_TAG_MAP_ENV = "GHOSTFOLIO_ACCOUNT_TAG_MAP"

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
VALID_OPTIONS_CAPABILITY = {"none", "long_premium", "vertical_spreads"}
BINDING_ES_LIMIT = 0.025
MIN_SCOPE_COVERAGE_PCT = 0.99
SNAPSHOT_CACHE_TTL_SECONDS = 120

_SNAPSHOT_CACHE: dict[str, Any] = {
    "latest_id": None,
    "latest": None,
    "created_at_epoch": 0.0,
}


# ── Low-level helpers ───────────────────────────────────────────────────────


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if GHOSTFOLIO_TOKEN:
        headers["Authorization"] = f"Bearer {GHOSTFOLIO_TOKEN}"
    return headers


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=GHOSTFOLIO_URL, headers=_headers(), timeout=30.0)


async def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    async with _client() as client:
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        body = response.text.strip()
        if not body:
            return {"ok": True, "status_code": response.status_code}
        parsed = response.json()
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}


# ── Account tag helpers ─────────────────────────────────────────────────────


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
        if not isinstance(key, str) or not isinstance(value, list):
            continue
        tags = [str(v).strip().lower() for v in value if str(v).strip()]
        normalized[key] = tags
    return normalized


def _parse_comment_tags(comment: str | None) -> list[str]:
    if not comment:
        return []
    parts = re.split(r"[;,\s]+", comment)
    return [part.strip().lower() for part in parts if ":" in part]


def _extract_account_id(account: dict[str, Any]) -> str:
    for key in ("id", "accountId", "account_id"):
        value = account.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_account_tags(account: dict[str, Any], env_map: dict[str, list[str]]) -> list[str]:
    tags: set[str] = set()

    payload_tags = account.get("tags")
    if isinstance(payload_tags, list):
        for item in payload_tags:
            if isinstance(item, str) and ":" in item:
                tags.add(item.strip().lower())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and ":" in name:
                    tags.add(name.strip().lower())

    comment = account.get("comment")
    if isinstance(comment, str):
        for token in _parse_comment_tags(comment):
            tags.add(token)

    account_id = _extract_account_id(account)
    if account_id and account_id in env_map:
        for token in env_map[account_id]:
            if ":" in token:
                tags.add(token)

    return sorted(tags)


def _classify_account_tags(tags: list[str]) -> dict[str, Any]:
    entity = None
    wrapper = None
    account_type = None
    comp_plan = None
    owner_person = None
    employer_ticker = None
    options_capability = None

    for tag in tags:
        key, _, value = tag.partition(":")
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
        elif key == "owner_person":
            owner_person = value
        elif key == "employer_ticker":
            employer_ticker = value.upper() if value else None
        elif key == "options_capability":
            options_capability = value

    errors: list[str] = []
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
    if owner_person not in VALID_OWNER:
        errors.append("missing_or_invalid_owner_person_tag")
    if account_type == "equity_comp" and not employer_ticker:
        errors.append("missing_or_invalid_employer_ticker_tag_for_equity_comp")
    if options_capability is not None and options_capability not in VALID_OPTIONS_CAPABILITY:
        errors.append("invalid_options_capability_tag")

    result: dict[str, Any] = {
        "entity": entity,
        "tax_wrapper": wrapper,
        "account_type": account_type,
        "comp_plan": comp_plan,
        "owner_person": owner_person,
        "options_capability": options_capability or "none",
        "valid": len(errors) == 0,
        "errors": errors,
    }
    if employer_ticker:
        result["employer_ticker"] = employer_ticker
    return result


def _parse_scope_types(scope_account_types: list[ScopeAccountType] | None) -> set[str] | None:
    if scope_account_types is None:
        return None
    if not isinstance(scope_account_types, list):
        raise ValueError("scope_account_types must be a list of account type codes.")

    cleaned = [str(v).strip().lower() for v in scope_account_types if str(v).strip()]
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
    scope_types: set[str] | None,
    scope_owner: str = "all",
) -> bool:
    entity = classification.get("entity")
    wrapper = classification.get("tax_wrapper")
    account_type = classification.get("account_type")
    owner_person = classification.get("owner_person")

    if scope_entity != "all" and entity != scope_entity:
        return False
    if scope_wrapper != "all" and wrapper != scope_wrapper:
        return False
    if scope_types is not None and account_type not in scope_types:
        return False
    if scope_owner != "all" and owner_person != scope_owner:
        return False
    return True


# ── Ghostfolio data loading ────────────────────────────────────────────────


async def _load_accounts_with_classification() -> dict[str, Any]:
    payload = await _request("GET", "/api/v1/account")
    rows = payload.get("accounts")
    if not isinstance(rows, list):
        rows = payload.get("items")
    if not isinstance(rows, list):
        rows = []

    env_map = _load_env_account_tag_map()
    accounts: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = _extract_account_id(row)
        tags = _extract_account_tags(row, env_map)
        classification = _classify_account_tags(tags)
        accounts.append(
            {
                **row,
                "account_id": account_id,
                "classification_tags": tags,
                "classification": classification,
            }
        )

    invalid = [a for a in accounts if not a.get("classification", {}).get("valid", False)]
    return {
        "accounts": accounts,
        "summary": {
            "total_accounts": len(accounts),
            "valid_accounts": len(accounts) - len(invalid),
            "invalid_accounts": len(invalid),
        },
        "invalid_accounts": [
            {
                "account_id": a.get("account_id"),
                "name": a.get("name"),
                "errors": a.get("classification", {}).get("errors", []),
                "tags": a.get("classification_tags", []),
            }
            for a in invalid
        ],
    }


async def _load_holdings() -> list[dict[str, Any]]:
    payload = await _request("GET", "/api/v1/portfolio/holdings")
    rows = payload.get("holdings")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def _load_activities() -> list[dict[str, Any]]:
    payload = await _request("GET", "/api/v1/order")
    rows = payload.get("activities")
    if not isinstance(rows, list):
        rows = payload.get("items")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


# ── Activity/holding extraction helpers ─────────────────────────────────────


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


def _extract_activity_date_sort_key(activity: dict[str, Any]) -> tuple[str, str]:
    raw_date = activity.get("date") or activity.get("createdAt") or activity.get("updatedAt") or ""
    if not isinstance(raw_date, str):
        raw_date = str(raw_date)
    return (raw_date, str(activity.get("id", "")))


def _activity_trade_sign(activity_type: str, quantity: float) -> int:
    t = (activity_type or "").strip().upper()
    if t in {"SELL", "WITHDRAWAL", "CASH_OUT", "DELIVERY_OUT"}:
        return -1
    if t in {"BUY", "DEPOSIT", "CASH_IN", "DELIVERY_IN"}:
        return 1
    if quantity < 0:
        return -1
    return 1


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


def _holding_symbol(holding: dict[str, Any]) -> str:
    return normalized_position_symbol(holding)


def _holding_value(holding: dict[str, Any]) -> float:
    for key in ("valueInBaseCurrency", "value", "marketValue", "currentValue"):
        value = _coerce_float(holding.get(key), default=math.nan)
        if not math.isnan(value):
            return value

    quantity = _coerce_float(holding.get("quantity", holding.get("shares", holding.get("units", 0))))
    price = _coerce_float(holding.get("marketPrice", holding.get("price", 0)))
    return quantity * price


def _holding_cost(holding: dict[str, Any]) -> float:
    for key in ("investment", "costBasis", "costBasisInBaseCurrency", "totalCost"):
        value = _coerce_float(holding.get(key), default=math.nan)
        if not math.isnan(value):
            return value

    quantity = _coerce_float(holding.get("quantity", holding.get("shares", holding.get("units", 0))))
    unit_cost = _coerce_float(holding.get("unitPrice", holding.get("averageBuyPrice", 0)))
    return quantity * unit_cost


def _is_cash_like_holding(holding: dict[str, Any]) -> bool:
    return is_cash_like_row(holding)


def _is_ignorable_unscoped_holding(holding: dict[str, Any]) -> bool:
    """Ignore zero-value cash/system rows without account IDs in strict scoped mode."""
    if not _is_cash_like_holding(holding):
        return False

    value = abs(_holding_value(holding))
    cost = abs(_holding_cost(holding))
    quantity = abs(_coerce_float(holding.get("quantity", holding.get("shares", 0.0))))
    market_price = abs(_coerce_float(holding.get("marketPrice", holding.get("price", 0.0))))
    return value < 1e-9 and cost < 1e-9 and quantity < 1e-9 and market_price < 1e-9


def _portfolio_value_semantics(holdings: list[dict[str, Any]]) -> dict[str, float]:
    net_worth_total = sum(max(_holding_value(row), 0.0) for row in holdings)
    cash_balance = sum(max(_holding_value(row), 0.0) for row in holdings if _is_cash_like_holding(row))
    investments_value_ex_cash = max(net_worth_total - cash_balance, 0.0)
    return {
        "investments_value_ex_cash": investments_value_ex_cash,
        "cash_balance": cash_balance,
        "net_worth_total": net_worth_total,
    }


def _aggregate_holdings(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}

    for row in holdings:
        symbol = _holding_symbol(row)
        if not symbol:
            continue

        entry = aggregated.setdefault(
            symbol,
            {
                "symbol": symbol,
                "value": 0.0,
                "cost": 0.0,
                "quantity": 0.0,
                "holdings": 0,
                "asset_class": row.get("assetClass"),
                "currency": row.get("currency"),
            },
        )
        entry["value"] += _holding_value(row)
        entry["cost"] += _holding_cost(row)
        entry["quantity"] += _coerce_float(row.get("quantity", row.get("shares", 0)))
        entry["holdings"] += 1

    return aggregated


def _weights_from_aggregated(
    aggregated: dict[str, dict[str, Any]],
    clip_negatives: bool = True,
) -> tuple[dict[str, float], float]:
    if clip_negatives:
        total_value = sum(max(v["value"], 0.0) for v in aggregated.values())
    else:
        total_value = sum(v["value"] for v in aggregated.values())
    if total_value <= 0:
        return {}, 0.0

    weights = {}
    for symbol, payload in aggregated.items():
        value = payload["value"]
        if clip_negatives:
            value = max(value, 0.0)
        if abs(value) > 0:
            weights[symbol] = value / total_value
    return weights, total_value


def _effective_position_count(weights: dict[str, float]) -> float:
    if not weights:
        return 0.0
    squared_sum = sum(w * w for w in weights.values() if w > 0)
    if squared_sum <= 0:
        return 0.0
    return 1.0 / squared_sum


def _build_holdings_symbol_map(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in holdings:
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
                "marketPrice": None,
            },
        )
        entry["value"] += max(_holding_value(row), 0.0)
        entry["quantity"] += max(_coerce_float(row.get("quantity", row.get("shares", 0.0))), 0.0)
        market_price = _coerce_float(row.get("marketPrice"), default=math.nan)
        if not math.isnan(market_price) and market_price > 0:
            entry["marketPrice"] = market_price

    for symbol, payload in out.items():
        if payload.get("marketPrice") is None:
            qty = payload.get("quantity", 0.0)
            value = payload.get("value", 0.0)
            if qty > 0 and value > 0:
                payload["marketPrice"] = value / qty
            else:
                payload["marketPrice"] = 0.0
    return out


def _position_value_by_symbol(positions: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in positions:
        symbol = _holding_symbol(row)
        if not symbol:
            continue
        values[symbol] = values.get(symbol, 0.0) + max(_holding_value(row), 0.0)
    return values


def _coverage_metrics(
    holdings_symbol_map: dict[str, dict[str, Any]],
    all_positions: list[dict[str, Any]],
    scoped_positions: list[dict[str, Any]],
) -> dict[str, float]:
    all_position_values = _position_value_by_symbol(all_positions)
    scoped_position_values = _position_value_by_symbol(scoped_positions)

    covered_value = 0.0
    scoped_holdings_total_value = 0.0
    for symbol, payload in holdings_symbol_map.items():
        holdings_value = max(_coerce_float(payload.get("value"), 0.0), 0.0)
        if holdings_value <= 0:
            continue

        global_position_value = all_position_values.get(symbol, 0.0)
        scoped_position_value = scoped_position_values.get(symbol, 0.0)
        if scoped_position_value <= 0:
            continue

        if global_position_value > 0:
            scoped_share = min(1.0, scoped_position_value / global_position_value)
            scoped_holdings_value = holdings_value * scoped_share
        else:
            scoped_holdings_value = holdings_value

        scoped_holdings_total_value += scoped_holdings_value
        covered_value += min(scoped_holdings_value, scoped_position_value)

    coverage_pct = (covered_value / scoped_holdings_total_value) if scoped_holdings_total_value > 0 else 1.0
    return {
        "account_aware_coverage_pct": coverage_pct,
        "holdings_total_value": scoped_holdings_total_value,
        "reconstructed_total_value": sum(max(_holding_value(row), 0.0) for row in scoped_positions),
    }


# ── Snapshot cache ──────────────────────────────────────────────────────────


def _snapshot_cache_get(snapshot_id: str | None = None, as_of: str | None = None) -> dict[str, Any] | None:
    latest = _SNAPSHOT_CACHE.get("latest")
    latest_id = _SNAPSHOT_CACHE.get("latest_id")
    created_at = _coerce_float(_SNAPSHOT_CACHE.get("created_at_epoch"), 0.0)
    if not isinstance(latest, dict) or not isinstance(latest_id, str):
        return None

    if snapshot_id and snapshot_id == latest_id:
        return latest
    if (time.time() - created_at) <= SNAPSHOT_CACHE_TTL_SECONDS:
        return latest
    return None


def _snapshot_cache_put(snapshot: dict[str, Any]) -> None:
    snapshot_id = snapshot.get("snapshot_id")
    if isinstance(snapshot_id, str):
        _SNAPSHOT_CACHE["latest_id"] = snapshot_id
    _SNAPSHOT_CACHE["latest"] = snapshot
    _SNAPSHOT_CACHE["created_at_epoch"] = time.time()


# ── Canonical snapshot builder ──────────────────────────────────────────────


async def _build_canonical_snapshot(
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    if as_of:
        raise ValueError("Historical as_of replay is not supported; omit as_of.")
    cached = _snapshot_cache_get(snapshot_id=snapshot_id, as_of=as_of)
    if cached is not None:
        return cached

    account_payload = await _load_accounts_with_classification()
    accounts = account_payload.get("accounts", [])
    account_by_id = {
        account.get("account_id"): account
        for account in accounts
        if isinstance(account, dict) and isinstance(account.get("account_id"), str)
    }

    holdings = await _load_holdings()
    activities = await _load_activities()
    holdings_symbol_map = _build_holdings_symbol_map(holdings)

    position_map: dict[tuple[str, str], dict[str, Any]] = {}
    unassigned_activity_count = 0
    skipped_zero_quantity_activity_count = 0

    for activity in sorted(activities, key=_extract_activity_date_sort_key):
        if bool(activity.get("isDraft")):
            continue

        account_id = _extract_activity_account_id(activity)
        symbol = _extract_activity_symbol(activity)
        if not account_id or not symbol:
            unassigned_activity_count += 1
            continue

        raw_quantity = _coerce_float(activity.get("quantity"), 0.0)
        if abs(raw_quantity) < 1e-12:
            skipped_zero_quantity_activity_count += 1
            continue

        activity_type = str(activity.get("type", "BUY")).strip().upper()
        sign = _activity_trade_sign(activity_type, raw_quantity)
        quantity = abs(raw_quantity)
        quantity_delta = quantity * sign

        trade_value = _coerce_float(activity.get("valueInBaseCurrency"), default=math.nan)
        if math.isnan(trade_value):
            trade_value = _coerce_float(activity.get("value"), default=math.nan)
        if math.isnan(trade_value):
            unit_price_fallback = _coerce_float(
                activity.get("unitPriceInAssetProfileCurrency"),
                default=_coerce_float(activity.get("unitPrice"), 0.0),
            )
            trade_value = abs(quantity * unit_price_fallback)
        trade_value = max(trade_value, 0.0)

        fee = max(
            0.0,
            _coerce_float(
                activity.get("feeInBaseCurrency"),
                default=_coerce_float(activity.get("fee"), 0.0),
            ),
        )
        unit_price = _coerce_float(
            activity.get("unitPriceInAssetProfileCurrency"),
            default=_coerce_float(activity.get("unitPrice"), 0.0),
        )
        data_source = _extract_activity_data_source(activity)
        key = (account_id, symbol)
        entry = position_map.setdefault(
            key,
            {
                "accountId": account_id,
                "symbol": symbol,
                "quantity": 0.0,
                "cost": 0.0,
                "last_trade_price": 0.0,
                "currency": activity.get("currency") or "USD",
                "dataSource": data_source,
                "last_activity_type": activity_type,
            },
        )

        if quantity_delta > 0:
            entry["quantity"] += quantity_delta
            entry["cost"] += trade_value + fee
        else:
            sell_qty = abs(quantity_delta)
            if entry["quantity"] <= 1e-12:
                continue
            avg_cost = (entry["cost"] / entry["quantity"]) if entry["quantity"] > 0 else 0.0
            realized_qty = min(entry["quantity"], sell_qty)
            entry["quantity"] -= realized_qty
            if entry["quantity"] <= 1e-12:
                entry["quantity"] = 0.0
                entry["cost"] = 0.0
            else:
                entry["cost"] = max(0.0, entry["cost"] - (avg_cost * realized_qty))

        if unit_price > 0:
            entry["last_trade_price"] = unit_price
        if data_source:
            entry["dataSource"] = data_source
        entry["last_activity_type"] = activity_type

    positions: list[dict[str, Any]] = []
    for (account_id, symbol), entry in position_map.items():
        quantity = max(_coerce_float(entry.get("quantity"), 0.0), 0.0)
        if quantity <= 1e-9:
            continue

        holdings_meta = holdings_symbol_map.get(symbol, {})
        market_price = _coerce_float(holdings_meta.get("marketPrice"), default=0.0)
        if market_price <= 0:
            market_price = max(_coerce_float(entry.get("last_trade_price"), 0.0), 0.0)

        value = quantity * market_price
        cost = max(_coerce_float(entry.get("cost"), 0.0), 0.0)
        account = account_by_id.get(account_id, {})
        classification = account.get("classification", {}) if isinstance(account, dict) else {}

        positions.append(
            {
                "accountId": account_id,
                "symbol": symbol,
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
                "options_capability": classification.get("options_capability"),
            }
        )

    # Attach account balances as explicit cash positions so scoping remains account aware.
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = account.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            continue
        balance = _coerce_float(account.get("balance"), 0.0)
        if abs(balance) <= 1e-9:
            continue
        classification = account.get("classification", {})
        positions.append(
            {
                "accountId": account_id,
                "symbol": cash_position_symbol(account.get("currency")),
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
                "options_capability": classification.get("options_capability"),
            }
        )

    holdings_total_value = sum(max(_holding_value(row), 0.0) for row in holdings)
    reconstructed_total_value = sum(max(_holding_value(row), 0.0) for row in positions)

    coverage = _coverage_metrics(holdings_symbol_map, positions, positions)
    account_aware_coverage_pct = coverage["account_aware_coverage_pct"]
    reconciliation_drift_pct = (
        abs(reconstructed_total_value - holdings_total_value) / holdings_total_value
        if holdings_total_value > 0
        else 0.0
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    resolved_snapshot_id = snapshot_id or content_addressed_snapshot_id(
        positions=positions,
        accounts=[account for account in accounts if isinstance(account, dict)],
        holdings=holdings,
        prefix="snap",
    )

    warnings: list[str] = []
    if unassigned_activity_count > 0:
        warnings.append(f"{unassigned_activity_count} activities were skipped due to missing accountId or symbol.")
    if skipped_zero_quantity_activity_count > 0:
        warnings.append(f"{skipped_zero_quantity_activity_count} zero-quantity activities were skipped.")
    if account_aware_coverage_pct < MIN_SCOPE_COVERAGE_PCT:
        warnings.append(
            f"Account-aware coverage is {account_aware_coverage_pct:.2%}, below target {MIN_SCOPE_COVERAGE_PCT:.2%}."
        )

    snapshot = {
        "snapshot_id": resolved_snapshot_id,
        "as_of": now_iso,
        "positions": positions,
        "coverage": {
            "account_aware_coverage_pct": account_aware_coverage_pct,
            "reconciliation_drift_pct": reconciliation_drift_pct,
            "holdings_total_value": holdings_total_value,
            "reconstructed_total_value": reconstructed_total_value,
        },
        "holdings_symbol_map": holdings_symbol_map,
        "account_payload": account_payload,
        "warnings": warnings,
        "provenance": {
            "position_sources": ["ghostfolio:/api/v1/order", "ghostfolio:/api/v1/portfolio/holdings"],
            "account_source": "ghostfolio:/api/v1/account",
        },
    }
    _snapshot_cache_put(snapshot)
    return snapshot


# ── Scoped holdings loader ──────────────────────────────────────────────────


async def _load_scoped_holdings(
    scope_entity: str,
    scope_wrapper: str,
    scope_account_types: list[ScopeAccountType] | None,
    strict: bool,
    snapshot_id: str | None = None,
    as_of: str | None = None,
    scope_owner: str = "all",
) -> dict[str, Any]:
    scope_entity = scope_entity.strip().lower()
    scope_wrapper = scope_wrapper.strip().lower()
    scope_owner = scope_owner.strip().lower() if isinstance(scope_owner, str) else "all"
    scope_types = _parse_scope_types(scope_account_types)

    if scope_entity not in {"all", *VALID_ENTITY}:
        raise ValueError("scope_entity must be one of: all, personal, trust")
    if scope_wrapper not in {"all", *VALID_WRAPPER}:
        raise ValueError("scope_wrapper must be one of: all, taxable, tax_deferred, tax_exempt")
    if scope_owner not in {"all", *VALID_OWNER}:
        raise ValueError("scope_owner must be one of: all, Principal, Spouse, joint")

    snapshot = await _build_canonical_snapshot(snapshot_id=snapshot_id, as_of=as_of)
    account_payload = snapshot.get("account_payload", {})
    accounts = account_payload["accounts"]

    if strict and account_payload["summary"]["invalid_accounts"] > 0:
        invalid = ", ".join(
            a.get("account_id") or "<unknown>" for a in account_payload.get("invalid_accounts", [])
        )
        raise ValueError(
            "Account taxonomy validation failed in strict mode. "
            "Add entity:*, tax_wrapper:*, account_type:* tags to all accounts. "
            f"Invalid accounts: {invalid}"
        )

    scoped_account_ids = {
        a.get("account_id")
        for a in accounts
        if isinstance(a.get("account_id"), str)
        and _matches_scope(a.get("classification", {}), scope_entity, scope_wrapper, scope_types, scope_owner)
    }

    holdings = [
        row for row in snapshot.get("positions", [])
        if isinstance(row, dict)
    ]

    is_scoped = (
        scope_entity != "all"
        or scope_wrapper != "all"
        or (scope_types is not None and len(scope_types) > 0)
        or scope_owner != "all"
    )

    included: list[dict[str, Any]] = []
    excluded = 0

    for holding in holdings:
        if not is_scoped:
            included.append(holding)
            continue

        account_id = _extract_holding_account_id(holding)
        if not account_id:
            excluded += 1
            continue

        if account_id in scoped_account_ids:
            included.append(holding)
        else:
            excluded += 1

    coverage = snapshot.get("coverage", {})
    if is_scoped:
        coverage = {
            **coverage,
            **_coverage_metrics(
                snapshot.get("holdings_symbol_map", {}),
                holdings,
                included,
            ),
        }
    coverage_pct = _coerce_float(coverage.get("account_aware_coverage_pct"), 0.0)
    if strict and is_scoped and coverage_pct < MIN_SCOPE_COVERAGE_PCT:
        raise ValueError(
            "Account-aware coverage is "
            f"{coverage_pct:.2%}, below strict minimum {MIN_SCOPE_COVERAGE_PCT:.2%}."
        )

    warnings: list[str] = list(snapshot.get("warnings", []))
    if is_scoped and excluded > 0:
        warnings.append(f"{excluded} positions were excluded by account scope.")

    return {
        "accounts": accounts,
        "accounts_summary": account_payload["summary"],
        "invalid_accounts": account_payload.get("invalid_accounts", []),
        "holdings": included,
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_as_of": snapshot.get("as_of"),
        "coverage": coverage,
        "provenance": snapshot.get("provenance", {}),
        "scope": {
            "entity": scope_entity,
            "tax_wrapper": scope_wrapper,
            "account_types": sorted(scope_types) if scope_types is not None else "all",
            "owner": scope_owner,
            "strict": strict,
            "scoped_account_ids": sorted(a for a in scoped_account_ids if isinstance(a, str)),
            "excluded_holdings": excluded,
            "coverage_pct": coverage_pct,
        },
        "warnings": warnings,
    }


# ── Register tools ──────────────────────────────────────────────────────────


async def validate_account_taxonomy(strict: bool = True) -> dict[str, Any]:
    """Validate Ghostfolio account taxonomy tags used for scoped analytics."""
    payload = await _load_accounts_with_classification()
    invalid_accounts = payload.get("invalid_accounts", [])

    if strict and invalid_accounts:
        return {
            "ok": False,
            "message": "Taxonomy validation failed in strict mode.",
            "summary": payload["summary"],
            "invalid_accounts": invalid_accounts,
            "required_tags": [
                "entity:personal|trust",
                "tax_wrapper:taxable|tax_deferred|tax_exempt",
                "account_type:brokerage|roth_ira|trad_ira|401k|403b|457b|solo_401k|sep_ira|simple_ira|hsa|529|esa|custodial_utma|custodial_ugma|equity_comp|trust_taxable|trust_exempt|trust_irrevocable|trust_revocable|trust_qsst|other",
                "comp_plan:rsu|iso|nso|psu|espp|other (required if account_type:equity_comp)",
                "owner_person:Principal|Spouse|joint",
                "employer_ticker:MSFT|GOOG|... (required if account_type:equity_comp)",
                "options_capability:none|long_premium|vertical_spreads (optional)",
            ],
        }

    return {
        "ok": len(invalid_accounts) == 0,
        "summary": payload["summary"],
        "invalid_accounts": invalid_accounts,
    }


def register_holdings_tools(server) -> None:
    """Register account taxonomy validation tools on the FastMCP server."""
    server.tool()(validate_account_taxonomy)
