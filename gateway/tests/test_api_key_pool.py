"""Unit tests for :mod:`gateway.services.api_key_pool_manager`.

Covers the five test categories required by the task specification:

1. **Weighted round-robin algorithm** — verifies the
   ``effective_weight = base_weight × health_score × (1 − rpm_ratio)``
   formula and the resulting selection distribution.
2. **Health check** — verifies that non-active keys with expired
   cooldown / circuit windows are probed and recovered.
3. **Cooldown / circuit breaker / recovery** — verifies 429 → 60 s
   cooldown, 3× 5xx → 5 min circuit, and probe-based recovery.
4. **Concurrency safety** — verifies ``asyncio.Lock`` serialises
   mutations under concurrent ``select_key`` / ``record_failure`` calls.
5. **Boundary cases** — empty pool, single key, all keys unavailable.

The tests use injectable ``clock_fn`` and ``probe_fn`` for deterministic
behaviour — no real time or network calls are involved.
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter

import pytest

from gateway.services.api_key_pool_manager import (
    DELTA_5XX,
    DELTA_429,
    DELTA_PROBE_SUCCESS,
    DELTA_SUCCESS,
    HEALTH_SCORE_MAX,
    HEALTH_SCORE_MIN,
    STATUS_NETWORK_ERROR,
    STATUS_TIMEOUT,
    APIKeyPoolManager,
    KeyState,
    KeyStatus,
)

# ── Test helpers ────────────────────────────────────────────────────


class MockClock:
    """Deterministic clock for time-based tests.

    Calling the instance returns the current ``time`` value; tests can
    advance it via :meth:`advance`.
    """

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.time: float = start

    def __call__(self) -> float:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += seconds


class MockProbe:
    """Configurable async probe function.

    Records every call and returns the configured ``result``.  Per-key
    results can be set via :meth:`set_result`.
    """

    def __init__(self, default_result: bool = True) -> None:
        self._default: bool = default_result
        self._per_key: dict[str, bool] = {}
        self.calls: list[str] = []

    async def __call__(self, key_id: str) -> bool:
        self.calls.append(key_id)
        return self._per_key.get(key_id, self._default)

    def set_result(self, key_id: str, result: bool) -> None:
        self._per_key[key_id] = result

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _make_key(
    key_id: str = "k1",
    provider: str = "deepseek",
    *,
    base_weight: int = 100,
    health_score: float = 1.0,
    status: KeyStatus = KeyStatus.ACTIVE,
) -> KeyState:
    """Build a :class:`KeyState` with sensible defaults."""
    k = KeyState(
        key_id=key_id,
        provider=provider,
        base_weight=base_weight,
        health_score=health_score,
        status=status,
    )
    return k


# ── 1. Weighted round-robin algorithm tests ────────────────────────


class TestWeightedRoundRobin:
    """Tests for the weighted selection algorithm (§5.2)."""

    async def test_select_returns_active_key(self):
        """A single active key is always selected."""
        mgr = APIKeyPoolManager(keys=[_make_key("k1", "deepseek")])
        selected = await mgr.select_key("deepseek")
        assert selected is not None
        assert selected.key_id == "k1"

    async def test_select_filters_by_provider(self):
        """Only keys matching the requested provider are candidates."""
        keys = [
            _make_key("k1", "deepseek"),
            _make_key("k2", "openai"),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        for _ in range(20):
            selected = await mgr.select_key("deepseek")
            assert selected is not None
            assert selected.provider == "deepseek"

    async def test_higher_weight_selected_more_often(self):
        """A key with 3× the weight should be selected ~3× more often."""
        random.seed(42)
        keys = [
            _make_key("light", "ds", base_weight=10),
            _make_key("heavy", "ds", base_weight=90),
        ]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=10_000)
        counts: Counter[str] = Counter()
        n = 5_000
        for _ in range(n):
            sel = await mgr.select_key("ds")
            assert sel is not None
            counts[sel.key_id] += 1
            # Reset RPM so it doesn't affect weight
            sel._rpm_count = 0

        ratio = counts["heavy"] / counts["light"]
        # Expect ratio ≈ 9.0 (90/10).  Allow generous tolerance for RNG.
        assert 6.0 < ratio < 12.0, f"ratio {ratio:.2f} outside [6, 12]"

    async def test_lower_health_score_reduces_selection(self):
        """A key with health_score 0.5 should be selected half as often."""
        random.seed(123)
        keys = [
            _make_key("healthy", "ds", base_weight=100, health_score=1.0),
            _make_key("degraded", "ds", base_weight=100, health_score=0.5),
        ]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=10_000)
        counts: Counter[str] = Counter()
        n = 5_000
        for _ in range(n):
            sel = await mgr.select_key("ds")
            assert sel is not None
            counts[sel.key_id] += 1
            sel._rpm_count = 0  # reset RPM

        ratio = counts["healthy"] / counts["degraded"]
        # Expect ratio ≈ 2.0 (1.0/0.5).  Allow tolerance.
        assert 1.5 < ratio < 2.8, f"ratio {ratio:.2f} outside [1.5, 2.8]"

    async def test_rpm_ratio_reduces_weight(self):
        """As RPM approaches the limit, the key's effective weight drops."""
        random.seed(7)
        clock = MockClock(start=100.0)
        keys = [
            _make_key("k1", "ds", base_weight=100),
            _make_key("k2", "ds", base_weight=100),
        ]
        mgr = APIKeyPoolManager(keys=keys, clock_fn=clock, rpm_limit=10)
        # Exhaust k1's RPM — must set both count and minute to match clock.
        now_minute = int(clock()) // 60
        keys[0]._rpm_count = 10  # at limit
        keys[0]._rpm_minute = now_minute
        counts: Counter[str] = Counter()
        for _ in range(100):
            sel = await mgr.select_key("ds")
            assert sel is not None
            counts[sel.key_id] += 1
            if sel.key_id == "k2":
                sel._rpm_count = 0  # keep k2 available

        # k1 is at RPM limit → only k2 should be selected
        assert counts["k1"] == 0
        assert counts["k2"] == 100

    async def test_select_increments_rpm_and_stats(self):
        """select_key increments RPM, total_requests, and last_used_at."""
        clock = MockClock(start=100.0)
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key], clock_fn=clock)
        assert key.total_requests == 0
        assert key._rpm_count == 0

        await mgr.select_key("ds")
        assert key.total_requests == 1
        assert key._rpm_count == 1
        assert key.last_used_at == 100.0

        await mgr.select_key("ds")
        assert key.total_requests == 2
        assert key._rpm_count == 2

    async def test_rpm_resets_on_minute_rollover(self):
        """RPM counter resets when the minute changes."""
        clock = MockClock(start=60.0)  # minute 1
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key], clock_fn=clock, rpm_limit=100)

        await mgr.select_key("ds")
        assert key._rpm_count == 1
        assert key._rpm_minute == 1

        clock.advance(60.0)  # now minute 2
        await mgr.select_key("ds")
        assert key._rpm_count == 1  # reset
        assert key._rpm_minute == 2

    async def test_zero_health_falls_back_to_uniform(self):
        """When all weights are zero, uniform random is used (no deadlock)."""
        random.seed(99)
        keys = [
            _make_key("k1", "ds", health_score=0.0),
            _make_key("k2", "ds", health_score=0.0),
        ]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=10_000)
        # Should not raise / deadlock
        selected = await mgr.select_key("ds")
        assert selected is not None
        assert selected.key_id in {"k1", "k2"}


