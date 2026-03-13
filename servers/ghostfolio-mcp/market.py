from __future__ import annotations

from typing import Any

from client import (
    BLOCKED_MARKET_DATA_SOURCES,
    _blocked_market_source_message,
    _clean_operation,
    _failure,
    _from_request,
    _is_blocked_market_data_source,
    _merge_params,
    _normalize_data_source,
    _request,
    _resolve_symbol_context,
    _symbol_resolution_error_code,
)


def _filter_lookup_items_blocked_sources(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    items = payload.get("items")
    if not isinstance(items, list):
        return payload

    filtered = [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and _is_blocked_market_data_source(
                item.get("dataSource") if isinstance(item.get("dataSource"), str) else None
            )
        )
    ]
    output = dict(payload)
    output["items"] = filtered
    if BLOCKED_MARKET_DATA_SOURCES:
        output["blocked_data_sources"] = sorted(BLOCKED_MARKET_DATA_SOURCES)
    return output


def register_market_tools(mcp):
    @mcp.tool()
    async def market(
        operation: str,
        symbol: str | None = None,
        data_source: str | None = None,
        query: str | None = None,
        date: str | None = None,
        include_historical_data: int | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consolidated market and symbol operations."""
        tool = "market"
        op = _clean_operation(operation)
        blocked_sources = set(BLOCKED_MARKET_DATA_SOURCES)
        valid = [
            "lookup",
            "quote",
            "quote_at_date",
            "asset",
            "market_data",
            "update_market_data",
            "markets_overview",
            "exchange_rate",
        ]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        params = params or {}
        data = data or {}

        if op == "lookup":
            q = (query or "").strip()
            if not q:
                return _failure(tool, op, "GET", "/api/v1/symbol/lookup", "invalid_input", "query is required.")
            req_params = _merge_params(params, {"query": q})
            result = await _request("GET", "/api/v1/symbol/lookup", params=req_params)
            return _from_request(
                tool,
                op,
                "GET",
                "/api/v1/symbol/lookup",
                result,
                transform=_filter_lookup_items_blocked_sources,
            )

        if op in {"quote", "asset", "market_data", "update_market_data"} and not symbol:
            return _failure(tool, op, "GET", "N/A", "invalid_input", "symbol is required.")

        if op == "quote":
            resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
            if isinstance(resolved, str):
                return _failure(
                    tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol",
                    _symbol_resolution_error_code(resolved), resolved,
                    details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
                )
            source, resolved_symbol = resolved
            req_params = _merge_params(params, {"includeHistoricalData": include_historical_data})
            result = await _request("GET", f"/api/v1/symbol/{source}/{resolved_symbol}", params=req_params)
            return _from_request(tool, op, "GET", f"/api/v1/symbol/{source}/{resolved_symbol}", result)

        if op == "quote_at_date":
            if not date:
                return _failure(tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol/:date", "invalid_input", "date is required (YYYY-MM-DD).")
            if not data_source:
                return _failure(tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol/:date", "invalid_input", "data_source is required.")
            if _is_blocked_market_data_source(data_source):
                return _failure(
                    tool, op, "GET", "/api/v1/symbol/:dataSource/:symbol/:date",
                    "policy_blocked", _blocked_market_source_message(data_source),
                    details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
                )
            source = _normalize_data_source(data_source)
            result = await _request("GET", f"/api/v1/symbol/{source}/{symbol}/{date}", params=params)
            return _from_request(tool, op, "GET", f"/api/v1/symbol/{source}/{symbol}/{date}", result)

        if op == "asset":
            resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
            if isinstance(resolved, str):
                return _failure(
                    tool, op, "GET", "/api/v1/asset/:dataSource/:symbol",
                    _symbol_resolution_error_code(resolved), resolved,
                    details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
                )
            source, resolved_symbol = resolved
            result = await _request("GET", f"/api/v1/asset/{source}/{resolved_symbol}", params=params)
            return _from_request(tool, op, "GET", f"/api/v1/asset/{source}/{resolved_symbol}", result)

        if op == "market_data":
            resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
            if isinstance(resolved, str):
                return _failure(
                    tool, op, "GET", "/api/v1/market-data/:dataSource/:symbol",
                    _symbol_resolution_error_code(resolved), resolved,
                    details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
                )
            source, resolved_symbol = resolved
            result = await _request("GET", f"/api/v1/market-data/{source}/{resolved_symbol}", params=params)
            if (not result.get("ok")) and result.get("status_code") == 404:
                return _failure(
                    tool, op, "GET", f"/api/v1/market-data/{source}/{resolved_symbol}",
                    "unsupported_endpoint",
                    "Market-data read endpoint is not available on this Ghostfolio deployment.",
                    details={
                        "hint": "Use market-intel-direct for live market data. Upgrade Ghostfolio if read-through is required.",
                        "status_code": 404,
                    },
                )
            return _from_request(tool, op, "GET", f"/api/v1/market-data/{source}/{resolved_symbol}", result)

        if op == "update_market_data":
            resolved = await _resolve_symbol_context(symbol or "", data_source, blocked_sources=blocked_sources)
            if isinstance(resolved, str):
                return _failure(
                    tool, op, "POST", "/api/v1/market-data/:dataSource/:symbol",
                    _symbol_resolution_error_code(resolved), resolved,
                    details={"blocked_data_sources": sorted(BLOCKED_MARKET_DATA_SOURCES)},
                )
            source, resolved_symbol = resolved
            result = await _request("POST", f"/api/v1/market-data/{source}/{resolved_symbol}", json=data)
            if (not result.get("ok")) and result.get("status_code") == 404:
                return _failure(
                    tool, op, "POST", f"/api/v1/market-data/{source}/{resolved_symbol}",
                    "unsupported_endpoint",
                    "Market-data write endpoint is not available on this Ghostfolio deployment.",
                    details={
                        "hint": "Use market-intel-direct for live market data. Upgrade Ghostfolio if write-back is required.",
                        "status_code": 404,
                    },
                )
            return _from_request(tool, op, "POST", f"/api/v1/market-data/{source}/{resolved_symbol}", result)

        if op == "markets_overview":
            req_params = _merge_params(params, {"includeHistoricalData": include_historical_data})
            result = await _request("GET", "/api/v1/market-data/markets", params=req_params)
            return _from_request(tool, op, "GET", "/api/v1/market-data/markets", result)

        if op == "exchange_rate":
            if not symbol:
                return _failure(tool, op, "GET", "/api/v1/exchange-rate/:symbol/:date", "invalid_input", "symbol is required.")
            if not date:
                return _failure(tool, op, "GET", "/api/v1/exchange-rate/:symbol/:date", "invalid_input", "date is required (YYYY-MM-DD).")
            result = await _request("GET", f"/api/v1/exchange-rate/{symbol}/{date}")
            if (not result.get("ok")) and result.get("status_code") == 404:
                return _failure(
                    tool, op, "GET", f"/api/v1/exchange-rate/{symbol}/{date}",
                    "not_found",
                    "Exchange rate was not found for the requested symbol/date, or the endpoint is unavailable.",
                    details={"symbol": symbol, "date": date, "status_code": 404},
                )
            return _from_request(tool, op, "GET", f"/api/v1/exchange-rate/{symbol}/{date}", result)

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")
