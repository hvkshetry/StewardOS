from __future__ import annotations

from datetime import date
from typing import Any

from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool

from helpers import (
    _finish_run,
    _has_risk_allele,
    _normalize_action_class,
    _parse_date,
    _parse_tiers_arg,
    _safe_int,
    _start_run,
    _subject_has_genome_data,
    _subject_variant_for_rsid,
    _to_json,
    _upsert_evidence_link,
)

_PGX_HYDRATION_RULES: list[dict[str, Any]] = [
    {
        "rsid": "rs4244285",
        "gene_symbol": "CYP2C19",
        "risk_alleles": {"A"},
        "source_diplotype": "*1/*2_or_*2/*2",
        "recommendation_diplotype": "decreased_function",
        "phenotype": "intermediate_or_poor_metabolizer",
        "drug_name": "clopidogrel",
        "recommendation_text": (
            "Reduced CYP2C19 function may lower clopidogrel activation. "
            "Review antiplatelet choice with clinician."
        ),
        "source_name": "cpic_curated",
        "source_record_id": "CPIC:CYP2C19-clopidogrel",
        "confidence_score": 0.98,
    },
    {
        "rsid": "rs4149056",
        "gene_symbol": "SLCO1B1",
        "risk_alleles": {"C"},
        "source_diplotype": "*1/*5_or_*5/*5",
        "recommendation_diplotype": "decreased_transport",
        "phenotype": "increased_statin_myopathy_risk",
        "drug_name": "simvastatin",
        "recommendation_text": (
            "SLCO1B1 decreased transporter function may increase statin-associated myopathy risk. "
            "Consider dose strategy and monitoring."
        ),
        "source_name": "cpic_curated",
        "source_record_id": "CPIC:SLCO1B1-simvastatin",
        "confidence_score": 0.97,
    },
    {
        "rsid": "rs1057910",
        "gene_symbol": "CYP2C9",
        "risk_alleles": {"C"},
        "source_diplotype": "*1/*3_or_*3/*3",
        "recommendation_diplotype": "decreased_function",
        "phenotype": "poor_warfarin_clearance_risk",
        "drug_name": "warfarin",
        "recommendation_text": (
            "CYP2C9 reduced function can increase warfarin sensitivity. "
            "Dose selection should follow clinician-guided protocols."
        ),
        "source_name": "cpic_curated",
        "source_record_id": "CPIC:CYP2C9-warfarin",
        "confidence_score": 0.98,
    },
]

_CLINICAL_ASSERTION_RULES: list[dict[str, Any]] = [
    {
        "rsid": "rs6025",
        "gene_symbol": "F5",
        "risk_alleles": {"A"},
        "source_name": "clingen_curated",
        "source_record_id": "ClinVar:rs6025",
        "significance": "increased_thrombophilia_risk",
        "review_status": "criteria_provided_multiple_submitters_no_conflicts",
        "condition_name": "Factor V Leiden thrombophilia",
        "actionability": "review_required",
        "confidence_score": 0.9,
        "evidence_tier": 2,
    },
    {
        "rsid": "rs1799963",
        "gene_symbol": "F2",
        "risk_alleles": {"A"},
        "source_name": "clingen_curated",
        "source_record_id": "ClinVar:rs1799963",
        "significance": "increased_venous_thromboembolism_risk",
        "review_status": "criteria_provided_multiple_submitters_no_conflicts",
        "condition_name": "Prothrombin thrombophilia",
        "actionability": "review_required",
        "confidence_score": 0.88,
        "evidence_tier": 2,
    },
]

_TRAIT_ASSOCIATION_RULES: list[dict[str, Any]] = [
    {
        "rsid": "rs9939609",
        "trait_name": "BMI and adiposity predisposition",
        "effect_allele": "A",
        "effect_size": 0.08,
        "p_value": 1e-20,
        "ancestry": "multi-ancestry",
        "study_id": "GCST006368",
        "source_name": "gwas_catalog_curated",
        "evidence_tier": 3,
        "action_class": "context_only",
    },
    {
        "rsid": "rs7903146",
        "trait_name": "Type 2 diabetes susceptibility context",
        "effect_allele": "T",
        "effect_size": 0.12,
        "p_value": 1e-25,
        "ancestry": "multi-ancestry",
        "study_id": "GCST005414",
        "source_name": "gwas_catalog_curated",
        "evidence_tier": 3,
        "action_class": "context_only",
    },
    {
        "rsid": "rs1815739",
        "trait_name": "Sprint/power phenotype hypothesis",
        "effect_allele": "C",
        "effect_size": 0.04,
        "p_value": 1e-6,
        "ancestry": "mixed",
        "study_id": "SPORTS_REVIEW_2025",
        "source_name": "exercise_genomics_literature",
        "evidence_tier": 4,
        "action_class": "research_only",
    },
]