# ── 2. Health check tests ──────────────────────────────────────────


class TestHealthCheck:
    """Tests for the periodic health-check probing (§5.6)."""

    async def test_health_check_probes_expired_cooldown(self):
        """A RATE_LIMITED key past its cooldown is probed."""
        clock = MockClock(start=100.0)
        probe = MockProbe(default_result=True)
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 90.0  # expired
        mgr = APIKeyPoolManager(
            keys=[key], probe_fn=probe, clock_fn=clock, cooldown_duration=60.0
        )

        await mgr.health_check()
        assert probe.call_count == 1
        assert key.status == KeyStatus.ACTIVE
        assert key.cooldown_until is None

    async def test_health_check_probes_expired_circuit(self):
        """A CIRCUIT_OPEN key past its circuit window is probed."""
        clock = MockClock(start=200.0)
        probe = MockProbe(default_result=True)
        key = _make_key("k1", "ds", status=KeyStatus.CIRCUIT_OPEN)
        key.circuit_breaker_until = 150.0  # expired
        mgr = APIKeyPoolManager(
            keys=[key], probe_fn=probe, clock_fn=clock, circuit_duration=300.0
        )

        await mgr.health_check()
        assert probe.call_count == 1
        assert key.status == KeyStatus.ACTIVE
        assert key.circuit_breaker_until is None

    async def test_health_check_skips_active_keys(self):
        """ACTIVE keys are not probed."""
        probe = MockProbe()
        keys = [_make_key("k1", "ds", status=KeyStatus.ACTIVE)]
        mgr = APIKeyPoolManager(keys=keys, probe_fn=probe)
        await mgr.health_check()
        assert probe.call_count == 0

    async def test_health_check_skips_disabled_keys(self):
        """DISABLED keys are not probed."""
        probe = MockProbe()
        keys = [_make_key("k1", "ds", status=KeyStatus.DISABLED)]
        mgr = APIKeyPoolManager(keys=keys, probe_fn=probe)
        await mgr.health_check()
        assert probe.call_count == 0

    async def test_health_check_skips_unexpired_windows(self):
        """Keys still within cooldown / circuit window are not probed."""
        clock = MockClock(start=100.0)
        probe = MockProbe()
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 200.0  # not yet expired
        mgr = APIKeyPoolManager(keys=[key], probe_fn=probe, clock_fn=clock)

        await mgr.health_check()
        assert probe.call_count == 0
        assert key.status == KeyStatus.RATE_LIMITED

    async def test_health_check_skips_other_providers(self):
        """Only keys for the relevant providers are considered (all here)."""
        clock = MockClock(start=100.0)
        probe = MockProbe(default_result=True)
        keys = [
            _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED),
            _make_key("k2", "openai", status=KeyStatus.RATE_LIMITED),
        ]
        keys[0].cooldown_until = 50.0
        keys[1].cooldown_until = 50.0
        mgr = APIKeyPoolManager(keys=keys, probe_fn=probe, clock_fn=clock)

        await mgr.health_check()
        assert probe.call_count == 2  # both providers' keys probed


