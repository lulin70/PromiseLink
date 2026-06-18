"""API Key pool manager with weighted round-robin, health scoring,
cooldown, and circuit-breaker recovery.

Reference: Pro_Edition_Tech_Design_Phase0.md §5

Design overview
---------------
Each provider (DeepSeek, Moka AI, …) has one or more API keys in the
pool.  The manager keeps an **in-memory** copy of every key's runtime
state and uses an :class:`asyncio.Lock` to serialise mutations, making
it safe to call from concurrent FastAPI request handlers.

Selection algorithm (§5.2)::

    effective_weight = base_weight × health_score × (1 − rpm_ratio)
    rpm_ratio = current_minute_requests / rpm_limit

Keys are filtered to those that are ``active``, past any cooldown /
circuit-breaker window, and below their RPM limit.  A weighted random
choice is then made over the survivors.

Failure handling (§5.4, §5.5)::

    429          → cooldown 60 s,  health_score − 0.20
    5xx (×3)     → circuit 5 min, health_score − 0.30 per failure
    timeout      →                health_score − 0.25
    network err  →                health_score − 0.20

Recovery (§5.6): after the cooldown / circuit window expires a probe
request is sent; on success the key returns to ``active``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

logger = logging.getLogger("gateway.api_key_pool")


# ── Health-score deltas (§5.3) ──
DELTA_SUCCESS = 0.05  # +0.05 on 2xx
DELTA_429 = -0.20  # −0.20 on rate-limit
DELTA_5XX = -0.30  # −0.30 on server error
DELTA_TIMEOUT = -0.25  # −0.25 on timeout
DELTA_NETWORK = -0.20  # −0.20 on network error
DELTA_PROBE_SUCCESS = 0.10  # +0.10 on probe success

HEALTH_SCORE_MIN = 0.0
HEALTH_SCORE_MAX = 1.0

# Sentinel status codes for non-HTTP failures.
STATUS_TIMEOUT = -1
STATUS_NETWORK_ERROR = -2


class KeyStatus(str, Enum):
    """Runtime status of a pool key."""

    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"
    DISABLED = "disabled"


# Type alias for the probe function: async (key_id) -> success?
ProbeFn = Callable[[str], Awaitable[bool]]
# Type alias for the clock function: () -> unix_timestamp
ClockFn = Callable[[], float]


class SupportsBool(Protocol):
    """Minimal protocol for objects that can be evaluated as bool."""

    def __bool__(self) -> bool: ...


@dataclass
class KeyState:
    """In-memory runtime state of a single API key.

    This is a mutable dataclass; the pool manager updates fields in place
    under the protection of an :class:`asyncio.Lock`.
    """

    key_id: str
    provider: str
    base_weight: int = 100
    health_score: float = 1.0
    status: KeyStatus = KeyStatus.ACTIVE
    consecutive_failures: int = 0
    cooldown_until: float | None = None  # unix timestamp
    circuit_breaker_until: float | None = None  # unix timestamp
    last_used_at: float | None = None

    # RPM tracking — per-minute counter.
    _rpm_minute: int = field(default=0, repr=False)
    _rpm_count: int = field(default=0, repr=False)

    # Lifetime statistics (informational).
    total_requests: int = 0
    success_requests: int = 0
    failed_requests: int = 0

    def rpm(self, now: float) -> int:
        """Return the request count for the current minute, resetting if
        the minute has rolled over."""
        minute = int(now) // 60
        if minute != self._rpm_minute:
            self._rpm_minute = minute
            self._rpm_count = 0
        return self._rpm_count

    def increment_rpm(self, now: float) -> int:
        """Increment and return the RPM counter for the current minute."""
        minute = int(now) // 60
        if minute != self._rpm_minute:
            self._rpm_minute = minute
            self._rpm_count = 0
        self._rpm_count += 1
        return self._rpm_count

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-serialisable snapshot of the current state."""
        return {
            "key_id": self.key_id,
            "provider": self.provider,
            "base_weight": self.base_weight,
            "health_score": round(self.health_score, 4),
            "status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_until": self.cooldown_until,
            "circuit_breaker_until": self.circuit_breaker_until,
            "last_used_at": self.last_used_at,
            "rpm": self._rpm_count,
            "total_requests": self.total_requests,
            "success_requests": self.success_requests,
            "failed_requests": self.failed_requests,
        }


