from __future__ import annotations

import os

import httpx
from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool

from helpers import (
    _finish_run,
    _first_nonempty,
    _parse_date,
    _row_to_dict,
    _rows_to_dicts,
    _start_run,
    _to_json,
)

PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://localhost:8223")
PAPERLESS_API_TOKEN = os.environ.get("PAPERLESS_API_TOKEN", "")
PAPERLESS_MEDICAL_TAGS = tuple(
    tag.strip().lower()
    for tag in os.environ.get(
        "PAPERLESS_MEDICAL_TAGS",
        "medical,insurance,lab-results,prescription,referral",
    ).split(",")
    if tag.strip()
)
_MEDICAL_KEYWORDS = tuple(
    keyword.strip().lower()
    for keyword in os.environ.get(
        "PAPERLESS_MEDICAL_KEYWORDS",
        "medical,insurance,lab,prescription,referral,doctor,clinic,hospital,pharmacy",
    ).split(",")
    if keyword.strip()
)


def _headers_paperless() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Token {PAPERLESS_API_TOKEN}",
    }


async def _get_medical_tag_ids(client: httpx.AsyncClient) -> list[int]:
    resp = await client.get("/api/tags/", params={"page_size": 1000})
    resp.raise_for_status()
    data = resp.json()
    tags = data.get("results", []) if isinstance(data, dict) else []
    ids = []
    for tag in tags:
        if isinstance(tag, dict) and str(tag.get("name", "")).lower() in PAPERLESS_MEDICAL_TAGS:
            try:
                ids.append(int(tag["id"]))
            except Exception:  # noqa: BLE001
                continue
    return ids


def _doc_matches_medical_heuristics(doc: dict) -> bool:
    title = str(doc.get("title") or "").lower()
    doc_type = str(doc.get("document_type_name") or doc.get("document_type") or "").lower()
    candidate = " ".join([title, doc_type])
    return any(keyword in candidate for keyword in _MEDICAL_KEYWORDS)


async def _fetch_medical_documents(
    client: httpx.AsyncClient,
    *,
    limit: int,
    tag_ids: list[int],
) -> tuple[list[dict], int | None, bool]:
    params = {
        "page_size": max(1, min(limit, 1000)),
        "ordering": "-created",
    }
    if tag_ids:
        params["tags__id__in"] = ",".join(str(t) for t in tag_ids)

    results: list[dict] = []
    next_url: str | None = "/api/documents/"
    total_count: int | None = None
    truncated = False
    first_page = True

    while next_url and len(results) < limit:
        resp = await client.get(next_url, params=params if first_page else None)
        first_page = False
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            break
        if total_count is None and data.get("count") is not None:
            try:
                total_count = int(data["count"])
            except (TypeError, ValueError):
                total_count = None
        batch = data.get("results", []) if isinstance(data.get("results"), list) else []
        if not tag_ids:
            batch = [doc for doc in batch if isinstance(doc, dict) and _doc_matches_medical_heuristics(doc)]
        remaining = limit - len(results)
        results.extend(doc for doc in batch[:remaining] if isinstance(doc, dict))
        next_url = data.get("next") if isinstance(data.get("next"), str) and data.get("next") else None
        if len(results) >= limit and next_url:
            truncated = True

    return results[:limit], total_count, truncated


def register_paperless_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def sync_paperless_medical_metadata(limit: int = 200) -> dict:
        """Sync medical-tagged Paperless document metadata into health graph."""
        await ensure_initialized()
        if not PAPERLESS_API_TOKEN:
            return _error_response("PAPERLESS_API_TOKEN not configured", code="configuration_error")

        pool = await get_pool()
        rows_written = 0
        rows_read = 0

        async with httpx.AsyncClient(base_url=PAPERLESS_URL, headers=_headers_paperless(), timeout=60.0) as client:
            tag_ids = await _get_medical_tag_ids(client)
            results, total_count, truncated = await _fetch_medical_documents(
                client,
                limit=max(1, min(limit, 1000)),
                tag_ids=tag_ids,
            )

        async with pool.acquire() as conn:
            run_id = await _start_run(conn, source_name="paperless", run_type="paperless_metadata_sync")
            try:
                async with conn.transaction():
                    for doc in results:
                        rows_read += 1
                        pid = doc.get("id")
                        if pid is None:
                            continue

                        await conn.execute(
                            """INSERT INTO document_metadata (
                                   paperless_doc_id, title, doc_type, created_date, source_snapshot
                               ) VALUES ($1,$2,$3,$4,$5::jsonb)
                               ON CONFLICT (paperless_doc_id)
                               DO UPDATE SET title = COALESCE(EXCLUDED.title, document_metadata.title),
                                             doc_type = COALESCE(EXCLUDED.doc_type, document_metadata.doc_type),
                                             created_date = COALESCE(EXCLUDED.created_date, document_metadata.created_date),
                                             source_snapshot = EXCLUDED.source_snapshot,
                                             updated_at = NOW()""",
                            int(pid),
                            _first_nonempty(doc.get("title")),
                            str(doc.get("document_type_name") or doc.get("document_type"))
                            if doc.get("document_type_name") is not None or doc.get("document_type") is not None
                            else None,
                            _parse_date(doc.get("created")),
                            _to_json(doc),
                        )
                        rows_written += 1

                await _finish_run(conn, run_id, "success", rows_read, rows_written)
                return {
                    "ingestion_run_id": run_id,
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "tag_ids_used": tag_ids,
                    "rows_available": total_count,
                    "truncated": truncated,
                    "used_fallback_heuristics": not bool(tag_ids),
                }
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", rows_read, rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="sync_error",
                    payload={
                        "ingestion_run_id": run_id,
                        "rows_read": rows_read,
                        "rows_written": rows_written,
                    },
                )

    @_tool
    async def get_document_linkage(paperless_doc_id: int) -> dict:
        """Get metadata and linkages for a paperless document."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            doc = await conn.fetchrow(
                "SELECT * FROM document_metadata WHERE paperless_doc_id = $1",
                paperless_doc_id,
            )
            links = await conn.fetch(
                "SELECT * FROM document_links WHERE paperless_doc_id = $1 ORDER BY id",
                paperless_doc_id,
            )

        return {
            "document": _row_to_dict(doc),
            "links": _rows_to_dicts(links),
        }
