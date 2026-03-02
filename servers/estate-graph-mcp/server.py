"""Estate Planning Knowledge Graph MCP Server.

Provides tools for managing people, entities (trusts, LLCs, corps),
assets, ownership paths, documents, and critical dates across
US + India jurisdictions.
"""

import os
import json
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal

import asyncpg
import httpx
from jsonschema import ValidationError, validate
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://estate:changeme@localhost:5434/postgres"
)
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "").strip()
RENTCAST_BASE_URL = os.environ.get("RENTCAST_BASE_URL", "https://api.rentcast.io/v1").rstrip("/")
OCF_DEFAULT_VERSION = "1.2.0"
ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

ASSET_TYPE_BY_CLASS = {
    "real_estate": "real_estate",
    "private_equity": "securities",
}

REAL_ESTATE_SUBCLASSES = {
    "real_estate_residential",
    "real_estate_land",
    "real_estate_commercial",
    "real_estate_agricultural",
}

OCF_MINIMAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "ocf_version": {"type": "string"},
    },
    "required": ["ocf_version"],
}

# ─── Database pool ────────────────────────────────────────────────

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            server_settings={"search_path": "estate,public"},
        )
    return _pool


def _row_to_dict(row: asyncpg.Record) -> dict:
    """Convert asyncpg Record to JSON-safe dict."""
    d = {}
    for k, v in dict(row).items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, str):
            trimmed = v.strip()
            if (trimmed.startswith("{") and trimmed.endswith("}")) or (
                trimmed.startswith("[") and trimmed.endswith("]")
            ):
                try:
                    d[k] = json.loads(trimmed)
                    continue
                except json.JSONDecodeError:
                    pass
            d[k] = v
        else:
            d[k] = v
    return d


def _rows_to_list(rows: list[asyncpg.Record]) -> list[dict]:
    return [_row_to_dict(r) for r in rows]


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_numeric_value(payload: dict) -> float | None:
    """Best-effort extraction from heterogeneous valuation payloads."""
    if not isinstance(payload, dict):
        return None

    scalar_keys = (
        "price",
        "value",
        "avm",
        "estimate",
        "estimatedValue",
        "estimated_value",
    )
    for key in scalar_keys:
        maybe = _float_or_none(payload.get(key))
        if maybe is not None:
            return maybe

    nested_keys = ("data", "valuation", "result", "results")
    for key in nested_keys:
        nested = payload.get(key)
        if isinstance(nested, dict):
            maybe = _extract_numeric_value(nested)
            if maybe is not None:
                return maybe
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    maybe = _extract_numeric_value(item)
                    if maybe is not None:
                        return maybe
    return None


def _coerce_json_input(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _statement_table_name(statement_type: str) -> str | None:
    normalized = (statement_type or "").strip().lower()
    mapping = {
        "income_statement": "income_statement_facts",
        "pl": "income_statement_facts",
        "p&l": "income_statement_facts",
        "cash_flow_statement": "cash_flow_statement_facts",
        "cash_flow": "cash_flow_statement_facts",
        "cfs": "cash_flow_statement_facts",
        "balance_sheet": "balance_sheet_facts",
        "bs": "balance_sheet_facts",
    }
    return mapping.get(normalized)


def _normalize_currency_code(code: str | None) -> str | None:
    if not isinstance(code, str):
        return None
    normalized = code.strip().upper()
    if not ISO_CURRENCY_RE.fullmatch(normalized):
        return None
    return normalized


def _canonical_asset_type(asset_class_code: str, asset_subclass_code: str) -> str:
    class_code = (asset_class_code or "").strip().lower()
    subclass_code = (asset_subclass_code or "").strip().lower()
    if class_code == "real_estate" or subclass_code in REAL_ESTATE_SUBCLASSES:
        return "real_estate"
    return ASSET_TYPE_BY_CLASS.get(class_code, "other")


async def _insert_valuation_observation(
    *,
    pool: asyncpg.Pool,
    asset_id: int,
    method_code: str,
    source: str,
    value_amount: float,
    value_currency: str,
    valuation_date: date,
    confidence_score: float | None = None,
    notes: str | None = None,
    evidence: dict | None = None,
) -> asyncpg.Record:
    normalized_method = (method_code or "").strip().lower()
    if not normalized_method:
        raise ValueError("method_code must be non-empty")

    method_exists = await pool.fetchval(
        "SELECT 1 FROM valuation_methods WHERE code = $1",
        normalized_method,
    )
    if not method_exists:
        rows = await pool.fetch("SELECT code FROM valuation_methods ORDER BY code")
        valid_codes = [str(row["code"]) for row in rows]
        raise ValueError(
            f"Unknown method_code '{method_code}'. Valid values: {', '.join(valid_codes)}"
        )

    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        raise ValueError("value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)")

    return await pool.fetchrow(
        """INSERT INTO valuation_observations (
               asset_id, method_code, source, value_amount, value_currency,
               valuation_date, confidence_score, notes, evidence
           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
           RETURNING id, asset_id, method_code, source, value_amount,
                     value_currency, valuation_date, confidence_score, notes""",
        asset_id,
        normalized_method,
        source,
        value_amount,
        normalized_currency,
        valuation_date,
        confidence_score,
        notes,
        json.dumps(evidence or {}),
    )


# ─── MCP Server ──────────────────────────────────────────────────

mcp = FastMCP(
    "estate-graph",
    instructions=(
        "Estate planning knowledge graph. Query and manage people, entities "
        "(trusts, LLCs, corps, HUFs), assets, ownership paths, documents, "
        "and critical dates across US and India jurisdictions."
    ),
)


# ─── People Tools ────────────────────────────────────────────────


@mcp.tool()
async def list_people() -> str:
    """List all family members in the estate graph."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, legal_name, preferred_name, citizenship, residency_status "
        "FROM people ORDER BY legal_name"
    )
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def get_person(person_id: int) -> str:
    """Get full details for a person including their entity ownership and documents.

    Args:
        person_id: The person's database ID.
    """
    pool = await get_pool()
    person = await pool.fetchrow("SELECT * FROM people WHERE id = $1", person_id)
    if not person:
        return json.dumps({"error": f"Person {person_id} not found"})

    ownership = await pool.fetch(
        "SELECT * FROM v_ownership_summary WHERE owner_type = 'person' "
        "AND owner_name = $1",
        person["legal_name"],
    )
    docs = await pool.fetch(
        "SELECT id, title, doc_type, expiry_date FROM documents WHERE person_id = $1",
        person_id,
    )
    result = _row_to_dict(person)
    result["ownership"] = _rows_to_list(ownership)
    result["documents"] = _rows_to_list(docs)
    return json.dumps(result, indent=2)


@mcp.tool()
async def upsert_person(
    legal_name: str,
    preferred_name: str | None = None,
    date_of_birth: str | None = None,
    citizenship: list[str] | None = None,
    residency_status: str | None = None,
    tax_id: str | None = None,
    tax_id_type: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    person_id: int | None = None,
) -> str:
    """Create or update a family member. Pass person_id to update existing.

    Args:
        legal_name: Full legal name.
        preferred_name: Preferred/nickname.
        date_of_birth: Date of birth (YYYY-MM-DD).
        citizenship: List of country codes (e.g. ['US', 'IN']).
        residency_status: citizen, resident, nri, oci.
        tax_id: SSN, PAN, etc.
        tax_id_type: SSN, PAN.
        email: Email address.
        phone: Phone number.
        notes: Free-text notes.
        person_id: If provided, updates existing person.
    """
    pool = await get_pool()
    dob = date.fromisoformat(date_of_birth) if date_of_birth else None

    if person_id:
        row = await pool.fetchrow(
            """UPDATE people SET legal_name=$1, preferred_name=$2, date_of_birth=$3,
               citizenship=$4, residency_status=$5, tax_id=$6, tax_id_type=$7,
               email=$8, phone=$9, notes=$10, updated_at=now()
               WHERE id=$11 RETURNING id, legal_name""",
            legal_name, preferred_name, dob, citizenship, residency_status,
            tax_id, tax_id_type, email, phone, notes, person_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO people (legal_name, preferred_name, date_of_birth,
               citizenship, residency_status, tax_id, tax_id_type, email, phone, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id, legal_name""",
            legal_name, preferred_name, dob, citizenship, residency_status,
            tax_id, tax_id_type, email, phone, notes,
        )
    return json.dumps(_row_to_dict(row))


