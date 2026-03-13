"""Real-Postgres integration tests for finance-graph correctness-critical paths."""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import liability_tool_ops as liability_tool_ops_module
from assets import register_assets_tools
from cross_cutting import register_cross_cutting_tools
from liabilities import register_liabilities_tools
from valuations import register_valuations_tools

from test_support.mcp import FakeMCP
from test_support.postgres import STEWARDOS_TEST_DATABASE_URL, provision_test_schema

SCHEMA_SQL = Path(server_root, "schema.sql").read_text(encoding="utf-8")
US_JURISDICTION_CODE = "US-CA"

pytestmark = pytest.mark.skipif(
    not STEWARDOS_TEST_DATABASE_URL,
    reason="STEWARDOS_TEST_DATABASE_URL is not configured",
)


@pytest.fixture
async def pg_pool():
    async with provision_test_schema(SCHEMA_SQL, schema_prefix="finance_it") as pool:
        yield pool


async def _seed_person_and_entity(conn) -> tuple[int, int, int]:
    jurisdiction_id = await conn.fetchval(
        "SELECT id FROM jurisdictions WHERE code = $1",
        US_JURISDICTION_CODE,
    )
    entity_type_id = await conn.fetchval("SELECT id FROM entity_types ORDER BY id LIMIT 1")
    person_id = await conn.fetchval(
        "INSERT INTO people (legal_name) VALUES ('Alex Principal') RETURNING id"
    )
    entity_id = await conn.fetchval(
        """INSERT INTO entities (name, entity_type_id, jurisdiction_id)
           VALUES ('Alex Family LLC', $1, $2)
           RETURNING id""",
        entity_type_id,
        jurisdiction_id,
    )
    return int(person_id), int(entity_id), int(jurisdiction_id)


