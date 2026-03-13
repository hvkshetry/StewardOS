from __future__ import annotations

from typing import Any

from client import (
    _clean_operation,
    _failure,
    _from_request,
    _normalize_data_source,
    _request,
)


def _extract_lookup_symbol_profile_id(payload: dict[str, Any], source: str, symbol: str) -> str | None:
    items = payload.get("items")
    if not isinstance(items, list):
        return None

    source_norm = _normalize_data_source(source)
    symbol_norm = symbol.strip().lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        data_source = item.get("dataSource")
        item_symbol = item.get("symbol")
        if not isinstance(data_source, str) or not isinstance(item_symbol, str):
            continue
        if _normalize_data_source(data_source) != source_norm or item_symbol.strip().lower() != symbol_norm:
            continue
        profile_id = item.get("symbolProfileId") or item.get("id")
        if isinstance(profile_id, str) and profile_id.strip():
            return profile_id.strip()
    return None


def _find_existing_benchmark(payload: Any, source: str, symbol: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, list):
        return None

    source_norm = _normalize_data_source(source)
    symbol_norm = symbol.strip().lower()
    for benchmark in benchmarks:
        if not isinstance(benchmark, dict):
            continue
        data_source = benchmark.get("dataSource")
        item_symbol = benchmark.get("symbol")
        if not isinstance(data_source, str) or not isinstance(item_symbol, str):
            continue
        if _normalize_data_source(data_source) == source_norm and item_symbol.strip().lower() == symbol_norm:
            return benchmark
    return None


async def _add_benchmark_with_fallback(source: str, symbol: str) -> dict[str, Any]:
    payload = {"dataSource": _normalize_data_source(source), "symbol": symbol.strip()}
    first = await _request("POST", "/api/v1/benchmarks", json=payload)
    if first.get("ok"):
        return first

    status_code = first.get("status_code")
    if not isinstance(status_code, int) or status_code < 500:
        return first

    await _request(
        "GET",
        f"/api/v1/symbol/{payload['dataSource']}/{payload['symbol']}",
        params={"includeHistoricalData": 0},
    )
    second = await _request("POST", "/api/v1/benchmarks", json=payload)
    if second.get("ok"):
        return second

    listed = await _request("GET", "/api/v1/benchmarks")
    if listed.get("ok"):
        existing = _find_existing_benchmark(listed.get("body"), payload["dataSource"], payload["symbol"])
        if existing is not None:
            return {"ok": True, "status_code": 200, "body": existing}

    lookup = await _request("GET", "/api/v1/symbol/lookup", params={"query": payload["symbol"]})
    if lookup.get("ok"):
        profile_id = _extract_lookup_symbol_profile_id(
            lookup.get("body") if isinstance(lookup.get("body"), dict) else {},
            payload["dataSource"],
            payload["symbol"],
        )
        if profile_id:
            by_id = await _request("POST", "/api/v1/benchmarks", json={"symbolProfileId": profile_id})
            if by_id.get("ok"):
                return by_id

    return second


