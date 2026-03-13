#!/usr/bin/env python3
"""Direct market-intelligence MCP server (no OpenBB middle layer)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP


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
_TICKER_RE = re.compile(r'^[A-Z]{1,5}$|^\^[A-Z]{2,6}$|^[A-Z]{1,5}[=.][A-Z]{1,2}$|^[A-Z]{1,5}-[A-Z]{2,4}$')
_GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
_NEWS_CONNECT_TIMEOUT_SEC = 5.0
_NEWS_READ_TIMEOUT_SEC = 8.0
_SHILLER_DATA_PAGE_URL = os.getenv("SHILLER_CAPE_DATA_PAGE_URL", "https://shillerdata.com/")
_SHILLER_DATA_FALLBACK_URL = os.getenv(
    "SHILLER_CAPE_FALLBACK_XLS_URL",
    "https://www.econ.yale.edu/~shiller/data/ie_data.xls",
)
_SHILLER_CACHE_PATH = Path(
    os.getenv("SHILLER_CAPE_CACHE_PATH", "/tmp/market-intel-direct-shiller-cape.json")
)
_SHILLER_CACHE_TTL_SECONDS = max(
    300, int(os.getenv("SHILLER_CAPE_CACHE_TTL_SECONDS", "21600"))
)
_SHILLER_MAX_STALENESS_DAYS = max(
    1, int(os.getenv("SHILLER_CAPE_STALENESS_MAX_DAYS", "45"))
)
_OPTION_CAPABILITY_LEVELS = {"none": 0, "long_premium": 1, "vertical_spreads": 2}

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
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


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


def _cache_load(path: Path, ttl_seconds: int) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    fetched_at = _coerce_float(payload.get("fetched_at_epoch"))
    if fetched_at is None or (time.time() - fetched_at) > ttl_seconds:
        return None
    return payload


def _cache_store(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except OSError:
        return


def _is_plausible_shiller_payload(payload: dict[str, Any]) -> bool:
    value = _coerce_float(payload.get("value"))
    history_points = _coerce_float(payload.get("history_points"))
    observation_date = payload.get("observation_date")
    if value is None or value <= 1.0:
        return False
    if history_points is None or history_points < 100:
        return False
    if not isinstance(observation_date, str) or not observation_date:
        return False
    return True


def _normalize_header_label(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _parse_decimal_year_month(value: Any) -> datetime | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    year = int(numeric)
    if year < 1800 or year > 2200:
        return None
    fraction = max(0.0, numeric - year)
    month_hint = int(round(fraction * 100))
    if 1 <= month_hint <= 12:
        month = month_hint
    else:
        month = int(round(fraction * 12)) + 1
    month = max(1, min(month, 12))
    try:
        return datetime(year, month, 1, tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_shiller_xls_url(html: str) -> str | None:
    match = re.search(r'href=["\']([^"\']*ie_data\.xls[^"\']*)["\']', html, flags=re.IGNORECASE)
    if not match:
        match = re.search(r'(https?://[^"\'>\s]*ie_data\.xls[^"\'>\s]*)', html, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip()
    return urljoin(_SHILLER_DATA_PAGE_URL, candidate)


def _parse_shiller_cape_workbook(content: bytes) -> dict[str, Any]:
    workbook = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, engine="xlrd")
    if workbook is None:
        raise ValueError("Shiller workbook was empty")

    candidate_frames: list[pd.DataFrame] = []
    if isinstance(workbook, dict):
        if not workbook:
            raise ValueError("Shiller workbook was empty")
        if "Data" in workbook:
            candidate_frames.append(workbook["Data"])
        candidate_frames.extend(
            frame for sheet_name, frame in workbook.items()
            if sheet_name != "Data"
        )
    else:
        if workbook.empty:
            raise ValueError("Shiller workbook was empty")
        candidate_frames.append(workbook)

    header_row = None
    parsed = None
    for frame in candidate_frames:
        if frame is None or frame.empty:
            continue

        header_row_index = None
        best_score = -1
        for idx in range(min(len(frame), 25)):
            normalized = [_normalize_header_label(value) for value in frame.iloc[idx].tolist()]
            if "date" in normalized and any("cape" in value or value == "pe10" for value in normalized):
                score = sum(1 for token in ("date", "p", "d", "e", "cpi", "cape") if token in normalized)
                if score > best_score or (score == best_score and header_row_index is not None and idx > header_row_index):
                    header_row_index = idx
                    best_score = score

        if header_row_index is None:
            continue

        header_row = frame.iloc[header_row_index].tolist()
        parsed = frame.iloc[header_row_index + 1 :].copy()
        break

    if header_row is None or parsed is None:
        raise ValueError("Could not locate the CAPE header row in the Shiller workbook")

    parsed.columns = [
        str(value).strip() if value is not None and not (isinstance(value, float) and pd.isna(value)) else f"col_{idx}"
        for idx, value in enumerate(header_row)
    ]
    normalized_columns = {
        column: _normalize_header_label(column)
        for column in parsed.columns
    }

    date_column = next(
        (
            column
            for column, normalized in normalized_columns.items()
            if normalized == "date" or normalized.startswith("date")
        ),
        None,
    )
    cape_column = next(
        (
            column
            for column, normalized in normalized_columns.items()
            if normalized == "cape" or normalized == "pe10" or normalized.endswith("cape")
        ),
        None,
    )

    if date_column is None or cape_column is None:
        raise ValueError("Could not find date/CAPE columns in the Shiller workbook")

    rows: list[tuple[datetime, float]] = []
    for _, row in parsed.iterrows():
        observed_at = _parse_decimal_year_month(row.get(date_column))
        cape_value = _coerce_float(row.get(cape_column))
        if observed_at is None or cape_value is None or cape_value <= 0:
            continue
        rows.append((observed_at, float(cape_value)))

    if not rows:
        raise ValueError("Shiller workbook did not contain any usable CAPE rows")

    history_values = [cape for _, cape in rows]
    latest_observed_at, latest_cape = rows[-1]
    percentile = _percentile_rank(history_values, latest_cape)
    staleness_days = max(
        0, (datetime.now(timezone.utc).date() - latest_observed_at.date()).days
    )

    return {
        "value": round(latest_cape, 2),
        "observation_date": latest_observed_at.date().isoformat(),
        "percentile_vs_history": round(percentile, 1),
        "history_points": len(rows),
        "staleness_days": staleness_days,
        "stale": staleness_days > _SHILLER_MAX_STALENESS_DAYS,
    }


async def _fetch_shiller_cape_payload(provider: str = "auto") -> dict[str, Any]:
    resolved_provider = "official_shiller_dataset"
    if provider not in {"auto", resolved_provider}:
        return _error_response(
            source="shiller_cape",
            error_code="invalid_input",
            message=f"Unsupported provider '{provider}'.",
            retryable=False,
            details={"allowed": ["auto", resolved_provider]},
        )

    cached = _cache_load(_SHILLER_CACHE_PATH, _SHILLER_CACHE_TTL_SECONDS)
    if cached and _is_plausible_shiller_payload(cached):
        payload = dict(cached)
        payload.pop("fetched_at_epoch", None)
        payload["cached"] = True
        return payload

    warnings: list[str] = []
    started_at = time.monotonic()
    source_url = _SHILLER_DATA_FALLBACK_URL

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            try:
                page_response = await client.get(_SHILLER_DATA_PAGE_URL)
                page_response.raise_for_status()
                discovered_url = _extract_shiller_xls_url(page_response.text)
                if discovered_url:
                    source_url = discovered_url
                else:
                    warnings.append("Shiller data page did not expose an ie_data.xls link; using fallback URL")
            except Exception as exc:
                warnings.append(f"Failed to discover Shiller workbook URL dynamically: {exc}")

            workbook_response = await client.get(source_url)
            workbook_response.raise_for_status()

        parsed = _parse_shiller_cape_workbook(workbook_response.content)
    except Exception as exc:
        return _error_response(
            source="shiller_cape",
            error_code="upstream_request_failed",
            message=f"Failed to fetch Shiller CAPE data: {exc}",
            retryable=True,
            details={"provider": resolved_provider, "source_url": source_url},
        )

    payload = {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "provider": resolved_provider,
        "source_url": source_url,
        "warnings": warnings,
        "cached": False,
        "diagnostics": {
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "cache_ttl_seconds": _SHILLER_CACHE_TTL_SECONDS,
            "max_staleness_days": _SHILLER_MAX_STALENESS_DAYS,
        },
        **parsed,
    }
    _cache_store(
        _SHILLER_CACHE_PATH,
        {
            **payload,
            "fetched_at_epoch": time.time(),
        },
    )
    return payload


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


def _is_ticker_query(query: str) -> bool:
    """Detect if query is a stock/index/futures ticker vs a broad text search."""
    return bool(_TICKER_RE.match(query.strip()))


async def _fetch_google_news_rss(
    query: str, days_back: int, limit: int,
) -> list[dict[str, Any]]:
    """Fetch articles from Google News RSS feed, filtered by days_back."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    timeout_cfg = httpx.Timeout(
        timeout=_NEWS_READ_TIMEOUT_SEC,
        connect=_NEWS_CONNECT_TIMEOUT_SEC,
        read=_NEWS_READ_TIMEOUT_SEC,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    articles: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        resp = await client.get(_GOOGLE_NEWS_RSS_URL, params=params)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        source_el = item.find("source")
        if title_el is None or link_el is None:
            continue

        pub_date: datetime | None = None
        seendate_iso = ""
        if pub_el is not None and pub_el.text:
            try:
                pub_date = parsedate_to_datetime(pub_el.text)
                seendate_iso = pub_date.isoformat()
            except (ValueError, TypeError):
                pass

        if pub_date is not None and pub_date < cutoff:
            continue

        articles.append({
            "title": (title_el.text or "").strip(),
            "url": (link_el.text or "").strip(),
            "source": (source_el.text if source_el is not None and source_el.text else ""),
            "seendate": seendate_iso,
            "language": "en",
        })
        if len(articles) >= limit:
            break

    return articles


