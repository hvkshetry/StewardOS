"""Real-Postgres integration tests for estate-planning asset invariants."""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from assets import register_assets_tools
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
    async with provision_test_schema(SCHEMA_SQL, schema_prefix="estate_it") as pool:
        yield pool


async def _seed_person_and_entity(conn) -> tuple[int, int, int]:
    jurisdiction_id = await conn.fetchval(
        "SELECT id FROM jurisdictions WHERE code = $1",
        US_JURISDICTION_CODE,
    )
    entity_type_id = await conn.fetchval("SELECT id FROM entity_types ORDER BY id LIMIT 1")
    person_id = await conn.fetchval("INSERT INTO people (legal_name) VALUES ('Pat Owner') RETURNING id")
    entity_id = await conn.fetchval(
        """INSERT INTO entities (name, entity_type_id, jurisdiction_id)
           VALUES ('Pat Trust', $1, $2)
           RETURNING id""",
        entity_type_id,
        jurisdiction_id,
    )
    return int(person_id), int(entity_id), int(jurisdiction_id)


@pytest.mark.asyncio
async def test_asset_update_replaces_owner_and_nulls_other_owner(pg_pool):
    async with pg_pool.acquire() as conn:
        person_id, entity_id, _ = await _seed_person_and_entity(conn)

    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_assets_tools(mcp, get_pool)

    created = await mcp.call(
        "upsert_asset",
        name="Family Home",
        asset_class_code="real_estate",
        asset_subclass_code="real_estate_residential",
        jurisdiction_code=US_JURISDICTION_CODE,
        valuation_currency="USD",
        owner_person_id=person_id,
        current_valuation_amount=750000,
        property_type="residential",
    )
    asset_id = int(created["data"]["id"])

    await mcp.call(
        "upsert_asset",
        asset_id=asset_id,
        name="Family Home",
        asset_class_code="real_estate",
        asset_subclass_code="real_estate_residential",
        jurisdiction_code=US_JURISDICTION_CODE,
        valuation_currency="USD",
        owner_entity_id=entity_id,
        current_valuation_amount=760000,
        property_type="residential",
    )

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT owner_entity_id, owner_person_id FROM assets WHERE id = $1",
            asset_id,
        )
    assert row["owner_entity_id"] == entity_id
    assert row["owner_person_id"] is None


@pytest.mark.asyncio
async def test_real_estate_validation_happens_before_any_write(pg_pool):
    async with pg_pool.acquire() as conn:
        person_id, _, _ = await _seed_person_and_entity(conn)
        await conn.execute(
            """INSERT INTO jurisdictions (code, name, country, parent_code, tax_id_label)
               VALUES ('-', 'Broken Jurisdiction', 'ZZ', NULL, 'N/A')
               ON CONFLICT (code) DO NOTHING"""
        )

    async def get_pool():
        return pg_pool

    mcp = FakeMCP()
    register_assets_tools(mcp, get_pool)

    result = await mcp.call(
        "upsert_asset",
        name="Broken Deed",
        asset_class_code="real_estate",
        asset_subclass_code="real_estate_residential",
        jurisdiction_code="-",
        valuation_currency="USD",
        owner_person_id=person_id,
        current_valuation_amount=100000,
        property_type="residential",
    )
    assert result["status"] == "error"
    assert result["errors"][0]["message"] == "country_code could not be derived for real-estate asset"

    async with pg_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM assets WHERE name = 'Broken Deed'")
    assert count == 0
