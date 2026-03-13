from __future__ import annotations

import json
import math
from datetime import date

import asyncpg

from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import normalize_currency_code as _normalize_currency_code
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import error_response as _error_response

from ips_scope_ops import (
    coerce_float as _coerce_float,
    normalize_bucket_key as _normalize_bucket_key,
    normalize_bucket_lookthrough_allocations as _normalize_bucket_lookthrough_allocations,
    normalize_scope_account_types as _normalize_scope_account_types,
    normalize_scope_value as _normalize_scope_value,
    parse_iso_date as _parse_iso_date,
    profile_matches_scope as _profile_matches_scope,
    profile_scope_score as _profile_scope_score,
)

VALID_SCOPE_ENTITY = {"all", "personal", "trust"}
VALID_SCOPE_WRAPPER = {"all", "taxable", "tax_deferred", "tax_exempt"}
VALID_SCOPE_OWNER = {"all", "Principal", "Spouse", "joint"}
VALID_PROFILE_STATUS = {"draft", "active", "archived"}


async def upsert_ips_target_profile(
    get_pool,
    profile_code: str,
    name: str,
    effective_from: str,
    status: str = "draft",
    profile_id: int | None = None,
    effective_to: str | None = None,
    base_currency: str = "USD",
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_owner: str = "all",
    scope_account_types: list[str] | str | None = None,
    drift_threshold: float = 0.03,
    rebalance_band_abs: float | None = None,
    review_cadence: str | None = None,
    notes: str | None = None,
    metadata: dict | str | None = None,
):
    clean_code = (profile_code or "").strip()
    clean_name = (name or "").strip()
    if not clean_code:
        return _error_response("profile_code is required", code="validation_error")
    if not clean_name:
        return _error_response("name is required", code="validation_error")

    normalized_status = (status or "draft").strip().lower()
    if normalized_status not in VALID_PROFILE_STATUS:
        return _error_response(
            f"status must be one of: {', '.join(sorted(VALID_PROFILE_STATUS))}",
            code="validation_error",
        )

    start_date, start_error = _parse_iso_date(effective_from, "effective_from")
    if start_error:
        return _error_response(start_error, code="validation_error")
    if start_date is None:
        return _error_response("effective_from is required", code="validation_error")

    end_date, end_error = _parse_iso_date(effective_to, "effective_to")
    if end_error:
        return _error_response(end_error, code="validation_error")
    if end_date and end_date < start_date:
        return _error_response("effective_to cannot be earlier than effective_from", code="validation_error")

    normalized_currency = _normalize_currency_code(base_currency)
    if not normalized_currency:
        return _error_response("base_currency must be a valid ISO-4217 code", code="validation_error")

    normalized_entity, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
    if err:
        return _error_response(err, code="validation_error")
    normalized_wrapper, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
    if err:
        return _error_response(err, code="validation_error")
    normalized_owner, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
    if err:
        return _error_response(err, code="validation_error")

    normalized_types, types_error = _normalize_scope_account_types(scope_account_types)
    if types_error:
        return _error_response(types_error, code="validation_error")

    clean_drift_threshold = max(0.0, float(drift_threshold))
    metadata_payload = _coerce_json_input(metadata)

    pool = await get_pool()
    if profile_id:
        row = await pool.fetchrow(
            """UPDATE ips_target_profiles
               SET profile_code=$1,
                   name=$2,
                   status=$3,
                   effective_from=$4,
                   effective_to=$5,
                   base_currency=$6,
                   scope_entity=$7,
                   scope_wrapper=$8,
                   scope_owner=$9,
                   scope_account_types=$10::text[],
                   drift_threshold=$11,
                   rebalance_band_abs=$12,
                   review_cadence=$13,
                   notes=$14,
                   metadata=$15::jsonb,
                   updated_at=now()
               WHERE id=$16
               RETURNING *""",
            clean_code,
            clean_name,
            normalized_status,
            start_date,
            end_date,
            normalized_currency,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
            clean_drift_threshold,
            rebalance_band_abs,
            review_cadence,
            notes,
            json.dumps(metadata_payload),
            profile_id,
        )
        if row is None:
            return _error_response(f"profile_id {profile_id} not found", code="not_found")
    else:
        row = await pool.fetchrow(
            """INSERT INTO ips_target_profiles (
                   profile_code, name, status, effective_from, effective_to,
                   base_currency, scope_entity, scope_wrapper, scope_owner,
                   scope_account_types, drift_threshold, rebalance_band_abs,
                   review_cadence, notes, metadata
               ) VALUES (
                   $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::text[],$11,$12,$13,$14,$15::jsonb
               )
               RETURNING *""",
            clean_code,
            clean_name,
            normalized_status,
            start_date,
            end_date,
            normalized_currency,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
            clean_drift_threshold,
            rebalance_band_abs,
            review_cadence,
            notes,
            json.dumps(metadata_payload),
        )

    return _row_to_dict(row)


