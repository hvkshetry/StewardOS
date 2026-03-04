#!/usr/bin/env python3
"""Condensed portfolio analytics MCP server.

This server treats Ghostfolio as the source of truth for positions and account scope.
It provides a tight set of tools for portfolio state, risk, drift, and TLH scanning.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from fastmcp import FastMCP
from scipy.stats import t as student_t


server = FastMCP("portfolio-analytics")


GHOSTFOLIO_URL = os.getenv("GHOSTFOLIO_URL", "http://localhost:8224")
GHOSTFOLIO_TOKEN = os.getenv("GHOSTFOLIO_TOKEN", "")
ACCOUNT_TAG_MAP_ENV = "GHOSTFOLIO_ACCOUNT_TAG_MAP"
YFINANCE_CACHE_DIR = os.getenv("YFINANCE_CACHE_DIR", "/tmp/yfinance-cache")

os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
try:
    yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
except Exception:
    # Some yfinance versions do not expose this helper; continue without hard-failing startup.
    pass

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
BINDING_ES_LIMIT = 0.025
MIN_SCOPE_COVERAGE_PCT = 0.99
SNAPSHOT_CACHE_TTL_SECONDS = 120


_SNAPSHOT_CACHE: dict[str, Any] = {
    "latest_id": None,
    "latest": None,
    "created_at_epoch": 0.0,
}


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if GHOSTFOLIO_TOKEN:
        headers["Authorization"] = f"Bearer {GHOSTFOLIO_TOKEN}"
    return headers


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=GHOSTFOLIO_URL, headers=_headers(), timeout=30.0)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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

    return {
        "entity": entity,
        "tax_wrapper": wrapper,
        "account_type": account_type,
        "comp_plan": comp_plan,
        "valid": len(errors) == 0,
        "errors": errors,
    }


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
) -> bool:
    entity = classification.get("entity")
    wrapper = classification.get("tax_wrapper")
    account_type = classification.get("account_type")

    if scope_entity != "all" and entity != scope_entity:
        return False
    if scope_wrapper != "all" and wrapper != scope_wrapper:
        return False
    if scope_types is not None and account_type not in scope_types:
        return False
    return True


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


def _activity_trade_sign(activity_type: str, quantity: float) -> int:
    t = (activity_type or "").strip().upper()
    if t in {"SELL", "WITHDRAWAL", "CASH_OUT", "DELIVERY_OUT"}:
        return -1
    if t in {"BUY", "DEPOSIT", "CASH_IN", "DELIVERY_IN"}:
        return 1
    if quantity < 0:
        return -1
    return 1


def _snapshot_cache_get(snapshot_id: str | None = None, as_of: str | None = None) -> dict[str, Any] | None:
    latest = _SNAPSHOT_CACHE.get("latest")
    latest_id = _SNAPSHOT_CACHE.get("latest_id")
    created_at = _coerce_float(_SNAPSHOT_CACHE.get("created_at_epoch"), 0.0)
    if not isinstance(latest, dict) or not isinstance(latest_id, str):
        return None

    if snapshot_id and snapshot_id == latest_id:
        return latest
    if as_of and as_of == latest.get("as_of"):
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


async def _build_canonical_snapshot(
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
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

    holdings_total_value = sum(max(_holding_value(row), 0.0) for row in holdings)
    reconstructed_total_value = sum(max(_holding_value(row), 0.0) for row in positions)

    position_value_by_symbol: dict[str, float] = {}
    for row in positions:
        symbol = _holding_symbol(row)
        if not symbol:
            continue
        position_value_by_symbol[symbol] = position_value_by_symbol.get(symbol, 0.0) + max(_holding_value(row), 0.0)

    covered_value = 0.0
    for symbol, payload in holdings_symbol_map.items():
        holdings_value = max(_coerce_float(payload.get("value"), 0.0), 0.0)
        covered_value += min(holdings_value, position_value_by_symbol.get(symbol, 0.0))

    account_aware_coverage_pct = (covered_value / holdings_total_value) if holdings_total_value > 0 else 1.0
    reconciliation_drift_pct = (
        abs(reconstructed_total_value - holdings_total_value) / holdings_total_value
        if holdings_total_value > 0
        else 0.0
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    snapshot_hash = hashlib.sha1(
        (
            f"{now_iso}|{len(positions)}|{len(activities)}|"
            f"{holdings_total_value:.6f}|{reconstructed_total_value:.6f}"
        ).encode("utf-8")
    ).hexdigest()[:12]
    resolved_snapshot_id = snapshot_id or f"snap_{snapshot_hash}"

    warnings: list[str] = []
    if as_of:
        warnings.append("Historical as_of replay is not supported; returned latest available snapshot.")
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
        "account_payload": account_payload,
        "warnings": warnings,
        "provenance": {
            "position_sources": ["ghostfolio:/api/v1/order", "ghostfolio:/api/v1/portfolio/holdings"],
            "account_source": "ghostfolio:/api/v1/account",
        },
    }
    _snapshot_cache_put(snapshot)
    return snapshot


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


def _is_ignorable_unscoped_holding(holding: dict[str, Any]) -> bool:
    """Ignore zero-value cash/system rows without account IDs in strict scoped mode."""
    symbol = _holding_symbol(holding)
    asset_class = str(holding.get("assetClass", "")).strip().upper()
    asset_sub_class = str(holding.get("assetSubClass", "")).strip().upper()

    cash_like = (
        asset_sub_class == "CASH"
        or asset_class == "LIQUIDITY"
        or symbol in {"USD", "USX", "CASH"}
    )
    if not cash_like:
        return False

    value = abs(_holding_value(holding))
    cost = abs(_holding_cost(holding))
    quantity = abs(_coerce_float(holding.get("quantity", holding.get("shares", 0.0))))
    market_price = abs(_coerce_float(holding.get("marketPrice", holding.get("price", 0.0))))
    return value < 1e-9 and cost < 1e-9 and quantity < 1e-9 and market_price < 1e-9


def _holding_symbol(holding: dict[str, Any]) -> str:
    symbol = holding.get("symbol") or holding.get("ticker")
    if not isinstance(symbol, str):
        return ""
    return symbol.strip().upper()


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


_CASH_LIKE_SYMBOLS = {
    "USD", "USX", "CASH", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD",
    "HKD", "SGD", "INR", "CNY", "KRW", "TWD", "NZD", "SEK", "NOK",
    "DKK", "MXN", "BRL", "ZAR",
}


def _is_cash_like_holding(holding: dict[str, Any]) -> bool:
    symbol = _holding_symbol(holding)
    asset_class = str(holding.get("assetClass", "")).strip().upper()
    asset_sub_class = str(holding.get("assetSubClass", "")).strip().upper()
    return (
        asset_sub_class == "CASH"
        or asset_class == "LIQUIDITY"
        or symbol in _CASH_LIKE_SYMBOLS
    )


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


def _normalized_es_limit(requested_es_limit: float) -> tuple[float, list[str]]:
    warnings: list[str] = []
    requested = _coerce_float(requested_es_limit, BINDING_ES_LIMIT)
    if requested <= 0:
        warnings.append(
            f"Invalid es_limit ({requested_es_limit}); using binding limit {BINDING_ES_LIMIT:.4f}."
        )
        requested = BINDING_ES_LIMIT

    effective = min(requested, BINDING_ES_LIMIT)
    if requested > BINDING_ES_LIMIT:
        warnings.append(
            f"Requested es_limit {requested:.4f} exceeds binding policy limit {BINDING_ES_LIMIT:.4f}; binding limit enforced."
        )
    return effective, warnings


def _normalize_target_allocations(target_allocations: Any) -> dict[str, float]:
    if isinstance(target_allocations, str):
        target_allocations = json.loads(target_allocations)

    if not isinstance(target_allocations, dict):
        raise ValueError("target_allocations must be a dict of {symbol: weight}")

    parsed: dict[str, float] = {}
    for symbol, weight in target_allocations.items():
        if not isinstance(symbol, str):
            continue
        parsed[symbol.strip().upper()] = max(_coerce_float(weight), 0.0)

    total = sum(parsed.values())
    if total <= 0:
        raise ValueError("target_allocations must contain positive weights")

    return {k: v / total for k, v in parsed.items()}


def _filter_tradeable_symbols(weights: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    excluded = {
        "USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "HKD", "SGD",
        "INR", "CNY", "KRW", "TWD", "NZD", "SEK", "NOK", "DKK", "MXN",
        "BRL", "ZAR", "CASH",
    }
    tradeable = {}
    excluded_symbols = []
    for symbol, weight in weights.items():
        if not symbol or symbol in excluded or symbol.endswith("=X"):
            excluded_symbols.append(symbol)
        else:
            tradeable[symbol] = weight
    return tradeable, excluded_symbols


def _download_prices(
    symbols: list[str],
    lookback_days: int,
) -> tuple[pd.DataFrame | None, str | None]:
    """Download close prices from yfinance. Returns (prices_df, error_message)."""
    start_date = (datetime.now(timezone.utc) - timedelta(days=max(lookback_days * 2, 120))).date().isoformat()
    try:
        data = yf.download(
            tickers=symbols,
            start=start_date,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        return None, f"yfinance download failed: {type(exc).__name__}: {exc}"

    if data is None or data.empty:
        return None, "yfinance returned empty data"

    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            prices = data["Close"]
        else:
            first_level = data.columns.get_level_values(0)[0]
            prices = data[first_level]
    else:
        if "Close" in data.columns:
            prices = data[["Close"]]
            prices.columns = [symbols[0]]
        else:
            prices = data.copy()
            if isinstance(prices, pd.Series):
                prices = prices.to_frame(name=symbols[0])

    prices.columns = [str(col).upper() for col in prices.columns]
    return prices, None


def _download_returns(
    weights: dict[str, float],
    lookback_days: int,
    holdings_meta: dict[str, dict[str, Any]] | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    original_weight_sum = sum(weights.values())
    tradeable, excluded_symbols = _filter_tradeable_symbols(weights)
    tradeable_weight_sum = sum(tradeable.values())

    empty_quality = {
        "missing_symbols": sorted(tradeable.keys()) if tradeable else [],
        "excluded_symbols": excluded_symbols,
        "available_symbols": [],
        "original_weight_sum": original_weight_sum,
        "tradeable_weight_sum": tradeable_weight_sum,
        "available_weight_sum": 0.0,
        "weight_coverage_pct": 0.0,
        "renormalized": False,
        "yfinance_error": None,
        "observations": 0,
        "nan_fill_symbols": [],
        "data_quality_warnings": [],
    }

    if not tradeable:
        empty_quality["data_quality_warnings"].append(
            "No tradeable symbols in portfolio; all positions are cash or excluded."
        )
        return pd.Series(dtype=float), empty_quality

    symbols = sorted(tradeable.keys())

    prices, yf_error = _download_prices(symbols, lookback_days)
    if prices is None or prices.empty:
        empty_quality["yfinance_error"] = yf_error
        empty_quality["data_quality_warnings"].append(
            f"Market data download failed: {yf_error}"
        )
        return pd.Series(dtype=float), empty_quality

    returns = prices.pct_change().dropna(how="all")
    if returns.empty:
        empty_quality["yfinance_error"] = "No return data after pct_change"
        return pd.Series(dtype=float), empty_quality

    available = [s for s in symbols if s in returns.columns]
    if not available:
        empty_quality["yfinance_error"] = "No symbols matched in downloaded data"
        return pd.Series(dtype=float), empty_quality

    # Handle partial NaN rows: forward-fill gaps up to 3 days, then fill remaining with 0
    # and track which symbols had fills applied
    nan_fill_symbols = []
    for sym in available:
        nan_count = int(returns[sym].isna().sum())
        if nan_count > 0:
            nan_fill_symbols.append({"symbol": sym, "nan_days": nan_count})
    returns[available] = returns[available].ffill(limit=3).fillna(0.0)

    available_weight_sum = sum(tradeable[s] for s in available)
    if available_weight_sum <= 0:
        empty_quality["available_symbols"] = available
        return pd.Series(dtype=float), empty_quality

    missing = [s for s in symbols if s not in available]
    renormalized = len(missing) > 0
    normalized = {s: tradeable[s] / available_weight_sum for s in available}
    weighted = returns[available].mul(pd.Series(normalized), axis=1).sum(axis=1)
    weighted = weighted.tail(lookback_days)

    weight_coverage_pct = available_weight_sum / original_weight_sum if original_weight_sum > 0 else 0.0

    warnings: list[str] = []
    if weight_coverage_pct < 0.50:
        warnings.append(
            f"UNRELIABLE: Risk computed on only {weight_coverage_pct:.1%} of portfolio weight. "
            f"Missing symbols: {', '.join(missing)}. Tail risk is likely severely understated."
        )
    elif weight_coverage_pct < 0.90:
        warnings.append(
            f"Risk computed on {weight_coverage_pct:.1%} of portfolio weight; "
            f"tail risk likely understated. Missing: {', '.join(missing)}."
        )
    if renormalized:
        warnings.append(
            f"Weights renormalized from {available_weight_sum:.3f} to 1.0 "
            f"after dropping {len(missing)} symbols without market data."
        )
    if nan_fill_symbols:
        fills_desc = ", ".join(f"{s['symbol']}({s['nan_days']}d)" for s in nan_fill_symbols)
        warnings.append(f"NaN returns filled (ffill 3d, then 0): {fills_desc}")

    data_quality = {
        "missing_symbols": missing,
        "excluded_symbols": excluded_symbols,
        "available_symbols": available,
        "original_weight_sum": original_weight_sum,
        "tradeable_weight_sum": tradeable_weight_sum,
        "available_weight_sum": available_weight_sum,
        "weight_coverage_pct": weight_coverage_pct,
        "renormalized": renormalized,
        "yfinance_error": yf_error,
        "observations": int(len(weighted)),
        "nan_fill_symbols": nan_fill_symbols,
        "data_quality_warnings": warnings,
    }

    return weighted, data_quality


def _risk_metrics(
    returns: pd.Series,
    es_limit: float,
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if returns.empty or len(returns) < 30:
        return {
            "status": "insufficient_data",
            "message": "Need at least 30 daily return points to compute risk metrics.",
            "sample_size": int(len(returns)),
            "es_limit": es_limit,
        }

    n = len(returns)
    losses = -returns.values
    var_95 = float(np.quantile(losses, 0.95))
    var_975 = float(np.quantile(losses, 0.975))

    tail_95 = losses[losses >= var_95]
    tail_975 = losses[losses >= var_975]
    tail_975_count = int(len(tail_975))

    if len(tail_95) > 0:
        es_95 = float(np.mean(tail_95))
    else:
        es_95 = var_95

    if tail_975_count > 0:
        es_975 = float(np.mean(tail_975))
    else:
        es_975 = var_975

    volatility_annual = float(np.std(returns.values, ddof=1) * np.sqrt(252))

    cumulative = (1.0 + returns).cumprod()
    running_max = cumulative.cummax()
    max_drawdown = float(((cumulative / running_max) - 1.0).min())

    # Determine status based on data coverage and ES
    weight_coverage = 1.0
    risk_warnings: list[str] = []
    if data_quality:
        weight_coverage = data_quality.get("weight_coverage_pct", 1.0)
        risk_warnings.extend(data_quality.get("data_quality_warnings", []))

    if tail_975_count < 5:
        risk_warnings.append(
            f"ES estimate unstable: only {tail_975_count} observations in 97.5% tail "
            f"(from {n} total). Consider longer lookback or parametric model."
        )
    elif tail_975_count < 10:
        risk_warnings.append(
            f"ES estimate has limited precision: {tail_975_count} tail observations."
        )

    if weight_coverage < 0.50:
        status = "unreliable"
    elif es_975 > es_limit:
        status = "critical"
    else:
        status = "ok"

    return {
        "status": status,
        "sample_size": n,
        "var_95_1d": var_95,
        "var_975_1d": var_975,
        "es_95_1d": es_95,
        "es_975_1d": es_975,
        "es_975_1d_historical": es_975,
        "es_limit": es_limit,
        "es_utilization": (es_975 / es_limit) if es_limit > 0 else None,
        "annualized_volatility": volatility_annual,
        "max_drawdown": max_drawdown,
        "tail_sample_size_975": tail_975_count,
        "risk_warnings": risk_warnings,
    }


def _fit_student_t(returns: np.ndarray) -> dict[str, Any] | None:
    """Fit Student-t distribution via MLE. Returns fit params or None if inappropriate."""
    if len(returns) < 30:
        return None
    try:
        df, loc, scale = student_t.fit(returns)
    except Exception:
        return None

    if df <= 1:
        # ES undefined for df <= 1
        return None

    variance_infinite = bool(df <= 2)
    # If df > 30, tails are effectively normal — historical is fine
    normal_like = bool(df > 30)

    # KS test p-value vs normal for diagnostics
    try:
        from scipy.stats import kstest, norm
        ks_stat, ks_pvalue = kstest(returns, "norm", args=(np.mean(returns), np.std(returns, ddof=1)))
    except Exception:
        ks_pvalue = None

    return {
        "df": float(df),
        "loc": float(loc),
        "scale": float(scale),
        "variance_infinite": variance_infinite,
        "normal_like": normal_like,
        "ks_pvalue_vs_normal": float(ks_pvalue) if ks_pvalue is not None else None,
        "fat_tailed": bool(not normal_like and df < 30),
    }


def _parametric_es_student_t(
    df: float,
    loc: float,
    scale: float,
    confidence: float = 0.975,
) -> float | None:
    """Closed-form Student-t ES (McNeil, Frey & Embrechts).

    Computes ES on the LOSS distribution: losses = -returns.
    The loc/scale should be fit on returns, so we negate loc for loss ES.
    """
    if df <= 1:
        return None

    # Quantile of standardized t at confidence level (loss tail)
    q = student_t.ppf(confidence, df)

    # ES formula for standardized Student-t
    # ES_std = (df + q^2) / (df - 1) * t.pdf(q, df) / (1 - confidence)
    es_standardized = ((df + q ** 2) / (df - 1)) * student_t.pdf(q, df) / (1 - confidence)

    # Scale and shift: ES_loss = -loc + scale * ES_std
    # (negate loc because fit was on returns, ES is on losses)
    es_loss = -loc + scale * es_standardized

    return float(es_loss)


def _risk_metrics_with_model(
    returns: pd.Series,
    es_limit: float,
    data_quality: dict[str, Any] | None = None,
    risk_model: str = "auto",
) -> dict[str, Any]:
    """Extended risk metrics with optional Student-t parametric ES."""
    base = _risk_metrics(returns, es_limit, data_quality)

    if base.get("status") == "insufficient_data":
        base["risk_model_used"] = "none"
        return base

    losses = -returns.values
    student_t_fit = None
    parametric_es_975 = None
    risk_model_used = "historical"

    if risk_model in ("student_t", "auto"):
        fit = _fit_student_t(returns.values)
        if fit is not None and not fit["normal_like"]:
            student_t_fit = fit
            es_val = _parametric_es_student_t(
                fit["df"], fit["loc"], fit["scale"], confidence=0.975,
            )
            if es_val is not None and es_val > 0:
                parametric_es_975 = es_val
                risk_model_used = "student_t"

    historical_es = base["es_975_1d_historical"]

    if risk_model == "auto" and parametric_es_975 is not None:
        # Conservative envelope: max of historical and parametric
        effective_es = max(historical_es, parametric_es_975)
        risk_model_used = "student_t" if parametric_es_975 >= historical_es else "historical"
    elif risk_model == "student_t" and parametric_es_975 is not None:
        effective_es = parametric_es_975
    else:
        effective_es = historical_es
        risk_model_used = "historical"

    base["es_975_1d"] = effective_es
    base["es_975_1d_parametric"] = parametric_es_975
    base["risk_model_used"] = risk_model_used
    base["student_t_fit"] = student_t_fit

    # Recompute status with effective ES
    weight_coverage = 1.0
    if data_quality:
        weight_coverage = data_quality.get("weight_coverage_pct", 1.0)
    if weight_coverage < 0.50:
        base["status"] = "unreliable"
    elif effective_es > es_limit:
        base["status"] = "critical"
    else:
        base["status"] = "ok"

    base["es_utilization"] = (effective_es / es_limit) if es_limit > 0 else None

    return base


def _compute_illiquid_overlay(
    illiquid_overrides: list[dict[str, Any]],
    liquid_vol_annual: float,
    liquid_weight: float,
    student_t_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute portfolio variance expansion including illiquid positions.

    Uses full variance formula:
      σ_p² = w_L² σ_L² + Σ w_i² σ_i²
             + 2 Σ w_L w_i ρ_iL σ_i σ_L
             + 2 Σ_{i<j} w_i w_j ρ_ij σ_i σ_j

    For illiquid-illiquid cross-correlations, uses one-factor model:
      ρ_ij = ρ_i * ρ_j  (correlation through equity factor)
    unless explicit overrides are provided.
    """
    if not illiquid_overrides:
        return {"overlay_applied": False}

    illiquid_positions = []
    total_illiquid_weight = 0.0

    for override in illiquid_overrides:
        w = _coerce_float(override.get("weight"), 0.0)
        vol = _coerce_float(override.get("annual_vol"), 0.30)
        rho = _coerce_float(override.get("rho_equity"), 0.50)
        discount = _coerce_float(override.get("liquidity_discount"), 0.0)
        symbol = str(override.get("symbol", "UNKNOWN"))

        if w <= 0:
            continue

        # liquidity_discount adjusts weight (valuation haircut), not variance
        effective_weight = w * (1.0 - discount)
        total_illiquid_weight += effective_weight

        pos_entry: dict[str, Any] = {
            "symbol": symbol,
            "weight": effective_weight,
            "annual_vol": vol,
            "rho_equity": rho,
            "liquidity_discount": discount,
        }
        # Passthrough optional staleness metadata from skill layer
        if override.get("valuation_age_days") is not None:
            pos_entry["valuation_age_days"] = int(override["valuation_age_days"])
        if override.get("mark_staleness"):
            pos_entry["mark_staleness"] = str(override["mark_staleness"])
        illiquid_positions.append(pos_entry)

    if not illiquid_positions:
        return {"overlay_applied": False}

    # Renormalize weights so liquid + illiquid = 1.0
    total_weight = liquid_weight + total_illiquid_weight
    if total_weight <= 0:
        return {"overlay_applied": False}

    w_L = liquid_weight / total_weight
    σ_L = liquid_vol_annual

    # Portfolio variance: start with liquid component
    var_p = (w_L ** 2) * (σ_L ** 2)

    # Add illiquid own-variance and liquid-illiquid covariance
    for pos in illiquid_positions:
        w_i = pos["weight"] / total_weight
        σ_i = pos["annual_vol"]
        ρ_iL = pos["rho_equity"]

        var_p += (w_i ** 2) * (σ_i ** 2)
        var_p += 2 * w_L * w_i * ρ_iL * σ_i * σ_L

    # Add illiquid-illiquid cross-terms (one-factor model)
    for i in range(len(illiquid_positions)):
        for j in range(i + 1, len(illiquid_positions)):
            pos_i = illiquid_positions[i]
            pos_j = illiquid_positions[j]
            w_i = pos_i["weight"] / total_weight
            w_j = pos_j["weight"] / total_weight
            σ_i = pos_i["annual_vol"]
            σ_j = pos_j["annual_vol"]
            # One-factor: ρ_ij ≈ ρ_i * ρ_j
            ρ_ij = pos_i["rho_equity"] * pos_j["rho_equity"]
            var_p += 2 * w_i * w_j * ρ_ij * σ_i * σ_j

    adjusted_vol_annual = float(np.sqrt(max(var_p, 0.0)))
    adjusted_vol_daily = adjusted_vol_annual / np.sqrt(252)

    # ES adjustment: use Student-t if available, otherwise normal approximation
    if student_t_fit and student_t_fit.get("df", 100) <= 30:
        df = student_t_fit["df"]
        q = student_t.ppf(0.975, df)
        es_factor = ((df + q ** 2) / (df - 1)) * student_t.pdf(q, df) / 0.025
        adjusted_es_975_1d = adjusted_vol_daily * es_factor
    else:
        # Normal approximation: ES_975 ≈ σ * φ(z) / (1-α) where z = Φ⁻¹(0.975)
        from scipy.stats import norm
        z = norm.ppf(0.975)
        adjusted_es_975_1d = adjusted_vol_daily * norm.pdf(z) / 0.025

    return {
        "overlay_applied": True,
        "illiquid_weight_pct": total_illiquid_weight / total_weight,
        "liquid_weight_pct": w_L,
        "illiquid_positions": illiquid_positions,
        "unadjusted_vol_annual": σ_L,
        "adjusted_vol_annual": adjusted_vol_annual,
        "adjusted_vol_daily": float(adjusted_vol_daily),
        "adjusted_es_975_1d": float(adjusted_es_975_1d),
        "method": "student_t_overlay" if (student_t_fit and student_t_fit.get("df", 100) <= 30) else "normal_overlay",
    }


