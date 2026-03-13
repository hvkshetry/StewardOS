"""FastMCP schema regression tests for estate people tools."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
async def test_list_people_output_schema_is_enveloped():
    from people import register_people_tools

    async def get_pool():
        raise RuntimeError("get_pool should not be called for schema inspection")

    mcp = FastMCP("estate-people-schema-test")
    register_people_tools(mcp, get_pool)

    tools = await mcp.list_tools()
    by_name = {tool.name: tool for tool in tools}

    assert by_name["list_people"].outputSchema is not None
    schema = by_name["list_people"].outputSchema
    assert schema["type"] == "object"
    assert {"status", "errors", "data"} <= set(schema["properties"])
