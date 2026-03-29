from __future__ import annotations

from typing import Any

from helpers import (
    _read_json_input,
    _row_to_dict,
    _rows_to_dicts,
    _to_json,
)
from stewardos_lib.domain_ops import parse_iso_date as _parse_iso_date
from stewardos_lib.response_ops import error_response as _error_response, ok_response as _ok_response


def _normalize_identifier_inputs(identifiers: list[dict] | str | None) -> tuple[list[dict], str | None]:
    if identifiers in (None, "", []):
        return [], None

    payload = _read_json_input(identifiers)
    if not isinstance(payload, list):
        return [], "identifiers must be a list of objects"

    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in payload:
        if not isinstance(item, dict):
            return [], "identifiers must be a list of objects"
        id_type = str(item.get("id_type") or item.get("type") or "").strip().upper()
        id_value = str(item.get("id_value") or item.get("value") or "").strip()
        if not id_type or not id_value:
            return [], "Each identifier requires non-empty id_type and id_value"
        key = (id_type, id_value)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "id_type": id_type,
                "id_value": id_value,
                "source_name": str(item.get("source_name") or "").strip() or None,
            }
        )
    return normalized, None


def register_subject_tools(mcp, get_pool, ensure_initialized):

    @mcp.tool()
    async def upsert_subject(
        display_name: str,
        date_of_birth: str = "",
        sex_at_birth: str = "",
        metadata: dict | str | None = None,
        person_id: int | None = None,
        identifiers: list[dict] | str | None = None,
    ) -> dict:
        """Create or update a subject using explicit identity keys."""
        await ensure_initialized()
        pool = await get_pool()
        try:
            dob_value = _parse_iso_date(date_of_birth, "date_of_birth")
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")
        meta = _read_json_input(metadata or {})
        identifier_rows, error = _normalize_identifier_inputs(identifiers)
        if error:
            return _error_response(error, code="validation_error")

        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_person_id = person_id
                if person_id is not None:
                    existing_person = await conn.fetchrow("SELECT * FROM people WHERE id = $1", person_id)
                    if existing_person is None:
                        return _error_response(f"person_id {person_id} not found", code="not_found")

                matched_person_ids: set[int] = set()
                for identifier in identifier_rows:
                    match = await conn.fetchrow(
                        """SELECT person_id
                           FROM subject_identifiers
                           WHERE upper(btrim(id_type)) = $1
                             AND btrim(id_value) = $2
                           LIMIT 1""",
                        identifier["id_type"],
                        identifier["id_value"],
                    )
                    if match is not None:
                        matched_person_ids.add(int(match["person_id"]))

                if resolved_person_id is not None and matched_person_ids and matched_person_ids != {resolved_person_id}:
                    return _error_response(
                        "Provided identifiers resolve to a different person_id",
                        code="validation_error",
                    )
                if resolved_person_id is None:
                    if len(matched_person_ids) > 1:
                        return _error_response(
                            "Provided identifiers resolve to multiple people",
                            code="validation_error",
                        )
                    if len(matched_person_ids) == 1:
                        resolved_person_id = next(iter(matched_person_ids))

                status = "created"
                if resolved_person_id is None:
                    # Insert into core.people (via search_path) + health.subject_profiles
                    row = await conn.fetchrow(
                        """INSERT INTO people (legal_name, preferred_name, date_of_birth)
                           VALUES ($1, $2, $3)
                           RETURNING *""",
                        display_name,
                        display_name,
                        dob_value,
                    )
                    assert row is not None
                    resolved_person_id = int(row["id"])
                    await conn.execute(
                        """INSERT INTO health.subject_profiles (person_id, sex_at_birth, metadata)
                           VALUES ($1, $2, $3::jsonb)
                           ON CONFLICT (person_id) DO UPDATE SET
                               sex_at_birth = COALESCE(EXCLUDED.sex_at_birth, health.subject_profiles.sex_at_birth),
                               metadata = health.subject_profiles.metadata || EXCLUDED.metadata,
                               updated_at = NOW()""",
                        resolved_person_id,
                        sex_at_birth or None,
                        _to_json(meta),
                    )
                else:
                    status = "updated"
                    # Per plan: only update subject_profiles, NOT core.people
                    # (canonical person data is owned by finance/estate)
                    await conn.execute(
                        """INSERT INTO health.subject_profiles (person_id, sex_at_birth, metadata)
                           VALUES ($1, $2, $3::jsonb)
                           ON CONFLICT (person_id) DO UPDATE SET
                               sex_at_birth = COALESCE(EXCLUDED.sex_at_birth, health.subject_profiles.sex_at_birth),
                               metadata = health.subject_profiles.metadata || EXCLUDED.metadata,
                               updated_at = NOW()""",
                        resolved_person_id,
                        sex_at_birth or None,
                        _to_json(meta),
                    )
                    row = await conn.fetchrow(
                        "SELECT * FROM people WHERE id = $1",
                        resolved_person_id,
                    )

                assert row is not None
                resolved_person_id = int(row["id"])
                linked_identifiers: list[dict] = []
                for identifier in identifier_rows:
                    existing_identifier = await conn.fetchrow(
                        """SELECT *
                           FROM subject_identifiers
                           WHERE upper(btrim(id_type)) = $1
                             AND btrim(id_value) = $2
                           LIMIT 1""",
                        identifier["id_type"],
                        identifier["id_value"],
                    )
                    if existing_identifier is not None:
                        if int(existing_identifier["person_id"]) != resolved_person_id:
                            return _error_response(
                                (
                                    f"Identifier {identifier['id_type']}:{identifier['id_value']} already belongs to "
                                    f"person_id {existing_identifier['person_id']}"
                                ),
                                code="conflict",
                            )
                        identifier_row = await conn.fetchrow(
                            """UPDATE subject_identifiers
                               SET source_name = COALESCE($2, source_name)
                               WHERE id = $1
                               RETURNING *""",
                            existing_identifier["id"],
                            identifier["source_name"],
                        )
                    else:
                        identifier_row = await conn.fetchrow(
                            """INSERT INTO subject_identifiers (person_id, id_type, id_value, source_name)
                               VALUES ($1, $2, $3, $4)
                               RETURNING *""",
                            resolved_person_id,
                            identifier["id_type"],
                            identifier["id_value"],
                            identifier["source_name"],
                        )
                    linked_identifiers.append(_row_to_dict(identifier_row) or {})

                payload = _row_to_dict(row) or {}
                payload["operation_status"] = status
                if linked_identifiers:
                    payload["identifiers"] = linked_identifiers
                return _ok_response(payload)

    @mcp.tool()
    async def list_subjects() -> dict:
        """List subjects."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM people ORDER BY id")
        return _ok_response(_rows_to_dicts(rows))

    @mcp.tool()
    async def link_subject_identifier(
        person_id: int,
        id_type: str,
        id_value: str,
        source_name: str = "",
    ) -> dict:
        """Attach external identifier to a subject."""
        await ensure_initialized()
        pool = await get_pool()
        normalized_type = str(id_type or "").strip().upper()
        normalized_value = str(id_value or "").strip()
        if not normalized_type or not normalized_value:
            return _error_response("id_type and id_value are required", code="validation_error")
        async with pool.acquire() as conn:
            async with conn.transaction():
                person_exists = await conn.fetchval("SELECT 1 FROM people WHERE id = $1", person_id)
                if not person_exists:
                    return _error_response(f"person_id {person_id} not found", code="not_found")

                existing = await conn.fetchrow(
                    """SELECT *
                       FROM subject_identifiers
                       WHERE upper(btrim(id_type)) = $1
                         AND btrim(id_value) = $2
                       LIMIT 1""",
                    normalized_type,
                    normalized_value,
                )
                if existing is not None:
                    if int(existing["person_id"]) != person_id:
                        return _error_response(
                            (
                                f"Identifier {normalized_type}:{normalized_value} already belongs to "
                                f"person_id {existing['person_id']}"
                            ),
                            code="conflict",
                        )
                    row = await conn.fetchrow(
                        """UPDATE subject_identifiers
                           SET source_name = COALESCE($2, source_name)
                           WHERE id = $1
                           RETURNING *""",
                        existing["id"],
                        source_name or None,
                    )
                else:
                    row = await conn.fetchrow(
                        """INSERT INTO subject_identifiers (person_id, id_type, id_value, source_name)
                           VALUES ($1, $2, $3, $4)
                           RETURNING *""",
                        person_id,
                        normalized_type,
                        normalized_value,
                        source_name or None,
                    )
        return _ok_response(_row_to_dict(row) or {})
