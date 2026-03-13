"""MCP server for wger workout and nutrition tracking."""

import csv
import hashlib
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


WGER_URL = os.environ.get("WGER_URL", "http://localhost:8280")
WGER_API_TOKEN = os.environ.get("WGER_API_TOKEN", "")
FITBOD_MAPPING_PATH = Path(
    os.environ.get("FITBOD_MAPPING_PATH", "/tmp/wger-fitbod-exercise-map.json")
)
FITBOD_IMPORT_LEDGER_PATH = Path(
    os.environ.get("FITBOD_IMPORT_LEDGER_PATH", "/tmp/wger-fitbod-import-ledger.json")
)
FITBOD_DEFAULT_TIMEZONE = os.environ.get("FITBOD_DEFAULT_TIMEZONE", "")
FITBOD_REVIEW_COVERAGE_TARGET = 0.90
FITBOD_REVIEW_WINDOWS_DAYS = (30, 90, 365)

FITBOD_PHRASE_NORMALIZATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhammer\s*curls?\b"), "hammer curl"),
    (re.compile(r"\bpush[\s-]*ups?\b"), "push up"),
    (re.compile(r"\bpull[\s-]*ups?\b"), "pull up"),
    (re.compile(r"\bchin[\s-]*ups?\b"), "chin up"),
    (re.compile(r"\bsit[\s-]*ups?\b"), "sit up"),
    (re.compile(r"\bpress[\s-]*ups?\b"), "push up"),
    (re.compile(r"\blat\s+pull\s*downs?\b"), "lat pulldown"),
    (re.compile(r"\bpull\s*downs?\b"), "pulldown"),
    (re.compile(r"\bhand\s+release\b"), "hand release"),
)

FITBOD_TOKEN_NORMALIZATIONS: dict[str, str] = {
    "running": "run",
    "walking": "walk",
    "bicep": "biceps",
    "tricep": "triceps",
    "bike": "cycling",
    "curls": "curl",
    "raises": "raise",
    "dips": "dip",
    "lunges": "lunge",
    "extensions": "extension",
    "kickbacks": "kickback",
    "crunches": "crunch",
    "rows": "row",
    "pullups": "pull up",
    "pushups": "push up",
    "chinups": "chin up",
    "situps": "sit up",
    "hammercurls": "hammer curl",
}

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP(
    "wger-mcp",
    instructions=(
        "wger workout and nutrition tracking server. Provides tools to view "
        "workout routines, log exercises, track body weight and measurements, "
        "and manage nutrition plans. Uses the wger REST API v2."
    ),
)

FITBOD_IMPORT_STATUS: dict[str, dict[str, Any]] = {}


@dataclass
class FitbodRow:
    """Normalized representation of one FitBod CSV row."""

    row_number: int
    source_file: str
    raw_date: str
    timestamp: datetime
    timestamp_iso: str
    session_key: str
    workout_date: str
    exercise: str
    reps: float | None
    weight_kg: float | None
    duration_s: float | None
    distance_m: float | None
    incline: float | None
    resistance: float | None
    is_warmup: bool
    note: str
    multiplier: float | None
    dedupe_hash: str


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token {WGER_API_TOKEN}",
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=WGER_URL,
        headers=_headers(),
        timeout=30.0,
    )


async def _get(path: str, params: dict | None = None) -> dict | list | str:
    """Execute a GET request against the wger API."""
    try:
        async with _client() as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


