from __future__ import annotations

import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.config import Settings, _repo_root


def test_settings_default_persona_resolution(monkeypatch):
    monkeypatch.delenv("AGENT_CONFIGS_ROOT", raising=False)
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.delenv("CODEX_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.alias_persona_map["cos"] == "chief-of-staff"
    assert settings.resolve_persona_dir("cos") == str(_repo_root() / "agent-configs" / "chief-of-staff")
    assert settings.codex_timeout_seconds == 3600


def test_settings_env_overrides_paths(monkeypatch, tmp_path):
    configs_root = tmp_path / "agent-configs"
    configs_root.mkdir()
    monkeypatch.setenv("AGENT_CONFIGS_ROOT", str(configs_root))
    monkeypatch.setenv("CODEX_BIN", "/tmp/custom-codex")
    monkeypatch.setenv("CODEX_TIMEOUT_SECONDS", "5400")

    settings = Settings(_env_file=None)

    assert settings.agent_configs_root == str(configs_root)
    assert settings.codex_bin == "/tmp/custom-codex"
    assert settings.codex_timeout_seconds == 5400
    assert settings.resolve_persona_dir("io") == str(configs_root / "investment-officer")
