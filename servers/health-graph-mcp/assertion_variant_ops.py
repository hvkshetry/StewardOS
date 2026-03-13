from __future__ import annotations

from helpers import (
    _subject_has_genome_data,
    _subject_has_variant_match,
    _to_json,
    _variant_key,
)


async def ensure_subject_has_genome_data(conn, subject_id: int) -> None:
    if not await _subject_has_genome_data(conn, subject_id):
        raise ValueError(f"subject_id {subject_id} has no genotype data")


async def resolve_subject_variant_id(
    conn,
    *,
    subject_id: int,
    source_name: str,
    rsid: str | None,
    chrom: str | None,
    pos_int: int | None,
) -> int | None:
    if not await _subject_has_variant_match(conn, subject_id, rsid, chrom, pos_int):
        return None

    if chrom and pos_int is not None:
        key = _variant_key("GRCh37", chrom, pos_int, rsid)
        variant = await conn.fetchrow(
            """INSERT INTO variant_canonical (
                   variant_key, rsid, assembly, chromosome, position, metadata
               ) VALUES ($1,$2,'GRCh37',$3,$4,$5::jsonb)
               ON CONFLICT (variant_key)
               DO UPDATE SET rsid = COALESCE(EXCLUDED.rsid, variant_canonical.rsid)
               RETURNING id""",
            key,
            rsid,
            chrom,
            pos_int,
            _to_json({"source": source_name}),
        )
        assert variant is not None
        return int(variant["id"])

    if rsid:
        variant = await conn.fetchrow(
            """SELECT vc.id
               FROM variant_canonical vc
               JOIN genotype_calls gc ON gc.variant_id = vc.id
               JOIN callsets c ON c.id = gc.callset_id
               JOIN samples s ON s.id = c.sample_id
               WHERE s.subject_id = $1 AND gc.rsid = $2
               ORDER BY vc.id DESC
               LIMIT 1""",
            subject_id,
            rsid,
        )
        if variant is not None:
            return int(variant["id"])

    return None
