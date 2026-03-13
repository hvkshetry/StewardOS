from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from planning import compare_individual_payment_strategies_internal, plan_fiduciary_safe_harbor_internal
from returns import compute_fiduciary_return_exact_internal, compute_individual_return_exact_internal

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
OFFICIAL_SOURCE_PREFIXES = ("https://www.irs.gov/", "https://www.mass.gov/")


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def _load_fixture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _assert_subset(expected: Any, actual: Any, *, path: str = "root") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__}"
        for key, value in expected.items():
            assert key in actual, f"{path}: missing key {key!r}"
            _assert_subset(value, actual[key], path=f"{path}.{key}")
        return
    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__}"
        assert len(actual) >= len(expected), f"{path}: expected at least {len(expected)} items, got {len(actual)}"
        for idx, value in enumerate(expected):
            _assert_subset(value, actual[idx], path=f"{path}[{idx}]")
        return
    assert actual == expected, f"{path}: expected {expected!r}, got {actual!r}"


def _run_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    tool = fixture["tool"]
    facts = fixture["facts"]
    as_of = fixture.get("as_of")
    if tool == "compute_individual_return_exact":
        return compute_individual_return_exact_internal(facts)
    if tool == "compute_fiduciary_return_exact":
        return compute_fiduciary_return_exact_internal(facts)
    if tool == "compare_individual_payment_strategies":
        return compare_individual_payment_strategies_internal(facts, as_of=as_of)
    if tool == "plan_fiduciary_safe_harbor":
        return plan_fiduciary_safe_harbor_internal(facts, as_of=as_of)
    raise AssertionError(f"Unsupported golden fixture tool: {tool}")


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda path: path.stem)
def test_authority_backed_goldens(fixture_path: Path) -> None:
    fixture = _load_fixture(fixture_path)

    sources = fixture.get("authority_sources", [])
    assert sources, f"{fixture_path.name}: authority_sources must not be empty"
    assert all(
        isinstance(source, str) and source.startswith(OFFICIAL_SOURCE_PREFIXES) for source in sources
    ), f"{fixture_path.name}: authority_sources must be official IRS or Mass.gov URLs"
    assert fixture.get("workpaper_basis"), f"{fixture_path.name}: workpaper_basis must not be empty"

    result = _run_fixture(fixture)
    _assert_subset(fixture["expected"], result)