# ─── Entity Tools ────────────────────────────────────────────────


@mcp.tool()
async def list_entities(
    entity_type: str | None = None,
    jurisdiction: str | None = None,
    status: str | None = None,
) -> str:
    """List entities (trusts, LLCs, corps, HUFs) with optional filters.

    Args:
        entity_type: Filter by entity_type code (e.g. LLC, REVOCABLE_TRUST).
        jurisdiction: Filter by jurisdiction code (e.g. US-DE, IN-KA).
        status: Filter by status (active, dissolved, pending).
    """
    pool = await get_pool()
    query = """
        SELECT e.id, e.name, et.code AS entity_type, et.name AS entity_type_name,
               j.code AS jurisdiction, e.status, e.formation_date, e.tax_id
        FROM entities e
        JOIN entity_types et ON e.entity_type_id = et.id
        JOIN jurisdictions j ON e.jurisdiction_id = j.id
        WHERE 1=1
    """
    params = []
    idx = 1
    if entity_type:
        query += f" AND et.code = ${idx}"
        params.append(entity_type)
        idx += 1
    if jurisdiction:
        query += f" AND j.code = ${idx}"
        params.append(jurisdiction)
        idx += 1
    if status:
        query += f" AND e.status = ${idx}"
        params.append(status)
        idx += 1
    query += " ORDER BY e.name"
    rows = await pool.fetch(query, *params)
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def get_entity(entity_id: int) -> str:
    """Get full entity details with ownership, documents, and critical dates.

    Args:
        entity_id: The entity's database ID.
    """
    pool = await get_pool()
    entity = await pool.fetchrow(
        """SELECT e.*, et.code AS entity_type_code, et.name AS entity_type_name,
                  j.code AS jurisdiction_code, j.name AS jurisdiction_name
           FROM entities e
           JOIN entity_types et ON e.entity_type_id = et.id
           JOIN jurisdictions j ON e.jurisdiction_id = j.id
           WHERE e.id = $1""",
        entity_id,
    )
    if not entity:
        return json.dumps({"error": f"Entity {entity_id} not found"})

    ownership = await pool.fetch(
        "SELECT * FROM v_ownership_summary WHERE owned_name = $1",
        entity["name"],
    )
    docs = await pool.fetch(
        "SELECT id, title, doc_type, expiry_date FROM documents WHERE entity_id = $1",
        entity_id,
    )
    dates = await pool.fetch(
        "SELECT * FROM critical_dates WHERE entity_id = $1 AND NOT completed ORDER BY due_date",
        entity_id,
    )
    result = _row_to_dict(entity)
    result["ownership"] = _rows_to_list(ownership)
    result["documents"] = _rows_to_list(docs)
    result["critical_dates"] = _rows_to_list(dates)
    return json.dumps(result, indent=2)


