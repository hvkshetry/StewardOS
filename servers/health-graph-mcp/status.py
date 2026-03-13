from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from helpers import (
    _row_to_dict,
    _rows_to_dicts,
    _start_run,
    _finish_run,
    _validate_source_name,
)
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
    ok_response as _ok_response,
)

OPEN_TARGETS_GRAPHQL_ENDPOINT = os.environ.get(
    "OPEN_TARGETS_GRAPHQL_ENDPOINT", "https://api.platform.opentargets.org/api/v4/graphql"
)


async def _open_targets_query(query: str, variables: dict | None = None) -> dict:
    payload = {
        "query": query,
        "variables": variables or {},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(OPEN_TARGETS_GRAPHQL_ENDPOINT, json=payload)
        resp.raise_for_status()
        return resp.json()


def register_status_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def refresh_source(source_name: str, search_term: str = "") -> dict:
        """Refresh a source. For opentargets, run direct GraphQL fetch and store metadata run records."""
        await ensure_initialized()

        try:
            _validate_source_name(source_name)
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        pool = await get_pool()

        source = source_name.strip().lower()
        async with pool.acquire() as conn:
            run_id = await _start_run(conn, source_name=source, run_type="source_refresh")
            try:
                if source == "opentargets":
                    query = """
                    query searchEntity($queryString: String!) {
                      search(queryString: $queryString) {
                        total
                        hits { id entity description }
                      }
                    }
                    """
                    data = await _open_targets_query(query, {"queryString": search_term or "CYP2C19"})
                    rows_read = int((data.get("data") or {}).get("search", {}).get("total") or 0)
                    await _finish_run(conn, run_id, "success", rows_read, 1)
                    return _ok_response(
                        {
                        "source": source,
                        "ingestion_run_id": run_id,
                        "rows_read": rows_read,
                        "result": data.get("data"),
                        "mode": "direct_graphql_runtime",
                        }
                    )

                await _finish_run(conn, run_id, "success", 0, 0)
                return _ok_response(
                    {
                    "source": source,
                    "ingestion_run_id": run_id,
                    "message": "No-op refresh for unsupported source",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", 0, 0, str(exc))
                return _error_response(
                    str(exc),
                    code="refresh_failed",
                    payload={"source": source, "ingestion_run_id": run_id},
                )

    @_tool
    async def health_graph_status() -> dict:
        """Return ingestion and data freshness status."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            latest_runs = await conn.fetch(
                """SELECT *
                   FROM ingestion_runs
                   ORDER BY started_at DESC
                   LIMIT 25"""
            )
            counts = await conn.fetchrow(
                """SELECT
                       (SELECT COUNT(*) FROM subjects) AS subjects,
                       (SELECT COUNT(*) FROM callsets) AS callsets,
                       (SELECT COUNT(*) FROM genotype_calls) AS genotype_calls,
                       (SELECT COUNT(*) FROM clinical_assertions) AS clinical_assertions,
                       (SELECT COUNT(*) FROM pgx_recommendations) AS pgx_recommendations,
                       (SELECT COUNT(*) FROM observations) AS observations,
                       (SELECT COUNT(*) FROM coverages) AS coverages,
                       (SELECT COUNT(*) FROM coverage_determinations) AS coverage_determinations,
                       (SELECT COUNT(*) FROM document_metadata) AS document_metadata,
                       (SELECT COUNT(*) FROM literature_evidence) AS literature_evidence
                """
            )

        return _ok_response(
            {
            "open_targets_mode": "direct_graphql_runtime",
            "counts": _row_to_dict(counts),
            "latest_runs": _rows_to_dicts(latest_runs),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            }
        )