# ── 3. Cooldown / circuit breaker / recovery tests ─────────────────


class TestCooldownCircuitRecovery:
    """Tests for 429 cooldown, 5xx circuit breaker, and recovery (§5.4–§5.6)."""

    async def test_429_triggers_cooldown(self):
        """A 429 response sets RATE_LIMITED and cooldown_until."""
        clock = MockClock(start=100.0)
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(
            keys=[key], clock_fn=clock, cooldown_duration=60.0
        )

        await mgr.record_failure("k1", 429)
        assert key.status == KeyStatus.RATE_LIMITED
        assert key.cooldown_until == 160.0  # 100 + 60
        assert key.health_score == 1.0 + DELTA_429  # 0.80

    async def test_429_makes_key_unavailable(self):
        """After a 429 the key is not selectable until cooldown expires."""
        clock = MockClock(start=100.0)
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(
            keys=[key], clock_fn=clock, cooldown_duration=60.0
        )

        await mgr.record_failure("k1", 429)
        assert await mgr.select_key("ds") is None  # in cooldown

        clock.advance(61.0)  # cooldown expired
        # But status is still RATE_LIMITED — need health_check to recover
        probe = MockProbe(default_result=True)
        mgr._probe_fn = probe
        await mgr.health_check()
        assert key.status == KeyStatus.ACTIVE
        sel = await mgr.select_key("ds")
        assert sel is not None

    async def test_5xx_increments_consecutive_failures(self):
        """Each 5xx increments consecutive_failures and reduces health."""
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_failure("k1", 500)
        assert key.consecutive_failures == 1
        assert key.health_score == pytest.approx(1.0 + DELTA_5XX)  # 0.70

        await mgr.record_failure("k1", 502)
        assert key.consecutive_failures == 2
        assert key.health_score == pytest.approx(1.0 + 2 * DELTA_5XX)  # 0.40

    async def test_three_consecutive_5xx_opens_circuit(self):
        """3 consecutive 5xx → CIRCUIT_OPEN for circuit_duration seconds."""
        clock = MockClock(start=100.0)
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(
            keys=[key],
            clock_fn=clock,
            circuit_duration=300.0,
            circuit_threshold=3,
        )

        await mgr.record_failure("k1", 500)
        await mgr.record_failure("k1", 500)
        assert key.status == KeyStatus.ACTIVE  # not yet

        await mgr.record_failure("k1", 500)
        assert key.status == KeyStatus.CIRCUIT_OPEN
        assert key.circuit_breaker_until == 400.0  # 100 + 300
        assert key.consecutive_failures == 3

    async def test_success_resets_consecutive_failures(self):
        """A successful request resets the consecutive failure counter."""
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_failure("k1", 500)
        await mgr.record_failure("k1", 500)
        assert key.consecutive_failures == 2

        await mgr.record_success("k1")
        assert key.consecutive_failures == 0
        # After 2× 5xx (health=0.40) + 1 success (+0.05) → 0.45
        assert key.health_score == pytest.approx(0.45)

    async def test_success_increases_health_score(self):
        """record_success adds DELTA_SUCCESS (capped at 1.0)."""
        key = _make_key("k1", "ds", health_score=0.50)
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_success("k1")
        assert key.health_score == pytest.approx(0.50 + DELTA_SUCCESS)

    async def test_health_score_capped_at_max(self):
        """Health score cannot exceed HEALTH_SCORE_MAX (1.0)."""
        key = _make_key("k1", "ds", health_score=0.99)
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_success("k1")
        assert key.health_score == HEALTH_SCORE_MAX

    async def test_health_score_floored_at_min(self):
        """Health score cannot drop below HEALTH_SCORE_MIN (0.0)."""
        key = _make_key("k1", "ds", health_score=0.05)
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_failure("k1", 500)  # -0.30
        assert key.health_score == HEALTH_SCORE_MIN

    async def test_timeout_reduces_health(self):
        """STATUS_TIMEOUT reduces health by DELTA_TIMEOUT (-0.25)."""
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_failure("k1", STATUS_TIMEOUT)
        assert key.health_score == 1.0 + (-0.25)
        assert key.consecutive_failures == 0  # timeout doesn't increment

    async def test_network_error_reduces_health(self):
        """STATUS_NETWORK_ERROR reduces health by DELTA_NETWORK (-0.20)."""
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_failure("k1", STATUS_NETWORK_ERROR)
        assert key.health_score == 1.0 + (-0.20)
        assert key.consecutive_failures == 0

    async def test_recover_key_success(self):
        """recover_key with a successful probe restores ACTIVE status."""
        clock = MockClock(start=100.0)
        probe = MockProbe(default_result=True)
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 50.0  # expired
        key.health_score = 0.50
        mgr = APIKeyPoolManager(
            keys=[key], probe_fn=probe, clock_fn=clock
        )

        result = await mgr.recover_key("k1")
        assert result is True
        assert key.status == KeyStatus.ACTIVE
        assert key.consecutive_failures == 0
        assert key.health_score == pytest.approx(0.50 + DELTA_PROBE_SUCCESS)
        assert key.cooldown_until is None

    async def test_recover_key_probe_failure_extends_penalty(self):
        """recover_key with a failed probe extends the cooldown window."""
        clock = MockClock(start=100.0)
        probe = MockProbe(default_result=False)
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 50.0  # expired
        mgr = APIKeyPoolManager(
            keys=[key], probe_fn=probe, clock_fn=clock, cooldown_duration=60.0
        )

        result = await mgr.recover_key("k1")
        assert result is False
        assert key.status == KeyStatus.RATE_LIMITED
        assert key.cooldown_until == 160.0  # 100 + 60 (extended)

    async def test_recover_key_window_not_expired(self):
        """recover_key returns False if the window hasn't expired."""
        clock = MockClock(start=100.0)
        probe = MockProbe()
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 200.0  # not yet expired
        mgr = APIKeyPoolManager(keys=[key], probe_fn=probe, clock_fn=clock)

        result = await mgr.recover_key("k1")
        assert result is False
        assert probe.call_count == 0  # not probed

    async def test_recover_nonexistent_key(self):
        """recover_key on an unknown key_id returns False."""
        mgr = APIKeyPoolManager(keys=[])
        result = await mgr.recover_key("nonexistent")
        assert result is False

    async def test_record_success_clears_cooldown(self):
        """record_success on a RATE_LIMITED key clears cooldown."""
        key = _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED)
        key.cooldown_until = 200.0
        mgr = APIKeyPoolManager(keys=[key])

        await mgr.record_success("k1")
        assert key.status == KeyStatus.ACTIVE
        assert key.cooldown_until is None
        assert key.circuit_breaker_until is None

    async def test_record_failure_unknown_key(self):
        """record_failure on an unknown key_id is a no-op (no crash)."""
        mgr = APIKeyPoolManager(keys=[])
        # Should not raise
        await mgr.record_failure("unknown", 500)

    async def test_record_success_unknown_key(self):
        """record_success on an unknown key_id is a no-op (no crash)."""
        mgr = APIKeyPoolManager(keys=[])
        # Should not raise
        await mgr.record_success("unknown")