@mcp.tool()
async def upsert_entity(
    name: str,
    entity_type_code: str,
    jurisdiction_code: str,
    status: str = "active",
    formation_date: str | None = None,
    tax_id: str | None = None,
    tax_id_type: str | None = None,
    grantor_id: int | None = None,
    trustee_id: int | None = None,
    karta_id: int | None = None,
    registered_agent: str | None = None,
    notes: str | None = None,
    entity_id: int | None = None,
) -> str:
    """Create or update an entity (trust, LLC, corp, HUF). Pass entity_id to update.

    Args:
        name: Entity name.
        entity_type_code: Entity type code (e.g. LLC, REVOCABLE_TRUST, HUF).
        jurisdiction_code: Jurisdiction code (e.g. US-DE, IN-KA).
        status: active, dissolved, or pending.
        formation_date: Formation date (YYYY-MM-DD).
        tax_id: EIN, PAN, TAN.
        tax_id_type: EIN, PAN, TAN.
        grantor_id: Person ID of grantor (trusts).
        trustee_id: Person ID of trustee (trusts).
        karta_id: Person ID of Karta (HUF).
        registered_agent: Registered agent name.
        notes: Free-text notes.
        entity_id: If provided, updates existing entity.
    """
    pool = await get_pool()
    fd = date.fromisoformat(formation_date) if formation_date else None

    et = await pool.fetchval("SELECT id FROM entity_types WHERE code = $1", entity_type_code)
    if not et:
        return json.dumps({"error": f"Unknown entity_type_code: {entity_type_code}"})
    jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
    if not jid:
        return json.dumps({"error": f"Unknown jurisdiction_code: {jurisdiction_code}"})

    if entity_id:
        row = await pool.fetchrow(
            """UPDATE entities SET name=$1, entity_type_id=$2, jurisdiction_id=$3,
               status=$4, formation_date=$5, tax_id=$6, tax_id_type=$7,
               grantor_id=$8, trustee_id=$9, karta_id=$10, registered_agent=$11,
               notes=$12, updated_at=now()
               WHERE id=$13 RETURNING id, name""",
            name, et, jid, status, fd, tax_id, tax_id_type,
            grantor_id, trustee_id, karta_id, registered_agent, notes, entity_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO entities (name, entity_type_id, jurisdiction_id, status,
               formation_date, tax_id, tax_id_type, grantor_id, trustee_id,
               karta_id, registered_agent, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               RETURNING id, name""",
            name, et, jid, status, fd, tax_id, tax_id_type,
            grantor_id, trustee_id, karta_id, registered_agent, notes,
        )
    return json.dumps(_row_to_dict(row))


# ─── Asset Tools ─────────────────────────────────────────────────


@mcp.tool()
async def list_assets(
    asset_class_code: str | None = None,
    asset_subclass_code: str | None = None,
    jurisdiction: str | None = None,
    owner_entity_id: int | None = None,
    owner_person_id: int | None = None,
) -> str:
    """List assets with optional normalized taxonomy filters.

    Args:
        asset_class_code: Filter by normalized class code.
        asset_subclass_code: Filter by normalized subclass code.
        jurisdiction: Filter by jurisdiction code.
        owner_entity_id: Filter by owning entity ID.
        owner_person_id: Filter by owning person ID.
    """
    pool = await get_pool()
    query = """
        SELECT a.id, a.name, a.asset_type, a.current_valuation_amount,
               a.valuation_currency, a.valuation_date,
               j.code AS jurisdiction,
               COALESCE(e.name, p.legal_name) AS owner_name,
               ac.code AS asset_class_code,
               ascb.code AS asset_subclass_code,
               at.country_code,
               at.region_code,
               rea.property_type
        FROM assets a
        LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
        LEFT JOIN entities e ON a.owner_entity_id = e.id
        LEFT JOIN people p ON a.owner_person_id = p.id
        LEFT JOIN asset_taxonomy at ON at.asset_id = a.id
        LEFT JOIN asset_classes ac ON at.asset_class_id = ac.id
        LEFT JOIN asset_subclasses ascb ON at.asset_subclass_id = ascb.id
        LEFT JOIN real_estate_assets rea ON rea.asset_id = a.id
        WHERE 1=1
    """
    params = []
    idx = 1
    if asset_class_code:
        query += f" AND ac.code = ${idx}"
        params.append(asset_class_code.strip().lower())
        idx += 1
    if asset_subclass_code:
        query += f" AND ascb.code = ${idx}"
        params.append(asset_subclass_code.strip().lower())
        idx += 1
    if jurisdiction:
        query += f" AND j.code = ${idx}"
        params.append(jurisdiction)
        idx += 1
    if owner_entity_id:
        query += f" AND a.owner_entity_id = ${idx}"
        params.append(owner_entity_id)
        idx += 1
    if owner_person_id:
        query += f" AND a.owner_person_id = ${idx}"
        params.append(owner_person_id)
        idx += 1
    query += " ORDER BY a.name"
    rows = await pool.fetch(query, *params)
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def upsert_asset(
    name: str,
    asset_class_code: str,
    asset_subclass_code: str,
    jurisdiction_code: str,
    valuation_currency: str,
    owner_entity_id: int | None = None,
    owner_person_id: int | None = None,
    current_valuation_amount: float | None = None,
    valuation_date: str | None = None,
    acquisition_date: str | None = None,
    acquisition_cost: float | None = None,
    paperless_doc_id: int | None = None,
    ghostfolio_account_id: str | None = None,
    address: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    country_code: str | None = None,
    state_code: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    address_line1: str | None = None,
    property_type: str | None = None,
    land_area: float | None = None,
    land_area_unit: str | None = None,
    building_area: float | None = None,
    building_area_unit: str | None = None,
    bedrooms: int | None = None,
    bathrooms: float | None = None,
    year_built: int | None = None,
    parcel_id: str | None = None,
    metadata: dict | str | None = None,
    asset_id: int | None = None,
) -> str:
    """Create or update an asset using normalized class/subclass taxonomy.

    This is a breaking interface by design:
    - `asset_class_code` and `asset_subclass_code` are required.
    - `jurisdiction_code` and `valuation_currency` are required.
    - Legacy free-text `asset_type` input is no longer accepted.

    Args:
        name: Asset name.
        asset_class_code: Normalized asset class code.
        asset_subclass_code: Normalized asset subclass code.
        jurisdiction_code: Jurisdiction code.
        valuation_currency: ISO-4217 currency code (e.g. USD, INR).
        owner_entity_id: Owning entity ID (provide this OR owner_person_id).
        owner_person_id: Owning person ID (provide this OR owner_entity_id).
        current_valuation_amount: Current market value.
        valuation_date: Date of valuation (YYYY-MM-DD).
        acquisition_date: Date acquired (YYYY-MM-DD).
        acquisition_cost: Original cost basis.
        paperless_doc_id: Link to Paperless-ngx document.
        ghostfolio_account_id: Link to Ghostfolio account.
        address: Physical address (for real estate).
        description: Description.
        notes: Free-text notes.
        country_code: Optional ISO country code for real-estate detail row.
        state_code: Optional state/province code.
        city: Optional city.
        postal_code: Optional postal/ZIP code.
        address_line1: Optional structured address line.
        property_type: Optional property type (residential, land, commercial, ag).
        land_area: Optional land area numeric value.
        land_area_unit: Unit for land area.
        building_area: Optional building area numeric value.
        building_area_unit: Unit for building area.
        bedrooms: Optional bedroom count.
        bathrooms: Optional bathroom count.
        year_built: Optional construction year.
        parcel_id: Optional parcel identifier.
        metadata: Optional JSON metadata payload for real-estate extension.
        asset_id: If provided, updates existing asset.
    """
    pool = await get_pool()
    normalized_class = (asset_class_code or "").strip().lower()
    normalized_subclass = (asset_subclass_code or "").strip().lower()
    normalized_jurisdiction = (jurisdiction_code or "").strip().upper()
    normalized_currency = _normalize_currency_code(valuation_currency)

    if not normalized_class:
        return json.dumps({"error": "asset_class_code is required"})
    if not normalized_subclass:
        return json.dumps({"error": "asset_subclass_code is required"})
    if not normalized_jurisdiction:
        return json.dumps({"error": "jurisdiction_code is required"})
    if not normalized_currency:
        return json.dumps(
            {"error": "valuation_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )

    class_row = await pool.fetchrow(
        "SELECT id, code FROM asset_classes WHERE code = $1",
        normalized_class,
    )
    if not class_row:
        class_codes = await pool.fetch("SELECT code FROM asset_classes ORDER BY code")
        return json.dumps(
            {
                "error": f"Unknown asset_class_code: {normalized_class}",
                "valid_asset_class_codes": [str(row["code"]) for row in class_codes],
            }
        )

    subclass_row = await pool.fetchrow(
        "SELECT id, asset_class_id, code FROM asset_subclasses WHERE code = $1",
        normalized_subclass,
    )
    if not subclass_row:
        subclass_codes = await pool.fetch(
            """SELECT code
               FROM asset_subclasses
               WHERE asset_class_id = $1
               ORDER BY code""",
            int(class_row["id"]),
        )
        return json.dumps(
            {
                "error": f"Unknown asset_subclass_code: {normalized_subclass}",
                "valid_asset_subclass_codes_for_class": [str(row["code"]) for row in subclass_codes],
            }
        )
    if int(subclass_row["asset_class_id"]) != int(class_row["id"]):
        return json.dumps(
            {
                "error": "asset_subclass_code does not belong to asset_class_code",
                "asset_class_code": normalized_class,
                "asset_subclass_code": normalized_subclass,
            }
        )

    jid = await pool.fetchval(
        "SELECT id FROM jurisdictions WHERE code = $1",
        normalized_jurisdiction,
    )
    if not jid:
        return json.dumps({"error": f"Unknown jurisdiction_code: {normalized_jurisdiction}"})

    if not asset_id and owner_entity_id is None and owner_person_id is None:
        return json.dumps({"error": "owner_entity_id or owner_person_id is required for new assets"})

    try:
        vd = date.fromisoformat(valuation_date) if valuation_date else None
    except ValueError:
        return json.dumps({"error": f"Invalid valuation_date: {valuation_date}"})
    try:
        ad = date.fromisoformat(acquisition_date) if acquisition_date else None
    except ValueError:
        return json.dumps({"error": f"Invalid acquisition_date: {acquisition_date}"})

    derived_asset_type = _canonical_asset_type(normalized_class, normalized_subclass)

    if asset_id:
        row = await pool.fetchrow(
            """UPDATE assets SET name=$1, asset_type=$2,
               owner_entity_id=COALESCE($3, owner_entity_id),
               owner_person_id=COALESCE($4, owner_person_id),
               jurisdiction_id=$5, current_valuation_amount=$6,
               valuation_currency=$7, valuation_date=$8, acquisition_date=$9,
               acquisition_cost=$10, paperless_doc_id=$11, ghostfolio_account_id=$12,
               address=$13, description=$14, notes=$15, updated_at=now()
               WHERE id=$16 RETURNING id, name""",
            name, derived_asset_type, owner_entity_id, owner_person_id, jid,
            current_valuation_amount, normalized_currency, vd, ad, acquisition_cost,
            paperless_doc_id, ghostfolio_account_id, address, description, notes, asset_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO assets (name, asset_type, owner_entity_id, owner_person_id,
               jurisdiction_id, current_valuation_amount, valuation_currency, valuation_date,
               acquisition_date, acquisition_cost, paperless_doc_id, ghostfolio_account_id,
               address, description, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
               RETURNING id, name""",
            name, derived_asset_type, owner_entity_id, owner_person_id, jid,
            current_valuation_amount, normalized_currency, vd, ad, acquisition_cost,
            paperless_doc_id, ghostfolio_account_id, address, description, notes,
        )
    resolved_asset_id = int(row["id"])

    await pool.execute(
        """INSERT INTO asset_taxonomy (
               asset_id, asset_class_id, asset_subclass_id, country_code, region_code
           ) VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (asset_id) DO UPDATE SET
               asset_class_id = EXCLUDED.asset_class_id,
               asset_subclass_id = EXCLUDED.asset_subclass_id,
               country_code = EXCLUDED.country_code,
               region_code = EXCLUDED.region_code,
               updated_at = now()""",
        resolved_asset_id,
        int(class_row["id"]),
        int(subclass_row["id"]),
        (country_code or "").strip().upper() or None,
        (state_code or "").strip().upper() or None,
    )

    metadata_payload = _coerce_json_input(metadata)
    resolved_country = (country_code or "").strip().upper()
    if not resolved_country and normalized_jurisdiction:
        resolved_country = normalized_jurisdiction.split("-")[0].strip().upper()

    # Maintain structured real-estate details when supplied.
    normalized_property_type = (property_type or "").strip().lower() or None
    if not normalized_property_type:
        if normalized_subclass == "real_estate_residential":
            normalized_property_type = "residential"
        elif normalized_subclass == "real_estate_land":
            normalized_property_type = "land"

    should_upsert_real_estate = (
        derived_asset_type == "real_estate"
        or any(v is not None for v in [state_code, city, postal_code, address_line1, property_type, land_area, building_area, bedrooms, bathrooms, year_built, parcel_id])
    )
    if should_upsert_real_estate and not resolved_country:
        return json.dumps(
            {
                "error": "country_code could not be derived for real-estate asset",
                "hint": "Provide country_code explicitly or use a jurisdiction_code with country prefix (e.g. US-CA).",
            }
        )
    if should_upsert_real_estate and resolved_country:
        await pool.execute(
            """INSERT INTO real_estate_assets (
                   asset_id, country_code, state_code, city, postal_code, address_line1,
                   property_type, land_area, land_area_unit, building_area, building_area_unit,
                   bedrooms, bathrooms, year_built, parcel_id, metadata
               ) VALUES (
                   $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16
               )
               ON CONFLICT (asset_id) DO UPDATE SET
                   country_code = EXCLUDED.country_code,
                   state_code = EXCLUDED.state_code,
                   city = EXCLUDED.city,
                   postal_code = EXCLUDED.postal_code,
                   address_line1 = EXCLUDED.address_line1,
                   property_type = EXCLUDED.property_type,
                   land_area = EXCLUDED.land_area,
                   land_area_unit = EXCLUDED.land_area_unit,
                   building_area = EXCLUDED.building_area,
                   building_area_unit = EXCLUDED.building_area_unit,
                   bedrooms = EXCLUDED.bedrooms,
                   bathrooms = EXCLUDED.bathrooms,
                   year_built = EXCLUDED.year_built,
                   parcel_id = EXCLUDED.parcel_id,
                   metadata = EXCLUDED.metadata,
                   updated_at = now()""",
            resolved_asset_id,
            resolved_country,
            state_code,
            city,
            postal_code,
            address_line1 or address,
            normalized_property_type,
            land_area,
            land_area_unit,
            building_area,
            building_area_unit,
            bedrooms,
            bathrooms,
            year_built,
            parcel_id,
            json.dumps(metadata_payload),
        )

    payload = _row_to_dict(row)
    payload["asset_id"] = resolved_asset_id
    payload["taxonomy_updated"] = True
    payload["asset_class_code"] = normalized_class
    payload["asset_subclass_code"] = normalized_subclass
    payload["jurisdiction_code"] = normalized_jurisdiction
    payload["valuation_currency"] = normalized_currency
    payload["asset_type"] = derived_asset_type
    payload["real_estate_details_updated"] = bool(should_upsert_real_estate and resolved_country)
    return json.dumps(payload)


# ─── Ownership Tools ─────────────────────────────────────────────


@mcp.tool()
async def get_ownership_graph(person_id: int | None = None) -> str:
    """Get the full ownership hierarchy. If person_id given, shows transitive ownership.

    Args:
        person_id: Optional person ID to get transitive ownership for.
    """
    pool = await get_pool()
    if person_id:
        rows = await pool.fetch(
            "SELECT * FROM get_transitive_ownership($1)", person_id
        )
        return json.dumps(_rows_to_list(rows), indent=2)
    else:
        rows = await pool.fetch(
            "SELECT * FROM v_ownership_summary ORDER BY owner_name, owned_name"
        )
        return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def set_ownership(
    percentage: float,
    owner_person_id: int | None = None,
    owner_entity_id: int | None = None,
    owned_entity_id: int | None = None,
    owned_asset_id: int | None = None,
    units: float | None = None,
    effective_date: str | None = None,
    notes: str | None = None,
) -> str:
    """Set or update an ownership relationship.

    Args:
        percentage: Ownership percentage (0-100).
        owner_person_id: Person who owns (provide this OR owner_entity_id).
        owner_entity_id: Entity that owns (provide this OR owner_person_id).
        owned_entity_id: Entity being owned (provide this OR owned_asset_id).
        owned_asset_id: Asset being owned (provide this OR owned_entity_id).
        units: Number of shares/units.
        effective_date: Effective date (YYYY-MM-DD).
        notes: Free-text notes.
    """
    pool = await get_pool()
    ed = date.fromisoformat(effective_date) if effective_date else date.today()

    # Check for existing active ownership path and update, or insert new
    existing = await pool.fetchrow(
        """SELECT id FROM ownership_paths
           WHERE owner_person_id IS NOT DISTINCT FROM $1
             AND owner_entity_id IS NOT DISTINCT FROM $2
             AND owned_entity_id IS NOT DISTINCT FROM $3
             AND owned_asset_id IS NOT DISTINCT FROM $4
             AND (end_date IS NULL OR end_date > CURRENT_DATE)""",
        owner_person_id, owner_entity_id, owned_entity_id, owned_asset_id,
    )

    if existing:
        row = await pool.fetchrow(
            """UPDATE ownership_paths SET percentage=$1, units=$2,
               effective_date=$3, notes=$4, updated_at=now()
               WHERE id=$5 RETURNING id""",
            percentage, units, ed, notes, existing["id"],
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO ownership_paths (owner_person_id, owner_entity_id,
               owned_entity_id, owned_asset_id, percentage, units,
               effective_date, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
            owner_person_id, owner_entity_id, owned_entity_id, owned_asset_id,
            percentage, units, ed, notes,
        )
    return json.dumps({"id": row["id"], "status": "ok"})


# ─── Cross-Cutting Tools ─────────────────────────────────────────


@mcp.tool()
async def get_net_worth(
    person_id: int | None = None,
    jurisdiction: str | None = None,
) -> str:
    """Get net worth summary, optionally filtered by person or jurisdiction.

    Args:
        person_id: Filter to assets owned by this person (direct + through entities).
        jurisdiction: Filter by jurisdiction code.
    """
    pool = await get_pool()
    if person_id:
        # Direct + entity-owned assets
        rows = await pool.fetch(
            """WITH person_entities AS (
                SELECT entity_id, effective_pct
                FROM get_transitive_ownership($1)
               )
               SELECT j.code AS jurisdiction, a.valuation_currency AS currency,
                      SUM(a.current_valuation_amount) AS direct_value,
                      0::numeric AS indirect_value
               FROM assets a
               LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
               WHERE a.owner_person_id = $1
                 AND a.current_valuation_amount IS NOT NULL
               GROUP BY j.code, a.valuation_currency
               UNION ALL
               SELECT j.code, a.valuation_currency,
                      0::numeric,
                      SUM(a.current_valuation_amount * pe.effective_pct / 100)
               FROM assets a
               JOIN person_entities pe ON a.owner_entity_id = pe.entity_id
               LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
               WHERE a.current_valuation_amount IS NOT NULL
               GROUP BY j.code, a.valuation_currency""",
            person_id,
        )
    elif jurisdiction:
        rows = await pool.fetch(
            "SELECT * FROM v_net_worth_by_jurisdiction WHERE jurisdiction_code = $1",
            jurisdiction,
        )
    else:
        rows = await pool.fetch("SELECT * FROM v_net_worth_by_jurisdiction")
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def get_upcoming_dates(days: int = 30) -> str:
    """Get critical dates due in the next N days.

    Args:
        days: Number of days to look ahead (default 30).
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT cd.*, e.name AS entity_name, a.name AS asset_name,
                  p.legal_name AS person_name, j.code AS jurisdiction
           FROM critical_dates cd
           LEFT JOIN entities e ON cd.entity_id = e.id
           LEFT JOIN assets a ON cd.asset_id = a.id
           LEFT JOIN people p ON cd.person_id = p.id
           LEFT JOIN jurisdictions j ON cd.jurisdiction_id = j.id
           WHERE NOT cd.completed
             AND cd.due_date <= CURRENT_DATE + $1 * INTERVAL '1 day'
           ORDER BY cd.due_date""",
        days,
    )
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def link_document(
    title: str,
    doc_type: str,
    paperless_doc_id: int | None = None,
    vaultwarden_item_id: str | None = None,
    entity_id: int | None = None,
    asset_id: int | None = None,
    person_id: int | None = None,
    jurisdiction_code: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    notes: str | None = None,
) -> str:
    """Link a document (from Paperless-ngx or Vaultwarden) to an entity, asset, or person.

    Args:
        title: Document title.
        doc_type: trust_agreement, llc_agreement, deed, will, poa, k1, tax_return, registration, certificate, other.
        paperless_doc_id: Paperless-ngx document ID.
        vaultwarden_item_id: Vaultwarden item ID.
        entity_id: Link to entity.
        asset_id: Link to asset.
        person_id: Link to person.
        jurisdiction_code: Relevant jurisdiction.
        effective_date: Document effective date (YYYY-MM-DD).
        expiry_date: Document expiry date (YYYY-MM-DD).
        notes: Free-text notes.
    """
    pool = await get_pool()
    jid = None
    if jurisdiction_code:
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)

    ed = date.fromisoformat(effective_date) if effective_date else None
    xd = date.fromisoformat(expiry_date) if expiry_date else None

    row = await pool.fetchrow(
        """INSERT INTO documents (title, doc_type, paperless_doc_id, vaultwarden_item_id,
           entity_id, asset_id, person_id, jurisdiction_id, effective_date, expiry_date, notes)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
           RETURNING id, title""",
        title, doc_type, paperless_doc_id, vaultwarden_item_id,
        entity_id, asset_id, person_id, jid, ed, xd, notes,
    )
    return json.dumps(_row_to_dict(row))