async def _fetch_yfinance_ticker_news(
    symbol: str, days_back: int, limit: int,
) -> list[dict[str, Any]]:
    """Fetch ticker-specific news via yfinance Ticker.get_news()."""
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp()

    def _sync_fetch() -> list[dict[str, Any]]:
        ticker = yf.Ticker(symbol)
        try:
            raw = ticker.get_news(count=min(limit, 25))
        except Exception:
            raw = getattr(ticker, "news", None) or []
        if not isinstance(raw, list):
            return []
        articles: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item
            pub_ts = content.get("pubDate") or item.get("providerPublishTime")
            if isinstance(pub_ts, str):
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pub_ts)
                    pub_ts_epoch = pub_dt.timestamp()
                    seendate_iso = pub_dt.isoformat()
                except (ValueError, TypeError):
                    pub_ts_epoch = 0
                    seendate_iso = pub_ts
            elif isinstance(pub_ts, (int, float)) and pub_ts > 0:
                pub_ts_epoch = float(pub_ts)
                seendate_iso = datetime.fromtimestamp(pub_ts_epoch, tz=timezone.utc).isoformat()
            else:
                pub_ts_epoch = 0
                seendate_iso = ""
            if pub_ts_epoch > 0 and pub_ts_epoch < cutoff_ts:
                continue
            title = content.get("title") or item.get("title", "")
            link = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
            publisher = content.get("provider", {}).get("displayName") or item.get("publisher", "")
            articles.append({
                "title": title,
                "url": link,
                "source": publisher,
                "seendate": seendate_iso,
                "language": "en",
            })
            if len(articles) >= limit:
                break
        return articles

    return await asyncio.to_thread(_sync_fetch)


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
    """Search market news via Google News RSS (broad queries) or yfinance (ticker queries)."""
    query = (query or "").strip()
    if len(query) < 3:
        return _error_response(
            source="news",
            error_code="invalid_input",
            message="query must be at least 3 characters",
            retryable=False,
            details={"hint": "Use full terms like 'artificial intelligence' instead of 'AI'."},
        )

    days_back = max(1, min(_coerce_int(days_back, 3), 30))
    limit = max(1, min(_coerce_int(limit, 20), 50))
    started_at = time.monotonic()
    ticker_mode = _is_ticker_query(query)
    articles: list[dict[str, Any]] = []
    provider: str = ""
    fallback_used = False

    try:
        if ticker_mode:
            # Primary: yfinance ticker news
            provider = "yfinance"
            try:
                articles = await _fetch_yfinance_ticker_news(query, days_back, limit)
            except Exception:
                articles = []
            if not articles:
                # Fallback: Google News RSS with ticker as search term
                provider = "google_news"
                fallback_used = True
                articles = await _fetch_google_news_rss(query, days_back, limit)
        else:
            # Primary: Google News RSS
            provider = "google_news"
            try:
                articles = await _fetch_google_news_rss(query, days_back, limit)
            except Exception:
                articles = []
            if not articles:
                # Fallback: try as ticker in case it's an unrecognized symbol
                provider = "yfinance"
                fallback_used = True
                articles = await _fetch_yfinance_ticker_news(query, days_back, limit)
    except Exception as exc:
        elapsed = round(time.monotonic() - started_at, 3)
        return _error_response(
            source=provider or "news",
            error_code="upstream_request_failed",
            message=f"Failed to fetch news: {exc}",
            retryable=True,
            details={
                "query": query,
                "ticker_mode": ticker_mode,
                "elapsed_seconds": elapsed,
            },
            extra={
                "query": query,
                "days_back": days_back,
                "count": 0,
                "articles": [],
            },
        )

    elapsed = round(time.monotonic() - started_at, 3)
    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "days_back": days_back,
        "count": len(articles),
        "articles": articles,
        "source": provider,
        "diagnostics": {
            "elapsed_seconds": elapsed,
            "ticker_mode": ticker_mode,
            "fallback_used": fallback_used,
        },
    }


