"""Integration tests for search_market_news (Google News RSS + yfinance).

These tests hit live APIs — no mocks. Run with: pytest tests/test_news.py -v
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import _is_ticker_query, search_market_news


# ---------------------------------------------------------------------------
# Unit: ticker detection
# ---------------------------------------------------------------------------


class TestTickerDetection:
    def test_simple_ticker(self):
        assert _is_ticker_query("AAPL") is True

    def test_index_ticker(self):
        assert _is_ticker_query("^GSPC") is True

    def test_futures_ticker(self):
        assert _is_ticker_query("CL=F") is True

    def test_dot_ticker(self):
        assert _is_ticker_query("BRK.B") is True

    def test_crypto_ticker(self):
        assert _is_ticker_query("BTC-USD") is True

    def test_broad_query_not_ticker(self):
        assert _is_ticker_query("tariff trade policy") is False

    def test_phrase_not_ticker(self):
        assert _is_ticker_query("federal reserve") is False

    def test_short_lowercase_not_ticker(self):
        assert _is_ticker_query("oil prices") is False


# ---------------------------------------------------------------------------
# Integration: live API calls
# ---------------------------------------------------------------------------


class TestSearchMarketNewsIntegration:
    async def test_ticker_query_returns_results(self):
        result = await search_market_news(query="AAPL", days_back=7, limit=10)
        assert result["ok"] is True
        assert result["diagnostics"]["ticker_mode"] is True
        # Primary provider for ticker should be yfinance (fallback to google_news if empty)
        assert result["source"] in ("yfinance", "google_news")
        assert result["count"] > 0
        assert result["diagnostics"]["elapsed_seconds"] < 10.0
        # Verify article schema
        for article in result["articles"]:
            assert "title" in article
            assert "url" in article
            assert "source" in article
            assert "seendate" in article
            assert "language" in article

    async def test_broad_query_returns_results(self):
        result = await search_market_news(query="tariff economy", days_back=7, limit=10)
        assert result["ok"] is True
        assert result["diagnostics"]["ticker_mode"] is False
        # Primary provider for broad query should be google_news
        assert result["source"] in ("google_news", "yfinance")
        assert result["count"] > 0

    async def test_short_query_rejected(self):
        result = await search_market_news(query="ab")
        assert result["ok"] is False
        assert result["error_code"] == "invalid_input"

    async def test_invalid_ticker_falls_back(self):
        result = await search_market_news(query="ZZZZZ", days_back=3, limit=5)
        assert result["ok"] is True
        # Invalid ticker: yfinance returns 0, should fallback to Google News
        assert result["diagnostics"]["ticker_mode"] is True
        if result["count"] > 0:
            assert result["diagnostics"]["fallback_used"] is True
            assert result["source"] == "google_news"

    async def test_days_back_clamped(self):
        result = await search_market_news(query="market news", days_back=100, limit=5)
        assert result["ok"] is True
        assert result["days_back"] <= 30

    async def test_limit_clamped(self):
        result = await search_market_news(query="market news", limit=200)
        assert result["ok"] is True
        assert len(result["articles"]) <= 50
