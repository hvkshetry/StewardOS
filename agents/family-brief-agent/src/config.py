"""Configuration management for family brief agent."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service
    service_port: int = 8300
    service_host: str = "127.0.0.1"

    # Google OAuth2
    google_credentials_path: str = "credentials.json"
    google_token_path: str = ".google-token.json"

    # Google Pub/Sub (for Gmail push notifications)
    google_pubsub_project_id: str = ""
    google_pubsub_topic: str = ""

    # Agent identity — the dedicated family assistant Gmail address
    agent_email: str = ""

    # Sender allowlist — only emails from these addresses are processed.
    # All other senders are silently discarded (security boundary).
    family_emails: list[str] = []

    # Codex CLI
    codex_model: str = "gpt-5.4"
    codex_timeout_seconds: int = 3600

    # Scheduled tasks
    briefing_timezone: str = "America/New_York"
    pre_meeting_lead_minutes: int = 60
    schedules_path: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./family_brief_agent.db"

    # Logging
    log_level: str = "INFO"

    # Codex agent config directories (persona-specific .codex/config.toml)
    agent_config_dir_family: str = "$STEWARDOS_ROOT/agent-configs/chief-of-staff"
    agent_config_dir_personal_finance: str = "$STEWARDOS_ROOT/agent-configs/household-comptroller"
    agent_config_dir_personal_admin: str = "$STEWARDOS_ROOT/agent-configs/household-director"


settings = Settings()
