"""yfinance downloads and returns calculations — importable utilities.

No register function; used by risk.py, drift.py, and other modules.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf

YFINANCE_CACHE_DIR = os.getenv("YFINANCE_CACHE_DIR", "/tmp/yfinance-cache")
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
try:
    yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
except Exception:
    pass

_ZERO_RETURN_EXCLUDED_SYMBOLS = {
    "USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "HKD", "SGD",
    "INR", "CNY", "KRW", "TWD", "NZD", "SEK", "NOK", "DKK", "MXN",
    "BRL", "ZAR", "CASH",
}

_PRICE_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.getenv("PORTFOLIO_ANALYTICS_PRICE_CACHE_TTL_SECONDS", "600")),
)
_PRICE_ERROR_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.getenv("PORTFOLIO_ANALYTICS_PRICE_ERROR_CACHE_TTL_SECONDS", "60")),
)
_PRICE_CACHE_MAX_ENTRIES = max(
    1,
    int(os.getenv("PORTFOLIO_ANALYTICS_PRICE_CACHE_MAX_ENTRIES", "32")),
)
_PRICE_CACHE: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}


def _copy_prices_frame(prices: pd.DataFrame | None) -> pd.DataFrame | None:
    if prices is None:
        return None
    return prices.copy(deep=True)


def _price_cache_key(symbols: list[str], start_date: str) -> tuple[tuple[str, ...], str]:
    normalized = tuple(sorted(str(symbol).upper() for symbol in symbols if str(symbol).strip()))
    return normalized, start_date


def _get_cached_prices(
    key: tuple[tuple[str, ...], str],
) -> tuple[pd.DataFrame | None, str | None] | None:
    if _PRICE_CACHE_TTL_SECONDS <= 0 and _PRICE_ERROR_CACHE_TTL_SECONDS <= 0:
        return None

    cached = _PRICE_CACHE.get(key)
    if cached is None:
        return None

    now = time.time()
    ttl = _PRICE_CACHE_TTL_SECONDS
    if cached.get("error") is not None:
        ttl = _PRICE_ERROR_CACHE_TTL_SECONDS

    if ttl <= 0 or (now - cached["created_at"]) > ttl:
        _PRICE_CACHE.pop(key, None)
        return None

    return _copy_prices_frame(cached.get("prices")), cached.get("error")


def _store_cached_prices(
    key: tuple[tuple[str, ...], str],
    prices: pd.DataFrame | None,
    error: str | None,
) -> None:
    if (
        prices is None
        and error is None
        and _PRICE_CACHE_TTL_SECONDS <= 0
        and _PRICE_ERROR_CACHE_TTL_SECONDS <= 0
    ):
        return

    _PRICE_CACHE[key] = {
        "created_at": time.time(),
        "prices": _copy_prices_frame(prices),
        "error": error,
    }
    if len(_PRICE_CACHE) <= _PRICE_CACHE_MAX_ENTRIES:
        return

    oldest_key = min(_PRICE_CACHE.items(), key=lambda item: item[1]["created_at"])[0]
    _PRICE_CACHE.pop(oldest_key, None)


def _download_prices(
    symbols: list[str],
    lookback_days: int,
) -> tuple[pd.DataFrame | None, str | None]:
    """Download close prices from yfinance. Returns (prices_df, error_message)."""
    start_date = (datetime.now(timezone.utc) - timedelta(days=max(lookback_days * 2, 120))).date().isoformat()
    cache_key = _price_cache_key(symbols, start_date)
    cached = _get_cached_prices(cache_key)
    if cached is not None:
        return cached
    try:
        data = yf.download(
            tickers=symbols,
            start=start_date,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        error = f"yfinance download failed: {type(exc).__name__}: {exc}"
        _store_cached_prices(cache_key, None, error)
        return None, error

    if data is None or data.empty:
        error = "yfinance returned empty data"
        _store_cached_prices(cache_key, None, error)
        return None, error

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
    _store_cached_prices(cache_key, prices, None)
    return _copy_prices_frame(prices), None


def _filter_tradeable_symbols(weights: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    tradeable = {}
    excluded_symbols = []
    for symbol, weight in weights.items():
        if (
            not symbol
            or symbol in _ZERO_RETURN_EXCLUDED_SYMBOLS
            or symbol.startswith("CASH:")
            or symbol.endswith("=X")
        ):
            excluded_symbols.append(symbol)
        else:
            tradeable[symbol] = weight
    return tradeable, excluded_symbols


def _download_returns(
    weights: dict[str, float],
    lookback_days: int,
    holdings_meta: dict[str, dict[str, Any]] | None = None,
    scale_to_total_weight: bool = False,
) -> tuple[pd.Series, dict[str, Any]]:
    original_weight_sum = sum(weights.values())
    tradeable, excluded_symbols = _filter_tradeable_symbols(weights)
    tradeable_weight_sum = sum(tradeable.values())
    zero_return_excluded_symbols = [
        symbol
        for symbol in excluded_symbols
        if symbol in _ZERO_RETURN_EXCLUDED_SYMBOLS or symbol.startswith("CASH:")
    ]
    zero_return_excluded_weight_sum = sum(weights.get(symbol, 0.0) for symbol in zero_return_excluded_symbols)

    empty_quality = {
        "missing_symbols": sorted(tradeable.keys()) if tradeable else [],
        "excluded_symbols": excluded_symbols,
        "zero_return_excluded_symbols": zero_return_excluded_symbols,
        "available_symbols": [],
        "original_weight_sum": original_weight_sum,
        "tradeable_weight_sum": tradeable_weight_sum,
        "available_weight_sum": 0.0,
        "missing_tradeable_weight_sum": tradeable_weight_sum,
        "zero_return_excluded_weight_sum": zero_return_excluded_weight_sum,
        "weight_coverage_pct": 0.0,
        "renormalized": False,
        "scaled_to_total_weight": scale_to_total_weight,
        "scale_factor": 0.0,
        "yfinance_error": None,
        "observations": 0,
        "nan_fill_symbols": [],
        "data_quality_warnings": [],
    }

    if not tradeable:
        if scale_to_total_weight and zero_return_excluded_weight_sum > 0 and zero_return_excluded_weight_sum == original_weight_sum:
            index = pd.bdate_range(
                end=datetime.now(timezone.utc).date(),
                periods=lookback_days,
            )
            zero_returns = pd.Series(0.0, index=index, dtype=float)
            empty_quality["available_weight_sum"] = 0.0
            empty_quality["missing_tradeable_weight_sum"] = 0.0
            empty_quality["weight_coverage_pct"] = 1.0
            empty_quality["scale_factor"] = 0.0
            empty_quality["observations"] = int(len(zero_returns))
            empty_quality["data_quality_warnings"].append(
                "All positions are cash or currency balances; portfolio returns modeled as zero."
            )
            return zero_returns, empty_quality
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
    missing_tradeable_weight_sum = sum(tradeable.get(symbol, 0.0) for symbol in missing)
    renormalized = len(missing) > 0
    normalized = {s: tradeable[s] / available_weight_sum for s in available}
    weighted = returns[available].mul(pd.Series(normalized), axis=1).sum(axis=1)
    scale_factor = 1.0
    if scale_to_total_weight and original_weight_sum > 0:
        scale_factor = available_weight_sum / original_weight_sum
        weighted = weighted * scale_factor
    weighted = weighted.tail(lookback_days)

    weight_coverage_pct = available_weight_sum / original_weight_sum if original_weight_sum > 0 else 0.0

    warnings: list[str] = []
    missing_tradeable_weight_pct = (
        missing_tradeable_weight_sum / original_weight_sum if original_weight_sum > 0 else 0.0
    )
    if missing_tradeable_weight_pct >= 0.50:
        warnings.append(
            f"UNRELIABLE: Risk computed on only {(1.0 - missing_tradeable_weight_pct):.1%} of portfolio weight after "
            f"excluding tradeable symbols without market data. "
            f"Missing symbols: {', '.join(missing)}. Tail risk is likely severely understated."
        )
    elif missing_tradeable_weight_pct > 0.10:
        warnings.append(
            f"Risk excludes {missing_tradeable_weight_pct:.1%} of portfolio weight in tradeable symbols without market data; "
            f"tail risk likely understated. Missing: {', '.join(missing)}."
        )
    if scale_to_total_weight and zero_return_excluded_weight_sum > 0:
        warnings.append(
            f"Cash/currency-like balances totaling {zero_return_excluded_weight_sum / original_weight_sum:.1%} "
            "were modeled as zero-return ballast."
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
        "zero_return_excluded_symbols": zero_return_excluded_symbols,
        "available_symbols": available,
        "original_weight_sum": original_weight_sum,
        "tradeable_weight_sum": tradeable_weight_sum,
        "available_weight_sum": available_weight_sum,
        "missing_tradeable_weight_sum": missing_tradeable_weight_sum,
        "zero_return_excluded_weight_sum": zero_return_excluded_weight_sum,
        "weight_coverage_pct": weight_coverage_pct,
        "renormalized": renormalized,
        "scaled_to_total_weight": scale_to_total_weight,
        "scale_factor": scale_factor,
        "yfinance_error": yf_error,
        "observations": int(len(weighted)),
        "nan_fill_symbols": nan_fill_symbols,
        "data_quality_warnings": warnings,
    }

    return weighted, data_quality
