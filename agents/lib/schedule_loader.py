"""Declarative schedule loader for StewardOS agents.

Reads ``agents/schedules.yaml`` and returns typed ScheduleEntry objects
filtered by agent name.  Both family-office-mail-worker and family-brief-agent
use this to wire up APScheduler jobs from a single source of truth.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_SCHEDULES_PATH = Path(__file__).resolve().parent.parent / "schedules.yaml"


@dataclass(frozen=True)
class ScheduleEntry:
    id: str
    agent: str
    persona: Optional[str]
    cron: Optional[str]
    interval_minutes: Optional[int]
    recipients: list[str]
    delivery_mode: str
    prompt_template: Optional[str]
    enabled: bool
    timezone: str


def load_schedules(
    agent_name: str,
    path: Optional[str | Path] = None,
) -> list[ScheduleEntry]:
    """Load and validate schedules.yaml, return only entries for *agent_name*.

    Validation rules:
    - Each entry must have exactly one of ``cron`` or ``interval_minutes``.
    - Entries with ``enabled: false`` are excluded.

    Raises:
        FileNotFoundError: If the schedules file does not exist.
        ValueError: If an entry violates the cron-xor-interval constraint.
    """
    schedules_path = Path(path) if path else _DEFAULT_SCHEDULES_PATH

    if not schedules_path.exists():
        raise FileNotFoundError(f"Schedules file not found: {schedules_path}")

    with open(schedules_path) as f:
        data = yaml.safe_load(f)

    version = data.get("version", 1)
    if version != 1:
        logger.warning("Unexpected schedules.yaml version %s, proceeding anyway", version)

    default_tz = data.get("timezone", "UTC")
    entries: list[ScheduleEntry] = []

    for job in data.get("jobs", []):
        job_id = job["id"]
        has_cron = bool(job.get("cron"))
        has_interval = bool(job.get("interval_minutes"))

        if has_cron == has_interval:
            raise ValueError(
                f"Schedule '{job_id}' must have exactly one of 'cron' or "
                f"'interval_minutes', got {'both' if has_cron else 'neither'}"
            )

        if job.get("agent") != agent_name:
            continue

        if not job.get("enabled", True):
            continue

        delivery_mode = str(job.get("delivery_mode", "email")).strip().lower() or "email"
        if delivery_mode not in {"email", "maintenance"}:
            raise ValueError(
                f"Schedule '{job_id}' has unsupported delivery_mode '{delivery_mode}'. "
                "Supported values: email, maintenance"
            )

        entries.append(
            ScheduleEntry(
                id=job_id,
                agent=job["agent"],
                persona=job.get("persona"),
                cron=job.get("cron"),
                interval_minutes=job.get("interval_minutes"),
                recipients=job.get("recipients", []),
                delivery_mode=delivery_mode,
                prompt_template=job.get("prompt_template"),
                enabled=True,
                timezone=job.get("timezone", default_tz),
            )
        )

    logger.info(
        "Loaded %d schedule(s) for agent '%s' from %s",
        len(entries),
        agent_name,
        schedules_path,
    )
    return entries