# ---------------------------------------------------------------------------
# Phase 4: FX Risk
# ---------------------------------------------------------------------------

def _identify_fx_exposures(
    aggregated: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """Identify non-USD currency exposures and map to yfinance FX pairs."""
    fx_map: dict[str, dict[str, Any]] = {}  # currency -> {weight, symbols, yf_pair}

    for symbol, payload in aggregated.items():
        currency = str(payload.get("currency", "USD")).strip().upper()
        if currency == "USD" or not currency:
            continue
        weight = weights.get(symbol, 0.0)
        if weight <= 0:
            continue

        if currency not in fx_map:
            # yfinance convention: USDINR=X quotes INR per 1 USD
            yf_pair = f"USD{currency}=X"
            fx_map[currency] = {
                "currency": currency,
                "yf_pair": yf_pair,
                "total_weight": 0.0,
                "symbols": [],
            }
        fx_map[currency]["total_weight"] += weight
        fx_map[currency]["symbols"].append(symbol)

    return fx_map


def _download_fx_returns(
    fx_pairs: list[str],
    lookback_days: int,
) -> tuple[pd.DataFrame | None, str | None]:
    """Download FX rate return series from yfinance."""
    if not fx_pairs:
        return None, None
    prices, error = _download_prices(fx_pairs, lookback_days)
    if prices is None:
        return None, error
    returns = prices.pct_change().dropna(how="all")
    returns.columns = [str(c).upper() for c in returns.columns]
    # Forward-fill up to 3 days for calendar misalignment
    returns = returns.ffill(limit=3).fillna(0.0)
    return returns, error


def _adjust_returns_for_fx(
    asset_returns: pd.DataFrame,
    fx_returns: pd.DataFrame,
    fx_map: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Adjust local-currency returns to USD returns.

    Correct formula: r_usd = (1 + r_local) / (1 + r_usdinr) - 1
    When INR weakens (USDINR rises), USD value of INR assets falls.
    """
    adjusted = asset_returns.copy()

    for currency, info in fx_map.items():
        yf_pair = info["yf_pair"]
        if yf_pair not in fx_returns.columns:
            continue

        for symbol in info["symbols"]:
            if symbol not in adjusted.columns:
                continue

            # Align dates
            common_idx = adjusted.index.intersection(fx_returns.index)
            if len(common_idx) == 0:
                continue

            local_ret = adjusted.loc[common_idx, symbol]
            fx_ret = fx_returns.loc[common_idx, yf_pair]

            # r_usd = (1 + r_local) / (1 + r_usdinr) - 1
            adjusted.loc[common_idx, symbol] = (1 + local_ret) / (1 + fx_ret) - 1

    return adjusted


# ---------------------------------------------------------------------------
# Phase 5: Volatility Regime Detection
# ---------------------------------------------------------------------------

def _detect_vol_regime(
    returns: pd.Series,
    short_window: int = 21,
    long_window: int = 63,
) -> dict[str, Any]:
    """Detect volatility regime from return series."""
    if len(returns) < long_window:
        return {
            "current_regime": "insufficient_data",
            "short_vol": None,
            "long_vol": None,
            "vol_ratio": None,
            "days_in_regime": None,
        }

    short_vol = float(np.std(returns.values[-short_window:], ddof=1) * np.sqrt(252))
    long_vol = float(np.std(returns.values[-long_window:], ddof=1) * np.sqrt(252))

    if long_vol <= 0:
        vol_ratio = 1.0
    else:
        vol_ratio = short_vol / long_vol

    if vol_ratio < 0.7:
        regime = "low"
    elif vol_ratio <= 1.3:
        regime = "normal"
    elif vol_ratio <= 2.0:
        regime = "elevated"
    else:
        regime = "crisis"

    # Estimate days in current regime by scanning backward
    days_in_regime = 0
    if len(returns) >= short_window:
        for i in range(short_window, min(len(returns), long_window * 3)):
            window = returns.values[-i:]
            w_vol = float(np.std(window[:short_window], ddof=1) * np.sqrt(252))
            if long_vol > 0:
                w_ratio = w_vol / long_vol
            else:
                w_ratio = 1.0

            if w_ratio < 0.7:
                w_regime = "low"
            elif w_ratio <= 1.3:
                w_regime = "normal"
            elif w_ratio <= 2.0:
                w_regime = "elevated"
            else:
                w_regime = "crisis"

            if w_regime == regime:
                days_in_regime = i
            else:
                break
        if days_in_regime == 0:
            days_in_regime = short_window

    return {
        "current_regime": regime,
        "short_vol": short_vol,
        "long_vol": long_vol,
        "vol_ratio": float(vol_ratio),
        "days_in_regime": days_in_regime,
    }


def _stress_es(returns: pd.Series, short_window: int = 21) -> float | None:
    """Compute ES from recent short-window returns only."""
    if len(returns) < short_window:
        return None
    recent = returns.values[-short_window:]
    losses = -recent
    var_975 = float(np.quantile(losses, 0.975))
    tail = losses[losses >= var_975]
    if len(tail) > 0:
        return float(np.mean(tail))
    return var_975


# ---------------------------------------------------------------------------
# Phase 6: Concentration Risk Decomposition
# ---------------------------------------------------------------------------

def _build_covariance_matrix(
    symbols: list[str],
    lookback_days: int,
) -> tuple[np.ndarray | None, list[str], dict[str, Any]]:
    """Download individual returns and build sample covariance matrix."""
    prices, error = _download_prices(symbols, lookback_days)
    if prices is None:
        return None, symbols, {"error": error, "condition_number": None}

    returns = prices.pct_change().dropna(how="all")
    returns.columns = [str(c).upper() for c in returns.columns]

    available = [s for s in symbols if s in returns.columns]
    if len(available) < 2:
        return None, symbols, {"error": "Need at least 2 symbols for covariance", "condition_number": None}

    # Drop rows with any NaN in the available columns
    clean = returns[available].dropna()
    if len(clean) < 30:
        return None, symbols, {"error": "Insufficient clean observations", "condition_number": None}

    cov = clean.cov().values
    try:
        cond = float(np.linalg.cond(cov))
    except Exception:
        cond = float("inf")

    quality = {
        "error": None,
        "condition_number": cond,
        "observations": len(clean),
        "symbols_used": available,
        "high_condition_warning": cond > 1000,
    }

    return cov, available, quality


def _component_var(
    weights_arr: np.ndarray,
    cov_matrix: np.ndarray,
    confidence: float = 0.975,
) -> np.ndarray:
    """Euler decomposition of parametric VaR.

    Component VaR_i = w_i * (Σw)_i / (w'Σw) * VaR_p
    Sum of component VaRs equals portfolio VaR (exact under elliptical).
    """
    from scipy.stats import norm
    z = norm.ppf(confidence)

    port_var = float(weights_arr @ cov_matrix @ weights_arr)
    port_vol = np.sqrt(port_var)
    portfolio_var = z * port_vol

    # Marginal contribution: Σw
    sigma_w = cov_matrix @ weights_arr

    # Component VaR: w_i * (Σw)_i / (w'Σw) * VaR_p
    if port_var > 0:
        component = weights_arr * sigma_w / port_var * portfolio_var
    else:
        component = np.zeros_like(weights_arr)

    return component


def _marginal_var(
    weights_arr: np.ndarray,
    cov_matrix: np.ndarray,
    confidence: float = 0.975,
) -> np.ndarray:
    """Marginal VaR: sensitivity of portfolio VaR to unit weight change.

    mVaR_i = z_α * (Σw)_i / σ_p
    """
    from scipy.stats import norm
    z = norm.ppf(confidence)

    port_var = float(weights_arr @ cov_matrix @ weights_arr)
    port_vol = np.sqrt(port_var)

    sigma_w = cov_matrix @ weights_arr

    if port_vol > 0:
        marginal = z * sigma_w / port_vol
    else:
        marginal = np.zeros_like(weights_arr)

    return marginal


def _vol_weighted_hhi(
    weights: dict[str, float],
    volatilities: dict[str, float],
    portfolio_vol: float,
) -> float:
    """HHI_vol = Σ(w_i * σ_i / σ_p)²

    Captures that 10% in a high-vol biotech is riskier than 10% in T-bills.
    """
    if portfolio_vol <= 0:
        return 0.0
    total = 0.0
    for symbol, w in weights.items():
        sigma_i = volatilities.get(symbol, 0.0)
        risk_share = (w * sigma_i) / portfolio_vol
        total += risk_share ** 2
    return float(total)


async def _load_scoped_holdings(
    scope_entity: str,
    scope_wrapper: str,
    scope_account_types: list[ScopeAccountType] | None,
    strict: bool,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    scope_entity = scope_entity.strip().lower()
    scope_wrapper = scope_wrapper.strip().lower()
    scope_types = _parse_scope_types(scope_account_types)

    if scope_entity not in {"all", *VALID_ENTITY}:
        raise ValueError("scope_entity must be one of: all, personal, trust")
    if scope_wrapper not in {"all", *VALID_WRAPPER}:
        raise ValueError("scope_wrapper must be one of: all, taxable, tax_deferred, tax_exempt")

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
        and _matches_scope(a.get("classification", {}), scope_entity, scope_wrapper, scope_types)
    }

    holdings = [
        row for row in snapshot.get("positions", [])
        if isinstance(row, dict)
    ]

    is_scoped = (
        scope_entity != "all"
        or scope_wrapper != "all"
        or (scope_types is not None and len(scope_types) > 0)
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
            "strict": strict,
            "scoped_account_ids": sorted(a for a in scoped_account_ids if isinstance(a, str)),
            "excluded_holdings": excluded,
            "coverage_pct": coverage_pct,
        },
        "warnings": warnings,
    }


def _replacement_suggestion(symbol: str) -> str:
    replacements = {
        "SPY": "IVV or VOO",
        "IVV": "SPY or VOO",
        "VOO": "SPY or IVV",
        "QQQ": "VGT or ONEQ",
        "VTI": "SCHB or ITOT",
        "VXUS": "IXUS or ACWX",
        "EFA": "VEA or IEFA",
        "IWM": "VTWO or SCHA",
        "BND": "AGG or SCHZ",
    }
    return replacements.get(symbol, "Use a comparable ETF or basket and avoid substantially identical replacement for 30 days.")


@server.tool()
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
            ],
        }

    return {
        "ok": len(invalid_accounts) == 0,
        "summary": payload["summary"],
        "invalid_accounts": invalid_accounts,
    }


@server.tool()
async def validate_account_scope_coverage(
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Validate account-aware position coverage before scoped analytics."""
    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=False,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    coverage = scoped.get("coverage", {})
    coverage_pct = _coerce_float(coverage.get("account_aware_coverage_pct"), 0.0)
    strict_ok = coverage_pct >= MIN_SCOPE_COVERAGE_PCT

    return {
        "ok": strict_ok if strict else True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped.get("scope", {}),
        "warnings": scoped.get("warnings", []),
        "coverage": coverage,
        "strict_check": {
            "requested": strict,
            "minimum_required_pct": MIN_SCOPE_COVERAGE_PCT,
            "pass": strict_ok,
        },
        "provenance": scoped.get("provenance", {}),
    }


@server.tool()
async def get_condensed_portfolio_state(
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Return scoped holdings and aggregate portfolio state from Ghostfolio."""
    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    weights, total_value = _weights_from_aggregated(aggregated)
    total_cost = sum(max(v["cost"], 0.0) for v in aggregated.values())
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    top_positions = sorted(
        (
            {
                "symbol": symbol,
                "value": payload["value"],
                "weight": weights.get(symbol, 0.0),
                "cost": payload["cost"],
                "unrealized_pnl": payload["value"] - payload["cost"],
            }
            for symbol, payload in aggregated.items()
        ),
        key=lambda row: row["value"],
        reverse=True,
    )[:15]

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "account_taxonomy": {
            "summary": scoped["accounts_summary"],
            "invalid_accounts": scoped["invalid_accounts"],
        },
        "coverage": scoped.get("coverage", {}),
        "portfolio": {
            "holdings_count": len(scoped["holdings"]),
            "symbols_count": len(aggregated),
            "total_value": total_value,
            **value_semantics,
            "total_cost": total_cost,
            "unrealized_pnl": total_value - total_cost,
            "cash_proxy_weight": max(0.0, 1.0 - sum(weights.values())),
            "weight_hhi": sum(w * w for w in weights.values()),
            "effective_positions": _effective_position_count(weights),
            "largest_position_weight": max(weights.values()) if weights else 0.0,
            "value_field_semantics": {
                "investments_value_ex_cash": "Invested assets excluding cash balances.",
                "cash_balance": "Cash and cash-like balances from scoped accounts.",
                "net_worth_total": "Invested assets plus cash balances.",
            },
        },
        "top_positions": top_positions,
        "provenance": scoped.get("provenance", {}),
    }


@server.tool()
async def analyze_portfolio_risk(
    lookback_days: int = 252,
    es_limit: float = 0.025,
    risk_model: str = "auto",
    illiquid_overrides: list[dict[str, Any]] | None = None,
    include_fx_risk: bool = True,
    include_decomposition: bool = False,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compute ES/VaR/volatility/max drawdown using Ghostfolio positions and direct market data."""
    lookback_days = max(30, min(int(lookback_days), 1260))
    effective_es_limit, policy_warnings = _normalized_es_limit(es_limit)
    if risk_model not in ("historical", "student_t", "auto"):
        risk_model = "auto"

    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    # clip_negatives=False so short positions are visible to risk engine
    weights, total_value = _weights_from_aggregated(aggregated, clip_negatives=False)
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    if not weights:
        return {
            "ok": True,
            "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
            "snapshot_id": scoped.get("snapshot_id"),
            "scope": scoped["scope"],
            "warnings": scoped["warnings"],
            "risk": {
                "status": "no_positions",
                "message": "No scoped holdings available to compute risk.",
                "es_limit": effective_es_limit,
            },
            "portfolio": {**value_semantics, "total_value": total_value, "symbols": []},
            "coverage": scoped.get("coverage", {}),
            "provenance": scoped.get("provenance", {}),
            "risk_policy": {
                "binding_es_limit": BINDING_ES_LIMIT,
                "requested_es_limit": es_limit,
                "effective_es_limit": effective_es_limit,
                "warnings": policy_warnings,
            },
        }

    returns, data_quality = _download_returns(weights, lookback_days)

    # Phase 4: FX risk adjustment
    fx_exposure_info: dict[str, Any] = {"fx_adjusted": False, "total_non_usd_weight": 0.0}
    if include_fx_risk:
        fx_map = _identify_fx_exposures(aggregated, weights)
        if fx_map:
            total_non_usd = sum(info["total_weight"] for info in fx_map.values())
            fx_pairs = [info["yf_pair"] for info in fx_map.values()]
            fx_returns_df, fx_error = _download_fx_returns(fx_pairs, lookback_days)

            # Compute per-currency FX volatility from downloaded returns
            fx_vol_by_currency: dict[str, float | None] = {}
            if fx_returns_df is not None and not fx_returns_df.empty:
                for cur, info in fx_map.items():
                    pair = info["yf_pair"]
                    if pair in fx_returns_df.columns:
                        fx_series = fx_returns_df[pair].dropna()
                        if len(fx_series) >= 20:
                            fx_vol_by_currency[cur] = float(fx_series.std() * np.sqrt(252))
                        else:
                            fx_vol_by_currency[cur] = None
                    else:
                        fx_vol_by_currency[cur] = None

            fx_exposure_info = {
                "fx_adjusted": fx_returns_df is not None and not fx_returns_df.empty,
                "total_non_usd_weight": total_non_usd,
                "currencies": {
                    cur: {
                        "weight": info["total_weight"],
                        "symbols": info["symbols"],
                        "yf_pair": info["yf_pair"],
                        "annualized_vol": fx_vol_by_currency.get(cur),
                    }
                    for cur, info in fx_map.items()
                },
                "fx_download_error": fx_error,
            }

            # If we got FX data and have individual asset returns, recompute weighted returns
            if fx_returns_df is not None and not fx_returns_df.empty:
                tradeable, _ = _filter_tradeable_symbols(weights)
                symbols = sorted(tradeable.keys())
                prices, _ = _download_prices(symbols, lookback_days)
                if prices is not None and not prices.empty:
                    asset_returns = prices.pct_change().dropna(how="all")
                    asset_returns.columns = [str(c).upper() for c in asset_returns.columns]
                    asset_returns = asset_returns.ffill(limit=3).fillna(0.0)

                    # Apply FX adjustment
                    adjusted_returns = _adjust_returns_for_fx(asset_returns, fx_returns_df, fx_map)

                    available = [s for s in symbols if s in adjusted_returns.columns]
                    if available:
                        avail_sum = sum(tradeable[s] for s in available)
                        if avail_sum > 0:
                            norm_w = {s: tradeable[s] / avail_sum for s in available}
                            weighted_fx = adjusted_returns[available].mul(
                                pd.Series(norm_w), axis=1,
                            ).sum(axis=1).tail(lookback_days)

                            if not weighted_fx.empty:
                                returns = weighted_fx
                                data_quality["fx_adjusted"] = True

    risk = _risk_metrics_with_model(
        returns, es_limit=effective_es_limit, data_quality=data_quality, risk_model=risk_model,
    )

    # Phase 5: Volatility regime detection
    vol_regime = _detect_vol_regime(returns)
    if vol_regime.get("current_regime") in ("elevated", "crisis"):
        stress_es_val = _stress_es(returns)
        if stress_es_val is not None:
            risk["stress_es_975_1d"] = stress_es_val

    # Phase 6: Risk decomposition (optional, adds latency)
    risk_decomposition = None
    if include_decomposition and not returns.empty:
        tradeable_dec, _ = _filter_tradeable_symbols(weights)
        dec_symbols = sorted(tradeable_dec.keys())
        if len(dec_symbols) >= 2:
            cov_matrix, cov_symbols, cov_quality = _build_covariance_matrix(dec_symbols, lookback_days)
            if cov_matrix is not None:
                # Build weight array aligned with cov_symbols
                total_w = sum(tradeable_dec.get(s, 0.0) for s in cov_symbols)
                if total_w > 0:
                    w_arr = np.array([tradeable_dec.get(s, 0.0) / total_w for s in cov_symbols])
                    comp_var = _component_var(w_arr, cov_matrix, confidence=0.975)
                    marg_var = _marginal_var(w_arr, cov_matrix, confidence=0.975)

                    # Individual volatilities for vol-weighted HHI
                    individual_vols = {}
                    for i, s in enumerate(cov_symbols):
                        individual_vols[s] = float(np.sqrt(cov_matrix[i, i] * 252))

                    port_vol_daily = float(np.sqrt(w_arr @ cov_matrix @ w_arr))
                    port_vol_annual = port_vol_daily * np.sqrt(252)

                    dec_weights = {s: w_arr[i] for i, s in enumerate(cov_symbols)}
                    vw_hhi = _vol_weighted_hhi(dec_weights, individual_vols, port_vol_annual)

                    # Build component VaR table sorted by absolute contribution
                    comp_table = sorted(
                        [
                            {
                                "symbol": cov_symbols[i],
                                "weight": float(w_arr[i]),
                                "component_var_975": float(comp_var[i]),
                                "marginal_var_975": float(marg_var[i]),
                                "pct_contribution": float(comp_var[i] / sum(comp_var)) if sum(comp_var) > 0 else 0.0,
                            }
                            for i in range(len(cov_symbols))
                        ],
                        key=lambda x: abs(x["component_var_975"]),
                        reverse=True,
                    )

                    risk_decomposition = {
                        "component_var_975": comp_table,
                        "parametric_portfolio_var_975": float(sum(comp_var)),
                        "vol_weighted_hhi": vw_hhi,
                        "covariance_quality": cov_quality,
                    }

    concentration = sorted(
        (
            {
                "symbol": symbol,
                "weight": weight,
                "value": aggregated.get(symbol, {}).get("value", 0.0),
            }
            for symbol, weight in weights.items()
        ),
        key=lambda row: row["weight"],
        reverse=True,
    )

    alerts: list[str] = []
    risk_alert_level = 0
    if risk.get("status") == "critical":
        risk_alert_level = 3
        alerts.append(
            "RISK ALERT LEVEL 3 (CRITICAL): ES(97.5%) exceeds 2.5% binding limit; strongly discourage new trades."
        )
    elif risk.get("status") == "unreliable":
        risk_alert_level = 2
        alerts.append(
            "RISK ALERT LEVEL 2 (UNRELIABLE): Risk metrics cover less than 50% of portfolio weight. "
            "Tail risk is likely severely understated."
        )
    if concentration and concentration[0]["weight"] > 0.10:
        alerts.append(
            f"Single-name concentration alert: {concentration[0]['symbol']} at {concentration[0]['weight']:.2%}."
        )

    # Phase 5: Regime alerts
    if vol_regime.get("current_regime") == "crisis":
        alerts.append(
            f"VOLATILITY REGIME: Crisis detected — short-term vol ({vol_regime['short_vol']:.1%}) "
            f"is {vol_regime['vol_ratio']:.1f}x long-term vol ({vol_regime['long_vol']:.1%})."
        )
    elif vol_regime.get("current_regime") == "elevated":
        alerts.append(
            f"Elevated volatility regime: vol ratio {vol_regime['vol_ratio']:.2f}."
        )

    # Illiquid overlay
    illiquid_overlay = {"overlay_applied": False}
    if illiquid_overrides:
        liquid_vol = risk.get("annualized_volatility", 0.0)
        liquid_weight_pct = data_quality.get("weight_coverage_pct", 1.0)
        illiquid_overlay = _compute_illiquid_overlay(
            illiquid_overrides=illiquid_overrides,
            liquid_vol_annual=liquid_vol,
            liquid_weight=liquid_weight_pct,
            student_t_fit=risk.get("student_t_fit"),
        )
        if illiquid_overlay.get("overlay_applied"):
            adjusted_es = illiquid_overlay.get("adjusted_es_975_1d")
            if adjusted_es is not None and adjusted_es > effective_es_limit:
                risk["status"] = "critical"
                if risk_alert_level < 3:
                    risk_alert_level = 3
                    alerts.append(
                        f"RISK ALERT LEVEL 3 (CRITICAL): Adjusted ES(97.5%) with illiquid overlay "
                        f"({adjusted_es:.4f}) exceeds {effective_es_limit:.4f} binding limit."
                    )
            # Valuation staleness alerts
            for pos in illiquid_overlay.get("illiquid_positions", []):
                staleness = pos.get("mark_staleness")
                age = pos.get("valuation_age_days")
                sym = pos.get("symbol", "UNKNOWN")
                if staleness == "very_stale_mark":
                    alerts.append(
                        f"Illiquid position {sym} valued {age} days ago "
                        f"— mark uncertainty significantly increases risk estimate."
                    )
                elif staleness == "stale_mark":
                    # Lower severity: warning appended to overlay, not top-level alert
                    illiquid_overlay.setdefault("warnings", []).append(
                        f"Position {sym} valuation is {age} days old — consider reappraisal."
                    )

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": [*scoped["warnings"], *policy_warnings],
        "coverage": scoped.get("coverage", {}),
        "portfolio": {
            "total_value": total_value,
            **value_semantics,
            "symbols": sorted(weights.keys()),
            "top_positions": concentration[:10],
            "weight_hhi": sum(w * w for w in weights.values()),
            "effective_positions": _effective_position_count(weights),
            "value_field_semantics": {
                "investments_value_ex_cash": "Invested assets excluding cash balances.",
                "cash_balance": "Cash and cash-like balances from scoped accounts.",
                "net_worth_total": "Invested assets plus cash balances.",
            },
        },
        "risk": risk,
        "vol_regime": vol_regime,
        "fx_exposure": fx_exposure_info,
        "risk_decomposition": risk_decomposition,
        "risk_alert_level": risk_alert_level,
        "alerts": alerts,
        "illiquid_overlay": illiquid_overlay,
        "risk_data_integrity": {
            "weight_coverage_pct": data_quality.get("weight_coverage_pct", 0.0),
            "available_symbols": data_quality.get("available_symbols", []),
            "missing_symbols": data_quality.get("missing_symbols", []),
            "excluded_symbols": data_quality.get("excluded_symbols", []),
            "renormalized": data_quality.get("renormalized", False),
            "nan_fill_symbols": data_quality.get("nan_fill_symbols", []),
            "yfinance_error": data_quality.get("yfinance_error"),
            "data_quality_warnings": data_quality.get("data_quality_warnings", []),
        },
        "data_quality": {
            "returns_observations": data_quality.get("observations", int(len(returns))),
            "lookback_days_requested": lookback_days,
            "missing_market_data_symbols": data_quality.get("missing_symbols", []),
        },
        "provenance": {
            **scoped.get("provenance", {}),
            "market_source": "yfinance",
        },
        "risk_policy": {
            "binding_es_limit": BINDING_ES_LIMIT,
            "requested_es_limit": es_limit,
            "effective_es_limit": effective_es_limit,
            "advisory_only": True,
        },
    }


@server.tool()
async def get_portfolio_return_series(
    lookback_days: int = 252,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Return daily portfolio return path (returns/cumulative/drawdown) for LLM risk interpretation."""
    lookback_days = max(30, min(int(lookback_days), 1260))

    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    weights, total_value = _weights_from_aggregated(aggregated)
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    if not weights:
        return {
            "ok": True,
            "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
            "snapshot_id": scoped.get("snapshot_id"),
            "scope": scoped["scope"],
            "warnings": scoped["warnings"],
            "coverage": scoped.get("coverage", {}),
            "portfolio": {**value_semantics, "total_value": total_value, "symbols": []},
            "series": [],
            "data_quality": {
                "returns_observations": 0,
                "lookback_days_requested": lookback_days,
                "missing_market_data_symbols": [],
            },
            "provenance": scoped.get("provenance", {}),
        }

    returns, data_quality = _download_returns(weights, lookback_days)
    missing_symbols = data_quality.get("missing_symbols", [])
    if returns.empty:
        return {
            "ok": True,
            "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
            "snapshot_id": scoped.get("snapshot_id"),
            "scope": scoped["scope"],
            "warnings": scoped["warnings"],
            "coverage": scoped.get("coverage", {}),
            "portfolio": {
                "total_value": total_value,
                **value_semantics,
                "symbols": sorted(weights.keys()),
                "weight_hhi": sum(w * w for w in weights.values()),
                "effective_positions": _effective_position_count(weights),
            },
            "series": [],
            "data_quality": {
                "returns_observations": 0,
                "lookback_days_requested": lookback_days,
                "missing_market_data_symbols": missing_symbols,
            },
            "provenance": {
                **scoped.get("provenance", {}),
                "market_source": "yfinance",
            },
        }

    cumulative = (1.0 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max) - 1.0

    rows: list[dict[str, Any]] = []
    for idx in returns.index:
        rows.append(
            {
                "date": idx.isoformat(),
                "return_1d": float(returns.loc[idx]),
                "cumulative_growth": float(cumulative.loc[idx]),
                "drawdown": float(drawdown.loc[idx]),
            }
        )

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "coverage": scoped.get("coverage", {}),
        "portfolio": {
            "total_value": total_value,
            **value_semantics,
            "symbols": sorted(weights.keys()),
            "weight_hhi": sum(w * w for w in weights.values()),
            "effective_positions": _effective_position_count(weights),
            "largest_position_weight": max(weights.values()) if weights else 0.0,
            "value_field_semantics": {
                "investments_value_ex_cash": "Invested assets excluding cash balances.",
                "cash_balance": "Cash and cash-like balances from scoped accounts.",
                "net_worth_total": "Invested assets plus cash balances.",
            },
        },
        "series": rows,
        "data_quality": {
            "returns_observations": data_quality.get("observations", int(len(returns))),
            "lookback_days_requested": lookback_days,
            "missing_market_data_symbols": missing_symbols,
        },
        "provenance": {
            **scoped.get("provenance", {}),
            "market_source": "yfinance",
        },
    }


@server.tool()
async def analyze_allocation_drift(
    target_allocations: dict[str, float],
    drift_threshold: float = 0.03,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compare current weights to target weights and return drift and rebalance notionals."""
    try:
        targets = _normalize_target_allocations(target_allocations)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    drift_threshold = abs(_coerce_float(drift_threshold, 0.03))

    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    current_weights, total_value = _weights_from_aggregated(aggregated)
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    rows: list[dict[str, Any]] = []
    all_symbols = sorted(set(current_weights) | set(targets))

    for symbol in all_symbols:
        current = current_weights.get(symbol, 0.0)
        target = targets.get(symbol, 0.0)
        drift = current - target
        rebalance_notional = drift * total_value

        if drift > drift_threshold:
            action = "sell"
        elif drift < -drift_threshold:
            action = "buy"
        else:
            action = "hold"

        rows.append(
            {
                "symbol": symbol,
                "current_weight": current,
                "target_weight": target,
                "drift": drift,
                "rebalance_notional": rebalance_notional,
                "action": action,
            }
        )

    flagged = [row for row in rows if row["action"] != "hold"]
    flagged.sort(key=lambda row: abs(row["drift"]), reverse=True)

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "coverage": scoped.get("coverage", {}),
        "portfolio_value": total_value,
        "portfolio_value_semantics": value_semantics,
        "drift_threshold": drift_threshold,
        "target_symbols": sorted(targets.keys()),
        "flagged_trades": flagged,
        "all_positions": sorted(rows, key=lambda row: abs(row["drift"]), reverse=True),
        "provenance": scoped.get("provenance", {}),
    }


@server.tool()
async def find_tax_loss_harvesting_candidates(
    min_loss_amount: float = 200.0,
    min_loss_pct: float = 0.05,
    estimated_marginal_rate: float = 0.30,
    scope_entity: str = "personal",
    scope_wrapper: str = "taxable",
    scope_account_types: list[ScopeAccountType] | None = None,
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Find unrealized loss candidates in scoped taxable holdings with replacement hints."""
    min_loss_amount = max(0.0, _coerce_float(min_loss_amount, 200.0))
    min_loss_pct = max(0.0, _coerce_float(min_loss_pct, 0.05))
    estimated_marginal_rate = max(0.0, min(1.0, _coerce_float(estimated_marginal_rate, 0.30)))

    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    candidates: list[dict[str, Any]] = []
    total_loss = 0.0

    for symbol, payload in aggregated.items():
        cost = max(payload.get("cost", 0.0), 0.0)
        value = max(payload.get("value", 0.0), 0.0)

        if cost <= 0:
            continue

        unrealized_pnl = value - cost
        loss_amount = max(0.0, -unrealized_pnl)
        loss_pct = (loss_amount / cost) if cost > 0 else 0.0

        if loss_amount < min_loss_amount or loss_pct < min_loss_pct:
            continue

        total_loss += loss_amount
        candidates.append(
            {
                "symbol": symbol,
                "cost": cost,
                "value": value,
                "loss_amount": loss_amount,
                "loss_pct": loss_pct,
                "estimated_tax_savings": loss_amount * estimated_marginal_rate,
                "replacement_hint": _replacement_suggestion(symbol),
            }
        )

    candidates.sort(key=lambda row: row["loss_amount"], reverse=True)

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "coverage": scoped.get("coverage", {}),
        "thresholds": {
            "min_loss_amount": min_loss_amount,
            "min_loss_pct": min_loss_pct,
            "estimated_marginal_rate": estimated_marginal_rate,
        },
        "summary": {
            "candidate_count": len(candidates),
            "total_harvestable_loss": total_loss,
            "estimated_tax_savings": total_loss * estimated_marginal_rate,
            **value_semantics,
        },
        "candidates": candidates,
        "wash_sale_note": "Avoid substantially identical purchases 30 days before/after harvesting.",
        "provenance": scoped.get("provenance", {}),
    }


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
