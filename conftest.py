"""Root pytest policy for the StewardOS monorepo.

Per-project virtualenvs and working directories are the supported way to run
server and agent test suites. Root-level pytest intentionally does not recurse
into project test trees because the monorepo does not provide a unified Python
environment for every subproject dependency set.
"""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parent


def pytest_ignore_collect(collection_path, config) -> bool:  # pragma: no cover - exercised by pytest itself
    path = Path(str(collection_path))
    try:
        rel = path.relative_to(_ROOT)
    except ValueError:
        return False

    if not rel.parts:
        return False

    if rel.parts[0] not in {"agents", "servers"}:
        return False

    return "tests" in rel.parts
