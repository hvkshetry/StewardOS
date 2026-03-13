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
        subject_id: int | None = None,
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
                resolved_subject_id = subject_id
                if subject_id is not None:
                    existing_subject = await conn.fetchrow("SELECT * FROM subjects WHERE id = $1", subject_id)
                    if existing_subject is None:
                        return _error_response(f"subject_id {subject_id} not found", code="not_found")

                matched_subject_ids: set[int] = set()
                for identifier in identifier_rows:
                    match = await conn.fetchrow(
                        """SELECT subject_id
                           FROM subject_identifiers
                           WHERE upper(btrim(id_type)) = $1
                             AND btrim(id_value) = $2
                           LIMIT 1""",
                        identifier["id_type"],
                        identifier["id_value"],
                    )
                    if match is not None:
                        matched_subject_ids.add(int(match["subject_id"]))

                if resolved_subject_id is not None and matched_subject_ids and matched_subject_ids != {resolved_subject_id}:
                    return _error_response(
                        "Provided identifiers resolve to a different subject_id",
                        code="validation_error",
                    )
                if resolved_subject_id is None:
                    if len(matched_subject_ids) > 1:
                        return _error_response(
                            "Provided identifiers resolve to multiple subjects",
                            code="validation_error",
                        )
                    if len(matched_subject_ids) == 1:
                        resolved_subject_id = next(iter(matched_subject_ids))

                status = "created"
                if resolved_subject_id is None:
                    row = await conn.fetchrow(
                        """INSERT INTO subjects (display_name, date_of_birth, sex_at_birth, metadata)
                           VALUES ($1, $2, $3, $4::jsonb)
                           RETURNING *""",
                        display_name,
                        dob_value,
                        sex_at_birth or None,
                        _to_json(meta),
                    )
                else:
                    status = "updated"
                    row = await conn.fetchrow(
                        """UPDATE subjects
                           SET display_name = COALESCE($2, display_name),
                               date_of_birth = COALESCE($3, date_of_birth),
                               sex_at_birth = COALESCE($4, sex_at_birth),
                               metadata = metadata || $5::jsonb,
                               updated_at = NOW()
                           WHERE id = $1
                           RETURNING *""",
                        resolved_subject_id,
                        display_name or None,
                        dob_value,
                        sex_at_birth or None,
                        _to_json(meta),
                    )

                assert row is not None
                resolved_subject_id = int(row["id"])
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
                        if int(existing_identifier["subject_id"]) != resolved_subject_id:
                            return _error_response(
                                (
                                    f"Identifier {identifier['id_type']}:{identifier['id_value']} already belongs to "
                                    f"subject_id {existing_identifier['subject_id']}"
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
                            """INSERT INTO subject_identifiers (subject_id, id_type, id_value, source_name)
                               VALUES ($1, $2, $3, $4)
                               RETURNING *""",
                            resolved_subject_id,
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
            rows = await conn.fetch("SELECT * FROM subjects ORDER BY id")
        return _ok_response(_rows_to_dicts(rows))

    @mcp.tool()
    async def link_subject_identifier(
        subject_id: int,
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
                subject_exists = await conn.fetchval("SELECT 1 FROM subjects WHERE id = $1", subject_id)
                if not subject_exists:
                    return _error_response(f"subject_id {subject_id} not found", code="not_found")

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
                    if int(existing["subject_id"]) != subject_id:
                        return _error_response(
                            (
                                f"Identifier {normalized_type}:{normalized_value} already belongs to "
                                f"subject_id {existing['subject_id']}"
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
                        """INSERT INTO subject_identifiers (subject_id, id_type, id_value, source_name)
                           VALUES ($1, $2, $3, $4)
                           RETURNING *""",
                        subject_id,
                        normalized_type,
                        normalized_value,
                        source_name or None,
                    )
        return _ok_response(_row_to_dict(row) or {})
