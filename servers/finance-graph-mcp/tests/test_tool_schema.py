"""FastMCP schema regression tests for enveloped finance tools."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
async def test_list_liability_types_output_schema_is_enveloped():
    from liabilities import register_liabilities_tools

    async def get_pool():
        raise RuntimeError("get_pool should not be called for schema inspection")

    mcp = FastMCP("finance-liability-schema-test")
    register_liabilities_tools(mcp, get_pool)

    tools = await mcp.list_tools()
    by_name = {tool.name: tool for tool in tools}

    assert by_name["list_liability_types"].outputSchema is not None
    schema = by_name["list_liability_types"].outputSchema
    assert schema["type"] == "object"
    assert {"status", "errors", "data"} <= set(schema["properties"])
