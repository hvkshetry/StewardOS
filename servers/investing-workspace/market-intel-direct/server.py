#!/usr/bin/env python3
"""Direct market-intelligence MCP server (no OpenBB middle layer)."""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd
import yfinance as yf
from fastmcp import FastMCP


server = FastMCP("market-intel-direct")

YFINANCE_CACHE_DIR = os.getenv("YFINANCE_CACHE_DIR", "/tmp/yfinance-cache")
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
try:
    yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
except Exception:
    # Older yfinance releases may not expose this helper.
    pass


DEFAULT_SNAPSHOT_SYMBOLS = [
    "^GSPC",  # S&P 500
    "^IXIC",  # Nasdaq
    "^DJI",   # Dow Jones
    "^RUT",   # Russell 2000
    "^VIX",   # Volatility Index
    "^IRX",   # 13-week treasury
    "^TNX",   # 10-year treasury
    "^TYX",   # 30-year treasury
    "CL=F",   # WTI crude
    "GC=F",   # Gold
    "BTC-USD",
    "ETH-USD",
]

DEFAULT_MACRO_SERIES = {
    "CPIAUCSL": "Consumer Price Index (headline)",
    "UNRATE": "Unemployment rate",
    "FEDFUNDS": "Fed funds target (effective)",
    "DGS10": "US 10Y Treasury yield",
    "DGS2": "US 2Y Treasury yield",
    "T10Y2Y": "10Y minus 2Y term spread",
}

CFTC_FINANCIAL_FUTURES_ENDPOINT = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_MAX_ROWS = 5000
DEFAULT_GDELT_CONNECT_TIMEOUT_SEC = 4.0
DEFAULT_GDELT_READ_TIMEOUT_SEC = 8.0
DEFAULT_GDELT_MAX_ATTEMPTS = 3
DEFAULT_GDELT_TOTAL_TIMEOUT_SEC = 20.0

CFTC_POSITION_FIELDS = {
    "dealer": (
        ("dealer_positions_long_all",),
        ("dealer_positions_short_all",),
        ("dealer_positions_spread_all",),
    ),
    "asset_manager": (
        ("asset_mgr_positions_long", "asset_mgr_positions_long_all"),
        ("asset_mgr_positions_short", "asset_mgr_positions_short_all"),
        ("asset_mgr_positions_spread", "asset_mgr_positions_spread_all"),
    ),
    "leveraged_money": (
        ("lev_money_positions_long", "lev_money_positions_long_all"),
        ("lev_money_positions_short", "lev_money_positions_short_all"),
        ("lev_money_positions_spread", "lev_money_positions_spread_all"),
    ),
    "other_reportable": (
        ("other_rept_positions_long", "other_rept_positions_long_all"),
        ("other_rept_positions_short", "other_rept_positions_short_all"),
        ("other_rept_positions_spread", "other_rept_positions_spread_all"),
    ),
    "non_reportable": (
        ("nonrept_positions_long_all", "nonrept_positions_long"),
        ("nonrept_positions_short_all", "nonrept_positions_short"),
        ("nonrept_positions_spread_all", "nonrept_positions_spread"),
    ),
}


def _retry_delay_seconds(attempt: int, base: float = 0.5, jitter_max: float = 0.35) -> float:
    return (base * (2**attempt)) + random.uniform(0.0, jitter_max)


