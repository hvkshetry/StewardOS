from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from assertion_variant_ops import ensure_subject_has_genome_data, resolve_subject_variant_id
from helpers import (
    _contains_placeholder,
    _finish_run,
    _first_nonempty,
    _normalize_action_class,
    _normalize_evidence_tier,
    _parse_date,
    _policy_for_tier,
    _read_json_input,
    _row_to_dict,
    _rows_to_dicts,
    _safe_int,
    _start_run,
    _to_json,
    _upsert_evidence_link,
    _validate_source_name,
)
from stewardos_lib.response_ops import error_response as _error_response, ok_response as _ok_response


GetPool = Callable[[], Awaitable[Any]]
EnsureInitialized = Callable[[], Awaitable[None]]


async def ingest_clinical_assertions_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    source_name: str,
    assertions_json: str | dict | list,
    subject_id: int = 0,
) -> dict:
    await ensure_initialized()

    try:
        _validate_source_name(source_name)
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    if subject_id <= 0:
        return _error_response(
            "subject_id is required to prevent ungrounded clinical assertion ingestion",
            code="validation_error",
        )

    payload = _read_json_input(assertions_json)
    if isinstance(payload, dict):
        assertions = payload.get("assertions") if isinstance(payload.get("assertions"), list) else [payload]
    elif isinstance(payload, list):
        assertions = payload
    else:
        return _error_response("Unsupported assertions payload", code="validation_error")

    pool = await get_pool()
    rows_written = 0
    skipped_placeholder = 0
    skipped_unmatched_subject = 0
    skipped_invalid = 0

    async with pool.acquire() as conn:
        run_id = await _start_run(
            conn,
            source_name=source_name,
            run_type="clinical_assertion_ingest",
            metadata={"subject_id": subject_id},
        )
        try:
            async with conn.transaction():
                await ensure_subject_has_genome_data(conn, subject_id)

                for item in assertions:
                    if not isinstance(item, dict):
                        skipped_invalid += 1
                        continue
                    if _contains_placeholder(item):
                        skipped_placeholder += 1
                        continue

                    rsid = _first_nonempty(item.get("rsid"))
                    chrom = _first_nonempty(item.get("chromosome"))
                    pos_int = _safe_int(item.get("position"))
                    if not rsid and (not chrom or pos_int is None):
                        skipped_invalid += 1
                        continue

                    variant_id = await resolve_subject_variant_id(
                        conn,
                        subject_id=subject_id,
                        source_name=source_name,
                        rsid=rsid,
                        chrom=chrom,
                        pos_int=pos_int,
                    )
                    if variant_id is None:
                        skipped_unmatched_subject += 1
                        continue

                    gene_symbol = _first_nonempty(item.get("gene"), item.get("gene_symbol"))
                    gene_id = None
                    if gene_symbol:
                        gene = await conn.fetchrow(
                            """INSERT INTO genes (gene_symbol, gene_id, metadata)
                               VALUES ($1,$2,$3::jsonb)
                               ON CONFLICT (gene_symbol)
                               DO UPDATE SET gene_id = COALESCE(EXCLUDED.gene_id, genes.gene_id)
                               RETURNING id""",
                            gene_symbol,
                            _first_nonempty(item.get("gene_id")),
                            _to_json({"source": source_name}),
                        )
                        assert gene is not None
                        gene_id = int(gene["id"])

                    evidence_tier = _normalize_evidence_tier(item.get("evidence_tier"), default=2)
                    action_class = _normalize_action_class(_first_nonempty(item.get("action_class")), evidence_tier)

                    await conn.execute(
                        """INSERT INTO clinical_assertions (
                               variant_id, gene_id, source_name, source_record_id, significance,
                               review_status, conflict_state, condition_name, actionability,
                               evidence_tier, action_class, confidence_score, assertion_json, last_evaluated
                           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14)
                           ON CONFLICT (
                               COALESCE(variant_id, 0), COALESCE(gene_id, 0), source_name,
                               COALESCE(source_record_id, ''), COALESCE(condition_name, ''),
                               COALESCE(significance, '')
                           )
                           DO UPDATE SET review_status = EXCLUDED.review_status,
                                         conflict_state = EXCLUDED.conflict_state,
                                         actionability = EXCLUDED.actionability,
                                         evidence_tier = EXCLUDED.evidence_tier,
                                         action_class = EXCLUDED.action_class,
                                         confidence_score = EXCLUDED.confidence_score,
                                         assertion_json = EXCLUDED.assertion_json,
                                         last_evaluated = COALESCE(EXCLUDED.last_evaluated, clinical_assertions.last_evaluated),
                                         updated_at = NOW()""",
                        variant_id,
                        gene_id,
                        source_name,
                        _first_nonempty(item.get("source_record_id"), item.get("id")),
                        _first_nonempty(item.get("significance")),
                        _first_nonempty(item.get("review_status")),
                        _first_nonempty(item.get("conflict_state")),
                        _first_nonempty(item.get("condition_name"), item.get("condition")),
                        _first_nonempty(item.get("actionability")),
                        evidence_tier,
                        action_class,
                        float(item.get("confidence_score") or 0.0) if item.get("confidence_score") is not None else None,
                        _to_json(item),
                        _parse_date(item.get("last_evaluated")),
                    )
                    rows_written += 1

            await _finish_run(conn, run_id, "success", len(assertions), rows_written)
            return _ok_response(
                {
                    "ingestion_run_id": run_id,
                    "rows_read": len(assertions),
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_unmatched_subject": skipped_unmatched_subject,
                    "skipped_invalid": skipped_invalid,
                }
            )
        except Exception as exc:  # noqa: BLE001
            await _finish_run(conn, run_id, "error", len(assertions), rows_written, str(exc))
            return _error_response(
                str(exc),
                code="clinical_assertion_ingest_failed",
                payload={
                    "ingestion_run_id": run_id,
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_unmatched_subject": skipped_unmatched_subject,
                    "skipped_invalid": skipped_invalid,
                },
            )


