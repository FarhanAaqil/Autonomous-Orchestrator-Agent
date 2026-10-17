"""
orchestrator_core/config.py

Lazy settings configuration using pydantic-settings.
Settings are loaded on demand and cached, avoiding any import-time side effects
or reliance on global mutable singletons.
"""

import os
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Preload .env into os.environ so all standard library / SDK modules have access
load_dotenv(override=False)


class Settings(BaseSettings):
    """Application settings read from environment variables and .env file."""

    database_path: str = "database/orchestrator.db"
    chroma_db_dir: str = "chroma_db"
    groq_api_key: Optional[str] = None
    router_model: str = "openai/gpt-oss-120b"
    router_confidence_threshold: float = 0.6
    auth_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("auth_token", "api_bearer_token"),
    )
    environment: str = "development"
    app_version: str = "1.0.0"
    executor_hmac_secret: str = Field(
        default="aaqil-secret-hmac-key-dev-environment",
        validation_alias=AliasChoices("executor_hmac_secret", "EXECUTOR_HMAC_SECRET"),
    )

    # External integrations & credentials
    email_address: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("email_address", "EMAIL_ADDRESS"),
    )
    email_app_password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("email_app_password", "EMAIL_APP_PASSWORD"),
    )
    enable_real_email: bool = Field(
        default=False,
        validation_alias=AliasChoices("enable_real_email", "ENABLE_REAL_EMAIL"),
    )
    github_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("github_token", "GITHUB_TOKEN"),
    )
    hashnode_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("hashnode_token", "HASHNODE_TOKEN"),
    )
    devto_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("devto_api_key", "DEVTO_API_KEY"),
    )
    linkedin_email: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("linkedin_email", "LINKEDIN_EMAIL"),
    )
    linkedin_password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("linkedin_password", "LINKEDIN_PASSWORD"),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context) -> None:
        if os.path.exists("/app/data") and self.database_path == "database/orchestrator.db":
            self.database_path = "/app/data/orchestrator.db"
        if os.path.exists("/app/data") and self.chroma_db_dir == "chroma_db":
            self.chroma_db_dir = "/app/data/chroma_db"


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance. Safe to use as a FastAPI dependency."""
    return Settings()
