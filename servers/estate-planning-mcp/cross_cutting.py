from stewardos_lib.db import rows_to_dicts as _rows_to_list
from stewardos_lib.response_ops import (
    error_response as _error_response,
)
from stewardos_lib.response_ops import (
    make_enveloped_tool as _make_enveloped_tool,
)
from stewardos_lib.response_ops import (
    ok_response as _ok_response,
)

_LEGAL_TITLE_OWNERSHIP_BASIS = "legal_title"
_OWNERSHIP_BASIS_NOTE = (
    "Current net-worth rollups use assets.owner_* as legal-title ownership plus "
    "transitive entity lookthrough. Beneficial-interests are not yet included."
)


def _validate_ownership_basis(ownership_basis: str) -> str | None:
    basis = (ownership_basis or "").strip().lower()
    if basis == _LEGAL_TITLE_OWNERSHIP_BASIS:
        return None
    return (
        f"Unsupported ownership_basis '{ownership_basis}'. "
        f"Only '{_LEGAL_TITLE_OWNERSHIP_BASIS}' is currently supported."
    )


def _attach_ownership_basis(rows: list[dict], ownership_basis: str) -> list[dict]:
    return [{**row, "ownership_basis": ownership_basis} for row in rows]


def register_cross_cutting_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def get_net_worth(
        person_id: int | None = None,
        jurisdiction: str | None = None,
        ownership_basis: str = _LEGAL_TITLE_OWNERSHIP_BASIS,
    ) -> dict:
        """Get net worth summary, optionally filtered by person or jurisdiction.

        Args:
            person_id: Filter to assets owned by this person (direct + through entities).
            jurisdiction: Filter by jurisdiction code.
            ownership_basis: Ownership basis for the roll-up. Only ``legal_title`` is
                currently supported; this makes current title-based semantics explicit.
        """
        ownership_basis_error = _validate_ownership_basis(ownership_basis)
        if ownership_basis_error:
            return _error_response(
                ownership_basis_error,
                code="unsupported_ownership_basis",
                provenance={
                    "ownership_basis": ownership_basis,
                    "ownership_basis_note": _OWNERSHIP_BASIS_NOTE,
                },
            )
        pool = await get_pool()
        if person_id:
            rows = await pool.fetch(
                """WITH person_entities AS (
                    SELECT entity_id, effective_pct
                    FROM get_transitive_ownership($1)
                   )
                   SELECT j.code AS jurisdiction, vo.value_currency AS currency,
                          SUM(vo.value_amount) AS direct_value,
                          0::numeric AS indirect_value
                   FROM assets a
                   JOIN finance.valuation_observations vo ON vo.asset_id = a.id AND vo.is_current = true
                   LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
                   WHERE a.owner_person_id = $1
                   GROUP BY j.code, vo.value_currency
                   UNION ALL
                   SELECT j.code, vo.value_currency,
                          0::numeric,
                          SUM(vo.value_amount * pe.effective_pct / 100)
                   FROM assets a
                   JOIN finance.valuation_observations vo ON vo.asset_id = a.id AND vo.is_current = true
                   JOIN person_entities pe ON a.owner_entity_id = pe.entity_id
                   LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
                   GROUP BY j.code, vo.value_currency""",
                person_id,
            )
        elif jurisdiction:
            rows = await pool.fetch(
                """SELECT j.code AS jurisdiction_code, j.name AS jurisdiction_name, j.country,
                          vo.value_currency AS currency,
                          SUM(vo.value_amount) AS total_value, COUNT(*) AS asset_count
                   FROM assets a
                   JOIN finance.valuation_observations vo ON vo.asset_id = a.id AND vo.is_current = true
                   JOIN jurisdictions j ON a.jurisdiction_id = j.id
                   WHERE j.code = $1
                   GROUP BY j.code, j.name, j.country, vo.value_currency""",
                jurisdiction,
            )
        else:
            rows = await pool.fetch(
                """SELECT j.code AS jurisdiction_code, j.name AS jurisdiction_name, j.country,
                          vo.value_currency AS currency,
                          SUM(vo.value_amount) AS total_value, COUNT(*) AS asset_count
                   FROM assets a
                   JOIN finance.valuation_observations vo ON vo.asset_id = a.id AND vo.is_current = true
                   JOIN jurisdictions j ON a.jurisdiction_id = j.id
                   GROUP BY j.code, j.name, j.country, vo.value_currency"""
            )
        return _ok_response(
            _attach_ownership_basis(_rows_to_list(rows), ownership_basis),
            provenance={
                "ownership_basis": ownership_basis,
                "ownership_basis_note": _OWNERSHIP_BASIS_NOTE,
            },
        )

    @_tool
    async def get_upcoming_dates(days: int = 30) -> dict:
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
        return _ok_response(_rows_to_list(rows))
