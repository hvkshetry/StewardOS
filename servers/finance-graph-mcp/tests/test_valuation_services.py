from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import valuation_services as valuation_services_module
from test_support.db import FakeRecord


class TestRecordValuationObservation:
    async def test_auto_promotion_keeps_newer_current_mark(self, pool, get_pool, monkeypatch):
        inserted_observation = FakeRecord(
            id=11,
            asset_id=7,
            method_code="manual_mark",
            source="manual",
            value_amount=100.0,
            value_currency="USD",
            valuation_date=date(2026, 2, 1),
            confidence_score=0.4,
            notes=None,
        )
        monkeypatch.setattr(
            valuation_services_module,
            "_insert_valuation_observation",
            AsyncMock(return_value=inserted_observation),
        )
        pool._conn.fetchval.return_value = 1
        pool._conn.fetchrow.side_effect = [
            FakeRecord(
                current_valuation_observation_id=9,
                observation_id=9,
                valuation_date=date(2026, 3, 1),
                confidence_score=0.9,
            ),
        ]

        result = await valuation_services_module.record_valuation_observation(
            get_pool,
            asset_id=7,
            method_code="manual_mark",
            value_amount=100.0,
            valuation_date="2026-02-01",
        )

        assert result["promoted_to_current"] is False
        assert result["current_valuation_observation_id"] == 9
        pool._conn.execute.assert_not_awaited()

    async def test_force_promotion_updates_canonical_pointer(self, pool, get_pool, monkeypatch):
        inserted_observation = FakeRecord(
            id=12,
            asset_id=7,
            method_code="manual_mark",
            source="manual",
            value_amount=250.0,
            value_currency="USD",
            valuation_date=date(2026, 1, 1),
            confidence_score=0.1,
            notes=None,
        )
        monkeypatch.setattr(
            valuation_services_module,
            "_insert_valuation_observation",
            AsyncMock(return_value=inserted_observation),
        )
        pool._conn.fetchval.return_value = 1
        pool._conn.fetchrow.side_effect = [
            FakeRecord(
                current_valuation_observation_id=9,
                observation_id=9,
                valuation_date=date(2026, 3, 1),
                confidence_score=0.9,
            ),
        ]

        result = await valuation_services_module.record_valuation_observation(
            get_pool,
            asset_id=7,
            method_code="manual_mark",
            value_amount=250.0,
            valuation_date="2026-01-01",
            promote_to_current="force",
        )

        assert result["promoted_to_current"] is True
        assert result["current_valuation_observation_id"] == 12
        assert pool._conn.execute.await_count == 1


class TestStatementLineItems:
    async def test_no_overwrite_insert_count_uses_actual_insert_results(self, get_pool, pool):
        pool._conn.execute.side_effect = ["INSERT 0 1", "INSERT 0 0", "INSERT 0 1"]

        result = await valuation_services_module.upsert_statement_line_items(
            get_pool,
            reporting_period_id=5,
            statement_type="balance_sheet",
            line_items={
                "cash": 10.0,
                "receivables": 20.0,
                "inventory": 30.0,
            },
            overwrite=False,
        )

        assert result["rows_processed"] == 3
        assert result["rows_inserted_no_overwrite_mode"] == 2
        assert result["rows_updated_or_upserted"] == 0


class TestXbrlUpsert:
    async def test_replaces_existing_report_rows_before_inserting_facts(self, get_pool, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(id=5),
            FakeRecord(id=11),
        ]

        result = await valuation_services_module.upsert_xbrl_facts_core(
            get_pool,
            accession_number="0000000000-26-000001",
            facts=[
                {
                    "concept_qname": "us-gaap:Revenues",
                    "value": "1000",
                    "fact_value_numeric": 1000,
                }
            ],
        )

        assert result["xbrl_report_id"] == 5
        assert result["facts_ingested"] == 1
        executed_sql = [call.args[0] for call in pool._conn.execute.await_args_list]
        assert "DELETE FROM xbrl_facts WHERE xbrl_report_id = $1" in executed_sql[0]
        assert "DELETE FROM xbrl_contexts WHERE xbrl_report_id = $1" in executed_sql[1]
        assert "DELETE FROM xbrl_units WHERE xbrl_report_id = $1" in executed_sql[2]
        assert "INSERT INTO xbrl_facts" in executed_sql[3]
