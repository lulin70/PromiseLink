"""Gateway configuration.

Loads settings from environment variables with sensible defaults for development
and testing. Production deployments should override all sensitive values via
environment variables or Docker secrets.

Reference: Pro_Edition_Tech_Design_Phase0.md §10.2 Environment Variables
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Prefix that marks an encrypted API key value.
ENC_PREFIX = "ENC:"

# Default RPM limit used by the API Key pool manager (§5.2).
DEFAULT_RPM_LIMIT = 60


class Settings(BaseSettings):
    """Gateway application settings.

    All values can be overridden via environment variables. The env_prefix is
    empty so variable names match the design document exactly (e.g.
    ``GATEWAY_ENV``, ``DATABASE_URL``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Basic ──
    gateway_env: str = Field(default="development", description="deployment environment")
    gateway_host: str = Field(default="0.0.0.0")
    gateway_port: int = Field(default=8000)
    gateway_secret_key: str = Field(default="dev-gateway-secret-key-min-32-chars!!")
    gateway_version: str = Field(default="1.0.0")

    # ── JWT ──
    # Use HS256 by default for dev/test; production should set jwt_algorithm=RS256
    # and provide JWT_PRIVATE_KEY_PATH / JWT_PUBLIC_KEY_PATH.
    jwt_algorithm: str = Field(default="HS256")
    jwt_secret_key: str = Field(default="dev-jwt-secret-key-min-32-chars-padding!")
    jwt_private_key_path: str = Field(default="")
    jwt_public_key_path: str = Field(default="")
    jwt_access_token_ttl: int = Field(default=900, description="15 minutes")
    jwt_refresh_token_ttl: int = Field(default=604800, description="7 days")
    jwt_issuer: str = Field(default="promiselink-gateway")
    jwt_audience: str = Field(default="promiselink-client")

    # ── Admin JWT (P0-4) ──
    admin_api_key: str = Field(default="dev-admin-api-key-min-32-chars-padding!!")
    admin_jwt_secret: str = Field(default="dev-admin-jwt-secret-min-32-chars!!!")
    admin_id: str = Field(default="admin_001")
    admin_passphrase: str = Field(default="dev-admin-passphrase")
    admin_jwt_ttl: int = Field(default=1800)

    # ── Admin monitoring key (deprecated — use admin_api_key + X-Admin-API-Key) ──
    gateway_admin_key: str = Field(
        default="dev-gateway-admin-key",
        description="Deprecated: admin monitoring key (X-Admin-Key header). "
                    "Admin API now uses admin_api_key with X-Admin-API-Key header + admin JWT.",
    )

    # ── Database ──
    database_url: str = Field(
        default="sqlite+aiosqlite:///:memory:",
        description="Async database URL. Use postgresql+asyncpg:// for production.",
    )
    pg_pool_size: int = Field(default=20)
    pg_max_overflow: int = Field(default=10)

    # ── Redis ──
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_maxmemory_policy: str = Field(
        default="volatile-lru",
        description=(
            "Redis maxmemory-policy. Use 'volatile-lru' (default) so that "
            "only keys with TTL (e.g. jwt_blacklist) can be evicted — "
            "never persistent data. 'allkeys-lru' is unsafe because it "
            "can evict the JWT blacklist, allowing revoked tokens to pass."
        ),
    )

    # ── Client API Key (X-API-Key header) ──
    api_key: str = Field(default="pl_gateway_client_dev_key")

    # ── LLM Providers ──
    moka_ai_base_url: str = Field(default="https://api.moka.ai/v1")
    moka_ai_api_key: str = Field(default="sk-moka-dev-key")
    moka_ai_price_per_1k_tokens: float = Field(default=0.002)

    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_api_key: str = Field(default="sk-openai-dev-key")
    openai_price_per_1k_tokens: float = Field(default=0.001)

    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    deepseek_api_key: str = Field(default="sk-deepseek-dev-key")
    deepseek_price_per_1k_tokens: float = Field(default=0.001)

    # ── Provider degradation ──
    primary_provider: str = Field(default="moka_ai")
    fallback_provider: str = Field(default="openai")

    # ── API Key pool ──
    key_pool_health_check_interval: int = Field(default=30)
    key_pool_cooldown_duration: int = Field(default=60)
    key_pool_circuit_duration: int = Field(default=300)
    key_pool_circuit_threshold: int = Field(default=3)
    key_pool_probe_timeout: int = Field(default=5)
    key_pool_rpm_limit: int = Field(default=DEFAULT_RPM_LIMIT, description="Default RPM limit per key")

    # ── API Key encryption (AES-256-GCM) ──
    gateway_encryption_key: str = Field(
        default="",
        description="Base64-encoded 32-byte key for API Key encryption. "
                    "Generate: python -c \"import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\"",
    )

    # ── Rate limiting ──
    rate_limit_user_per_minute: int = Field(default=100)
    rate_limit_user_per_hour: int = Field(default=1000)

    # ── Timeouts ──
    llm_request_timeout: float = Field(default=30.0)
    llm_max_retries: int = Field(default=3)
    asr_max_audio_size_mb: int = Field(default=25)
    tts_max_text_length: int = Field(default=500)
    ocr_max_image_size_mb: int = Field(default=10)

    # ── Logging ──
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")

    @property
    def is_production(self) -> bool:
        """Return True when running in production environment."""
        return self.gateway_env == "production"

    @property
    def is_test(self) -> bool:
        """Return True when running tests (env=test)."""
        return self.gateway_env == "test"

    def provider_base_url(self, provider: str) -> str:
        """Return the base URL for the given provider."""
        urls = {
            "moka_ai": self.moka_ai_base_url,
            "openai": self.openai_base_url,
            "deepseek": self.deepseek_base_url,
        }
        return urls.get(provider, self.moka_ai_base_url)

    def provider_api_key(self, provider: str) -> str:
        """Return the API key for the given provider."""
        keys = {
            "moka_ai": self.moka_ai_api_key,
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
        }
        return keys.get(provider, self.moka_ai_api_key)

    def provider_price_per_1k(self, provider: str) -> float:
        """Return the price per 1K tokens for the given provider."""
        prices = {
            "moka_ai": self.moka_ai_price_per_1k_tokens,
            "openai": self.openai_price_per_1k_tokens,
            "deepseek": self.deepseek_price_per_1k_tokens,
        }
        return prices.get(provider, self.moka_ai_price_per_1k_tokens)

    def get_encryption_key_bytes(self) -> bytes:
        """Return the raw 32-byte AES key for API Key encryption.

        If ``gateway_encryption_key`` is empty a deterministic development
        key is derived from ``gateway_secret_key`` so the gateway can boot
        locally.  Production MUST set ``GATEWAY_ENCRYPTION_KEY``.
        """
        if self.gateway_encryption_key:
            raw = base64.b64decode(self.gateway_encryption_key)
            if len(raw) != 32:
                raise ValueError(
                    f"GATEWAY_ENCRYPTION_KEY must decode to 32 bytes, got {len(raw)}"
                )
            return raw
        return hashlib.sha256(self.gateway_secret_key.encode()).digest()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    The cache ensures a single instance is reused across the application.
    Tests can clear the cache via ``get_settings.cache_clear()``.
    """
    return Settings()


def reload_settings(**overrides: Any) -> Settings:
    """Create a fresh Settings instance with optional overrides (for tests)."""
    get_settings.cache_clear()
    # Apply overrides via environment-like construction
    base = Settings()
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# ── API Key encryption helpers (AES-256-GCM) ──


def _aes_key() -> bytes:
    """Return the AES-256 key used for API Key encryption."""
    return get_settings().get_encryption_key_bytes()


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key with AES-256-GCM.

    Returns ``ENC:`` followed by base64(nonce || ciphertext).
    """
    key = _aes_key()
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ENC_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API key previously encrypted with :func:`encrypt_api_key`.

    If the value does not carry the ``ENC:`` prefix it is returned as-is
    (allows plain-text keys during migration).
    """
    if not encrypted.startswith(ENC_PREFIX):
        return encrypted
    key = _aes_key()
    data = base64.b64decode(encrypted[len(ENC_PREFIX):])
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def generate_encryption_key() -> str:
    """Generate a new base64-encoded 32-byte encryption key.

    Convenience helper for initial setup::

        python -c "from gateway.config import generate_encryption_key; print(generate_encryption_key())"
    """
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")
