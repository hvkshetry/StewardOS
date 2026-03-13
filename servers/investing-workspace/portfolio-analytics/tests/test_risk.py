"""Live integration tests for portfolio-analytics risk engine.

These tests exercise Ghostfolio/yfinance-backed paths.
Deterministic regime math coverage lives in ``test_risk_unit.py``.
Requires GHOSTFOLIO_URL and GHOSTFOLIO_TOKEN env vars to be set.
"""

from __future__ import annotations

import os

import drift as drift_module
import pandas as pd
import prices as prices_module
import pytest
import risk as risk_module
from drift import (
    _bucket_weights_from_holdings,
    _holding_bucket_key,
    _normalize_bucket_lookthrough,
    _normalize_bucket_target_allocations,
    analyze_bucket_allocation_drift,
)
from risk import (
    _compute_illiquid_overlay,
    _fit_student_t,
    _parametric_es_student_t,
    _risk_metrics_with_model,
    analyze_hypothetical_portfolio_risk,
    analyze_portfolio_risk,
    classify_barbell_buckets,
)
from snapshot import get_condensed_portfolio_state

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


class TestCashWeightScaling:
    """Verify cash-like balances reduce modeled returns instead of disappearing."""

    def test_download_returns_scales_tradeable_returns_by_total_weight(self, monkeypatch):
        dates = pd.date_range("2026-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"VTI": [100.0, 101.0, 102.0]}, index=dates)
        monkeypatch.setattr(prices_module, "_download_prices", lambda symbols, lookback_days: (prices, None))

        weighted, quality = prices_module._download_returns(
            {"VTI": 0.5, "USD": 0.5},
            lookback_days=2,
            scale_to_total_weight=True,
        )

        expected_last = ((102.0 / 101.0) - 1.0) * 0.5
        assert weighted.iloc[-1] == pytest.approx(expected_last, rel=1e-6)
        assert quality["zero_return_excluded_weight_sum"] == pytest.approx(0.5)
        assert quality["scaled_to_total_weight"] is True

    def test_download_returns_treats_canonical_cash_symbols_as_zero_return_ballast(self, monkeypatch):
        dates = pd.date_range("2026-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"VTI": [100.0, 101.0, 102.0]}, index=dates)
        monkeypatch.setattr(prices_module, "_download_prices", lambda symbols, lookback_days: (prices, None))

        weighted, quality = prices_module._download_returns(
            {"VTI": 0.5, "CASH:USD": 0.5},
            lookback_days=2,
            scale_to_total_weight=True,
        )

        expected_last = ((102.0 / 101.0) - 1.0) * 0.5
        assert weighted.iloc[-1] == pytest.approx(expected_last, rel=1e-6)
        assert quality["zero_return_excluded_symbols"] == ["CASH:USD"]
        assert quality["zero_return_excluded_weight_sum"] == pytest.approx(0.5)


class TestBarbellGapMath:
    """Verify safe/convex/fragile gap outputs."""

    async def test_classify_barbell_reports_gap_values(self, monkeypatch):
        async def _fake_load_scoped_holdings(**kwargs):
            return {
                "snapshot_as_of": "2026-03-05T00:00:00+00:00",
                "snapshot_id": "snap_barbell",
                "scope": {"entity": "all", "tax_wrapper": "all", "account_types": "all", "owner": "all"},
                "warnings": [],
                "coverage": {},
                "provenance": {},
                "holdings": [
                    {"symbol": "USD", "valueInBaseCurrency": 100.0, "assetClass": "LIQUIDITY", "assetSubClass": "CASH"},
                    {"symbol": "GLDM", "valueInBaseCurrency": 100.0, "assetClass": "COMMODITY", "assetSubClass": "GOLD"},
                    {"symbol": "VTI", "valueInBaseCurrency": 800.0, "assetClass": "EQUITY", "assetSubClass": "US_LARGE_BLEND"},
                ],
            }

        monkeypatch.setattr(risk_module, "_load_scoped_holdings", _fake_load_scoped_holdings)

        result = await classify_barbell_buckets(strict=False)
        assert result["ok"] is True
        assert result["safe_gap_pct"] == pytest.approx(0.05)
        assert result["safe_gap_value"] == pytest.approx(50.0)
        assert result["convex_gap_pct"] == pytest.approx(0.0)
        assert result["fragile_excess_pct"] == pytest.approx(0.10)
        assert result["signal"] == "FRAGILE"


class TestHypotheticalRisk:
    """Verify hypothetical portfolio risk uses target allocations and compares to current state."""

    async def test_hypothetical_risk_reduces_es_with_cash_target(self, monkeypatch):
        async def _fake_load_scoped_holdings(**kwargs):
            return {
                "snapshot_as_of": "2026-03-05T00:00:00+00:00",
                "snapshot_id": "snap_hypothetical",
                "scope": {"entity": "all", "tax_wrapper": "all", "account_types": "all", "owner": "all"},
                "warnings": [],
                "coverage": {},
                "provenance": {},
                "holdings": [
                    {
                        "accountId": "acct1",
                        "symbol": "VTI",
                        "valueInBaseCurrency": 1000.0,
                        "marketPrice": 100.0,
                        "quantity": 10.0,
                        "assetClass": "EQUITY",
                        "assetSubClass": "US_LARGE_BLEND",
                        "currency": "USD",
                    },
                ],
            }

        def _fake_download_returns(weights, lookback_days, holdings_meta=None, scale_to_total_weight=False):
            dates = pd.date_range("2026-01-01", periods=60, freq="B")
            risk_weight = sum(
                weight
                for symbol, weight in weights.items()
                if symbol not in {"USD", "CASH"} and not symbol.startswith("CASH:")
            )
            base = pd.Series([0.001] * 58 + [-0.04, -0.04], index=dates, dtype=float)
            scaled = base * risk_weight
            excluded_symbols = [symbol for symbol in weights if symbol == "USD" or symbol.startswith("CASH:")]
            return scaled, {
                "missing_symbols": [],
                "excluded_symbols": excluded_symbols,
                "zero_return_excluded_symbols": excluded_symbols,
                "available_symbols": [symbol for symbol in weights if symbol not in excluded_symbols],
                "original_weight_sum": sum(weights.values()),
                "tradeable_weight_sum": risk_weight,
                "available_weight_sum": risk_weight,
                "missing_tradeable_weight_sum": 0.0,
                "zero_return_excluded_weight_sum": sum(weights.get(symbol, 0.0) for symbol in excluded_symbols),
                "weight_coverage_pct": 1.0,
                "renormalized": False,
                "scaled_to_total_weight": scale_to_total_weight,
                "scale_factor": risk_weight,
                "yfinance_error": None,
                "observations": int(len(scaled)),
                "nan_fill_symbols": [],
                "data_quality_warnings": [],
            }

        monkeypatch.setattr(risk_module, "_load_scoped_holdings", _fake_load_scoped_holdings)
        monkeypatch.setattr(risk_module, "_download_returns", _fake_download_returns)

        result = await analyze_hypothetical_portfolio_risk(
            target_allocations={"USD": 0.5, "VTI": 0.5},
            include_fx_risk=False,
            include_decomposition=False,
            strict=False,
        )

        assert result["ok"] is True
        assert result["verification_pass"] is True
        assert result["improves_vs_current"] is True
        assert result["within_policy_limit"] is True
        assert result["delta_vs_current"]["es_975_1d"] < 0
        assert result["post_plan_barbell"]["safe_gap_pct"] == pytest.approx(0.0)
        assert result["post_plan_barbell"]["fragile_excess_pct"] == pytest.approx(0.0)

    async def test_hypothetical_risk_surfaces_improvement_separately_from_policy_limit(self, monkeypatch):
        async def _fake_load_scoped_holdings(**kwargs):
            return {
                "snapshot_as_of": "2026-03-05T00:00:00+00:00",
                "snapshot_id": "snap_hypothetical",
                "scope": {"entity": "all", "tax_wrapper": "all", "account_types": "all", "owner": "all"},
                "warnings": [],
                "coverage": {},
                "provenance": {},
                "holdings": [
                    {
                        "accountId": "acct1",
                        "symbol": "VTI",
                        "valueInBaseCurrency": 1000.0,
                        "marketPrice": 100.0,
                        "quantity": 10.0,
                        "assetClass": "EQUITY",
                        "assetSubClass": "US_LARGE_BLEND",
                        "currency": "USD",
                    },
                ],
            }

        def _fake_download_returns(weights, lookback_days, holdings_meta=None, scale_to_total_weight=False):
            dates = pd.date_range("2026-01-01", periods=60, freq="B")
            risk_weight = sum(
                weight
                for symbol, weight in weights.items()
                if symbol not in {"USD", "CASH"} and not symbol.startswith("CASH:")
            )
            base = pd.Series([0.001] * 58 + [-0.04, -0.04], index=dates, dtype=float)
            scaled = base * risk_weight
            return scaled, {
                "missing_symbols": [],
                "excluded_symbols": [],
                "zero_return_excluded_symbols": [],
                "available_symbols": [symbol for symbol in weights if not symbol.startswith("CASH:")],
                "original_weight_sum": sum(weights.values()),
                "tradeable_weight_sum": risk_weight,
                "available_weight_sum": risk_weight,
                "missing_tradeable_weight_sum": 0.0,
                "zero_return_excluded_weight_sum": 0.0,
                "weight_coverage_pct": 1.0,
                "renormalized": False,
                "scaled_to_total_weight": scale_to_total_weight,
                "scale_factor": risk_weight,
                "yfinance_error": None,
                "observations": int(len(scaled)),
                "nan_fill_symbols": [],
                "data_quality_warnings": [],
            }

        monkeypatch.setattr(risk_module, "_load_scoped_holdings", _fake_load_scoped_holdings)
        monkeypatch.setattr(risk_module, "_download_returns", _fake_download_returns)

        result = await analyze_hypothetical_portfolio_risk(
            target_allocations={"USD": 0.5, "VTI": 0.5},
            es_limit=0.015,
            include_fx_risk=False,
            include_decomposition=False,
            strict=False,
        )

        assert result["ok"] is True
        assert result["improves_vs_current"] is True
        assert result["within_policy_limit"] is False
        assert result["verification_pass"] is False


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
        import pandas as pd
        from fx import _adjust_returns_for_fx

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
        import pandas as pd
        from fx import _adjust_returns_for_fx

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


class TestBucketAllocationDrift:
    """Verify bucket-level IPS drift analytics helpers and tool behavior."""

    def test_normalize_bucket_targets(self):
        targets = _normalize_bucket_target_allocations({"equity:us_large_blend": 60, "fixed_income:aggregate": 40})
        assert abs(sum(targets.values()) - 1.0) < 1e-10
        assert "EQUITY:US_LARGE_BLEND" in targets
        assert "FIXED_INCOME:AGGREGATE" in targets

    def test_holding_bucket_key_uses_override(self):
        row = {
            "symbol": "AVUV",
            "assetClass": "EQUITY",
            "assetSubClass": "US_SMALL_VALUE",
        }
        key = _holding_bucket_key(row, bucket_overrides={"AVUV": "EQUITY:DM_SMALL_VALUE"})
        assert key == "EQUITY:DM_SMALL_VALUE"

    def test_holding_bucket_key_uses_yfinance_fallback_for_unclassified(self, monkeypatch):
        monkeypatch.setattr(
            drift_module,
            "_lookup_yfinance_bucket",
            lambda symbol: ("EQUITY:INTERNATIONAL_DEVELOPED", "unit_test"),
        )
        row = {"symbol": "VXUS", "assetClass": None, "assetSubClass": None}
        tracker: dict[str, dict[str, str]] = {}
        key = _holding_bucket_key(row, fallback_tracker=tracker)
        assert key == "EQUITY:INTERNATIONAL_DEVELOPED"
        assert tracker["VXUS"]["from_bucket"] == "UNCLASSIFIED"
        assert tracker["VXUS"]["to_bucket"] == "EQUITY:INTERNATIONAL_DEVELOPED"

    def test_normalize_bucket_lookthrough_percent_input(self):
        normalized = _normalize_bucket_lookthrough(
            [
                {"symbol": "VFIFX", "bucket_key": "EQUITY:US_LARGE_BLEND", "fraction_weight": 53.0},
                {"symbol": "VFIFX", "bucket_key": "EQUITY:INTERNATIONAL_DEVELOPED", "fraction_weight": 37.6},
                {"symbol": "VFIFX", "bucket_key": "FIXED_INCOME:AGGREGATE", "fraction_weight": 6.8},
                {"symbol": "VFIFX", "bucket_key": "FIXED_INCOME:TIPS", "fraction_weight": 2.6},
            ]
        )
        vfifx_rows = normalized["VFIFX"]
        assert len(vfifx_rows) == 4
        assert abs(sum(weight for _, weight in vfifx_rows) - 1.0) < 1e-10

    def test_bucket_weights_from_holdings_applies_lookthrough(self):
        weights, values, total = _bucket_weights_from_holdings(
            holdings=[
                {
                    "symbol": "VFIFX",
                    "assetClass": "EQUITY",
                    "assetSubClass": "US_LARGE_BLEND",
                    "valueInBaseCurrency": 100.0,
                }
            ],
            bucket_overrides={"VFIFX": "EQUITY:US_LARGE_BLEND"},
            bucket_lookthrough={
                "VFIFX": [
                    ("EQUITY:US_LARGE_BLEND", 0.60),
                    ("FIXED_INCOME:AGGREGATE", 0.40),
                ]
            },
        )
        assert total == 100.0
        assert abs(weights["EQUITY:US_LARGE_BLEND"] - 0.60) < 1e-10
        assert abs(weights["FIXED_INCOME:AGGREGATE"] - 0.40) < 1e-10
        assert abs(values["EQUITY:US_LARGE_BLEND"] - 60.0) < 1e-10
        assert abs(values["FIXED_INCOME:AGGREGATE"] - 40.0) < 1e-10

    async def test_bucket_drift_with_stubbed_scope(self, monkeypatch):
        async def _fake_load_scoped_holdings(**kwargs):
            return {
                "snapshot_as_of": "2026-03-04T00:00:00+00:00",
                "snapshot_id": "snap_test",
                "scope": {
                    "entity": "all",
                    "tax_wrapper": "all",
                    "account_types": "all",
                    "owner": "all",
                },
                "warnings": [],
                "coverage": {},
                "holdings": [
                    {
                        "symbol": "VOO",
                        "assetClass": "EQUITY",
                        "assetSubClass": "US_LARGE_BLEND",
                        "valueInBaseCurrency": 60.0,
                    },
                    {
                        "symbol": "BND",
                        "assetClass": "FIXED_INCOME",
                        "assetSubClass": "AGGREGATE",
                        "valueInBaseCurrency": 40.0,
                    },
                ],
                "provenance": {"source": "unit_test"},
            }

        monkeypatch.setattr(drift_module, "_load_scoped_holdings", _fake_load_scoped_holdings)

        result = await analyze_bucket_allocation_drift(
            target_bucket_allocations={
                "EQUITY:US_LARGE_BLEND": 0.50,
                "FIXED_INCOME:AGGREGATE": 0.50,
            },
            drift_threshold=0.05,
            strict=False,
        )
        assert result["ok"] is True
        assert result["bucket_lookthrough"] == []

        actions = {row["bucket_key"]: row["action"] for row in result["flagged_trades"]}
        assert actions["EQUITY:US_LARGE_BLEND"] == "sell"
        assert actions["FIXED_INCOME:AGGREGATE"] == "buy"

    async def test_bucket_drift_reports_yfinance_fallbacks(self, monkeypatch):
        async def _fake_load_scoped_holdings(**kwargs):
            return {
                "snapshot_as_of": "2026-03-04T00:00:00+00:00",
                "snapshot_id": "snap_test_fallback",
                "scope": {
                    "entity": "all",
                    "tax_wrapper": "all",
                    "account_types": "all",
                    "owner": "all",
                },
                "warnings": [],
                "coverage": {},
                "holdings": [
                    {
                        "symbol": "VXUS",
                        "assetClass": None,
                        "assetSubClass": None,
                        "valueInBaseCurrency": 100.0,
                    },
                ],
                "provenance": {"source": "unit_test"},
            }

        monkeypatch.setattr(drift_module, "_load_scoped_holdings", _fake_load_scoped_holdings)
        monkeypatch.setattr(
            drift_module,
            "_lookup_yfinance_bucket",
            lambda symbol: ("EQUITY:INTERNATIONAL_DEVELOPED", "unit_test"),
        )

        result = await analyze_bucket_allocation_drift(
            target_bucket_allocations={"EQUITY:INTERNATIONAL_DEVELOPED": 1.0},
            drift_threshold=0.01,
            strict=False,
        )
        assert result["ok"] is True
        assert len(result["yfinance_bucket_fallbacks"]) == 1
        assert result["yfinance_bucket_fallbacks"][0]["symbol"] == "VXUS"
        assert result["yfinance_bucket_fallbacks"][0]["to_bucket"] == "EQUITY:INTERNATIONAL_DEVELOPED"
        assert any("Applied yfinance metadata fallback" in warning for warning in result["warnings"])
