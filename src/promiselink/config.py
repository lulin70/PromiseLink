"""Application configuration management."""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLM_PRESETS: dict[str, dict[str, str]] = {
    "moka_ai": {"base_url": "https://api.moka-ai.com/v1", "model": "moka/claude-sonnet-4-6"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-5.5"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-6-20250514"},
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "PromiseLink"
    app_version: str = "0.8.0-rc2"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    app_edition: str = "basic"  # "basic" or "pro"

    # API
    api_host: str = "0.0.0.0"  # nosec B104 — container must bind all interfaces; port mapping controls exposure
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8000",
            "http://localhost:10086",
            "https://promiselink.cn",
            "https://www.promiselink.cn",
        ],
        description="Allowed CORS origins",
    )

    @field_validator("app_edition", mode="before")
    @classmethod
    def validate_app_edition(cls, v: Any) -> str:
        """Validate app_edition is either 'basic' or 'pro'."""
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower in ("basic", "pro"):
                return v_lower
        raise ValueError("app_edition must be either 'basic' or 'pro'")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            import json
            return json.loads(v)  # type: ignore[no-any-return]
        return v  # type: ignore[no-any-return]

    # Database
    database_url: str = "sqlite:///./data/promiselink.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    # WeChat Mini Program
    wechat_app_id: str = Field(default="")
    wechat_app_secret: str = Field(default="")

    # Authentication
    secret_key: str = Field(
        default="change-me-in-production",
        description="JWT signing key; MUST be changed for any deployment. "
                    "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
    )
    pii_encryption_key: str = Field(default="", description="Independent key for PII encryption; if empty, falls back to secret_key")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    poc_anonymous_access: bool = Field(default=False, description="PoC only: allow unauthenticated access with default user")
    poc_secret: str = Field(
        default="promiselink2026",
        description="PoC login secret; please change this default password immediately",
    )
    allow_insecure_key: bool = Field(default=False, description="Allow default secret key in non-test environments (development convenience)")
    trusted_proxies: list[str] = Field(default_factory=list, description="Trusted reverse proxy IPs for X-Forwarded-For")

    # LLM Provider
    llm_provider: str = "moka_ai"  # moka_ai, openai, anthropic — see LLM_PRESETS
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="")
    llm_model: str = Field(default="")
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.3
    llm_timeout: int = 60
    llm_max_retries: int = 3

    # Embedding Provider
    embedding_provider: str = Field(default="local", description="Embedding provider: local (sentence-transformers) or api (OpenAI-compatible)")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="Local model name or API model name")

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

    # Entity Properties Validation
    strict_properties_validation: bool = Field(
        default=False,
        description="If True, raise on EntityProperties validation failure "
                    "instead of graceful degradation",
    )

    # Opportunity Matching
    opportunity_match_strong_threshold: float = 0.80
    opportunity_match_potential_threshold: float = 0.60

    # ── Pro Edition: Gateway Relay ──
    relay_gateway_url: str = Field(default="", description="网关WSS地址，设置即启用relay_client")
    relay_user_token: str = Field(default="", description="网关JWT令牌")
    relay_reconnect_interval: int = 1  # 初始重连间隔(秒)
    relay_reconnect_max: int = 30  # 最大重连间隔(秒)
    relay_heartbeat_interval: int = 30  # 心跳间隔(秒)
    relay_token_refresh_interval: int = 900  # relay token刷新间隔(秒)

    # ── Pro Edition: License Verification ──
    pro_license_key: str = Field(default="", description="专业版许可证密钥")

    # Rate Limiting (basic版适当放宽)
    rate_limit_enabled: bool = True
    rate_limit_authenticated: int = 200   # 基础版单用户放宽
    rate_limit_unauthenticated: int = 30
    rate_limit_llm: int = 30

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
    def apply_llm_preset(self) -> "Settings":
        """Auto-fill llm_base_url and llm_model from LLM_PRESETS if not explicitly set."""
        preset = LLM_PRESETS.get(self.llm_provider)
        if preset:
            if not self.llm_base_url:
                self.llm_base_url = preset["base_url"]
            if not self.llm_model:
                self.llm_model = preset["model"]
        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Validate critical settings and auto-fix insecure defaults."""
        import secrets

        if self.secret_key == "change-me-in-production":
            if self.app_env == "development":
                # Auto-generate a random key in development to prevent token forgery
                self.secret_key = secrets.token_urlsafe(32)
                import structlog
                structlog.get_logger().warning(
                    "⚠️  AUTO-GENERATED SECRET KEY",
                    note="SECRET_KEY was the default 'change-me-in-production'. "
                         "A random key has been generated for this session. "
                         "Tokens will be invalid after restart. "
                         "Set SECRET_KEY in .env for persistent sessions.",
                )
            else:
                if self.allow_insecure_key:
                    import structlog
                    structlog.get_logger().warning(
                        "⚠️  DEFAULT SECRET KEY IN NON-DEVELOPMENT ENVIRONMENT",
                        note="This is extremely insecure. Set SECRET_KEY immediately.",
                    )
                else:
                    raise ValueError(
                        "secret_key must be changed from default in non-development environments. "
                        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                    )

        if not self.llm_api_key:
            import structlog
            structlog.get_logger().warning("llm_api_key_empty", note="Set LLM_API_KEY env var")

        if self.app_env != "development":
            if not self.llm_api_key:
                raise ValueError("llm_api_key must be set in non-development environments")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
