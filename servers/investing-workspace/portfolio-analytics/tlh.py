"""Tax-loss harvesting candidate scanning.

Provides register_tlh_tools(server).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from holdings import (
    ScopeAccountType,
    _aggregate_holdings,
    _coerce_float,
    _load_scoped_holdings,
    _portfolio_value_semantics,
)


def _replacement_suggestion(symbol: str) -> str:
    replacements = {
        "SPY": "IVV or VOO",
        "IVV": "SPY or VOO",
        "VOO": "SPY or IVV",
        "QQQ": "VGT or ONEQ",
        "VTI": "SCHB or ITOT",
        "VXUS": "IXUS or ACWX",
        "EFA": "VEA or IEFA",
        "IWM": "VTWO or SCHA",
        "BND": "AGG or SCHZ",
    }
    return replacements.get(symbol, "Use a comparable ETF or basket and avoid substantially identical replacement for 30 days.")


# ── Tool functions (module-level so they are importable by tests) ───────────


async def find_tax_loss_harvesting_candidates(
    min_loss_amount: float = 200.0,
    min_loss_pct: float = 0.05,
    estimated_marginal_rate: float = 0.30,
    scope_entity: str = "personal",
    scope_wrapper: str = "taxable",
    scope_account_types: list[ScopeAccountType] | None = None,
    scope_owner: str = "all",
    strict: bool = True,
    snapshot_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Find unrealized loss candidates in scoped taxable holdings with replacement hints."""
    min_loss_amount = max(0.0, _coerce_float(min_loss_amount, 200.0))
    min_loss_pct = max(0.0, _coerce_float(min_loss_pct, 0.05))
    estimated_marginal_rate = max(0.0, min(1.0, _coerce_float(estimated_marginal_rate, 0.30)))

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
    value_semantics = _portfolio_value_semantics(scoped["holdings"])

    candidates: list[dict[str, Any]] = []
    total_loss = 0.0

    for symbol, payload in aggregated.items():
        cost = max(payload.get("cost", 0.0), 0.0)
        value = max(payload.get("value", 0.0), 0.0)

        if cost <= 0:
            continue

        unrealized_pnl = value - cost
        loss_amount = max(0.0, -unrealized_pnl)
        loss_pct = (loss_amount / cost) if cost > 0 else 0.0

        if loss_amount < min_loss_amount or loss_pct < min_loss_pct:
            continue

        total_loss += loss_amount
        candidates.append(
            {
                "symbol": symbol,
                "cost": cost,
                "value": value,
                "loss_amount": loss_amount,
                "loss_pct": loss_pct,
                "estimated_tax_savings": loss_amount * estimated_marginal_rate,
                "replacement_hint": _replacement_suggestion(symbol),
            }
        )

    candidates.sort(key=lambda row: row["loss_amount"], reverse=True)

    return {
        "ok": True,
        "as_of": scoped.get("snapshot_as_of", datetime.now(timezone.utc).isoformat()),
        "snapshot_id": scoped.get("snapshot_id"),
        "scope": scoped["scope"],
        "warnings": scoped["warnings"],
        "coverage": scoped.get("coverage", {}),
        "thresholds": {
            "min_loss_amount": min_loss_amount,
            "min_loss_pct": min_loss_pct,
            "estimated_marginal_rate": estimated_marginal_rate,
        },
        "summary": {
            "candidate_count": len(candidates),
            "total_harvestable_loss": total_loss,
            "estimated_tax_savings": total_loss * estimated_marginal_rate,
            **value_semantics,
        },
        "candidates": candidates,
        "wash_sale_note": "Avoid substantially identical purchases 30 days before/after harvesting.",
        "provenance": scoped.get("provenance", {}),
    }


# ── Registration ────────────────────────────────────────────────────────────


def register_tlh_tools(server) -> None:
    """Register tax-loss harvesting tools on the FastMCP server."""
    server.tool()(find_tax_loss_harvesting_candidates)
