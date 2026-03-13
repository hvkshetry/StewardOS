"""Shared helpers for canonical portfolio snapshot semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

_CASH_LIKE_SYMBOLS = {
    "USD",
    "USX",
    "CASH",
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
}


def _normalize_currency_code(value: Any, default: str = "USD") -> str:
    if isinstance(value, str):
        cleaned = value.strip().upper()
        if len(cleaned) == 3 and cleaned.isalpha():
            return cleaned
    return default


def cash_position_symbol(currency: Any) -> str:
    return f"CASH:{_normalize_currency_code(currency)}"


def is_cash_like_row(row: Mapping[str, Any]) -> bool:
    asset_class = str(row.get("assetClass", "")).strip().upper()
    asset_sub_class = str(row.get("assetSubClass", "")).strip().upper()
    symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
    return (
        asset_sub_class == "CASH"
        or asset_class == "LIQUIDITY"
        or symbol.startswith("CASH:")
        or symbol in _CASH_LIKE_SYMBOLS
    )


def normalized_position_symbol(row: Mapping[str, Any]) -> str:
    symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
    if is_cash_like_row(row):
        return cash_position_symbol(row.get("currency"))
    return symbol


def content_addressed_snapshot_id(
    *,
    positions: Sequence[Mapping[str, Any]],
    accounts: Sequence[Mapping[str, Any]],
    holdings: Sequence[Mapping[str, Any]] | None = None,
    prefix: str = "snap",
) -> str:
    def _normalize(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 10)
        if isinstance(value, Mapping):
            return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [_normalize(item) for item in value]
        return value

    payload = {
        "positions": sorted((_normalize(dict(row)) for row in positions), key=lambda row: json.dumps(row, sort_keys=True)),
        "accounts": sorted((_normalize(dict(row)) for row in accounts), key=lambda row: json.dumps(row, sort_keys=True)),
        "holdings": sorted(
            (_normalize(dict(row)) for row in (holdings or [])),
            key=lambda row: json.dumps(row, sort_keys=True),
        ),
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:12]
    return f"{prefix}_{digest}"
