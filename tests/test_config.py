"""Unit tests for Settings configuration validation.

Focuses on P1-4: production environment must reject POC backdoor
(``poc_anonymous_access``) and default secret key backdoor (``allow_insecure_key``).

These are pure unit tests that do not require database or HTTP fixtures.
"""

import pytest
from pydantic import ValidationError

from promiselink.config import Settings

# ── Helpers ──


def _make_production_settings(**overrides) -> Settings:
    """Build a Settings instance with production-safe defaults.

    All security-sensitive flags are set to safe values; callers override
    the specific flag under test.
    """
    defaults = {
        "app_env": "production",
        "secret_key": "a-very-secure-production-secret-key-1234567890",
        "llm_api_key": "sk-test-key-for-production",
        "poc_anonymous_access": False,
        "allow_insecure_key": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── P1-4: Production security validation ──


class TestProductionSecurityValidation:
    """P1-4: Production environment must reject insecure backdoor flags."""

    def test_production_rejects_poc_anonymous_access(self):
        """poc_anonymous_access=True in production must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            _make_production_settings(poc_anonymous_access=True)
        message = str(exc_info.value)
        assert "poc_anonymous_access" in message
        assert "False" in message or "false" in message.lower()

    def test_production_rejects_allow_insecure_key(self):
        """allow_insecure_key=True in production must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            _make_production_settings(allow_insecure_key=True)
        message = str(exc_info.value)
        assert "allow_insecure_key" in message
        assert "False" in message or "false" in message.lower()

    def test_production_accepts_secure_config(self):
        """A fully secure production config must instantiate without error."""
        settings = _make_production_settings()
        assert settings.app_env == "production"
        assert settings.poc_anonymous_access is False
        assert settings.allow_insecure_key is False

    def test_production_rejects_both_backdoors_simultaneously(self):
        """Both backdoors enabled together must still be rejected."""
        with pytest.raises(ValidationError):
            _make_production_settings(
                poc_anonymous_access=True, allow_insecure_key=True
            )

    def test_staging_env_also_rejects_poc_anonymous_access(self):
        """Any non-development environment (e.g. staging) must reject POC backdoor."""
        with pytest.raises(ValidationError):
            _make_production_settings(app_env="staging", poc_anonymous_access=True)

    def test_staging_env_also_rejects_allow_insecure_key(self):
        """Any non-development environment (e.g. staging) must reject insecure key."""
        with pytest.raises(ValidationError):
            _make_production_settings(app_env="staging", allow_insecure_key=True)


# ── P1-4: Development environment keeps convenience ──


class TestDevelopmentAllowsBackdoors:
    """P1-4: Development environment allows POC and insecure key for convenience."""

    def test_dev_allows_poc_anonymous_access(self):
        """poc_anonymous_access=True in development must NOT raise."""
        settings = Settings(
            app_env="development",
            poc_anonymous_access=True,
            allow_insecure_key=True,
        )
        assert settings.poc_anonymous_access is True

    def test_dev_allows_allow_insecure_key(self):
        """allow_insecure_key=True in development must NOT raise."""
        settings = Settings(
            app_env="development",
            allow_insecure_key=True,
        )
        assert settings.allow_insecure_key is True

    def test_dev_defaults_are_safe(self):
        """Default Settings (development) must have both backdoors disabled."""
        settings = Settings(app_env="development")
        # Default field values — backdoors are opt-in even in dev
        assert settings.poc_anonymous_access is False
        assert settings.allow_insecure_key is False
