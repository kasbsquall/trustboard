"""Central TrustBoard configuration, loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: str = ""

    database_url: str = "sqlite:///./trustboard.db"
    slack_webhook_url: str = ""

    # The Navigator agent is the only part of TrustBoard that calls a model, and
    # it is the only thing that needs this. Empty by default so the other four
    # components, the dashboard and the whole test suite run on a machine with no
    # key, which is most machines this will be run on.
    anthropic_api_key: str = ""
    trustboard_agent_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    """Single configuration instance (cached)."""
    return Settings()