class APIKeyPoolManager:
    """Manages a pool of API keys with weighted selection and self-healing.

    The manager is designed to be **testable in isolation**: it accepts a
    list of :class:`KeyState` objects, an injectable probe function, and an
    injectable clock function.  No database or Redis connection is
    required for unit testing.

    Example::

        manager = APIKeyPoolManager(
            keys=[KeyState("k1", "deepseek"), KeyState("k2", "deepseek")],
            probe_fn=lambda kid: asyncio.sleep(0, result=True),
        )
        selected = await manager.select_key("deepseek")
    """

    def __init__(
        self,
        keys: list[KeyState] | None = None,
        *,
        probe_fn: ProbeFn | None = None,
        clock_fn: ClockFn | None = None,
        cooldown_duration: float = 60.0,
        circuit_duration: float = 300.0,
        circuit_threshold: int = 3,
        rpm_limit: int = 60,
        health_check_interval: float = 30.0,
    ) -> None:
        """Initialise the pool manager.

        Args:
            keys: Initial key states.  May be empty; keys can be added
                later via :meth:`add_key`.
            probe_fn: Async function ``async (key_id) -> bool`` used for
                health-check probes.  If ``None`` probes always succeed.
            clock_fn: Function returning the current unix timestamp.
                Defaults to :func:`time.time`.  Inject a mock in tests.
            cooldown_duration: Seconds a key stays in cooldown after a
                429 response (default 60).
            circuit_duration: Seconds a key stays circuit-broken after
                ``circuit_threshold`` consecutive 5xx errors (default 300).
            circuit_threshold: Consecutive 5xx failures that trip the
                circuit breaker (default 3).
            rpm_limit: Maximum requests per minute per key (default 60).
            health_check_interval: Interval between automatic
                :meth:`health_check` calls in seconds (default 30).
        """
        self._keys: dict[str, KeyState] = {}
        if keys:
            for k in keys:
                self._keys[k.key_id] = k

        self._probe_fn: ProbeFn = probe_fn or _default_probe
        self._clock_fn: ClockFn = clock_fn or time.time
        self._cooldown_duration = cooldown_duration
        self._circuit_duration = circuit_duration
        self._circuit_threshold = circuit_threshold
        self._rpm_limit = rpm_limit
        self._health_check_interval = health_check_interval

        self._lock = asyncio.Lock()
        self._health_check_task: asyncio.Task[None] | None = None

    # ── Key management ──

    def add_key(self, key: KeyState) -> None:
        """Add a key to the pool (thread-unsafe; call before serving)."""
        self._keys[key.key_id] = key

    def remove_key(self, key_id: str) -> KeyState | None:
        """Remove a key from the pool (thread-unsafe; call before serving)."""
        return self._keys.pop(key_id, None)

    def get_key(self, key_id: str) -> KeyState | None:
        """Return the key state for *key_id* (read-only, no lock)."""
        return self._keys.get(key_id)

    @property
    def all_keys(self) -> list[KeyState]:
        """Return a list of all key states (read-only copy)."""
        return list(self._keys.values())

    def active_keys(self, provider: str | None = None) -> list[KeyState]:
        """Return active keys, optionally filtered by provider."""
        result = []
        for k in self._keys.values():
            if k.status != KeyStatus.ACTIVE:
                continue
            if provider is not None and k.provider != provider:
                continue
            result.append(k)
        return result

    # ── Selection ──

    def _is_available(self, key: KeyState, now: float) -> bool:
        """Check whether *key* is eligible for selection at time *now*."""
        if key.status != KeyStatus.ACTIVE:
            return False
        # Safety: even an 'active' key should not be past its cooldown /
        # circuit window (defensive — normally cleared on recovery).
        if key.cooldown_until is not None and now < key.cooldown_until:
            return False
        if key.circuit_breaker_until is not None and now < key.circuit_breaker_until:
            return False
        # RPM limit check.
        if key.rpm(now) >= self._rpm_limit:
            return False
        return True

    def _effective_weight(self, key: KeyState, now: float) -> float:
        """Compute the effective weight for weighted random selection.

        ``effective_weight = base_weight × health_score × (1 − rpm_ratio)``
        """
        rpm_ratio = key.rpm(now) / self._rpm_limit
        rpm_ratio = min(rpm_ratio, 1.0)
        return key.base_weight * key.health_score * (1.0 - rpm_ratio)

    async def select_key(self, provider: str) -> KeyState | None:
        """Select an available key for *provider* using weighted round-robin.

        Returns ``None`` when no key is available (caller should return
        ``503 NO_AVAILABLE_KEY``).

        The RPM counter of the selected key is incremented atomically
        under the pool lock.
        """
        now = self._clock_fn()
        async with self._lock:
            candidates = [
                k for k in self._keys.values()
                if k.provider == provider and self._is_available(k, now)
            ]
            if not candidates:
                return None

            weights = [self._effective_weight(k, now) for k in candidates]
            total = sum(weights)
            if total <= 0:
                # All weights are zero (e.g. health_score == 0).  Fall back
                # to uniform random among candidates so we don't deadlock.
                selected = random.choice(candidates)
            else:
                selected = random.choices(candidates, weights=weights, k=1)[0]

            selected.increment_rpm(now)
            selected.last_used_at = now
            selected.total_requests += 1
            return selected

    # ── Success / failure recording ──

    async def record_success(self, key_id: str) -> None:
        """Record a successful (2xx) request for *key_id*.

        Increments health score by 0.05 (capped at 1.00) and resets the
        consecutive-failure counter.
        """
        async with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                logger.warning("record_success: unknown key %s", key_id)
                return
            key.health_score = min(
                key.health_score + DELTA_SUCCESS, HEALTH_SCORE_MAX
            )
            key.consecutive_failures = 0
            key.success_requests += 1
            # A successful request implies the key is healthy.
            if key.status != KeyStatus.DISABLED:
                key.status = KeyStatus.ACTIVE
                key.cooldown_until = None
                key.circuit_breaker_until = None

    async def record_failure(self, key_id: str, status_code: int) -> None:
        """Record a failed request for *key_id*.

        Handling depends on the status code:

        * ``429`` → cooldown for ``cooldown_duration`` seconds,
          health_score − 0.20.
        * ``500``–``599`` → consecutive_failures += 1, health_score − 0.30.
          If ``consecutive_failures >= circuit_threshold`` the key is
          circuit-broken for ``circuit_duration`` seconds.
        * :data:`STATUS_TIMEOUT` (−1) → health_score − 0.25.
        * :data:`STATUS_NETWORK_ERROR` (−2) → health_score − 0.20.
        """
        now = self._clock_fn()
        async with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                logger.warning("record_failure: unknown key %s", key_id)
                return

            key.failed_requests += 1

            if status_code == 429:
                self._handle_rate_limited(key, now)
            elif 500 <= status_code < 600:
                self._handle_5xx(key, now)
            elif status_code == STATUS_TIMEOUT:
                self._apply_health_delta(key, DELTA_TIMEOUT)
            elif status_code == STATUS_NETWORK_ERROR:
                self._apply_health_delta(key, DELTA_NETWORK)
            else:
                # Unknown failure — apply a small penalty.
                self._apply_health_delta(key, DELTA_NETWORK)

    def _handle_rate_limited(self, key: KeyState, now: float) -> None:
        """Apply 429 cooldown (§5.4)."""
        self._apply_health_delta(key, DELTA_429)
        key.status = KeyStatus.RATE_LIMITED
        key.cooldown_until = now + self._cooldown_duration
        logger.info(
            "key %s rate-limited, cooldown until %.0f",
            key.key_id, key.cooldown_until,
        )

    def _handle_5xx(self, key: KeyState, now: float) -> None:
        """Apply 5xx failure handling and circuit breaker (§5.5)."""
        self._apply_health_delta(key, DELTA_5XX)
        key.consecutive_failures += 1
        if key.consecutive_failures >= self._circuit_threshold:
            key.status = KeyStatus.CIRCUIT_OPEN
            key.circuit_breaker_until = now + self._circuit_duration
            logger.warning(
                "key %s circuit opened after %d consecutive failures",
                key.key_id, key.consecutive_failures,
            )

    @staticmethod
    def _apply_health_delta(key: KeyState, delta: float) -> None:
        """Apply *delta* to the key's health score, clamped to [0, 1]."""
        key.health_score = max(
            min(key.health_score + delta, HEALTH_SCORE_MAX),
            HEALTH_SCORE_MIN,
        )

    # ── Health check & recovery ──

    async def health_check(self) -> None:
        """Probe all non-active, non-disabled keys whose cooldown or
        circuit-breaker window has expired.

        This method is designed to be called periodically (every
        ``health_check_interval`` seconds) by a background task started
        via :meth:`start_health_check_loop`.
        """
        now = self._clock_fn()
        # Collect candidates under the lock, then probe outside the lock
        # to avoid blocking other operations during HTTP probes.
        async with self._lock:
            candidates: list[KeyState] = []
            for key in self._keys.values():
                if key.status in (KeyStatus.ACTIVE, KeyStatus.DISABLED):
                    continue
                if self._recovery_window_expired(key, now):
                    candidates.append(key)

        for key in candidates:
            await self.recover_key(key.key_id)

    async def recover_key(self, key_id: str) -> bool:
        """Probe a single key and recover it if the probe succeeds.

        Returns ``True`` if the key was recovered to ``active``, ``False``
        otherwise (still in cooldown / circuit, or probe failed).

        If the cooldown / circuit window has **not** yet expired the
        method returns ``False`` immediately without probing.
        """
        now = self._clock_fn()

        async with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return False
            if key.status in (KeyStatus.ACTIVE, KeyStatus.DISABLED):
                return key.status == KeyStatus.ACTIVE
            if not self._recovery_window_expired(key, now):
                return False
            # Mark intent to probe (keep status as-is until probe completes).

        # Probe outside the lock.
        try:
            success = await self._probe_fn(key_id)
        except Exception:
            logger.exception("probe failed for key %s", key_id)
            success = False

        now = self._clock_fn()
        async with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return False
            if success:
                key.status = KeyStatus.ACTIVE
                key.consecutive_failures = 0
                key.health_score = min(
                    key.health_score + DELTA_PROBE_SUCCESS, HEALTH_SCORE_MAX
                )
                key.cooldown_until = None
                key.circuit_breaker_until = None
                logger.info("key %s recovered to active", key_id)
                return True
            else:
                # Extend the cooldown / circuit window.
                if key.status == KeyStatus.RATE_LIMITED:
                    key.cooldown_until = now + self._cooldown_duration
                elif key.status == KeyStatus.CIRCUIT_OPEN:
                    key.circuit_breaker_until = now + self._circuit_duration
                logger.info("key %s probe failed, extended penalty", key_id)
                return False

    def _recovery_window_expired(self, key: KeyState, now: float) -> bool:
        """Check whether the key's cooldown / circuit window has expired."""
        if key.status == KeyStatus.RATE_LIMITED:
            return key.cooldown_until is None or now >= key.cooldown_until
        if key.status == KeyStatus.CIRCUIT_OPEN:
            return (
                key.circuit_breaker_until is None
                or now >= key.circuit_breaker_until
            )
        return False

    # ── Background health-check loop ──

    async def start_health_check_loop(self) -> None:
        """Start the periodic health-check background task.

        The task runs until :meth:`stop_health_check_loop` is called or
        the event loop is closed.  Calling this method when a task is
        already running is a no-op.
        """
        if self._health_check_task is not None and not self._health_check_task.done():
            return
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop_health_check_loop(self) -> None:
        """Cancel the periodic health-check task if running."""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    async def _health_check_loop(self) -> None:
        """Run :meth:`health_check` every ``health_check_interval`` seconds."""
        while True:
            try:
                await self.health_check()
            except Exception:
                logger.exception("health_check iteration failed")
            await asyncio.sleep(self._health_check_interval)

    # ── Introspection ──

    async def get_pool_status(self) -> list[dict[str, object]]:
        """Return a snapshot of every key's state (for /health endpoint)."""
        async with self._lock:
            return [k.snapshot() for k in self._keys.values()]

    async def get_provider_status(self, provider: str) -> dict[str, int]:
        """Return ``{active, total, circuit_open}`` counts for *provider*."""
        async with self._lock:
            active = 0
            total = 0
            circuit = 0
            for k in self._keys.values():
                if k.provider != provider:
                    continue
                total += 1
                if k.status == KeyStatus.ACTIVE:
                    active += 1
                elif k.status == KeyStatus.CIRCUIT_OPEN:
                    circuit += 1
            return {"active": active, "total": total, "circuit_open": circuit}


async def _default_probe(_key_id: str) -> bool:
    """Default probe function — always returns ``True``.

    In production this is replaced with an actual HTTP probe (e.g.
    ``GET {base_url}/models`` with a 5-second timeout).
    """
    return True