async def query_variant_assertions_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    rsid: str = "",
    gene_symbol: str = "",
    evidence_tier_max: int = 4,
    limit: int = 100,
) -> list[dict]:
    await ensure_initialized()
    pool = await get_pool()
    clauses = ["ca.evidence_tier <= $1"]
    params: list[Any] = [max(1, min(evidence_tier_max, 4))]
    idx = 2
    if rsid:
        clauses.append(f"vc.rsid = ${idx}")
        params.append(rsid)
        idx += 1
    if gene_symbol:
        clauses.append(f"g.gene_symbol = ${idx}")
        params.append(gene_symbol)
        idx += 1
    params.append(max(1, min(limit, 1000)))

    query = (
        "SELECT ca.*, vc.rsid, vc.chromosome, vc.position, g.gene_symbol "
        "FROM clinical_assertions ca "
        "LEFT JOIN variant_canonical vc ON vc.id = ca.variant_id "
        "LEFT JOIN genes g ON g.id = ca.gene_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY ca.id DESC LIMIT $" + str(idx)
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return _rows_to_dicts(rows)


async def ingest_trait_associations_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    source_name: str,
    associations_json: str | dict | list,
    subject_id: int = 0,
) -> dict:
    await ensure_initialized()

    try:
        _validate_source_name(source_name)
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    if subject_id <= 0:
        return _error_response(
            "subject_id is required to prevent ungrounded trait association ingestion",
            code="validation_error",
        )

    payload = _read_json_input(associations_json)
    if isinstance(payload, dict):
        associations = payload.get("associations") if isinstance(payload.get("associations"), list) else [payload]
    elif isinstance(payload, list):
        associations = payload
    else:
        return _error_response("Unsupported associations payload", code="validation_error")

    pool = await get_pool()
    rows_written = 0
    skipped_placeholder = 0
    skipped_unmatched_subject = 0
    skipped_invalid = 0

    async with pool.acquire() as conn:
        run_id = await _start_run(
            conn,
            source_name=source_name,
            run_type="trait_association_ingest",
            metadata={"subject_id": subject_id},
        )
        try:
            async with conn.transaction():
                await ensure_subject_has_genome_data(conn, subject_id)

                for item in associations:
                    if not isinstance(item, dict):
                        skipped_invalid += 1
                        continue
                    if _contains_placeholder(item):
                        skipped_placeholder += 1
                        continue

                    rsid = _first_nonempty(item.get("rsid"))
                    chrom = _first_nonempty(item.get("chromosome"))
                    pos_int = _safe_int(item.get("position"))
                    if not rsid and (not chrom or pos_int is None):
                        skipped_invalid += 1
                        continue

                    variant_id = await resolve_subject_variant_id(
                        conn,
                        subject_id=subject_id,
                        source_name=source_name,
                        rsid=rsid,
                        chrom=chrom,
                        pos_int=pos_int,
                    )
                    if variant_id is None:
                        skipped_unmatched_subject += 1
                        continue

                    evidence_tier = _normalize_evidence_tier(item.get("evidence_tier"), default=3)
                    action_class = "context_only"
                    if _first_nonempty(item.get("domain"), item.get("category")) in {"nutrition", "exercise", "sports"}:
                        action_class = "research_only"
                    action_class = _normalize_action_class(action_class, evidence_tier)

                    trait_name = _first_nonempty(item.get("trait_name"), item.get("trait"))
                    if not trait_name:
                        skipped_invalid += 1
                        continue

                    await conn.execute(
                        """INSERT INTO trait_associations (
                               variant_id, source_name, trait_name, effect_allele, effect_size,
                               p_value, ancestry, study_id, evidence_tier, action_class, metadata
                           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
                           ON CONFLICT (
                               COALESCE(variant_id, 0), source_name, trait_name,
                               COALESCE(study_id, ''), COALESCE(effect_allele, '')
                           )
                           DO UPDATE SET effect_size = EXCLUDED.effect_size,
                                         p_value = EXCLUDED.p_value,
                                         ancestry = EXCLUDED.ancestry,
                                         evidence_tier = EXCLUDED.evidence_tier,
                                         action_class = EXCLUDED.action_class,
                                         metadata = EXCLUDED.metadata""",
                        variant_id,
                        source_name,
                        trait_name,
                        _first_nonempty(item.get("effect_allele")),
                        float(item.get("effect_size")) if item.get("effect_size") is not None else None,
                        float(item.get("p_value")) if item.get("p_value") is not None else None,
                        _first_nonempty(item.get("ancestry")),
                        _first_nonempty(item.get("study_id")),
                        evidence_tier,
                        action_class,
                        _to_json(item),
                    )
                    rows_written += 1

            await _finish_run(conn, run_id, "success", len(associations), rows_written)
            return _ok_response(
                {
                    "ingestion_run_id": run_id,
                    "rows_read": len(associations),
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_unmatched_subject": skipped_unmatched_subject,
                    "skipped_invalid": skipped_invalid,
                }
            )
        except Exception as exc:  # noqa: BLE001
            await _finish_run(conn, run_id, "error", len(associations), rows_written, str(exc))
            return _error_response(
                str(exc),
                code="trait_association_ingest_failed",
                payload={
                    "ingestion_run_id": run_id,
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_unmatched_subject": skipped_unmatched_subject,
                    "skipped_invalid": skipped_invalid,
                },
            )


