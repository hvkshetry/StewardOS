"""Shared document primitives for finance and estate graph servers."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from stewardos_lib.db import row_to_dict as _row_to_dict
from stewardos_lib.domain_ops import parse_iso_date as _parse_iso_date


@dataclass(slots=True)
class NormalizedDocumentLink:
    paperless_doc_id: int
    purpose_type: str
    source_title: str | None
    jurisdiction_id: int | None
    effective_date: object | None
    expiry_date: object | None


async def normalize_document_link(
    *,
    pool: asyncpg.Pool,
    paperless_doc_id: int | None,
    title: str | None,
    doc_type: str | None,
    jurisdiction_code: str | None,
    effective_date: str | None,
    expiry_date: str | None,
    default_title: str | None,
) -> NormalizedDocumentLink:
    if paperless_doc_id is None:
        raise ValueError("paperless_doc_id is required")

    jurisdiction_id = None
    if jurisdiction_code:
        jurisdiction_id = await pool.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            jurisdiction_code,
        )
        if not jurisdiction_id:
            raise ValueError(f"Unknown jurisdiction_code: {jurisdiction_code}")

    return NormalizedDocumentLink(
        paperless_doc_id=int(paperless_doc_id),
        purpose_type=(doc_type or "other").strip().lower(),
        source_title=(title or "").strip() or default_title,
        jurisdiction_id=jurisdiction_id,
        effective_date=_parse_iso_date(effective_date, "effective_date"),
        expiry_date=_parse_iso_date(expiry_date, "expiry_date"),
    )


async def upsert_document_row(
    conn: asyncpg.Connection,
    *,
    title: str | None,
    doc_type: str,
    paperless_doc_id: int,
    vaultwarden_item_id: str | None,
    entity_id: int | None,
    asset_id: int | None,
    person_id: int | None,
    jurisdiction_id: int | None,
    effective_date,
    expiry_date,
    notes: str | None,
    use_conflict_upsert: bool,
) -> dict:
    if use_conflict_upsert:
        row = await conn.fetchrow(
            """INSERT INTO documents (
                   title, doc_type, paperless_doc_id, vaultwarden_item_id,
                   entity_id, asset_id, person_id, jurisdiction_id, effective_date, expiry_date, notes
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (paperless_doc_id) DO UPDATE SET
                   title = COALESCE(EXCLUDED.title, documents.title),
                   doc_type = COALESCE(EXCLUDED.doc_type, documents.doc_type),
                   vaultwarden_item_id = COALESCE(EXCLUDED.vaultwarden_item_id, documents.vaultwarden_item_id),
                   entity_id = COALESCE(EXCLUDED.entity_id, documents.entity_id),
                   asset_id = COALESCE(EXCLUDED.asset_id, documents.asset_id),
                   person_id = COALESCE(EXCLUDED.person_id, documents.person_id),
                   jurisdiction_id = COALESCE(EXCLUDED.jurisdiction_id, documents.jurisdiction_id),
                   effective_date = COALESCE(EXCLUDED.effective_date, documents.effective_date),
                   expiry_date = COALESCE(EXCLUDED.expiry_date, documents.expiry_date),
                   notes = COALESCE(EXCLUDED.notes, documents.notes),
                   updated_at = now()
               RETURNING id, title, paperless_doc_id""",
            title,
            doc_type,
            paperless_doc_id,
            vaultwarden_item_id,
            entity_id,
            asset_id,
            person_id,
            jurisdiction_id,
            effective_date,
            expiry_date,
            notes,
        )
        return _row_to_dict(row) or {}

    existing = await conn.fetchrow(
        "SELECT id FROM documents WHERE paperless_doc_id = $1",
        paperless_doc_id,
    )
    if existing is not None:
        row = await conn.fetchrow(
            """UPDATE documents
               SET title = COALESCE($1, title),
                   doc_type = COALESCE($2, doc_type),
                   vaultwarden_item_id = COALESCE($3, vaultwarden_item_id),
                   entity_id = COALESCE($4, entity_id),
                   asset_id = COALESCE($5, asset_id),
                   person_id = COALESCE($6, person_id),
                   jurisdiction_id = COALESCE($7, jurisdiction_id),
                   effective_date = COALESCE($8, effective_date),
                   expiry_date = COALESCE($9, expiry_date),
                   notes = COALESCE($10, notes),
                   updated_at = now()
               WHERE id = $11
               RETURNING id, title, paperless_doc_id""",
            title,
            doc_type,
            vaultwarden_item_id,
            entity_id,
            asset_id,
            person_id,
            jurisdiction_id,
            effective_date,
            expiry_date,
            notes,
            existing["id"],
        )
    else:
        row = await conn.fetchrow(
            """INSERT INTO documents (
                   title, doc_type, paperless_doc_id, vaultwarden_item_id,
                   entity_id, asset_id, person_id, jurisdiction_id,
                   effective_date, expiry_date, notes
               ) VALUES (
                   $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
               )
               RETURNING id, title, paperless_doc_id""",
            title,
            doc_type,
            paperless_doc_id,
            vaultwarden_item_id,
            entity_id,
            asset_id,
            person_id,
            jurisdiction_id,
            effective_date,
            expiry_date,
            notes,
        )
    return _row_to_dict(row) or {}


async def upsert_document_metadata_row(
    conn: asyncpg.Connection,
    *,
    paperless_doc_id: int,
    entity_id: int | None,
    asset_id: int | None,
    person_id: int | None,
    jurisdiction_id: int | None,
    doc_purpose_type: str,
    effective_date,
    expiry_date,
    source_snapshot_title: str | None,
    source_snapshot_doc_type: str | None,
    notes: str | None,
    status: str = "active",
) -> dict:
    row = await conn.fetchrow(
        """INSERT INTO document_metadata (
               paperless_doc_id, entity_id, asset_id, person_id, jurisdiction_id,
               doc_purpose_type, effective_date, expiry_date, source_snapshot_title,
               source_snapshot_doc_type, notes, status
           ) VALUES (
               $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12
           )
           ON CONFLICT (paperless_doc_id) DO UPDATE SET
               entity_id = COALESCE(EXCLUDED.entity_id, document_metadata.entity_id),
               asset_id = COALESCE(EXCLUDED.asset_id, document_metadata.asset_id),
               person_id = COALESCE(EXCLUDED.person_id, document_metadata.person_id),
               jurisdiction_id = COALESCE(EXCLUDED.jurisdiction_id, document_metadata.jurisdiction_id),
               doc_purpose_type = COALESCE(EXCLUDED.doc_purpose_type, document_metadata.doc_purpose_type),
               effective_date = COALESCE(EXCLUDED.effective_date, document_metadata.effective_date),
               expiry_date = COALESCE(EXCLUDED.expiry_date, document_metadata.expiry_date),
               source_snapshot_title = COALESCE(EXCLUDED.source_snapshot_title, document_metadata.source_snapshot_title),
               source_snapshot_doc_type = COALESCE(EXCLUDED.source_snapshot_doc_type, document_metadata.source_snapshot_doc_type),
               notes = COALESCE(EXCLUDED.notes, document_metadata.notes),
               status = COALESCE(EXCLUDED.status, document_metadata.status),
               updated_at = now()
           RETURNING *""",
        paperless_doc_id,
        entity_id,
        asset_id,
        person_id,
        jurisdiction_id,
        doc_purpose_type,
        effective_date,
        expiry_date,
        source_snapshot_title,
        source_snapshot_doc_type,
        notes,
        status,
    )
    return _row_to_dict(row) or {}
