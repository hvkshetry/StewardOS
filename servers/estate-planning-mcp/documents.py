import json
from datetime import datetime

import asyncpg

from stewardos_lib.db import row_to_dict as _row_to_dict
from stewardos_lib.graph_documents import (
    normalize_document_link as _normalize_document_link,
    upsert_document_metadata_row as _upsert_document_metadata_row,
    upsert_document_row as _upsert_document_row,
)
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
    ok_response as _ok_response,
)
from stewardos_lib.domain_ops import parse_iso_date as _parse_iso_date


async def _ensure_document_metadata_exists(pool: asyncpg.Pool, paperless_doc_id: int) -> None:
    await pool.execute(
        """INSERT INTO document_metadata (paperless_doc_id, doc_purpose_type)
           VALUES ($1, 'other')
           ON CONFLICT (paperless_doc_id) DO NOTHING""",
        paperless_doc_id,
    )


def register_documents_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
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
    ) -> dict:
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
                default_title=None,
            )
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        async with pool.acquire() as conn:
            async with conn.transaction():
                payload = await _upsert_document_row(
                    conn,
                    title=normalized.source_title or f"Paperless {normalized.paperless_doc_id}",
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
                    use_conflict_upsert=False,
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

    @_tool
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
    ) -> dict:
        """Create or update estate-only metadata for a Paperless document."""
        pool = await get_pool()
        try:
            normalized = await _normalize_document_link(
                pool=pool,
                paperless_doc_id=paperless_doc_id,
                title=source_snapshot_title,
                doc_type=doc_purpose_type,
                jurisdiction_code=jurisdiction_code,
                effective_date=effective_date,
                expiry_date=expiry_date,
                default_title=None,
            )
            lr = _parse_iso_date(last_reviewed, "last_reviewed")
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        async with pool.acquire() as conn:
            payload = await _upsert_document_metadata_row(
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
                source_snapshot_doc_type=(source_snapshot_doc_type or "").strip() or None,
                notes=notes,
                status=status.strip().lower(),
            )
            if lr is not None:
                row = await conn.fetchrow(
                    """UPDATE document_metadata
                       SET last_reviewed = $2,
                           updated_at = now()
                       WHERE paperless_doc_id = $1
                       RETURNING *""",
                    normalized.paperless_doc_id,
                    lr,
                )
                payload = _row_to_dict(row) or payload
        return _ok_response(payload)

    @_tool
    async def set_document_version_link(
        paperless_doc_id: int,
        supersedes_paperless_doc_id: int,
        version_reason: str | None = None,
        asserted_by: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Record that one Paperless document supersedes another."""
        if paperless_doc_id == supersedes_paperless_doc_id:
            return _error_response(
                "paperless_doc_id and supersedes_paperless_doc_id must differ",
                code="validation_error",
            )

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
            return _error_response(
                "version link would create a cycle",
                code="validation_error",
                payload={
                    "paperless_doc_id": paperless_doc_id,
                    "supersedes_paperless_doc_id": supersedes_paperless_doc_id,
                },
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
        return _ok_response(_row_to_dict(row) or {})

    @_tool
    async def add_document_participant(
        paperless_doc_id: int,
        person_id: int,
        role: str,
        signed_at: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Add a person-role participant for a Paperless document (signatory/witness/notary/etc.)."""
        pool = await get_pool()
        await _ensure_document_metadata_exists(pool, paperless_doc_id)
        signed_dt = None
        if signed_at:
            try:
                signed_dt = datetime.fromisoformat(signed_at)
            except ValueError:
                return _error_response(
                    f"Invalid signed_at: {signed_at}. Use ISO datetime format.",
                    code="validation_error",
                )

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
        return _ok_response(_row_to_dict(row) or {})

    @_tool
    async def add_document_assertion(
        paperless_doc_id: int,
        assertion_type: str,
        asserted_value_json: dict | str | None = None,
        source_system: str = "estate-planning",
        source_record_id: str | None = None,
        confidence: float | None = None,
        asserted_at: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Record a source-backed assertion on a Paperless document."""
        pool = await get_pool()
        await _ensure_document_metadata_exists(pool, paperless_doc_id)

        assertion_dt = None
        if asserted_at:
            try:
                assertion_dt = datetime.fromisoformat(asserted_at)
            except ValueError:
                return _error_response(
                    f"Invalid asserted_at: {asserted_at}. Use ISO datetime format.",
                    code="validation_error",
                )

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
        return _ok_response(_row_to_dict(row) or {})

    @_tool
    async def upsert_document_review_policy(
        paperless_doc_id: int,
        review_cadence: str = "annual",
        next_review_date: str | None = None,
        renewal_window_days: int = 30,
        owner_person_id: int | None = None,
        policy_status: str = "active",
        notes: str | None = None,
    ) -> dict:
        """Set review cadence and renewal policy for a Paperless document."""
        pool = await get_pool()
        await _ensure_document_metadata_exists(pool, paperless_doc_id)

        try:
            nrd = _parse_iso_date(next_review_date, "next_review_date")
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

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
        return _ok_response(_row_to_dict(row) or {})