def _error_response(
    *,
    source: str,
    error_code: str,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "error_code": error_code,
        "message": message,
        "retryable": retryable,
    }
    if details:
        payload["details"] = details
    if extra:
        payload.update(extra)
    return payload


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any) -> float | None:
    if value in (None, "", "."):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        numeric = _coerce_float(row.get(key))
        if numeric is not None:
            return numeric
    return None


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_symbols(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return DEFAULT_SNAPSHOT_SYMBOLS
    normalized = [s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()]
    return normalized or DEFAULT_SNAPSHOT_SYMBOLS


def _normalize_required_symbols(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return []
    return [s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()]


def _extract_close_frame(data: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            closes = data["Close"].copy()
        else:
            first = data.columns.get_level_values(0)[0]
            closes = data[first].copy()
    else:
        if "Close" in data.columns:
            closes = data[["Close"]].copy()
            closes.columns = [symbols[0]]
        else:
            closes = data.copy()
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=symbols[0])

    closes.columns = [str(col).upper() for col in closes.columns]
    return closes


def _frame_to_matrix(frame: pd.DataFrame, row_limit: int = 1000) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"dates": [], "matrix": {}}

    trimmed = frame.tail(row_limit).copy()
    trimmed = trimmed.sort_index()

    dates = [idx.isoformat() for idx in trimmed.index]
    matrix: dict[str, list[float | None]] = {}
    for col in trimmed.columns:
        series: list[float | None] = []
        for value in trimmed[col].tolist():
            if pd.isna(value):
                series.append(None)
            else:
                series.append(float(value))
        matrix[str(col).upper()] = series

    return {"dates": dates, "matrix": matrix}


def _normalize_market_codes(market_codes: list[str] | None) -> list[str]:
    if not market_codes:
        return []
    normalized: list[str] = []
    for code in market_codes:
        if not isinstance(code, str):
            continue
        cleaned = code.strip().upper()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _normalize_cot_row(row: dict[str, Any]) -> dict[str, Any]:
    open_interest = _coerce_float(row.get("open_interest_all"))
    groups: dict[str, dict[str, float | None]] = {}
    for group_name, field_sets in CFTC_POSITION_FIELDS.items():
        long_val = _first_numeric(row, field_sets[0])
        short_val = _first_numeric(row, field_sets[1])
        spread_val = _first_numeric(row, field_sets[2])
        net_val = None
        net_pct_oi = None
        if long_val is not None and short_val is not None:
            net_val = long_val - short_val
            if open_interest and open_interest != 0:
                net_pct_oi = net_val / open_interest
        groups[group_name] = {
            "long": long_val,
            "short": short_val,
            "spread": spread_val,
            "net": net_val,
            "net_pct_open_interest": net_pct_oi,
        }

    return {
        "report_date": row.get("report_date_as_yyyy_mm_dd"),
        "market_name": row.get("market_and_exchange_names"),
        "contract_market_code": row.get("cftc_contract_market_code"),
        "commodity_code": row.get("cftc_commodity_code"),
        "open_interest": open_interest,
        "positions": groups,
    }


def _sanitize_gdelt_query(query: str) -> str:
    """Normalize punctuation-heavy market queries for GDELT compatibility."""
    normalized = " ".join((query or "").strip().split())
    if not normalized:
        return ""

    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("/", " ")
    # Remove punctuation that often triggers malformed upstream responses.
    normalized = re.sub(r"[^A-Za-z0-9\s\.-]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _gdelt_query_variants(query: str, source_country: str | None) -> list[str]:
    """Build fallback query variants, with and without source-country filters."""
    base = " ".join((query or "").strip().split())
    sanitized = _sanitize_gdelt_query(base)

    ordered_bases: list[str] = []
    for candidate in (base, sanitized):
        if candidate and candidate not in ordered_bases:
            ordered_bases.append(candidate)

    country = (source_country or "").strip().upper()
    variants: list[str] = []
    for candidate in ordered_bases:
        if country:
            variants.append(f"{candidate} sourcecountry:{country}")
        variants.append(candidate)

    # Preserve order while dropping duplicates.
    deduped: list[str] = []
    for candidate in variants:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


async def _fetch_fred_observations(
    client: httpx.AsyncClient,
    api_key: str,
    series_id: str,
    days_back: int,
    limit: int,
) -> dict[str, Any]:
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
    end_date = datetime.now(timezone.utc).date().isoformat()
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        # Descending order ensures the latest rows are returned when limit truncates.
        "sort_order": "desc",
        "limit": limit,
    }

    response = await client.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params=params,
    )
    response.raise_for_status()
    payload = response.json()

    observations = payload.get("observations", [])
    rows = []
    for item in observations:
        date_str = item.get("date")
        value = item.get("value")
        if value in (None, "."):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        rows.append({"date": date_str, "value": numeric})

    rows.sort(key=lambda item: item.get("date") or "")
    latest = rows[-1] if rows else None
    return {
        "series_id": series_id,
        "query_window": {"start_date": start_date, "end_date": end_date},
        "count": len(rows),
        "latest": latest,
        "latest_observation_date": latest.get("date") if isinstance(latest, dict) else None,
        "requested_limit": limit,
        "observations": rows,
    }