async def upsert_ips_target_allocations(
    get_pool,
    profile_id: int,
    allocations: list[dict] | str,
    overwrite: bool = True,
):
    payload = allocations
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return _error_response(
                "allocations must be a JSON list when provided as string",
                code="validation_error",
            )

    if not isinstance(payload, list):
        return _error_response("allocations must be a list of objects", code="validation_error")

    pool = await get_pool()
    profile_exists = await pool.fetchval(
        "SELECT 1 FROM ips_target_profiles WHERE id = $1",
        profile_id,
    )
    if not profile_exists:
        return _error_response(f"profile_id {profile_id} not found", code="not_found")

    if overwrite:
        await pool.execute("DELETE FROM ips_target_allocations WHERE profile_id = $1", profile_id)

    inserted = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        bucket_key = _normalize_bucket_key(
            item.get("bucket_key") or item.get("bucket") or item.get("bucketKey")
        )
        if not bucket_key:
            return _error_response("Each allocation row requires bucket_key", code="validation_error")

        target_weight = _coerce_float(item.get("target_weight", item.get("target")), default=math.nan)
        if math.isnan(target_weight) or target_weight < 0:
            return _error_response(
                f"Invalid target_weight for bucket {bucket_key}",
                code="validation_error",
            )

        min_weight = item.get("min_weight")
        if min_weight is not None:
            min_weight = _coerce_float(min_weight, default=math.nan)
            if math.isnan(min_weight) or min_weight < 0:
                return _error_response(
                    f"Invalid min_weight for bucket {bucket_key}",
                    code="validation_error",
                )

        max_weight = item.get("max_weight")
        if max_weight is not None:
            max_weight = _coerce_float(max_weight, default=math.nan)
            if math.isnan(max_weight) or max_weight < 0:
                return _error_response(
                    f"Invalid max_weight for bucket {bucket_key}",
                    code="validation_error",
                )

        if min_weight is not None and min_weight > target_weight:
            return _error_response(
                f"min_weight cannot exceed target_weight for bucket {bucket_key}",
                code="validation_error",
            )
        if max_weight is not None and max_weight < target_weight:
            return _error_response(
                f"max_weight cannot be below target_weight for bucket {bucket_key}",
                code="validation_error",
            )

        tilt_tag = item.get("tilt_tag")
        if tilt_tag is not None:
            tilt_tag = str(tilt_tag).strip() or None

        metadata_payload = _coerce_json_input(item.get("metadata"))

        await pool.execute(
            """INSERT INTO ips_target_allocations (
                   profile_id, bucket_key, target_weight, min_weight, max_weight, tilt_tag, metadata
               ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
               ON CONFLICT (profile_id, bucket_key) DO UPDATE SET
                   target_weight = EXCLUDED.target_weight,
                   min_weight = EXCLUDED.min_weight,
                   max_weight = EXCLUDED.max_weight,
                   tilt_tag = EXCLUDED.tilt_tag,
                   metadata = EXCLUDED.metadata,
                   updated_at = now()""",
            profile_id,
            bucket_key,
            float(target_weight),
            min_weight,
            max_weight,
            tilt_tag,
            json.dumps(metadata_payload),
        )
        inserted += 1

    summary = await pool.fetchrow(
        """SELECT COUNT(*)::int AS allocation_count,
                  COALESCE(SUM(target_weight), 0)::float8 AS total_target_weight
           FROM ips_target_allocations
           WHERE profile_id = $1""",
        profile_id,
    )

    return {
        "profile_id": profile_id,
        "rows_upserted": inserted,
        "allocation_count": int(summary["allocation_count"]),
        "total_target_weight": float(summary["total_target_weight"]),
        "overwrite": overwrite,
    }


