from __future__ import annotations

import pytest

import holdings as holdings_module
from stewardos_lib.portfolio_snapshot import content_addressed_snapshot_id


def test_holding_symbol_normalizes_cash_currency():
    row = {
        "symbol": "usd",
        "currency": "eur",
        "assetClass": "LIQUIDITY",
        "assetSubClass": "CASH",
    }

    assert holdings_module._holding_symbol(row) == "CASH:EUR"
    assert holdings_module._is_cash_like_holding(row) is True


def test_content_addressed_snapshot_id_is_deterministic():
    first = content_addressed_snapshot_id(
        positions=[
            {"accountId": "a1", "symbol": "AAPL", "valueInBaseCurrency": 100.0},
            {"accountId": "a2", "symbol": "CASH:USD", "valueInBaseCurrency": 25.0},
        ],
        accounts=[
            {"account_id": "a2", "classification": {"tax_wrapper": "taxable"}},
            {"account_id": "a1", "classification": {"tax_wrapper": "taxable"}},
        ],
        holdings=[{"symbol": "AAPL", "value": 100.0}],
    )
    second = content_addressed_snapshot_id(
        positions=[
            {"accountId": "a2", "symbol": "CASH:USD", "valueInBaseCurrency": 25.0},
            {"accountId": "a1", "symbol": "AAPL", "valueInBaseCurrency": 100.0},
        ],
        accounts=[
            {"classification": {"tax_wrapper": "taxable"}, "account_id": "a1"},
            {"classification": {"tax_wrapper": "taxable"}, "account_id": "a2"},
        ],
        holdings=[{"value": 100.0, "symbol": "AAPL"}],
    )

    assert first == second


@pytest.mark.asyncio
async def test_build_canonical_snapshot_rejects_as_of():
    with pytest.raises(ValueError, match="Historical as_of replay is not supported"):
        await holdings_module._build_canonical_snapshot(as_of="2026-03-01")


@pytest.mark.asyncio
async def test_load_scoped_holdings_uses_scoped_coverage(monkeypatch):
    async def _fake_snapshot(**kwargs):
        return {
            "snapshot_id": "snap_test",
            "as_of": "2026-03-06T00:00:00+00:00",
            "positions": [
                {
                    "accountId": "acct_taxable",
                    "symbol": "AAPL",
                    "valueInBaseCurrency": 100.0,
                    "currency": "USD",
                    "assetClass": "EQUITY",
                },
            ],
            "coverage": {
                "account_aware_coverage_pct": 0.5,
                "holdings_total_value": 200.0,
                "reconstructed_total_value": 100.0,
            },
            "holdings_symbol_map": {
                "AAPL": {"value": 100.0},
                "VXUS": {"value": 100.0},
            },
            "account_payload": {
                "accounts": [
                    {
                        "account_id": "acct_taxable",
                        "classification": {
                            "entity": "personal",
                            "tax_wrapper": "taxable",
                            "account_type": "brokerage",
                            "owner_person": "Principal",
                        },
                    },
                ],
                "summary": {"invalid_accounts": 0},
                "invalid_accounts": [],
            },
            "warnings": [],
            "provenance": {},
        }

    monkeypatch.setattr(holdings_module, "_build_canonical_snapshot", _fake_snapshot)

    scoped = await holdings_module._load_scoped_holdings(
        scope_entity="personal",
        scope_wrapper="taxable",
        scope_account_types=["brokerage"],
        strict=True,
        scope_owner="Principal",
    )

    assert scoped["coverage"]["account_aware_coverage_pct"] == pytest.approx(1.0)
    assert scoped["coverage"]["holdings_total_value"] == pytest.approx(100.0)
