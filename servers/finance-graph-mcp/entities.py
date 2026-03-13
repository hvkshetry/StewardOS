from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import list_entities_query as _list_entities_query, parse_iso_date as _parse_iso_date
from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool


def register_entities_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_entities(
        entity_type: str | None = None,
        jurisdiction: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
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
    async def get_entity(entity_id: int) -> dict:
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
            return _error_response(f"Entity {entity_id} not found", code="not_found")

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
        return result

    @_tool
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
    ) -> dict:
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
        fd = _parse_iso_date(formation_date, "formation_date")

        et = await pool.fetchval("SELECT id FROM entity_types WHERE code = $1", entity_type_code)
        if not et:
            return _error_response(f"Unknown entity_type_code: {entity_type_code}", code="validation_error")
        jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
        if not jid:
            return _error_response(f"Unknown jurisdiction_code: {jurisdiction_code}", code="validation_error")

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
        return _row_to_dict(row)
