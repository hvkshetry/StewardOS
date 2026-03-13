"""Canonical snapshot building, caching, and portfolio state tools.

Provides register_snapshot_tools(server).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from holdings import (
    ScopeAccountType,
    _aggregate_holdings,
    _coerce_float,
    _effective_position_count,
    _load_scoped_holdings,
    _portfolio_value_semantics,
    _weights_from_aggregated,
    MIN_SCOPE_COVERAGE_PCT,
)


# ── Tool functions (module-level so they are importable by tests) ───────────


async def validate_account_scope_coverage(
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Validate account-aware position coverage before scoped analytics."""
    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=False,
            snapshot_id=snapshot_id,
            as_of=as_of,
            scope_owner=scope_owner,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    coverage = scoped.get("coverage", {})
    coverage_pct = _coerce_float(coverage.get("account_aware_coverage_pct"), 0.0)
    strict_ok = coverage_pct >= MIN_SCOPE_COVERAGE_PCT

    return {
        "ok": strict_ok if strict else True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped.get("scope", {}),
        "warnings": scoped.get("warnings", []),
        "coverage": coverage,
        "strict_check": {
            "requested": strict,
            "minimum_required_pct": MIN_SCOPE_COVERAGE_PCT,
            "pass": strict_ok,
        },
        "provenance": scoped.get("provenance", {}),
    }


async def get_condensed_portfolio_state(
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Return scoped holdings and aggregate portfolio state from Ghostfolio."""
    try:
        scoped = await _load_scoped_holdings(
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_account_types=scope_account_types,
            strict=strict,
            snapshot_id=snapshot_id,
            as_of=as_of,
            scope_owner=scope_owner,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    aggregated = _aggregate_holdings(scoped["holdings"])
    weights, total_value = _weights_from_aggregated(aggregated)
    total_cost = sum(max(v["cost"], 0.0) for v in aggregated.values())
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    top_positions = sorted(
        (
            {
                "symbol": symbol,
                "value": payload["value"],
                "weight": weights.get(symbol, 0.0),
                "cost": payload["cost"],
                "unrealized_pnl": payload["value"] - payload["cost"],
            }
            for symbol, payload in aggregated.items()
        ),
        key=lambda row: row["value"],
        reverse=True,
    )[:15]

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "account_taxonomy": {
            "summary": scoped["accounts_summary"],
            "invalid_accounts": scoped["invalid_accounts"],
        },
        "coverage": scoped.get("coverage", {}),
        "portfolio": {
            "holdings_count": len(scoped["holdings"]),
            "symbols_count": len(aggregated),
            "total_value": total_value,
            **value_semantics,
            "total_cost": total_cost,
            "unrealized_pnl": total_value - total_cost,
            "cash_proxy_weight": max(0.0, 1.0 - sum(weights.values())),
            "weight_hhi": sum(w * w for w in weights.values()),
            "effective_positions": _effective_position_count(weights),
            "largest_position_weight": max(weights.values()) if weights else 0.0,
            "value_field_semantics": {
                "investments_value_ex_cash": "Invested assets excluding cash balances.",
                "cash_balance": "Cash and cash-like balances from scoped accounts.",
                "net_worth_total": "Invested assets plus cash balances.",
            },
        },
        "top_positions": top_positions,
        "provenance": scoped.get("provenance", {}),
    }


# ── Registration ────────────────────────────────────────────────────────────


def register_snapshot_tools(server) -> None:
    """Register snapshot / portfolio-state tools on the FastMCP server."""
    server.tool()(validate_account_scope_coverage)
    server.tool()(get_condensed_portfolio_state)
