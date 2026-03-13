from datetime import date

from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    get_ownership_graph_query as _get_ownership_graph_query,
    parse_iso_date as _parse_iso_date,
)
from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool


def register_ownership_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def get_ownership_graph(person_id: int | None = None) -> list[dict]:
        """Get the full ownership hierarchy. If person_id given, shows transitive ownership.

        Args:
            person_id: Optional person ID to get transitive ownership for.
        """
        pool = await get_pool()
        rows = await _get_ownership_graph_query(pool, person_id=person_id)
        return _rows_to_list(rows)

    @_tool
    async def set_ownership(
        percentage: float,
        owner_person_id: int | None = None,
        owner_entity_id: int | None = None,
        owned_entity_id: int | None = None,
        owned_asset_id: int | None = None,
        units: float | None = None,
        effective_date: str | None = None,
        notes: str | None = None,
    ) -> dict:
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
        ed = _parse_iso_date(effective_date, "effective_date") or date.today()

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
        return {"id": row["id"]}
