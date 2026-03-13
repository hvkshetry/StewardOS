from __future__ import annotations

from lib.schedule_loader import ScheduleEntry

import src.scheduler as scheduler


class _FakeScheduler:
    def __init__(self):
        self.jobs: list[dict] = []
        self.started = False
        self.shutdown_calls: list[bool] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "kwargs": kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait: bool = False):
        self.shutdown_calls.append(wait)


def test_start_scheduler_registers_known_jobs_and_skips_unknown_entries(monkeypatch):
    fake_scheduler = _FakeScheduler()
    entries = [
        ScheduleEntry(
            id="daily-brief",
            agent="family-brief-agent",
            persona=None,
            cron="0 7 * * *",
            interval_minutes=None,
            recipients=[],
            delivery_mode="email",
            prompt_template="daily_brief",
            enabled=True,
            timezone="America/New_York",
        ),
        ScheduleEntry(
            id="watch-renewal",
            agent="family-brief-agent",
            persona=None,
            cron=None,
            interval_minutes=60,
            recipients=[],
            delivery_mode="maintenance",
            prompt_template="gmail_watch_renewal",
            enabled=True,
            timezone="America/New_York",
        ),
        ScheduleEntry(
            id="unknown-job",
            agent="family-brief-agent",
            persona=None,
            cron="15 9 * * *",
            interval_minutes=None,
            recipients=[],
            delivery_mode="email",
            prompt_template="not-mapped",
            enabled=True,
            timezone="America/New_York",
        ),
    ]

    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "AsyncIOScheduler", lambda: fake_scheduler)
    monkeypatch.setattr(
        scheduler,
        "load_schedules",
        lambda agent_name, path=None: entries,
    )
    monkeypatch.setattr(
        scheduler.CronTrigger,
        "from_crontab",
        lambda spec, timezone=None: {
            "kind": "cron",
            "spec": spec,
            "timezone": timezone,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "IntervalTrigger",
        lambda minutes: {"kind": "interval", "minutes": minutes},
    )

    scheduler.start_scheduler()

    assert fake_scheduler.started is True
    assert [job["kwargs"]["id"] for job in fake_scheduler.jobs] == [
        "daily-brief",
        "watch-renewal",
    ]
    assert fake_scheduler.jobs[0]["func"] is scheduler.daily_brief_job
    assert fake_scheduler.jobs[0]["trigger"] == {
        "kind": "cron",
        "spec": "0 7 * * *",
        "timezone": scheduler.settings.briefing_timezone,
    }
    assert fake_scheduler.jobs[1]["func"] is scheduler.gmail_watch_renewal_job
    assert fake_scheduler.jobs[1]["trigger"] == {
        "kind": "interval",
        "minutes": 60,
    }

    scheduler.stop_scheduler()

    assert fake_scheduler.shutdown_calls == [False]
    assert scheduler._scheduler is None
