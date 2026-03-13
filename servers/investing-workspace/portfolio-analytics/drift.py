"""Bucket allocation drift analysis.

Provides register_drift_tools(server).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from holdings import (
    ScopeAccountType,
    _aggregate_holdings,
    _coerce_float,
    _holding_symbol,
    _holding_value,
    _load_scoped_holdings,
    _portfolio_value_semantics,
    _weights_from_aggregated,
)


# ── Config ──────────────────────────────────────────────────────────────────

YFINANCE_BUCKET_CACHE_TTL_SECONDS = int(os.getenv("YFINANCE_BUCKET_CACHE_TTL_SECONDS", "86400"))
ENABLE_YFINANCE_BUCKET_FALLBACK = os.getenv("ENABLE_YFINANCE_BUCKET_FALLBACK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_YFINANCE_BUCKET_CACHE: dict[str, dict[str, Any]] = {}


# ── Normalization helpers ───────────────────────────────────────────────────


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


def _normalize_bucket_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", "_", value.strip().upper())
    return cleaned


def _normalize_bucket_target_allocations(target_bucket_allocations: Any) -> dict[str, float]:
    if isinstance(target_bucket_allocations, str):
        target_bucket_allocations = json.loads(target_bucket_allocations)

    if not isinstance(target_bucket_allocations, dict):
        raise ValueError("target_bucket_allocations must be a dict of {bucket_key: weight}")

    parsed: dict[str, float] = {}
    for bucket_key, weight in target_bucket_allocations.items():
        key = _normalize_bucket_key(bucket_key)
        if not key:
            continue
        parsed[key] = max(_coerce_float(weight), 0.0)

    total = sum(parsed.values())
    if total <= 0:
        raise ValueError("target_bucket_allocations must contain positive weights")

    return {k: v / total for k, v in parsed.items()}


def _normalize_bucket_overrides(bucket_overrides: Any) -> dict[str, str]:
    if bucket_overrides is None:
        return {}

    payload = bucket_overrides
    if isinstance(payload, str):
        payload = json.loads(payload)

    if not isinstance(payload, list):
        raise ValueError("bucket_overrides must be a list of {symbol, override_bucket_key}")

    normalized: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = _holding_symbol(item)
        if not symbol:
            raw_symbol = item.get("symbol") or item.get("ticker")
            symbol = str(raw_symbol).strip().upper() if isinstance(raw_symbol, str) else ""
        key = _normalize_bucket_key(
            item.get("override_bucket_key") or item.get("bucket_key") or item.get("bucket")
        )
        if symbol and key:
            normalized[symbol] = key

    return normalized


def _normalize_bucket_lookthrough(bucket_lookthrough: Any) -> dict[str, list[tuple[str, float]]]:
    if bucket_lookthrough is None:
        return {}

    payload = bucket_lookthrough
    if isinstance(payload, str):
        payload = json.loads(payload)

    if not isinstance(payload, list):
        raise ValueError(
            "bucket_lookthrough must be a list of {symbol, bucket_key, fraction_weight}"
        )

    grouped: dict[str, list[tuple[str, float]]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = _holding_symbol(item)
        if not symbol:
            raw_symbol = item.get("symbol") or item.get("ticker")
            symbol = str(raw_symbol).strip().upper() if isinstance(raw_symbol, str) else ""
        bucket_key = _normalize_bucket_key(
            item.get("bucket_key") or item.get("override_bucket_key") or item.get("bucket")
        )
        raw_weight = _coerce_float(
            item.get("fraction_weight", item.get("weight", item.get("composition_weight"))),
            default=math.nan,
        )
        if symbol and bucket_key and math.isfinite(raw_weight) and raw_weight > 0:
            grouped.setdefault(symbol, []).append((bucket_key, raw_weight))

    normalized: dict[str, list[tuple[str, float]]] = {}
    for symbol, rows in grouped.items():
        total = sum(weight for _, weight in rows if weight > 0)
        if total <= 0:
            continue
        normalized[symbol] = [(bucket_key, weight / total) for bucket_key, weight in rows]

    return normalized


def _bucket_lookthrough_to_rows(
    bucket_lookthrough: dict[str, list[tuple[str, float]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in sorted(bucket_lookthrough):
        allocations = [
            {"bucket_key": bucket_key, "fraction_weight": fraction_weight}
            for bucket_key, fraction_weight in bucket_lookthrough[symbol]
        ]
        rows.append({"symbol": symbol, "allocations": allocations})
    return rows


# ── yfinance bucket fallback ───────────────────────────────────────────────


def _is_generic_bucket_key(bucket_key: str) -> bool:
    return bucket_key in {
        "",
        "UNCLASSIFIED",
        "EQUITY",
        "EQUITY:ETF",
        "EQUITY:STOCK",
        "EQUITY:MUTUALFUND",
        "FIXED_INCOME",
    }


def _can_attempt_yfinance_bucket_lookup(symbol: str) -> bool:
    if not ENABLE_YFINANCE_BUCKET_FALLBACK:
        return False
    if not symbol:
        return False
    if symbol.endswith("=X"):
        return False
    if symbol in {
        "USD",
        "EUR",
        "GBP",
        "CHF",
        "JPY",
        "CAD",
        "AUD",
        "HKD",
        "SGD",
        "INR",
        "CNY",
        "KRW",
        "TWD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "MXN",
        "BRL",
        "ZAR",
        "CASH",
    }:
        return False
    return True


def _infer_bucket_from_yfinance_metadata(info: dict[str, Any]) -> str | None:
    quote_type = str(info.get("quoteType", "") or info.get("instrumentType", "")).strip().upper()
    fields = [
        info.get("category"),
        info.get("fundCategory"),
        info.get("fundFamily"),
        info.get("longName"),
        info.get("shortName"),
        info.get("sector"),
        info.get("industry"),
    ]
    text = " | ".join(str(item).strip().lower() for item in fields if item is not None and str(item).strip())

    if any(term in text for term in {"money market", "cash reserve", "cash management", "ultra short treasury"}):
        return "LIQUIDITY:CASH"

    if any(term in text for term in {"municipal", "muni", "tax-exempt", "tax free"}):
        return "FIXED_INCOME:MUNICIPAL"

    if any(term in text for term in {"high yield", "high-yield", "junk bond"}):
        return "FIXED_INCOME:HIGH_YIELD"

    if any(term in text for term in {"tips", "inflation protected", "inflation-protected"}):
        return "FIXED_INCOME:TIPS"

    if any(term in text for term in {"bond", "fixed income", "treasury", "intermediate term"}):
        return "FIXED_INCOME:AGGREGATE"

    if any(term in text for term in {"real estate", "reit", "real assets"}):
        return "EQUITY:REAL_ESTATE"

    if any(term in text for term in {"emerging", "em ex", "emerging markets"}):
        return "EQUITY:EMERGING_MARKETS"

    if any(term in text for term in {"international", "developed", "foreign", "ex-us", "all-world ex-us"}):
        return "EQUITY:INTERNATIONAL_DEVELOPED"

    if any(term in text for term in {"small cap", "small-cap", "smid", "mid cap", "mid-cap"}):
        return "EQUITY:US_SMALL_CAP"

    if quote_type in {"MUTUALFUND", "ETF", "EQUITY", "STOCK"}:
        return "EQUITY:US_LARGE_BLEND"
    return None


def _lookup_yfinance_bucket(symbol: str) -> tuple[str | None, str | None]:
    if not _can_attempt_yfinance_bucket_lookup(symbol):
        return None, None

    now = time.time()
    cached = _YFINANCE_BUCKET_CACHE.get(symbol)
    if cached and (now - _coerce_float(cached.get("ts"), 0.0) <= YFINANCE_BUCKET_CACHE_TTL_SECONDS):
        return cached.get("bucket"), cached.get("reason")

    bucket: str | None = None
    reason: str | None = None
    try:
        info = yf.Ticker(symbol).info
        if isinstance(info, dict) and info:
            bucket = _infer_bucket_from_yfinance_metadata(info)
            if bucket:
                reason = "yfinance.info heuristic"
    except Exception:
        bucket = None
        reason = None

    _YFINANCE_BUCKET_CACHE[symbol] = {"bucket": bucket, "reason": reason, "ts": now}
    return bucket, reason


def _holding_bucket_key(
    holding: dict[str, Any],
    bucket_overrides: dict[str, str] | None = None,
    fallback_tracker: dict[str, dict[str, str]] | None = None,
) -> str:
    symbol = _holding_symbol(holding)
    if bucket_overrides and symbol in bucket_overrides:
        return bucket_overrides[symbol]

    asset_class = _normalize_bucket_key(holding.get("assetClass"))
    asset_sub_class = _normalize_bucket_key(holding.get("assetSubClass"))

    if not asset_class:
        bucket_key = "UNCLASSIFIED"
    elif asset_sub_class and asset_sub_class != asset_class:
        bucket_key = f"{asset_class}:{asset_sub_class}"
    else:
        bucket_key = asset_class

    if _is_generic_bucket_key(bucket_key):
        yf_bucket, yf_reason = _lookup_yfinance_bucket(symbol)
        if yf_bucket:
            if fallback_tracker is not None and symbol:
                fallback_tracker[symbol] = {
                    "from_bucket": bucket_key,
                    "to_bucket": yf_bucket,
                    "reason": yf_reason or "yfinance heuristic",
                }
            return yf_bucket

    return bucket_key


def _bucket_weights_from_holdings(
    holdings: list[dict[str, Any]],
    bucket_overrides: dict[str, str] | None = None,
    bucket_lookthrough: dict[str, list[tuple[str, float]]] | None = None,
    fallback_tracker: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, float], dict[str, float], float]:
    bucket_values: dict[str, float] = {}
    total_value = 0.0
    for row in holdings:
        value = max(_holding_value(row), 0.0)
        if value <= 0:
            continue
        symbol = _holding_symbol(row)
        lookthrough_rows = bucket_lookthrough.get(symbol) if bucket_lookthrough and symbol else None
        if lookthrough_rows:
            for bucket_key, fraction_weight in lookthrough_rows:
                if fraction_weight <= 0:
                    continue
                bucket_values[bucket_key] = bucket_values.get(bucket_key, 0.0) + (value * fraction_weight)
        else:
            bucket_key = _holding_bucket_key(
                row,
                bucket_overrides=bucket_overrides,
                fallback_tracker=fallback_tracker,
            )
            bucket_values[bucket_key] = bucket_values.get(bucket_key, 0.0) + value
        total_value += value

    if total_value <= 0:
        return {}, bucket_values, 0.0

    weights = {bucket: value / total_value for bucket, value in bucket_values.items()}
    return weights, bucket_values, total_value


# ── Tool functions (module-level so they are importable by tests) ───────────


async def analyze_allocation_drift(
    target_allocations: dict[str, float],
    drift_threshold: float = 0.03,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
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
            scope_owner=scope_owner,
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
        drift_val = current - target
        rebalance_notional = drift_val * total_value

        if drift_val > drift_threshold:
            action = "sell"
        elif drift_val < -drift_threshold:
            action = "buy"
        else:
            action = "hold"

        rows.append(
            {
                "symbol": symbol,
                "current_weight": current,
                "target_weight": target,
                "drift": drift_val,
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


async def analyze_bucket_allocation_drift(
    target_bucket_allocations: dict[str, float],
    drift_threshold: float = 0.03,
    bucket_overrides: list[dict[str, Any]] | str | None = None,
    bucket_lookthrough: list[dict[str, Any]] | str | None = None,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compare current bucket weights to IPS targets with optional symbol overrides and fractional lookthrough."""
    try:
        targets = _normalize_bucket_target_allocations(target_bucket_allocations)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        normalized_overrides = _normalize_bucket_overrides(bucket_overrides)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        normalized_lookthrough = _normalize_bucket_lookthrough(bucket_lookthrough)
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
            scope_owner=scope_owner,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    value_semantics = _portfolio_value_semantics(scoped["holdings"])
    fallback_tracker: dict[str, dict[str, str]] = {}
    current_weights, current_bucket_values, total_value = _bucket_weights_from_holdings(
        scoped["holdings"],
        bucket_overrides=normalized_overrides,
        bucket_lookthrough=normalized_lookthrough,
        fallback_tracker=fallback_tracker,
    )
    warnings = list(scoped["warnings"])
    if fallback_tracker:
        warnings.append(
            "Applied yfinance metadata fallback for "
            f"{len(fallback_tracker)} generic/unclassified symbols before bucket assignment."
        )

    rows: list[dict[str, Any]] = []
    all_buckets = sorted(set(current_weights) | set(targets))

    for bucket_key in all_buckets:
        current = current_weights.get(bucket_key, 0.0)
        target = targets.get(bucket_key, 0.0)
        drift_val = current - target
        rebalance_notional = drift_val * total_value

        if drift_val > drift_threshold:
            action = "sell"
        elif drift_val < -drift_threshold:
            action = "buy"
        else:
            action = "hold"

        rows.append(
            {
                "bucket_key": bucket_key,
                "current_weight": current,
                "target_weight": target,
                "drift": drift_val,
                "rebalance_notional": rebalance_notional,
                "current_value": current_bucket_values.get(bucket_key, 0.0),
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
        "warnings": warnings,
        "coverage": scoped.get("coverage", {}),
        "portfolio_value": total_value,
        "portfolio_value_semantics": value_semantics,
        "drift_threshold": drift_threshold,
        "target_buckets": sorted(targets.keys()),
        "bucket_overrides": normalized_overrides,
        "bucket_lookthrough": _bucket_lookthrough_to_rows(normalized_lookthrough),
        "yfinance_bucket_fallbacks": [
            {"symbol": symbol, **fallback_tracker[symbol]}
            for symbol in sorted(fallback_tracker.keys())
        ],
        "flagged_trades": flagged,
        "all_buckets": sorted(rows, key=lambda row: abs(row["drift"]), reverse=True),
        "provenance": scoped.get("provenance", {}),
    }


# ── Registration ────────────────────────────────────────────────────────────


def register_drift_tools(server) -> None:
    """Register drift analysis tools on the FastMCP server."""
    server.tool()(analyze_allocation_drift)
    server.tool()(analyze_bucket_allocation_drift)
