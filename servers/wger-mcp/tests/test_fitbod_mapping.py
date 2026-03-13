import csv
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


SERVER_PATH = Path("$STEWARDOS_ROOT/servers/wger-mcp/server.py")


def load_server_module():
    os.environ.setdefault("WGER_URL", "http://localhost:8280")
    os.environ.setdefault("WGER_API_TOKEN", "test-token")
    module_name = f"wger_server_test_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_fitbod_row(module, exercise: str, when: datetime, row_number: int = 2):
    return module.FitbodRow(
        row_number=row_number,
        source_file="WorkoutExport.csv",
        raw_date=when.strftime("%Y-%m-%d %H:%M:%S %z"),
        timestamp=when,
        timestamp_iso=when.isoformat(),
        session_key=when.isoformat(),
        workout_date=when.date().isoformat(),
        exercise=exercise,
        reps=10.0,
        weight_kg=20.0,
        duration_s=0.0,
        distance_m=0.0,
        incline=0.0,
        resistance=0.0,
        is_warmup=False,
        note="",
        multiplier=1.0,
        dedupe_hash=f"hash-{row_number}-{exercise}",
    )


class FitbodMappingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_server_module()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.mapping_path = Path(self.tmpdir.name) / "exercise-map.json"
        self.ledger_path = Path(self.tmpdir.name) / "import-ledger.json"
        self.module.FITBOD_MAPPING_PATH = self.mapping_path
        self.module.FITBOD_IMPORT_LEDGER_PATH = self.ledger_path
        self.mapping_path.write_text(
            json.dumps({"aliases": {"walking": 1104}, "metadata": {}, "updated_at": None}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_normalization_and_candidate_score(self):
        normalize = self.module._normalize_exercise_name
        score = self.module._candidate_score

        self.assertEqual(normalize("Push-Ups"), "push up")
        self.assertEqual(normalize("Hammer Curls"), "hammer curl")
        self.assertEqual(normalize("Cycling - Stationary"), "cycling stationary")
        self.assertEqual(normalize("Biceps Curls With Dumbbell"), "biceps curl with dumbbell")

        match = score("Dumbbell Bicep Curl", "Biceps Curls With Dumbbell")
        self.assertIn(match["confidence"], {"high", "medium"})
        self.assertGreaterEqual(match["score"], 0.72)

    async def test_preview_is_read_only_and_reports_review_queue(self):
        async def fake_search(term: str, language: int = 2):
            if term == "Running":
                return {
                    "suggestions": [
                        {"value": "Run", "data": {"id": 527, "base_id": 527, "category": "Cardio"}},
                        {
                            "value": "Zone 2 Running",
                            "data": {"id": 908, "base_id": 908, "category": "Cardio"},
                        },
                    ]
                }
            return {"suggestions": []}

        self.module._search_wger_exercise = fake_search
        file_before = self.mapping_path.read_text(encoding="utf-8")
        rows = [
            make_fitbod_row(self.module, "Walking", datetime(2026, 3, 4, tzinfo=timezone.utc), 2),
            make_fitbod_row(self.module, "Running", datetime(2026, 3, 5, tzinfo=timezone.utc), 3),
            make_fitbod_row(self.module, "Running", datetime(2026, 3, 5, 1, tzinfo=timezone.utc), 4),
        ]

        preview = await self.module._build_fitbod_mapping_preview(rows, language=2, top_k=3)

        self.assertEqual(file_before, self.mapping_path.read_text(encoding="utf-8"))
        mapping_by_name = {item["exercise"]: item for item in preview["mapping"]}
        self.assertEqual(mapping_by_name["Walking"]["status"], "mapped")
        self.assertEqual(mapping_by_name["Running"]["status"], "review_required")
        self.assertEqual(mapping_by_name["Running"]["suggested_exercise_id"], 527)
        self.assertEqual(preview["coverage_summary"]["all_time"]["mapped_rows"], 1)
        self.assertEqual(preview["coverage_summary"]["all_time"]["suggested_rows"], 2)
        self.assertEqual(preview["priority_queue"][0]["exercise"], "Running")

    async def test_apply_aliases_validates_and_is_idempotent(self):
        async def fake_validate(exercise_id: int):
            if exercise_id == 527:
                return {"ok": True, "exercise": {"id": 527}}
            return {"ok": False, "error": "not found"}

        self.module._validate_wger_exercise_id = fake_validate

        first = await self.module.fitbod_apply_aliases(
            [
                {"exercise_name": "Running", "exercise_id": 527, "confidence": "high"},
                {"exercise_name": "Bad Exercise", "exercise_id": 999999},
            ]
        )
        self.assertFalse(first["ok"])
        self.assertEqual(first["applied_count"], 1)
        self.assertEqual(first["error_count"], 1)

        store = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        self.assertEqual(store["aliases"]["run"], 527)
        self.assertEqual(store["metadata"]["run"]["confidence"], "high")

        second = await self.module.fitbod_apply_aliases(
            [{"exercise_name": "Running", "exercise_id": 527, "confidence": "high"}]
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["applied_count"], 0)
        self.assertEqual(second["unchanged_count"], 1)

    async def test_import_dry_run_uses_only_persisted_aliases(self):
        csv_path = Path(self.tmpdir.name) / "WorkoutExport.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
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
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Date": "2026-03-04 12:00:00 +0000",
                    "Exercise": "Walking",
                    "Reps": "0",
                    "Weight(kg)": "0",
                    "Duration(s)": "60",
                    "Distance(m)": "100",
                    "Incline": "0",
                    "Resistance": "0",
                    "isWarmup": "false",
                    "Note": "",
                    "multiplier": "1",
                }
            )
            writer.writerow(
                {
                    "Date": "2026-03-05 12:00:00 +0000",
                    "Exercise": "Running",
                    "Reps": "0",
                    "Weight(kg)": "0",
                    "Duration(s)": "60",
                    "Distance(m)": "100",
                    "Incline": "0",
                    "Resistance": "0",
                    "isWarmup": "false",
                    "Note": "",
                    "multiplier": "1",
                }
            )

        async def fake_search(term: str, language: int = 2):
            if term == "Running":
                return {
                    "suggestions": [
                        {"value": "Run", "data": {"id": 527, "base_id": 527, "category": "Cardio"}},
                    ]
                }
            return {"suggestions": []}

        self.module._search_wger_exercise = fake_search

        status = await self.module.fitbod_import_csv(
            file_path=str(csv_path),
            dry_run=True,
            timezone="UTC",
        )

        self.assertEqual(status["status"], "dry_run_complete")
        self.assertEqual(status["rows_ready"], 1)
        self.assertEqual(status["skipped_unmapped"], 1)
        self.assertFalse(status["coverage_target_met"])
        self.assertEqual(status["preview_rows"][0]["exercise"], "Walking")
        self.assertEqual(status["unresolved_priority"][0]["exercise"], "Running")


if __name__ == "__main__":
    unittest.main()
