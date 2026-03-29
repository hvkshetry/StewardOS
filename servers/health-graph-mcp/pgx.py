from __future__ import annotations

from typing import Any

from helpers import (
    _contains_placeholder,
    _extract_rsids,
    _finish_run,
    _first_nonempty,
    _policy_for_tier,
    _read_json_input,
    _row_to_dict,
    _rows_to_dicts,
    _start_run,
    _subject_has_any_rsid_match,
    _subject_has_genome_data,
    _to_json,
    _validate_source_name,
)
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
    ok_response as _ok_response,
)


def _extract_pharmcat_gene_reports(payload: dict) -> list[dict]:
    for key in ("geneReports", "genes", "report", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, dict):
            nested = _extract_pharmcat_gene_reports(value)
            if nested:
                return nested
    return []


def register_pgx_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def run_pgx_pipeline(
        person_id: int,
        phenotype_json: str,
        match_json: str = "",
        report_json: str = "",
        source_name: str = "pharmcat",
        allow_unverified: bool = False,
    ) -> dict:
        """Ingest PharmCAT outputs into normalized PGx tables."""
        await ensure_initialized()
        pool = await get_pool()
        rows_written = 0
        rows_skipped = 0

        try:
            _validate_source_name(source_name)
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        phenotype_payload = _read_json_input(phenotype_json)
        match_payload = _read_json_input(match_json) if match_json else {}
        report_payload = _read_json_input(report_json) if report_json else {}

        if _contains_placeholder(phenotype_payload) or _contains_placeholder(match_payload) or _contains_placeholder(report_payload):
            return _error_response(
                "PGx payload appears to contain placeholder/test content",
                code="validation_error",
            )

        if not allow_unverified and not match_payload:
            return _error_response(
                (
                    "match_json is required for subject-grounded PGx ingestion. "
                    "Set allow_unverified=true only for intentional manual backfill."
                ),
                code="validation_error",
            )

        gene_reports = []
        if isinstance(phenotype_payload, dict):
            gene_reports = _extract_pharmcat_gene_reports(phenotype_payload)

        if not gene_reports and isinstance(match_payload, dict):
            gene_reports = _extract_pharmcat_gene_reports(match_payload)

        async with pool.acquire() as conn:
            run_id = await _start_run(
                conn,
                source_name=source_name,
                run_type="pgx_ingest",
                metadata={"person_id": person_id, "allow_unverified": allow_unverified},
            )
            try:
                if not await _subject_has_genome_data(conn, person_id):
                    raise ValueError(f"person_id {person_id} has no genotype data")

                match_rsids = _extract_rsids(match_payload)
                if not allow_unverified and not match_rsids:
                    raise ValueError(
                        "match_json must include rsid-level grounding for this subject "
                        "(none were detected)"
                    )
                if not allow_unverified and not await _subject_has_any_rsid_match(conn, person_id, match_rsids):
                    raise ValueError(
                        "match_json rsids do not match this subject's genotype calls; "
                        "refusing ungrounded PGx ingestion"
                    )

                for gene_report in gene_reports:
                    if not isinstance(gene_report, dict) or _contains_placeholder(gene_report):
                        rows_skipped += 1
                        continue

                    gene_symbol = _first_nonempty(
                        gene_report.get("gene"),
                        gene_report.get("geneSymbol"),
                        gene_report.get("gene_name"),
                    )
                    if not gene_symbol:
                        rows_skipped += 1
                        continue

                    source_diplotype = _first_nonempty(
                        gene_report.get("sourceDiplotype"),
                        gene_report.get("sourceDiplotypes"),
                    )
                    rec_diplotype = _first_nonempty(
                        gene_report.get("recommendationDiplotype"),
                        gene_report.get("recommendationDiplotypes"),
                    )
                    phenotype = _first_nonempty(
                        gene_report.get("phenotype"),
                        gene_report.get("phenotypes"),
                        gene_report.get("recommendationLookupPhenotype"),
                    )
                    activity_score = _first_nonempty(
                        gene_report.get("activityScore"),
                        gene_report.get("recommendationLookupActivityScore"),
                    )

                    await conn.execute(
                        """INSERT INTO pgx_diplotypes (
                               person_id, gene_symbol, source_diplotype, recommendation_diplotype,
                               outside_call, match_score, source_name, source_json
                           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                           ON CONFLICT (
                               person_id, gene_symbol, source_name,
                               COALESCE(source_diplotype, ''), COALESCE(recommendation_diplotype, '')
                           )
                           DO UPDATE SET outside_call = EXCLUDED.outside_call,
                                         match_score = EXCLUDED.match_score,
                                         source_json = EXCLUDED.source_json""",
                        person_id,
                        gene_symbol,
                        source_diplotype,
                        rec_diplotype,
                        bool(gene_report.get("outsideCall")) if "outsideCall" in gene_report else None,
                        _first_nonempty(gene_report.get("matchScore")),
                        source_name,
                        _to_json(gene_report),
                    )
                    rows_written += 1

                    await conn.execute(
                        """INSERT INTO pgx_phenotypes (
                               person_id, gene_symbol, phenotype, activity_score, phenotype_source, source_json
                           ) VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                           ON CONFLICT (
                               person_id, gene_symbol, COALESCE(phenotype, ''),
                               COALESCE(activity_score, ''), COALESCE(phenotype_source, '')
                           )
                           DO UPDATE SET source_json = EXCLUDED.source_json""",
                        person_id,
                        gene_symbol,
                        phenotype,
                        activity_score,
                        _first_nonempty(gene_report.get("phenotypeDataSource"), source_name),
                        _to_json(gene_report),
                    )
                    rows_written += 1

                    if isinstance(report_payload, dict):
                        drug_entries = report_payload.get("drugs") or []
                        if isinstance(drug_entries, list):
                            for drug in drug_entries:
                                if not isinstance(drug, dict) or _contains_placeholder(drug):
                                    rows_skipped += 1
                                    continue
                                drug_name = _first_nonempty(drug.get("name"), drug.get("drug"))
                                rec_text = _first_nonempty(
                                    drug.get("recommendation"),
                                    drug.get("summary"),
                                    drug.get("message"),
                                )
                                if not drug_name or not rec_text:
                                    rows_skipped += 1
                                    continue
                                await conn.execute(
                                    """INSERT INTO pgx_recommendations (
                                           person_id, gene_symbol, drug_name, recommendation_text,
                                           source_name, source_record_id, evidence_tier, action_class,
                                           confidence_score, metadata
                                       ) VALUES ($1,$2,$3,$4,$5,$6,1,'actionable_with_guardrails',$7,$8::jsonb)
                                       ON CONFLICT (
                                           person_id, COALESCE(gene_symbol, ''), COALESCE(drug_name, ''),
                                           source_name, COALESCE(source_record_id, ''), recommendation_text
                                       )
                                       DO UPDATE SET evidence_tier = EXCLUDED.evidence_tier,
                                                     action_class = EXCLUDED.action_class,
                                                     confidence_score = EXCLUDED.confidence_score,
                                                     metadata = EXCLUDED.metadata""",
                                    person_id,
                                    gene_symbol,
                                    drug_name,
                                    rec_text,
                                    source_name,
                                    _first_nonempty(drug.get("id")),
                                    1.0,
                                    _to_json(drug),
                                )
                                rows_written += 1

                await _finish_run(conn, run_id, "success", len(gene_reports), rows_written)
                return _ok_response(
                    {
                    "ingestion_run_id": run_id,
                    "gene_reports": len(gene_reports),
                    "rows_written": rows_written,
                    "rows_skipped": rows_skipped,
                    "allow_unverified": allow_unverified,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", len(gene_reports), rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="pgx_ingest_failed",
                    payload={
                        "ingestion_run_id": run_id,
                        "rows_written": rows_written,
                        "rows_skipped": rows_skipped,
                    },
                )

    @_tool
    async def get_pgx_profile(person_id: int) -> dict:
        """Get PGx profile for a subject."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            diplotypes = await conn.fetch(
                """SELECT * FROM pgx_diplotypes
                   WHERE person_id=$1
                   ORDER BY id DESC""",
                person_id,
            )
            phenotypes = await conn.fetch(
                """SELECT * FROM pgx_phenotypes
                   WHERE person_id=$1
                   ORDER BY id DESC""",
                person_id,
            )
            recommendations = await conn.fetch(
                """SELECT * FROM pgx_recommendations
                   WHERE person_id=$1
                   ORDER BY id DESC""",
                person_id,
            )
        return {
            "person_id": person_id,
            "diplotypes": _rows_to_dicts(diplotypes),
            "phenotypes": _rows_to_dicts(phenotypes),
            "recommendations": _rows_to_dicts(recommendations),
        }

    @_tool
    async def list_pgx_recommendations(person_id: int) -> list[dict]:
        """List policy-annotated PGx recommendations."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM pgx_recommendations
                   WHERE person_id=$1
                   ORDER BY id DESC""",
                person_id,
            )
            output = []
            for row in rows:
                item = _row_to_dict(row) or {}
                policy = await _policy_for_tier(
                    conn,
                    int(item.get("evidence_tier") or 4),
                    str(item.get("action_class") or "research_only"),
                )
                item["policy"] = policy
                output.append(item)
        return output
