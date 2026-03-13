from __future__ import annotations

from typing import Any

from client import (
    _clean_operation,
    _failure,
    _from_request,
    _request,
)


def register_order_tools(mcp):
    @mcp.tool()
    async def order(
        operation: str,
        order_id: str | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consolidated order/activity operations."""
        tool = "order"
        op = _clean_operation(operation)
        valid = ["list", "get", "create", "update", "delete", "delete_filtered"]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        data = data or {}
        params = params or {}

        if op == "list":
            result = await _request("GET", "/api/v1/order", params=params)
            return _from_request(tool, op, "GET", "/api/v1/order", result)

        if op == "get":
            if not order_id:
                return _failure(tool, op, "GET", "/api/v1/order/:id", "invalid_input", "order_id is required.")
            result = await _request("GET", f"/api/v1/order/{order_id}")
            return _from_request(tool, op, "GET", f"/api/v1/order/{order_id}", result)

        if op == "create":
            result = await _request("POST", "/api/v1/order", json=data)
            return _from_request(tool, op, "POST", "/api/v1/order", result)

        if op == "update":
            if not order_id:
                return _failure(tool, op, "PUT", "/api/v1/order/:id", "invalid_input", "order_id is required.")
            payload = dict(data)
            payload.setdefault("id", order_id)
            result = await _request("PUT", f"/api/v1/order/{order_id}", json=payload)
            return _from_request(tool, op, "PUT", f"/api/v1/order/{order_id}", result)

        if op == "delete":
            if not order_id:
                return _failure(tool, op, "DELETE", "/api/v1/order/:id", "invalid_input", "order_id is required.")
            result = await _request("DELETE", f"/api/v1/order/{order_id}")
            return _from_request(tool, op, "DELETE", f"/api/v1/order/{order_id}", result)

        if op == "delete_filtered":
            result = await _request("DELETE", "/api/v1/order", params=params)
            return _from_request(tool, op, "DELETE", "/api/v1/order", result)

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")
