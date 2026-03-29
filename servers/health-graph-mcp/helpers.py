from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import asyncpg

_PLACEHOLDER_TOKEN_RE = re.compile(
    r"\b(smoke|placeholder|example|dummy|mock|unknown[_\s-]?trait)\b",
    re.IGNORECASE,
)

_ALLOWED_ACTION_CLASSES = {
    "actionable_with_guardrails",
    "review_required",
    "context_only",
    "research_only",
}

_RSID_RE = re.compile(r"\brs[0-9]{2,}\b", re.IGNORECASE)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=_json_default)


def _row_to_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    payload: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, (date, datetime)):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload


def _rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict]:
    return [_row_to_dict(r) for r in rows if r is not None]


def _looks_like_json(raw: str) -> bool:
    return raw.startswith("{") or raw.startswith("[")


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if not lines:
        return text
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    if lines and lines[0].strip().lower() == "json":
        lines = lines[1:]
    return "\n".join(lines).strip()


def _try_json_loads(raw: str) -> Any | None:
    text = raw.strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, str):
        nested = loaded.strip()
        if _looks_like_json(nested):
            try:
                return json.loads(nested)
            except json.JSONDecodeError:
                return loaded
    return loaded


def _looks_like_probable_file_path(raw: str) -> bool:
    if not raw:
        return False
    if len(raw) > 512:
        return False
    if "\n" in raw or "\r" in raw:
        return False
    if _looks_like_json(raw):
        return False
    return True


def _read_json_input(value: str | dict | list) -> Any:
    if isinstance(value, (dict, list)):
        return value
    raw = _strip_json_fence(str(value).strip())
    if not raw:
        return {}

    if _looks_like_json(raw):
        parsed = _try_json_loads(raw)
        if parsed is not None:
            return parsed

    if _looks_like_json(raw):
        return json.loads(raw)
    if _looks_like_probable_file_path(raw):
        try:
            path = Path(raw).expanduser()
            if path.is_file():
                file_raw = _strip_json_fence(path.read_text(encoding="utf-8"))
                parsed = _try_json_loads(file_raw)
                if parsed is not None:
                    return parsed
                return json.loads(file_raw)
        except OSError:
            pass
    parsed = _try_json_loads(raw)
    if parsed is not None:
        return parsed
    return json.loads(raw)


