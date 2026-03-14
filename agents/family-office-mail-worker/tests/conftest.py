from __future__ import annotations

import os
import sys
from pathlib import Path

agent_root = str(Path(__file__).resolve().parents[1])
repo_root = str(Path(__file__).resolve().parents[3])

for path in (agent_root, repo_root):
    if path not in sys.path:
        sys.path.insert(0, path)


def get_test_database_url(tmp_path: Path) -> str:
    """Return a database URL for tests.

    Uses SQLite for CI (default), Postgres for integration if
    TEST_DATABASE_URL is set in the environment.
    """
    env_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if env_url:
        return env_url
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
