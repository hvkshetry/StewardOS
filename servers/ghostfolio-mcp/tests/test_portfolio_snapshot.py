from __future__ import annotations

import asyncio
import copy
from typing import Any

import portfolio


def _run(coro):
    return asyncio.run(coro)


def _account(
    account_id: str,
    *,
    owner_person: str,
    account_type: str = "brokerage",
    tax_wrapper: str = "taxable",
    entity: str = "personal",
    balance: float = 0.0,
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "name": f"Account {account_id}",
        "balance": balance,
        "currency": currency,
        "classification": {
            "entity": entity,
            "tax_wrapper": tax_wrapper,
            "account_type": account_type,
            "owner_person": owner_person,
            "valid": True,
            "errors": [],
        },
    }


def _account_payload(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    by_entity: dict[str, int] = {}
    by_wrapper: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    for account in accounts:
        classification = account["classification"]
        entity = classification["entity"]
        wrapper = classification["tax_wrapper"]
        account_type = classification["account_type"]
        owner_person = classification["owner_person"]
        by_entity[entity] = by_entity.get(entity, 0) + 1
        by_wrapper[wrapper] = by_wrapper.get(wrapper, 0) + 1
        by_type[account_type] = by_type.get(account_type, 0) + 1
        by_owner[owner_person] = by_owner.get(owner_person, 0) + 1

    return {
        "ok": True,
        "accounts": accounts,
        "summary": {
            "total_accounts": len(accounts),
            "valid_accounts": len(accounts),
            "invalid_accounts": 0,
            "by_entity": by_entity,
            "by_tax_wrapper": by_wrapper,
            "by_account_type": by_type,
            "by_owner_person": by_owner,
        },
        "invalid_accounts": [],
    }


def _ok(body: Any) -> dict[str, Any]:
    return {"ok": True, "status_code": 200, "body": copy.deepcopy(body)}


class _RequestStub:
    def __init__(self, responses: dict[tuple[str, str], dict[str, Any]]):
        self._responses = {
            (method.upper(), path): copy.deepcopy(response)
            for (method, path), response in responses.items()
        }
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __call__(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        key = (method.upper(), path)
        self.calls.append((method.upper(), path, kwargs))
        return copy.deepcopy(self._responses[key])


def _patch_accounts(monkeypatch, accounts: list[dict[str, Any]]) -> None:
    payload = _account_payload(accounts)

    async def _fake_get_accounts_with_classification(strict: bool = False) -> dict[str, Any]:
        return copy.deepcopy(payload)

    monkeypatch.setattr(portfolio, "_get_accounts_with_classification", _fake_get_accounts_with_classification)


def test_snapshot_v2_reconstructs_positions_and_applies_owner_scope(monkeypatch) -> None:
    accounts = [
        _account("acct-Principal", owner_person="Principal", account_type="brokerage", balance=50.0),
        _account(
            "acct-Spouse",
            owner_person="Spouse",
            account_type="roth_ira",
            tax_wrapper="tax_exempt",
            balance=25.0,
        ),
    ]
    _patch_accounts(monkeypatch, accounts)

    request_stub = _RequestStub(
        {
            ("GET", "/api/v1/order"): _ok(
                {
                    "activities": [
                        {
                            "id": "1",
                            "date": "2026-03-01T10:00:00Z",
                            "accountId": "acct-Principal",
                            "symbol": "AAPL",
                            "type": "BUY",
                            "quantity": 2.0,
                            "valueInBaseCurrency": 200.0,
                            "unitPrice": 100.0,
                            "currency": "USD",
                            "dataSource": "YAHOO",
                        },
                        {
                            "id": "2",
                            "date": "2026-03-02T10:00:00Z",
                            "accountId": "acct-Spouse",
                            "symbol": "VTI",
                            "type": "BUY",
                            "quantity": 1.0,
                            "valueInBaseCurrency": 50.0,
                            "unitPrice": 50.0,
                            "currency": "USD",
                            "dataSource": "YAHOO",
                        },
                    ]
                }
            ),
            ("GET", "/api/v1/portfolio/holdings"): _ok(
                {
                    "holdings": [
                        {
                            "accountId": "acct-Principal",
                            "symbol": "AAPL",
                            "quantity": 2.0,
                            "marketPrice": 120.0,
                            "valueInBaseCurrency": 240.0,
                            "assetClass": "EQUITY",
                            "assetSubClass": "STOCK",
                            "currency": "USD",
                            "dataSource": "YAHOO",
                        },
                        {
                            "accountId": "acct-Spouse",
                            "symbol": "VTI",
                            "quantity": 1.0,
                            "marketPrice": 55.0,
                            "valueInBaseCurrency": 55.0,
                            "assetClass": "EQUITY",
                            "assetSubClass": "ETF",
                            "currency": "USD",
                            "dataSource": "YAHOO",
                        },
                    ]
                }
            ),
        }
    )
    monkeypatch.setattr(portfolio, "_request", request_stub)
    monkeypatch.setattr(portfolio, "_now_iso", lambda: "2026-03-08T12:00:00+00:00")

    result = _run(
        portfolio._handle_portfolio_snapshot_v2(
            "portfolio",
            "snapshot_v2",
            "1y",
            {},
            "all",
            "all",
            None,
            "Principal",
            False,
        )
    )

    assert result["ok"] is True
    data = result["data"]
    rows = data["positions"]["rows"]

    assert {row["symbol"] for row in rows} == {"AAPL", "CASH:USD"}
    assert {row["accountId"] for row in rows} == {"acct-Principal"}
    assert data["positions"]["count"] == 2
    assert data["positions"]["excluded_count"] == 2
    assert data["coverage"]["account_aware_coverage_pct"] == 1.0
    assert data["coverage"]["holdings_total_value"] == 240.0
    assert data["coverage"]["reconstructed_total_value"] == 290.0
    assert data["warnings"] == ["2 positions were excluded by account scope."]
    assert data["snapshot_id"].startswith("snap_v2_")


def test_snapshot_v2_strict_scope_fails_when_holdings_and_reconstruction_diverge(monkeypatch) -> None:
    accounts = [_account("acct-Principal", owner_person="Principal", balance=0.0)]
    _patch_accounts(monkeypatch, accounts)

    request_stub = _RequestStub(
        {
            ("GET", "/api/v1/order"): _ok(
                {
                    "activities": [
                        {
                            "id": "1",
                            "date": "2026-03-01T10:00:00Z",
                            "accountId": "acct-Principal",
                            "symbol": "AAPL",
                            "type": "BUY",
                            "quantity": 2.0,
                            "valueInBaseCurrency": 200.0,
                            "unitPrice": 100.0,
                            "currency": "USD",
                        }
                    ]
                }
            ),
            ("GET", "/api/v1/portfolio/holdings"): _ok(
                {
                    "holdings": [
                        {
                            "accountId": "acct-Principal",
                            "symbol": "AAPL",
                            "quantity": 2.0,
                            "marketPrice": 100.0,
                            "valueInBaseCurrency": 240.0,
                            "assetClass": "EQUITY",
                            "assetSubClass": "STOCK",
                            "currency": "USD",
                            "dataSource": "YAHOO",
                        }
                    ]
                }
            ),
        }
    )
    monkeypatch.setattr(portfolio, "_request", request_stub)

    result = _run(
        portfolio._handle_portfolio_snapshot_v2(
            "portfolio",
            "snapshot_v2",
            "1y",
            {},
            "all",
            "all",
            None,
            "Principal",
            True,
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "strict_scope_error"
    assert result["provenance"]["endpoint"] == "MULTI"
    assert result["error"]["details"]["minimum_required_pct"] == 0.99
    assert result["error"]["details"]["coverage_pct"] == 200.0 / 240.0


def test_snapshot_infers_missing_account_id_for_single_scoped_account(monkeypatch) -> None:
    accounts = [_account("acct-Principal", owner_person="Principal", balance=0.0)]
    _patch_accounts(monkeypatch, accounts)

    request_stub = _RequestStub(
        {
            ("GET", "/api/v1/portfolio/holdings"): _ok(
                {
                    "holdings": [
                        {
                            "symbol": "AAPL",
                            "quantity": 2.0,
                            "marketPrice": 120.0,
                            "valueInBaseCurrency": 240.0,
                            "currency": "USD",
                            "assetClass": "EQUITY",
                            "assetSubClass": "STOCK",
                        }
                    ]
                }
            ),
            ("GET", "/api/v1/portfolio/details"): _ok({"summary": {"marketValue": 240.0}}),
            ("GET", "/api/v2/portfolio/performance"): _ok({"performance": [{"date": "2026-03-08", "value": 240.0}]}),
        }
    )
    monkeypatch.setattr(portfolio, "_request", request_stub)
    monkeypatch.setattr(portfolio, "_now_iso", lambda: "2026-03-08T12:00:00+00:00")

    result = _run(
        portfolio._handle_portfolio_snapshot(
            "portfolio",
            "snapshot",
            "1y",
            {},
            "all",
            "all",
            ["brokerage"],
            "Principal",
            False,
        )
    )

    assert result["ok"] is True
    data = result["data"]

    assert data["positions"]["count"] == 1
    assert data["positions"]["excluded_holdings_count"] == 0
    assert data["positions"]["holdings"][0]["symbol"] == "AAPL"
    assert data["positions"]["classification_warnings"] == [
        "1 holdings missing account identifier were included by single-account scope inference."
    ]
    assert data["portfolio_details"] == {"summary": {"marketValue": 240.0}}
    assert data["portfolio_performance"] == {"performance": [{"date": "2026-03-08", "value": 240.0}]}
