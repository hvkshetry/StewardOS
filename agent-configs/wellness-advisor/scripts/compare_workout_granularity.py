#!/usr/bin/env python3
"""Compare direct FitBod export detail vs Apple Health derived data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

APPLE_DIR = Path("$STEWARDOS_ROOT/data/apple-health")
FITBOD_CSV = Path("$STEWARDOS_ROOT/data/fitbod/WorkoutExport.csv")


def fitbod_summary(path: Path) -> dict[str, object]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    columns = reader.fieldnames or []
    dates = sorted({(row.get("Date") or "").strip() for row in rows if row.get("Date")})
    exercises = sorted({(row.get("Exercise") or "").strip() for row in rows if row.get("Exercise")})

    return {
        "file": str(path),
        "rows": len(rows),
        "columns": columns,
        "unique_sessions_by_timestamp": len(dates),
        "unique_exercises": len(exercises),
        "sample_exercises": exercises[:10],
    }


def apple_source_summary(path: Path, source_token: str) -> dict[str, object]:
    if not path.exists():
        return {"file": str(path), "rows": 0, "columns": [], "found": False}

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    if len(rows) < 2:
        return {"file": str(path), "rows": 0, "columns": [], "found": True}

    header = rows[1]
    source_idx = header.index("sourceName") if "sourceName" in header else -1

    matched = []
    for row in rows[2:]:
        if source_idx >= 0 and source_idx < len(row):
            source_name = row[source_idx].strip().lower()
            if source_token.lower() in source_name:
                matched.append(row)

    return {
        "file": str(path),
        "found": True,
        "rows": len(matched),
        "columns": header,
        "sample_rows": matched[:3],
    }


def main() -> None:
    output: dict[str, object] = {
        "fitbod": fitbod_summary(FITBOD_CSV),
        "apple_fitbod_workout_summary": apple_source_summary(
            APPLE_DIR / "HKWorkoutTypeIdentifierWorkoutSummary.csv", "Fitbod"
        ),
        "apple_peloton_workout_summary": apple_source_summary(
            APPLE_DIR / "HKWorkoutTypeIdentifierWorkoutSummary.csv", "Peloton"
        ),
        "apple_peloton_heart_rate": apple_source_summary(
            APPLE_DIR / "HKQuantityTypeIdentifierHeartRate.csv", "Peloton"
        ),
        "interpretation": {
            "fitbod_expected_detail": [
                "Exercise",
                "Reps",
                "Weight(kg)",
                "Duration(s)",
                "Distance(m)",
                "Incline",
                "Resistance",
            ],
            "apple_workout_summary_shape": "Typically summary-level fields (type, sourceName, unit, startDate, endDate, value, workoutActivityType)",
            "note": "Use this output to judge whether direct FitBod/Peloton integrations are needed for deeper coaching analytics.",
        },
    }

    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
