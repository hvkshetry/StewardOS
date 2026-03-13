from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from helpers import _rows_to_dicts
from stewardos_lib.response_ops import make_enveloped_tool as _make_enveloped_tool


def register_lab_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def query_labs(
        subject_id: int,
        code: str = "",
        since_date: str = "",
        limit: int = 200,
    ) -> list[dict]:
        """Query lab observations for a subject."""
        await ensure_initialized()
        pool = await get_pool()

        clauses = ["subject_id = $1"]
        params: list[Any] = [subject_id]
        idx = 2
        if code:
            clauses.append(f"code = ${idx}")
            params.append(code)
            idx += 1
        if since_date:
            clauses.append(f"effective_at >= ${idx}")
            params.append(datetime.strptime(since_date, "%Y-%m-%d"))
            idx += 1

        params.append(max(1, min(limit, 2000)))
        query = (
            "SELECT * FROM observations "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY effective_at DESC NULLS LAST, id DESC LIMIT $" + str(idx)
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return _rows_to_dicts(rows)

    @_tool
    async def get_lab_trends(subject_id: int, code: str, days: int = 365) -> dict:
        """Summarize lab trends for a code over a time window."""
        await ensure_initialized()
        pool = await get_pool()
        since_dt = datetime.utcnow() - timedelta(days=max(1, days))

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT value_numeric, effective_at
                   FROM observations
                   WHERE subject_id=$1
                     AND code=$2
                     AND value_numeric IS NOT NULL
                     AND effective_at >= $3
                   ORDER BY effective_at""",
                subject_id,
                code,
                since_dt,
            )

        series = [float(r["value_numeric"]) for r in rows if r["value_numeric"] is not None]
        if not series:
            return {
                "subject_id": subject_id,
                "code": code,
                "days": days,
                "count": 0,
                "trend": "no_data",
            }

        trend = "stable"
        if len(series) >= 2:
            if series[-1] > series[0]:
                trend = "increasing"
            elif series[-1] < series[0]:
                trend = "decreasing"

        return {
            "subject_id": subject_id,
            "code": code,
            "days": days,
            "count": len(series),
            "first": series[0],
            "latest": series[-1],
            "min": min(series),
            "max": max(series),
            "trend": trend,
        }
