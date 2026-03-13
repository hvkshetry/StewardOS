"""household-tax-mcp exact 2025/2026 US+MA engine."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from planning import register_planning_tools
from readiness import register_readiness_tools
from returns import register_return_tools
from store import _ensure_db_ready

_ensure_db_ready()

mcp = FastMCP(
    "household-tax-mcp",
    instructions=(
        "Exact 2025/2026 household-tax engine for supported US + Massachusetts individual and "
        "fiduciary cases. Supports standard or itemized deductions, child tax credit, and AMT "
        "exposure for individuals. The server fails closed on unsupported entities, tax years, "
        "income categories, credits, and forms instead of approximating."
    ),
)

register_readiness_tools(mcp)
register_return_tools(mcp)
register_planning_tools(mcp)

if __name__ == "__main__":
    mcp.run()