async def activate_ips_target_profile(get_pool, profile_id: int, tolerance: float = 0.0001):
    pool = await get_pool()
    profile = await pool.fetchrow("SELECT * FROM ips_target_profiles WHERE id = $1", profile_id)
    if profile is None:
        return _error_response(f"profile_id {profile_id} not found", code="not_found")

    rows = await pool.fetch(
        """SELECT bucket_key, target_weight, min_weight, max_weight
           FROM ips_target_allocations
           WHERE profile_id = $1
           ORDER BY bucket_key""",
        profile_id,
    )
    if not rows:
        return _error_response("Cannot activate profile without allocation rows", code="validation_error")

    tol = max(0.0, float(tolerance))
    total_weight = sum(float(r["target_weight"] or 0.0) for r in rows)
    if abs(total_weight - 1.0) > tol:
        return _error_response(
            "Allocation weights must sum to 1.0 before activation",
            code="validation_error",
            payload={
                "profile_id": profile_id,
                "total_target_weight": total_weight,
                "tolerance": tol,
            },
        )

    for row in rows:
        target = float(row["target_weight"] or 0.0)
        min_weight = row["min_weight"]
        max_weight = row["max_weight"]
        if min_weight is not None and float(min_weight) > target:
            return _error_response(
                f"min_weight exceeds target_weight for bucket {row['bucket_key']}",
                code="validation_error",
            )
        if max_weight is not None and float(max_weight) < target:
            return _error_response(
                f"max_weight below target_weight for bucket {row['bucket_key']}",
                code="validation_error",
            )

    activated = await pool.fetchrow(
        """UPDATE ips_target_profiles
           SET status = 'active',
               updated_at = now()
           WHERE id = $1
           RETURNING *""",
        profile_id,
    )

    return {
        "profile": _row_to_dict(activated),
        "allocation_count": len(rows),
        "total_target_weight": total_weight,
    }


async def list_ips_target_profiles(
    get_pool,
    status: str | None = None,
    scope_entity: str | None = None,
    scope_wrapper: str | None = None,
    scope_owner: str | None = None,
    as_of: str | None = None,
    limit: int = 200,
):
    pool = await get_pool()
    cap = max(1, min(limit, 2000))

    clauses: list[str] = []
    params: list = []

    if status:
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_PROFILE_STATUS:
            return _error_response(
                f"status must be one of: {', '.join(sorted(VALID_PROFILE_STATUS))}",
                code="validation_error",
            )
        params.append(normalized_status)
        clauses.append(f"status = ${len(params)}")

    if scope_entity:
        normalized, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_entity = ${len(params)}")

    if scope_wrapper:
        normalized, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_wrapper = ${len(params)}")

    if scope_owner:
        normalized, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_owner = ${len(params)}")

    if as_of:
        as_of_date, err = _parse_iso_date(as_of, "as_of")
        if err:
            return _error_response(err, code="validation_error")
        params.append(as_of_date)
        clauses.append(f"effective_from <= ${len(params)}")
        clauses.append(f"(effective_to IS NULL OR effective_to >= ${len(params)})")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(cap)

    rows = await pool.fetch(
        f"""SELECT *
            FROM ips_target_profiles
            {where_sql}
            ORDER BY updated_at DESC, id DESC
            LIMIT ${len(params)}""",
        *params,
    )
    return _rows_to_list(rows)


async def get_ips_target_profile(get_pool, profile_id: int):
    pool = await get_pool()
    profile = await pool.fetchrow("SELECT * FROM ips_target_profiles WHERE id = $1", profile_id)
    if profile is None:
        return _error_response(f"profile_id {profile_id} not found", code="not_found")

    allocations = await pool.fetch(
        """SELECT *
           FROM ips_target_allocations
           WHERE profile_id = $1
           ORDER BY bucket_key""",
        profile_id,
    )

    overrides = await pool.fetch(
        """SELECT *
           FROM ips_bucket_overrides
           WHERE active = TRUE
           ORDER BY symbol, scope_entity, scope_wrapper, scope_owner, id"""
    )
    lookthrough = await pool.fetch(
        """SELECT *
           FROM ips_bucket_lookthrough
           WHERE active = TRUE
           ORDER BY symbol, scope_entity, scope_wrapper, scope_owner, bucket_key, id"""
    )

    return {
        "profile": _row_to_dict(profile),
        "allocations": _rows_to_list(allocations),
        "active_bucket_overrides": _rows_to_list(overrides),
        "active_bucket_lookthrough": _rows_to_list(lookthrough),
    }