# ── 4. Concurrency safety tests ────────────────────────────────────


class TestConcurrencySafety:
    """Tests for asyncio.Lock serialisation under concurrent access."""

    async def test_concurrent_select_does_not_corrupt_rpm(self):
        """Concurrent select_key calls must not lose RPM increments."""
        random.seed(42)
        keys = [_make_key("k1", "ds")]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=10_000)

        n = 200
        await asyncio.gather(*[mgr.select_key("ds") for _ in range(n)])
        assert keys[0].total_requests == n
        assert keys[0]._rpm_count == n

    async def test_concurrent_select_multiple_keys(self):
        """Concurrent selects across multiple keys distribute correctly."""
        random.seed(42)
        keys = [
            _make_key("k1", "ds"),
            _make_key("k2", "ds"),
            _make_key("k3", "ds"),
        ]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=10_000)

        n = 600
        await asyncio.gather(*[mgr.select_key("ds") for _ in range(n)])
        total = sum(k.total_requests for k in keys)
        assert total == n
        # Each key should get roughly 1/3 of requests
        for k in keys:
            assert 150 < k.total_requests < 450, (
                f"key {k.key_id} got {k.total_requests} requests"
            )

    async def test_concurrent_record_success_and_failure(self):
        """Concurrent record_success / record_failure don't corrupt state."""
        key = _make_key("k1", "ds")
        mgr = APIKeyPoolManager(keys=[key])

        async def succeed():
            await mgr.record_success("k1")

        async def fail():
            await mgr.record_failure("k1", 500)

        # Mix successes and failures concurrently
        tasks = []
        for _ in range(100):
            tasks.append(succeed())
            tasks.append(fail())
        await asyncio.gather(*tasks)

        # State should be internally consistent
        assert key.success_requests + key.failed_requests == 200
        assert 0.0 <= key.health_score <= 1.0

    async def test_concurrent_select_with_rpm_limit(self):
        """Concurrent selects respect RPM limit without overshooting."""
        random.seed(42)
        keys = [_make_key("k1", "ds")]
        mgr = APIKeyPoolManager(keys=keys, rpm_limit=50)

        n = 100
        results = await asyncio.gather(*[mgr.select_key("ds") for _ in range(n)])
        selected = [r for r in results if r is not None]
        # RPM limit is 50, so at most 50 should succeed
        assert len(selected) <= 50
        assert keys[0]._rpm_count <= 50