async def _fetch_cftc_rows(
    client: httpx.AsyncClient,
    where_clause: str,
    limit: int,
) -> list[dict[str, Any]]:
    params = {
        "$where": where_clause,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": max(1, min(limit, CFTC_MAX_ROWS)),
    }
    response = await client.get(CFTC_FINANCIAL_FUTURES_ENDPOINT, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


async def _fetch_fred_release_dates(
    client: httpx.AsyncClient,
    api_key: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    params = {
        "api_key": api_key,
        "file_type": "json",
        "order_by": "release_date",
        "sort_order": "desc",
        "limit": max(1, min(limit, 1000)),
    }
    response = await client.get("https://api.stlouisfed.org/fred/releases/dates", params=params)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("release_dates", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@server.tool()
def get_market_snapshot(symbols: list[str] | None = None) -> dict[str, Any]:
    """Get latest market snapshot for indices, rates, commodities, and selected assets."""
    tickers = _normalize_symbols(symbols)
    start = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()

    try:
        data = yf.download(
            tickers=tickers,
            start=start,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to download market snapshot: {exc}",
            "symbols": tickers,
        }
    closes = _extract_close_frame(data, tickers)

    if closes.empty:
        return {
            "ok": False,
            "error": "No market data returned.",
            "symbols": tickers,
        }

    rows: list[dict[str, Any]] = []
    for symbol in tickers:
        if symbol not in closes.columns:
            rows.append({"symbol": symbol, "status": "missing"})
            continue

        series = closes[symbol].dropna()
        if len(series) < 1:
            rows.append({"symbol": symbol, "status": "no_prices"})
            continue

        latest = float(series.iloc[-1])
        prev = float(series.iloc[-2]) if len(series) >= 2 else latest
        change = latest - prev
        change_pct = (change / prev) if prev else 0.0

        rows.append(
            {
                "symbol": symbol,
                "last": latest,
                "previous_close": prev,
                "change": change,
                "change_pct": change_pct,
                "status": "ok",
            }
        )

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "quotes": rows,
        "source": "yfinance",
    }


@server.tool()
def get_symbol_history(symbol: str, range: str = "6mo", interval: str = "1d") -> dict[str, Any]:
    """Get historical OHLCV bars for a symbol."""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"ok": False, "error": "symbol is required"}

    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period=range, interval=interval, auto_adjust=True)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to load symbol history: {exc}",
            "symbol": symbol,
            "range": range,
            "interval": interval,
        }

    if history is None or history.empty:
        return {
            "ok": False,
            "error": "No history returned for symbol.",
            "symbol": symbol,
            "range": range,
            "interval": interval,
        }

    bars = []
    for idx, row in history.tail(1000).iterrows():
        bars.append(
            {
                "date": idx.isoformat(),
                "open": float(row.get("Open", 0.0)),
                "high": float(row.get("High", 0.0)),
                "low": float(row.get("Low", 0.0)),
                "close": float(row.get("Close", 0.0)),
                "volume": float(row.get("Volume", 0.0)),
            }
        )

    return {
        "ok": True,
        "symbol": symbol,
        "range": range,
        "interval": interval,
        "bars": bars,
        "count": len(bars),
        "source": "yfinance",
    }


@server.tool()
def get_multi_asset_history(
    symbols: list[str],
    range: str = "6mo",
    interval: str = "1d",
    include_returns: bool = True,
) -> dict[str, Any]:
    """Get aligned close-price history for multiple assets (plus optional return matrix)."""
    tickers = _normalize_required_symbols(symbols)
    if not tickers:
        return {"ok": False, "error": "symbols is required"}

    try:
        data = yf.download(
            tickers=tickers,
            period=range,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to load multi-asset history: {exc}",
            "symbols": tickers,
            "range": range,
            "interval": interval,
        }

    closes = _extract_close_frame(data, tickers)
    if closes.empty:
        return {
            "ok": False,
            "error": "No history returned for symbols.",
            "symbols": tickers,
            "range": range,
            "interval": interval,
        }

    close_payload = _frame_to_matrix(closes, row_limit=1000)
    returns_payload = None
    if include_returns:
        returns = closes.pct_change().dropna(how="all")
        returns_payload = _frame_to_matrix(returns, row_limit=1000)

    return {
        "ok": True,
        "symbols": tickers,
        "range": range,
        "interval": interval,
        "close": close_payload,
        "returns": returns_payload,
        "source": "yfinance",
    }