# ---------------------------------------------------------------------------
# Market Temperature Gauge (Marks-inspired)
# ---------------------------------------------------------------------------


def _percentile_rank(values: list[float], current: float) -> float:
    """Compute percentile rank of current value within historical values (0-100)."""
    if not values:
        return 50.0
    below = sum(1 for v in values if v < current)
    equal = sum(1 for v in values if v == current)
    return 100.0 * (below + 0.5 * equal) / len(values)


def _normalize_options_capability(value: str | None) -> str:
    cleaned = str(value or "none").strip().lower()
    if cleaned not in _OPTION_CAPABILITY_LEVELS:
        return "none"
    return cleaned


def _summarize_candidate_reasons(
    regime_fit: float,
    convexity_quality: float,
    carry_score: float,
    simplicity_score: float,
) -> list[str]:
    reasons: list[str] = []
    if regime_fit >= 8:
        reasons.append("strong regime fit")
    elif regime_fit <= 4:
        reasons.append("weak regime fit")
    if convexity_quality >= 8:
        reasons.append("high convexity quality")
    if carry_score <= 4:
        reasons.append("meaningful carry drag")
    elif carry_score >= 8:
        reasons.append("low structural carry drag")
    if simplicity_score <= 4:
        reasons.append("high implementation complexity")
    return reasons


