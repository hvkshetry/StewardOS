from stewardos_lib.db import rows_to_dicts as _rows_to_list
from stewardos_lib.graph_documents import (
    normalize_document_link as _normalize_document_link,
)
from stewardos_lib.graph_documents import (
    upsert_document_metadata_row as _upsert_document_metadata_row,
)
from stewardos_lib.graph_documents import (
    upsert_document_row as _upsert_document_row,
)
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
        """Get net worth roll-up including liabilities.

        Args:
            person_id: Optional legacy person id filter (uses party_refs.metadata.legacy_person_id mapping).
            jurisdiction: Optional jurisdiction code filter.
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
        if person_id is not None:
            person_params: list = [person_id]
            asset_jurisdiction_clause = ""
            liability_jurisdiction_clause = ""
            if jurisdiction:
                person_params.append(jurisdiction)
                asset_jurisdiction_clause = " AND av.jurisdiction = $2"
                liability_jurisdiction_clause = " AND j.code = $2"

            asset_rows = await pool.fetch(
                f"""WITH person_entities AS (
                           SELECT entity_id, effective_pct
                           FROM get_transitive_ownership($1)
                       ), asset_values AS (
                           SELECT a.owner_person_id,
                                  a.owner_entity_id,
                                  j.code AS jurisdiction,
                                  cvo.value_currency AS currency,
                                  cvo.value_amount AS current_value
                           FROM assets a
                           LEFT JOIN valuation_observations cvo ON cvo.id = a.current_valuation_observation_id
                           LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
                       )
                       SELECT av.jurisdiction AS jurisdiction,
                              av.currency AS currency,
                              SUM(av.current_value)::numeric AS direct_asset_value,
                              0::numeric AS lookthrough_asset_value
                       FROM asset_values av
                       WHERE av.current_value IS NOT NULL
                         AND av.owner_person_id = $1
                         {asset_jurisdiction_clause}
                       GROUP BY av.jurisdiction, av.currency
                       UNION ALL
                       SELECT av.jurisdiction AS jurisdiction,
                              av.currency AS currency,
                              0::numeric AS direct_asset_value,
                              SUM(av.current_value * pe.effective_pct / 100.0)::numeric AS lookthrough_asset_value
                       FROM asset_values av
                       JOIN person_entities pe ON av.owner_entity_id = pe.entity_id
                       WHERE av.current_value IS NOT NULL
                         {asset_jurisdiction_clause}
                       GROUP BY av.jurisdiction, av.currency""",
                *person_params,
            )
            liability_rows = await pool.fetch(
                f"""WITH person_entities AS (
                           SELECT entity_id, effective_pct
                           FROM get_transitive_ownership($1)
                       )
                       SELECT j.code AS jurisdiction,
                              l.currency AS currency,
                              SUM(l.outstanding_principal)::numeric AS direct_liability_value,
                              0::numeric AS lookthrough_liability_value
                       FROM liabilities l
                       JOIN party_refs pr ON pr.party_uuid = l.primary_borrower_uuid
                       LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
                       WHERE l.status = 'active'
                         AND l.outstanding_principal IS NOT NULL
                         AND pr.party_type = 'person'
                         AND COALESCE(pr.metadata->>'legacy_person_id', '') = $1::text
                         {liability_jurisdiction_clause}
                       GROUP BY j.code, l.currency
                       UNION ALL
                       SELECT j.code AS jurisdiction,
                              l.currency AS currency,
                              0::numeric AS direct_liability_value,
                              SUM(l.outstanding_principal * pe.effective_pct / 100.0)::numeric AS lookthrough_liability_value
                       FROM liabilities l
                       JOIN party_refs pr ON pr.party_uuid = l.primary_borrower_uuid
                       JOIN person_entities pe ON COALESCE(pr.metadata->>'legacy_entity_id', '') = pe.entity_id::text
                       LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
                       WHERE l.status = 'active'
                         AND l.outstanding_principal IS NOT NULL
                         AND pr.party_type = 'entity'
                         {liability_jurisdiction_clause}
                       GROUP BY j.code, l.currency""",
                *person_params,
            )
        else:
            where_assets = "WHERE av.current_value IS NOT NULL"
            where_liabs = "WHERE l.status = 'active' AND l.outstanding_principal IS NOT NULL"
            params: list = []
            if jurisdiction:
                where_assets += " AND av.jurisdiction = $1"
                where_liabs += " AND j.code = $1"
                params.append(jurisdiction)

            asset_rows = await pool.fetch(
                f"""WITH asset_values AS (
                           SELECT j.code AS jurisdiction,
                                  cvo.value_currency AS currency,
                                  cvo.value_amount AS current_value
                           FROM assets a
                           LEFT JOIN valuation_observations cvo ON cvo.id = a.current_valuation_observation_id
                           LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
                       )
                    SELECT av.jurisdiction AS jurisdiction,
                           av.currency AS currency,
                           SUM(av.current_value)::numeric AS asset_value
                    FROM asset_values av
                    {where_assets}
                    GROUP BY av.jurisdiction, av.currency""",
                *params,
            )
            liability_rows = await pool.fetch(
                f"""SELECT j.code AS jurisdiction,
                           l.currency AS currency,
                           SUM(l.outstanding_principal)::numeric AS liability_value
                    FROM liabilities l
                    LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
                    {where_liabs}
                    GROUP BY j.code, l.currency""",
                *params,
            )

        rollup: dict[tuple[str | None, str | None], dict] = {}
        for row in asset_rows:
            key = (row["jurisdiction"], row["currency"])
            if key not in rollup:
                rollup[key] = {
                    "jurisdiction": row["jurisdiction"],
                    "currency": row["currency"],
                    "asset_value": 0.0,
                    "liability_value": 0.0,
                    "net_worth_after_liabilities": 0.0,
                }
                if person_id is not None:
                    rollup[key]["direct_asset_value"] = 0.0
                    rollup[key]["lookthrough_asset_value"] = 0.0
                    rollup[key]["direct_liability_value"] = 0.0
                    rollup[key]["lookthrough_liability_value"] = 0.0

            if person_id is not None:
                direct_asset_value = float(row["direct_asset_value"] or 0)
                lookthrough_asset_value = float(row["lookthrough_asset_value"] or 0)
                rollup[key]["direct_asset_value"] += direct_asset_value
                rollup[key]["lookthrough_asset_value"] += lookthrough_asset_value
                rollup[key]["asset_value"] = (
                    float(rollup[key]["direct_asset_value"]) + float(rollup[key]["lookthrough_asset_value"])
                )
            else:
                asset_value = float(row["asset_value"] or 0)
                rollup[key]["asset_value"] += asset_value
            rollup[key]["net_worth_after_liabilities"] = (
                float(rollup[key]["asset_value"]) - float(rollup[key]["liability_value"])
            )

        for row in liability_rows:
            key = (row["jurisdiction"], row["currency"])
            if key not in rollup:
                rollup[key] = {
                    "jurisdiction": row["jurisdiction"],
                    "currency": row["currency"],
                    "asset_value": 0.0,
                    "liability_value": 0.0,
                    "net_worth_after_liabilities": 0.0,
                }
                if person_id is not None:
                    rollup[key]["direct_asset_value"] = 0.0
                    rollup[key]["lookthrough_asset_value"] = 0.0
                    rollup[key]["direct_liability_value"] = 0.0
                    rollup[key]["lookthrough_liability_value"] = 0.0
            if person_id is not None:
                direct_liability_value = float(row["direct_liability_value"] or 0)
                lookthrough_liability_value = float(row["lookthrough_liability_value"] or 0)
                rollup[key]["direct_liability_value"] += direct_liability_value
                rollup[key]["lookthrough_liability_value"] += lookthrough_liability_value
                rollup[key]["liability_value"] = (
                    float(rollup[key]["direct_liability_value"]) + float(rollup[key]["lookthrough_liability_value"])
                )
            else:
                rollup[key]["liability_value"] += float(row["liability_value"] or 0)
            rollup[key]["net_worth_after_liabilities"] = (
                float(rollup[key]["asset_value"]) - float(rollup[key]["liability_value"])
            )

        return _ok_response(
            _attach_ownership_basis(list(rollup.values()), ownership_basis),
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
        return _ok_response(_rows_to_list(rows))

    @_tool
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
    ) -> dict:
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
        try:
            normalized = await _normalize_document_link(
                pool=pool,
                paperless_doc_id=paperless_doc_id,
                title=title,
                doc_type=doc_type,
                jurisdiction_code=jurisdiction_code,
                effective_date=effective_date,
                expiry_date=expiry_date,
                default_title=f"Paperless {paperless_doc_id}" if paperless_doc_id is not None else None,
            )
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        async with pool.acquire() as conn:
            async with conn.transaction():
                payload = await _upsert_document_row(
                    conn,
                    title=normalized.source_title,
                    doc_type=normalized.purpose_type,
                    paperless_doc_id=normalized.paperless_doc_id,
                    vaultwarden_item_id=vaultwarden_item_id,
                    entity_id=entity_id,
                    asset_id=asset_id,
                    person_id=person_id,
                    jurisdiction_id=normalized.jurisdiction_id,
                    effective_date=normalized.effective_date,
                    expiry_date=normalized.expiry_date,
                    notes=notes,
                    use_conflict_upsert=True,
                )
                metadata = await _upsert_document_metadata_row(
                    conn,
                    paperless_doc_id=normalized.paperless_doc_id,
                    entity_id=entity_id,
                    asset_id=asset_id,
                    person_id=person_id,
                    jurisdiction_id=normalized.jurisdiction_id,
                    doc_purpose_type=normalized.purpose_type,
                    effective_date=normalized.effective_date,
                    expiry_date=normalized.expiry_date,
                    source_snapshot_title=normalized.source_title,
                    source_snapshot_doc_type=normalized.purpose_type,
                    notes=notes,
                )

        payload["paperless_doc_id"] = normalized.paperless_doc_id
        payload["doc_metadata"] = metadata
        return _ok_response(payload)