@server.tool()
async def get_fred_series(
    series_id: str,
    days_back: int = 365,
    limit: int = 500,
    latest_only: bool = False,
) -> dict[str, Any]:
    """Get a FRED time series directly from the public API."""
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return _error_response(
            source="fred",
            error_code="missing_configuration",
            message="FRED_API_KEY is not configured.",
            retryable=False,
            details={"hint": "Set FRED_API_KEY in this server's env to use get_fred_series."},
        )

    days_back = max(1, min(_coerce_int(days_back, 365), 3650))
    limit = max(1, min(_coerce_int(limit, 500), 5000))
    series_id = (series_id or "").strip().upper()
    if not series_id:
        return _error_response(
            source="fred",
            error_code="invalid_input",
            message="series_id is required",
            retryable=False,
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = await _fetch_fred_observations(
                client=client,
                api_key=api_key,
                series_id=series_id,
                days_back=days_back,
                limit=limit,
            )
    except Exception as exc:
        return _error_response(
            source="fred",
            error_code="upstream_request_failed",
            message=f"Failed to fetch FRED series {series_id}: {exc}",
            retryable=True,
            details={"series_id": series_id},
        )

    if latest_only:
        latest = payload.get("latest")
        payload["observations"] = [latest] if isinstance(latest, dict) else []
        payload["count"] = len(payload["observations"])

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        **payload,
        "source": "fred",
    }


