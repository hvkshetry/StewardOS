"""MCP server for Ghostfolio with a consolidated, operation-based tool surface."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from accounts import register_account_tools
from market import register_market_tools
from orders import register_order_tools
from portfolio import register_portfolio_tools
from reference import register_reference_tools


mcp = FastMCP(
    "ghostfolio-mcp",
    instructions=(
        "Ghostfolio consolidated MCP server. Exposes operation-based tools for account, "
        "portfolio, order, market, reference, and system endpoints with taxonomy helpers."
    ),
)

register_account_tools(mcp)
register_portfolio_tools(mcp)
register_order_tools(mcp)
register_market_tools(mcp)
register_reference_tools(mcp)


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio", show_banner=False)
    except TypeError:
        mcp.run(transport="stdio")
