"""Metric observation and narrative observation tools."""

import json
from typing import Any

from helpers import (
    _fetch_learner_or_none,
    _normalize_date,
    _normalize_datetime,
    _opt_id,
    _row_to_dict,
    _rows_to_dicts,
    _title_from_code,
)


def register_metric_tools(mcp, get_pool):

    @mcp.tool()
    async def get_activity_performance_summary(
        learner_id: int,
        activity_code: str = "",
        metric_code: str = "",
        days: int = 180,
    ) -> dict:
        """Summarize metric observations for activities/program performance."""
        pool = await get_pool()

        sql = (
            "SELECT mo.*, md.code AS metric_code, md.name AS metric_name, md.unit, md.polarity, md.measure_type, "
            "ad.code AS activity_code, ad.name AS activity_name "
            "FROM metric_observations mo "
            "JOIN metric_definitions md ON md.id = mo.metric_definition_id "
            "LEFT JOIN activity_definitions ad ON ad.id = md.activity_definition_id "
            "WHERE mo.learner_id = $1 AND mo.observed_at >= NOW() - ($2::int || ' days')::interval"
        )
        params: list[Any] = [learner_id, max(1, days)]

        if activity_code:
            params.append(activity_code)
            sql += f" AND ad.code = ${len(params)}"

        if metric_code:
            params.append(metric_code)
            sql += f" AND md.code = ${len(params)}"

        sql += " ORDER BY mo.observed_at DESC, mo.id DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        observations = _rows_to_dicts(rows)
        metrics: dict[str, dict] = {}

        for obs in observations:
            key = f"{obs['activity_code']}::{obs['metric_code']}"
            bucket = metrics.setdefault(
                key,
                {
                    "activity_code": obs["activity_code"],
                    "activity_name": obs["activity_name"],
                    "metric_code": obs["metric_code"],
                    "metric_name": obs["metric_name"],
                    "unit": obs["unit"],
                    "polarity": obs["polarity"],
                    "measure_type": obs["measure_type"],
                    "count": 0,
                    "latest": None,
                    "numeric_values": [],
                },
            )
            bucket["count"] += 1
            if bucket["latest"] is None:
                bucket["latest"] = {
                    "observed_at": obs["observed_at"],
                    "value_numeric": obs["value_numeric"],
                    "value_text": obs["value_text"],
                    "value_boolean": obs["value_boolean"],
                    "context": obs["context"],
                }
            if obs["value_numeric"] is not None:
                bucket["numeric_values"].append(obs["value_numeric"])

        for bucket in metrics.values():
            values = bucket.pop("numeric_values")
            if values:
                bucket["numeric_avg"] = round(sum(values) / len(values), 4)
                bucket["numeric_min"] = min(values)
                bucket["numeric_max"] = max(values)

        return {
            "learner_id": learner_id,
            "window_days": days,
            "metric_summaries": list(metrics.values()),
            "recent_observations": observations[:50],
        }

    @mcp.tool()
    async def record_metric_observation(
        learner_id: int,
        activity_code: str,
        metric_code: str,
        value_numeric: float | None = None,
        value_text: str = "",
        value_boolean: bool | None = None,
        observed_at: str = "",
        unit: str = "",
        polarity: str = "higher_is_better",
        measure_type: str = "numeric",
        context: dict | None = None,
        source_artifact_id: int = 0,
        recorded_by: str = "",
    ) -> dict:
        """Record a generic time-series performance observation."""
        if context is None:
            context = {}

        if polarity not in {"higher_is_better", "lower_is_better", "neutral"}:
            return {"error": "polarity must be one of: higher_is_better, lower_is_better, neutral"}

        if observed_at:
            try:
                observed_at = _normalize_datetime(observed_at, "observed_at")
            except ValueError as exc:
                return {"error": str(exc)}

        pool = await get_pool()

        async with pool.acquire() as conn:
            learner = await _fetch_learner_or_none(conn, learner_id)
            if learner is None:
                return {"error": f"Learner {learner_id} not found."}

            activity_row = await conn.fetchrow(
                "INSERT INTO activity_definitions (code, name, activity_type) "
                "VALUES ($1, $2, 'general') ON CONFLICT (code) DO UPDATE SET name = activity_definitions.name "
                "RETURNING id, code, name",
                activity_code,
                _title_from_code(activity_code),
            )
            assert activity_row is not None
            activity_id = int(activity_row["id"])

            metric_row = await conn.fetchrow(
                "INSERT INTO metric_definitions (activity_definition_id, code, name, unit, polarity, measure_type) "
                "VALUES ($1, $2, $3, NULLIF($4, ''), $5, $6) "
                "ON CONFLICT (activity_definition_id, code) DO UPDATE SET "
                "unit = COALESCE(metric_definitions.unit, EXCLUDED.unit), "
                "polarity = metric_definitions.polarity, "
                "measure_type = metric_definitions.measure_type "
                "RETURNING id, code, name",
                activity_id,
                metric_code,
                _title_from_code(metric_code),
                unit,
                polarity,
                measure_type,
            )
            assert metric_row is not None

            obs_row = await conn.fetchrow(
                "INSERT INTO metric_observations ("
                "learner_id, metric_definition_id, observed_at, value_numeric, value_text, value_boolean, "
                "context, source_artifact_id, recorded_by"
                ") VALUES ("
                "$1, $2, COALESCE(NULLIF($3, '')::timestamptz, NOW()), $4, NULLIF($5, ''), $6, $7::jsonb, $8, NULLIF($9, '')"
                ") RETURNING *",
                learner_id,
                int(metric_row["id"]),
                observed_at,
                value_numeric,
                value_text,
                value_boolean,
                json.dumps(context, ensure_ascii=False),
                _opt_id(source_artifact_id),
                recorded_by,
            )

        observation = _row_to_dict(obs_row)
        assert observation is not None
        observation["activity_code"] = activity_code
        observation["metric_code"] = metric_code
        return observation

    @mcp.tool()
    async def record_observation(
        learner_id: int,
        observation_text: str,
        domain: str = "",
        observed_on: str = "",
        source: str = "manual",
        source_artifact_id: int = 0,
        recorded_by: str = "",
    ) -> dict:
        """Record a narrative developmental/academic observation."""
        if observed_on:
            try:
                observed_on = _normalize_date(observed_on, "observed_on")
            except ValueError as exc:
                return {"error": str(exc)}

        pool = await get_pool()

        async with pool.acquire() as conn:
            learner = await _fetch_learner_or_none(conn, learner_id)
            if learner is None:
                return {"error": f"Learner {learner_id} not found."}

            row = await conn.fetchrow(
                "INSERT INTO observations ("
                "learner_id, observed_on, domain, source, observation_text, source_artifact_id, recorded_by"
                ") VALUES ("
                "$1, COALESCE(NULLIF($2, '')::date, CURRENT_DATE), NULLIF($3, ''), NULLIF($4, ''), $5, $6, NULLIF($7, '')"
                ") RETURNING *",
                learner_id,
                observed_on,
                domain,
                source,
                observation_text,
                _opt_id(source_artifact_id),
                recorded_by,
            )

        observation = _row_to_dict(row)
        assert observation is not None
        return observation
