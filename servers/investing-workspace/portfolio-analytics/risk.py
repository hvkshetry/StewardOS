"""Risk metrics, Student-t ES, volatility regime detection, and risk decomposition.

Provides register_risk_tools(server).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from fx import (
    _adjust_returns_for_fx,
    _download_fx_returns,
    _identify_fx_exposures,
)
from holdings import (
    BINDING_ES_LIMIT,
    ScopeAccountType,
    _aggregate_holdings,
    _coerce_float,
    _effective_position_count,
    _holding_symbol,
    _holding_value,
    _is_cash_like_holding,
    _load_scoped_holdings,
    _portfolio_value_semantics,
    _weights_from_aggregated,
)
from prices import (
    _download_prices,
    _download_returns,
    _filter_tradeable_symbols,
)
from scipy.stats import t as student_t

# ── Binding limit imported from holdings; re-declare for local clarity ──────
# BINDING_ES_LIMIT is imported above from holdings


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


def _normalize_symbol_target_allocations(target_allocations: Any) -> dict[str, float]:
    if isinstance(target_allocations, str):
        import json

        target_allocations = json.loads(target_allocations)

    if not isinstance(target_allocations, dict):
        raise ValueError("target_allocations must be a dict of {symbol: weight}")

    parsed: dict[str, float] = {}
    for symbol, weight in target_allocations.items():
        if not isinstance(symbol, str):
            continue
        cleaned = symbol.strip().upper()
        if not cleaned:
            continue
        parsed[cleaned] = max(_coerce_float(weight), 0.0)

    total = sum(parsed.values())
    if total <= 0:
        raise ValueError("target_allocations must contain positive weights")

    return {symbol: weight / total for symbol, weight in parsed.items()}


# ── Core risk metrics ───────────────────────────────────────────────────────


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


# ── Student-t fitting ──────────────────────────────────────────────────────


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
    # If df > 30, tails are effectively normal -- historical is fine
    normal_like = bool(df > 30)

    # KS test p-value vs normal for diagnostics
    try:
        from scipy.stats import kstest
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


# ── Illiquid overlay ────────────────────────────────────────────────────────


def _compute_illiquid_overlay(
    illiquid_overrides: list[dict[str, Any]],
    liquid_vol_annual: float,
    liquid_weight: float,
    student_t_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute portfolio variance expansion including illiquid positions.

    Uses full variance formula:
      sigma_p^2 = w_L^2 sigma_L^2 + Sum w_i^2 sigma_i^2
             + 2 Sum w_L w_i rho_iL sigma_i sigma_L
             + 2 Sum_{i<j} w_i w_j rho_ij sigma_i sigma_j

    For illiquid-illiquid cross-correlations, uses one-factor model:
      rho_ij = rho_i * rho_j  (correlation through equity factor)
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
    sigma_L = liquid_vol_annual

    # Portfolio variance: start with liquid component
    var_p = (w_L ** 2) * (sigma_L ** 2)

    # Add illiquid own-variance and liquid-illiquid covariance
    for pos in illiquid_positions:
        w_i = pos["weight"] / total_weight
        sigma_i = pos["annual_vol"]
        rho_iL = pos["rho_equity"]

        var_p += (w_i ** 2) * (sigma_i ** 2)
        var_p += 2 * w_L * w_i * rho_iL * sigma_i * sigma_L

    # Add illiquid-illiquid cross-terms (one-factor model)
    for i in range(len(illiquid_positions)):
        for j in range(i + 1, len(illiquid_positions)):
            pos_i = illiquid_positions[i]
            pos_j = illiquid_positions[j]
            w_i = pos_i["weight"] / total_weight
            w_j = pos_j["weight"] / total_weight
            sigma_i = pos_i["annual_vol"]
            sigma_j = pos_j["annual_vol"]
            # One-factor: rho_ij ~ rho_i * rho_j
            rho_ij = pos_i["rho_equity"] * pos_j["rho_equity"]
            var_p += 2 * w_i * w_j * rho_ij * sigma_i * sigma_j

    adjusted_vol_annual = float(np.sqrt(max(var_p, 0.0)))
    adjusted_vol_daily = adjusted_vol_annual / np.sqrt(252)

    # ES adjustment: use Student-t if available, otherwise normal approximation
    if student_t_fit and student_t_fit.get("df", 100) <= 30:
        df = student_t_fit["df"]
        q = student_t.ppf(0.975, df)
        es_factor = ((df + q ** 2) / (df - 1)) * student_t.pdf(q, df) / 0.025
        adjusted_es_975_1d = adjusted_vol_daily * es_factor
    else:
        # Normal approximation: ES_975 ~ sigma * phi(z) / (1-alpha) where z = Phi^{-1}(0.975)
        from scipy.stats import norm
        z = norm.ppf(0.975)
        adjusted_es_975_1d = adjusted_vol_daily * norm.pdf(z) / 0.025

    return {
        "overlay_applied": True,
        "illiquid_weight_pct": total_illiquid_weight / total_weight,
        "liquid_weight_pct": w_L,
        "illiquid_positions": illiquid_positions,
        "unadjusted_vol_annual": sigma_L,
        "adjusted_vol_annual": adjusted_vol_annual,
        "adjusted_vol_daily": float(adjusted_vol_daily),
        "adjusted_es_975_1d": float(adjusted_es_975_1d),
        "method": "student_t_overlay" if (student_t_fit and student_t_fit.get("df", 100) <= 30) else "normal_overlay",
    }


# ── Volatility regime detection ────────────────────────────────────────────


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

    # Estimate days in current regime by scanning each trailing day with its
    # own contemporaneous short/long windows.
    days_in_regime = 0
    for end_idx in range(len(returns), long_window - 1, -1):
        short_slice = returns.values[end_idx - short_window:end_idx]
        long_slice = returns.values[end_idx - long_window:end_idx]
        short_slice_vol = float(np.std(short_slice, ddof=1) * np.sqrt(252))
        long_slice_vol = float(np.std(long_slice, ddof=1) * np.sqrt(252))

        if long_slice_vol <= 0:
            slice_ratio = 1.0
        else:
            slice_ratio = short_slice_vol / long_slice_vol

        if slice_ratio < 0.7:
            slice_regime = "low"
        elif slice_ratio <= 1.3:
            slice_regime = "normal"
        elif slice_ratio <= 2.0:
            slice_regime = "elevated"
        else:
            slice_regime = "crisis"

        if slice_regime == regime:
            days_in_regime += 1
        else:
            break

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


# ── Concentration risk decomposition ───────────────────────────────────────


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

    Component VaR_i = w_i * (Sigma*w)_i / (w'Sigma*w) * VaR_p
    Sum of component VaRs equals portfolio VaR (exact under elliptical).
    """
    from scipy.stats import norm
    z = norm.ppf(confidence)

    port_var = float(weights_arr @ cov_matrix @ weights_arr)
    port_vol = np.sqrt(port_var)
    portfolio_var = z * port_vol

    # Marginal contribution: Sigma*w
    sigma_w = cov_matrix @ weights_arr

    # Component VaR: w_i * (Sigma*w)_i / (w'Sigma*w) * VaR_p
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

    mVaR_i = z_alpha * (Sigma*w)_i / sigma_p
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
    """HHI_vol = Sum(w_i * sigma_i / sigma_p)^2

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


# ── Practitioner stress scenarios ──────────────────────────────────────────

_STRESS_HAIRCUTS: dict[str, dict[str, tuple[float, float]]] = {
    "2008_gfc": {
        "us_equity": (-0.57, -0.50),
        "intl_equity": (-0.65, -0.55),
        "pe": (-0.50, -0.30),
        "real_estate": (-0.40, -0.25),
        "inr_usd": (-0.30, -0.20),
        "gold": (0.15, 0.25),
        "bonds": (0.05, 0.15),
        "cash": (0.0, 0.0),
    },
    "2000_tech_bust": {
        "us_equity": (-0.50, -0.40),
        "intl_equity": (-0.35, -0.25),
        "pe": (-0.70, -0.50),
        "real_estate": (0.0, 0.05),
        "inr_usd": (0.0, 0.0),
        "gold": (0.05, 0.10),
        "bonds": (0.10, 0.20),
        "cash": (0.0, 0.0),
    },
    "1973_stagflation": {
        "us_equity": (-0.50, -0.40),
        "intl_equity": (-0.45, -0.35),
        "pe": (-0.40, -0.20),
        "real_estate": (-0.20, -0.10),
        "inr_usd": (0.0, 0.0),
        "gold": (1.00, 2.00),
        "bonds": (-0.20, -0.10),
        "cash": (0.0, 0.0),
    },
}

_STRESS_CATEGORY_MAP: dict[str, str] = {
    # Cash-like
    "USD": "cash", "CASH": "cash", "VMFXX": "cash", "SPAXX": "cash", "SWVXX": "cash",
    # US equity ETFs/mutual funds
    "VTI": "us_equity", "VOO": "us_equity", "SPY": "us_equity", "IVV": "us_equity",
    "QQQ": "us_equity", "VUG": "us_equity", "VTV": "us_equity", "SCHB": "us_equity",
    "ITOT": "us_equity", "IWM": "us_equity", "VGT": "us_equity", "ARKK": "us_equity",
    # International equity
    "VXUS": "intl_equity", "VEA": "intl_equity", "VWO": "intl_equity", "IXUS": "intl_equity",
    "EFA": "intl_equity", "EEM": "intl_equity", "IEFA": "intl_equity", "ACWX": "intl_equity",
    # Gold
    "GLD": "gold", "GLDM": "gold", "IAU": "gold", "GC=F": "gold",
    # Bonds
    "BND": "bonds", "AGG": "bonds", "TLT": "bonds", "VBTLX": "bonds",
    "IEF": "bonds", "SHY": "bonds", "TIP": "bonds", "SCHZ": "bonds",
}

_ASSET_CLASS_STRESS_MAP: dict[str, str] = {
    "EQUITY": "us_equity",
    "FIXED_INCOME": "bonds",
    "BOND": "bonds",
    "LIQUIDITY": "cash",
    "CASH": "cash",
    "COMMODITY": "gold",
    "REAL_ESTATE": "real_estate",
    "ALTERNATIVE": "pe",
}


def _classify_stress_category(holding: dict[str, Any]) -> str:
    symbol = _holding_symbol(holding)
    if symbol in _STRESS_CATEGORY_MAP:
        return _STRESS_CATEGORY_MAP[symbol]
    if _is_cash_like_holding(holding):
        return "cash"
    asset_class = str(holding.get("assetClass", "")).strip().upper()
    asset_sub_class = str(holding.get("assetSubClass", "")).strip().upper()
    if asset_sub_class in _ASSET_CLASS_STRESS_MAP:
        return _ASSET_CLASS_STRESS_MAP[asset_sub_class]
    if asset_class in _ASSET_CLASS_STRESS_MAP:
        return _ASSET_CLASS_STRESS_MAP[asset_class]
    # Default: treat as US equity (conservative for stress testing)
    return "us_equity"


# ── Barbell classification ─────────────────────────────────────────────────

_BARBELL_HYPER_SAFE: set[str] = {
    "USD", "CASH", "VMFXX", "SPAXX", "SWVXX", "FDRXX", "VUSXX",
    "SHV", "BIL", "SGOV", "USFR", "TFLO",
}

_BARBELL_CONVEX: set[str] = {
    "GLDM", "GLD", "IAU", "CAOS", "TLT", "DBMF", "KMLM",
    "GC=F", "SI=F",
}

_BARBELL_ASSET_CLASS_SAFE = {"LIQUIDITY", "CASH"}


def _classify_barbell_bucket(holding: dict[str, Any]) -> str:
    symbol = _holding_symbol(holding)
    if symbol in _BARBELL_HYPER_SAFE:
        return "hyper_safe"
    if _is_cash_like_holding(holding):
        return "hyper_safe"
    if symbol in _BARBELL_CONVEX:
        return "convex"
    asset_class = str(holding.get("assetClass", "")).strip().upper()
    if asset_class in _BARBELL_ASSET_CLASS_SAFE:
        return "hyper_safe"
    return "fragile_middle"


def _summarize_barbell_buckets(
    holdings: list[dict[str, Any]],
    total_value: float,
) -> dict[str, Any]:
    bucket_values: dict[str, float] = {"hyper_safe": 0.0, "convex": 0.0, "fragile_middle": 0.0}
    position_classifications: list[dict[str, Any]] = []

    for row in holdings:
        symbol = _holding_symbol(row)
        value = _holding_value(row)
        if not symbol or value <= 0:
            continue
        bucket = _classify_barbell_bucket(row)
        bucket_values[bucket] += value
        position_classifications.append(
            {
                "symbol": symbol,
                "value": round(value, 2),
                "weight": round(value / total_value, 4) if total_value > 0 else 0.0,
                "bucket": bucket,
            }
        )

    bucket_pcts = {
        key: round(value / total_value, 4) if total_value > 0 else 0.0
        for key, value in bucket_values.items()
    }
    thresholds = {
        "fragile_middle_max": 0.70,
        "convex_min": 0.10,
        "safe_min": 0.15,
    }
    safe_gap_pct = max(0.0, thresholds["safe_min"] - bucket_pcts["hyper_safe"])
    convex_gap_pct = max(0.0, thresholds["convex_min"] - bucket_pcts["convex"])
    fragile_excess_pct = max(0.0, bucket_pcts["fragile_middle"] - thresholds["fragile_middle_max"])

    flags: list[str] = []
    if fragile_excess_pct > 0:
        flags.append(f"FRAGILE_MIDDLE_HIGH: {bucket_pcts['fragile_middle']:.1%} exceeds 70% threshold")
    if convex_gap_pct > 0:
        flags.append(f"CONVEX_LOW: {bucket_pcts['convex']:.1%} below 10% threshold")
    if safe_gap_pct > 0:
        flags.append(f"SAFE_BUCKET_LOW: {bucket_pcts['hyper_safe']:.1%} below 15% threshold")

    return {
        "buckets": {
            "hyper_safe": {"value": round(bucket_values["hyper_safe"], 2), "pct": bucket_pcts["hyper_safe"]},
            "convex": {"value": round(bucket_values["convex"], 2), "pct": bucket_pcts["convex"]},
            "fragile_middle": {
                "value": round(bucket_values["fragile_middle"], 2),
                "pct": bucket_pcts["fragile_middle"],
            },
        },
        "signal": "FRAGILE" if flags else "OK",
        "flags": flags,
        "positions": sorted(position_classifications, key=lambda item: item["value"], reverse=True)[:20],
        "thresholds": thresholds,
        "safe_gap_pct": round(safe_gap_pct, 4),
        "safe_gap_value": round(total_value * safe_gap_pct, 2),
        "convex_gap_pct": round(convex_gap_pct, 4),
        "convex_gap_value": round(total_value * convex_gap_pct, 2),
        "fragile_excess_pct": round(fragile_excess_pct, 4),
        "fragile_excess_value": round(total_value * fragile_excess_pct, 2),
    }


def _build_synthetic_holdings_from_targets(
    current_holdings: list[dict[str, Any]],
    target_allocations: dict[str, float],
    total_value: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    template_by_symbol: dict[str, dict[str, Any]] = {}
    for row in current_holdings:
        symbol = _holding_symbol(row)
        if not symbol or symbol in template_by_symbol:
            continue
        template_by_symbol[symbol] = row

    synthetic_holdings: list[dict[str, Any]] = []
    new_symbols: list[str] = []
    for symbol, weight in target_allocations.items():
        target_value = max(total_value * weight, 0.0)
        if target_value <= 0:
            continue

        template = template_by_symbol.get(symbol, {})
        if not template and symbol not in {"USD", "CASH"}:
            new_symbols.append(symbol)

        market_price = _coerce_float(template.get("marketPrice"), 0.0)
        if market_price <= 0:
            market_price = 1.0 if symbol in {"USD", "CASH"} else max(target_value, 1.0)
        quantity = target_value / market_price if market_price > 0 else target_value

        synthetic_holdings.append(
            {
                "accountId": template.get("accountId") or "HYPOTHETICAL",
                "symbol": symbol,
                "quantity": quantity,
                "investment": target_value,
                "costBasisInBaseCurrency": target_value,
                "marketPrice": market_price,
                "valueInBaseCurrency": target_value,
                "currency": template.get("currency") or "USD",
                "assetClass": (
                    "LIQUIDITY"
                    if symbol in {"USD", "CASH"}
                    else template.get("assetClass")
                ),
                "assetSubClass": (
                    "CASH"
                    if symbol in {"USD", "CASH"}
                    else template.get("assetSubClass")
                ),
                "dataSource": template.get("dataSource") or "HYPOTHETICAL",
            }
        )

    return synthetic_holdings, sorted(new_symbols)


def _risk_delta(current: float | None, proposed: float | None) -> float | None:
    if current is None or proposed is None:
        return None
    return round(proposed - current, 6)


def _risk_improves(current: float | None, proposed: float | None, tolerance: float = 1e-9) -> bool:
    if current is None or proposed is None:
        return False
    return proposed < (current - tolerance)


async def _analyze_risk_from_loaded_holdings(
    *,
    holdings: list[dict[str, Any]],
    scoped: dict[str, Any],
    lookback_days: int,
    es_limit: float,
    requested_es_limit: float,
    policy_warnings: list[str],
    risk_model: str,
    illiquid_overrides: list[dict[str, Any]] | None,
    include_fx_risk: bool,
    include_decomposition: bool,
) -> dict[str, Any]:
    aggregated = _aggregate_holdings(holdings)
    # clip_negatives=False so short positions are visible to risk engine
    weights, total_value = _weights_from_aggregated(aggregated, clip_negatives=False)
    value_semantics = _portfolio_value_semantics(holdings)

    if not weights:
        return {
            "ok": True,
            "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
            "snapshot_id": scoped.get("snapshot_id"),
            "scope": scoped["scope"],
            "warnings": [*scoped["warnings"], *policy_warnings],
            "risk": {
                "status": "no_positions",
                "message": "No scoped holdings available to compute risk.",
                "es_limit": es_limit,
            },
            "portfolio": {**value_semantics, "total_value": total_value, "symbols": []},
            "coverage": scoped.get("coverage", {}),
            "provenance": scoped.get("provenance", {}),
            "risk_policy": {
                "binding_es_limit": BINDING_ES_LIMIT,
                "requested_es_limit": requested_es_limit,
                "effective_es_limit": es_limit,
                "warnings": policy_warnings,
            },
        }

    returns, data_quality = _download_returns(
        weights,
        lookback_days,
        scale_to_total_weight=True,
    )

    fx_exposure_info: dict[str, Any] = {"fx_adjusted": False, "total_non_usd_weight": 0.0}
    if include_fx_risk:
        fx_map = _identify_fx_exposures(aggregated, weights)
        if fx_map:
            total_non_usd = sum(info["total_weight"] for info in fx_map.values())
            fx_pairs = [info["yf_pair"] for info in fx_map.values()]
            fx_returns_df, fx_error = _download_fx_returns(fx_pairs, lookback_days)

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

            if fx_returns_df is not None and not fx_returns_df.empty:
                tradeable, _ = _filter_tradeable_symbols(weights)
                symbols = sorted(tradeable.keys())
                prices, _ = _download_prices(symbols, lookback_days)
                if prices is not None and not prices.empty:
                    asset_returns = prices.pct_change().dropna(how="all")
                    asset_returns.columns = [str(c).upper() for c in asset_returns.columns]
                    asset_returns = asset_returns.ffill(limit=3).fillna(0.0)

                    adjusted_returns = _adjust_returns_for_fx(asset_returns, fx_returns_df, fx_map)
                    available = [s for s in symbols if s in adjusted_returns.columns]
                    if available:
                        original_weight_sum = sum(weights.values())
                        available_weight_sum = sum(tradeable[s] for s in available)
                        if original_weight_sum > 0 and available_weight_sum > 0:
                            norm_w = {s: tradeable[s] / available_weight_sum for s in available}
                            weighted_fx = adjusted_returns[available].mul(
                                pd.Series(norm_w), axis=1,
                            ).sum(axis=1)
                            weighted_fx = weighted_fx * (available_weight_sum / original_weight_sum)
                            weighted_fx = weighted_fx.tail(lookback_days)

                            if not weighted_fx.empty:
                                returns = weighted_fx
                                data_quality["fx_adjusted"] = True

    risk = _risk_metrics_with_model(
        returns, es_limit=es_limit, data_quality=data_quality, risk_model=risk_model,
    )

    vol_regime = _detect_vol_regime(returns)
    if vol_regime.get("current_regime") in ("elevated", "crisis"):
        stress_es_val = _stress_es(returns)
        if stress_es_val is not None:
            risk["stress_es_975_1d"] = stress_es_val

    risk_decomposition = None
    if include_decomposition and not returns.empty:
        tradeable_dec, _ = _filter_tradeable_symbols(weights)
        dec_symbols = sorted(tradeable_dec.keys())
        if len(dec_symbols) >= 2:
            cov_matrix, cov_symbols, cov_quality = _build_covariance_matrix(dec_symbols, lookback_days)
            if cov_matrix is not None:
                total_w = sum(tradeable_dec.get(s, 0.0) for s in cov_symbols)
                if total_w > 0:
                    w_arr = np.array([tradeable_dec.get(s, 0.0) / total_w for s in cov_symbols])
                    comp_var = _component_var(w_arr, cov_matrix, confidence=0.975)
                    marg_var = _marginal_var(w_arr, cov_matrix, confidence=0.975)

                    individual_vols = {}
                    for i, symbol in enumerate(cov_symbols):
                        individual_vols[symbol] = float(np.sqrt(cov_matrix[i, i] * 252))

                    port_vol_daily = float(np.sqrt(w_arr @ cov_matrix @ w_arr))
                    port_vol_annual = port_vol_daily * np.sqrt(252)

                    dec_weights = {symbol: w_arr[i] for i, symbol in enumerate(cov_symbols)}
                    vw_hhi = _vol_weighted_hhi(dec_weights, individual_vols, port_vol_annual)
                    total_component_var = float(sum(comp_var))
                    comp_table = sorted(
                        [
                            {
                                "symbol": cov_symbols[i],
                                "weight": float(w_arr[i]),
                                "component_var_975": float(comp_var[i]),
                                "marginal_var_975": float(marg_var[i]),
                                "pct_contribution": (
                                    float(comp_var[i] / total_component_var)
                                    if total_component_var > 0
                                    else 0.0
                                ),
                            }
                            for i in range(len(cov_symbols))
                        ],
                        key=lambda row: abs(row["component_var_975"]),
                        reverse=True,
                    )

                    risk_decomposition = {
                        "component_var_975": comp_table,
                        "parametric_portfolio_var_975": total_component_var,
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

    if vol_regime.get("current_regime") == "crisis":
        alerts.append(
            f"VOLATILITY REGIME: Crisis detected — short-term vol ({vol_regime['short_vol']:.1%}) "
            f"is {vol_regime['vol_ratio']:.1f}x long-term vol ({vol_regime['long_vol']:.1%})."
        )
    elif vol_regime.get("current_regime") == "elevated":
        alerts.append(
            f"Elevated volatility regime: vol ratio {vol_regime['vol_ratio']:.2f}."
        )

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
            if adjusted_es is not None and adjusted_es > es_limit:
                risk["status"] = "critical"
                if risk_alert_level < 3:
                    risk_alert_level = 3
                    alerts.append(
                        f"RISK ALERT LEVEL 3 (CRITICAL): Adjusted ES(97.5%) with illiquid overlay "
                        f"({adjusted_es:.4f}) exceeds {es_limit:.4f} binding limit."
                    )
            for pos in illiquid_overlay.get("illiquid_positions", []):
                staleness = pos.get("mark_staleness")
                age = pos.get("valuation_age_days")
                sym = pos.get("symbol", "UNKNOWN")
                if staleness == "very_stale_mark":
                    alerts.append(
                        f"Illiquid position {sym} valued {age} days ago "
                        "— mark uncertainty significantly increases risk estimate."
                    )
                elif staleness == "stale_mark":
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
            "zero_return_excluded_symbols": data_quality.get("zero_return_excluded_symbols", []),
            "missing_tradeable_weight_sum": data_quality.get("missing_tradeable_weight_sum", 0.0),
            "zero_return_excluded_weight_sum": data_quality.get("zero_return_excluded_weight_sum", 0.0),
            "renormalized": data_quality.get("renormalized", False),
            "scaled_to_total_weight": data_quality.get("scaled_to_total_weight", False),
            "scale_factor": data_quality.get("scale_factor"),
            "nan_fill_symbols": data_quality.get("nan_fill_symbols", []),
            "yfinance_error": data_quality.get("yfinance_error"),
            "data_quality_warnings": data_quality.get("data_quality_warnings", []),
        },
        "provenance": {
            **scoped.get("provenance", {}),
            "market_source": "yfinance",
        },
        "risk_policy": {
            "binding_es_limit": BINDING_ES_LIMIT,
            "requested_es_limit": requested_es_limit,
            "effective_es_limit": es_limit,
            "advisory_only": True,
        },
    }


# ── Tool functions (module-level so they are importable by tests) ───────────


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
    scope_owner: str = "all",
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
            scope_owner=scope_owner,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return await _analyze_risk_from_loaded_holdings(
        holdings=scoped["holdings"],
        scoped=scoped,
        lookback_days=lookback_days,
        es_limit=effective_es_limit,
        requested_es_limit=es_limit,
        policy_warnings=policy_warnings,
        risk_model=risk_model,
        illiquid_overrides=illiquid_overrides,
        include_fx_risk=include_fx_risk,
        include_decomposition=include_decomposition,
    )


async def get_portfolio_return_series(
    lookback_days: int = 252,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
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
            scope_owner=scope_owner,
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

    returns, data_quality = _download_returns(
        weights,
        lookback_days,
        scale_to_total_weight=True,
    )
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


async def compute_ruin_scenario(
    illiquid_positions: list[dict[str, Any]] | None = None,
    swr_rates: list[float] | None = None,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Apply historical stress scenarios to the portfolio and compute stressed NW and SWR income.

    illiquid_positions: optional list of {symbol, value, stress_category} for positions
        not in Ghostfolio (e.g. PE, real estate from finance-graph). stress_category is one of:
        us_equity, intl_equity, pe, real_estate, inr_usd, gold, bonds, cash.
    swr_rates: withdrawal rates to compute income (default [0.035, 0.04]).
    """
    if swr_rates is None:
        swr_rates = [0.035, 0.04]

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

    holdings = scoped["holdings"]
    value_semantics = _portfolio_value_semantics(holdings)

    # Build position-level values with stress categories
    positions: list[dict[str, Any]] = []
    for row in holdings:
        symbol = _holding_symbol(row)
        value = _holding_value(row)
        if not symbol or value <= 0:
            continue
        positions.append({
            "symbol": symbol,
            "value": value,
            "stress_category": _classify_stress_category(row),
        })

    # Add illiquid positions from finance-graph
    if illiquid_positions:
        for pos in illiquid_positions:
            symbol = str(pos.get("symbol", "UNKNOWN"))
            value = _coerce_float(pos.get("value"), 0.0)
            cat = str(pos.get("stress_category", "pe")).lower()
            if cat not in next(iter(_STRESS_HAIRCUTS.values())):
                cat = "pe"
            if value > 0:
                positions.append({
                    "symbol": symbol,
                    "value": value,
                    "stress_category": cat,
                })

    total_nw = sum(p["value"] for p in positions)

    # Build simultaneous worst-case haircuts.
    simultaneous_worst: dict[str, tuple[float, float]] = {}
    all_categories = set(next(iter(_STRESS_HAIRCUTS.values())).keys())
    scenario_list = list(_STRESS_HAIRCUTS.values())
    for cat in all_categories:
        first = scenario_list[0].get(cat, (0.0, 0.0))
        worst_pessimistic = first[0]
        worst_optimistic = first[1]
        for scenario_haircuts in scenario_list[1:]:
            h = scenario_haircuts.get(cat, (0.0, 0.0))
            worst_pessimistic = min(worst_pessimistic, h[0])
            worst_optimistic = min(worst_optimistic, h[1])
        simultaneous_worst[cat] = (worst_pessimistic, worst_optimistic)

    all_scenarios = {**_STRESS_HAIRCUTS, "simultaneous_worst": simultaneous_worst}

    results: list[dict[str, Any]] = []
    for scenario_name, haircuts in all_scenarios.items():
        stressed_pessimistic = 0.0
        stressed_optimistic = 0.0
        position_impacts: list[dict[str, Any]] = []

        for pos in positions:
            cat = pos["stress_category"]
            h = haircuts.get(cat, (0.0, 0.0))
            pess_value = pos["value"] * (1.0 + h[0])
            opt_value = pos["value"] * (1.0 + h[1])
            stressed_pessimistic += max(pess_value, 0.0)
            stressed_optimistic += max(opt_value, 0.0)
            position_impacts.append({
                "symbol": pos["symbol"],
                "current_value": round(pos["value"], 2),
                "haircut_range": [h[0], h[1]],
                "stressed_value_range": [round(max(pess_value, 0.0), 2), round(max(opt_value, 0.0), 2)],
            })

        swr_income: list[dict[str, Any]] = []
        for rate in swr_rates:
            swr_income.append({
                "rate": rate,
                "annual_income_range": [
                    round(stressed_pessimistic * rate, 2),
                    round(stressed_optimistic * rate, 2),
                ],
            })

        results.append({
            "scenario": scenario_name,
            "stressed_nw_range": [round(stressed_pessimistic, 2), round(stressed_optimistic, 2)],
            "drawdown_range_pct": [
                round((stressed_pessimistic - total_nw) / total_nw, 4) if total_nw > 0 else 0.0,
                round((stressed_optimistic - total_nw) / total_nw, 4) if total_nw > 0 else 0.0,
            ],
            "swr_income": swr_income,
            "position_impacts": sorted(
                position_impacts, key=lambda x: x["current_value"], reverse=True
            )[:10],
        })

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped.get("scope", {}),
        "current_nw": round(total_nw, 2),
        "liquid_nw": round(value_semantics["net_worth_total"], 2),
        "scenarios": results,
        "stress_categories_used": sorted(set(p["stress_category"] for p in positions)),
        "warnings": scoped.get("warnings", []),
    }