@pytest.mark.asyncio
async def test_person_net_worth_rollup_uses_lookthrough_assets_and_liabilities(pg_pool):
    async with pg_pool.acquire() as conn:
        person_id, entity_id, jurisdiction_id = await _seed_person_and_entity(conn)

        await conn.execute(
            """INSERT INTO ownership_paths (owner_person_id, owned_entity_id, percentage)
               VALUES ($1, $2, 50.0)""",
            person_id,
            entity_id,
        )
        direct_asset_id = await conn.fetchval(
            """INSERT INTO assets (
                   name, asset_type, jurisdiction_id, owner_person_id
               ) VALUES ('Direct Brokerage', 'securities', $1, $2)
               RETURNING id""",
            jurisdiction_id,
            person_id,
        )
        lookthrough_asset_id = await conn.fetchval(
            """INSERT INTO assets (
                   name, asset_type, jurisdiction_id, owner_entity_id
               ) VALUES ('LLC Property', 'real_estate', $1, $2)
               RETURNING id""",
            jurisdiction_id,
            entity_id,
        )
        direct_observation_id = await conn.fetchval(
            """INSERT INTO valuation_observations (
                   asset_id, method_code, source, value_amount, value_currency, valuation_date, confidence_score
               ) VALUES ($1, 'manual_mark', 'seed', 100000, 'USD', DATE '2026-03-01', 0.9)
               RETURNING id""",
            direct_asset_id,
        )
        await conn.execute(
            "UPDATE assets SET current_valuation_observation_id = $1 WHERE id = $2",
            direct_observation_id,
            direct_asset_id,
        )
        lookthrough_observation_id = await conn.fetchval(
            """INSERT INTO valuation_observations (
                   asset_id, method_code, source, value_amount, value_currency, valuation_date, confidence_score
               ) VALUES ($1, 'manual_mark', 'seed', 200000, 'USD', DATE '2026-03-01', 0.9)
               RETURNING id""",
            lookthrough_asset_id,
        )
        await conn.execute(
            "UPDATE assets SET current_valuation_observation_id = $1 WHERE id = $2",
            lookthrough_observation_id,
            lookthrough_asset_id,
        )

        person_party_uuid = str(uuid.uuid4())
        entity_party_uuid = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO party_refs (party_uuid, party_type, legal_name, metadata)
               VALUES ($1::uuid, 'person', 'Alex Principal', $2::jsonb)""",
            person_party_uuid,
            json.dumps({"legacy_person_id": str(person_id)}),
        )
        await conn.execute(
            """INSERT INTO party_refs (party_uuid, party_type, legal_name, metadata)
               VALUES ($1::uuid, 'entity', 'Alex Family LLC', $2::jsonb)""",
            entity_party_uuid,
            json.dumps({"legacy_entity_id": str(entity_id)}),
        )
        await conn.execute(
            """INSERT INTO liabilities (
                   name, liability_type_code, jurisdiction_id, primary_borrower_uuid,
                   outstanding_principal, currency
               ) VALUES ('Direct Mortgage', 'mortgage_fixed', $1, $2::uuid, 30000, 'USD')""",
            jurisdiction_id,
            person_party_uuid,
        )
        await conn.execute(
            """INSERT INTO liabilities (
                   name, liability_type_code, jurisdiction_id, primary_borrower_uuid,
                   outstanding_principal, currency
               ) VALUES ('LLC Mortgage', 'mortgage_fixed', $1, $2::uuid, 80000, 'USD')""",
            jurisdiction_id,
            entity_party_uuid,
        )

    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_cross_cutting_tools(mcp, get_pool)
    result = await mcp.call("get_net_worth", person_id=person_id)

    assert result["data"] == [
        {
            "jurisdiction": US_JURISDICTION_CODE,
            "currency": "USD",
            "asset_value": 200000.0,
            "liability_value": 70000.0,
            "net_worth_after_liabilities": 130000.0,
            "direct_asset_value": 100000.0,
            "lookthrough_asset_value": 100000.0,
            "direct_liability_value": 30000.0,
            "lookthrough_liability_value": 40000.0,
            "ownership_basis": "legal_title",
        }
    ]


@pytest.mark.asyncio
async def test_link_document_validates_and_upserts_on_paperless_id(pg_pool):
    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_cross_cutting_tools(mcp, get_pool)

    invalid = (
        await mcp.call(
            "link_document",
            title="Draft",
            doc_type="tax_return",
            paperless_doc_id=101,
            jurisdiction_code="ZZ-UNKNOWN",
        )
    )
    assert invalid["status"] == "error"
    assert invalid["errors"][0]["message"] == "Unknown jurisdiction_code: ZZ-UNKNOWN"

    created = (
        await mcp.call(
            "link_document",
            title="2025 Return",
            doc_type="tax_return",
            paperless_doc_id=101,
            jurisdiction_code=US_JURISDICTION_CODE,
            effective_date="2026-01-15",
            notes="initial",
        )
    )
    updated = (
        await mcp.call(
            "link_document",
            title="2025 Return Revised",
            doc_type="tax_return",
            paperless_doc_id=101,
            jurisdiction_code=US_JURISDICTION_CODE,
            notes="reissued",
        )
    )

    assert created["status"] == "ok"
    assert updated["data"]["title"] == "2025 Return Revised"
    async with pg_pool.acquire() as conn:
        doc_count = await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE paperless_doc_id = 101"
        )
        metadata = await conn.fetchrow(
            "SELECT source_snapshot_title, notes FROM document_metadata WHERE paperless_doc_id = 101"
        )
    assert doc_count == 1
    assert metadata["source_snapshot_title"] == "2025 Return Revised"
    assert metadata["notes"] == "reissued"


@pytest.mark.asyncio
async def test_amortization_does_not_capitalize_escrow_shortfall(pg_pool):
    async with pg_pool.acquire() as conn:
        jurisdiction_id = await conn.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            US_JURISDICTION_CODE,
        )
        party_uuid = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO party_refs (party_uuid, party_type, legal_name)
               VALUES ($1::uuid, 'person', 'Alex Principal')""",
            party_uuid,
        )
        liability_id = await conn.fetchval(
            """INSERT INTO liabilities (
                   name, liability_type_code, jurisdiction_id, primary_borrower_uuid,
                   outstanding_principal, interest_rate, currency
               ) VALUES ('Escrow Test', 'mortgage_fixed', $1, $2::uuid, 100000, 0.12, 'USD')
               RETURNING id""",
            jurisdiction_id,
            party_uuid,
        )

    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_liabilities_tools(mcp, get_pool)
    await mcp.call(
        "generate_liability_amortization",
        liability_id=int(liability_id),
        months=1,
        payment_total_override=100.0,
        escrow_payment_override=200.0,
        annual_rate_override=0.12,
        start_date="2026-02-01",
    )

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT opening_balance, closing_balance, metadata
               FROM liability_cashflow_schedule
               WHERE liability_id = $1""",
            liability_id,
        )
    assert round(float(row["opening_balance"]), 2) == 100000.00
    assert round(float(row["closing_balance"]), 2) == 101000.00
    metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
    assert metadata["interest_shortfall"] == pytest.approx(1000.0)
    assert metadata["escrow_shortfall"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_schedule_generation_rolls_back_on_mid_insert_failure(pg_pool, monkeypatch):
    async with pg_pool.acquire() as conn:
        jurisdiction_id = await conn.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            US_JURISDICTION_CODE,
        )
        party_uuid = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO party_refs (party_uuid, party_type, legal_name)
               VALUES ($1::uuid, 'person', 'Alex Principal')""",
            party_uuid,
        )
        liability_id = await conn.fetchval(
            """INSERT INTO liabilities (
                   name, liability_type_code, jurisdiction_id, primary_borrower_uuid,
                   outstanding_principal, interest_rate, currency
               ) VALUES ('Rollback Test', 'mortgage_fixed', $1, $2::uuid, 100000, 0.06, 'USD')
               RETURNING id""",
            jurisdiction_id,
            party_uuid,
        )
        await conn.execute(
            """INSERT INTO liability_cashflow_schedule (
                   liability_id, due_date, opening_balance, payment_total, payment_principal,
                   payment_interest, payment_escrow, closing_balance, scenario_tag, source
               ) VALUES ($1, DATE '2026-01-01', 100000, 500, 100, 400, 0, 99900, 'base', 'seed')""",
            liability_id,
        )

    duplicate_rows = [
        {
            "due_date": date(2026, 1, 1),
            "opening_balance": 100000.0,
            "payment_total": 500.0,
            "payment_principal": 100.0,
            "payment_interest": 400.0,
            "payment_escrow": 0.0,
            "closing_balance": 99900.0,
            "interest_shortfall": 0.0,
            "escrow_shortfall": 0.0,
        },
        {
            "due_date": date(2026, 1, 1),
            "opening_balance": 99900.0,
            "payment_total": 500.0,
            "payment_principal": 100.0,
            "payment_interest": 400.0,
            "payment_escrow": 0.0,
            "closing_balance": 99800.0,
            "interest_shortfall": 0.0,
            "escrow_shortfall": 0.0,
        },
    ]
    monkeypatch.setattr(
        liability_tool_ops_module,
        "_build_amortization_payload",
        lambda **_: {
            "schedule": duplicate_rows,
            "annual_rate": 0.06,
            "term_months": len(duplicate_rows),
            "payment_total": 500.0,
            "total_payments": 1000.0,
            "total_interest": 800.0,
            "ending_balance": 99800.0,
        },
    )

    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_liabilities_tools(mcp, get_pool)
    with pytest.raises(Exception):
        await mcp.call("generate_liability_amortization", liability_id=int(liability_id))

    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT due_date, source
               FROM liability_cashflow_schedule
               WHERE liability_id = $1
               ORDER BY due_date""",
            liability_id,
        )
    assert len(rows) == 1
    assert rows[0]["source"] == "seed"


@pytest.mark.asyncio
async def test_asset_reads_and_rollups_prefer_canonical_current_valuation_pointer(pg_pool):
    async with pg_pool.acquire() as conn:
        person_id, _, jurisdiction_id = await _seed_person_and_entity(conn)
        asset_id = await conn.fetchval(
            """INSERT INTO assets (
                   name, asset_type, jurisdiction_id, owner_person_id
               ) VALUES ('Canonical Pointer Asset', 'securities', $1, $2)
               RETURNING id""",
            jurisdiction_id,
            person_id,
        )
        observation_id = await conn.fetchval(
            """INSERT INTO valuation_observations (
                   asset_id, method_code, source, value_amount, value_currency, valuation_date, confidence_score
               ) VALUES ($1, 'manual_mark', 'seed', 250, 'USD', DATE '2026-03-01', 0.8)
               RETURNING id""",
            asset_id,
        )
        await conn.execute(
            """UPDATE assets
               SET current_valuation_observation_id = $1
               WHERE id = $2""",
            observation_id,
            asset_id,
        )

    async def get_pool():
        return pg_pool

    assets_mcp = FakeMCP()
    register_assets_tools(assets_mcp, get_pool)
    assets_result = await assets_mcp.call("list_assets")

    assert assets_result["status"] == "ok"
    assert float(assets_result["data"][0]["current_valuation_amount"]) == 250.0
    assert assets_result["data"][0]["current_valuation_observation_id"] == observation_id

    cross_cutting_mcp = FakeMCP()
    register_cross_cutting_tools(cross_cutting_mcp, get_pool)
    net_worth_result = await cross_cutting_mcp.call("get_net_worth", person_id=person_id)

    assert net_worth_result["data"] == [
        {
            "jurisdiction": US_JURISDICTION_CODE,
            "currency": "USD",
            "asset_value": 250.0,
            "liability_value": 0.0,
            "net_worth_after_liabilities": 250.0,
            "direct_asset_value": 250.0,
            "lookthrough_asset_value": 0.0,
            "direct_liability_value": 0.0,
            "lookthrough_liability_value": 0.0,
            "ownership_basis": "legal_title",
        }
    ]


@pytest.mark.asyncio
async def test_xbrl_reingest_replaces_facts_instead_of_duplicating(pg_pool):
    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_valuations_tools(mcp, get_pool)
    facts_payload = [
        {
            "concept_qname": "us-gaap:Revenues",
            "value": "1000",
            "fact_value_numeric": 1000,
            "context_ref": "ctx-2025",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "unit_ref": "usd",
            "measure": "USD",
        }
    ]

    created = await mcp.call(
        "upsert_xbrl_facts_core",
        accession_number="0000000000-26-000001",
        facts=facts_payload,
        cik="0000123456",
        ticker="TEST",
    )
    replaced = await mcp.call(
        "upsert_xbrl_facts_core",
        accession_number="0000000000-26-000001",
        facts=facts_payload,
        cik="0000123456",
        ticker="TEST",
    )

    assert created["status"] == "ok"
    assert replaced["status"] == "ok"
    async with pg_pool.acquire() as conn:
        report_count = await conn.fetchval(
            "SELECT COUNT(*) FROM xbrl_reports WHERE accession_number = $1",
            "0000000000-26-000001",
        )
        fact_count = await conn.fetchval("SELECT COUNT(*) FROM xbrl_facts")
        context_count = await conn.fetchval("SELECT COUNT(*) FROM xbrl_contexts")
        unit_count = await conn.fetchval("SELECT COUNT(*) FROM xbrl_units")

    assert report_count == 1
    assert fact_count == 1
    assert context_count == 1
    assert unit_count == 1
