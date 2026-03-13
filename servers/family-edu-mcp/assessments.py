"""Assessment summary and report card history tools."""

from typing import Any

from helpers import _row_to_dict, _rows_to_dicts


def register_assessment_tools(mcp, get_pool):

    @mcp.tool()
    async def get_assessment_summary(
        learner_id: int,
        assessment_definition_code: str = "",
        limit: int = 25,
    ) -> dict:
        """Summarize assessment history and latest outcomes for a learner."""
        pool = await get_pool()

        sql = (
            "SELECT ad.code, ad.name, ad.subject_area, ad.measure_type, ad.unit, "
            "ae.id AS assessment_event_id, ae.assessed_on, ae.term_id, ae.staff_contact_id, "
            "ar.result_numeric, ar.result_text, ar.result_boolean, ar.percentile, "
            "ar.proficiency_band, ar.normalized_score "
            "FROM assessment_events ae "
            "JOIN assessment_definitions ad ON ad.id = ae.assessment_definition_id "
            "LEFT JOIN assessment_results ar ON ar.assessment_event_id = ae.id "
            "WHERE ae.learner_id = $1"
        )
        params: list[Any] = [learner_id]

        if assessment_definition_code:
            params.append(assessment_definition_code)
            sql += f" AND ad.code = ${len(params)}"

        params.append(max(1, min(limit, 200)))
        sql += f" ORDER BY ae.assessed_on DESC, ae.id DESC LIMIT ${len(params)}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        results = _rows_to_dicts(rows)
        by_definition: dict[str, dict] = {}
        for row in results:
            code = row["code"]
            entry = by_definition.setdefault(
                code,
                {
                    "code": code,
                    "name": row["name"],
                    "subject_area": row["subject_area"],
                    "measure_type": row["measure_type"],
                    "count": 0,
                    "latest_assessed_on": row["assessed_on"],
                    "latest_result": None,
                    "numeric_values": [],
                },
            )
            entry["count"] += 1
            if entry["latest_result"] is None:
                entry["latest_result"] = {
                    "result_numeric": row["result_numeric"],
                    "result_text": row["result_text"],
                    "result_boolean": row["result_boolean"],
                    "percentile": row["percentile"],
                    "normalized_score": row["normalized_score"],
                }
            if row["result_numeric"] is not None:
                entry["numeric_values"].append(row["result_numeric"])

        for entry in by_definition.values():
            values = entry.pop("numeric_values")
            if values:
                entry["numeric_avg"] = round(sum(values) / len(values), 4)
                entry["numeric_min"] = min(values)
                entry["numeric_max"] = max(values)

        return {
            "learner_id": learner_id,
            "recent_results": results,
            "by_definition": list(by_definition.values()),
        }

    @mcp.tool()
    async def get_report_card_history(learner_id: int, subject: str = "") -> list[dict]:
        """Return structured report-card facts over time."""
        pool = await get_pool()

        sql = (
            "SELECT rcf.*, t.label AS term_label "
            "FROM report_card_facts rcf "
            "LEFT JOIN terms t ON t.id = rcf.term_id "
            "WHERE rcf.learner_id = $1"
        )
        params: list[Any] = [learner_id]

        if subject:
            params.append(subject)
            sql += f" AND rcf.subject = ${len(params)}"

        sql += " ORDER BY COALESCE(rcf.issued_on, DATE '1900-01-01') DESC, rcf.id DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return _rows_to_dicts(rows)