async def get_polygenic_context_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    subject_id: int,
    limit: int = 100,
) -> dict:
    await ensure_initialized()
    pool = await get_pool()
    async with pool.acquire() as conn:
        associations = await conn.fetch(
            """SELECT ta.*
               FROM trait_associations ta
               WHERE EXISTS (
                   SELECT 1
                   FROM genotype_calls gc
                   JOIN callsets c ON c.id = gc.callset_id
                   JOIN samples s ON s.id = c.sample_id
                   WHERE s.subject_id = $1
                     AND gc.variant_id = ta.variant_id
               )
               ORDER BY ta.id DESC
               LIMIT $2""",
            subject_id,
            max(1, min(limit, 1000)),
        )
        evaluations = await conn.fetch(
            """SELECT pe.*, ps.score_id, ps.trait_name, ps.ancestry
               FROM polygenic_evaluations pe
               JOIN polygenic_scores ps ON ps.id = pe.polygenic_score_id
               WHERE pe.subject_id = $1
               ORDER BY pe.id DESC""",
            subject_id,
        )

        out_assoc = []
        for row in associations:
            item = _row_to_dict(row) or {}
            policy = await _policy_for_tier(
                conn,
                int(item.get("evidence_tier") or 4),
                str(item.get("action_class") or "research_only"),
            )
            item["policy"] = policy
            out_assoc.append(item)

    return {
        "subject_id": subject_id,
        "trait_associations": out_assoc,
        "polygenic_evaluations": _rows_to_dicts(evaluations),
    }


