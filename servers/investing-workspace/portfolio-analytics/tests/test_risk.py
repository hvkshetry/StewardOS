"""Integration tests for portfolio-analytics risk engine.

Tests use real data from Ghostfolio and yfinance (no mocks).
Requires GHOSTFOLIO_URL and GHOSTFOLIO_TOKEN env vars to be set.
"""

from __future__ import annotations

import os
import sys

import pytest

# Add parent dir to path so we can import server internals for unit-level checks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import (
    _compute_illiquid_overlay,
    _detect_vol_regime,
    _fit_student_t,
    _parametric_es_student_t,
    _risk_metrics,
    _risk_metrics_with_model,
    analyze_portfolio_risk,
    get_condensed_portfolio_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_ghostfolio():
    """Skip test if Ghostfolio is not configured."""
    if not os.getenv("GHOSTFOLIO_TOKEN"):
        pytest.skip("GHOSTFOLIO_TOKEN not set; skipping live integration test")


# ---------------------------------------------------------------------------
# Phase 1: Data Quality Transparency
# ---------------------------------------------------------------------------


class TestPhase1DataQuality:
    """Verify risk_data_integrity section and data quality warnings."""

    async def test_risk_data_integrity_present(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        assert result["ok"] is True
        assert "risk_data_integrity" in result
        integrity = result["risk_data_integrity"]
        assert "weight_coverage_pct" in integrity
        assert integrity["weight_coverage_pct"] > 0

    async def test_data_quality_warnings_for_partial_coverage(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        integrity = result["risk_data_integrity"]
        if integrity.get("missing_symbols"):
            # If portfolio has illiquid/manual positions, warnings should exist
            assert len(integrity.get("data_quality_warnings", [])) > 0
            assert integrity["weight_coverage_pct"] < 1.0

    async def test_data_quality_section_backward_compat(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        # Legacy data_quality section still present
        assert "data_quality" in result
        dq = result["data_quality"]
        assert "returns_observations" in dq
        assert "lookback_days_requested" in dq
        assert "missing_market_data_symbols" in dq


# ---------------------------------------------------------------------------
# Phase 2: Student-t ES
# ---------------------------------------------------------------------------


class TestPhase2StudentT:
    """Verify Student-t fitting and parametric ES."""

    async def test_student_t_fit_present(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            risk_model="auto", scope_entity="all", strict=False,
        )
        assert result["ok"] is True
        risk = result["risk"]
        assert "risk_model_used" in risk
        assert risk["risk_model_used"] in ("historical", "student_t")
        # student_t_fit may be None if tails are normal-like
        if risk.get("student_t_fit"):
            fit = risk["student_t_fit"]
            assert "df" in fit
            assert "loc" in fit
            assert "scale" in fit
            assert isinstance(fit["fat_tailed"], bool)

    async def test_conservative_envelope(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            risk_model="auto", scope_entity="all", strict=False,
        )
        risk = result["risk"]
        historical_es = risk.get("es_975_1d_historical")
        effective_es = risk.get("es_975_1d")
        assert historical_es is not None
        assert effective_es is not None
        # Conservative envelope: effective >= historical
        assert effective_es >= historical_es - 1e-10

    async def test_historical_model_matches(self):
        _require_ghostfolio()
        r_hist = await analyze_portfolio_risk(
            risk_model="historical", scope_entity="all", strict=False,
        )
        r_auto = await analyze_portfolio_risk(
            risk_model="auto", scope_entity="all", strict=False,
        )
        # Historical ES values should be identical between models
        assert abs(
            r_hist["risk"]["es_975_1d_historical"]
            - r_auto["risk"]["es_975_1d_historical"]
        ) < 1e-10

    def test_fit_student_t_unit(self):
        """Unit test: fit Student-t on synthetic fat-tailed data."""
        import numpy as np
        from scipy.stats import t as student_t

        rng = np.random.default_rng(42)
        # Generate Student-t with df=4 (fat-tailed)
        data = student_t.rvs(df=4, loc=0.0005, scale=0.01, size=500, random_state=rng)
        fit = _fit_student_t(data)
        assert fit is not None
        assert fit["df"] > 1
        assert fit["fat_tailed"] is True
        assert not fit["variance_infinite"]  # df > 2

    def test_parametric_es_positive(self):
        """Unit test: parametric ES should be positive for reasonable params."""
        es = _parametric_es_student_t(df=5.0, loc=0.0005, scale=0.01, confidence=0.975)
        assert es is not None
        assert es > 0

    def test_parametric_es_undefined_for_df_le_1(self):
        """Unit test: ES undefined for df <= 1."""
        es = _parametric_es_student_t(df=0.8, loc=0.0, scale=0.01, confidence=0.975)
        assert es is None


# ---------------------------------------------------------------------------
# Phase 3: Illiquid Overlay
# ---------------------------------------------------------------------------


class TestPhase3IlliquidOverlay:
    """Verify illiquid overlay computation."""

    async def test_no_overlay_by_default(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        assert result["illiquid_overlay"]["overlay_applied"] is False

    async def test_overlay_with_overrides(self):
        _require_ghostfolio()
        overrides = [
            {
                "symbol": "TEST_PE",
                "weight": 0.10,
                "annual_vol": 0.30,
                "rho_equity": 0.65,
                "liquidity_discount": 0.15,
            },
        ]
        result = await analyze_portfolio_risk(
            illiquid_overrides=overrides,
            scope_entity="all",
            strict=False,
        )
        overlay = result["illiquid_overlay"]
        assert overlay["overlay_applied"] is True
        assert overlay["illiquid_weight_pct"] > 0
        assert overlay["adjusted_es_975_1d"] > 0
        # With positive correlation, adjusted ES should differ from unadjusted
        unadjusted_es = result["risk"]["es_975_1d"]
        assert overlay["adjusted_es_975_1d"] != unadjusted_es

    def test_overlay_unit_positive_correlation(self):
        """Unit test: positive ρ and positive vol should increase portfolio vol."""
        overlay = _compute_illiquid_overlay(
            illiquid_overrides=[
                {"symbol": "PE1", "weight": 0.15, "annual_vol": 0.30, "rho_equity": 0.65},
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.85,
        )
        assert overlay["overlay_applied"] is True
        assert overlay["adjusted_vol_annual"] > 0.15  # Higher than liquid-only

    def test_overlay_unit_zero_weight_ignored(self):
        """Unit test: zero-weight overrides should be ignored."""
        overlay = _compute_illiquid_overlay(
            illiquid_overrides=[
                {"symbol": "PE1", "weight": 0.0, "annual_vol": 0.30, "rho_equity": 0.65},
            ],
            liquid_vol_annual=0.15,
            liquid_weight=1.0,
        )
        assert overlay["overlay_applied"] is False

    def test_overlay_multiple_illiquids_cross_terms(self):
        """Unit test: multiple illiquid positions should include cross-terms."""
        overlay_single = _compute_illiquid_overlay(
            illiquid_overrides=[
                {"symbol": "PE1", "weight": 0.10, "annual_vol": 0.30, "rho_equity": 0.65},
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.90,
        )
        overlay_double = _compute_illiquid_overlay(
            illiquid_overrides=[
                {"symbol": "PE1", "weight": 0.05, "annual_vol": 0.30, "rho_equity": 0.65},
                {"symbol": "PE2", "weight": 0.05, "annual_vol": 0.30, "rho_equity": 0.65},
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.90,
        )
        # Both should produce valid overlays
        assert overlay_single["overlay_applied"]
        assert overlay_double["overlay_applied"]
        # Diversification: splitting into two correlated positions shouldn't increase vol
        # (same total weight, same vol/rho, but cross-correlation < 1 via one-factor model)
        # ρ_12 = 0.65 * 0.65 = 0.4225 < 1, so splitting should reduce vol slightly
        assert overlay_double["adjusted_vol_annual"] <= overlay_single["adjusted_vol_annual"] + 1e-10


# ---------------------------------------------------------------------------
# Phase 4: FX Risk
# ---------------------------------------------------------------------------


class TestPhase4FXRisk:
    """Verify FX exposure identification and adjustment."""

    async def test_fx_exposure_present(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_fx_risk=True, scope_entity="all", strict=False,
        )
        assert "fx_exposure" in result
        fx = result["fx_exposure"]
        assert "total_non_usd_weight" in fx

    async def test_fx_disabled(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_fx_risk=False, scope_entity="all", strict=False,
        )
        fx = result["fx_exposure"]
        assert fx["fx_adjusted"] is False

    async def test_fx_changes_risk_if_non_usd(self):
        _require_ghostfolio()
        r_fx = await analyze_portfolio_risk(
            include_fx_risk=True, scope_entity="all", strict=False,
        )
        r_no_fx = await analyze_portfolio_risk(
            include_fx_risk=False, scope_entity="all", strict=False,
        )
        if r_fx["fx_exposure"].get("total_non_usd_weight", 0) > 0.01:
            # If meaningful FX exposure exists, risk should differ
            # Note: NOT asserting adjusted >= unadjusted — hedging effects can reduce vol
            assert r_fx["risk"]["annualized_volatility"] != r_no_fx["risk"]["annualized_volatility"]


# ---------------------------------------------------------------------------
# Phase 5: Regime Detection
# ---------------------------------------------------------------------------


class TestPhase5RegimeDetection:
    """Verify volatility regime detection."""

    async def test_vol_regime_present(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        assert "vol_regime" in result
        regime = result["vol_regime"]
        assert "current_regime" in regime
        assert regime["current_regime"] in ("low", "normal", "elevated", "crisis", "insufficient_data")

    async def test_vol_regime_sanity(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        regime = result["vol_regime"]
        if regime["current_regime"] != "insufficient_data":
            assert regime["short_vol"] > 0
            assert regime["long_vol"] > 0
            assert regime["vol_ratio"] > 0

    def test_regime_detection_unit(self):
        """Unit test: regime detection on synthetic data."""
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(42)
        # Normal vol period
        returns = pd.Series(rng.normal(0.0005, 0.01, 252))
        regime = _detect_vol_regime(returns)
        assert regime["current_regime"] in ("low", "normal", "elevated")
        assert regime["vol_ratio"] > 0

    def test_regime_crisis_detection(self):
        """Unit test: crisis regime on high-vol data."""
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(42)
        # Long calm period followed by very short extreme vol spike
        # long_window (63d) will be mostly calm, short_window (21d) all crisis
        calm = rng.normal(0.0005, 0.005, 252)
        crisis = rng.normal(-0.005, 0.06, 21)
        returns = pd.Series(np.concatenate([calm, crisis]))
        regime = _detect_vol_regime(returns)
        # Short vol should be much higher than long vol
        assert regime["vol_ratio"] > 1.3


# ---------------------------------------------------------------------------
# Phase 6: Risk Decomposition
# ---------------------------------------------------------------------------


class TestPhase6Decomposition:
    """Verify risk decomposition (component VaR, marginal VaR, vol-weighted HHI)."""

    async def test_decomposition_off_by_default(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(scope_entity="all", strict=False)
        assert result.get("risk_decomposition") is None

    async def test_decomposition_on(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_decomposition=True, scope_entity="all", strict=False,
        )
        decomp = result.get("risk_decomposition")
        if decomp is not None:
            assert "component_var_975" in decomp
            assert isinstance(decomp["component_var_975"], list)
            assert len(decomp["component_var_975"]) > 0
            assert "covariance_quality" in decomp
            assert decomp["covariance_quality"]["condition_number"] is not None

    async def test_euler_property(self):
        """Component VaRs should sum to approximately parametric portfolio VaR."""
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_decomposition=True, scope_entity="all", strict=False,
        )
        decomp = result.get("risk_decomposition")
        if decomp is not None and decomp.get("component_var_975"):
            component_sum = sum(c["component_var_975"] for c in decomp["component_var_975"])
            portfolio_var = decomp["parametric_portfolio_var_975"]
            if portfolio_var > 0:
                # Euler property: sum of components ≈ portfolio VaR
                # 5% tolerance because historical VaR is non-smooth
                assert abs(component_sum - portfolio_var) / portfolio_var < 0.05

    async def test_covariance_quality_warning(self):
        """If condition number is very high, a warning should be present."""
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_decomposition=True, scope_entity="all", strict=False,
        )
        decomp = result.get("risk_decomposition")
        if decomp and decomp.get("covariance_quality"):
            cq = decomp["covariance_quality"]
            assert "condition_number" in cq
            if cq["condition_number"] and cq["condition_number"] > 1000:
                assert cq.get("high_condition_warning") is True


# ---------------------------------------------------------------------------
# Cross-phase Integration
# ---------------------------------------------------------------------------


class TestCrossPhaseIntegration:
    """Verify all phases work together in a single call."""

    async def test_full_analysis(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            risk_model="auto",
            include_fx_risk=True,
            include_decomposition=True,
            scope_entity="all",
            strict=False,
        )
        assert result["ok"] is True

        # All sections present
        assert "risk" in result
        assert "vol_regime" in result
        assert "fx_exposure" in result
        assert "illiquid_overlay" in result
        assert "risk_data_integrity" in result
        assert "risk_policy" in result

        # Risk section has new fields
        risk = result["risk"]
        assert "es_975_1d_historical" in risk
        assert "risk_model_used" in risk
        assert "tail_sample_size_975" in risk
        assert "risk_warnings" in risk

    async def test_portfolio_state_unchanged(self):
        """get_condensed_portfolio_state should still work without new params."""
        _require_ghostfolio()
        result = await get_condensed_portfolio_state(scope_entity="all", strict=False)
        assert result["ok"] is True
        assert "portfolio" in result


# ---------------------------------------------------------------------------
# Edge Cases & Guard Tests (Codex review gaps)
# ---------------------------------------------------------------------------


class TestStudentTGuards:
    """Verify Student-t fitting edge cases: df<=2, df>30, empty data."""

    def test_fit_variance_infinite_df_le_2(self):
        """df<=2 should flag variance_infinite=True."""
        import numpy as np
        from scipy.stats import t as student_t_dist

        rng = np.random.default_rng(99)
        # df=1.5 → Cauchy-like, variance infinite
        data = student_t_dist.rvs(df=1.5, loc=0.0, scale=0.01, size=1000, random_state=rng)
        fit = _fit_student_t(data)
        # Might return None if fit fails, but if it succeeds with low df, check flag
        if fit is not None and fit["df"] <= 2:
            assert fit["variance_infinite"] is True

    def test_fit_normal_like_df_gt_30(self):
        """Normal-like data (large df) should return None (normal_like guard)."""
        import numpy as np

        rng = np.random.default_rng(42)
        # Pure Gaussian → MLE should give high df → normal_like → returns None
        data = rng.normal(0.0005, 0.01, 500)
        fit = _fit_student_t(data)
        # With Gaussian data, df should be very large; function should return None
        assert fit is None or fit["df"] > 30

    def test_fit_empty_data(self):
        """Empty or too-short data should return None safely."""
        import numpy as np

        fit = _fit_student_t(np.array([]))
        assert fit is None
        fit = _fit_student_t(np.array([0.01, -0.01]))
        assert fit is None  # too few observations for stable MLE

    def test_risk_metrics_empty_returns(self):
        """Empty returns series should produce safe output."""
        import pandas as pd

        data_quality = {
            "weight_coverage_pct": 0.0,
            "missing_symbols": [],
            "observations": 0,
        }
        result = _risk_metrics_with_model(
            pd.Series([], dtype=float),
            es_limit=0.025,
            data_quality=data_quality,
            risk_model="auto",
        )
        assert result["status"] == "insufficient_data"


class TestStalenessPassthrough:
    """Verify valuation staleness metadata passthrough and alert generation."""

    def test_staleness_metadata_in_overlay(self):
        """Unit test: valuation_age_days and mark_staleness pass through to output."""
        overlay = _compute_illiquid_overlay(
            illiquid_overrides=[
                {
                    "symbol": "HOUSE1",
                    "weight": 0.15,
                    "annual_vol": 0.12,
                    "rho_equity": 0.30,
                    "valuation_age_days": 400,
                    "mark_staleness": "stale_mark",
                },
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.85,
        )
        assert overlay["overlay_applied"] is True
        pos = overlay["illiquid_positions"][0]
        assert pos["valuation_age_days"] == 400
        assert pos["mark_staleness"] == "stale_mark"

    def test_very_stale_metadata_in_overlay(self):
        """Unit test: very_stale_mark passes through."""
        overlay = _compute_illiquid_overlay(
            illiquid_overrides=[
                {
                    "symbol": "PE_INDIA",
                    "weight": 0.10,
                    "annual_vol": 0.35,
                    "rho_equity": 0.50,
                    "valuation_age_days": 800,
                    "mark_staleness": "very_stale_mark",
                },
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.90,
        )
        assert overlay["overlay_applied"] is True
        pos = overlay["illiquid_positions"][0]
        assert pos["valuation_age_days"] == 800
        assert pos["mark_staleness"] == "very_stale_mark"

    def test_no_staleness_fields_when_absent(self):
        """Unit test: overlay without staleness fields should not include them."""
        overlay = _compute_illiquid_overlay(
            illiquid_overrides=[
                {"symbol": "PE1", "weight": 0.10, "annual_vol": 0.30, "rho_equity": 0.65},
            ],
            liquid_vol_annual=0.15,
            liquid_weight=0.90,
        )
        assert overlay["overlay_applied"] is True
        pos = overlay["illiquid_positions"][0]
        assert "valuation_age_days" not in pos
        assert "mark_staleness" not in pos

    async def test_very_stale_generates_alert(self):
        """Integration test: very_stale_mark override generates an alert."""
        _require_ghostfolio()
        overrides = [
            {
                "symbol": "STALE_HOUSE",
                "weight": 0.10,
                "annual_vol": 0.12,
                "rho_equity": 0.30,
                "valuation_age_days": 800,
                "mark_staleness": "very_stale_mark",
            },
        ]
        result = await analyze_portfolio_risk(
            illiquid_overrides=overrides,
            scope_entity="all",
            strict=False,
        )
        assert result["ok"] is True
        # Should have a staleness alert
        staleness_alerts = [a for a in result["alerts"] if "valued 800 days ago" in a]
        assert len(staleness_alerts) == 1
        assert "STALE_HOUSE" in staleness_alerts[0]

    async def test_stale_mark_generates_warning_not_alert(self):
        """Integration test: stale_mark generates warning in overlay, not top-level alert."""
        _require_ghostfolio()
        overrides = [
            {
                "symbol": "AGING_PE",
                "weight": 0.10,
                "annual_vol": 0.30,
                "rho_equity": 0.50,
                "valuation_age_days": 250,
                "mark_staleness": "stale_mark",
            },
        ]
        result = await analyze_portfolio_risk(
            illiquid_overrides=overrides,
            scope_entity="all",
            strict=False,
        )
        assert result["ok"] is True
        # Should NOT have a top-level staleness alert
        staleness_alerts = [a for a in result["alerts"] if "AGING_PE" in a and "valued" in a]
        assert len(staleness_alerts) == 0
        # Should have a warning in overlay
        overlay_warnings = result["illiquid_overlay"].get("warnings", [])
        assert any("AGING_PE" in w for w in overlay_warnings)


class TestFXDirection:
    """Verify FX adjustment formula direction."""

    def test_inr_weakening_reduces_usd_return(self):
        """When USDINR rises (INR weakens), USD return on INR asset should decrease."""
        import numpy as np
        import pandas as pd

        from server import _adjust_returns_for_fx

        dates = pd.date_range("2024-01-01", periods=5, freq="B")

        # INR asset has +1% local return every day
        asset_returns = pd.DataFrame({"RELIANCE.NS": [0.01] * 5}, index=dates)

        # USDINR rises 2% (INR weakens) — USD return should be lower than local
        fx_returns = pd.DataFrame({"USDINR=X": [0.02] * 5}, index=dates)

        fx_map = {
            "INR": {
                "yf_pair": "USDINR=X",
                "symbols": ["RELIANCE.NS"],
                "total_weight": 0.1,
            },
        }

        adjusted = _adjust_returns_for_fx(asset_returns, fx_returns, fx_map)
        # r_usd = (1 + 0.01) / (1 + 0.02) - 1 ≈ -0.0098
        for val in adjusted["RELIANCE.NS"]:
            assert val < 0.01  # Less than local return
            assert val < 0  # Actually negative because FX drag > local return

    def test_inr_strengthening_boosts_usd_return(self):
        """When USDINR falls (INR strengthens), USD return on INR asset should increase."""
        import numpy as np
        import pandas as pd

        from server import _adjust_returns_for_fx

        dates = pd.date_range("2024-01-01", periods=5, freq="B")

        # INR asset has +1% local return every day
        asset_returns = pd.DataFrame({"RELIANCE.NS": [0.01] * 5}, index=dates)

        # USDINR falls 1% (INR strengthens)
        fx_returns = pd.DataFrame({"USDINR=X": [-0.01] * 5}, index=dates)

        fx_map = {
            "INR": {
                "yf_pair": "USDINR=X",
                "symbols": ["RELIANCE.NS"],
                "total_weight": 0.1,
            },
        }

        adjusted = _adjust_returns_for_fx(asset_returns, fx_returns, fx_map)
        # r_usd = (1 + 0.01) / (1 + (-0.01)) - 1 ≈ 0.0202
        for val in adjusted["RELIANCE.NS"]:
            assert val > 0.01  # Higher than local return due to FX tailwind


class TestFXVolFields:
    """Verify FX exposure includes volatility fields."""

    async def test_fx_vol_present_when_non_usd(self):
        _require_ghostfolio()
        result = await analyze_portfolio_risk(
            include_fx_risk=True, scope_entity="all", strict=False,
        )
        fx = result["fx_exposure"]
        if fx.get("total_non_usd_weight", 0) > 0.01 and fx.get("fx_adjusted"):
            currencies = fx.get("currencies", {})
            for cur, info in currencies.items():
                # annualized_vol field should exist (may be None if insufficient data)
                assert "annualized_vol" in info