# ── 5. Boundary case tests ─────────────────────────────────────────


class TestBoundaryCases:
    """Tests for edge cases: empty pool, single key, all unavailable."""

    async def test_empty_pool_returns_none(self):
        """select_key on an empty pool returns None."""
        mgr = APIKeyPoolManager(keys=[])
        assert await mgr.select_key("ds") is None

    async def test_empty_pool_unknown_provider(self):
        """select_key for a provider with no keys returns None."""
        mgr = APIKeyPoolManager(keys=[_make_key("k1", "openai")])
        assert await mgr.select_key("deepseek") is None

    async def test_single_key_always_selected(self):
        """A single active key is selected every time."""
        mgr = APIKeyPoolManager(keys=[_make_key("k1", "ds")], rpm_limit=10_000)
        for _ in range(50):
            sel = await mgr.select_key("ds")
            assert sel is not None
            assert sel.key_id == "k1"

    async def test_all_keys_rate_limited(self):
        """When all keys are RATE_LIMITED, select_key returns None."""
        keys = [
            _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED),
            _make_key("k2", "ds", status=KeyStatus.RATE_LIMITED),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        assert await mgr.select_key("ds") is None

    async def test_all_keys_circuit_open(self):
        """When all keys are CIRCUIT_OPEN, select_key returns None."""
        keys = [
            _make_key("k1", "ds", status=KeyStatus.CIRCUIT_OPEN),
            _make_key("k2", "ds", status=KeyStatus.CIRCUIT_OPEN),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        assert await mgr.select_key("ds") is None

    async def test_all_keys_disabled(self):
        """When all keys are DISABLED, select_key returns None."""
        keys = [
            _make_key("k1", "ds", status=KeyStatus.DISABLED),
            _make_key("k2", "ds", status=KeyStatus.DISABLED),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        assert await mgr.select_key("ds") is None

    async def test_all_keys_at_rpm_limit(self):
        """When all keys are at RPM limit, select_key returns None."""
        clock = MockClock(start=100.0)
        keys = [_make_key("k1", "ds")]
        # Set RPM to match the clock's current minute.
        now_minute = int(clock()) // 60
        keys[0]._rpm_count = 60
        keys[0]._rpm_minute = now_minute
        mgr = APIKeyPoolManager(keys=keys, clock_fn=clock, rpm_limit=60)
        assert await mgr.select_key("ds") is None

    async def test_one_available_one_unavailable(self):
        """Mix of available and unavailable keys: only available is selected."""
        clock = MockClock(start=100.0)
        keys = [
            _make_key("k1", "ds", status=KeyStatus.RATE_LIMITED),
            _make_key("k2", "ds", status=KeyStatus.ACTIVE),
        ]
        keys[0].cooldown_until = 200.0
        mgr = APIKeyPoolManager(keys=keys, clock_fn=clock, rpm_limit=10_000)

        for _ in range(20):
            sel = await mgr.select_key("ds")
            assert sel is not None
            assert sel.key_id == "k2"

    async def test_get_pool_status(self):
        """get_pool_status returns a snapshot of all keys."""
        keys = [
            _make_key("k1", "ds"),
            _make_key("k2", "openai", health_score=0.5),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        status = await mgr.get_pool_status()
        assert len(status) == 2
        ids = {s["key_id"] for s in status}
        assert ids == {"k1", "k2"}

    async def test_get_provider_status(self):
        """get_provider_status returns active/total/circuit_open counts."""
        keys = [
            _make_key("k1", "ds"),
            _make_key("k2", "ds", status=KeyStatus.CIRCUIT_OPEN),
            _make_key("k3", "openai"),
        ]
        mgr = APIKeyPoolManager(keys=keys)
        ds_status = await mgr.get_provider_status("ds")
        assert ds_status == {"active": 1, "total": 2, "circuit_open": 1}

        openai_status = await mgr.get_provider_status("openai")
        assert openai_status == {"active": 1, "total": 1, "circuit_open": 0}

    async def test_add_and_remove_key(self):
        """add_key / remove_key manage the pool correctly."""
        mgr = APIKeyPoolManager(keys=[])
        assert await mgr.select_key("ds") is None

        mgr.add_key(_make_key("k1", "ds"))
        sel = await mgr.select_key("ds")
        assert sel is not None
        assert sel.key_id == "k1"

        removed = mgr.remove_key("k1")
        assert removed is not None
        assert removed.key_id == "k1"
        assert await mgr.select_key("ds") is None

    async def test_remove_nonexistent_key(self):
        """remove_key on an unknown key returns None."""
        mgr = APIKeyPoolManager(keys=[])
        assert mgr.remove_key("nope") is None

    async def test_snapshot_contains_all_fields(self):
        """KeyState.snapshot() returns all expected fields."""
        key = _make_key("k1", "ds", health_score=0.75)
        mgr = APIKeyPoolManager(keys=[key])
        status = await mgr.get_pool_status()
        snap = status[0]
        expected_keys = {
            "key_id", "provider", "base_weight", "health_score",
            "status", "consecutive_failures", "cooldown_until",
            "circuit_breaker_until", "last_used_at", "rpm",
            "total_requests", "success_requests", "failed_requests",
        }
        assert expected_keys.issubset(snap.keys())
        assert snap["health_score"] == 0.75
        assert snap["status"] == "active"


# ── Background loop tests ──────────────────────────────────────────


class TestBackgroundLoop:
    """Tests for the periodic health-check background task."""

    async def test_start_and_stop_loop(self):
        """start_health_check_loop creates a task; stop cancels it."""
        mgr = APIKeyPoolManager(keys=[], health_check_interval=0.01)
        assert mgr._health_check_task is None

        await mgr.start_health_check_loop()
        assert mgr._health_check_task is not None
        assert not mgr._health_check_task.done()

        await mgr.stop_health_check_loop()
        assert mgr._health_check_task is None

    async def test_start_loop_idempotent(self):
        """Calling start twice does not create a second task."""
        mgr = APIKeyPoolManager(keys=[], health_check_interval=0.01)
        await mgr.start_health_check_loop()
        task1 = mgr._health_check_task
        await mgr.start_health_check_loop()
        assert mgr._health_check_task is task1
        await mgr.stop_health_check_loop()

    async def test_stop_loop_without_start(self):
        """stop_health_check_loop is safe to call when no task is running."""
        mgr = APIKeyPoolManager(keys=[])
        await mgr.stop_health_check_loop()  # should not raise
