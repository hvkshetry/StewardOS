"""Tests for canonical Plane MCP server registration."""

from server import mcp


def test_server_registers_only_canonical_tools():
    assert sorted(mcp._tool_manager._tools) == [
        "coordination",
        "project_admin",
        "work_item",
        "workspace",
    ]
