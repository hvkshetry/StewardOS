"""Estate Planning MCP Server.

Provides tools for managing people, legal entities, ownership, documents,
and critical dates for succession, trust, and inheritance workflows.
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
    "DATABASE_URL", "postgresql://estate:changeme@localhost:5434/estate_planning"
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


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _normalize_identifier_type(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "_")


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


async def _ensure_document_metadata_exists(pool: asyncpg.Pool, paperless_doc_id: int) -> None:
    await pool.execute(
        """INSERT INTO document_metadata (paperless_doc_id, doc_purpose_type)
           VALUES ($1, 'other')
           ON CONFLICT (paperless_doc_id) DO NOTHING""",
        paperless_doc_id,
    )


def _exactly_one(values: list[object]) -> bool:
    return sum(v is not None for v in values) == 1


# ─── MCP Server ──────────────────────────────────────────────────

mcp = FastMCP(
    "estate-planning",
    instructions=(
        "Estate planning graph for people, legal entities, ownership paths, "
        "documents, and critical dates across jurisdictions."
    ),
)


# ─── People Tools ────────────────────────────────────────────────


@mcp.tool()
async def list_people() -> str:
    """List all family members in the estate-planning graph."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, legal_name, preferred_name, citizenship, residency_status, "
        "death_date, incapacity_status "
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
        """SELECT dm.paperless_doc_id,
                  COALESCE(dm.source_snapshot_title, d.title) AS title,
                  dm.doc_purpose_type,
                  dm.status,
                  dm.effective_date,
                  dm.expiry_date,
                  dm.last_reviewed
           FROM document_metadata dm
           LEFT JOIN documents d ON d.paperless_doc_id = dm.paperless_doc_id
           WHERE dm.person_id = $1
           ORDER BY dm.paperless_doc_id""",
        person_id,
    )
    relationships = await pool.fetch(
        """SELECT id, person_id, related_person_id, relationship_type,
                  start_date, end_date, jurisdiction_code
           FROM person_relationships
           WHERE person_id = $1 OR related_person_id = $1
           ORDER BY relationship_type, start_date NULLS FIRST""",
        person_id,
    )
    result = _row_to_dict(person)
    result["ownership"] = _rows_to_list(ownership)
    result["documents"] = _rows_to_list(docs)
    result["relationships"] = _rows_to_list(relationships)
    return json.dumps(result, indent=2)


@mcp.tool()
async def upsert_person(
    legal_name: str,
    preferred_name: str | None = None,
    date_of_birth: str | None = None,
    death_date: str | None = None,
    place_of_birth: str | None = None,
    citizenship: list[str] | None = None,
    tax_residencies: list[str] | None = None,
    residency_status: str | None = None,
    incapacity_status: str | None = None,
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
        death_date: Date of death (YYYY-MM-DD).
        place_of_birth: Place of birth text.
        citizenship: List of country codes (e.g. ['US', 'IN']).
        tax_residencies: Tax residency country codes (e.g. ['US', 'IN']).
        residency_status: citizen, resident, nri, oci.
        incapacity_status: legal_capacity, limited_capacity, incapacitated.
        tax_id: SSN, PAN, etc.
        tax_id_type: SSN, PAN.
        email: Email address.
        phone: Phone number.
        notes: Free-text notes.
        person_id: If provided, updates existing person.
    """
    pool = await get_pool()
    try:
        dob = _parse_iso_date(date_of_birth, "date_of_birth")
        dod = _parse_iso_date(death_date, "death_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if person_id:
        row = await pool.fetchrow(
            """UPDATE people SET legal_name=$1, preferred_name=$2, date_of_birth=$3,
               death_date=$4, place_of_birth=$5, citizenship=$6, tax_residencies=$7,
               residency_status=$8, incapacity_status=$9, tax_id=$10, tax_id_type=$11,
               email=$12, phone=$13, notes=$14, updated_at=now()
               WHERE id=$15 RETURNING id, legal_name""",
            legal_name, preferred_name, dob, dod, place_of_birth, citizenship, tax_residencies,
            residency_status, incapacity_status, tax_id, tax_id_type,
            email, phone, notes, person_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO people (legal_name, preferred_name, date_of_birth,
               death_date, place_of_birth, citizenship, tax_residencies, residency_status,
               incapacity_status, tax_id, tax_id_type, email, phone, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id, legal_name""",
            legal_name, preferred_name, dob, dod, place_of_birth, citizenship, tax_residencies,
            residency_status, incapacity_status, tax_id, tax_id_type, email, phone, notes,
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
                  j.code AS jurisdiction_code, j.name AS jurisdiction_name,
                  glj.code AS governing_law_jurisdiction_code
           FROM entities e
           JOIN entity_types et ON e.entity_type_id = et.id
           JOIN jurisdictions j ON e.jurisdiction_id = j.id
           LEFT JOIN jurisdictions glj ON e.governing_law_jurisdiction_id = glj.id
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
        """SELECT dm.paperless_doc_id,
                  COALESCE(dm.source_snapshot_title, d.title) AS title,
                  dm.doc_purpose_type,
                  dm.status,
                  dm.effective_date,
                  dm.expiry_date,
                  dm.last_reviewed
           FROM document_metadata dm
           LEFT JOIN documents d ON d.paperless_doc_id = dm.paperless_doc_id
           WHERE dm.entity_id = $1
           ORDER BY dm.paperless_doc_id""",
        entity_id,
    )
    dates = await pool.fetch(
        "SELECT * FROM critical_dates WHERE entity_id = $1 AND NOT completed ORDER BY due_date",
        entity_id,
    )
    roles = await pool.fetch(
        """SELECT er.*, p.legal_name AS holder_person_name, he.name AS holder_entity_name
           FROM entity_roles er
           LEFT JOIN people p ON p.id = er.holder_person_id
           LEFT JOIN entities he ON he.id = er.holder_entity_id
           WHERE er.entity_id = $1
             AND (er.end_date IS NULL OR er.end_date >= CURRENT_DATE)
           ORDER BY er.role_type, er.effective_date DESC""",
        entity_id,
    )
    result = _row_to_dict(entity)
    result["ownership"] = _rows_to_list(ownership)
    result["documents"] = _rows_to_list(docs)
    result["critical_dates"] = _rows_to_list(dates)
    result["roles"] = _rows_to_list(roles)
    return json.dumps(result, indent=2)


