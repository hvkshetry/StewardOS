"""Configuration for family-office mail worker."""

import os
import shutil
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _agent_configs_root() -> str:
    configured = os.environ.get("AGENT_CONFIGS_ROOT", "").strip()
    if configured:
        return configured
    return str(_repo_root() / "agent-configs")


def _default_alias_persona_map() -> dict[str, str]:
    return {
        "cos": "chief-of-staff",
        "estate": "estate-counsel",
        "hc": "household-comptroller",
        "hd": "household-director",
        "io": "investment-officer",
        "wellness": "wellness-advisor",
        "insurance": "insurance-advisor",
        "ra": "research-analyst",
    }


def _default_codex_bin() -> str:
    configured = os.environ.get("CODEX_BIN", "").strip()
    if configured:
        return configured
    return shutil.which("codex") or "codex"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_port: int = 8312
    service_host: str = "127.0.0.1"

    worker_shared_secret: str = ""

    google_credentials_path: str = "credentials.json"
    google_token_path: str = ".google-token.json"
    google_pubsub_topic: str = ""

    agent_email: str = "steward.agent@example.com"
    allowed_senders: list[str] = []
    agent_configs_root: str = Field(default_factory=_agent_configs_root)

    alias_persona_map: dict[str, str] = Field(default_factory=_default_alias_persona_map)

    alias_display_name_map: dict[str, str] = {
        "cos": "Chief of Staff Agent",
        "estate": "Estate Counsel",
        "hc": "Household Comptroller",
        "hd": "Household Director",
        "io": "Portfolio Manager",
        "wellness": "Wellness Advisor",
        "insurance": "Insurance Advisor",
        "ra": "Research Analyst",
    }

    codex_bin: str = Field(default_factory=_default_codex_bin)
    codex_timeout_seconds: int = 3600
    codex_scratch_dir: str = "/tmp/family-office-mail-worker"

    scheduled_briefs_enabled: bool = True
    briefing_timezone: str = "America/New_York"
    schedules_path: str = ""
    io_tlh_min_savings_usd: int = 500
    io_rebalance_drift_threshold_pct: float = 3.0
    io_rebalance_es_warning_pct: float = 2.3

    watch_renew_enabled: bool = True
    watch_renew_check_seconds: int = 1800
    watch_renew_lead_seconds: int = 86400

    # ─── Plane PM integration ───
    plane_polling_enabled: bool = True
    plane_polling_interval_seconds: int = 300
    plane_base_url: str = ""
    plane_api_token: str = ""
    plane_webhook_secret: str = ""

    database_url: str = "postgresql+asyncpg://orchestration:changeme@localhost:5434/stewardos_db"
    log_level: str = "INFO"

    def resolve_persona_dir(self, alias: str) -> str | None:
        persona_name = self.alias_persona_map.get(alias)
        if not persona_name:
            return None
        return str(Path(self.agent_configs_root) / persona_name)


settings = Settings()


def alias_email(alias: str) -> str:
    """Return full +alias sender email for the dedicated agent mailbox."""
    local, _, domain = settings.agent_email.partition("@")
    return f"{local}+{alias}@{domain}" if domain else settings.agent_email
