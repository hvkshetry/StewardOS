"""Shared domain operations for estate-planning and finance-graph servers.

All functions accept an asyncpg.Pool and return raw asyncpg.Record(s).
Callers are responsible for serialization (via db.row_to_dict).
"""

import json
import re
from datetime import date

import asyncpg

from stewardos_lib.constants import ISO_CURRENCY_RE

# ── Currency / date helpers ───────────────────────────────────────────────


def normalize_currency_code(code: str | None) -> str | None:
    if not isinstance(code, str):
        return None
    normalized = code.strip().upper()
    if not ISO_CURRENCY_RE.fullmatch(normalized):
        return None
    return normalized


def parse_iso_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def resolve_exact_one_owner(
    *,
    owner_entity_id: int | None,
    owner_person_id: int | None,
    existing_owner_entity_id: int | None = None,
    existing_owner_person_id: int | None = None,
    is_create: bool,
) -> tuple[int | None, int | None]:
    """Return normalized owner fields while enforcing exact-one ownership."""

    entity_provided = owner_entity_id is not None
    person_provided = owner_person_id is not None

    if is_create:
        if entity_provided == person_provided:
            raise ValueError("Provide exactly one of owner_entity_id or owner_person_id")
        return owner_entity_id, owner_person_id

    if entity_provided and person_provided:
        raise ValueError("Provide at most one of owner_entity_id or owner_person_id when updating an asset")

    if entity_provided:
        return owner_entity_id, None
    if person_provided:
        return None, owner_person_id

    if existing_owner_entity_id is None and existing_owner_person_id is None:
        raise ValueError("Existing asset has no owner; provide exactly one of owner_entity_id or owner_person_id")
    return existing_owner_entity_id, existing_owner_person_id


def normalize_identifier_type(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "_")


# ── Valuation ─────────────────────────────────────────────────────────────


async def insert_valuation_observation(
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

    normalized_currency = normalize_currency_code(value_currency)
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


# ── Entity listing ────────────────────────────────────────────────────────


async def list_entities_query(
    pool: asyncpg.Pool,
    entity_type: str | None = None,
    jurisdiction: str | None = None,
    status: str | None = None,
) -> list[asyncpg.Record]:
    query = """
        SELECT e.id, e.name, et.code AS entity_type, et.name AS entity_type_name,
               j.code AS jurisdiction, e.status, e.formation_date, e.tax_id
        FROM entities e
        JOIN entity_types et ON e.entity_type_id = et.id
        JOIN jurisdictions j ON e.jurisdiction_id = j.id
        WHERE 1=1
    """
    params: list = []
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
    return await pool.fetch(query, *params)


# ── People listing ────────────────────────────────────────────────────────


async def list_people_query(
    pool: asyncpg.Pool,
) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT id, legal_name, preferred_name, citizenship, residency_status, "
        "death_date, incapacity_status FROM people ORDER BY legal_name"
    )


# ── Ownership graph ───────────────────────────────────────────────────────


async def get_ownership_graph_query(
    pool: asyncpg.Pool,
    person_id: int | None = None,
) -> list[asyncpg.Record]:
    if person_id:
        return await pool.fetch(
            "SELECT * FROM get_transitive_ownership($1)", person_id
        )
    return await pool.fetch(
        "SELECT * FROM v_ownership_summary ORDER BY owner_name, owned_name"
    )