async def resolve_ips_target_profile(
    get_pool,
    as_of: str | None = None,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_owner: str = "all",
    scope_account_types: list[str] | str | None = None,
):
    normalized_entity, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
    if err:
        return _error_response(err, code="validation_error")
    normalized_wrapper, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
    if err:
        return _error_response(err, code="validation_error")
    normalized_owner, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
    if err:
        return _error_response(err, code="validation_error")

    normalized_types, types_error = _normalize_scope_account_types(scope_account_types)
    if types_error:
        return _error_response(types_error, code="validation_error")

    as_of_date, date_error = _parse_iso_date(as_of, "as_of")
    if date_error:
        return _error_response(date_error, code="validation_error")
    if as_of_date is None:
        as_of_date = date.today()

    pool = await get_pool()
    candidates = await pool.fetch(
        """SELECT *
           FROM ips_target_profiles
           WHERE status = 'active'
             AND effective_from <= $1
             AND (effective_to IS NULL OR effective_to >= $1)""",
        as_of_date,
    )

    ranked: list[dict] = []
    for row in candidates:
        item = _row_to_dict(row)
        if not _profile_matches_scope(
            item,
            scope_entity=normalized_entity or "all",
            scope_wrapper=normalized_wrapper or "all",
            scope_owner=normalized_owner or "all",
            scope_account_types=normalized_types,
        ):
            continue
        item["_precedence_score"] = _profile_scope_score(item)
        ranked.append(item)

    if not ranked:
        return _error_response(
            "No matching active IPS profile",
            code="not_found",
            payload={
                "as_of": as_of_date.isoformat(),
                "requested_scope": {
                    "entity": normalized_entity,
                    "wrapper": normalized_wrapper,
                    "owner": normalized_owner,
                    "account_types": normalized_types or "all",
                },
            },
        )

    ranked.sort(
        key=lambda item: (
            item.get("_precedence_score", 0),
            item.get("effective_from") or "",
            item.get("id") or 0,
        ),
        reverse=True,
    )
    selected = ranked[0]

    allocations = await pool.fetch(
        """SELECT *
           FROM ips_target_allocations
           WHERE profile_id = $1
           ORDER BY bucket_key""",
        selected["id"],
    )

    return {
        "resolved_profile": {k: v for k, v in selected.items() if not k.startswith("_")},
        "allocations": _rows_to_list(allocations),
        "resolution": {
            "as_of": as_of_date.isoformat(),
            "requested_scope": {
                "entity": normalized_entity,
                "wrapper": normalized_wrapper,
                "owner": normalized_owner,
                "account_types": normalized_types or "all",
            },
            "candidate_count": len(ranked),
            "selected_precedence_score": selected.get("_precedence_score", 0),
            "precedence_weights": {
                "owner_specific": 8,
                "account_type_specific": 4,
                "wrapper_specific": 2,
                "entity_specific": 1,
            },
        },
    }


