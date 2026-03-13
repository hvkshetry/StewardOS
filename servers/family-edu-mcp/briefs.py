"""Term brief generation tool."""

from typing import Any

from helpers import (
    _child_age_months,
    _fetch_learner_or_none,
    _opt_id,
    _row_to_dict,
    _rows_to_dicts,
)


def register_brief_tools(mcp, get_pool):

    @mcp.tool()
    async def generate_term_brief(
        learner_id: int,
        term_id: int = 0,
        term_label: str = "",
    ) -> dict:
        """Generate a structured term brief with provenance context."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            learner = await _fetch_learner_or_none(conn, learner_id)
            if learner is None:
                return {"error": f"Learner {learner_id} not found."}

            resolved_term_id = _opt_id(term_id)
            resolved_term = None
            if resolved_term_id is None and term_label:
                resolved_term = await conn.fetchrow("SELECT * FROM terms WHERE label = $1 ORDER BY id DESC LIMIT 1", term_label)
                if resolved_term is not None:
                    resolved_term_id = int(resolved_term["id"])
            elif resolved_term_id is not None:
                resolved_term = await conn.fetchrow("SELECT * FROM terms WHERE id = $1", resolved_term_id)

            artifact_where = "WHERE learner_id = $1"
            artifact_params: list[Any] = [learner_id]
            if resolved_term_id is not None:
                artifact_params.append(resolved_term_id)
                artifact_where += f" AND term_id = ${len(artifact_params)}"

            artifact_stats = await conn.fetch(
                f"SELECT artifact_type, review_status, COUNT(*) AS count FROM artifacts {artifact_where} "
                "GROUP BY artifact_type, review_status ORDER BY artifact_type, review_status",
                *artifact_params,
            )

            report_cards = await conn.fetch(
                "SELECT subject, grade_mark, teacher_comment, issued_on "
                "FROM report_card_facts WHERE learner_id = $1 "
                + ("AND term_id = $2 " if resolved_term_id is not None else "")
                + "ORDER BY COALESCE(issued_on, DATE '1900-01-01') DESC, id DESC LIMIT 20",
                *([learner_id, resolved_term_id] if resolved_term_id is not None else [learner_id]),
            )

            assessments = await conn.fetch(
                "SELECT ad.code, ad.name, ae.assessed_on, ar.result_numeric, ar.result_text, ar.percentile "
                "FROM assessment_events ae "
                "JOIN assessment_definitions ad ON ad.id = ae.assessment_definition_id "
                "LEFT JOIN assessment_results ar ON ar.assessment_event_id = ae.id "
                "WHERE ae.learner_id = $1 "
                + ("AND ae.term_id = $2 " if resolved_term_id is not None else "")
                + "ORDER BY ae.assessed_on DESC, ae.id DESC LIMIT 25",
                *([learner_id, resolved_term_id] if resolved_term_id is not None else [learner_id]),
            )

            metric_recent = await conn.fetch(
                "SELECT ad.code AS activity_code, md.code AS metric_code, mo.value_numeric, mo.value_text, mo.observed_at "
                "FROM metric_observations mo "
                "JOIN metric_definitions md ON md.id = mo.metric_definition_id "
                "LEFT JOIN activity_definitions ad ON ad.id = md.activity_definition_id "
                "WHERE mo.learner_id = $1 ORDER BY mo.observed_at DESC LIMIT 25",
                learner_id,
            )

            goals = await conn.fetch(
                "SELECT id, title, status, target_date FROM goals WHERE learner_id = $1 "
                "ORDER BY (status = 'completed') ASC, COALESCE(target_date, DATE '2999-12-31'), id DESC LIMIT 25",
                learner_id,
            )

            observations = await conn.fetch(
                "SELECT observed_on, domain, observation_text, source FROM observations "
                "WHERE learner_id = $1 ORDER BY observed_on DESC, id DESC LIMIT 15",
                learner_id,
            )

        artifact_rows = _rows_to_dicts(artifact_stats)
        report_rows = _rows_to_dicts(report_cards)
        assessment_rows = _rows_to_dicts(assessments)
        metric_rows = _rows_to_dicts(metric_recent)
        goal_rows = _rows_to_dicts(goals)
        observation_rows = _rows_to_dicts(observations)

        total_artifacts = sum(int(row["count"]) for row in artifact_rows)
        open_goals = sum(1 for row in goal_rows if row["status"] in {"open", "in_progress"})

        summary_lines = [
            f"Learner: {learner['display_name']}",
            f"Artifacts in scope: {total_artifacts}",
            f"Recent assessments: {len(assessment_rows)}",
            f"Report-card facts: {len(report_rows)}",
            f"Open goals: {open_goals}",
            f"Recent observations: {len(observation_rows)}",
        ]

        return {
            "learner": learner,
            "term": _row_to_dict(resolved_term),
            "summary": " | ".join(summary_lines),
            "artifact_summary": artifact_rows,
            "report_card_facts": report_rows,
            "assessment_results": assessment_rows,
            "recent_metric_observations": metric_rows,
            "goals": goal_rows,
            "observations": observation_rows,
            "provenance": {
                "source_tables": [
                    "artifacts",
                    "report_card_facts",
                    "assessment_events",
                    "assessment_results",
                    "metric_observations",
                    "goals",
                    "observations",
                ],
                "evidence_model": "artifact + extraction + review + canonical facts",
            },
        }