async def analyze_hypothetical_portfolio_risk(
    target_allocations: dict[str, float],
    lookback_days: int = 252,
    es_limit: float = 0.025,
    risk_model: str = "auto",
    illiquid_overrides: list[dict[str, Any]] | None = None,
    include_fx_risk: bool = True,
    include_decomposition: bool = False,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Analyze a proposed target allocation mix and compare it to the current scoped portfolio."""
    lookback_days = max(30, min(int(lookback_days), 1260))
    effective_es_limit, policy_warnings = _normalized_es_limit(es_limit)
    if risk_model not in ("historical", "student_t", "auto"):
        risk_model = "auto"

    try:
        normalized_targets = _normalize_symbol_target_allocations(target_allocations)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

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

    current_holdings = scoped["holdings"]
    current_value_semantics = _portfolio_value_semantics(current_holdings)
    current_total_value = current_value_semantics["net_worth_total"]

    synthetic_holdings, new_symbols = _build_synthetic_holdings_from_targets(
        current_holdings,
        normalized_targets,
        current_total_value,
    )
    synthetic_scoped = dict(scoped)
    synthetic_scoped["warnings"] = list(scoped.get("warnings", []))
    if new_symbols:
        synthetic_scoped["warnings"].append(
            "Target allocations include symbols not present in the live scoped holdings; "
            f"assumed default USD metadata for: {', '.join(new_symbols)}."
        )

    current_result = await _analyze_risk_from_loaded_holdings(
        holdings=current_holdings,
        scoped=scoped,
        lookback_days=lookback_days,
        es_limit=effective_es_limit,
        requested_es_limit=es_limit,
        policy_warnings=policy_warnings,
        risk_model=risk_model,
        illiquid_overrides=illiquid_overrides,
        include_fx_risk=include_fx_risk,
        include_decomposition=include_decomposition,
    )
    proposed_result = await _analyze_risk_from_loaded_holdings(
        holdings=synthetic_holdings,
        scoped=synthetic_scoped,
        lookback_days=lookback_days,
        es_limit=effective_es_limit,
        requested_es_limit=es_limit,
        policy_warnings=policy_warnings,
        risk_model=risk_model,
        illiquid_overrides=illiquid_overrides,
        include_fx_risk=include_fx_risk,
        include_decomposition=include_decomposition,
    )

    post_plan_barbell = _summarize_barbell_buckets(synthetic_holdings, current_total_value)
    current_risk = current_result.get("risk", {}) if isinstance(current_result, dict) else {}
    proposed_risk = proposed_result.get("risk", {}) if isinstance(proposed_result, dict) else {}
    current_es_975 = current_risk.get("es_975_1d")
    proposed_es_975 = proposed_risk.get("es_975_1d")
    improves_vs_current = bool(
        proposed_result.get("ok") is True
        and proposed_risk.get("status") not in {"insufficient_data", "no_positions"}
        and _risk_improves(current_es_975, proposed_es_975)
    )
    within_policy_limit = bool(
        proposed_result.get("ok") is True
        and proposed_risk.get("status") not in {"insufficient_data", "no_positions"}
        and proposed_es_975 is not None
        and proposed_es_975 <= effective_es_limit
    )
    verification_pass = bool(
        proposed_result.get("ok") is True
        and proposed_risk.get("status") not in {"insufficient_data", "no_positions"}
        and improves_vs_current
        and within_policy_limit
    )

    proposed_result["analysis_mode"] = "hypothetical"
    proposed_result["target_allocations"] = normalized_targets
    proposed_result["improves_vs_current"] = improves_vs_current
    proposed_result["within_policy_limit"] = within_policy_limit
    proposed_result["verification_pass"] = verification_pass
    proposed_result["verification"] = {
        "verification_pass": verification_pass,
        "improves_vs_current": improves_vs_current,
        "within_policy_limit": within_policy_limit,
        "binding_es_limit": effective_es_limit,
        "proposed_es_975_1d": proposed_es_975,
        "current_es_975_1d": current_es_975,
    }
    proposed_result["delta_vs_current"] = {
        "es_975_1d": _risk_delta(current_risk.get("es_975_1d"), proposed_risk.get("es_975_1d")),
        "es_95_1d": _risk_delta(current_risk.get("es_95_1d"), proposed_risk.get("es_95_1d")),
        "annualized_volatility": _risk_delta(
            current_risk.get("annualized_volatility"),
            proposed_risk.get("annualized_volatility"),
        ),
        "max_drawdown": _risk_delta(current_risk.get("max_drawdown"), proposed_risk.get("max_drawdown")),
        "largest_position_weight": _risk_delta(
            current_result.get("portfolio", {}).get("top_positions", [{}])[0].get("weight")
            if current_result.get("portfolio", {}).get("top_positions")
            else None,
            proposed_result.get("portfolio", {}).get("top_positions", [{}])[0].get("weight")
            if proposed_result.get("portfolio", {}).get("top_positions")
            else None,
        ),
    }
    proposed_result["current_portfolio"] = {
        "risk": current_risk,
        "risk_alert_level": current_result.get("risk_alert_level"),
        "top_positions": current_result.get("portfolio", {}).get("top_positions", [])[:10],
    }
    proposed_result["post_plan_top_positions"] = proposed_result.get("portfolio", {}).get("top_positions", [])[:10]
    proposed_result["post_plan_barbell"] = post_plan_barbell
    proposed_result["assumptions"] = {
        "target_total_value": round(current_total_value, 2),
        "new_symbol_defaults_to_usd_metadata": new_symbols,
        "cash_modeled_as_zero_return_ballast": True,
    }

    return proposed_result


async def classify_barbell_buckets(
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Classify portfolio positions into barbell buckets (hyper-safe, convex, fragile-middle)."""
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

    holdings = scoped["holdings"]
    value_semantics = _portfolio_value_semantics(holdings)
    total_value = value_semantics["net_worth_total"]
    summary = _summarize_barbell_buckets(holdings, total_value)

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped.get("scope", {}),
        "total_value": round(total_value, 2),
        **summary,
        "warnings": scoped.get("warnings", []),
    }


# ── Registration ────────────────────────────────────────────────────────────


def register_risk_tools(server) -> None:
    """Register risk analysis tools on the FastMCP server."""
    server.tool()(analyze_portfolio_risk)
    server.tool()(analyze_hypothetical_portfolio_risk)
    server.tool()(get_portfolio_return_series)
    server.tool()(compute_ruin_scenario)
    server.tool()(classify_barbell_buckets)