async def upsert_ips_bucket_override(
    get_pool,
    symbol: str,
    override_bucket_key: str,
    data_source: str = "YAHOO",
    override_id: int | None = None,
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_owner: str = "all",
    scope_account_types: list[str] | str | None = None,
    active: bool = True,
    notes: str | None = None,
):
    clean_symbol = (symbol or "").strip().upper()
    if not clean_symbol:
        return _error_response("symbol is required", code="validation_error")

    bucket_key = _normalize_bucket_key(override_bucket_key)
    if not bucket_key:
        return _error_response("override_bucket_key is required", code="validation_error")

    clean_data_source = (data_source or "YAHOO").strip().upper() or "YAHOO"

    normalized_entity, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
    if err:
        return _error_response(err, code="validation_error")
    normalized_wrapper, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
    if err:
        return _error_response(err, code="validation_error")
    normalized_owner, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
    if err:
        return _error_response(err, code="validation_error")

    normalized_types, types_error = _normalize_scope_account_types(scope_account_types)
    if types_error:
        return _error_response(types_error, code="validation_error")

    pool = await get_pool()
    if override_id:
        row = await pool.fetchrow(
            """UPDATE ips_bucket_overrides
               SET symbol=$1,
                   data_source=$2,
                   override_bucket_key=$3,
                   scope_entity=$4,
                   scope_wrapper=$5,
                   scope_owner=$6,
                   scope_account_types=$7::text[],
                   active=$8,
                   notes=$9,
                   updated_at=now()
               WHERE id=$10
               RETURNING *""",
            clean_symbol,
            clean_data_source,
            bucket_key,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
            active,
            notes,
            override_id,
        )
        if row is None:
            return _error_response(f"override_id {override_id} not found", code="not_found")
    else:
        if active:
            await pool.execute(
                """UPDATE ips_bucket_overrides
                   SET active = FALSE,
                       updated_at = now()
                   WHERE active = TRUE
                     AND symbol = $1
                     AND data_source = $2
                     AND scope_entity = $3
                     AND scope_wrapper = $4
                     AND scope_owner = $5
                     AND COALESCE(scope_account_types, '{}'::text[]) = COALESCE($6::text[], '{}'::text[])""",
                clean_symbol,
                clean_data_source,
                normalized_entity,
                normalized_wrapper,
                normalized_owner,
                normalized_types,
            )

        row = await pool.fetchrow(
            """INSERT INTO ips_bucket_overrides (
                   symbol, data_source, override_bucket_key,
                   scope_entity, scope_wrapper, scope_owner, scope_account_types,
                   active, notes
               ) VALUES ($1,$2,$3,$4,$5,$6,$7::text[],$8,$9)
               RETURNING *""",
            clean_symbol,
            clean_data_source,
            bucket_key,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
            active,
            notes,
        )

    return _row_to_dict(row)


async def list_ips_bucket_overrides(
    get_pool,
    symbol: str | None = None,
    data_source: str | None = None,
    active_only: bool = True,
    scope_entity: str | None = None,
    scope_wrapper: str | None = None,
    scope_owner: str | None = None,
    limit: int = 500,
):
    pool = await get_pool()
    cap = max(1, min(limit, 5000))

    clauses: list[str] = []
    params: list = []

    if symbol:
        params.append(symbol.strip().upper())
        clauses.append(f"symbol = ${len(params)}")
    if data_source:
        params.append(data_source.strip().upper())
        clauses.append(f"data_source = ${len(params)}")
    if active_only:
        clauses.append("active = TRUE")

    if scope_entity:
        normalized, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_entity = ${len(params)}")

    if scope_wrapper:
        normalized, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_wrapper = ${len(params)}")

    if scope_owner:
        normalized, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_owner = ${len(params)}")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(cap)

    rows = await pool.fetch(
        f"""SELECT *
            FROM ips_bucket_overrides
            {where_sql}
            ORDER BY symbol, data_source, active DESC, updated_at DESC, id DESC
            LIMIT ${len(params)}""",
        *params,
    )
    return _rows_to_list(rows)


