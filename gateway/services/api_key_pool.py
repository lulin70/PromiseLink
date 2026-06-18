"""API Key pool manager.

Implements weighted round-robin key selection, health score tracking,
rate-limit cooldown, and circuit breaker logic.

Reference: Pro_Edition_Tech_Design_Phase0.md §5 API Key Pool Algorithm
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from gateway.config import Settings, get_settings


@dataclass
class KeyInfo:
    """Runtime info for a single API key."""

    key_id: str
    provider: str
    api_key: str
    base_url: str
    weight: int = 100
    health_score: float = 1.0
    status: str = "active"  # active / rate_limited / circuit_open / disabled
    consecutive_failures: int = 0
    last_used_at: float | None = None
    last_error: str | None = None
    cooldown_until: float | None = None
    circuit_opened_at: float | None = None
    current_rpm: int = 0

    @property
    def is_available(self) -> bool:
        """Return True if the key is currently selectable."""
        if self.status == "disabled":
            return False
        now = time.time()
        if self.status == "rate_limited" and self.cooldown_until and now < self.cooldown_until:
            return False
        if (
            self.status == "circuit_open"
            and self.circuit_opened_at
            and now < self.circuit_opened_at + 300  # 5-minute circuit
        ):
            return False
        return True

    @property
    def effective_weight(self) -> float:
        """Calculate effective weight: base × health × (1 - rpm_ratio)."""
        # Simplified: assume rpm_limit=60 for ratio calculation
        rpm_ratio = min(self.current_rpm / 60.0, 1.0) if self.current_rpm > 0 else 0.0
        return self.weight * self.health_score * (1.0 - rpm_ratio)


class APIKeyPool:
    """Manages a pool of API keys with weighted selection and health tracking.

    The pool is initialized with a list of KeyInfo objects. In production,
    these are loaded from the database; in tests, they can be injected directly.
    """

    def __init__(
        self,
        keys: list[KeyInfo] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._keys: dict[str, KeyInfo] = {}
        if keys:
            for k in keys:
                self._keys[k.key_id] = k

    def add_key(self, key: KeyInfo) -> None:
        """Add a key to the pool."""
        self._keys[key.key_id] = key

    def get_key(self, key_id: str) -> KeyInfo | None:
        """Return a key by ID."""
        return self._keys.get(key_id)

    def select_key(self, provider: str | None = None) -> KeyInfo:
        """Select an available key using weighted random selection.

        Args:
            provider: If set, only select keys for this provider.

        Returns:
            The selected KeyInfo.

        Raises:
            NoAvailableKeyError: If no keys are available.
        """
        from gateway.core.exceptions import NoAvailableKeyError

        candidates = [
            k
            for k in self._keys.values()
            if k.is_available and (provider is None or k.provider == provider)
        ]
        if not candidates:
            # Try fallback: any available key regardless of provider
            candidates = [k for k in self._keys.values() if k.is_available]
        if not candidates:
            raise NoAvailableKeyError(
                details={"retry_after": 60, "alternative": "Basic features still available"}
            )

        total_weight = sum(k.effective_weight for k in candidates)
        if total_weight <= 0:
            # All weights are zero — pick randomly
            return random.choice(candidates)

        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for k in candidates:
            cumulative += k.effective_weight
            if r <= cumulative:
                k.last_used_at = time.time()
                return k
        return candidates[-1]  # fallback

    def mark_success(self, key_id: str) -> None:
        """Mark a key as having a successful request (health +0.05)."""
        key = self._keys.get(key_id)
        if key:
            key.health_score = min(1.0, key.health_score + 0.05)
            key.consecutive_failures = 0

    def mark_rate_limited(self, key_id: str) -> None:
        """Mark a key as rate-limited (429 from provider)."""
        key = self._keys.get(key_id)
        if key:
            key.status = "rate_limited"
            key.cooldown_until = time.time() + self.settings.key_pool_cooldown_duration
            key.health_score = max(0.0, key.health_score - 0.20)
            key.last_error = "Provider returned 429"

    def mark_5xx_error(self, key_id: str) -> None:
        """Mark a key as having a 5xx error (health -0.30, circuit after 3)."""
        key = self._keys.get(key_id)
        if key:
            key.consecutive_failures += 1
            key.health_score = max(0.0, key.health_score - 0.30)
            key.last_error = "Provider returned 5xx"
            if key.consecutive_failures >= self.settings.key_pool_circuit_threshold:
                key.status = "circuit_open"
                key.circuit_opened_at = time.time()

    def mark_timeout(self, key_id: str) -> None:
        """Mark a key as having timed out (health -0.25)."""
        key = self._keys.get(key_id)
        if key:
            key.health_score = max(0.0, key.health_score - 0.25)
            key.last_error = "Request timed out"

    def mark_network_error(self, key_id: str) -> None:
        """Mark a key as having a network error (health -0.20)."""
        key = self._keys.get(key_id)
        if key:
            key.health_score = max(0.0, key.health_score - 0.20)
            key.last_error = "Network error"

    def reset_key(self, key_id: str) -> None:
        """Reset a key to active state (after recovery probe)."""
        key = self._keys.get(key_id)
        if key:
            key.status = "active"
            key.consecutive_failures = 0
            key.cooldown_until = None
            key.circuit_opened_at = None
            key.health_score = min(1.0, key.health_score + 0.10)

    @property
    def active_count(self) -> int:
        """Return the number of active keys."""
        return sum(1 for k in self._keys.values() if k.status == "active")

    @property
    def total_count(self) -> int:
        """Return the total number of keys."""
        return len(self._keys)

    @property
    def circuit_open_count(self) -> int:
        """Return the number of circuit-open keys."""
        return sum(1 for k in self._keys.values() if k.status == "circuit_open")

    def get_status(self) -> dict[str, Any]:
        """Return pool status summary for health checks."""
        return {
            "active_keys": self.active_count,
            "total_keys": self.total_count,
            "circuit_open_count": self.circuit_open_count,
        }


def create_default_key_pool(settings: Settings | None = None) -> APIKeyPool:
    """Create a default key pool from settings (for dev/testing)."""
    s = settings or get_settings()
    keys = [
        KeyInfo(
            key_id="key-moka-1",
            provider="moka_ai",
            api_key=s.moka_ai_api_key,
            base_url=s.moka_ai_base_url,
        ),
        KeyInfo(
            key_id="key-openai-1",
            provider="openai",
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
        ),
    ]
    return APIKeyPool(keys=keys, settings=s)