@server.tool()
async def get_macro_context_panel(
    days_back: int = 365 * 2,
    limit: int = 2000,
    series_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Get a multi-series FRED macro panel for LLM regime analysis."""
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return _error_response(
            source="fred",
            error_code="missing_configuration",
            message="FRED_API_KEY is not configured.",
            retryable=False,
            details={"hint": "Set FRED_API_KEY in this server's env to use get_macro_context_panel."},
        )

    days_back = max(30, min(_coerce_int(days_back, 365 * 2), 3650))
    limit = max(100, min(_coerce_int(limit, 2000), 5000))
    requested = series_ids or list(DEFAULT_MACRO_SERIES.keys())
    normalized = [s.strip().upper() for s in requested if isinstance(s, str) and s.strip()]
    if not normalized:
        normalized = list(DEFAULT_MACRO_SERIES.keys())

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            _fetch_fred_observations(
                client=client,
                api_key=api_key,
                series_id=series_id,
                days_back=days_back,
                limit=limit,
            )
            for series_id in normalized
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    series_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, result in enumerate(results):
        series_id = normalized[idx]
        if isinstance(result, Exception):
            errors.append({"series_id": series_id, "error": str(result)})
            continue
        series_rows.append(
            {
                **result,
                "label": DEFAULT_MACRO_SERIES.get(series_id, ""),
            }
        )

    return {
        "ok": len(series_rows) > 0,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days_back": days_back,
        "series": series_rows,
        "errors": errors,
        "source": "fred",
    }


@server.tool()
async def get_cftc_cot_snapshot(
    market_codes: list[str] | None = None,
    weeks_back: int = 12,
) -> dict[str, Any]:
    """Get latest CFTC COT positioning snapshot for financial futures markets."""
    codes = _normalize_market_codes(market_codes)
    weeks_back = max(1, min(_coerce_int(weeks_back, 12), 260))
    requested_weeks_back = weeks_back

    def _build_where_clause(window_weeks: int) -> str:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=window_weeks * 7)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%dT00:00:00.000")
        filters = [f"report_date_as_yyyy_mm_dd >= '{cutoff_str}'"]
        if codes:
            quoted_codes = ",".join(f"'{code}'" for code in codes)
            filters.append(f"cftc_contract_market_code IN ({quoted_codes})")
        return " AND ".join(filters)

    effective_weeks_back = weeks_back
    expanded_window_used = False
    where_clause = _build_where_clause(weeks_back)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rows = await _fetch_cftc_rows(client=client, where_clause=where_clause, limit=CFTC_MAX_ROWS)
            # COT can lag by publication cadence; expand tiny windows to avoid false empties.
            if not rows and weeks_back < 4:
                effective_weeks_back = 4
                expanded_window_used = True
                where_clause = _build_where_clause(effective_weeks_back)
                rows = await _fetch_cftc_rows(client=client, where_clause=where_clause, limit=CFTC_MAX_ROWS)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to fetch CFTC COT snapshot: {exc}",
            "source": "cftc_socrata",
        }

    latest_by_code: dict[str, dict[str, Any]] = {}
    expected = set(codes)
    for row in rows:
        code = str(row.get("cftc_contract_market_code", "")).strip().upper()
        if not code or code in latest_by_code:
            continue
        latest_by_code[code] = _normalize_cot_row(row)
        if expected and expected.issubset(latest_by_code):
            break

    snapshot_rows: list[dict[str, Any]]
    if codes:
        snapshot_rows = [latest_by_code[code] for code in codes if code in latest_by_code]
    else:
        snapshot_rows = list(latest_by_code.values())

    payload = {
        "ok": len(snapshot_rows) > 0,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "weeks_back": effective_weeks_back,
        "requested_weeks_back": requested_weeks_back,
        "expanded_window_used": expanded_window_used,
        "count": len(snapshot_rows),
        "snapshot": snapshot_rows,
        "missing_market_codes": [code for code in codes if code not in latest_by_code],
        "source": "cftc_socrata",
        "dataset": "gpe5-46if",
    }
    if not snapshot_rows:
        payload["error"] = "No COT rows found for requested market codes/window."
    return payload


@server.tool()
async def get_cftc_cot_history(
    market_code: str,
    weeks_back: int = 52,
) -> dict[str, Any]:
    """Get CFTC COT net-position history for a contract market code."""
    normalized_code = (market_code or "").strip().upper()
    if not normalized_code:
        return {"ok": False, "error": "market_code is required"}

    weeks_back = max(1, min(_coerce_int(weeks_back, 52), 520))
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=weeks_back * 7)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%dT00:00:00.000")
    where_clause = (
        f"cftc_contract_market_code = '{normalized_code}' "
        f"AND report_date_as_yyyy_mm_dd >= '{cutoff_str}'"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rows = await _fetch_cftc_rows(client=client, where_clause=where_clause, limit=CFTC_MAX_ROWS)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to fetch CFTC COT history: {exc}",
            "market_code": normalized_code,
            "source": "cftc_socrata",
        }

    history_rows = [_normalize_cot_row(row) for row in rows]
    history_rows.sort(key=lambda row: _parse_iso_date(row.get("report_date")) or datetime.min)

    if not history_rows:
        return {
            "ok": False,
            "error": "No COT rows found for market_code in selected window.",
            "market_code": normalized_code,
            "weeks_back": weeks_back,
            "source": "cftc_socrata",
            "dataset": "gpe5-46if",
        }

    latest = history_rows[-1]
    comparison = history_rows[-5] if len(history_rows) >= 5 else history_rows[0]
    delta_4w_net: dict[str, float | None] = {}
    for group_name, metrics in latest.get("positions", {}).items():
        latest_net = metrics.get("net")
        base_net = comparison.get("positions", {}).get(group_name, {}).get("net")
        if latest_net is None or base_net is None:
            delta_4w_net[group_name] = None
        else:
            delta_4w_net[group_name] = float(latest_net) - float(base_net)

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "market_code": normalized_code,
        "weeks_back": weeks_back,
        "count": len(history_rows),
        "latest": latest,
        "delta_4w_net": delta_4w_net,
        "history": history_rows,
        "source": "cftc_socrata",
        "dataset": "gpe5-46if",
    }


@server.tool()
async def get_macro_release_calendar(
    days_back: int = 7,
    days_ahead: int = 30,
    release_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Get macroeconomic release calendar rows from FRED release metadata."""
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "FRED_API_KEY is not configured.",
            "hint": "Set FRED_API_KEY in this server's env to use get_macro_release_calendar.",
        }

    days_back = max(0, min(_coerce_int(days_back, 7), 3650))
    days_ahead = max(0, min(_coerce_int(days_ahead, 30), 3650))
    today = datetime.now(timezone.utc).date()
    min_day = today - timedelta(days=days_back)
    max_day = today + timedelta(days=days_ahead)
    release_filter = {int(rid) for rid in (release_ids or []) if _coerce_int(rid, 0) > 0}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # FRED releases/dates rejects limits above 1000.
            rows = await _fetch_fred_release_dates(client=client, api_key=api_key, limit=1000)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to fetch FRED macro release calendar: {exc}",
            "source": "fred",
        }

    calendar_rows: list[dict[str, Any]] = []
    for row in rows:
        release_id = _coerce_int(row.get("release_id"), 0)
        if release_filter and release_id not in release_filter:
            continue

        date_str = row.get("date")
        try:
            release_day = datetime.fromisoformat(f"{date_str}T00:00:00+00:00").date()
        except Exception:
            continue

        if release_day < min_day or release_day > max_day:
            continue

        calendar_rows.append(
            {
                "release_id": release_id,
                "release_name": row.get("release_name"),
                "date": date_str,
            }
        )

    calendar_rows.sort(key=lambda item: (item.get("date") or "", item.get("release_name") or ""))
    unique_release_ids = sorted({row["release_id"] for row in calendar_rows if row.get("release_id")})

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days_back": days_back,
        "days_ahead": days_ahead,
        "count": len(calendar_rows),
        "calendar": calendar_rows,
        "release_ids": unique_release_ids,
        "source": "fred",
    }