def _contains_placeholder(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_PLACEHOLDER_TOKEN_RE.search(value))
    if isinstance(value, dict):
        return any(_contains_placeholder(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_placeholder(v) for v in value)
    return False


def _validate_source_name(source_name: str) -> None:
    if not source_name or not source_name.strip():
        raise ValueError("source_name is required")
    if _contains_placeholder(source_name):
        raise ValueError("source_name appears to be placeholder/test data")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_evidence_tier(value: Any, default: int = 4) -> int:
    tier = _safe_int(value)
    if tier is None:
        tier = default
    return max(1, min(tier, 4))


def _normalize_action_class(action_class: str | None, evidence_tier: int) -> str:
    candidate = (action_class or "").strip().lower()
    if candidate in _ALLOWED_ACTION_CLASSES:
        return candidate
    if evidence_tier <= 1:
        return "actionable_with_guardrails"
    if evidence_tier == 2:
        return "review_required"
    if evidence_tier == 3:
        return "context_only"
    return "research_only"


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_rsids(value: Any) -> set[str]:
    found: set[str] = set()

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            for match in _RSID_RE.findall(node):
                found.add(match.lower())
            return
        if isinstance(node, dict):
            for key, nested in node.items():
                if isinstance(key, str):
                    for match in _RSID_RE.findall(key):
                        found.add(match.lower())
                _walk(nested)
            return
        if isinstance(node, (list, tuple, set)):
            for nested in node:
                _walk(nested)

    _walk(value)
    return found


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
            continue
        if isinstance(value, list):
            if value:
                return _first_nonempty(value[0])
            continue
        if isinstance(value, dict):
            maybe = _first_nonempty(
                value.get("label"),
                value.get("name"),
                value.get("value"),
                value.get("display"),
            )
            if maybe:
                return maybe
        else:
            return str(value)
    return None


def _infer_zygosity(genotype: str) -> str:
    gt = (genotype or "").strip()
    if gt == "--":
        return "no_call"
    if len(gt) != 2:
        return "unknown"
    if gt[0] == gt[1]:
        return "homozygous"
    return "heterozygous"


def _variant_key(assembly: str, chromosome: str, position: int, rsid: str | None) -> str:
    return f"{assembly}:{chromosome}:{position}:{(rsid or '.')}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _start_run(conn: asyncpg.Connection, source_name: str, run_type: str, metadata: dict | None = None) -> int:
    row = await conn.fetchrow(
        """INSERT INTO ingestion_runs (source_name, run_type, metadata)
           VALUES ($1, $2, $3::jsonb)
           RETURNING id""",
        source_name,
        run_type,
        _to_json(metadata or {}),
    )
    assert row is not None
    return int(row["id"])


async def _finish_run(
    conn: asyncpg.Connection,
    run_id: int,
    status: str,
    rows_read: int,
    rows_written: int,
    error_message: str | None = None,
) -> None:
    await conn.execute(
        """UPDATE ingestion_runs
           SET status=$2,
               rows_read=$3,
               rows_written=$4,
               error_message=$5,
               finished_at=NOW()
           WHERE id=$1""",
        run_id,
        status,
        rows_read,
        rows_written,
        error_message,
    )


async def _policy_for_tier(conn: asyncpg.Connection, evidence_tier: int, action_class: str) -> dict:
    row = await conn.fetchrow(
        """SELECT evidence_tier, action_class, allow_direct_action, research_mode_only, notes
           FROM recommendation_policy_rules
           WHERE evidence_tier=$1 AND action_class=$2""",
        evidence_tier,
        action_class,
    )
    if row:
        return _row_to_dict(row) or {}
    return {
        "evidence_tier": evidence_tier,
        "action_class": action_class,
        "allow_direct_action": False,
        "research_mode_only": evidence_tier >= 4,
        "notes": "fallback policy",
    }


async def _subject_has_genome_data(conn: asyncpg.Connection, person_id: int) -> bool:
    row = await conn.fetchrow(
        """SELECT 1
           FROM samples s
           JOIN callsets c ON c.sample_id = s.id
           JOIN genotype_calls gc ON gc.callset_id = c.id
           WHERE s.person_id = $1
           LIMIT 1""",
        person_id,
    )
    return row is not None


async def _subject_has_variant_match(
    conn: asyncpg.Connection,
    person_id: int,
    rsid: str | None,
    chromosome: str | None,
    position: int | None,
) -> bool:
    if not rsid and (not chromosome or position is None):
        return False

    row = await conn.fetchrow(
        """SELECT 1
           FROM genotype_calls gc
           JOIN callsets c ON c.id = gc.callset_id
           JOIN samples s ON s.id = c.sample_id
           WHERE s.person_id = $1
             AND (
               ($2::text IS NOT NULL AND gc.rsid = $2)
               OR ($3::text IS NOT NULL AND $4::int IS NOT NULL AND gc.chromosome = $3 AND gc.position = $4)
             )
           LIMIT 1""",
        person_id,
        rsid,
        chromosome,
        position,
    )
    return row is not None


async def _subject_has_any_rsid_match(conn: asyncpg.Connection, person_id: int, rsids: set[str]) -> bool:
    normalized = sorted({r.lower() for r in rsids if r})
    if not normalized:
        return False
    row = await conn.fetchrow(
        """SELECT 1
           FROM genotype_calls gc
           JOIN callsets c ON c.id = gc.callset_id
           JOIN samples s ON s.id = c.sample_id
           WHERE s.person_id = $1
             AND lower(gc.rsid) = ANY($2::text[])
           LIMIT 1""",
        person_id,
        normalized,
    )
    return row is not None


async def _subject_variant_for_rsid(
    conn: asyncpg.Connection,
    person_id: int,
    rsid: str,
) -> dict | None:
    row = await conn.fetchrow(
        """SELECT vc.id AS variant_id, gc.rsid, gc.genotype, gc.chromosome, gc.position
           FROM genotype_calls gc
           JOIN callsets c ON c.id = gc.callset_id
           JOIN samples s ON s.id = c.sample_id
           LEFT JOIN variant_canonical vc ON vc.id = gc.variant_id
           WHERE s.person_id = $1
             AND lower(gc.rsid) = lower($2)
           ORDER BY gc.id DESC
           LIMIT 1""",
        person_id,
        rsid,
    )
    return _row_to_dict(row)


def _has_risk_allele(genotype: str | None, risk_alleles: set[str]) -> bool:
    if not genotype:
        return False
    gt = genotype.strip().upper()
    if len(gt) != 2:
        return False
    return any(allele in gt for allele in {a.upper() for a in risk_alleles})


async def _upsert_evidence_link(
    conn: asyncpg.Connection,
    literature_evidence_id: int,
    assertion_id: int | None = None,
    variant_id: int | None = None,
    trait_association_id: int | None = None,
    notes: str | None = None,
) -> None:
    await conn.execute(
        """INSERT INTO evidence_links (
               literature_evidence_id, assertion_id, variant_id, trait_association_id, notes
           ) VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (
               literature_evidence_id,
               COALESCE(assertion_id, 0),
               COALESCE(variant_id, 0),
               COALESCE(trait_association_id, 0),
               COALESCE(notes, '')
           )
           DO NOTHING""",
        literature_evidence_id,
        assertion_id,
        variant_id,
        trait_association_id,
        notes,
    )


def _parse_tiers_arg(tiers: str | list[int] | list[str]) -> list[int]:
    raw_items: list[Any]
    if isinstance(tiers, str):
        raw_items = [part.strip() for part in tiers.split(",") if part.strip()]
    elif isinstance(tiers, list):
        raw_items = tiers
    else:
        raw_items = [1, 2, 3, 4]

    normalized: set[int] = set()
    for item in raw_items:
        tier = _safe_int(item)
        if tier is None:
            continue
        normalized.add(max(1, min(tier, 4)))
    if not normalized:
        return [1, 2, 3, 4]
    return sorted(normalized)
