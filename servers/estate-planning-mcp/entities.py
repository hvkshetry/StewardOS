import json
from datetime import date

from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import list_entities_query as _list_entities_query, parse_iso_date as _parse_iso_date
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
)


def _exactly_one(values: list[object]) -> bool:
    return sum(v is not None for v in values) == 1


def register_entities_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_entities(
        entity_type: str | None = None,
        jurisdiction: str | None = None,
        status: str | None = None,
    ):
        """List entities (trusts, LLCs, corps, HUFs) with optional filters.

        Args:
            entity_type: Filter by entity_type code (e.g. LLC, REVOCABLE_TRUST).
            jurisdiction: Filter by jurisdiction code (e.g. US-DE, IN-KA).
            status: Filter by status (active, dissolved, pending).
        """
        pool = await get_pool()
        rows = await _list_entities_query(
            pool,
            entity_type=entity_type,
            jurisdiction=jurisdiction,
            status=status,
        )
        return _rows_to_list(rows)

    @_tool
    async def get_entity(entity_id: int):
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
            return _error_response(f"Entity {entity_id} not found")

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
        return result

    @_tool
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
    ):
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
        try:
            fd = _parse_iso_date(formation_date, "formation_date")
        except ValueError as exc:
            return _error_response(str(exc))

        et = await pool.fetchval("SELECT id FROM entity_types WHERE code = $1", entity_type_code)
        if not et:
            return _error_response(f"Unknown entity_type_code: {entity_type_code}")
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
        if not jid:
            return _error_response(f"Unknown jurisdiction_code: {jurisdiction_code}")
        governing_law_jid = None
        if governing_law_jurisdiction_code:
            governing_law_jid = await pool.fetchval(
                "SELECT id FROM jurisdictions WHERE code = $1",
                governing_law_jurisdiction_code,
            )
            if not governing_law_jid:
                return _error_response(
                    f"Unknown governing_law_jurisdiction_code: {governing_law_jurisdiction_code}"
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
        return _row_to_dict(row)

    @_tool
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
    ):
        """Assign a fiduciary/governance role to a person or entity."""
        if not _exactly_one([holder_person_id, holder_entity_id]):
            return _error_response("Provide exactly one of holder_person_id or holder_entity_id")

        try:
            ed = _parse_iso_date(effective_date, "effective_date") or date.today()
            xd = _parse_iso_date(end_date, "end_date")
        except ValueError as exc:
            return _error_response(str(exc))

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
        return _row_to_dict(row)

    @_tool
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
    ):
        """Create or update a typed statutory identifier for person/entity/asset."""
        if not _exactly_one([person_id, entity_id, asset_id]):
            return _error_response("Provide exactly one of person_id, entity_id, or asset_id")

        from stewardos_lib.domain_ops import normalize_identifier_type as _normalize_identifier_type

        try:
            issue_dt = _parse_iso_date(issue_date, "issue_date")
            expiry_dt = _parse_iso_date(expiry_date, "expiry_date")
        except ValueError as exc:
            return _error_response(str(exc))

        normalized_type = _normalize_identifier_type(identifier_type)
        normalized_value = (identifier_value or "").strip()
        if not normalized_value:
            return _error_response("identifier_value is required")

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
        return _row_to_dict(row)