@server.tool()
async def get_macro_release_details(
    release_id: int,
    days_back: int = 30,
    days_ahead: int = 30,
) -> dict[str, Any]:
    """Get details for one FRED release, including nearby release dates and series sample."""
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "FRED_API_KEY is not configured.",
            "hint": "Set FRED_API_KEY in this server's env to use get_macro_release_details.",
        }

    release_id = _coerce_int(release_id, 0)
    if release_id <= 0:
        return {"ok": False, "error": "release_id must be a positive integer"}

    days_back = max(0, min(_coerce_int(days_back, 30), 3650))
    days_ahead = max(0, min(_coerce_int(days_ahead, 30), 3650))
    today = datetime.now(timezone.utc).date()
    min_day = today - timedelta(days=days_back)
    max_day = today + timedelta(days=days_ahead)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            release_resp = await client.get(
                "https://api.stlouisfed.org/fred/release",
                params={"api_key": api_key, "file_type": "json", "release_id": release_id},
            )
            release_resp.raise_for_status()
            release_payload = release_resp.json()

            dates_resp = await client.get(
                "https://api.stlouisfed.org/fred/release/dates",
                params={
                    "api_key": api_key,
                    "file_type": "json",
                    "release_id": release_id,
                    "limit": 5000,
                    "order_by": "release_date",
                    "sort_order": "desc",
                },
            )
            dates_resp.raise_for_status()
            dates_payload = dates_resp.json()

            series_resp = await client.get(
                "https://api.stlouisfed.org/fred/release/series",
                params={
                    "api_key": api_key,
                    "file_type": "json",
                    "release_id": release_id,
                    "limit": 200,
                    "order_by": "series_id",
                    "sort_order": "asc",
                },
            )
            series_resp.raise_for_status()
            series_payload = series_resp.json()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to fetch FRED release details: {exc}",
            "release_id": release_id,
            "source": "fred",
        }

    releases = release_payload.get("releases", [])
    release_meta = releases[0] if isinstance(releases, list) and releases else None

    filtered_dates: list[dict[str, Any]] = []
    for item in dates_payload.get("release_dates", []):
        if not isinstance(item, dict):
            continue
        date_str = item.get("date")
        try:
            release_day = datetime.fromisoformat(f"{date_str}T00:00:00+00:00").date()
        except Exception:
            continue
        if release_day < min_day or release_day > max_day:
            continue
        filtered_dates.append({"date": date_str, "release_id": _coerce_int(item.get("release_id"), 0)})

    filtered_dates.sort(key=lambda item: item.get("date") or "")

    series_rows = series_payload.get("seriess", [])
    if not isinstance(series_rows, list):
        series_rows = []

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "release_id": release_id,
        "release": release_meta,
        "days_back": days_back,
        "days_ahead": days_ahead,
        "release_dates_in_window": filtered_dates,
        "series_sample_count": len(series_rows),
        "series_sample": series_rows[:50],
        "source": "fred",
    }