async def _infer_convex_regime_context(
    current_regime_override: str | None = None,
) -> dict[str, Any]:
    override = (current_regime_override or "").strip().lower()
    override_map = {
        "inflationary": "inflationary",
        "stagflation": "inflationary",
        "reflation": "inflationary",
        "deflationary": "deflationary",
        "deflation": "deflationary",
        "recession": "deflationary",
        "disinflationary": "mixed",
        "mixed": "mixed",
        "normal": "mixed",
    }
    if override:
        resolved = override_map.get(override)
        if resolved:
            return {
                "regime_label": resolved,
                "source": "override",
                "warnings": [],
            }

    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return {
            "regime_label": "mixed",
            "source": "fallback",
            "warnings": ["FRED_API_KEY not configured; defaulting convex ranking regime to mixed"],
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            dgs10, cpi = await asyncio.gather(
                _fetch_fred_observations(client, api_key, "DGS10", days_back=60, limit=10),
                _fetch_fred_observations(client, api_key, "CPIAUCSL", days_back=500, limit=16),
            )
        dgs10_obs = dgs10.get("observations", [])
        cpi_obs = cpi.get("observations", [])
        nominal_10y = (dgs10_obs[-1]["value"] / 100.0) if dgs10_obs else None
        yoy_cpi = None
        if len(cpi_obs) >= 13:
            latest = cpi_obs[-1]["value"]
            prior = cpi_obs[-13]["value"]
            if prior > 0:
                yoy_cpi = (latest - prior) / prior

        regime_label = "mixed"
        if yoy_cpi is not None and yoy_cpi >= 0.03:
            regime_label = "inflationary"
        elif nominal_10y is not None and nominal_10y >= 0.04 and (yoy_cpi is None or yoy_cpi <= 0.025):
            regime_label = "deflationary"

        return {
            "regime_label": regime_label,
            "source": "fred",
            "warnings": [],
            "nominal_10y": nominal_10y,
            "cpi_yoy": yoy_cpi,
        }
    except Exception as exc:
        return {
            "regime_label": "mixed",
            "source": "fallback",
            "warnings": [f"Failed to infer regime from FRED data: {exc}"],
        }


def _option_mid_price(option_row: pd.Series) -> float | None:
    bid = _coerce_float(option_row.get("bid"))
    ask = _coerce_float(option_row.get("ask"))
    last = _coerce_float(option_row.get("lastPrice"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last is not None and last > 0:
        return last
    if ask is not None and ask > 0:
        return ask
    if bid is not None and bid > 0:
        return bid
    return None


async def _estimate_spy_put_spread(
    *,
    target_days: int,
    long_otm: float,
    short_otm: float,
) -> dict[str, Any] | None:
    def _sync_fetch() -> dict[str, Any] | None:
        ticker = yf.Ticker("SPY")
        history = ticker.history(period="5d", interval="1d", auto_adjust=True)
        if history is None or history.empty:
            return None
        spot = float(history["Close"].dropna().iloc[-1])
        expiries = getattr(ticker, "options", []) or []
        if not expiries:
            return None

        best_expiry = None
        best_days = None
        today = datetime.now(timezone.utc).date()
        for expiry_str in expiries:
            try:
                expiry_date = datetime.fromisoformat(expiry_str).date()
            except ValueError:
                continue
            days = (expiry_date - today).days
            if days < 30:
                continue
            if best_days is None or abs(days - target_days) < abs(best_days - target_days):
                best_days = days
                best_expiry = expiry_str
        if best_expiry is None or best_days is None:
            return None

        chain = ticker.option_chain(best_expiry)
        puts = getattr(chain, "puts", None)
        if puts is None or puts.empty or "strike" not in puts.columns:
            return None
        strikes = puts["strike"].dropna().astype(float)
        if strikes.empty:
            return None

        long_target = spot * (1.0 - long_otm)
        short_target = spot * (1.0 - short_otm)
        long_strike = min(strikes.tolist(), key=lambda strike: abs(strike - long_target))
        short_strike = min(strikes.tolist(), key=lambda strike: abs(strike - short_target))
        if short_strike >= long_strike:
            return None

        long_row = puts.loc[puts["strike"] == long_strike].iloc[0]
        short_row = puts.loc[puts["strike"] == short_strike].iloc[0]
        long_mid = _option_mid_price(long_row)
        short_mid = _option_mid_price(short_row)
        if long_mid is None or short_mid is None:
            return None

        debit = max(long_mid - short_mid, 0.0)
        min_open_interest = min(
            int(_coerce_float(long_row.get("openInterest")) or 0),
            int(_coerce_float(short_row.get("openInterest")) or 0),
        )
        return {
            "spot_price": round(spot, 2),
            "expiry": best_expiry,
            "days_to_expiry": best_days,
            "long_strike": round(float(long_strike), 2),
            "short_strike": round(float(short_strike), 2),
            "net_debit_per_share": round(debit, 2),
            "net_debit_pct_spot": round((debit / spot) if spot > 0 else 0.0, 4),
            "min_open_interest": min_open_interest,
        }

    return await asyncio.to_thread(_sync_fetch)


@server.tool()
async def get_shiller_cape(provider: str = "auto") -> dict[str, Any]:
    """Get the latest strict Shiller CAPE value from the official published dataset."""
    return await _fetch_shiller_cape_payload(provider=provider)


@server.tool()
async def rank_convex_candidates(
    target_convex_add_pct: float | None = None,
    target_convex_add_value: float | None = None,
    scope_wrapper: str = "all",
    allow_options: bool = False,
    options_capability: str = "none",
    current_regime_override: str | None = None,
) -> dict[str, Any]:
    """Rank retail-accessible convex candidates by regime fit, carry drag, and implementation burden."""
    resolved_options_capability = _normalize_options_capability(options_capability)
    regime_context = await _infer_convex_regime_context(current_regime_override=current_regime_override)
    warnings = list(regime_context.get("warnings", []))

    static_candidates: list[dict[str, Any]] = [
        {
            "symbol": "GLDM",
            "instrument_type": "etf",
            "role": "gold hedge",
            "regime_fit": {"inflationary": 9.0, "deflationary": 4.5, "mixed": 7.0},
            "convexity_quality": 6.5,
            "carry_score": 8.5,
            "liquidity_score": 8.0,
            "tax_fit_score": 8.0,
            "simplicity_score": 9.5,
            "primary_path_eligible": True,
        },
        {
            "symbol": "IAU",
            "instrument_type": "etf",
            "role": "gold hedge",
            "regime_fit": {"inflationary": 8.5, "deflationary": 4.0, "mixed": 6.8},
            "convexity_quality": 6.5,
            "carry_score": 8.0,
            "liquidity_score": 8.5,
            "tax_fit_score": 8.0,
            "simplicity_score": 9.0,
            "primary_path_eligible": True,
        },
        {
            "symbol": "DBMF",
            "instrument_type": "etf",
            "role": "managed futures",
            "regime_fit": {"inflationary": 8.5, "deflationary": 6.5, "mixed": 7.5},
            "convexity_quality": 7.5,
            "carry_score": 6.0,
            "liquidity_score": 7.0,
            "tax_fit_score": 7.0,
            "simplicity_score": 7.5,
            "primary_path_eligible": True,
        },
        {
            "symbol": "KMLM",
            "instrument_type": "etf",
            "role": "managed futures",
            "regime_fit": {"inflationary": 8.0, "deflationary": 6.5, "mixed": 7.0},
            "convexity_quality": 7.0,
            "carry_score": 5.5,
            "liquidity_score": 6.5,
            "tax_fit_score": 7.0,
            "simplicity_score": 7.0,
            "primary_path_eligible": True,
        },
        {
            "symbol": "CAOS",
            "instrument_type": "etf",
            "role": "tail risk ETF",
            "regime_fit": {"inflationary": 6.0, "deflationary": 8.5, "mixed": 8.0},
            "convexity_quality": 9.0,
            "carry_score": 3.5,
            "liquidity_score": 5.5,
            "tax_fit_score": 7.0,
            "simplicity_score": 7.0,
            "primary_path_eligible": True,
        },
        {
            "symbol": "TLT",
            "instrument_type": "etf",
            "role": "duration hedge",
            "regime_fit": {"inflationary": 2.5, "deflationary": 9.0, "mixed": 5.5},
            "convexity_quality": 7.5,
            "carry_score": 7.0,
            "liquidity_score": 9.0,
            "tax_fit_score": 7.0,
            "simplicity_score": 9.0,
            "primary_path_eligible": True,
        },
    ]

    quotes = get_market_snapshot([candidate["symbol"] for candidate in static_candidates])
    quote_map = {
        row.get("symbol"): row
        for row in quotes.get("quotes", [])
        if isinstance(row, dict) and row.get("status") == "ok"
    }

    regime_label = str(regime_context.get("regime_label", "mixed")).strip().lower()
    weighted_candidates: list[dict[str, Any]] = []
    for candidate in static_candidates:
        regime_fit = candidate["regime_fit"].get(regime_label, candidate["regime_fit"]["mixed"])
        convexity_quality = candidate["convexity_quality"]
        carry_score = candidate["carry_score"]
        liquidity_score = candidate["liquidity_score"]
        tax_fit_score = candidate["tax_fit_score"]
        simplicity_score = candidate["simplicity_score"]
        total_score = (
            (regime_fit / 10.0) * 30.0
            + (convexity_quality / 10.0) * 25.0
            + (carry_score / 10.0) * 15.0
            + (liquidity_score / 10.0) * 10.0
            + (tax_fit_score / 10.0) * 10.0
            + (simplicity_score / 10.0) * 10.0
        )
        weighted_candidates.append(
            {
                "symbol": candidate["symbol"],
                "instrument_type": candidate["instrument_type"],
                "role": candidate["role"],
                "primary_path_eligible": candidate["primary_path_eligible"],
                "score": round(total_score, 1),
                "score_breakdown": {
                    "regime_fit": round(regime_fit, 1),
                    "convexity_quality": round(convexity_quality, 1),
                    "carry_drag_score": round(carry_score, 1),
                    "liquidity_score": round(liquidity_score, 1),
                    "tax_location_fit_score": round(tax_fit_score, 1),
                    "implementation_simplicity_score": round(simplicity_score, 1),
                },
                "market_snapshot": quote_map.get(candidate["symbol"]),
                "reasons": _summarize_candidate_reasons(
                    regime_fit=regime_fit,
                    convexity_quality=convexity_quality,
                    carry_score=carry_score,
                    simplicity_score=simplicity_score,
                ),
            }
        )

    options_candidates: list[dict[str, Any]] = []
    allow_option_candidates = (
        bool(allow_options)
        and _OPTION_CAPABILITY_LEVELS.get(resolved_options_capability, 0)
        >= _OPTION_CAPABILITY_LEVELS["vertical_spreads"]
    )
    if allow_option_candidates:
        for template_name, long_otm, short_otm in (
            ("SPY_90D_10_25_OTM_PUT_SPREAD", 0.10, 0.25),
            ("SPY_90D_15_30_OTM_PUT_SPREAD", 0.15, 0.30),
        ):
            estimate = await _estimate_spy_put_spread(
                target_days=90, long_otm=long_otm, short_otm=short_otm
            )
            if estimate is None:
                warnings.append(f"Could not price options template {template_name} from yfinance")
                continue
            regime_fit = 7.5 if regime_label == "inflationary" else 9.0 if regime_label == "deflationary" else 8.5
            convexity_quality = 10.0
            carry_score = max(1.5, 7.0 - (estimate["net_debit_pct_spot"] * 20.0))
            liquidity_score = 8.5 if estimate["min_open_interest"] >= 500 else 6.5
            tax_fit_score = 4.0
            simplicity_score = 2.0
            total_score = (
                (regime_fit / 10.0) * 30.0
                + (convexity_quality / 10.0) * 25.0
                + (carry_score / 10.0) * 15.0
                + (liquidity_score / 10.0) * 10.0
                + (tax_fit_score / 10.0) * 10.0
                + (simplicity_score / 10.0) * 10.0
            )
            options_candidates.append(
                {
                    "symbol": template_name,
                    "instrument_type": "options",
                    "role": "tail hedge",
                    "primary_path_eligible": False,
                    "score": round(total_score, 1),
                    "score_breakdown": {
                        "regime_fit": round(regime_fit, 1),
                        "convexity_quality": round(convexity_quality, 1),
                        "carry_drag_score": round(carry_score, 1),
                        "liquidity_score": round(liquidity_score, 1),
                        "tax_location_fit_score": round(tax_fit_score, 1),
                        "implementation_simplicity_score": round(simplicity_score, 1),
                    },
                    "market_snapshot": estimate,
                    "reasons": _summarize_candidate_reasons(
                        regime_fit=regime_fit,
                        convexity_quality=convexity_quality,
                        carry_score=carry_score,
                        simplicity_score=simplicity_score,
                    ),
                }
            )
    elif allow_options:
        warnings.append(
            "Options were requested but options_capability does not permit vertical spreads; excluding options candidates"
        )

    ranked = sorted(
        [*weighted_candidates, *options_candidates],
        key=lambda candidate: candidate["score"],
        reverse=True,
    )
    primary_candidates = [candidate for candidate in ranked if candidate.get("primary_path_eligible")]

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "scope_wrapper": scope_wrapper,
        "target_convex_add_pct": round(float(target_convex_add_pct or 0.0), 4),
        "target_convex_add_value": round(float(target_convex_add_value or 0.0), 2),
        "allow_options": bool(allow_options),
        "options_capability": resolved_options_capability,
        "regime_context": regime_context,
        "warnings": warnings,
        "ranked_candidates": ranked,
        "primary_path_shortlist": primary_candidates[:3],
        "advanced_alternatives": [candidate for candidate in ranked if not candidate.get("primary_path_eligible")][:3],
    }


@server.tool()
async def compute_market_temperature(
    vix_lookback_years: int = 5,
    cape_value: float | None = None,
    cape_long_term_median: float = 17.0,
) -> dict[str, Any]:
    """Compute a strict market-temperature composite from VIX, CAPE, credit spreads, and equity risk premium."""
    started_at = time.monotonic()
    api_key = os.getenv("FRED_API_KEY", "").strip()
    components: list[dict[str, Any]] = []
    warnings: list[str] = []
    missing_components: list[str] = []
    component_sources: dict[str, str] = {}
    component_staleness_days: dict[str, int | None] = {}

    # 1. VIX percentile
    try:
        vix_ticker = yf.Ticker("^VIX")
        vix_hist = vix_ticker.history(period=f"{vix_lookback_years}y", interval="1d")
        if not vix_hist.empty and "Close" in vix_hist.columns:
            vix_values = vix_hist["Close"].dropna().tolist()
            current_vix = vix_values[-1] if vix_values else 20.0
            vix_score = _percentile_rank(vix_values, current_vix)
            components.append({
                "name": "vix_percentile",
                "value": round(current_vix, 2),
                "score": round(vix_score, 1),
                "description": f"VIX {current_vix:.1f} at {vix_score:.0f}th percentile vs {vix_lookback_years}yr history",
                "source": "yfinance",
                "observation_date": datetime.now(timezone.utc).date().isoformat(),
                "staleness_days": 0,
            })
            component_sources["vix_percentile"] = "yfinance"
            component_staleness_days["vix_percentile"] = 0
        else:
            warnings.append("VIX history unavailable")
            missing_components.append("vix_percentile")
    except Exception as exc:
        warnings.append(f"VIX fetch failed: {exc}")
        missing_components.append("vix_percentile")

    # 2. Strict CAPE / Shiller PE
    effective_cape = None
    cape_payload = None
    if cape_value is not None and cape_value > 0:
        effective_cape = float(cape_value)
        cape_payload = {
            "provider": "input_override",
            "observation_date": None,
            "staleness_days": None,
            "warnings": [],
        }
    else:
        cape_payload = await _fetch_shiller_cape_payload(provider="auto")
        if cape_payload.get("ok") is True:
            effective_cape = _coerce_float(cape_payload.get("value"))
            warnings.extend(cape_payload.get("warnings", []))
        else:
            warnings.append(cape_payload.get("message", "Strict CAPE unavailable"))

    if effective_cape is not None:
        cape_ratio = effective_cape / cape_long_term_median
        cape_score = min(100.0, max(0.0, (cape_ratio - 0.5) * 66.67))
        components.append({
            "name": "cape_percentile",
            "value": round(effective_cape, 1),
            "score": round(cape_score, 1),
            "description": f"CAPE {effective_cape:.1f} vs median {cape_long_term_median} (ratio {cape_ratio:.2f})",
            "source": cape_payload.get("provider"),
            "observation_date": cape_payload.get("observation_date"),
            "staleness_days": cape_payload.get("staleness_days"),
        })
        component_sources["cape_percentile"] = str(cape_payload.get("provider", "unknown"))
        component_staleness_days["cape_percentile"] = cape_payload.get("staleness_days")
    else:
        missing_components.append("cape_percentile")
        warnings.append("Strict CAPE value unavailable")

    # 3. Credit spread (FRED BAMLH0A0HYM2)
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                fred_data = await _fetch_fred_observations(
                    client, api_key, "BAMLH0A0HYM2",
                    days_back=365 * 5, limit=2000,
                )
            obs = fred_data.get("observations", [])
            if obs:
                spread_values = [o["value"] for o in obs]
                current_spread = spread_values[-1]
                # Invert: tight spreads = hot market (high score), wide spreads = cold
                raw_pctile = _percentile_rank(spread_values, current_spread)
                credit_score = 100.0 - raw_pctile  # Invert so tight spreads → high temperature
                components.append({
                    "name": "credit_spread",
                    "value": round(current_spread, 2),
                    "score": round(credit_score, 1),
                    "description": f"HY OAS {current_spread:.0f}bp at {raw_pctile:.0f}th pctile (inverted: tighter = hotter)",
                    "source": "fred:BAMLH0A0HYM2",
                    "observation_date": fred_data.get("latest_observation_date"),
                    "staleness_days": None,
                })
                latest_date = _parse_iso_date(f"{fred_data.get('latest_observation_date')}T00:00:00+00:00")
                credit_staleness = (
                    max(0, (datetime.now(timezone.utc).date() - latest_date.date()).days)
                    if latest_date is not None
                    else None
                )
                component_sources["credit_spread"] = "fred:BAMLH0A0HYM2"
                component_staleness_days["credit_spread"] = credit_staleness
                components[-1]["staleness_days"] = credit_staleness
            else:
                warnings.append("FRED BAMLH0A0HYM2 returned no observations")
                missing_components.append("credit_spread")
        except Exception as exc:
            warnings.append(f"Credit spread fetch failed: {exc}")
            missing_components.append("credit_spread")
    else:
        warnings.append("FRED_API_KEY not configured — credit spread component skipped")
        missing_components.append("credit_spread")

    # 4. Equity risk premium
    erp = None
    try:
        earnings_yield = None
        real_risk_free = None

        if effective_cape and effective_cape > 0:
            earnings_yield = 1.0 / effective_cape

        if api_key:
            async with httpx.AsyncClient(timeout=15.0) as client:
                dgs10 = await _fetch_fred_observations(client, api_key, "DGS10", days_back=30, limit=10)
                cpi = await _fetch_fred_observations(client, api_key, "CPIAUCSL", days_back=400, limit=15)

            dgs10_obs = dgs10.get("observations", [])
            cpi_obs = cpi.get("observations", [])

            if dgs10_obs and len(cpi_obs) >= 2:
                nominal_10y = dgs10_obs[-1]["value"] / 100.0
                cpi_latest = cpi_obs[-1]["value"]
                cpi_prior = cpi_obs[-13]["value"] if len(cpi_obs) >= 14 else cpi_obs[0]["value"]
                yoy_cpi = (cpi_latest - cpi_prior) / cpi_prior if cpi_prior > 0 else 0.03
                real_risk_free = nominal_10y - yoy_cpi

        if earnings_yield is not None and real_risk_free is not None:
            erp = earnings_yield - real_risk_free
            erp_score = min(100.0, max(0.0, (0.06 - erp) / 0.06 * 100.0))
            dgs10_latest = dgs10.get("latest_observation_date") if api_key else None
            cpi_latest_date = cpi.get("latest_observation_date") if api_key else None
            latest_reference = cpi_latest_date or dgs10_latest
            reference_dt = _parse_iso_date(f"{latest_reference}T00:00:00+00:00") if latest_reference else None
            erp_staleness = (
                max(0, (datetime.now(timezone.utc).date() - reference_dt.date()).days)
                if reference_dt is not None
                else None
            )
            components.append({
                "name": "equity_risk_premium",
                "value": round(erp, 4),
                "score": round(erp_score, 1),
                "description": f"ERP {erp:.2%} (earnings yield {earnings_yield:.2%} - real Rf {real_risk_free:.2%})",
                "source": "derived:strict_cape+fred",
                "observation_date": latest_reference,
                "staleness_days": erp_staleness,
            })
            component_sources["equity_risk_premium"] = "derived:strict_cape+fred"
            component_staleness_days["equity_risk_premium"] = erp_staleness
        else:
            warnings.append("Equity risk premium unavailable — need CAPE + FRED data")
            missing_components.append("equity_risk_premium")
    except Exception as exc:
        warnings.append(f"ERP computation failed: {exc}")
        missing_components.append("equity_risk_premium")

    missing_components = sorted(set(missing_components))
    partial_score = round(sum(c["score"] for c in components) / len(components), 1) if components else None
    status = "complete" if not missing_components else "incomplete"
    composite = None
    label = None
    posture = None
    if status == "complete" and components:
        composite = partial_score
        if composite is not None and composite >= 85:
            label = "extreme_heat"
            posture = "Defensive: raise cash, raise quality, reduce leverage"
        elif composite is not None and composite >= 70:
            label = "hot"
            posture = "Cautious: trim marginal positions, build cash buffer"
        elif composite is not None and composite >= 30:
            label = "normal"
            posture = "Neutral: maintain current allocation, rebalance on drift"
        else:
            label = "cold"
            posture = "Opportunistic: lean into risk, deploy cash into equities"

    elapsed = round(time.monotonic() - started_at, 3)
    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "temperature": {
            "score": composite,
            "label": label,
            "posture": posture,
        },
        "components": components,
        "thresholds": {"cold": "<30", "normal": "30-70", "hot": "70-85", "extreme_heat": ">85"},
        "warnings": warnings,
        "missing_components": missing_components,
        "component_sources": component_sources,
        "component_staleness_days": component_staleness_days,
        "diagnostics": {
            "elapsed_seconds": elapsed,
            "components_available": len(components),
            "partial_score": partial_score,
            "strict_cape_required": True,
        },
    }


if __name__ == "__main__":
    server.run(transport="stdio")
