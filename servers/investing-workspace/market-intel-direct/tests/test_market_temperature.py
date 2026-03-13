"""Unit tests for strict CAPE, market-temperature completeness, and convex ranking."""

from __future__ import annotations

import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as market_server


class TestShillerCapeParsing:
    def test_parse_shiller_workbook(self, monkeypatch):
        frame = pd.DataFrame(
            [
                ["Noise", None, None],
                ["Date", "P", "CAPE"],
                [2025.01, 100.0, 28.2],
                [2025.02, 101.0, 29.4],
            ]
        )
        monkeypatch.setattr(market_server.pd, "read_excel", lambda *args, **kwargs: frame)

        result = market_server._parse_shiller_cape_workbook(b"fake workbook bytes")
        assert result["value"] == 29.4
        assert result["observation_date"] == "2025-02-01"
        assert result["history_points"] == 2
        assert "staleness_days" in result


class TestMarketTemperature:
    def test_compute_market_temperature_incomplete_without_strict_cape(self, monkeypatch):
        class _FakeTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, period="5y", interval="1d"):
                return pd.DataFrame({"Close": [15.0, 18.0, 22.0, 25.0]})

        async def _fake_cape(provider="auto"):
            return {"ok": False, "message": "Strict CAPE unavailable"}

        monkeypatch.delenv("FRED_API_KEY", raising=False)
        monkeypatch.setattr(market_server.yf, "Ticker", _FakeTicker)
        monkeypatch.setattr(market_server, "_fetch_shiller_cape_payload", _fake_cape)

        result = asyncio.run(market_server.compute_market_temperature())
        assert result["ok"] is True
        assert result["status"] == "incomplete"
        assert result["temperature"]["score"] is None
        assert "cape_percentile" in result["missing_components"]


class TestConvexRanking:
    def test_rank_convex_candidates_blocks_options_without_capability(self, monkeypatch):
        async def _fake_regime(current_regime_override=None):
            return {"regime_label": "mixed", "source": "test", "warnings": []}

        monkeypatch.setattr(market_server, "_infer_convex_regime_context", _fake_regime)
        monkeypatch.setattr(
            market_server,
            "get_market_snapshot",
            lambda symbols=None: {
                "ok": True,
                "quotes": [
                    {"symbol": symbol, "status": "ok", "last": 100.0}
                    for symbol in (symbols or [])
                ],
            },
        )

        result = asyncio.run(
            market_server.rank_convex_candidates(
                target_convex_add_pct=0.05,
                allow_options=True,
                options_capability="none",
            )
        )
        assert result["ok"] is True
        assert all(row["instrument_type"] != "options" for row in result["ranked_candidates"])
        assert any("Options were requested" in warning for warning in result["warnings"])

    def test_rank_convex_candidates_includes_options_with_capability(self, monkeypatch):
        async def _fake_regime(current_regime_override=None):
            return {"regime_label": "deflationary", "source": "test", "warnings": []}

        async def _fake_spread(**kwargs):
            return {
                "spot_price": 600.0,
                "expiry": "2026-06-19",
                "days_to_expiry": 92,
                "long_strike": 540.0,
                "short_strike": 450.0,
                "net_debit_per_share": 4.0,
                "net_debit_pct_spot": 0.0067,
                "min_open_interest": 1200,
            }

        monkeypatch.setattr(market_server, "_infer_convex_regime_context", _fake_regime)
        monkeypatch.setattr(market_server, "_estimate_spy_put_spread", _fake_spread)
        monkeypatch.setattr(
            market_server,
            "get_market_snapshot",
            lambda symbols=None: {
                "ok": True,
                "quotes": [
                    {"symbol": symbol, "status": "ok", "last": 100.0}
                    for symbol in (symbols or [])
                ],
            },
        )

        result = asyncio.run(
            market_server.rank_convex_candidates(
                target_convex_add_pct=0.05,
                allow_options=True,
                options_capability="vertical_spreads",
            )
        )
        assert result["ok"] is True
        assert any(row["instrument_type"] == "options" for row in result["ranked_candidates"])
        assert result["advanced_alternatives"]