async def add_literature_evidence_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    source_name: str,
    external_id: str,
    title: str,
    url: str = "",
    published_at: str = "",
    abstract_text: str = "",
    assertion_id: int = 0,
    variant_id: int = 0,
    trait_association_id: int = 0,
    notes: str = "",
) -> dict:
    await ensure_initialized()

    try:
        _validate_source_name(source_name)
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    if _contains_placeholder(
        {
            "external_id": external_id,
            "title": title,
            "abstract_text": abstract_text,
            "notes": notes,
        }
    ):
        return _error_response(
            "literature evidence appears to contain placeholder/test content",
            code="validation_error",
        )

    if assertion_id <= 0 and variant_id <= 0 and trait_association_id <= 0:
        return _error_response(
            (
                "At least one linkage target (assertion_id, variant_id, trait_association_id) "
                "is required to avoid ungrounded literature inserts"
            ),
            code="validation_error",
        )

    pool = await get_pool()
    pub_date = _parse_date(published_at)

    async with pool.acquire() as conn:
        if assertion_id > 0:
            exists = await conn.fetchrow("SELECT 1 FROM clinical_assertions WHERE id=$1", assertion_id)
            if exists is None:
                return _error_response(f"assertion_id {assertion_id} not found", code="not_found")
        if variant_id > 0:
            exists = await conn.fetchrow("SELECT 1 FROM variant_canonical WHERE id=$1", variant_id)
            if exists is None:
                return _error_response(f"variant_id {variant_id} not found", code="not_found")
        if trait_association_id > 0:
            exists = await conn.fetchrow("SELECT 1 FROM trait_associations WHERE id=$1", trait_association_id)
            if exists is None:
                return _error_response(f"trait_association_id {trait_association_id} not found", code="not_found")

        evidence = await conn.fetchrow(
            """INSERT INTO literature_evidence (
                   source_name, external_id, title, url, published_at, abstract_text
               ) VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (source_name, COALESCE(external_id, ''))
               DO UPDATE SET title = EXCLUDED.title,
                             url = EXCLUDED.url,
                             published_at = COALESCE(EXCLUDED.published_at, literature_evidence.published_at),
                             abstract_text = COALESCE(EXCLUDED.abstract_text, literature_evidence.abstract_text)
               RETURNING *""",
            source_name,
            external_id,
            title,
            url or None,
            pub_date,
            abstract_text or None,
        )
        assert evidence is not None

        await _upsert_evidence_link(
            conn,
            int(evidence["id"]),
            assertion_id=assertion_id if assertion_id > 0 else None,
            variant_id=variant_id if variant_id > 0 else None,
            trait_association_id=trait_association_id if trait_association_id > 0 else None,
            notes=notes or None,
        )

    return _row_to_dict(evidence) or {}


async def query_evidence_graph_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    assertion_id: int = 0,
    variant_id: int = 0,
    limit: int = 200,
) -> list[dict]:
    await ensure_initialized()
    pool = await get_pool()

    clauses = ["1=1"]
    params: list[Any] = []
    idx = 1
    if assertion_id > 0:
        clauses.append(f"el.assertion_id = ${idx}")
        params.append(assertion_id)
        idx += 1
    if variant_id > 0:
        clauses.append(f"el.variant_id = ${idx}")
        params.append(variant_id)
        idx += 1
    params.append(max(1, min(limit, 1000)))

    query = (
        "SELECT el.*, le.source_name, le.external_id, le.title, le.url, le.published_at "
        "FROM evidence_links el "
        "JOIN literature_evidence le ON le.id = el.literature_evidence_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY el.id DESC LIMIT $" + str(idx)
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return _rows_to_dicts(rows)


async def get_wellness_recommendations_tool(
    *,
    get_pool: GetPool,
    ensure_initialized: EnsureInitialized,
    subject_id: int,
) -> dict:
    await ensure_initialized()
    pool = await get_pool()

    async with pool.acquire() as conn:
        pgx_rows = await conn.fetch(
            """SELECT * FROM pgx_recommendations
               WHERE subject_id=$1
               ORDER BY id DESC
               LIMIT 50""",
            subject_id,
        )
        assoc_rows = await conn.fetch(
            """SELECT ta.*
               FROM trait_associations ta
               WHERE EXISTS (
                   SELECT 1
                   FROM genotype_calls gc
                   JOIN callsets c ON c.id = gc.callset_id
                   JOIN samples s ON s.id = c.sample_id
                   WHERE s.subject_id = $1
                     AND gc.variant_id = ta.variant_id
               )
               ORDER BY ta.id DESC
               LIMIT 100""",
            subject_id,
        )
        recent_labs = await conn.fetch(
            """SELECT * FROM observations
               WHERE subject_id=$1
               ORDER BY effective_at DESC NULLS LAST, id DESC
               LIMIT 20""",
            subject_id,
        )

        recommendations = []

        for row in pgx_rows:
            item = _row_to_dict(row) or {}
            policy = await _policy_for_tier(
                conn,
                int(item.get("evidence_tier") or 4),
                str(item.get("action_class") or "research_only"),
            )
            item["policy"] = policy
            recommendations.append(item)

        research_notes = []
        for row in assoc_rows:
            item = _row_to_dict(row) or {}
            policy = await _policy_for_tier(
                conn,
                int(item.get("evidence_tier") or 4),
                str(item.get("action_class") or "research_only"),
            )
            if policy.get("research_mode_only"):
                research_notes.append(item)

    return {
        "subject_id": subject_id,
        "actionable_recommendations": recommendations,
        "research_mode_notes": research_notes[:20],
        "recent_labs": _rows_to_dicts(recent_labs),
        "provenance": {
            "servers": ["health-graph-mcp"],
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
    }