async def upsert_ips_bucket_lookthrough(
    get_pool,
    symbol: str,
    allocations: list[dict] | str,
    data_source: str = "YAHOO",
    scope_entity: str = "all",
    scope_wrapper: str = "all",
    scope_owner: str = "all",
    scope_account_types: list[str] | str | None = None,
    source_as_of: str | None = None,
    active: bool = True,
    notes: str | None = None,
    metadata: dict | str | None = None,
    overwrite: bool = True,
):
    clean_symbol = (symbol or "").strip().upper()
    if not clean_symbol:
        return _error_response("symbol is required", code="validation_error")

    clean_data_source = (data_source or "YAHOO").strip().upper() or "YAHOO"

    normalized_entity, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
    if err:
        return _error_response(err, code="validation_error")
    normalized_wrapper, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
    if err:
        return _error_response(err, code="validation_error")
    normalized_owner, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
    if err:
        return _error_response(err, code="validation_error")

    normalized_types, types_error = _normalize_scope_account_types(scope_account_types)
    if types_error:
        return _error_response(types_error, code="validation_error")

    as_of_date, date_error = _parse_iso_date(source_as_of, "source_as_of")
    if date_error:
        return _error_response(date_error, code="validation_error")

    normalized_allocations, alloc_error = _normalize_bucket_lookthrough_allocations(allocations)
    if alloc_error:
        return _error_response(alloc_error, code="validation_error")

    base_metadata = _coerce_json_input(metadata)
    pool = await get_pool()

    if overwrite:
        await pool.execute(
            """UPDATE ips_bucket_lookthrough
               SET active = FALSE,
                   updated_at = now()
               WHERE active = TRUE
                 AND symbol = $1
                 AND data_source = $2
                 AND scope_entity = $3
                 AND scope_wrapper = $4
                 AND scope_owner = $5
                 AND COALESCE(scope_account_types, '{}'::text[]) = COALESCE($6::text[], '{}'::text[])""",
            clean_symbol,
            clean_data_source,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
        )

    inserted_rows: list[asyncpg.Record] = []
    for item in normalized_allocations:
        merged_metadata = dict(base_metadata)
        merged_metadata.update(_coerce_json_input(item.get("metadata")))

        row = await pool.fetchrow(
            """INSERT INTO ips_bucket_lookthrough (
                   symbol, data_source, bucket_key, fraction_weight, source_as_of,
                   scope_entity, scope_wrapper, scope_owner, scope_account_types,
                   active, notes, metadata
               ) VALUES (
                   $1,$2,$3,$4,$5,$6,$7,$8,$9::text[],$10,$11,$12::jsonb
               )
               RETURNING *""",
            clean_symbol,
            clean_data_source,
            item["bucket_key"],
            item["fraction_weight"],
            as_of_date,
            normalized_entity,
            normalized_wrapper,
            normalized_owner,
            normalized_types,
            active,
            notes,
            json.dumps(merged_metadata),
        )
        inserted_rows.append(row)

    total_weight = sum(float(row["fraction_weight"] or 0.0) for row in inserted_rows)
    return {
        "symbol": clean_symbol,
        "data_source": clean_data_source,
        "scope": {
            "entity": normalized_entity,
            "wrapper": normalized_wrapper,
            "owner": normalized_owner,
            "account_types": normalized_types or "all",
        },
        "rows_upserted": len(inserted_rows),
        "total_fraction_weight": total_weight,
        "overwrite": overwrite,
        "rows": _rows_to_list(inserted_rows),
    }


async def list_ips_bucket_lookthrough(
    get_pool,
    symbol: str | None = None,
    data_source: str | None = None,
    active_only: bool = True,
    scope_entity: str | None = None,
    scope_wrapper: str | None = None,
    scope_owner: str | None = None,
    limit: int = 1000,
):
    pool = await get_pool()
    cap = max(1, min(limit, 5000))

    clauses: list[str] = []
    params: list = []

    if symbol:
        params.append(symbol.strip().upper())
        clauses.append(f"symbol = ${len(params)}")
    if data_source:
        params.append(data_source.strip().upper())
        clauses.append(f"data_source = ${len(params)}")
    if active_only:
        clauses.append("active = TRUE")

    if scope_entity:
        normalized, err = _normalize_scope_value(scope_entity, VALID_SCOPE_ENTITY, "scope_entity")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_entity = ${len(params)}")

    if scope_wrapper:
        normalized, err = _normalize_scope_value(scope_wrapper, VALID_SCOPE_WRAPPER, "scope_wrapper")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_wrapper = ${len(params)}")

    if scope_owner:
        normalized, err = _normalize_scope_value(scope_owner, VALID_SCOPE_OWNER, "scope_owner")
        if err:
            return _error_response(err, code="validation_error")
        params.append(normalized)
        clauses.append(f"scope_owner = ${len(params)}")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(cap)

    rows = await pool.fetch(
        f"""SELECT *
            FROM ips_bucket_lookthrough
            {where_sql}
            ORDER BY symbol, data_source, active DESC, bucket_key, updated_at DESC, id DESC
            LIMIT ${len(params)}""",
        *params,
    )
    return _rows_to_list(rows)
