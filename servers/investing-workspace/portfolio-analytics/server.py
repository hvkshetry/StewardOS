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


def _is_cash_like_holding(holding: dict[str, Any]) -> bool:
    symbol = _holding_symbol(holding)
    asset_class = str(holding.get("assetClass", "")).strip().upper()
    asset_sub_class = str(holding.get("assetSubClass", "")).strip().upper()
    return (
        asset_sub_class == "CASH"
        or asset_class == "LIQUIDITY"
        or symbol in {"USD", "USX", "CASH", "EUR", "GBP", "CHF", "JPY"}
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


def _weights_from_aggregated(aggregated: dict[str, dict[str, Any]]) -> tuple[dict[str, float], float]:
    total_value = sum(max(v["value"], 0.0) for v in aggregated.values())
    if total_value <= 0:
        return {}, 0.0

    weights = {
        symbol: max(payload["value"], 0.0) / total_value
        for symbol, payload in aggregated.items()
        if max(payload["value"], 0.0) > 0
    }
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


def _filter_tradeable_symbols(weights: dict[str, float]) -> dict[str, float]:
    excluded = {"USD", "EUR", "GBP", "CHF", "JPY", "CASH"}
    return {
        symbol: weight
        for symbol, weight in weights.items()
        if symbol and symbol not in excluded and not symbol.endswith("=X")
    }


def _download_returns(weights: dict[str, float], lookback_days: int) -> tuple[pd.Series, list[str]]:
    tradeable = _filter_tradeable_symbols(weights)
    if not tradeable:
        return pd.Series(dtype=float), []

    symbols = sorted(tradeable.keys())
    start_date = (datetime.now(timezone.utc) - timedelta(days=max(lookback_days * 2, 120))).date().isoformat()

    try:
        data = yf.download(
            tickers=symbols,
            start=start_date,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return pd.Series(dtype=float), symbols

    if data is None or data.empty:
        return pd.Series(dtype=float), symbols

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

    returns = prices.pct_change().dropna(how="all")
    if returns.empty:
        return pd.Series(dtype=float), symbols

    # Normalize symbols in case provider casing differs.
    returns.columns = [str(col).upper() for col in returns.columns]

    available = [s for s in symbols if s in returns.columns]
    if not available:
        return pd.Series(dtype=float), symbols

    weight_sum = sum(tradeable[s] for s in available)
    if weight_sum <= 0:
        return pd.Series(dtype=float), symbols

    normalized = {s: tradeable[s] / weight_sum for s in available}
    weighted = returns[available].mul(pd.Series(normalized), axis=1).sum(axis=1)
    weighted = weighted.tail(lookback_days)

    missing = [s for s in symbols if s not in available]
    return weighted, missing


def _risk_metrics(returns: pd.Series, es_limit: float) -> dict[str, Any]:
    if returns.empty or len(returns) < 30:
        return {
            "status": "insufficient_data",
            "message": "Need at least 30 daily return points to compute risk metrics.",
            "sample_size": int(len(returns)),
            "es_limit": es_limit,
        }

    losses = -returns.values
    var_95 = float(np.quantile(losses, 0.95))
    var_975 = float(np.quantile(losses, 0.975))

    tail_95 = losses[losses >= var_95]
    tail_975 = losses[losses >= var_975]
    es_95 = float(np.mean(tail_95)) if len(tail_95) else var_95
    es_975 = float(np.mean(tail_975)) if len(tail_975) else var_975

    volatility_annual = float(np.std(returns.values, ddof=1) * np.sqrt(252))

    cumulative = (1.0 + returns).cumprod()
    running_max = cumulative.cummax()
    max_drawdown = float(((cumulative / running_max) - 1.0).min())

    status = "critical" if es_975 > es_limit else "ok"

    return {
        "status": status,
        "sample_size": int(len(returns)),
        "var_95_1d": var_95,
        "var_975_1d": var_975,
        "es_95_1d": es_95,
        "es_975_1d": es_975,
        "es_limit": es_limit,
        "es_utilization": (es_975 / es_limit) if es_limit > 0 else None,
        "annualized_volatility": volatility_annual,
        "max_drawdown": max_drawdown,
    }


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

    returns, missing_symbols = _download_returns(weights, lookback_days)
    risk = _risk_metrics(returns, es_limit=effective_es_limit)

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
    if concentration and concentration[0]["weight"] > 0.10:
        alerts.append(
            f"Single-name concentration alert: {concentration[0]['symbol']} at {concentration[0]['weight']:.2%}."
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
        "risk_alert_level": risk_alert_level,
        "alerts": alerts,
        "data_quality": {
            "returns_observations": int(len(returns)),
            "lookback_days_requested": lookback_days,
            "missing_market_data_symbols": missing_symbols,
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

    returns, missing_symbols = _download_returns(weights, lookback_days)
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
            "returns_observations": int(len(returns)),
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
