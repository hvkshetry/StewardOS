from __future__ import annotations

from datetime import date

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def liabilities_mcp(fake_mcp, get_pool):
    from liabilities import register_liabilities_tools

    register_liabilities_tools(fake_mcp, get_pool)
    return fake_mcp


class TestRecordLiabilityPayment:
    async def test_monthly_payment_advances_next_due_date(self, liabilities_mcp, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(
                id=10,
                outstanding_principal=1000.0,
                status="current",
                next_payment_date=date(2026, 3, 15),
                payment_frequency="monthly",
            ),
            None,
            FakeRecord(
                id=77,
                liability_id=10,
                payment_date=date(2026, 3, 15),
                amount_total=200.0,
                amount_principal=150.0,
                amount_interest=50.0,
                amount_escrow=None,
                idempotency_key="monthly-key",
            ),
        ]

        result = await liabilities_mcp.call(
            "record_liability_payment",
            liability_id=10,
            payment_date="2026-03-15",
            amount_total=200.0,
            amount_interest=50.0,
        )

        assert result["status"] == "ok"
        assert result["errors"] == []
        assert result["data"]["updated_outstanding_principal"] == 850.0
        assert result["data"]["next_payment_date"] == "2026-04-15"

    async def test_rejects_invalid_payment_split(self, liabilities_mcp, pool):
        pool._conn.fetchrow.return_value = FakeRecord(
            id=10,
            outstanding_principal=1000.0,
            status="current",
            next_payment_date=date(2026, 3, 15),
            payment_frequency="monthly",
        )

        result = await liabilities_mcp.call(
            "record_liability_payment",
            liability_id=10,
            payment_date="2026-03-15",
            amount_total=200.0,
            amount_interest=150.0,
            amount_escrow=75.0,
        )

        assert result["status"] == "error"
        assert result["errors"][0]["message"] == "Payment split exceeds amount_total"

    async def test_quarterly_payment_advances_from_contractual_schedule(self, liabilities_mcp, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(
                id=10,
                outstanding_principal=1000.0,
                status="current",
                next_payment_date=date(2026, 1, 15),
                payment_frequency="quarterly",
            ),
            None,
            FakeRecord(
                id=88,
                liability_id=10,
                payment_date=date(2026, 4, 20),
                amount_total=100.0,
                amount_principal=100.0,
                amount_interest=0.0,
                amount_escrow=0.0,
                idempotency_key="abc123",
            ),
        ]

        result = await liabilities_mcp.call(
            "record_liability_payment",
            liability_id=10,
            payment_date="2026-04-20",
            amount_total=100.0,
        )

        assert result["status"] == "ok"
        assert result["data"]["updated_outstanding_principal"] == 900.0
        assert result["data"]["next_payment_date"] == "2026-07-15"
        assert result["data"]["idempotency_reused"] is False

    async def test_reuses_existing_idempotent_payment(self, liabilities_mcp, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(
                id=10,
                outstanding_principal=1000.0,
                status="current",
                next_payment_date=date(2026, 3, 15),
                payment_frequency="monthly",
            ),
            FakeRecord(
                id=77,
                liability_id=10,
                payment_date=date(2026, 3, 15),
                amount_total=200.0,
                amount_principal=150.0,
                amount_interest=50.0,
                amount_escrow=0.0,
                idempotency_key="dupe-key",
            ),
            FakeRecord(
                outstanding_principal=850.0,
                status="current",
                next_payment_date=date(2026, 4, 15),
            ),
        ]

        result = await liabilities_mcp.call(
            "record_liability_payment",
            liability_id=10,
            payment_date="2026-03-15",
            amount_total=200.0,
            amount_interest=50.0,
            idempotency_key="dupe-key",
        )

        assert result["status"] == "ok"
        assert result["data"]["idempotency_reused"] is True
        assert result["data"]["payment"]["id"] == 77
        assert result["data"]["updated_outstanding_principal"] == 850.0