def register_reference_tools(mcp):
    @mcp.tool()
    async def reference(
        operation: str,
        reference_id: str | None = None,
        data_source: str | None = None,
        symbol: str | None = None,
        start_date: str | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consolidated reference/admin operations (watchlist, benchmarks, tags, platforms, info)."""
        tool = "reference"
        op = _clean_operation(operation)
        valid = [
            "watchlist_list",
            "watchlist_add",
            "watchlist_remove",
            "benchmarks_list",
            "benchmark_add",
            "benchmark_remove",
            "benchmark_series",
            "tags_list",
            "tag_create",
            "tag_update",
            "tag_delete",
            "platform_list",
            "platform_create",
            "platform_update",
            "platform_delete",
            "info",
        ]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        data = data or {}
        params = params or {}

        if op == "watchlist_list":
            result = await _request("GET", "/api/v1/watchlist")
            return _from_request(tool, op, "GET", "/api/v1/watchlist", result)

        if op == "watchlist_add":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            if not source or not sym:
                return _failure(tool, op, "POST", "/api/v1/watchlist", "invalid_input", "data_source and symbol are required.")
            payload = {"dataSource": _normalize_data_source(str(source)), "symbol": str(sym)}
            result = await _request("POST", "/api/v1/watchlist", json=payload)
            return _from_request(tool, op, "POST", "/api/v1/watchlist", result)

        if op == "watchlist_remove":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            if not source or not sym:
                return _failure(tool, op, "DELETE", "/api/v1/watchlist/:dataSource/:symbol", "invalid_input", "data_source and symbol are required.")
            source = _normalize_data_source(str(source))
            result = await _request("DELETE", f"/api/v1/watchlist/{source}/{sym}")
            return _from_request(tool, op, "DELETE", f"/api/v1/watchlist/{source}/{sym}", result)

        if op == "benchmarks_list":
            result = await _request("GET", "/api/v1/benchmarks")
            return _from_request(tool, op, "GET", "/api/v1/benchmarks", result)

        if op == "benchmark_add":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            if not source or not sym:
                return _failure(tool, op, "POST", "/api/v1/benchmarks", "invalid_input", "data_source and symbol are required.")
            result = await _add_benchmark_with_fallback(str(source), str(sym))
            return _from_request(tool, op, "POST", "/api/v1/benchmarks", result)

        if op == "benchmark_remove":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            if not source or not sym:
                return _failure(tool, op, "DELETE", "/api/v1/benchmarks/:dataSource/:symbol", "invalid_input", "data_source and symbol are required.")
            source = _normalize_data_source(str(source))
            result = await _request("DELETE", f"/api/v1/benchmarks/{source}/{sym}")
            return _from_request(tool, op, "DELETE", f"/api/v1/benchmarks/{source}/{sym}", result)

        if op == "benchmark_series":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            started = start_date or data.get("startDate")
            if not source or not sym or not started:
                return _failure(
                    tool, op, "GET", "/api/v1/benchmarks/:dataSource/:symbol/:startDate",
                    "invalid_input", "data_source, symbol, and start_date are required.",
                )
            source = _normalize_data_source(str(source))
            result = await _request(
                "GET", f"/api/v1/benchmarks/{source}/{sym}/{started}", params=params,
            )
            return _from_request(tool, op, "GET", f"/api/v1/benchmarks/{source}/{sym}/{started}", result)

        if op == "tags_list":
            result = await _request("GET", "/api/v1/tags")
            return _from_request(tool, op, "GET", "/api/v1/tags", result)

        if op == "tag_create":
            result = await _request("POST", "/api/v1/tags", json=data)
            return _from_request(tool, op, "POST", "/api/v1/tags", result)

        if op == "tag_update":
            target = reference_id or data.get("id")
            if not target:
                return _failure(tool, op, "PUT", "/api/v1/tags/:id", "invalid_input", "reference_id (tag id) is required.")
            payload = dict(data)
            payload.setdefault("id", target)
            result = await _request("PUT", f"/api/v1/tags/{target}", json=payload)
            return _from_request(tool, op, "PUT", f"/api/v1/tags/{target}", result)

        if op == "tag_delete":
            target = reference_id or data.get("id")
            if not target:
                return _failure(tool, op, "DELETE", "/api/v1/tags/:id", "invalid_input", "reference_id (tag id) is required.")
            result = await _request("DELETE", f"/api/v1/tags/{target}")
            return _from_request(tool, op, "DELETE", f"/api/v1/tags/{target}", result)

        if op == "platform_list":
            result = await _request("GET", "/api/v1/platform")
            return _from_request(tool, op, "GET", "/api/v1/platform", result)

        if op == "platform_create":
            result = await _request("POST", "/api/v1/platform", json=data)
            return _from_request(tool, op, "POST", "/api/v1/platform", result)

        if op == "platform_update":
            target = reference_id or data.get("id")
            if not target:
                return _failure(tool, op, "PUT", "/api/v1/platform/:id", "invalid_input", "reference_id (platform id) is required.")
            payload = dict(data)
            payload.setdefault("id", target)
            result = await _request("PUT", f"/api/v1/platform/{target}", json=payload)
            return _from_request(tool, op, "PUT", f"/api/v1/platform/{target}", result)

        if op == "platform_delete":
            target = reference_id or data.get("id")
            if not target:
                return _failure(tool, op, "DELETE", "/api/v1/platform/:id", "invalid_input", "reference_id (platform id) is required.")
            result = await _request("DELETE", f"/api/v1/platform/{target}")
            return _from_request(tool, op, "DELETE", f"/api/v1/platform/{target}", result)

        if op == "info":
            result = await _request("GET", "/api/v1/info")
            return _from_request(tool, op, "GET", "/api/v1/info", result)

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")

    @mcp.tool()
    async def system(
        operation: str,
        data_source: str | None = None,
        symbol: str | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consolidated system operations (health, import/export)."""
        tool = "system"
        op = _clean_operation(operation)
        valid = ["health", "data_provider_health", "export", "import", "import_dividends"]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        params = params or {}
        data = data or {}

        if op == "health":
            result = await _request("GET", "/api/v1/health")
            return _from_request(tool, op, "GET", "/api/v1/health", result)

        if op == "data_provider_health":
            source = data_source or data.get("dataSource")
            if not source:
                return _failure(
                    tool, op, "GET", "/api/v1/health/data-provider/:dataSource",
                    "invalid_input", "data_source is required.",
                )
            source = _normalize_data_source(str(source))
            result = await _request("GET", f"/api/v1/health/data-provider/{source}")
            return _from_request(tool, op, "GET", f"/api/v1/health/data-provider/{source}", result)

        if op == "export":
            result = await _request("GET", "/api/v1/export", params=params)
            return _from_request(tool, op, "GET", "/api/v1/export", result)

        if op == "import":
            result = await _request("POST", "/api/v1/import", json=data)
            return _from_request(tool, op, "POST", "/api/v1/import", result)

        if op == "import_dividends":
            source = data_source or data.get("dataSource")
            sym = symbol or data.get("symbol")
            if not source or not sym:
                return _failure(
                    tool, op, "GET", "/api/v1/import/dividends/:dataSource/:symbol",
                    "invalid_input", "data_source and symbol are required.",
                )
            source = _normalize_data_source(str(source))
            result = await _request("GET", f"/api/v1/import/dividends/{source}/{sym}")
            return _from_request(tool, op, "GET", f"/api/v1/import/dividends/{source}/{sym}", result)

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")