@mcp.tool()
async def upsert_entity(
    name: str,
    entity_type_code: str,
    jurisdiction_code: str,
    governing_law_jurisdiction_code: str | None = None,
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
        governing_law_jurisdiction_code: Governing-law jurisdiction code (e.g. US-DE, IN-KA).
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
    governing_law_jid = None
    if governing_law_jurisdiction_code:
        governing_law_jid = await pool.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            governing_law_jurisdiction_code,
        )
        if not governing_law_jid:
            return json.dumps(
                {"error": f"Unknown governing_law_jurisdiction_code: {governing_law_jurisdiction_code}"}
            )

    if entity_id:
        row = await pool.fetchrow(
            """UPDATE entities SET name=$1, entity_type_id=$2, jurisdiction_id=$3,
               governing_law_jurisdiction_id=COALESCE($4, governing_law_jurisdiction_id),
               status=$5, formation_date=$6, tax_id=$7, tax_id_type=$8,
               grantor_id=$9, trustee_id=$10, karta_id=$11, registered_agent=$12,
               notes=$13, updated_at=now()
               WHERE id=$14 RETURNING id, name""",
            name, et, jid, governing_law_jid, status, fd, tax_id, tax_id_type,
            grantor_id, trustee_id, karta_id, registered_agent, notes, entity_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO entities (name, entity_type_id, jurisdiction_id, status,
               governing_law_jurisdiction_id, formation_date, tax_id, tax_id_type, grantor_id, trustee_id,
               karta_id, registered_agent, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               RETURNING id, name""",
            name, et, jid, status, governing_law_jid, fd, tax_id, tax_id_type,
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
    interest_row = await pool.fetchrow(
        """INSERT INTO beneficial_interests (
               ownership_path_id,
               owner_person_id, owner_entity_id,
               subject_entity_id, subject_asset_id,
               interest_type, direct_or_indirect, beneficial_flag,
               share_exact, start_date, assertion_source, notes
           )
           VALUES ($1,$2,$3,$4,$5,'shareholding','unknown',FALSE,$6,$7,'set_ownership', $8)
           ON CONFLICT (ownership_path_id) WHERE ownership_path_id IS NOT NULL
           DO UPDATE SET
               owner_person_id = EXCLUDED.owner_person_id,
               owner_entity_id = EXCLUDED.owner_entity_id,
               subject_entity_id = EXCLUDED.subject_entity_id,
               subject_asset_id = EXCLUDED.subject_asset_id,
               share_exact = EXCLUDED.share_exact,
               start_date = EXCLUDED.start_date,
               notes = EXCLUDED.notes,
               updated_at = now()
           RETURNING id""",
        row["id"],
        owner_person_id,
        owner_entity_id,
        owned_entity_id,
        owned_asset_id,
        percentage,
        ed,
        notes,
    )
    return json.dumps(
        {
            "id": row["id"],
            "status": "ok",
            "beneficial_interest_id": interest_row["id"] if interest_row else None,
        }
    )


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
        """SELECT cd.id,
                  cd.title,
                  cd.date_type,
                  cd.due_date,
                  cd.entity_id,
                  cd.asset_id,
                  cd.person_id,
                  cd.jurisdiction_id,
                  cd.notes,
                  'critical_date'::text AS source_type,
                  e.name AS entity_name,
                  a.name AS asset_name,
                  p.legal_name AS person_name,
                  j.code AS jurisdiction
           FROM critical_dates cd
           LEFT JOIN entities e ON cd.entity_id = e.id
           LEFT JOIN assets a ON cd.asset_id = a.id
           LEFT JOIN people p ON cd.person_id = p.id
           LEFT JOIN jurisdictions j ON cd.jurisdiction_id = j.id
           WHERE NOT cd.completed
             AND cd.due_date <= CURRENT_DATE + $1 * INTERVAL '1 day'
           UNION ALL
           SELECT NULL::integer AS id,
                  COALESCE(dm.source_snapshot_title, 'Document review') AS title,
                  'document_review'::text AS date_type,
                  drp.next_review_date AS due_date,
                  dm.entity_id,
                  dm.asset_id,
                  dm.person_id,
                  dm.jurisdiction_id,
                  drp.notes,
                  'document_review_policy'::text AS source_type,
                  e2.name AS entity_name,
                  a2.name AS asset_name,
                  p2.legal_name AS person_name,
                  j2.code AS jurisdiction
           FROM document_review_policies drp
           JOIN document_metadata dm ON dm.paperless_doc_id = drp.paperless_doc_id
           LEFT JOIN entities e2 ON dm.entity_id = e2.id
           LEFT JOIN assets a2 ON dm.asset_id = a2.id
           LEFT JOIN people p2 ON dm.person_id = p2.id
           LEFT JOIN jurisdictions j2 ON dm.jurisdiction_id = j2.id
           WHERE drp.policy_status = 'active'
             AND drp.next_review_date IS NOT NULL
             AND drp.next_review_date <= CURRENT_DATE + $1 * INTERVAL '1 day'
           ORDER BY due_date, title""",
        days,
    )
    return json.dumps(_rows_to_list(rows), indent=2)


@mcp.tool()
async def link_document(
    title: str | None = None,
    doc_type: str | None = None,
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
    """Link document metadata to estate records using Paperless as canonical identity.

    Args:
        title: Optional non-canonical title snapshot from source.
        doc_type: Estate purpose type (trust_agreement, llc_agreement, deed, will, poa, etc).
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
    if paperless_doc_id is None:
        return json.dumps({"error": "paperless_doc_id is required"})

    pool = await get_pool()
    jid = None
    if jurisdiction_code:
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
        if not jid:
            return json.dumps({"error": f"Unknown jurisdiction_code: {jurisdiction_code}"})

    try:
        ed = _parse_iso_date(effective_date, "effective_date")
        xd = _parse_iso_date(expiry_date, "expiry_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    source_title = (title or "").strip() or None
    purpose_type = (doc_type or "other").strip().lower()

    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM documents WHERE paperless_doc_id = $1",
                paperless_doc_id,
            )
            if existing:
                legacy = await conn.fetchrow(
                    """UPDATE documents
                       SET title = COALESCE($1, title),
                           doc_type = COALESCE($2, doc_type),
                           vaultwarden_item_id = COALESCE($3, vaultwarden_item_id),
                           entity_id = COALESCE($4, entity_id),
                           asset_id = COALESCE($5, asset_id),
                           person_id = COALESCE($6, person_id),
                           jurisdiction_id = COALESCE($7, jurisdiction_id),
                           effective_date = COALESCE($8, effective_date),
                           expiry_date = COALESCE($9, expiry_date),
                           notes = COALESCE($10, notes),
                           updated_at = now()
                       WHERE id = $11
                       RETURNING id, title, paperless_doc_id""",
                    source_title,
                    purpose_type,
                    vaultwarden_item_id,
                    entity_id,
                    asset_id,
                    person_id,
                    jid,
                    ed,
                    xd,
                    notes,
                    existing["id"],
                )
            else:
                legacy = await conn.fetchrow(
                    """INSERT INTO documents (
                           title, doc_type, paperless_doc_id, vaultwarden_item_id,
                           entity_id, asset_id, person_id, jurisdiction_id,
                           effective_date, expiry_date, notes
                       ) VALUES (
                           $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
                       )
                       RETURNING id, title, paperless_doc_id""",
                    source_title or f"Paperless {paperless_doc_id}",
                    purpose_type,
                    paperless_doc_id,
                    vaultwarden_item_id,
                    entity_id,
                    asset_id,
                    person_id,
                    jid,
                    ed,
                    xd,
                    notes,
                )

            metadata = await conn.fetchrow(
                """INSERT INTO document_metadata (
                       paperless_doc_id, entity_id, asset_id, person_id, jurisdiction_id,
                       doc_purpose_type, effective_date, expiry_date, source_snapshot_title,
                       source_snapshot_doc_type, notes, status
                   ) VALUES (
                       $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'active'
                   )
                   ON CONFLICT (paperless_doc_id) DO UPDATE SET
                       entity_id = COALESCE(EXCLUDED.entity_id, document_metadata.entity_id),
                       asset_id = COALESCE(EXCLUDED.asset_id, document_metadata.asset_id),
                       person_id = COALESCE(EXCLUDED.person_id, document_metadata.person_id),
                       jurisdiction_id = COALESCE(EXCLUDED.jurisdiction_id, document_metadata.jurisdiction_id),
                       doc_purpose_type = COALESCE(EXCLUDED.doc_purpose_type, document_metadata.doc_purpose_type),
                       effective_date = COALESCE(EXCLUDED.effective_date, document_metadata.effective_date),
                       expiry_date = COALESCE(EXCLUDED.expiry_date, document_metadata.expiry_date),
                       source_snapshot_title = COALESCE(EXCLUDED.source_snapshot_title, document_metadata.source_snapshot_title),
                       source_snapshot_doc_type = COALESCE(EXCLUDED.source_snapshot_doc_type, document_metadata.source_snapshot_doc_type),
                       notes = COALESCE(EXCLUDED.notes, document_metadata.notes),
                       updated_at = now()
                   RETURNING paperless_doc_id, doc_purpose_type, status""",
                paperless_doc_id,
                entity_id,
                asset_id,
                person_id,
                jid,
                purpose_type,
                ed,
                xd,
                source_title,
                purpose_type,
                notes,
            )

    payload = _row_to_dict(legacy)
    payload["paperless_doc_id"] = paperless_doc_id
    payload["doc_metadata"] = _row_to_dict(metadata)
    payload["status"] = "ok"
    return json.dumps(payload)


@mcp.tool()
async def upsert_document_metadata(
    paperless_doc_id: int,
    doc_purpose_type: str = "other",
    entity_id: int | None = None,
    asset_id: int | None = None,
    person_id: int | None = None,
    jurisdiction_code: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    last_reviewed: str | None = None,
    status: str = "active",
    source_snapshot_title: str | None = None,
    source_snapshot_doc_type: str | None = None,
    notes: str | None = None,
) -> str:
    """Create or update estate-only metadata for a Paperless document."""
    pool = await get_pool()
    jid = None
    if jurisdiction_code:
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
        if not jid:
            return json.dumps({"error": f"Unknown jurisdiction_code: {jurisdiction_code}"})
    try:
        ed = _parse_iso_date(effective_date, "effective_date")
        xd = _parse_iso_date(expiry_date, "expiry_date")
        lr = _parse_iso_date(last_reviewed, "last_reviewed")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    row = await pool.fetchrow(
        """INSERT INTO document_metadata (
               paperless_doc_id, entity_id, asset_id, person_id, jurisdiction_id,
               doc_purpose_type, effective_date, expiry_date, last_reviewed, status,
               source_snapshot_title, source_snapshot_doc_type, notes
           )
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
           ON CONFLICT (paperless_doc_id) DO UPDATE SET
               entity_id = COALESCE(EXCLUDED.entity_id, document_metadata.entity_id),
               asset_id = COALESCE(EXCLUDED.asset_id, document_metadata.asset_id),
               person_id = COALESCE(EXCLUDED.person_id, document_metadata.person_id),
               jurisdiction_id = COALESCE(EXCLUDED.jurisdiction_id, document_metadata.jurisdiction_id),
               doc_purpose_type = EXCLUDED.doc_purpose_type,
               effective_date = COALESCE(EXCLUDED.effective_date, document_metadata.effective_date),
               expiry_date = COALESCE(EXCLUDED.expiry_date, document_metadata.expiry_date),
               last_reviewed = COALESCE(EXCLUDED.last_reviewed, document_metadata.last_reviewed),
               status = EXCLUDED.status,
               source_snapshot_title = COALESCE(EXCLUDED.source_snapshot_title, document_metadata.source_snapshot_title),
               source_snapshot_doc_type = COALESCE(EXCLUDED.source_snapshot_doc_type, document_metadata.source_snapshot_doc_type),
               notes = COALESCE(EXCLUDED.notes, document_metadata.notes),
               updated_at = now()
           RETURNING *""",
        paperless_doc_id,
        entity_id,
        asset_id,
        person_id,
        jid,
        doc_purpose_type.strip().lower(),
        ed,
        xd,
        lr,
        status.strip().lower(),
        (source_snapshot_title or "").strip() or None,
        (source_snapshot_doc_type or "").strip() or None,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def set_document_version_link(
    paperless_doc_id: int,
    supersedes_paperless_doc_id: int,
    version_reason: str | None = None,
    asserted_by: str | None = None,
    notes: str | None = None,
) -> str:
    """Record that one Paperless document supersedes another."""
    if paperless_doc_id == supersedes_paperless_doc_id:
        return json.dumps({"error": "paperless_doc_id and supersedes_paperless_doc_id must differ"})

    pool = await get_pool()
    await _ensure_document_metadata_exists(pool, paperless_doc_id)
    await _ensure_document_metadata_exists(pool, supersedes_paperless_doc_id)

    cycle = await pool.fetchval(
        """WITH RECURSIVE chain AS (
               SELECT supersedes_paperless_doc_id AS node
               FROM document_version_links
               WHERE paperless_doc_id = $1
               UNION ALL
               SELECT dvl.supersedes_paperless_doc_id
               FROM document_version_links dvl
               JOIN chain c ON dvl.paperless_doc_id = c.node
           )
           SELECT 1 FROM chain WHERE node = $2 LIMIT 1""",
        supersedes_paperless_doc_id,
        paperless_doc_id,
    )
    if cycle:
        return json.dumps(
            {
                "error": "version link would create a cycle",
                "paperless_doc_id": paperless_doc_id,
                "supersedes_paperless_doc_id": supersedes_paperless_doc_id,
            }
        )

    row = await pool.fetchrow(
        """INSERT INTO document_version_links (
               paperless_doc_id, supersedes_paperless_doc_id, version_reason, asserted_by, notes
           )
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (paperless_doc_id, supersedes_paperless_doc_id) DO UPDATE SET
               version_reason = COALESCE(EXCLUDED.version_reason, document_version_links.version_reason),
               asserted_by = COALESCE(EXCLUDED.asserted_by, document_version_links.asserted_by),
               notes = COALESCE(EXCLUDED.notes, document_version_links.notes),
               asserted_at = now()
           RETURNING *""",
        paperless_doc_id,
        supersedes_paperless_doc_id,
        version_reason,
        asserted_by,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def add_document_participant(
    paperless_doc_id: int,
    person_id: int,
    role: str,
    signed_at: str | None = None,
    notes: str | None = None,
) -> str:
    """Add a person-role participant for a Paperless document (signatory/witness/notary/etc.)."""
    pool = await get_pool()
    await _ensure_document_metadata_exists(pool, paperless_doc_id)
    signed_dt = None
    if signed_at:
        try:
            signed_dt = datetime.fromisoformat(signed_at)
        except ValueError:
            return json.dumps({"error": f"Invalid signed_at: {signed_at}. Use ISO datetime format."})

    row = await pool.fetchrow(
        """INSERT INTO document_participants (
               paperless_doc_id, person_id, role, signed_at, notes
           ) VALUES ($1,$2,$3,$4,$5)
           RETURNING *""",
        paperless_doc_id,
        person_id,
        role.strip().lower(),
        signed_dt,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def add_document_assertion(
    paperless_doc_id: int,
    assertion_type: str,
    asserted_value_json: dict | str | None = None,
    source_system: str = "estate-planning",
    source_record_id: str | None = None,
    confidence: float | None = None,
    asserted_at: str | None = None,
    notes: str | None = None,
) -> str:
    """Record a source-backed assertion on a Paperless document."""
    pool = await get_pool()
    await _ensure_document_metadata_exists(pool, paperless_doc_id)

    assertion_dt = None
    if asserted_at:
        try:
            assertion_dt = datetime.fromisoformat(asserted_at)
        except ValueError:
            return json.dumps({"error": f"Invalid asserted_at: {asserted_at}. Use ISO datetime format."})

    row = await pool.fetchrow(
        """INSERT INTO document_assertions (
               paperless_doc_id, assertion_type, asserted_value_json, source_system,
               source_record_id, confidence, asserted_at, notes
           ) VALUES (
               $1,$2,$3,$4,$5,$6,COALESCE($7, now()),$8
           )
           RETURNING *""",
        paperless_doc_id,
        assertion_type.strip().lower(),
        json.dumps(_coerce_json_input(asserted_value_json)),
        source_system,
        source_record_id,
        confidence,
        assertion_dt,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def upsert_document_review_policy(
    paperless_doc_id: int,
    review_cadence: str = "annual",
    next_review_date: str | None = None,
    renewal_window_days: int = 30,
    owner_person_id: int | None = None,
    policy_status: str = "active",
    notes: str | None = None,
) -> str:
    """Set review cadence and renewal policy for a Paperless document."""
    pool = await get_pool()
    await _ensure_document_metadata_exists(pool, paperless_doc_id)

    try:
        nrd = _parse_iso_date(next_review_date, "next_review_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    row = await pool.fetchrow(
        """INSERT INTO document_review_policies (
               paperless_doc_id, review_cadence, next_review_date, renewal_window_days,
               owner_person_id, policy_status, notes
           ) VALUES ($1,$2,$3,$4,$5,$6,$7)
           ON CONFLICT (paperless_doc_id) DO UPDATE SET
               review_cadence = EXCLUDED.review_cadence,
               next_review_date = EXCLUDED.next_review_date,
               renewal_window_days = EXCLUDED.renewal_window_days,
               owner_person_id = EXCLUDED.owner_person_id,
               policy_status = EXCLUDED.policy_status,
               notes = COALESCE(EXCLUDED.notes, document_review_policies.notes),
               updated_at = now()
           RETURNING *""",
        paperless_doc_id,
        review_cadence.strip().lower(),
        nrd,
        renewal_window_days,
        owner_person_id,
        policy_status.strip().lower(),
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def set_person_relationship(
    person_id: int,
    related_person_id: int,
    relationship_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
    jurisdiction_code: str | None = None,
    source_paperless_doc_id: int | None = None,
    notes: str | None = None,
) -> str:
    """Create a first-class family relationship edge used for succession workflows."""
    if person_id == related_person_id:
        return json.dumps({"error": "person_id and related_person_id must differ"})

    pool = await get_pool()
    try:
        sd = _parse_iso_date(start_date, "start_date")
        ed = _parse_iso_date(end_date, "end_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if sd and ed and ed < sd:
        return json.dumps({"error": "end_date cannot be before start_date"})

    row = await pool.fetchrow(
        """INSERT INTO person_relationships (
               person_id, related_person_id, relationship_type, start_date, end_date,
               jurisdiction_code, source_paperless_doc_id, notes
           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
           RETURNING *""",
        person_id,
        related_person_id,
        relationship_type.strip().lower(),
        sd,
        ed,
        jurisdiction_code,
        source_paperless_doc_id,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def set_entity_role(
    entity_id: int,
    role_type: str,
    holder_person_id: int | None = None,
    holder_entity_id: int | None = None,
    authority_scope: dict | str | None = None,
    effective_date: str | None = None,
    end_date: str | None = None,
    appointment_paperless_doc_id: int | None = None,
    removal_paperless_doc_id: int | None = None,
    notes: str | None = None,
) -> str:
    """Assign a fiduciary/governance role to a person or entity."""
    if not _exactly_one([holder_person_id, holder_entity_id]):
        return json.dumps({"error": "Provide exactly one of holder_person_id or holder_entity_id"})

    try:
        ed = _parse_iso_date(effective_date, "effective_date") or date.today()
        xd = _parse_iso_date(end_date, "end_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO entity_roles (
               entity_id, holder_person_id, holder_entity_id, role_type, authority_scope,
               effective_date, end_date, appointment_paperless_doc_id, removal_paperless_doc_id, notes
           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
           RETURNING *""",
        entity_id,
        holder_person_id,
        holder_entity_id,
        role_type.strip().lower(),
        json.dumps(_coerce_json_input(authority_scope)),
        ed,
        xd,
        appointment_paperless_doc_id,
        removal_paperless_doc_id,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def upsert_identifier(
    identifier_type: str,
    identifier_value: str,
    person_id: int | None = None,
    entity_id: int | None = None,
    asset_id: int | None = None,
    jurisdiction_code: str | None = None,
    issuing_authority: str | None = None,
    issue_date: str | None = None,
    expiry_date: str | None = None,
    status: str = "active",
    verification_paperless_doc_id: int | None = None,
    notes: str | None = None,
) -> str:
    """Create or update a typed statutory identifier for person/entity/asset."""
    if not _exactly_one([person_id, entity_id, asset_id]):
        return json.dumps({"error": "Provide exactly one of person_id, entity_id, or asset_id"})

    try:
        issue_dt = _parse_iso_date(issue_date, "issue_date")
        expiry_dt = _parse_iso_date(expiry_date, "expiry_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    normalized_type = _normalize_identifier_type(identifier_type)
    normalized_value = (identifier_value or "").strip()
    if not normalized_value:
        return json.dumps({"error": "identifier_value is required"})

    owner_column = "person_id"
    owner_id = person_id
    table_name = "person_identifiers"
    if entity_id is not None:
        owner_column = "entity_id"
        owner_id = entity_id
        table_name = "entity_identifiers"
    elif asset_id is not None:
        owner_column = "asset_id"
        owner_id = asset_id
        table_name = "asset_identifiers"

    pool = await get_pool()
    query = f"""
        INSERT INTO {table_name} (
            {owner_column}, identifier_type, identifier_value, jurisdiction_code,
            issuing_authority, issue_date, expiry_date, status,
            verification_paperless_doc_id, notes
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT ({owner_column}, identifier_type, identifier_value) DO UPDATE SET
            jurisdiction_code = COALESCE(EXCLUDED.jurisdiction_code, {table_name}.jurisdiction_code),
            issuing_authority = COALESCE(EXCLUDED.issuing_authority, {table_name}.issuing_authority),
            issue_date = COALESCE(EXCLUDED.issue_date, {table_name}.issue_date),
            expiry_date = COALESCE(EXCLUDED.expiry_date, {table_name}.expiry_date),
            status = EXCLUDED.status,
            verification_paperless_doc_id = COALESCE(EXCLUDED.verification_paperless_doc_id, {table_name}.verification_paperless_doc_id),
            notes = COALESCE(EXCLUDED.notes, {table_name}.notes),
            updated_at = now()
        RETURNING *
    """
    row = await pool.fetchrow(
        query,
        owner_id,
        normalized_type,
        normalized_value,
        jurisdiction_code,
        issuing_authority,
        issue_dt,
        expiry_dt,
        status.strip().lower(),
        verification_paperless_doc_id,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def set_beneficial_interest(
    interest_type: str,
    owner_person_id: int | None = None,
    owner_entity_id: int | None = None,
    subject_entity_id: int | None = None,
    subject_asset_id: int | None = None,
    direct_or_indirect: str = "unknown",
    beneficial_flag: bool = False,
    share_exact: float | None = None,
    share_min: float | None = None,
    share_max: float | None = None,
    assertion_source: str | None = None,
    ownership_path_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
) -> str:
    """Set rich ownership semantics (economic/control rights) for an ownership relationship."""
    if not _exactly_one([owner_person_id, owner_entity_id]):
        return json.dumps({"error": "Provide exactly one of owner_person_id or owner_entity_id"})
    if not _exactly_one([subject_entity_id, subject_asset_id]):
        return json.dumps({"error": "Provide exactly one of subject_entity_id or subject_asset_id"})

    doi = (direct_or_indirect or "").strip().lower()
    if doi not in {"direct", "indirect", "unknown"}:
        return json.dumps({"error": "direct_or_indirect must be one of: direct, indirect, unknown"})

    try:
        sd = _parse_iso_date(start_date, "start_date") or date.today()
        ed = _parse_iso_date(end_date, "end_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO beneficial_interests (
               ownership_path_id, owner_person_id, owner_entity_id, subject_entity_id, subject_asset_id,
               interest_type, direct_or_indirect, beneficial_flag,
               share_exact, share_min, share_max, assertion_source, start_date, end_date, notes
           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
           ON CONFLICT (ownership_path_id) WHERE ownership_path_id IS NOT NULL
           DO UPDATE SET
               owner_person_id = EXCLUDED.owner_person_id,
               owner_entity_id = EXCLUDED.owner_entity_id,
               subject_entity_id = EXCLUDED.subject_entity_id,
               subject_asset_id = EXCLUDED.subject_asset_id,
               interest_type = EXCLUDED.interest_type,
               direct_or_indirect = EXCLUDED.direct_or_indirect,
               beneficial_flag = EXCLUDED.beneficial_flag,
               share_exact = EXCLUDED.share_exact,
               share_min = EXCLUDED.share_min,
               share_max = EXCLUDED.share_max,
               assertion_source = COALESCE(EXCLUDED.assertion_source, beneficial_interests.assertion_source),
               start_date = EXCLUDED.start_date,
               end_date = EXCLUDED.end_date,
               notes = COALESCE(EXCLUDED.notes, beneficial_interests.notes),
               updated_at = now()
           RETURNING *""",
        ownership_path_id,
        owner_person_id,
        owner_entity_id,
        subject_entity_id,
        subject_asset_id,
        (interest_type or "").strip().lower(),
        doi,
        beneficial_flag,
        share_exact,
        share_min,
        share_max,
        assertion_source,
        sd,
        ed,
        notes,
    )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def upsert_succession_plan(
    name: str,
    governing_law_jurisdiction_code: str | None = None,
    grantor_person_id: int | None = None,
    sponsor_entity_id: int | None = None,
    primary_instrument_paperless_doc_id: int | None = None,
    status: str = "active",
    effective_date: str | None = None,
    termination_date: str | None = None,
    notes: str | None = None,
    succession_plan_id: int | None = None,
) -> str:
    """Create or update a succession plan."""
    pool = await get_pool()
    gl_jid = None
    if governing_law_jurisdiction_code:
        gl_jid = await pool.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            governing_law_jurisdiction_code,
        )
        if not gl_jid:
            return json.dumps({"error": f"Unknown governing_law_jurisdiction_code: {governing_law_jurisdiction_code}"})

    try:
        eff = _parse_iso_date(effective_date, "effective_date")
        term = _parse_iso_date(termination_date, "termination_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if succession_plan_id:
        row = await pool.fetchrow(
            """UPDATE succession_plans
               SET name=$1,
                   governing_law_jurisdiction_id=COALESCE($2, governing_law_jurisdiction_id),
                   grantor_person_id=COALESCE($3, grantor_person_id),
                   sponsor_entity_id=COALESCE($4, sponsor_entity_id),
                   primary_instrument_paperless_doc_id=COALESCE($5, primary_instrument_paperless_doc_id),
                   status=$6,
                   effective_date=COALESCE($7, effective_date),
                   termination_date=COALESCE($8, termination_date),
                   notes=COALESCE($9, notes),
                   updated_at=now()
               WHERE id=$10
               RETURNING *""",
            name,
            gl_jid,
            grantor_person_id,
            sponsor_entity_id,
            primary_instrument_paperless_doc_id,
            status.strip().lower(),
            eff,
            term,
            notes,
            succession_plan_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO succession_plans (
                   name, governing_law_jurisdiction_id, grantor_person_id, sponsor_entity_id,
                   primary_instrument_paperless_doc_id, status, effective_date, termination_date, notes
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               RETURNING *""",
            name,
            gl_jid,
            grantor_person_id,
            sponsor_entity_id,
            primary_instrument_paperless_doc_id,
            status.strip().lower(),
            eff,
            term,
            notes,
        )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def set_beneficiary_designation(
    succession_plan_id: int,
    beneficiary_person_id: int | None = None,
    beneficiary_entity_id: int | None = None,
    beneficiary_class: str = "primary",
    share_percentage: float | None = None,
    per_stirpes: bool = False,
    per_capita: bool = False,
    anti_lapse: bool = False,
    condition_json: dict | str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source_paperless_doc_id: int | None = None,
    notes: str | None = None,
    designation_id: int | None = None,
) -> str:
    """Create or update a beneficiary designation for a succession plan."""
    if not _exactly_one([beneficiary_person_id, beneficiary_entity_id]):
        return json.dumps({"error": "Provide exactly one of beneficiary_person_id or beneficiary_entity_id"})

    try:
        sd = _parse_iso_date(start_date, "start_date")
        ed = _parse_iso_date(end_date, "end_date")
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    pool = await get_pool()
    if designation_id:
        row = await pool.fetchrow(
            """UPDATE beneficiary_designations
               SET succession_plan_id=$1,
                   beneficiary_person_id=$2,
                   beneficiary_entity_id=$3,
                   beneficiary_class=$4,
                   share_percentage=$5,
                   per_stirpes=$6,
                   per_capita=$7,
                   anti_lapse=$8,
                   condition_json=$9,
                   start_date=$10,
                   end_date=$11,
                   source_paperless_doc_id=$12,
                   notes=$13,
                   updated_at=now()
               WHERE id=$14
               RETURNING *""",
            succession_plan_id,
            beneficiary_person_id,
            beneficiary_entity_id,
            beneficiary_class.strip().lower(),
            share_percentage,
            per_stirpes,
            per_capita,
            anti_lapse,
            json.dumps(_coerce_json_input(condition_json)),
            sd,
            ed,
            source_paperless_doc_id,
            notes,
            designation_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO beneficiary_designations (
                   succession_plan_id, beneficiary_person_id, beneficiary_entity_id,
                   beneficiary_class, share_percentage, per_stirpes, per_capita, anti_lapse,
                   condition_json, start_date, end_date, source_paperless_doc_id, notes
               ) VALUES (
                   $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
               )
               RETURNING *""",
            succession_plan_id,
            beneficiary_person_id,
            beneficiary_entity_id,
            beneficiary_class.strip().lower(),
            share_percentage,
            per_stirpes,
            per_capita,
            anti_lapse,
            json.dumps(_coerce_json_input(condition_json)),
            sd,
            ed,
            source_paperless_doc_id,
            notes,
        )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def upsert_compliance_obligation(
    title: str,
    obligation_type: str,
    recurrence: str = "annual",
    jurisdiction_code: str | None = None,
    entity_type_code: str | None = None,
    due_rule: str | None = None,
    grace_days: int = 0,
    penalty_notes: str | None = None,
    default_owner_person_id: int | None = None,
    active: bool = True,
    obligation_id: int | None = None,
) -> str:
    """Create or update a compliance obligation definition."""
    pool = await get_pool()
    jid = None
    if jurisdiction_code:
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
        if not jid:
            return json.dumps({"error": f"Unknown jurisdiction_code: {jurisdiction_code}"})

    entity_type_id = None
    if entity_type_code:
        entity_type_id = await pool.fetchval("SELECT id FROM entity_types WHERE code = $1", entity_type_code)
        if not entity_type_id:
            return json.dumps({"error": f"Unknown entity_type_code: {entity_type_code}"})

    if obligation_id:
        row = await pool.fetchrow(
            """UPDATE compliance_obligations
               SET title=$1,
                   obligation_type=$2,
                   jurisdiction_id=$3,
                   entity_type_id=$4,
                   recurrence=$5,
                   due_rule=$6,
                   grace_days=$7,
                   penalty_notes=$8,
                   default_owner_person_id=$9,
                   active=$10,
                   updated_at=now()
               WHERE id=$11
               RETURNING *""",
            title,
            obligation_type.strip().lower(),
            jid,
            entity_type_id,
            recurrence.strip().lower(),
            due_rule,
            grace_days,
            penalty_notes,
            default_owner_person_id,
            active,
            obligation_id,
        )
    else:
        row = await pool.fetchrow(
            """INSERT INTO compliance_obligations (
                   title, obligation_type, jurisdiction_id, entity_type_id,
                   recurrence, due_rule, grace_days, penalty_notes, default_owner_person_id, active
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               RETURNING *""",
            title,
            obligation_type.strip().lower(),
            jid,
            entity_type_id,
            recurrence.strip().lower(),
            due_rule,
            grace_days,
            penalty_notes,
            default_owner_person_id,
            active,
        )
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def update_compliance_instance_status(
    compliance_instance_id: int,
    status: str,
    assigned_to_person_id: int | None = None,
    rejection_reason: str | None = None,
    completion_notes: str | None = None,
) -> str:
    """Update lifecycle status for a compliance instance."""
    normalized_status = (status or "").strip().lower()
    valid_statuses = {"pending", "in_progress", "submitted", "accepted", "rejected", "waived"}
    if normalized_status not in valid_statuses:
        return json.dumps({"error": f"Invalid status: {status}", "valid_statuses": sorted(valid_statuses)})

    submitted_at = None
    accepted_at = None
    rejected_at = None
    if normalized_status == "submitted":
        submitted_at = datetime.utcnow()
    elif normalized_status == "accepted":
        accepted_at = datetime.utcnow()
    elif normalized_status == "rejected":
        rejected_at = datetime.utcnow()

    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE compliance_instances
           SET status=$1,
               assigned_to_person_id=COALESCE($2, assigned_to_person_id),
               rejection_reason=COALESCE($3, rejection_reason),
               completion_notes=COALESCE($4, completion_notes),
               submitted_at=COALESCE($5, submitted_at),
               accepted_at=COALESCE($6, accepted_at),
               rejected_at=COALESCE($7, rejected_at),
               updated_at=now()
           WHERE id=$8
           RETURNING *""",
        normalized_status,
        assigned_to_person_id,
        rejection_reason,
        completion_notes,
        submitted_at,
        accepted_at,
        rejected_at,
        compliance_instance_id,
    )
    if not row:
        return json.dumps({"error": f"Compliance instance {compliance_instance_id} not found"})
    return json.dumps(_row_to_dict(row))


@mcp.tool()
async def link_compliance_evidence(
    compliance_instance_id: int,
    evidence_type: str,
    paperless_doc_id: int | None = None,
    evidence_ref: str | None = None,
    status: str = "submitted",
    notes: str | None = None,
) -> str:
    """Attach filing evidence to a compliance instance."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO compliance_evidence (
               compliance_instance_id, paperless_doc_id, evidence_type, evidence_ref, status, notes
           ) VALUES ($1,$2,$3,$4,$5,$6)
           RETURNING *""",
        compliance_instance_id,
        paperless_doc_id,
        evidence_type.strip().lower(),
        evidence_ref,
        status.strip().lower(),
        notes,
    )
    return json.dumps(_row_to_dict(row))



if __name__ == "__main__":
    mcp.run()