# ─── Illiquid Valuation & Statement Tools ────────────────────────


@mcp.tool()
async def list_valuation_methods() -> str:
    """List supported valuation methods."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT code, name, description, created_at
           FROM valuation_methods
           ORDER BY code"""
    )
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def record_valuation_observation(
    asset_id: int,
    method_code: str,
    value_amount: float,
    value_currency: str = "USD",
    source: str = "manual",
    valuation_date: str | None = None,
    confidence_score: float | None = None,
    notes: str | None = None,
    evidence: dict | str | None = None,
) -> str:
    """Record a valuation observation and update the asset's current valuation snapshot."""
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM assets WHERE id = $1", asset_id)
    if not exists:
        return json.dumps({"error": f"Asset {asset_id} not found"})

    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        return json.dumps(
            {"error": "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )

    vd = date.fromisoformat(valuation_date) if valuation_date else date.today()
    evidence_payload = _coerce_json_input(evidence)
    try:
        row = await _insert_valuation_observation(
            pool=pool,
            asset_id=asset_id,
            method_code=method_code,
            source=source,
            value_amount=value_amount,
            value_currency=normalized_currency,
            valuation_date=vd,
            confidence_score=confidence_score,
            notes=notes,
            evidence=evidence_payload,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    await pool.execute(
        """UPDATE assets
           SET current_valuation_amount = $1,
               valuation_currency = $2,
               valuation_date = $3,
               updated_at = now()
           WHERE id = $4""",
        value_amount,
        normalized_currency,
        vd,
        asset_id,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def list_valuation_observations(
    asset_id: int | None = None,
    limit: int = 100,
) -> str:
    """List valuation observations across assets or for a single asset."""
    pool = await get_pool()
    cap = max(1, min(limit, 500))
    if asset_id:
        rows = await pool.fetch(
            """SELECT vo.*, a.name AS asset_name
               FROM valuation_observations vo
               JOIN assets a ON vo.asset_id = a.id
               WHERE vo.asset_id = $1
               ORDER BY vo.valuation_date DESC, vo.id DESC
               LIMIT $2""",
            asset_id,
            cap,
        )
    else:
        rows = await pool.fetch(
            """SELECT vo.*, a.name AS asset_name
               FROM valuation_observations vo
               JOIN assets a ON vo.asset_id = a.id
               ORDER BY vo.valuation_date DESC, vo.id DESC
               LIMIT $1""",
            cap,
        )
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def set_manual_comp_valuation(
    asset_id: int,
    value_amount: float,
    value_currency: str = "USD",
    valuation_date: str | None = None,
    confidence_score: float | None = None,
    notes: str | None = None,
    comps: list[dict] | str | None = None,
) -> str:
    """Set a manual comp-based valuation, with optional individual comp records."""
    pool = await get_pool()
    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        return json.dumps(
            {"error": "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )

    vd = date.fromisoformat(valuation_date) if valuation_date else date.today()

    comps_payload = []
    if isinstance(comps, list):
        comps_payload = comps
    elif isinstance(comps, str):
        try:
            parsed = json.loads(comps)
            if isinstance(parsed, list):
                comps_payload = parsed
        except json.JSONDecodeError:
            comps_payload = []

    try:
        observation = await _insert_valuation_observation(
            pool=pool,
            asset_id=asset_id,
            method_code="manual_comp",
            source="user_manual",
            value_amount=value_amount,
            value_currency=normalized_currency,
            valuation_date=vd,
            confidence_score=confidence_score,
            notes=notes,
            evidence={"comps_count": len(comps_payload)},
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    observation_id = int(observation["id"])

    inserted_comps = 0
    for comp in comps_payload:
        if not isinstance(comp, dict):
            continue
        comp_date = None
        raw_date = comp.get("valuation_date")
        if isinstance(raw_date, str) and raw_date:
            try:
                comp_date = date.fromisoformat(raw_date)
            except ValueError:
                comp_date = None
        await pool.execute(
            """INSERT INTO valuation_comps (
                   valuation_observation_id, comp_identifier, address, city, state_code,
                   country_code, valuation_amount, valuation_currency, valuation_date,
                   distance_km, adjustment_notes, raw_data
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            observation_id,
            comp.get("comp_identifier") or comp.get("id"),
            comp.get("address"),
            comp.get("city"),
            comp.get("state_code") or comp.get("state"),
            comp.get("country_code") or comp.get("country"),
            _float_or_none(comp.get("valuation_amount") or comp.get("value")),
            _normalize_currency_code(comp.get("valuation_currency") or comp.get("currency"))
            or normalized_currency,
            comp_date,
            _float_or_none(comp.get("distance_km") or comp.get("distance")),
            comp.get("adjustment_notes"),
            json.dumps(comp),
        )
        inserted_comps += 1

    await pool.execute(
        """UPDATE assets
           SET current_valuation_amount = $1,
               valuation_currency = $2,
               valuation_date = $3,
               updated_at = now()
           WHERE id = $4""",
        value_amount,
        normalized_currency,
        vd,
        asset_id,
    )
    return json.dumps(
        {
            "status": "ok",
            "observation_id": observation_id,
            "asset_id": asset_id,
            "comps_inserted": inserted_comps,
        }
    )


@mcp.tool()
async def refresh_us_property_valuation(
    asset_id: int,
    valuation_date: str | None = None,
    value_currency: str = "USD",
) -> str:
    """Fetch a US property valuation from RentCast and persist it as a valuation observation."""
    if not RENTCAST_API_KEY:
        return json.dumps(
            {
                "error": "RENTCAST_API_KEY is not configured",
                "hint": "Set RENTCAST_API_KEY in estate-graph-mcp environment.",
            }
        )

    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        return json.dumps(
            {"error": "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT a.id, a.name, a.address,
                  r.country_code, r.state_code, r.city, r.postal_code, r.address_line1
           FROM assets a
           LEFT JOIN real_estate_assets r ON r.asset_id = a.id
           WHERE a.id = $1""",
        asset_id,
    )
    if not row:
        return json.dumps({"error": f"Asset {asset_id} not found"})
    row_dict = dict(row)

    country_code = (row_dict.get("country_code") or "").upper() if isinstance(row_dict.get("country_code"), str) else ""
    if country_code and country_code != "US":
        return json.dumps(
            {
                "error": "Only US automated valuation is supported",
                "asset_id": asset_id,
                "country_code": country_code,
            }
        )

    structured_address = ", ".join(
        part for part in [
            row_dict.get("address_line1"),
            row_dict.get("city"),
            row_dict.get("state_code"),
            row_dict.get("postal_code"),
        ] if isinstance(part, str) and part.strip()
    )
    address_query = structured_address or row_dict.get("address")
    if not address_query:
        return json.dumps(
            {
                "error": "No address available for asset",
                "asset_id": asset_id,
            }
        )

    headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_API_KEY}
    endpoints = [
        ("/avm/value", {"address": address_query}),
        ("/avm", {"address": address_query}),
        ("/properties", {"address": address_query, "limit": 1}),
    ]

    last_error: str | None = None
    for endpoint, params in endpoints:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(f"{RENTCAST_BASE_URL}{endpoint}", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            candidate_payload = payload[0] if isinstance(payload, list) and payload else payload
            if not isinstance(candidate_payload, dict):
                last_error = f"{endpoint}: unsupported payload type"
                continue
            extracted_value = _extract_numeric_value(candidate_payload)
            if extracted_value is None:
                last_error = f"{endpoint}: no numeric valuation field found"
                continue

            vd = date.fromisoformat(valuation_date) if valuation_date else date.today()
            try:
                observation = await _insert_valuation_observation(
                    pool=pool,
                    asset_id=asset_id,
                    method_code="rentcast_avm",
                    source="rentcast",
                    value_amount=extracted_value,
                    value_currency=normalized_currency,
                    valuation_date=vd,
                    confidence_score=None,
                    notes="Automated valuation refresh",
                    evidence={
                        "provider": "rentcast",
                        "endpoint": endpoint,
                        "params": params,
                        "payload": candidate_payload,
                    },
                )
            except ValueError as exc:
                return json.dumps({"error": str(exc), "asset_id": asset_id})
            await pool.execute(
                """UPDATE assets
                   SET current_valuation_amount = $1,
                       valuation_currency = $2,
                       valuation_date = $3,
                       updated_at = now()
                   WHERE id = $4""",
                extracted_value,
                normalized_currency,
                vd,
                asset_id,
            )
            return json.dumps(
                {
                    "status": "ok",
                    "asset_id": asset_id,
                    "valuation_observation_id": observation["id"],
                    "value_amount": extracted_value,
                    "value_currency": normalized_currency,
                    "provider": "rentcast",
                    "endpoint": endpoint,
                }
            )
        except Exception as exc:
            last_error = f"{endpoint}: {exc}"

    return json.dumps(
        {
            "error": "RentCast valuation lookup failed",
            "asset_id": asset_id,
            "address_query": address_query,
            "last_error": last_error,
        }
    )


@mcp.tool()
async def upsert_financial_statement_period(
    asset_id: int,
    period_start: str,
    period_end: str,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
    statement_currency: str = "USD",
    source: str = "manual",
    reporting_period_id: int | None = None,
) -> str:
    """Create or update a reporting period used by PL/CFS/BS statement fact tables."""
    pool = await get_pool()
    normalized_statement_currency = _normalize_currency_code(statement_currency)
    if not normalized_statement_currency:
        return json.dumps(
            {"error": "statement_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )
    ps = date.fromisoformat(period_start)
    pe = date.fromisoformat(period_end)

    if reporting_period_id:
        row = await pool.fetchrow(
            """UPDATE reporting_periods
               SET asset_id = $1, period_start = $2, period_end = $3, fiscal_year = $4,
                   fiscal_period = $5, statement_currency = $6, source = $7, updated_at = now()
               WHERE id = $8
               RETURNING *""",
            asset_id,
            ps,
            pe,
            fiscal_year,
            fiscal_period,
            normalized_statement_currency,
            source,
            reporting_period_id,
        )
    else:
        existing_id = await pool.fetchval(
            """SELECT id
               FROM reporting_periods
               WHERE asset_id = $1
                 AND period_start = $2
                 AND period_end = $3
                 AND COALESCE(fiscal_period, '') = COALESCE($4, '')""",
            asset_id,
            ps,
            pe,
            fiscal_period,
        )
        if existing_id:
            row = await pool.fetchrow(
                """UPDATE reporting_periods
                   SET fiscal_year = $1, statement_currency = $2, source = $3, updated_at = now()
                   WHERE id = $4
                   RETURNING *""",
                fiscal_year,
                normalized_statement_currency,
                source,
                existing_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO reporting_periods (
                       asset_id, period_start, period_end, fiscal_year, fiscal_period,
                       statement_currency, source
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                   RETURNING *""",
                asset_id,
                ps,
                pe,
                fiscal_year,
                fiscal_period,
                normalized_statement_currency,
                source,
            )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def upsert_statement_line_items(
    reporting_period_id: int,
    statement_type: str,
    line_items: dict | str,
    source: str = "manual",
    value_currency: str = "USD",
    overwrite: bool = True,
) -> str:
    """Upsert statement line items for PL/CFS/BS tables."""
    pool = await get_pool()
    normalized_value_currency = _normalize_currency_code(value_currency)
    if not normalized_value_currency:
        return json.dumps(
            {"error": "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)"}
        )

    table_name = _statement_table_name(statement_type)
    if not table_name:
        return json.dumps(
            {
                "error": f"Unsupported statement_type: {statement_type}",
                "valid_values": ["income_statement", "cash_flow_statement", "balance_sheet"],
            }
        )

    payload = _coerce_json_input(line_items)
    if not payload:
        return json.dumps({"error": "line_items must be a non-empty dict or JSON object string"})

    inserted = 0
    updated = 0
    for code, raw in payload.items():
        if not isinstance(code, str) or not code.strip():
            continue
        line_item_code = code.strip()
        line_item_label = None
        metadata = {}
        numeric_value = None

        if isinstance(raw, dict):
            line_item_label = raw.get("label")
            metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
            numeric_value = _float_or_none(raw.get("value_amount") if "value_amount" in raw else raw.get("value"))
        else:
            numeric_value = _float_or_none(raw)

        if numeric_value is None:
            continue

        if overwrite:
            await pool.execute(
                f"""INSERT INTO {table_name} (
                        reporting_period_id, line_item_code, line_item_label,
                        value_amount, value_currency, source, metadata
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (reporting_period_id, line_item_code, source) DO UPDATE SET
                        line_item_label = EXCLUDED.line_item_label,
                        value_amount = EXCLUDED.value_amount,
                        value_currency = EXCLUDED.value_currency,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()""",
                reporting_period_id,
                line_item_code,
                line_item_label,
                numeric_value,
                normalized_value_currency,
                source,
                json.dumps(metadata),
            )
            updated += 1
        else:
            await pool.execute(
                f"""INSERT INTO {table_name} (
                        reporting_period_id, line_item_code, line_item_label,
                        value_amount, value_currency, source, metadata
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (reporting_period_id, line_item_code, source) DO NOTHING""",
                reporting_period_id,
                line_item_code,
                line_item_label,
                numeric_value,
                normalized_value_currency,
                source,
                json.dumps(metadata),
            )
            inserted += 1

    return json.dumps(
        {
            "status": "ok",
            "statement_type": statement_type,
            "table_name": table_name,
            "rows_processed": len(payload),
            "rows_updated_or_upserted": updated,
            "rows_inserted_no_overwrite_mode": inserted,
        }
    )


@mcp.tool()
async def upsert_xbrl_facts_core(
    accession_number: str,
    facts: list[dict] | str,
    asset_id: int | None = None,
    filing_date: str | None = None,
    cik: str | None = None,
    ticker: str | None = None,
    source: str = "sec-edgar",
) -> str:
    """Insert XBRL core facts (report/concept/context/unit/fact) for illiquid valuation workflows."""
    pool = await get_pool()
    fd = date.fromisoformat(filing_date) if filing_date else None

    facts_payload = facts if isinstance(facts, list) else []
    if isinstance(facts, str):
        try:
            parsed = json.loads(facts)
            if isinstance(parsed, list):
                facts_payload = parsed
        except json.JSONDecodeError:
            facts_payload = []
    if not facts_payload:
        return json.dumps({"error": "facts must be a non-empty list or JSON list string"})

    report = await pool.fetchrow(
        """INSERT INTO xbrl_reports (asset_id, accession_number, cik, ticker, filing_date, source)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (accession_number) DO UPDATE SET
               asset_id = COALESCE(EXCLUDED.asset_id, xbrl_reports.asset_id),
               cik = COALESCE(EXCLUDED.cik, xbrl_reports.cik),
               ticker = COALESCE(EXCLUDED.ticker, xbrl_reports.ticker),
               filing_date = COALESCE(EXCLUDED.filing_date, xbrl_reports.filing_date),
               source = EXCLUDED.source
           RETURNING id""",
        asset_id,
        accession_number,
        cik,
        ticker,
        fd,
        source,
    )
    report_id = int(report["id"])

    inserted_facts = 0
    for fact in facts_payload:
        if not isinstance(fact, dict):
            continue
        concept_qname = (
            fact.get("concept_qname")
            or fact.get("concept")
            or fact.get("qname")
            or ""
        )
        concept_qname = concept_qname.strip()
        if not concept_qname:
            continue

        concept = await pool.fetchrow(
            """INSERT INTO xbrl_concepts (
                   concept_qname, namespace, local_name, label, data_type, balance, period_type
               ) VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (concept_qname) DO UPDATE SET
                   label = COALESCE(EXCLUDED.label, xbrl_concepts.label),
                   data_type = COALESCE(EXCLUDED.data_type, xbrl_concepts.data_type),
                   balance = COALESCE(EXCLUDED.balance, xbrl_concepts.balance),
                   period_type = COALESCE(EXCLUDED.period_type, xbrl_concepts.period_type)
               RETURNING id""",
            concept_qname,
            fact.get("namespace"),
            fact.get("local_name"),
            fact.get("label"),
            fact.get("data_type"),
            fact.get("balance"),
            fact.get("period_type"),
        )
        concept_id = int(concept["id"])

        context_id = None
        context_ref = fact.get("context_ref")
        if isinstance(context_ref, str) and context_ref.strip():
            ps = None
            pe = None
            inst = None
            try:
                if fact.get("period_start"):
                    ps = date.fromisoformat(str(fact.get("period_start")))
                if fact.get("period_end"):
                    pe = date.fromisoformat(str(fact.get("period_end")))
                if fact.get("instant_date"):
                    inst = date.fromisoformat(str(fact.get("instant_date")))
            except ValueError:
                ps = None
                pe = None
                inst = None
            context = await pool.fetchrow(
                """INSERT INTO xbrl_contexts (
                       xbrl_report_id, context_ref, entity_identifier,
                       period_start, period_end, instant_date, dimensions
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (xbrl_report_id, context_ref) DO UPDATE SET
                       period_start = COALESCE(EXCLUDED.period_start, xbrl_contexts.period_start),
                       period_end = COALESCE(EXCLUDED.period_end, xbrl_contexts.period_end),
                       instant_date = COALESCE(EXCLUDED.instant_date, xbrl_contexts.instant_date),
                       dimensions = EXCLUDED.dimensions
                   RETURNING id""",
                report_id,
                context_ref.strip(),
                fact.get("entity_identifier"),
                ps,
                pe,
                inst,
                json.dumps(fact.get("dimensions") if isinstance(fact.get("dimensions"), dict) else {}),
            )
            context_id = int(context["id"])

        unit_id = None
        unit_ref = fact.get("unit_ref")
        if isinstance(unit_ref, str) and unit_ref.strip():
            unit = await pool.fetchrow(
                """INSERT INTO xbrl_units (xbrl_report_id, unit_ref, measure, numerator, denominator)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (xbrl_report_id, unit_ref) DO UPDATE SET
                       measure = COALESCE(EXCLUDED.measure, xbrl_units.measure),
                       numerator = COALESCE(EXCLUDED.numerator, xbrl_units.numerator),
                       denominator = COALESCE(EXCLUDED.denominator, xbrl_units.denominator)
                   RETURNING id""",
                report_id,
                unit_ref.strip(),
                fact.get("measure"),
                fact.get("numerator"),
                fact.get("denominator"),
            )
            unit_id = int(unit["id"])

        fact_value_numeric = _float_or_none(
            fact.get("fact_value_numeric") if "fact_value_numeric" in fact else fact.get("value")
        )
        fact_value_text = fact.get("fact_value_text")
        if fact_value_text is None and fact.get("value") is not None:
            fact_value_text = str(fact.get("value"))

        await pool.execute(
            """INSERT INTO xbrl_facts (
                   xbrl_report_id, concept_id, context_id, unit_id,
                   fact_value_text, fact_value_numeric, decimals, precision, metadata
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            report_id,
            concept_id,
            context_id,
            unit_id,
            fact_value_text,
            fact_value_numeric,
            fact.get("decimals"),
            fact.get("precision"),
            json.dumps(fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}),
        )
        inserted_facts += 1

    return json.dumps(
        {
            "status": "ok",
            "xbrl_report_id": report_id,
            "accession_number": accession_number,
            "facts_ingested": inserted_facts,
        }
    )


@mcp.tool()
async def validate_ocf_document(document: dict | str) -> str:
    """Validate an OCF document against a minimal pinned schema contract."""
    payload = _coerce_json_input(document)
    if not payload:
        return json.dumps({"valid": False, "errors": ["Document must be a JSON object"]})

    errors: list[str] = []
    try:
        validate(instance=payload, schema=OCF_MINIMAL_SCHEMA)
    except ValidationError as exc:
        errors.append(str(exc))

    ocf_version = payload.get("ocf_version")
    if isinstance(ocf_version, str):
        if not ocf_version.strip():
            errors.append("ocf_version must be non-empty")
    else:
        errors.append("ocf_version must be a string")

    return json.dumps(
        {
            "valid": len(errors) == 0,
            "ocf_version": ocf_version,
            "errors": errors,
            "expected_version_default": OCF_DEFAULT_VERSION,
        }
    )


@mcp.tool()
async def ingest_ocf_document(
    document: dict | str,
    asset_id: int | None = None,
    run_validation: bool = True,
) -> str:
    """Store an OCF document payload and derive instrument/position rows."""
    pool = await get_pool()
    payload = _coerce_json_input(document)
    if not payload:
        return json.dumps({"error": "Document must be a JSON object"})

    validation_status = "unknown"
    validation_errors: list[str] = []
    if run_validation:
        validation_result = json.loads(await validate_ocf_document(payload))
        validation_status = "valid" if validation_result.get("valid") else "invalid"
        validation_errors = validation_result.get("errors", [])

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    ocf_version = payload.get("ocf_version")

    document_row = await pool.fetchrow(
        """INSERT INTO ocf_documents (asset_id, ocf_version, document_hash, validation_status, validation_errors, payload)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (document_hash) DO UPDATE SET
               asset_id = COALESCE(EXCLUDED.asset_id, ocf_documents.asset_id),
               ocf_version = COALESCE(EXCLUDED.ocf_version, ocf_documents.ocf_version),
               validation_status = EXCLUDED.validation_status,
               validation_errors = EXCLUDED.validation_errors,
               payload = EXCLUDED.payload
           RETURNING id""",
        asset_id,
        ocf_version if isinstance(ocf_version, str) else None,
        digest,
        validation_status,
        json.dumps(validation_errors),
        json.dumps(payload),
    )
    document_id = int(document_row["id"])

    await pool.execute("DELETE FROM ocf_instruments WHERE ocf_document_id = $1", document_id)
    await pool.execute("DELETE FROM ocf_positions WHERE ocf_document_id = $1", document_id)

    instruments = payload.get("instruments")
    if not isinstance(instruments, list):
        instruments = []
    positions = payload.get("positions")
    if not isinstance(positions, list):
        positions = []

    instrument_count = 0
    for instrument in instruments:
        if not isinstance(instrument, dict):
            continue
        instrument_id = (
            instrument.get("id")
            or instrument.get("instrument_id")
            or instrument.get("security_id")
        )
        if not instrument_id:
            continue
        await pool.execute(
            """INSERT INTO ocf_instruments (
                   ocf_document_id, instrument_id, instrument_type, security_name, payload
               ) VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (ocf_document_id, instrument_id) DO UPDATE SET
                   instrument_type = EXCLUDED.instrument_type,
                   security_name = EXCLUDED.security_name,
                   payload = EXCLUDED.payload""",
            document_id,
            str(instrument_id),
            instrument.get("type") or instrument.get("instrument_type"),
            instrument.get("name") or instrument.get("security_name"),
            json.dumps(instrument),
        )
        instrument_count += 1

    position_count = 0
    for position in positions:
        if not isinstance(position, dict):
            continue
        await pool.execute(
            """INSERT INTO ocf_positions (
                   ocf_document_id, instrument_id, stakeholder_name, quantity, ownership_pct, payload
               ) VALUES ($1,$2,$3,$4,$5,$6)""",
            document_id,
            position.get("instrument_id") or position.get("security_id"),
            position.get("stakeholder_name") or position.get("holder_name"),
            _float_or_none(position.get("quantity")),
            _float_or_none(position.get("ownership_pct")),
            json.dumps(position),
        )
        position_count += 1

    return json.dumps(
        {
            "status": "ok",
            "ocf_document_id": document_id,
            "document_hash": digest,
            "validation_status": validation_status,
            "validation_errors": validation_errors,
            "instruments_ingested": instrument_count,
            "positions_ingested": position_count,
        }
    )


@mcp.tool()
async def get_ocf_positions(
    ocf_document_id: int | None = None,
    asset_id: int | None = None,
    limit: int = 500,
) -> str:
    """Return OCF-derived position rows."""
    pool = await get_pool()
    cap = max(1, min(limit, 2000))
    if ocf_document_id:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               WHERE p.ocf_document_id = $1
               ORDER BY p.id
               LIMIT $2""",
            ocf_document_id,
            cap,
        )
    elif asset_id:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               WHERE d.asset_id = $1
               ORDER BY p.id
               LIMIT $2""",
            asset_id,
            cap,
        )
    else:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               ORDER BY p.id DESC
               LIMIT $1""",
            cap,
        )
    return json.dumps(_rows_to_list(rows), indent=2)


if __name__ == "__main__":
    mcp.run()
