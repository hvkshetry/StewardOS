from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_critical_services_have_migration_directories():
    expected = {
        "servers/finance-graph-mcp/migrations",
        "servers/health-graph-mcp/migrations",
        "servers/household-tax-mcp/migrations",
    }
    missing = [path for path in expected if not (REPO_ROOT / path).is_dir()]
    assert missing == []


def test_behavior_heavy_projects_have_characterization_tests():
    expected = {
        "servers/ghostfolio-mcp/tests/test_portfolio_snapshot.py",
        "servers/investing-workspace/market-intel-direct/tests/test_ranking_and_degraded.py",
        "agents/family-brief-agent/tests/test_main_characterization.py",
        "agents/family-brief-agent/tests/test_scheduler_characterization.py",
    }
    missing = [path for path in expected if not (REPO_ROOT / path).is_file()]
    assert missing == []
