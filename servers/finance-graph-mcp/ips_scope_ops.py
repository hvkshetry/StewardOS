import json
import math
import re
from datetime import date
from typing import Any

from stewardos_lib.db import float_or_none as _float_or_none
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input


def normalize_scope_value(
    value: str | None,
    allowed: set[str],
    field_name: str,
    default: str = "all",
) -> tuple[str | None, str | None]:
    if value is None:
        return default, None
    normalized = str(value).strip().lower()
    if not normalized:
        return default, None
    if normalized not in allowed:
        return None, f"{field_name} must be one of: {', '.join(sorted(allowed))}"
    return normalized, None


def normalize_scope_account_types(value) -> tuple[list[str] | None, str | None]:
    if value is None:
        return None, None

    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, None
        try:
            maybe = json.loads(raw)
            if isinstance(maybe, list):
                parsed = maybe
            else:
                parsed = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
        except json.JSONDecodeError:
            parsed = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]

    if not isinstance(parsed, list):
        return None, "scope_account_types must be a list (or JSON string list)"

    normalized = sorted({str(v).strip().lower() for v in parsed if str(v).strip()})
    return (normalized if normalized else None), None


def parse_iso_date(value: str | None, field_name: str) -> tuple[date | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, None
        try:
            return date.fromisoformat(raw), None
        except ValueError:
            return None, f"Invalid {field_name}: {value}"
    return None, f"{field_name} must be a YYYY-MM-DD string"


def normalize_bucket_key(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "_", value.strip().upper())


def normalize_bucket_lookthrough_allocations(value) -> tuple[list[dict], str | None]:
    payload = value
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return [], "allocations must be a JSON list when provided as string"

    if not isinstance(payload, list):
        return [], "allocations must be a list of objects"

    normalized: list[dict] = []
    raw_total = 0.0
    for item in payload:
        if not isinstance(item, dict):
            continue
        bucket_key = normalize_bucket_key(item.get("bucket_key") or item.get("bucket"))
        if not bucket_key:
            return [], "Each lookthrough allocation requires bucket_key"

        raw_weight = _float_or_none(item.get("fraction_weight", item.get("weight")))
        if raw_weight is None or not math.isfinite(raw_weight) or raw_weight <= 0:
            return [], f"Invalid fraction_weight for bucket {bucket_key}"

        normalized.append(
            {
                "bucket_key": bucket_key,
                "fraction_weight": float(raw_weight),
                "metadata": _coerce_json_input(item.get("metadata")),
            }
        )
        raw_total += float(raw_weight)

    if not normalized:
        return [], "allocations must contain at least one valid row"
    if raw_total <= 0:
        return [], "allocation weights must sum to a positive value"

    for row in normalized:
        row["fraction_weight"] = row["fraction_weight"] / raw_total

    return normalized, None


def profile_scope_score(profile: dict) -> int:
    score = 0
    if profile.get("scope_owner") and profile.get("scope_owner") != "all":
        score += 8
    if profile.get("scope_account_types"):
        score += 4
    if profile.get("scope_wrapper") and profile.get("scope_wrapper") != "all":
        score += 2
    if profile.get("scope_entity") and profile.get("scope_entity") != "all":
        score += 1
    return score


def profile_matches_scope(
    profile: dict,
    scope_entity: str,
    scope_wrapper: str,
    scope_owner: str,
    scope_account_types: list[str] | None,
) -> bool:
    profile_entity = (profile.get("scope_entity") or "all").strip().lower()
    profile_wrapper = (profile.get("scope_wrapper") or "all").strip().lower()
    profile_owner = (profile.get("scope_owner") or "all").strip().lower()

    if scope_entity != "all" and profile_entity not in {"all", scope_entity}:
        return False
    if scope_wrapper != "all" and profile_wrapper not in {"all", scope_wrapper}:
        return False
    if scope_owner != "all" and profile_owner not in {"all", scope_owner}:
        return False

    profile_types_raw = profile.get("scope_account_types")
    profile_types = (
        sorted({str(v).strip().lower() for v in profile_types_raw if str(v).strip()})
        if isinstance(profile_types_raw, list)
        else []
    )
    if profile_types:
        if scope_account_types is None:
            return False
        if sorted(scope_account_types) != profile_types:
            return False

    return True


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