async def _post(path: str, payload: dict) -> dict | str:
    """Execute a POST request against the wger API."""
    try:
        async with _client() as client:
            resp = await client.post(path, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


async def _patch(path: str, payload: dict) -> dict | str:
    """Execute a PATCH request against the wger API."""
    try:
        async with _client() as client:
            resp = await client.patch(path, json=payload)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _mapping_store() -> dict[str, Any]:
    raw = _read_json(FITBOD_MAPPING_PATH, {"aliases": {}, "metadata": {}, "updated_at": None})
    if not isinstance(raw, dict):
        return {"aliases": {}, "metadata": {}, "updated_at": None}

    raw_aliases = raw.get("aliases")
    if not isinstance(raw_aliases, dict):
        raw_aliases = {key: value for key, value in raw.items() if key not in {"metadata", "updated_at"}}

    aliases: dict[str, int] = {}
    for key, value in raw_aliases.items():
        normalized = _normalize_exercise_name(str(key))
        if not normalized:
            continue
        try:
            aliases[normalized] = int(value)
        except (TypeError, ValueError):
            continue

    raw_metadata = raw.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    normalized_metadata = {
        _normalize_exercise_name(str(key)): value
        for key, value in metadata.items()
        if _normalize_exercise_name(str(key))
    }

    return {
        "aliases": aliases,
        "metadata": normalized_metadata,
        "updated_at": raw.get("updated_at"),
    }


def _save_mapping_store(store: dict[str, Any]) -> None:
    store["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_json(FITBOD_MAPPING_PATH, store)


def _ledger_store() -> dict[str, Any]:
    return _read_json(FITBOD_IMPORT_LEDGER_PATH, {"items": {}, "updated_at": None})


def _save_ledger_store(store: dict[str, Any]) -> None:
    store["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_json(FITBOD_IMPORT_LEDGER_PATH, store)


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_fitbod_datetime(raw_value: str, timezone_name: str = "") -> datetime:
    raw_value = raw_value.strip()
    formats = (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    )

    parsed: datetime | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw_value, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        parsed = datetime.fromisoformat(raw_value)

    if parsed.tzinfo is None:
        tz_name = timezone_name.strip() or FITBOD_DEFAULT_TIMEZONE
        if tz_name and ZoneInfo is not None:
            parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed


def _normalize_exercise_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    if not text:
        return ""

    text = re.sub(r"[&/+,]", " ", text)
    text = re.sub(r"[-_()]+", " ", text)
    text = text.replace("'", "")
    text = re.sub(r"\s+", " ", text).strip()

    for pattern, replacement in FITBOD_PHRASE_NORMALIZATIONS:
        text = pattern.sub(replacement, text)

    normalized_tokens: list[str] = []
    for token in text.split():
        replacement = FITBOD_TOKEN_NORMALIZATIONS.get(token, token)
        if not replacement:
            continue
        normalized_tokens.extend(replacement.split())

    return " ".join(normalized_tokens)


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(_normalize_exercise_name(left).split())
    right_tokens = set(_normalize_exercise_name(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    if union == 0:
        return 0.0
    return intersection / union


def _candidate_score(source_name: str, candidate_label: str) -> dict[str, Any]:
    source = _normalize_exercise_name(source_name)
    candidate = _normalize_exercise_name(candidate_label)
    source_tokens = source.split()
    candidate_tokens = candidate.split()
    token_score = _token_similarity(source, candidate)
    sequence_score = SequenceMatcher(None, source, candidate).ratio() if source and candidate else 0.0
    exact = source == candidate and bool(source)
    shared_prefix = bool(source_tokens and candidate_tokens and source_tokens[0] == candidate_tokens[0])
    containment = bool(source and candidate and (source in candidate or candidate in source))
    score = max(token_score, sequence_score)
    if shared_prefix:
        score += 0.05
    if containment:
        score += 0.05
    score = min(score, 1.0)

    if exact:
        confidence = "high"
    elif score >= 0.88:
        confidence = "high"
    elif score >= 0.72:
        confidence = "medium"
    elif score >= 0.55:
        confidence = "low"
    else:
        confidence = "none"

    return {
        "score": round(score, 3),
        "token_score": round(token_score, 3),
        "sequence_score": round(sequence_score, 3),
        "normalized_label": candidate,
        "exact": exact,
        "shared_prefix": shared_prefix,
        "containment": containment,
        "confidence": confidence,
    }


def _dedupe_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _parse_fitbod_rows(
    file_path: str,
    timezone: str = "",
) -> tuple[list[FitbodRow], dict[str, Any]]:
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"CSV not found: {source}")

    parsed_rows: list[FitbodRow] = []
    errors: list[str] = []

    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "Date",
            "Exercise",
            "Reps",
            "Weight(kg)",
            "Duration(s)",
            "Distance(m)",
            "Incline",
            "Resistance",
            "isWarmup",
            "Note",
            "multiplier",
        }
        header = set(reader.fieldnames or [])
        missing = required - header
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")

        for idx, row in enumerate(reader, start=2):
            try:
                raw_date = (row.get("Date") or "").strip()
                exercise = (row.get("Exercise") or "").strip()
                if not raw_date or not exercise:
                    errors.append(f"row {idx}: missing Date or Exercise")
                    continue

                timestamp = _parse_fitbod_datetime(raw_date, timezone)
                timestamp_iso = timestamp.isoformat()
                session_key = timestamp_iso
                workout_date = timestamp.date().isoformat()

                payload_for_hash = {
                    "date": raw_date,
                    "exercise": exercise,
                    "reps": _to_float(row.get("Reps")),
                    "weight_kg": _to_float(row.get("Weight(kg)")),
                    "duration_s": _to_float(row.get("Duration(s)")),
                    "distance_m": _to_float(row.get("Distance(m)")),
                    "incline": _to_float(row.get("Incline")),
                    "resistance": _to_float(row.get("Resistance")),
                    "is_warmup": _to_bool(row.get("isWarmup")),
                    "note": (row.get("Note") or "").strip(),
                    "multiplier": _to_float(row.get("multiplier")),
                }

                parsed_rows.append(
                    FitbodRow(
                        row_number=idx,
                        source_file=source.name,
                        raw_date=raw_date,
                        timestamp=timestamp,
                        timestamp_iso=timestamp_iso,
                        session_key=session_key,
                        workout_date=workout_date,
                        exercise=exercise,
                        reps=payload_for_hash["reps"],
                        weight_kg=payload_for_hash["weight_kg"],
                        duration_s=payload_for_hash["duration_s"],
                        distance_m=payload_for_hash["distance_m"],
                        incline=payload_for_hash["incline"],
                        resistance=payload_for_hash["resistance"],
                        is_warmup=payload_for_hash["is_warmup"],
                        note=payload_for_hash["note"],
                        multiplier=payload_for_hash["multiplier"],
                        dedupe_hash=_dedupe_hash(payload_for_hash),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive row parsing
                errors.append(f"row {idx}: {exc}")

    summary = {
        "source_file": str(source),
        "rows_total": len(parsed_rows),
        "rows_with_errors": len(errors),
        "errors": errors[:25],
        "date_min": min((r.workout_date for r in parsed_rows), default=None),
        "date_max": max((r.workout_date for r in parsed_rows), default=None),
        "unique_exercises": len({_normalize_exercise_name(r.exercise) for r in parsed_rows}),
        "unique_sessions": len({r.session_key for r in parsed_rows}),
    }
    return parsed_rows, summary


def _fitbod_row_stats(rows: list[FitbodRow]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_exercise_name(row.exercise)
        if not normalized:
            continue
        current = stats.get(normalized)
        if current is None:
            stats[normalized] = {
                "exercise": row.exercise,
                "normalized": normalized,
                "row_count": 1,
                "last_seen": row.timestamp,
                "last_seen_iso": row.timestamp_iso,
            }
            continue

        current["row_count"] += 1
        if row.timestamp >= current["last_seen"]:
            current["exercise"] = row.exercise
            current["last_seen"] = row.timestamp
            current["last_seen_iso"] = row.timestamp_iso
    return stats


def _fitbod_coverage_summary(
    rows: list[FitbodRow],
    preview_items: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not rows:
        empty_window = {
            "window": "all",
            "days": None,
            "total_rows": 0,
            "mapped_rows": 0,
            "suggested_rows": 0,
            "unmapped_rows": 0,
            "weighted_coverage_pct": 0.0,
            "weighted_coverage_pct_with_suggestions": 0.0,
        }
        return {
            "target_weighted_coverage_pct": round(FITBOD_REVIEW_COVERAGE_TARGET * 100, 1),
            "all_time": empty_window,
            "windows": [],
        }

    latest_timestamp = max(row.timestamp for row in rows)
    windows: list[tuple[str, int | None, datetime | None]] = [("all", None, None)]
    for days in FITBOD_REVIEW_WINDOWS_DAYS:
        windows.append((f"trailing_{days}d", days, latest_timestamp - timedelta(days=days)))

    output: list[dict[str, Any]] = []
    for label, days, cutoff in windows:
        subset = rows if cutoff is None else [row for row in rows if row.timestamp >= cutoff]
        total_rows = len(subset)
        mapped_rows = 0
        suggested_rows = 0
        for row in subset:
            normalized = _normalize_exercise_name(row.exercise)
            preview = preview_items.get(normalized, {})
            if preview.get("status") == "mapped":
                mapped_rows += 1
            elif preview.get("status") == "review_required" and preview.get("suggested_exercise_id"):
                suggested_rows += 1

        uncovered_rows = max(0, total_rows - mapped_rows)
        weighted = round((mapped_rows / total_rows) * 100, 2) if total_rows else 0.0
        weighted_with_suggestions = (
            round(((mapped_rows + suggested_rows) / total_rows) * 100, 2) if total_rows else 0.0
        )
        output.append(
            {
                "window": label,
                "days": days,
                "total_rows": total_rows,
                "mapped_rows": mapped_rows,
                "suggested_rows": suggested_rows,
                "unmapped_rows": uncovered_rows,
                "weighted_coverage_pct": weighted,
                "weighted_coverage_pct_with_suggestions": weighted_with_suggestions,
            }
        )

    return {
        "target_weighted_coverage_pct": round(FITBOD_REVIEW_COVERAGE_TARGET * 100, 1),
        "all_time": output[0],
        "windows": output[1:],
    }


def _priority_queue(
    stats: dict[str, dict[str, Any]],
    preview_items: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for normalized, item in preview_items.items():
        if item.get("status") == "mapped":
            continue
        stat = stats.get(normalized)
        if not stat:
            continue
        queue.append(
            {
                "exercise": stat["exercise"],
                "normalized": normalized,
                "row_count": stat["row_count"],
                "last_seen": stat["last_seen_iso"],
                "status": item.get("status"),
                "suggested_exercise_id": item.get("suggested_exercise_id"),
                "suggested_label": item.get("suggested_label"),
                "suggestion_confidence": item.get("suggestion_confidence"),
                "suggestion_score": item.get("suggestion_score"),
                "candidate_gap": item.get("candidate_gap"),
            }
        )
    queue.sort(key=lambda item: (item["row_count"], item["last_seen"]), reverse=True)
    return queue


def _coverage_target_met(coverage_summary: dict[str, Any]) -> bool:
    target_pct = round(FITBOD_REVIEW_COVERAGE_TARGET * 100, 1)
    for window in coverage_summary.get("windows", []):
        if window.get("window") == "trailing_365d":
            return float(window.get("weighted_coverage_pct", 0.0)) >= target_pct
    return float(coverage_summary.get("all_time", {}).get("weighted_coverage_pct", 0.0)) >= target_pct


async def _validate_wger_exercise_id(exercise_id: int) -> dict[str, Any]:
    result = await _get(f"/api/v2/exercise/{exercise_id}/", params={"format": "json"})
    if isinstance(result, str):
        return {"ok": False, "error": result}
    if not isinstance(result, dict) or int(result.get("id", 0) or 0) != int(exercise_id):
        return {"ok": False, "error": "exercise_id did not resolve to a valid wger exercise"}
    return {"ok": True, "exercise": result}


async def _search_wger_exercise(term: str, language: int = 2) -> dict[str, Any] | str:
    result = await _get(
        "/api/v2/exercise/search/",
        params={"format": "json", "term": term, "language": language},
    )
    if isinstance(result, str):
        return result
    return result if isinstance(result, dict) else {"suggestions": []}


async def _build_fitbod_mapping_preview(
    rows: list[FitbodRow],
    language: int = 2,
    top_k: int = 5,
) -> dict[str, Any]:
    mapping_store = _mapping_store()
    aliases: dict[str, int] = {
        key: int(value) for key, value in mapping_store.get("aliases", {}).items()
    }
    metadata: dict[str, Any] = mapping_store.get("metadata", {})
    stats = _fitbod_row_stats(rows)

    preview_by_name: dict[str, dict[str, Any]] = {}

    for normalized, stat in stats.items():
        display_name = stat["exercise"]
        if normalized in aliases:
            stored_metadata = metadata.get(normalized, {}) if isinstance(metadata.get(normalized), dict) else {}
            preview_by_name[normalized] = {
                "exercise": display_name,
                "normalized": normalized,
                "status": "mapped",
                "exercise_id": aliases[normalized],
                "source": "alias_map",
                "row_count": stat["row_count"],
                "last_seen": stat["last_seen_iso"],
                "metadata": stored_metadata,
            }
            continue

        search_result = await _search_wger_exercise(display_name, language=language)
        if isinstance(search_result, str):
            preview_by_name[normalized] = {
                "exercise": display_name,
                "normalized": normalized,
                "status": "error",
                "error": search_result,
                "row_count": stat["row_count"],
                "last_seen": stat["last_seen_iso"],
                "candidates": [],
            }
            continue

        suggestions = search_result.get("suggestions", [])[: max(1, top_k)]
        compact = []
        for item in suggestions:
            data = item.get("data") or {}
            match = _candidate_score(display_name, item.get("value") or "")
            compact.append(
                {
                    "label": item.get("value"),
                    "exercise_id": data.get("base_id") or data.get("id"),
                    "category": data.get("category"),
                    "score": match["score"],
                    "confidence": match["confidence"],
                    "exact": match["exact"],
                    "normalized_label": match["normalized_label"],
                }
            )

        compact.sort(
            key=lambda item: (item.get("score", 0.0), item.get("exact", False), item.get("label") or ""),
            reverse=True,
        )
        best = compact[0] if compact else None
        runner_up = compact[1] if len(compact) > 1 else None
        gap = None
        if best and runner_up:
            gap = round(float(best.get("score", 0.0)) - float(runner_up.get("score", 0.0)), 3)

        confidence = best.get("confidence") if best else "none"
        confidence_is_actionable = confidence in {"high", "medium"} and (gap is None or gap >= 0.08)
        if best and best.get("exercise_id") and confidence_is_actionable:
            preview_by_name[normalized] = {
                "exercise": display_name,
                "normalized": normalized,
                "status": "review_required",
                "row_count": stat["row_count"],
                "last_seen": stat["last_seen_iso"],
                "suggested_exercise_id": int(best["exercise_id"]),
                "suggested_label": best.get("label"),
                "suggestion_confidence": confidence,
                "suggestion_score": best.get("score"),
                "candidate_gap": gap,
                "candidates": compact,
            }
        else:
            preview_by_name[normalized] = {
                "exercise": display_name,
                "normalized": normalized,
                "status": "unmapped",
                "row_count": stat["row_count"],
                "last_seen": stat["last_seen_iso"],
                "suggested_exercise_id": int(best["exercise_id"]) if best and best.get("exercise_id") else None,
                "suggested_label": best.get("label") if best else None,
                "suggestion_confidence": confidence,
                "suggestion_score": best.get("score") if best else None,
                "candidate_gap": gap,
                "candidates": compact,
            }

    preview = sorted(
        preview_by_name.values(),
        key=lambda item: (item.get("row_count", 0), item.get("last_seen") or "", item.get("exercise") or ""),
        reverse=True,
    )
    coverage_summary = _fitbod_coverage_summary(rows, preview_by_name)
    priority_queue = _priority_queue(stats, preview_by_name)
    mapped_count = sum(1 for item in preview if item.get("status") == "mapped")
    review_count = sum(1 for item in preview if item.get("status") == "review_required")
    unresolved_count = len(preview) - mapped_count - review_count

    return {
        "summary": {
            "unique_exercises": len(stats),
            "mapped": mapped_count,
            "review_required": review_count,
            "unmapped": unresolved_count,
            "mapping_path": str(FITBOD_MAPPING_PATH),
            "target_weighted_coverage_pct": round(FITBOD_REVIEW_COVERAGE_TARGET * 100, 1),
        },
        "coverage_summary": coverage_summary,
        "priority_queue": priority_queue,
        "mapping": preview,
    }


def _row_to_preview_dict(row: FitbodRow, mapped_id: int | None = None) -> dict[str, Any]:
    data = {
        "row_number": row.row_number,
        "workout_date": row.workout_date,
        "timestamp": row.timestamp_iso,
        "exercise": row.exercise,
        "reps": row.reps,
        "weight_kg": row.weight_kg,
        "duration_s": row.duration_s,
        "distance_m": row.distance_m,
        "incline": row.incline,
        "resistance": row.resistance,
        "is_warmup": row.is_warmup,
        "note": row.note,
        "multiplier": row.multiplier,
        "dedupe_hash": row.dedupe_hash,
    }
    if mapped_id is not None:
        data["exercise_id"] = mapped_id
    return data


def _session_note(import_id: str, session_key: str, rows: list[FitbodRow], truncated: bool) -> str:
    metadata = {
        "source": "fitbod_csv",
        "import_id": import_id,
        "session_key": session_key,
        "row_count": len(rows),
        "rows": [
            {
                "row": row.row_number,
                "exercise": row.exercise,
                "reps": row.reps,
                "weight_kg": row.weight_kg,
                "duration_s": row.duration_s,
                "distance_m": row.distance_m,
                "incline": row.incline,
                "resistance": row.resistance,
                "is_warmup": row.is_warmup,
                "note": row.note,
                "multiplier": row.multiplier,
                "dedupe_hash": row.dedupe_hash,
            }
            for row in rows
        ],
        "rows_truncated": truncated,
    }
    return "FITBOD_IMPORT_METADATA=" + json.dumps(metadata, separators=(",", ":"))


@mcp.tool()
async def get_routines() -> dict | list | str:
    """List workout routines with exercises and configurations."""
    return await _get("/api/v2/routine/", params={"format": "json"})


@mcp.tool()
async def get_workout_sessions(limit: int = 10) -> dict | list | str:
    """Get recent workout sessions with dates and notes."""
    return await _get(
        "/api/v2/workoutsession/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def get_workout_log(days: int = 7) -> dict | list | str:
    """Get exercise log entries (sets, reps, weight) for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    return await _get(
        "/api/v2/workoutlog/",
        params={"format": "json", "ordering": "-date", "date__gte": since},
    )


@mcp.tool()
async def get_nutrition_plan() -> dict | list | str:
    """Get current nutrition plan with macros and meal items."""
    return await _get("/api/v2/nutritionplan/", params={"format": "json"})


@mcp.tool()
async def get_body_weight(limit: int = 30) -> dict | list | str:
    """Get body weight entries over time (most recent first)."""
    return await _get(
        "/api/v2/weightentry/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def get_body_measurements(limit: int = 30) -> dict | list | str:
    """Get body measurements (chest, waist, arms, etc.) over time."""
    return await _get(
        "/api/v2/measurement/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def log_workout(
    exercise_id: int,
    reps: int,
    weight: float,
    workout_id: int,
    sets: int = 1,
) -> dict | str:
    """Log a workout entry. Specify exercise_id, reps, weight (kg), and workout_id.

    Creates `sets` number of identical log entries (default 1).
    """
    results = []
    for _ in range(sets):
        result = await _post(
            "/api/v2/workoutlog/",
            {
                "exercise": exercise_id,
                "repetitions": str(reps),
                "weight": str(weight),
                "routine": workout_id,
            },
        )
        results.append(result)
    return results if len(results) > 1 else results[0]


@mcp.tool()
async def log_weight(weight_kg: float, date_str: str = "") -> dict | str:
    """Add a body weight entry. date_str format: YYYY-MM-DD (default: today)."""
    payload: dict = {"weight": str(weight_kg)}
    if date_str:
        payload["date"] = date_str
    else:
        payload["date"] = date.today().isoformat()
    return await _post("/api/v2/weightentry/", payload)


@mcp.tool()
async def get_nutrition_plan_detail(plan_id: int) -> dict | list | str:
    """Get detailed nutrition plan with all meals and items.

    Args:
        plan_id: Nutrition plan ID
    """
    return await _get(f"/api/v2/nutritionplaninfo/{plan_id}/", params={"format": "json"})


@mcp.tool()
async def get_nutrition_values(plan_id: int) -> dict | list | str:
    """Get calculated nutritional values (calories, protein, carbs, fat) for a plan.

    Args:
        plan_id: Nutrition plan ID
    """
    return await _get(
        f"/api/v2/nutritionplan/{plan_id}/nutritional_values/",
        params={"format": "json"},
    )


@mcp.tool()
async def log_nutrition_diary(
    plan_id: int,
    ingredient_id: int,
    amount: float,
    meal_id: int | None = None,
) -> dict | str:
    """Log a food item to the nutrition diary.

    Args:
        plan_id: Nutrition plan ID
        ingredient_id: Ingredient/food ID from wger database
        amount: Amount in grams
        meal_id: Optional meal ID to associate with
    """
    payload: dict = {
        "plan": plan_id,
        "ingredient": ingredient_id,
        "amount": str(amount),
    }
    if meal_id is not None:
        payload["meal"] = meal_id
    return await _post("/api/v2/nutritiondiary/", payload)


@mcp.tool()
async def get_nutrition_diary(days: int = 7) -> dict | list | str:
    """Get nutrition diary entries for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    return await _get(
        "/api/v2/nutritiondiary/",
        params={"format": "json", "ordering": "-datetime", "datetime__gte": since},
    )


@mcp.tool()
async def search_ingredients(query: str, language: int = 2) -> dict | list | str:
    """Search for food ingredients by name.

    Args:
        query: Search term (food name)
        language: Language ID (2 = English)
    """
    return await _get(
        "/api/v2/ingredient/search/",
        params={"format": "json", "term": query, "language": language},
    )


@mcp.tool()
async def log_body_measurement(
    category_id: int,
    value: float,
    date_str: str = "",
) -> dict | str:
    """Log a body measurement (e.g., waist circumference, arm size).

    Args:
        category_id: Measurement category ID (use get_measurement_categories to find)
        value: Measurement value
        date_str: Date in YYYY-MM-DD format (default: today)
    """
    payload: dict = {
        "category": category_id,
        "value": str(value),
        "date": date_str or date.today().isoformat(),
    }
    return await _post("/api/v2/measurement/", payload)


@mcp.tool()
async def get_measurement_categories() -> dict | list | str:
    """Get all body measurement categories (e.g., chest, waist, biceps)."""
    return await _get("/api/v2/measurement-category/", params={"format": "json"})


@mcp.tool()
async def get_user_profile() -> dict | list | str:
    """Get current user profile with personal settings and preferences."""
    return await _get("/api/v2/userprofile/", params={"format": "json"})


@mcp.tool()
async def fitbod_parse_csv(
    file_path: str,
    timezone: str = "",
    sample_rows: int = 25,
) -> dict[str, Any]:
    """Parse a FitBod CSV export and return normalized rows + summary.

    Args:
        file_path: Path to WorkoutExport.csv
        timezone: Optional IANA timezone for naive timestamps (e.g., America/New_York)
        sample_rows: Number of parsed rows to include in the response sample
    """
    rows, summary = _parse_fitbod_rows(file_path=file_path, timezone=timezone)
    sample = [_row_to_preview_dict(row) for row in rows[: max(0, sample_rows)]]
    return {
        "summary": summary,
        "sample_rows": sample,
        "mapping_path": str(FITBOD_MAPPING_PATH),
        "ledger_path": str(FITBOD_IMPORT_LEDGER_PATH),
    }


@mcp.tool()
async def fitbod_preview_mapping(
    file_path: str,
    language: int = 2,
    top_k: int = 5,
    timezone: str = "",
) -> dict[str, Any]:
    """Preview how FitBod exercise names map to wger exercise IDs.

    Args:
        file_path: Path to WorkoutExport.csv
        language: wger language ID for exercise search (2 = English)
        top_k: Number of candidate matches to show for each unmapped exercise
        timezone: Optional IANA timezone for naive timestamps
    """
    rows, parse_summary = _parse_fitbod_rows(file_path=file_path, timezone=timezone)
    mapping_preview = await _build_fitbod_mapping_preview(
        rows,
        language=language,
        top_k=top_k,
    )
    return {
        "parse_summary": parse_summary,
        "mapping_summary": mapping_preview["summary"],
        "coverage_summary": mapping_preview["coverage_summary"],
        "priority_queue": mapping_preview["priority_queue"],
        "mapping": mapping_preview["mapping"],
    }


@mcp.tool()
async def fitbod_set_exercise_alias(exercise_name: str, exercise_id: int) -> dict[str, Any]:
    """Persist a manual FitBod exercise-name -> wger exercise_id mapping."""
    normalized = _normalize_exercise_name(exercise_name)
    if not normalized:
        return {"ok": False, "error": "exercise_name must not be empty"}
    if exercise_id <= 0:
        return {"ok": False, "error": "exercise_id must be > 0"}

    validation = await _validate_wger_exercise_id(exercise_id)
    if not validation["ok"]:
        return {
            "ok": False,
            "error": validation["error"],
            "exercise_name": exercise_name,
            "exercise_id": int(exercise_id),
        }

    store = _mapping_store()
    aliases: dict[str, int] = {
        key: int(value) for key, value in store.get("aliases", {}).items()
    }
    metadata: dict[str, Any] = store.get("metadata", {})
    aliases[normalized] = int(exercise_id)
    metadata[normalized] = {
        "source": "manual_set",
        "applied_at": datetime.utcnow().isoformat() + "Z",
        "exercise_name": exercise_name,
        "exercise_id": int(exercise_id),
        "validated_exercise_id": validation["exercise"].get("id"),
    }
    store["aliases"] = aliases
    store["metadata"] = metadata
    _save_mapping_store(store)
    return {
        "ok": True,
        "exercise_name": exercise_name,
        "normalized": normalized,
        "exercise_id": int(exercise_id),
        "mapping_path": str(FITBOD_MAPPING_PATH),
        "alias_count": len(aliases),
    }


@mcp.tool()
async def fitbod_list_exercise_aliases(limit: int = 200) -> dict[str, Any]:
    """Return current manual/auto FitBod alias mappings."""
    store = _mapping_store()
    aliases: dict[str, int] = {
        key: int(value) for key, value in store.get("aliases", {}).items()
    }
    metadata: dict[str, Any] = store.get("metadata", {})
    items = sorted(aliases.items())[: max(1, limit)]
    return {
        "mapping_path": str(FITBOD_MAPPING_PATH),
        "alias_count": len(aliases),
        "aliases": [
            {
                "normalized_name": key,
                "exercise_id": value,
                "metadata": metadata.get(key),
            }
            for key, value in items
        ],
        "updated_at": store.get("updated_at"),
    }


@mcp.tool()
async def fitbod_apply_aliases(mappings: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist reviewed FitBod exercise-name -> wger exercise_id mappings in batch."""
    if not mappings:
        return {"ok": False, "error": "mappings must not be empty"}

    store = _mapping_store()
    aliases: dict[str, int] = {
        key: int(value) for key, value in store.get("aliases", {}).items()
    }
    metadata: dict[str, Any] = store.get("metadata", {})
    validation_cache: dict[int, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, item in enumerate(mappings, start=1):
        if not isinstance(item, dict):
            errors.append({"index": index, "error": "mapping entry must be an object"})
            continue

        exercise_name = str(
            item.get("exercise_name") or item.get("exercise") or item.get("normalized") or ""
        ).strip()
        normalized = _normalize_exercise_name(exercise_name)
        if not normalized:
            errors.append({"index": index, "error": "exercise_name must not be empty"})
            continue

        try:
            exercise_id = int(item.get("exercise_id"))
        except (TypeError, ValueError):
            errors.append(
                {
                    "index": index,
                    "exercise_name": exercise_name,
                    "error": "exercise_id must be an integer",
                }
            )
            continue

        if exercise_id not in validation_cache:
            validation_cache[exercise_id] = await _validate_wger_exercise_id(exercise_id)
        validation = validation_cache[exercise_id]
        if not validation["ok"]:
            errors.append(
                {
                    "index": index,
                    "exercise_name": exercise_name,
                    "exercise_id": exercise_id,
                    "error": validation["error"],
                }
            )
            continue

        previous_id = aliases.get(normalized)
        aliases[normalized] = exercise_id
        metadata[normalized] = {
            "source": str(item.get("source") or "reviewed_batch"),
            "applied_at": datetime.utcnow().isoformat() + "Z",
            "exercise_name": exercise_name,
            "exercise_id": exercise_id,
            "candidate_label": item.get("candidate_label") or item.get("suggested_label"),
            "confidence": item.get("confidence") or item.get("suggestion_confidence"),
        }
        results.append(
            {
                "exercise_name": exercise_name,
                "normalized": normalized,
                "exercise_id": exercise_id,
                "previous_exercise_id": previous_id,
                "status": "unchanged" if previous_id == exercise_id else "applied",
            }
        )

    store["aliases"] = aliases
    store["metadata"] = metadata
    _save_mapping_store(store)

    return {
        "ok": not errors,
        "applied_count": sum(1 for item in results if item["status"] == "applied"),
        "unchanged_count": sum(1 for item in results if item["status"] == "unchanged"),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
        "alias_count": len(aliases),
        "mapping_path": str(FITBOD_MAPPING_PATH),
        "updated_at": store.get("updated_at"),
    }


@mcp.tool()
async def fitbod_import_csv(
    file_path: str,
    dry_run: bool = True,
    date_from: str = "",
    date_to: str = "",
    max_rows: int = 0,
    dedupe_mode: str = "hash",
    timezone: str = "",
    language: int = 2,
) -> dict[str, Any]:
    """Import FitBod CSV rows into wger workout sessions/logs.

    Args:
        file_path: Path to WorkoutExport.csv
        dry_run: If true, do not write to wger; return what would be imported
        date_from: Optional lower bound date (YYYY-MM-DD)
        date_to: Optional upper bound date (YYYY-MM-DD)
        max_rows: Optional hard row limit after date filtering (0 = no limit)
        dedupe_mode: "hash" (recommended) or "none"
        timezone: Optional IANA timezone for naive timestamps
        language: wger language ID for exercise search
    """
    import_id = str(uuid4())
    started_at = datetime.utcnow().isoformat() + "Z"

    status: dict[str, Any] = {
        "import_id": import_id,
        "status": "running",
        "started_at": started_at,
        "dry_run": dry_run,
        "dedupe_mode": dedupe_mode,
        "source_file": file_path,
        "created_sessions": 0,
        "created_logs": 0,
        "skipped_deduped": 0,
        "skipped_unmapped": 0,
        "errors": [],
    }
    FITBOD_IMPORT_STATUS[import_id] = status

    if dedupe_mode not in {"hash", "none"}:
        status["status"] = "failed"
        status["errors"].append("dedupe_mode must be 'hash' or 'none'")
        return status

    rows, parse_summary = _parse_fitbod_rows(file_path=file_path, timezone=timezone)

    filtered = rows
    if date_from:
        filtered = [row for row in filtered if row.workout_date >= date_from]
    if date_to:
        filtered = [row for row in filtered if row.workout_date <= date_to]
    if max_rows and max_rows > 0:
        filtered = filtered[:max_rows]

    mapping_preview = await _build_fitbod_mapping_preview(filtered, language=language, top_k=5)

    mapping_by_name: dict[str, int] = {}
    for item in mapping_preview["mapping"]:
        if item.get("status") == "mapped" and item.get("exercise_id"):
            mapping_by_name[item["normalized"]] = int(item["exercise_id"])

    ledger = _ledger_store()
    ledger_items: dict[str, Any] = ledger.get("items", {})

    session_buffers: dict[str, list[FitbodRow]] = {}
    dry_run_rows: list[dict[str, Any]] = []
    session_ids: dict[str, int] = {}

    for row in filtered:
        normalized = _normalize_exercise_name(row.exercise)
        mapped_id = mapping_by_name.get(normalized)
        if not mapped_id:
            status["skipped_unmapped"] += 1
            if len(status["errors"]) < 50:
                status["errors"].append(
                    f"row {row.row_number}: no mapped exercise_id for '{row.exercise}'"
                )
            continue

        if dedupe_mode == "hash" and row.dedupe_hash in ledger_items:
            status["skipped_deduped"] += 1
            continue

        if dry_run:
            dry_run_rows.append(_row_to_preview_dict(row, mapped_id=mapped_id))
            continue

        if row.session_key not in session_ids:
            create_session = await _post(
                "/api/v2/workoutsession/",
                {
                    "date": row.workout_date,
                    "notes": f"FitBod import {import_id} ({row.timestamp_iso})",
                },
            )
            if isinstance(create_session, str):
                status["errors"].append(
                    f"session create failed ({row.workout_date}): {create_session}"
                )
                continue

            session_id = create_session.get("id")
            if not isinstance(session_id, int):
                status["errors"].append(
                    f"session create returned invalid id for row {row.row_number}: {create_session}"
                )
                continue

            session_ids[row.session_key] = session_id
            status["created_sessions"] += 1

        payload: dict[str, Any] = {
            "exercise": mapped_id,
            "session": session_ids[row.session_key],
            "date": row.timestamp_iso,
        }
        if row.reps is not None:
            payload["repetitions"] = str(row.reps)
        if row.weight_kg is not None:
            payload["weight"] = str(row.weight_kg)

        create_log = await _post("/api/v2/workoutlog/", payload)
        if isinstance(create_log, str):
            status["errors"].append(f"log create failed row {row.row_number}: {create_log}")
            continue

        status["created_logs"] += 1
        session_buffers.setdefault(row.session_key, []).append(row)
        ledger_items[row.dedupe_hash] = {
            "import_id": import_id,
            "imported_at": datetime.utcnow().isoformat() + "Z",
            "row_number": row.row_number,
            "workout_date": row.workout_date,
            "exercise": row.exercise,
            "exercise_id": mapped_id,
            "source_file": row.source_file,
        }

    if dry_run:
        status["status"] = "dry_run_complete"
        status["finished_at"] = datetime.utcnow().isoformat() + "Z"
        status["rows_considered"] = len(filtered)
        status["rows_ready"] = len(dry_run_rows)
        status["parse_summary"] = parse_summary
        status["mapping_summary"] = mapping_preview["summary"]
        status["coverage_summary"] = mapping_preview["coverage_summary"]
        status["coverage_target_met"] = _coverage_target_met(mapping_preview["coverage_summary"])
        status["unresolved_priority"] = mapping_preview["priority_queue"][:50]
        status["preview_rows"] = dry_run_rows[:200]
        return status

    for session_key, rows_for_session in session_buffers.items():
        session_id = session_ids.get(session_key)
        if not session_id:
            continue
        max_rows_for_note = 200
        truncated = len(rows_for_session) > max_rows_for_note
        note_rows = rows_for_session[:max_rows_for_note]
        note = _session_note(import_id, session_key, note_rows, truncated=truncated)
        patch_result = await _patch(
            f"/api/v2/workoutsession/{session_id}/",
            {"notes": note},
        )
        if isinstance(patch_result, str):
            status["errors"].append(
                f"session note patch failed session {session_id}: {patch_result}"
            )

    ledger["items"] = ledger_items
    _save_ledger_store(ledger)

    status["status"] = "completed_with_errors" if status["errors"] else "completed"
    status["finished_at"] = datetime.utcnow().isoformat() + "Z"
    status["rows_considered"] = len(filtered)
    status["parse_summary"] = parse_summary
    status["mapping_summary"] = mapping_preview["summary"]
    status["coverage_summary"] = mapping_preview["coverage_summary"]
    status["coverage_target_met"] = _coverage_target_met(mapping_preview["coverage_summary"])
    status["unresolved_priority"] = mapping_preview["priority_queue"][:50]
    return status


@mcp.tool()
async def fitbod_get_import_status(import_id: str) -> dict[str, Any]:
    """Get status for a prior fitbod_import_csv call."""
    status = FITBOD_IMPORT_STATUS.get(import_id)
    if status:
        return status

    ledger = _ledger_store()
    items: dict[str, Any] = ledger.get("items", {})
    matches = [item for item in items.values() if item.get("import_id") == import_id]

    if not matches:
        return {
            "import_id": import_id,
            "status": "not_found",
            "message": "No matching import_id found in memory or ledger",
        }

    return {
        "import_id": import_id,
        "status": "completed",
        "rows_recorded": len(matches),
        "sample": matches[:25],
        "ledger_path": str(FITBOD_IMPORT_LEDGER_PATH),
    }


if __name__ == "__main__":
    mcp.run()
