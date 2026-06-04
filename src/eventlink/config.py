"""Application configuration management."""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "EventLink"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    # Database
    database_url: str = "sqlite:///./data/eventlink.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    # WeChat Mini Program
    wechat_app_id: str = Field(default="")
    wechat_app_secret: str = Field(default="")

    # Authentication
    secret_key: str = Field(default="change-me-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # LLM Provider
    llm_provider: str = "moka_ai"  # anthropic, openai, moka_ai
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.moka-ai.com/v1")
    llm_model: str = Field(default="moka/claude-sonnet-4-6")
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.3
    llm_timeout: int = 60
    llm_max_retries: int = 3

    # CarryMem Integration
    carrymem_enabled: bool = False
    carrymem_api_url: str = "http://localhost:8100"
    carrymem_api_key: str = ""

    # Memory Provider (raw data storage)
    memory_provider: str = "null"  # null, file, carrymem
    memory_file_base_dir: str = "./data/memory"

    # Entity Resolution
    entity_resolution_auto_merge_threshold: float = 0.80
    entity_resolution_human_review_threshold: float = 0.70

    # Opportunity Matching
    opportunity_match_strong_threshold: float = 0.80
    opportunity_match_potential_threshold: float = 0.60

    # Performance
    max_workers: int = 4
    request_timeout: int = 30

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return self.database_url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL database."""
        return self.database_url.startswith("postgresql")

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Validate critical settings in non-development environments."""
        if self.app_env == "development":
            if self.secret_key == "change-me-in-production":
                print("WARNING: Using default secret_key in development mode")
            if not self.llm_api_key:
                print("WARNING: llm_api_key is empty in development mode")
        else:
            if self.secret_key == "change-me-in-production":
                raise ValueError("secret_key must be changed from default in non-development environments")
            if not self.llm_api_key:
                raise ValueError("llm_api_key must be set in non-development environments")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
