#!/usr/bin/env python3
"""Generate a repeatable open-wearables pilot readiness report."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path("/tmp/open-wearables")

REQUIRED_FILES = [
    "README.md",
    "docs/providers/apple-health.mdx",
    "docs/api-reference/guides/apple-xml-import.mdx",
    "backend/app/api/routes/v1/external_connectors.py",
    "backend/app/api/routes/v1/import_xml.py",
    "backend/app/integrations/celery/tasks/process_sdk_upload_task.py",
    "mcp/README.md",
]


def contains(path: Path, text: str) -> bool:
    if not path.exists():
        return False
    return text in path.read_text(encoding="utf-8")


def main() -> None:
    report: dict[str, object] = {
        "repo": str(REPO),
        "repo_exists": REPO.exists(),
        "required_files": {},
        "key_findings": {},
        "pilot_plan": [
            "1) Launch open-wearables backend in isolated environment (do not bind into production stack)",
            "2) Validate Apple XML import path with a sample export",
            "3) Validate auto-health-export endpoint behavior for recurring push ingestion",
            "4) Query open-wearables MCP workouts/sleep/activity tools",
            "5) Compare granularity and operational burden against apple-health-mcp + direct FitBod/Peloton sources",
        ],
        "decision_gate": {
            "adopt_if": [
                "Automates recurring ingestion with lower operator effort than current manual zip flow",
                "Provides materially better or equivalent workout detail for target use cases",
                "Operational complexity (services/jobs/auth) is acceptable for home-server deployment",
            ],
            "do_not_adopt_if": [
                "Still requires frequent manual intervention",
                "Apple pipeline remains summary-level for required metrics",
                "Operational footprint outweighs practical benefit",
            ],
        },
    }

    required = {}
    for rel in REQUIRED_FILES:
        required[rel] = (REPO / rel).exists()
    report["required_files"] = required

    findings = {
        "apple_push_model_documented": contains(REPO / "docs/providers/apple-health.mdx", "push-based model"),
        "xml_import_endpoints_present": contains(
            REPO / "backend/app/api/routes/v1/import_xml.py", "/import/apple/xml"
        ),
        "auto_health_export_endpoint_present": contains(
            REPO / "backend/app/api/routes/v1/external_connectors.py", "auto-health-export"
        ),
        "sdk_upload_task_supports_auto_export": contains(
            REPO / "backend/app/integrations/celery/tasks/process_sdk_upload_task.py",
            "auto-health-export",
        ),
        "apple_handler_todo_risk": contains(
            REPO / "backend/app/services/providers/apple/handlers/auto_export.py",
            "TODO",
        ) or contains(
            REPO / "backend/app/services/providers/apple/handlers/healthkit.py",
            "TODO",
        ),
    }
    report["key_findings"] = findings

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