@server.tool()
async def search_market_news(
    query: str,
    days_back: int = 3,
    limit: int = 20,
    source_country: str = "US",
) -> dict[str, Any]:
    """Search market news via GDELT DOC API without OpenBB."""
    query = (query or "").strip()
    if len(query) < 3:
        return _error_response(
            source="gdelt",
            error_code="invalid_input",
            message="query must be at least 3 characters",
            retryable=False,
            details={"hint": "Use full terms like 'artificial intelligence' instead of 'AI'."},
        )

    days_back = max(1, min(_coerce_int(days_back, 3), 30))
    limit = max(1, min(_coerce_int(limit, 20), 50))

    mode = "ArtList"
    max_records = limit
    sort = "DateDesc"
    variants = _gdelt_query_variants(query, source_country)
    if not variants:
        return _error_response(
            source="gdelt",
            error_code="invalid_input",
            message="query normalization produced an empty search term",
            retryable=False,
            details={"query": query},
        )

    # GDELT supports date windows via startdatetime/enddatetime (UTC, YYYYMMDDHHMMSS)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days_back)

    base_params = {
        "mode": mode,
        "format": "json",
        "maxrecords": max_records,
        "sort": sort,
        "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end_dt.strftime("%Y%m%d%H%M%S"),
    }

    connect_timeout = max(
        1.0,
        _coerce_float(os.getenv("GDELT_CONNECT_TIMEOUT_SEC")) or DEFAULT_GDELT_CONNECT_TIMEOUT_SEC,
    )
    read_timeout = max(
        1.0,
        _coerce_float(os.getenv("GDELT_READ_TIMEOUT_SEC")) or DEFAULT_GDELT_READ_TIMEOUT_SEC,
    )
    max_attempts = max(
        1,
        min(_coerce_int(os.getenv("GDELT_MAX_ATTEMPTS"), DEFAULT_GDELT_MAX_ATTEMPTS), 6),
    )
    total_timeout_sec = max(
        read_timeout + 1.0,
        _coerce_float(os.getenv("GDELT_TOTAL_TIMEOUT_SEC")) or DEFAULT_GDELT_TOTAL_TIMEOUT_SEC,
    )

    started_at = time.monotonic()
    attempt_records: list[dict[str, Any]] = []

    try:
        timeout_cfg = httpx.Timeout(
            timeout=max(connect_timeout, read_timeout),
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        async with asyncio.timeout(total_timeout_sec):
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                response: httpx.Response | None = None
                payload: dict[str, Any] | None = None
                resolved_query: str | None = None
                last_error: Exception | None = None
                attempts_by_variant: dict[str, str] = {}

                for variant in variants:
                    params = {**base_params, "query": variant}
                    variant_error: Exception | None = None

                    for attempt in range(max_attempts):
                        attempt_no = attempt + 1
                        try:
                            candidate = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params)
                        except (httpx.TimeoutException, httpx.RequestError) as exc:
                            attempt_records.append(
                                {
                                    "variant": variant,
                                    "attempt": attempt_no,
                                    "kind": "request_error",
                                    "error": str(exc),
                                }
                            )
                            variant_error = exc
                            if attempt < max_attempts - 1:
                                await asyncio.sleep(_retry_delay_seconds(attempt))
                                continue
                            break

                        is_retryable_status = candidate.status_code == 429 or 500 <= candidate.status_code <= 599
                        if is_retryable_status and attempt < max_attempts - 1:
                            attempt_records.append(
                                {
                                    "variant": variant,
                                    "attempt": attempt_no,
                                    "kind": "http_status_retry",
                                    "status_code": candidate.status_code,
                                }
                            )
                            await asyncio.sleep(_retry_delay_seconds(attempt))
                            continue

                        try:
                            candidate.raise_for_status()
                            parsed = candidate.json()
                            if isinstance(parsed, dict):
                                response = candidate
                                payload = parsed
                                resolved_query = variant
                                attempt_records.append(
                                    {
                                        "variant": variant,
                                        "attempt": attempt_no,
                                        "kind": "success",
                                        "status_code": candidate.status_code,
                                    }
                                )
                                break
                            variant_error = RuntimeError("GDELT returned non-dict JSON payload.")
                        except ValueError as exc:
                            variant_error = RuntimeError(f"GDELT returned invalid JSON payload: {exc}")
                        except httpx.HTTPStatusError as exc:
                            variant_error = exc
                        except Exception as exc:  # pragma: no cover - defensive
                            variant_error = exc

                        attempt_records.append(
                            {
                                "variant": variant,
                                "attempt": attempt_no,
                                "kind": "parse_or_status_error",
                                "error": str(variant_error),
                            }
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(_retry_delay_seconds(attempt))

                    if payload is not None and response is not None:
                        break

                    if variant_error is not None:
                        attempts_by_variant[variant] = str(variant_error)
                        last_error = variant_error

                if payload is None or response is None or resolved_query is None:
                    elapsed = round(time.monotonic() - started_at, 3)
                    if isinstance(last_error, httpx.HTTPStatusError) and last_error.response.status_code == 429:
                        retry_after = last_error.response.headers.get("Retry-After")
                        return _error_response(
                            source="gdelt",
                            error_code="rate_limited",
                            message="GDELT rate limit reached.",
                            retryable=True,
                            details={
                                "retry_after": retry_after,
                                "variants_tried": variants,
                                "attempts_by_variant": attempts_by_variant,
                            },
                            extra={
                                "query": query,
                                "days_back": days_back,
                                "count": 0,
                                "articles": [],
                                "diagnostics": {
                                    "elapsed_seconds": elapsed,
                                    "max_attempts": max_attempts,
                                    "total_timeout_seconds": total_timeout_sec,
                                    "connect_timeout_seconds": connect_timeout,
                                    "read_timeout_seconds": read_timeout,
                                    "attempts": attempt_records,
                                },
                            },
                        )
                    if last_error is not None:
                        raise RuntimeError(f"{last_error}; variants_tried={len(variants)}")
                    raise RuntimeError("No valid response from GDELT")
    except TimeoutError:
        elapsed = round(time.monotonic() - started_at, 3)
        return _error_response(
            source="gdelt",
            error_code="upstream_timeout",
            message="Timed out while fetching GDELT news within configured timeout budget.",
            retryable=True,
            details={
                "query": query,
                "variants_tried": variants,
                "max_attempts": max_attempts,
                "total_timeout_seconds": total_timeout_sec,
                "connect_timeout_seconds": connect_timeout,
                "read_timeout_seconds": read_timeout,
                "elapsed_seconds": elapsed,
            },
            extra={
                "query": query,
                "days_back": days_back,
                "count": 0,
                "articles": [],
                "diagnostics": {
                    "elapsed_seconds": elapsed,
                    "max_attempts": max_attempts,
                    "total_timeout_seconds": total_timeout_sec,
                    "connect_timeout_seconds": connect_timeout,
                    "read_timeout_seconds": read_timeout,
                    "attempts": attempt_records,
                },
            },
        )
    except Exception as exc:
        elapsed = round(time.monotonic() - started_at, 3)
        return _error_response(
            source="gdelt",
            error_code="upstream_request_failed",
            message=f"Failed to fetch GDELT news: {exc}",
            retryable=True,
            details={
                "query": query,
                "variants_tried": variants,
                "elapsed_seconds": elapsed,
                "max_attempts": max_attempts,
                "total_timeout_seconds": total_timeout_sec,
            },
            extra={
                "query": query,
                "days_back": days_back,
                "count": 0,
                "articles": [],
                "diagnostics": {
                    "elapsed_seconds": elapsed,
                    "max_attempts": max_attempts,
                    "total_timeout_seconds": total_timeout_sec,
                    "connect_timeout_seconds": connect_timeout,
                    "read_timeout_seconds": read_timeout,
                    "attempts": attempt_records,
                },
            },
        )

    articles = payload.get("articles", [])
    rows: list[dict[str, Any]] = []

    for article in articles[:limit]:
        if not isinstance(article, dict):
            continue
        rows.append(
            {
                "title": article.get("title"),
                "url": article.get("url"),
                "source": article.get("sourcecountry") or article.get("domain"),
                "seendate": article.get("seendate"),
                "language": article.get("language"),
                "tone": article.get("tone"),
            }
        )

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "query_used": resolved_query,
        "variants_tried": variants,
        "days_back": days_back,
        "count": len(rows),
        "articles": rows,
        "source": "gdelt",
        "diagnostics": {
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "max_attempts": max_attempts,
            "total_timeout_seconds": total_timeout_sec,
            "connect_timeout_seconds": connect_timeout,
            "read_timeout_seconds": read_timeout,
            "attempts": attempt_records,
        },
    }


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
