"""FX exposure identification and returns adjustment — importable utilities.

No register function; used by risk.py.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from prices import _download_prices


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
