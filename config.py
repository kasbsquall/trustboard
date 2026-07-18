"""Configuracion central de TrustBoard, cargada desde variables de entorno."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: str = ""
    datahub_mcp_url: str = "http://localhost:8080/mcp"

    database_url: str = "sqlite:///./trustboard.db"
    slack_webhook_url: str = ""
    backend_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """Instancia unica de configuracion (cacheada)."""
    return Settings()
