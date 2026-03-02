"""Configuration for family-office mail worker."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    agent_email: str = "agent@example.com"
    allowed_senders: list[str] = []

    alias_persona_map: dict[str, str] = {
        "cos": "agent-configs/chief-of-staff",
        "estate": "agent-configs/estate-counsel",
        "hc": "agent-configs/household-comptroller",
        "hd": "agent-configs/household-director",
        "io": "agent-configs/investment-officer",
        "wellness": "agent-configs/wellness-advisor",
    }

    alias_display_name_map: dict[str, str] = {
        "cos": "Chief of Staff Agent",
        "estate": "Estate Counsel",
        "hc": "Household Comptroller",
        "hd": "Household Director",
        "io": "Investment Officer",
        "wellness": "Wellness Advisor",
    }

    codex_bin: str = "codex"
    codex_timeout_seconds: int = 360
    codex_scratch_dir: str = "/tmp/family-office-mail-worker"
    require_send_ack: bool = True

    scheduled_briefs_enabled: bool = True
    briefing_timezone: str = "America/New_York"
    scheduled_recipients: list[str] = [
        "ops@example.com",
        "finance@example.com",
    ]
    cos_weekly_recipients: list[str] = [
        "ops@example.com",
        "finance@example.com",
        "admin@example.com",
        "wellness@example.com",
    ]
    io_preopen_cron: str = "0 6 * * MON"
    io_postclose_cron: str = "0 18 * * FRI"
    cos_weekly_cron: str = "0 7 * * MON"
    io_tlh_min_savings_usd: int = 500
    io_rebalance_drift_threshold_pct: float = 3.0
    io_rebalance_es_warning_pct: float = 2.3

    watch_renew_enabled: bool = True
    watch_renew_check_seconds: int = 1800
    watch_renew_lead_seconds: int = 86400

    database_url: str = "sqlite+aiosqlite:///./family_office_mail_worker.db"
    log_level: str = "INFO"


settings = Settings()


def alias_email(alias: str) -> str:
    """Return full +alias sender email for the dedicated agent mailbox."""
    local, _, domain = settings.agent_email.partition("@")
    return f"{local}+{alias}@{domain}" if domain else settings.agent_email
