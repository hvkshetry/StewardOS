"""Non-live unit tests for convex ranking and degraded-data behavior."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as market_server


def _quote_payload(symbols: list[str]) -> dict[str, object]:
    return {
        "ok": True,
        "quotes": [
            {"symbol": symbol, "status": "ok", "last": 100.0}
            for symbol in symbols
        ],
    }


class TestConvexRankingCharacterization:
    def test_rank_convex_candidates_prefers_tlt_in_deflationary_regime(self, monkeypatch):
        async def _fake_regime(current_regime_override=None):
            return {"regime_label": "deflationary", "source": "test", "warnings": []}

        monkeypatch.setattr(market_server, "_infer_convex_regime_context", _fake_regime)
        monkeypatch.setattr(
            market_server,
            "get_market_snapshot",
            lambda symbols=None: _quote_payload(symbols or []),
        )

        result = asyncio.run(
            market_server.rank_convex_candidates(
                target_convex_add_pct=0.05,
                allow_options=False,
            )
        )

        assert result["ok"] is True
        assert result["warnings"] == []
        assert result["ranked_candidates"][0]["symbol"] == "TLT"
        assert result["primary_path_shortlist"][0]["symbol"] == "TLT"
        assert result["advanced_alternatives"] == []

    def test_rank_convex_candidates_surfaces_option_pricing_failures(self, monkeypatch):
        async def _fake_regime(current_regime_override=None):
            return {"regime_label": "mixed", "source": "test", "warnings": []}

        async def _fake_spread(**kwargs):
            return None

        monkeypatch.setattr(market_server, "_infer_convex_regime_context", _fake_regime)
        monkeypatch.setattr(market_server, "_estimate_spy_put_spread", _fake_spread)
        monkeypatch.setattr(
            market_server,
            "get_market_snapshot",
            lambda symbols=None: _quote_payload(symbols or []),
        )

        result = asyncio.run(
            market_server.rank_convex_candidates(
                target_convex_add_pct=0.05,
                allow_options=True,
                options_capability="vertical_spreads",
            )
        )

        assert result["ok"] is True
        assert all(candidate["instrument_type"] != "options" for candidate in result["ranked_candidates"])
        assert any(
            "Could not price options template" in warning
            for warning in result["warnings"]
        )
        assert len(result["primary_path_shortlist"]) == 3


class TestSearchMarketNewsDegradedData:
    def test_search_market_news_falls_back_to_google_news_for_empty_ticker_feed(self, monkeypatch):
        async def _fake_yfinance(symbol: str, days_back: int, limit: int):
            assert symbol == "AAPL"
            return []

        async def _fake_google(query: str, days_back: int, limit: int):
            assert query == "AAPL"
            return [
                {
                    "title": "Fallback article",
                    "url": "https://example.com/aapl",
                    "source": "example",
                    "seendate": "2026-03-08T00:00:00+00:00",
                    "language": "en",
                }
            ]

        monkeypatch.setattr(market_server, "_fetch_yfinance_ticker_news", _fake_yfinance)
        monkeypatch.setattr(market_server, "_fetch_google_news_rss", _fake_google)

        result = asyncio.run(market_server.search_market_news(query="AAPL", days_back=7, limit=10))

        assert result["ok"] is True
        assert result["source"] == "google_news"
        assert result["count"] == 1
        assert result["diagnostics"]["ticker_mode"] is True
        assert result["diagnostics"]["fallback_used"] is True

    def test_search_market_news_returns_retryable_error_when_fallback_fails(self, monkeypatch):
        async def _fake_google(query: str, days_back: int, limit: int):
            return []

        async def _fake_yfinance(symbol: str, days_back: int, limit: int):
            raise RuntimeError("provider down")

        monkeypatch.setattr(market_server, "_fetch_google_news_rss", _fake_google)
        monkeypatch.setattr(market_server, "_fetch_yfinance_ticker_news", _fake_yfinance)

        result = asyncio.run(
            market_server.search_market_news(
                query="tariff economy",
                days_back=7,
                limit=10,
            )
        )

        assert result["ok"] is False
        assert result["source"] == "yfinance"
        assert result["error_code"] == "upstream_request_failed"
        assert result["retryable"] is True
        assert result["count"] == 0
        assert result["articles"] == []
