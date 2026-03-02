"""Configuration for remote family-office ingress service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_port: int = 8311
    service_host: str = "127.0.0.1"
    worker_webhook_url: str = ""
    worker_shared_secret: str = ""
    log_level: str = "INFO"


settings = Settings()