_LITERATURE_BY_RSID: dict[str, list[dict[str, str]]] = {
    "rs4244285": [
        {
            "source_name": "pubmed",
            "external_id": "PMID:26230191",
            "title": "Clinical Pharmacogenetics Implementation Consortium guideline for CYP2C19 and clopidogrel",
            "url": "https://pubmed.ncbi.nlm.nih.gov/26230191/",
            "published_at": "2015-08-01",
        }
    ],
    "rs4149056": [
        {
            "source_name": "pubmed",
            "external_id": "PMID:24918167",
            "title": "CPIC guideline for SLCO1B1 and simvastatin-induced myopathy",
            "url": "https://pubmed.ncbi.nlm.nih.gov/24918167/",
            "published_at": "2014-06-10",
        }
    ],
    "rs1057910": [
        {
            "source_name": "pubmed",
            "external_id": "PMID:24851822",
            "title": "Clinical Pharmacogenetics Implementation Consortium guidelines for CYP2C9 and warfarin",
            "url": "https://pubmed.ncbi.nlm.nih.gov/24851822/",
            "published_at": "2014-05-20",
        }
    ],
}


def register_genome_knowledge_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def hydrate_subject_genome_knowledge(
        subject_id: int,
        mode: str = "delta",
        tiers: str | list[int] | list[str] = "1,2,3,4",
        max_literature_per_item: int = 5,
    ) -> dict:
        """Hydrate subject-specific PGx, assertions, traits, and literature links."""
        await ensure_initialized()
        pool = await get_pool()

        if subject_id <= 0:
            return _error_response("subject_id must be > 0", code="validation_error")

        mode_normalized = (mode or "delta").strip().lower()
        if mode_normalized not in {"delta", "bulk"}:
            return _error_response("mode must be one of: delta, bulk", code="validation_error")

        tier_list = _parse_tiers_arg(tiers)
        tier_set = set(tier_list)
        lit_cap = max(1, min(max_literature_per_item, 10))

        rows_written = 0
        rows_read = 0
        summary = {
            "pgx_recommendations": 0,
            "clinical_assertions": 0,
            "trait_associations": 0,
            "literature_evidence": 0,
            "evidence_links": 0,
        }

        async with pool.acquire() as conn:
            run_id = await _start_run(
                conn,
                source_name="health_graph_hydrator",
                run_type="hydrate_subject_genome_knowledge",
                metadata={
                    "subject_id": subject_id,
                    "requested_mode": mode_normalized,
                    "tiers": tier_list,
                    "max_literature_per_item": lit_cap,
                },
            )
            try:
                if not await _subject_has_genome_data(conn, subject_id):
                    raise ValueError(f"subject_id {subject_id} has no genotype data")

                variant_map: dict[str, int] = {}
                assertion_map: dict[str, int] = {}
                trait_map: dict[str, int] = {}

                if 1 in tier_set:
                    for rule in _PGX_HYDRATION_RULES:
                        rsid = str(rule["rsid"])
                        subject_variant = await _subject_variant_for_rsid(conn, subject_id, rsid)
                        if not subject_variant:
                            continue
                        rows_read += 1
                        genotype = str(subject_variant.get("genotype") or "")
                        if not _has_risk_allele(genotype, set(rule.get("risk_alleles") or [])):
                            continue

                        variant_id = _safe_int(subject_variant.get("variant_id"))
                        if variant_id:
                            variant_map[rsid.lower()] = variant_id

                        gene_symbol = str(rule["gene_symbol"])
                        source_name = str(rule["source_name"])
                        source_record_id = str(rule["source_record_id"])

                        await conn.execute(
                            """INSERT INTO pgx_diplotypes (
                                   subject_id, gene_symbol, source_diplotype, recommendation_diplotype,
                                   outside_call, match_score, source_name, source_json
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                               ON CONFLICT (
                                   subject_id, gene_symbol, source_name,
                                   COALESCE(source_diplotype, ''), COALESCE(recommendation_diplotype, '')
                               )
                               DO UPDATE SET source_json = EXCLUDED.source_json""",
                            subject_id,
                            gene_symbol,
                            str(rule.get("source_diplotype") or ""),
                            str(rule.get("recommendation_diplotype") or ""),
                            None,
                            None,
                            source_name,
                            _to_json(
                                {
                                    "hydration_mode": mode_normalized,
                                    "rsid": rsid,
                                    "genotype": genotype,
                                }
                            ),
                        )
                        rows_written += 1

                        await conn.execute(
                            """INSERT INTO pgx_phenotypes (
                                   subject_id, gene_symbol, phenotype, activity_score, phenotype_source, source_json
                               ) VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                               ON CONFLICT (
                                   subject_id, gene_symbol, COALESCE(phenotype, ''),
                                   COALESCE(activity_score, ''), COALESCE(phenotype_source, '')
                               )
                               DO UPDATE SET source_json = EXCLUDED.source_json""",
                            subject_id,
                            gene_symbol,
                            str(rule.get("phenotype") or ""),
                            None,
                            source_name,
                            _to_json({"hydration_mode": mode_normalized, "rsid": rsid, "genotype": genotype}),
                        )
                        rows_written += 1

                        await conn.execute(
                            """INSERT INTO pgx_recommendations (
                                   subject_id, gene_symbol, drug_name, recommendation_text,
                                   source_name, source_record_id, evidence_tier, action_class,
                                   confidence_score, metadata
                               ) VALUES ($1,$2,$3,$4,$5,$6,1,'actionable_with_guardrails',$7,$8::jsonb)
                               ON CONFLICT (
                                   subject_id, COALESCE(gene_symbol, ''), COALESCE(drug_name, ''),
                                   source_name, COALESCE(source_record_id, ''), recommendation_text
                               )
                               DO UPDATE SET confidence_score = EXCLUDED.confidence_score,
                                             metadata = EXCLUDED.metadata""",
                            subject_id,
                            gene_symbol,
                            str(rule.get("drug_name") or ""),
                            str(rule.get("recommendation_text") or ""),
                            source_name,
                            source_record_id,
                            float(rule.get("confidence_score") or 0.95),
                            _to_json(
                                {
                                    "hydration_mode": mode_normalized,
                                    "rsid": rsid,
                                    "genotype": genotype,
                                }
                            ),
                        )
                        rows_written += 1
                        summary["pgx_recommendations"] += 1

                if 2 in tier_set:
                    for rule in _CLINICAL_ASSERTION_RULES:
                        rsid = str(rule["rsid"])
                        subject_variant = await _subject_variant_for_rsid(conn, subject_id, rsid)
                        if not subject_variant:
                            continue
                        rows_read += 1
                        genotype = str(subject_variant.get("genotype") or "")
                        if not _has_risk_allele(genotype, set(rule.get("risk_alleles") or [])):
                            continue

                        variant_id = _safe_int(subject_variant.get("variant_id"))
                        if not variant_id:
                            continue
                        variant_map[rsid.lower()] = variant_id

                        gene = await conn.fetchrow(
                            """INSERT INTO genes (gene_symbol, metadata)
                               VALUES ($1,$2::jsonb)
                               ON CONFLICT (gene_symbol)
                               DO UPDATE SET metadata = genes.metadata || EXCLUDED.metadata
                               RETURNING id""",
                            str(rule["gene_symbol"]),
                            _to_json({"source": rule["source_name"]}),
                        )
                        assert gene is not None
                        gene_id = int(gene["id"])

                        assertion = await conn.fetchrow(
                            """INSERT INTO clinical_assertions (
                                   variant_id, gene_id, source_name, source_record_id, significance,
                                   review_status, conflict_state, condition_name, actionability,
                                   evidence_tier, action_class, confidence_score, assertion_json, last_evaluated
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'review_required',$11,$12::jsonb,$13)
                               ON CONFLICT (
                                   COALESCE(variant_id, 0), COALESCE(gene_id, 0), source_name,
                                   COALESCE(source_record_id, ''), COALESCE(condition_name, ''),
                                   COALESCE(significance, '')
                               )
                               DO UPDATE SET review_status = EXCLUDED.review_status,
                                             actionability = EXCLUDED.actionability,
                                             confidence_score = EXCLUDED.confidence_score,
                                             assertion_json = EXCLUDED.assertion_json,
                                             updated_at = NOW()
                               RETURNING id""",
                            variant_id,
                            gene_id,
                            str(rule["source_name"]),
                            str(rule["source_record_id"]),
                            str(rule.get("significance") or ""),
                            str(rule.get("review_status") or ""),
                            None,
                            str(rule.get("condition_name") or ""),
                            str(rule.get("actionability") or "review_required"),
                            int(rule.get("evidence_tier") or 2),
                            float(rule.get("confidence_score") or 0.8),
                            _to_json(
                                {
                                    "hydration_mode": mode_normalized,
                                    "rsid": rsid,
                                    "genotype": genotype,
                                }
                            ),
                            date.today(),
                        )
                        assert assertion is not None
                        assertion_map[rsid.lower()] = int(assertion["id"])
                        rows_written += 1
                        summary["clinical_assertions"] += 1

                for rule in _TRAIT_ASSOCIATION_RULES:
                    evidence_tier = int(rule.get("evidence_tier") or 4)
                    if evidence_tier not in tier_set:
                        continue

                    rsid = str(rule["rsid"])
                    subject_variant = await _subject_variant_for_rsid(conn, subject_id, rsid)
                    if not subject_variant:
                        continue
                    rows_read += 1
                    genotype = str(subject_variant.get("genotype") or "")
                    effect_allele = str(rule.get("effect_allele") or "")
                    if effect_allele and effect_allele.upper() not in genotype.upper():
                        continue

                    variant_id = _safe_int(subject_variant.get("variant_id"))
                    if not variant_id:
                        continue
                    variant_map[rsid.lower()] = variant_id

                    trait = await conn.fetchrow(
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
                                         metadata = EXCLUDED.metadata
                           RETURNING id""",
                        variant_id,
                        str(rule["source_name"]),
                        str(rule["trait_name"]),
                        effect_allele or None,
                        float(rule["effect_size"]) if rule.get("effect_size") is not None else None,
                        float(rule["p_value"]) if rule.get("p_value") is not None else None,
                        str(rule.get("ancestry") or ""),
                        str(rule.get("study_id") or ""),
                        evidence_tier,
                        _normalize_action_class(str(rule.get("action_class") or ""), evidence_tier),
                        _to_json(
                            {
                                "hydration_mode": mode_normalized,
                                "rsid": rsid,
                                "genotype": genotype,
                            }
                        ),
                    )
                    assert trait is not None
                    trait_map[rsid.lower()] = int(trait["id"])
                    rows_written += 1
                    summary["trait_associations"] += 1

                for rsid, refs in _LITERATURE_BY_RSID.items():
                    key = rsid.lower()
                    if key not in variant_map and key not in assertion_map and key not in trait_map:
                        continue
                    for citation in refs[:lit_cap]:
                        evidence = await conn.fetchrow(
                            """INSERT INTO literature_evidence (
                                   source_name, external_id, title, url, published_at, abstract_text
                               ) VALUES ($1,$2,$3,$4,$5,$6)
                               ON CONFLICT (source_name, COALESCE(external_id, ''))
                               DO UPDATE SET title = EXCLUDED.title,
                                             url = EXCLUDED.url,
                                             published_at = COALESCE(EXCLUDED.published_at, literature_evidence.published_at)
                               RETURNING id""",
                            citation["source_name"],
                            citation["external_id"],
                            citation["title"],
                            citation.get("url"),
                            _parse_date(citation.get("published_at")),
                            None,
                        )
                        assert evidence is not None
                        evidence_id = int(evidence["id"])
                        summary["literature_evidence"] += 1

                        before = await conn.fetchval(
                            """SELECT COUNT(*)::int FROM evidence_links
                               WHERE literature_evidence_id = $1
                                 AND COALESCE(assertion_id, 0) = COALESCE($2, 0)
                                 AND COALESCE(variant_id, 0) = COALESCE($3, 0)
                                 AND COALESCE(trait_association_id, 0) = COALESCE($4, 0)
                                 AND COALESCE(notes, '') = COALESCE($5, '')""",
                            evidence_id,
                            assertion_map.get(key),
                            variant_map.get(key),
                            trait_map.get(key),
                            "hydrated_genome_specific",
                        )
                        await _upsert_evidence_link(
                            conn,
                            evidence_id,
                            assertion_id=assertion_map.get(key),
                            variant_id=variant_map.get(key),
                            trait_association_id=trait_map.get(key),
                            notes="hydrated_genome_specific",
                        )
                        after = await conn.fetchval(
                            """SELECT COUNT(*)::int FROM evidence_links
                               WHERE literature_evidence_id = $1
                                 AND COALESCE(assertion_id, 0) = COALESCE($2, 0)
                                 AND COALESCE(variant_id, 0) = COALESCE($3, 0)
                                 AND COALESCE(trait_association_id, 0) = COALESCE($4, 0)
                                 AND COALESCE(notes, '') = COALESCE($5, '')""",
                            evidence_id,
                            assertion_map.get(key),
                            variant_map.get(key),
                            trait_map.get(key),
                            "hydrated_genome_specific",
                        )
                        if int(after or 0) > int(before or 0):
                            summary["evidence_links"] += 1
                            rows_written += 1

                await _finish_run(conn, run_id, "success", rows_read, rows_written)
                return {
                    "ingestion_run_id": run_id,
                    "subject_id": subject_id,
                    "mode": "delta",
                    "requested_mode": mode_normalized,
                    "tiers": tier_list,
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "summary": summary,
                }
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", rows_read, rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="hydration_error",
                    payload={
                        "ingestion_run_id": run_id,
                        "subject_id": subject_id,
                        "rows_read": rows_read,
                        "rows_written": rows_written,
                        "summary": summary,
                    },
                )
