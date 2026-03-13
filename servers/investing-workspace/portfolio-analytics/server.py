#!/usr/bin/env python3
"""Portfolio analytics MCP server — thin orchestrator.

Creates the FastMCP instance and delegates tool registration to domain modules:
  - holdings.py  — account taxonomy validation
  - snapshot.py  — canonical snapshot + portfolio state
  - risk.py      — risk metrics, Student-t ES, vol regime, decomposition, stress, barbell
  - drift.py     — symbol-level and bucket-level allocation drift
  - tlh.py       — tax-loss harvesting
  - prices.py    — yfinance downloads (utility, no tools)
  - fx.py        — FX exposure/adjustment (utility, no tools)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("portfolio-analytics")

# ── Register domain tools ───────────────────────────────────────────────────

from holdings import register_holdings_tools   # noqa: E402
from snapshot import register_snapshot_tools   # noqa: E402
from risk import register_risk_tools           # noqa: E402
from drift import register_drift_tools         # noqa: E402
from tlh import register_tlh_tools             # noqa: E402

register_holdings_tools(server)
register_snapshot_tools(server)
register_risk_tools(server)
register_drift_tools(server)
register_tlh_tools(server)


if __name__ == "__main__":
    server.run(transport="stdio")
