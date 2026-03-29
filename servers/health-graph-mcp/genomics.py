from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from helpers import (
    _finish_run,
    _infer_zygosity,
    _row_to_dict,
    _rows_to_dicts,
    _sha256_file,
    _start_run,
    _to_json,
    _validate_source_name,
    _variant_key,
)
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
    ok_response as _ok_response,
)


def register_genomics_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def ingest_genome_artifact(
        person_id: int,
        file_path: str,
        sample_name: str = "primary_dna",
        callset_name: str = "23andme_raw",
        source_name: str = "23andme",
        max_rows: int = 0,
    ) -> dict:
        """Ingest 23andMe style raw genotype artifact and normalize genotype calls.

        Set max_rows=0 for full file.
        """
        await ensure_initialized()
        try:
            _validate_source_name(source_name)
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")
        path = Path(file_path)
        if not path.is_file():
            return _error_response(f"File not found: {file_path}", code="not_found")

        pool = await get_pool()
        rows_read = 0
        rows_written = 0
        assembly = "GRCh37"

        async with pool.acquire() as conn:
            run_id = await _start_run(conn, source_name=source_name, run_type="genome_ingest")
            try:
                sha = _sha256_file(path)
                artifact = await conn.fetchrow(
                    """INSERT INTO source_artifacts (source_name, artifact_type, file_path, sha256, metadata)
                       VALUES ($1, 'genotype_raw', $2, $3, $4::jsonb)
                       RETURNING *""",
                    source_name,
                    str(path),
                    sha,
                    _to_json({"filename": path.name}),
                )
                assert artifact is not None

                sample = await conn.fetchrow(
                    """INSERT INTO samples (person_id, sample_name, sample_type)
                       VALUES ($1, $2, 'dna')
                       ON CONFLICT (person_id, sample_name)
                       DO UPDATE SET sample_type = EXCLUDED.sample_type
                       RETURNING *""",
                    person_id,
                    sample_name,
                )
                assert sample is not None

                assay = await conn.fetchrow(
                    """INSERT INTO assays (assay_name, platform, assembly)
                       VALUES ('23andme_raw_genotype', '23andme', $1)
                       ON CONFLICT (assay_name, COALESCE(platform, ''))
                       DO UPDATE SET assembly = COALESCE(EXCLUDED.assembly, assays.assembly)
                       RETURNING *""",
                    assembly,
                )
                assert assay is not None

                callset = await conn.fetchrow(
                    """INSERT INTO callsets (sample_id, assay_id, source_artifact_id, callset_name, assembly)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (sample_id, callset_name)
                       DO UPDATE SET source_artifact_id = EXCLUDED.source_artifact_id,
                                     assembly = EXCLUDED.assembly
                       RETURNING *""",
                    int(sample["id"]),
                    int(assay["id"]),
                    int(artifact["id"]),
                    callset_name,
                    assembly,
                )
                assert callset is not None

                with path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader((line.replace("\r", "") for line in f), delimiter="\t")
                    for row in reader:
                        if not row:
                            continue
                        if row[0].startswith("#"):
                            if "build 37" in row[0].lower():
                                assembly = "GRCh37"
                            continue
                        if len(row) < 4:
                            continue
                        rsid, chrom, pos_text, genotype = row[0], row[1], row[2], row[3]
                        try:
                            pos = int(pos_text)
                        except ValueError:
                            continue
                        rows_read += 1
                        if max_rows and rows_read > max_rows:
                            break

                        key = _variant_key(assembly, chrom, pos, rsid)
                        variant = await conn.fetchrow(
                            """INSERT INTO variant_canonical (
                                   variant_key, rsid, assembly, chromosome, position, metadata
                               ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                               ON CONFLICT (variant_key)
                               DO UPDATE SET rsid = COALESCE(EXCLUDED.rsid, variant_canonical.rsid),
                                             updated_at = NOW()
                               RETURNING id""",
                            key,
                            rsid if rsid and rsid != "--" else None,
                            assembly,
                            chrom,
                            pos,
                            _to_json({"source": "23andme_raw"}),
                        )
                        assert variant is not None

                        zygosity = _infer_zygosity(genotype)
                        no_call = genotype == "--"

                        await conn.execute(
                            """INSERT INTO genotype_calls (
                                   callset_id, variant_id, rsid, chromosome, position, genotype, zygosity, no_call
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                               ON CONFLICT (callset_id, chromosome, position, COALESCE(rsid, ''))
                               DO UPDATE SET genotype = EXCLUDED.genotype,
                                             zygosity = EXCLUDED.zygosity,
                                             no_call = EXCLUDED.no_call""",
                            int(callset["id"]),
                            int(variant["id"]),
                            rsid if rsid and rsid != "--" else None,
                            chrom,
                            pos,
                            genotype,
                            zygosity,
                            no_call,
                        )
                        rows_written += 1

                await _finish_run(conn, run_id, "success", rows_read, rows_written)
                return _ok_response(
                    {
                    "ingestion_run_id": run_id,
                    "source_artifact_id": int(artifact["id"]),
                    "callset_id": int(callset["id"]),
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "assembly": assembly,
                    "sha256": sha,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", rows_read, rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="genome_ingest_failed",
                    payload={
                        "ingestion_run_id": run_id,
                        "rows_read": rows_read,
                        "rows_written": rows_written,
                    },
                )

    @_tool
    async def list_callsets(person_id: int | None = None) -> list[dict]:
        """List callsets, optionally filtered by subject."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            if person_id is None:
                rows = await conn.fetch(
                    """SELECT c.*, s.person_id
                       FROM callsets c
                       JOIN samples s ON s.id = c.sample_id
                       ORDER BY c.id DESC"""
                )
            else:
                rows = await conn.fetch(
                    """SELECT c.*, s.person_id
                       FROM callsets c
                       JOIN samples s ON s.id = c.sample_id
                       WHERE s.person_id = $1
                       ORDER BY c.id DESC""",
                    person_id,
                )
        return _rows_to_dicts(rows)

    @_tool
    async def query_genotype_calls(
        person_id: int,
        rsid: str = "",
        chromosome: str = "",
        position: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Query genotype calls by rsid or locus."""
        await ensure_initialized()
        pool = await get_pool()

        clauses = ["s.person_id = $1"]
        params: list[Any] = [person_id]
        idx = 2

        if rsid:
            clauses.append(f"gc.rsid = ${idx}")
            params.append(rsid)
            idx += 1
        if chromosome:
            clauses.append(f"gc.chromosome = ${idx}")
            params.append(chromosome)
            idx += 1
        if position > 0:
            clauses.append(f"gc.position = ${idx}")
            params.append(position)
            idx += 1

        params.append(max(1, min(limit, 1000)))
        query = (
            "SELECT gc.*, c.callset_name, s.person_id "
            "FROM genotype_calls gc "
            "JOIN callsets c ON c.id = gc.callset_id "
            "JOIN samples s ON s.id = c.sample_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY gc.id DESC LIMIT $" + str(idx)
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return _rows_to_dicts(rows)
