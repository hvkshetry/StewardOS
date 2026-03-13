from datetime import date

from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    get_ownership_graph_query as _get_ownership_graph_query,
    parse_iso_date as _parse_iso_date,
)
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
)


def _exactly_one(values: list[object]) -> bool:
    return sum(v is not None for v in values) == 1


def register_ownership_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def get_ownership_graph(person_id: int | None = None):
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
    ):
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
        try:
            ed = _parse_iso_date(effective_date, "effective_date") or date.today()
        except ValueError as exc:
            return _error_response(str(exc))

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
        return {
            "id": row["id"],
            "beneficial_interest_id": interest_row["id"] if interest_row else None,
        }

    @_tool
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
    ):
        """Set rich ownership semantics (economic/control rights) for an ownership relationship."""
        if not _exactly_one([owner_person_id, owner_entity_id]):
            return _error_response("Provide exactly one of owner_person_id or owner_entity_id")
        if not _exactly_one([subject_entity_id, subject_asset_id]):
            return _error_response("Provide exactly one of subject_entity_id or subject_asset_id")

        doi = (direct_or_indirect or "").strip().lower()
        if doi not in {"direct", "indirect", "unknown"}:
            return _error_response("direct_or_indirect must be one of: direct, indirect, unknown")

        try:
            sd = _parse_iso_date(start_date, "start_date") or date.today()
            ed = _parse_iso_date(end_date, "end_date")
        except ValueError as exc:
            return _error_response(str(exc))

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
        return _row_to_dict(row)
