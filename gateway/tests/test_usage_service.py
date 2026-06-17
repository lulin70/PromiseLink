"""Unit tests for :mod:`gateway.services.usage_service`.

Covers the test cases from the Phase 0 test plan §2.3:

* Quota check three-state (UT-BIL-001 … UT-BIL-012)
* Usage recording (UT-BIL-020 … UT-BIL-030)
* Monthly reset (UT-BIL-040 … UT-BIL-045)
* Traffic-light transitions (UT-BIL-050 … UT-BIL-056)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from gateway.core.exceptions import (
    ASRQuotaExceeded,
    OCRQuotaExceeded,
    QuotaExceeded,
    TTSQuotaExceeded,
)
from gateway.models.tables import License, MonthlyUsage, UsageRecord
from gateway.services.usage_service import (
    UsageService,
    _compute_traffic_light,
    _current_year_month,
)
from gateway.tests.conftest import make_user_id

# ── Helpers ──────────────────────────────────────────────────────────


def _make_service(db_session, redis_client) -> UsageService:
    """Build a UsageService with the standard test dependencies."""
    return UsageService(db_session=db_session, redis_client=redis_client)


async def _set_quota(
    db_session,
    license_row: License,
    *,
    used_tokens: int = 0,
    used_asr: int = 0,
    used_tts: int = 0,
    used_ocr: int = 0,
    limit_tokens: int = 500000,
    limit_asr: int = 200,
    limit_tts: int = 200,
    limit_ocr: int = 100,
) -> License:
    """Set quota values on a license and commit."""
    license_row.quota_used_tokens = used_tokens
    license_row.quota_used_asr = used_asr
    license_row.quota_used_tts = used_tts
    license_row.quota_used_ocr = used_ocr
    license_row.quota_limit_tokens = limit_tokens
    license_row.quota_limit_asr = limit_asr
    license_row.quota_limit_tts = limit_tts
    license_row.quota_limit_ocr = limit_ocr
    license_row.user_id = license_row.user_id or make_user_id("quota")
    await db_session.commit()
    await db_session.refresh(license_row)
    return license_row


# ── Traffic-light computation unit tests (UT-BIL-005 … UT-BIL-008) ──


def test_traffic_light_green():
    """UT-BIL-001 / UT-BIL-005: < 80% → green."""
    assert _compute_traffic_light(0, 500000) == "green"
    assert _compute_traffic_light(399949, 500000) == "green"  # 79.99%


def test_traffic_light_yellow():
    """UT-BIL-002 / UT-BIL-006 / UT-BIL-007: 80-100% → yellow."""
    assert _compute_traffic_light(400000, 500000) == "yellow"  # 80.00%
    assert _compute_traffic_light(499949, 500000) == "yellow"  # 99.99%


def test_traffic_light_red():
    """UT-BIL-003 / UT-BIL-004 / UT-BIL-008: ≥ 100% → red."""
    assert _compute_traffic_light(500000, 500000) == "red"  # 100.00%
    assert _compute_traffic_light(550000, 500000) == "red"  # 110%


def test_traffic_light_zero_limit():
    """Edge case: limit=0 → red (no quota available)."""
    assert _compute_traffic_light(0, 0) == "red"


# ── Quota check tests (UT-BIL-001 … UT-BIL-012) ─────────────────────


@pytest.mark.asyncio
async def test_check_quota_green(
    db_session, redis_client, active_license
):
    """UT-BIL-001: 25% usage → green, request allowed."""
    await _set_quota(db_session, active_license, used_tokens=125000)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id, request_type="llm")
    assert status.traffic_light == "green"
    assert status.token_used == 125000
    assert status.token_limit == 500000
    assert status.token_percentage == 25.0
    assert not status.is_red


@pytest.mark.asyncio
async def test_check_quota_yellow(
    db_session, redis_client, active_license
):
    """UT-BIL-002 / UT-BIL-006: 80% usage → yellow, request allowed."""
    await _set_quota(db_session, active_license, used_tokens=400000)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id, request_type="llm")
    assert status.traffic_light == "yellow"
    assert status.token_percentage == 80.0
    assert not status.is_red


@pytest.mark.asyncio
async def test_check_quota_red_rejects_llm(
    db_session, redis_client, active_license
):
    """UT-BIL-003 / UT-BIL-054: 100% usage → red, LLM rejected with 402."""
    await _set_quota(db_session, active_license, used_tokens=500000)
    service = _make_service(db_session, redis_client)

    with pytest.raises(QuotaExceeded) as exc_info:
        await service.check_quota(active_license.user_id, request_type="llm")
    assert exc_info.value.details["used"] == 500000
    assert exc_info.value.details["limit"] == 500000


@pytest.mark.asyncio
async def test_check_quota_over_100_percent(
    db_session, redis_client, active_license
):
    """UT-BIL-004: > 100% usage → red, rejected."""
    await _set_quota(db_session, active_license, used_tokens=550000)
    service = _make_service(db_session, redis_client)

    with pytest.raises(QuotaExceeded):
        await service.check_quota(active_license.user_id, request_type="llm")


@pytest.mark.asyncio
async def test_check_quota_boundary_79_percent(
    db_session, redis_client, active_license
):
    """UT-BIL-005: 79.99% → green (boundary)."""
    await _set_quota(db_session, active_license, used_tokens=399949)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "green"


@pytest.mark.asyncio
async def test_check_quota_boundary_80_percent(
    db_session, redis_client, active_license
):
    """UT-BIL-006: 80.00% → yellow (boundary)."""
    await _set_quota(db_session, active_license, used_tokens=400000)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "yellow"


@pytest.mark.asyncio
async def test_check_quota_boundary_99_percent(
    db_session, redis_client, active_license
):
    """UT-BIL-007: 99.99% → yellow (boundary)."""
    await _set_quota(db_session, active_license, used_tokens=499949)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "yellow"


@pytest.mark.asyncio
async def test_check_quota_boundary_100_percent(
    db_session, redis_client, active_license
):
    """UT-BIL-008: 100.00% → red (boundary)."""
    await _set_quota(db_session, active_license, used_tokens=500000)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "red"


@pytest.mark.asyncio
async def test_check_quota_asr_exceeded(
    db_session, redis_client, active_license
):
    """UT-BIL-009: ASR quota exhausted → ASRQuotaExceeded."""
    await _set_quota(db_session, active_license, used_asr=200, limit_asr=200)
    service = _make_service(db_session, redis_client)

    with pytest.raises(ASRQuotaExceeded):
        await service.check_quota(active_license.user_id, request_type="asr")


@pytest.mark.asyncio
async def test_check_quota_tts_exceeded(
    db_session, redis_client, active_license
):
    """UT-BIL-010: TTS quota exhausted → TTSQuotaExceeded."""
    await _set_quota(db_session, active_license, used_tts=200, limit_tts=200)
    service = _make_service(db_session, redis_client)

    with pytest.raises(TTSQuotaExceeded):
        await service.check_quota(active_license.user_id, request_type="tts")


@pytest.mark.asyncio
async def test_check_quota_ocr_exceeded(
    db_session, redis_client, active_license
):
    """UT-BIL-011: OCR quota exhausted → OCRQuotaExceeded."""
    await _set_quota(db_session, active_license, used_ocr=100, limit_ocr=100)
    service = _make_service(db_session, redis_client)

    with pytest.raises(OCRQuotaExceeded):
        await service.check_quota(active_license.user_id, request_type="ocr")


@pytest.mark.asyncio
async def test_llm_exceeded_does_not_block_asr(
    db_session, redis_client, active_license
):
    """UT-BIL-012: LLM red state does not block ASR (independent quotas)."""
    await _set_quota(
        db_session, active_license,
        used_tokens=500000,  # LLM exhausted
        used_asr=10,  # ASR still available
    )
    service = _make_service(db_session, redis_client)

    # LLM should be rejected
    with pytest.raises(QuotaExceeded):
        await service.check_quota(active_license.user_id, request_type="llm")

    # ASR should be allowed
    status = await service.check_quota(active_license.user_id, request_type="asr")
    assert status.traffic_light == "red"  # token-based light is red
    # But ASR-specific check passes (no exception raised)


# ── Usage recording tests (UT-BIL-020 … UT-BIL-030) ─────────────────


@pytest.mark.asyncio
async def test_record_llm_usage(
    db_session, redis_client, active_license
):
    """UT-BIL-020 / UT-BIL-021 / UT-BIL-022: record LLM usage."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=150,
        tokens_out=80,
        latency_ms=850,
        status=200,
    )

    # Verify usage_records
    result = await db_session.execute(select(UsageRecord))
    records = result.scalars().all()
    assert len(records) == 1
    rec = records[0]
    assert rec.request_type == "llm"
    assert rec.input_tokens == 150
    assert rec.output_tokens == 80
    assert rec.total_tokens == 230
    assert rec.success is True

    # Verify license quota updated
    await db_session.refresh(active_license)
    assert active_license.quota_used_tokens == 230

    # Verify monthly_usage updated
    monthly_result = await db_session.execute(select(MonthlyUsage))
    monthlies = monthly_result.scalars().all()
    assert len(monthlies) == 1
    assert monthlies[0].total_tokens == 230
    assert monthlies[0].request_count == 1


@pytest.mark.asyncio
async def test_record_usage_cost_deepseek(
    db_session, redis_client, active_license
):
    """UT-BIL-024: DeepSeek cost = 230 × 0.001/1000 = 0.00023."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=150,
        tokens_out=80,
        status=200,
    )

    result = await db_session.execute(select(UsageRecord))
    rec = result.scalar_one()
    assert rec.cost_cny == Decimal("0.000230")


@pytest.mark.asyncio
async def test_record_usage_cost_moka(
    db_session, redis_client, active_license
):
    """UT-BIL-025: Moka AI cost = 230 × 0.002/1000 = 0.00046."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="moka_ai",
        model="moka-chat",
        request_type="llm",
        tokens_in=150,
        tokens_out=80,
        status=200,
    )

    result = await db_session.execute(select(UsageRecord))
    rec = result.scalar_one()
    assert rec.cost_cny == Decimal("0.000460")


@pytest.mark.asyncio
async def test_record_asr_usage(
    db_session, redis_client, active_license
):
    """UT-BIL-027: recording ASR increments asr counter."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="moka_ai",
        model="whisper-1",
        request_type="asr",
        status=200,
    )

    await db_session.refresh(active_license)
    assert active_license.quota_used_asr == 1
    assert active_license.quota_used_tokens == 0  # ASR doesn't consume tokens

    result = await db_session.execute(select(MonthlyUsage))
    monthly = result.scalar_one()
    assert monthly.asr_count == 1


@pytest.mark.asyncio
async def test_record_tts_usage(
    db_session, redis_client, active_license
):
    """UT-BIL-028: recording TTS increments tts counter."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="moka_ai",
        model="moka-tts",
        request_type="tts",
        status=200,
    )

    await db_session.refresh(active_license)
    assert active_license.quota_used_tts == 1


@pytest.mark.asyncio
async def test_record_ocr_usage(
    db_session, redis_client, active_license
):
    """UT-BIL-029: recording OCR increments ocr counter."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="moka_ai",
        model="moka-vision",
        request_type="ocr",
        status=200,
    )

    await db_session.refresh(active_license)
    assert active_license.quota_used_ocr == 1


@pytest.mark.asyncio
async def test_record_failed_request_no_quota(
    db_session, redis_client, active_license
):
    """UT-BIL-030: failed request (5xx) does not consume quota."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=150,
        tokens_out=80,
        status=500,
    )

    await db_session.refresh(active_license)
    assert active_license.quota_used_tokens == 0  # quota not consumed

    # But the usage record is still written
    result = await db_session.execute(select(UsageRecord))
    rec = result.scalar_one()
    assert rec.success is False
    assert rec.status_code == 500


@pytest.mark.asyncio
async def test_record_usage_updates_redis_cache(
    db_session, redis_client, active_license
):
    """UT-BIL-023: Redis quota cache is updated."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=100,
        tokens_out=50,
        status=200,
    )

    cache_key = f"quota:cache:{active_license.user_id}:{_current_year_month()}"
    cached = await redis_client.hget(cache_key, "tokens_used")
    assert cached is not None
    assert int(cached) == 150


# ── Monthly reset tests (UT-BIL-040 … UT-BIL-045) ───────────────────


@pytest.mark.asyncio
async def test_monthly_reset_zeros_counters(
    db_session, redis_client, active_license
):
    """UT-BIL-040: monthly reset zeros out quota_used_*."""
    await _set_quota(
        db_session, active_license,
        used_tokens=420000, used_asr=45, used_tts=12, used_ocr=3,
    )
    service = _make_service(db_session, redis_client)

    reset_count = await service.reset_monthly_quota()
    assert reset_count == 1

    await db_session.refresh(active_license)
    assert active_license.quota_used_tokens == 0
    assert active_license.quota_used_asr == 0
    assert active_license.quota_used_tts == 0
    assert active_license.quota_used_ocr == 0


@pytest.mark.asyncio
async def test_monthly_reset_archives_previous_month(
    db_session, redis_client, active_license
):
    """UT-BIL-041: monthly reset archives usage into monthly_usage."""
    await _set_quota(
        db_session, active_license,
        used_tokens=420000, used_asr=45, used_tts=12, used_ocr=3,
    )
    service = _make_service(db_session, redis_client)

    now = datetime.now(timezone.utc)
    await service.reset_monthly_quota(now=now)

    # Compute expected previous month
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    result = await db_session.execute(
        select(MonthlyUsage).where(MonthlyUsage.user_id == active_license.user_id)
    )
    monthlies = result.scalars().all()
    assert len(monthlies) == 1
    assert monthlies[0].year_month == prev_month
    assert monthlies[0].total_tokens == 420000
    assert monthlies[0].asr_count == 45
    assert monthlies[0].tts_count == 12
    assert monthlies[0].ocr_count == 3


@pytest.mark.asyncio
async def test_monthly_reset_preserves_history(
    db_session, redis_client, active_license
):
    """UT-BIL-044: reset does not delete usage_records history."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=100,
        tokens_out=50,
        status=200,
    )

    await service.reset_monthly_quota()

    result = await db_session.execute(select(UsageRecord))
    records = result.scalars().all()
    assert len(records) == 1  # history preserved


@pytest.mark.asyncio
async def test_monthly_reset_idempotent(
    db_session, redis_client, active_license
):
    """UT-BIL-045: running reset twice does not double-archive."""
    await _set_quota(db_session, active_license, used_tokens=100000)
    service = _make_service(db_session, redis_client)

    await service.reset_monthly_quota()
    await service.reset_monthly_quota()  # second run

    result = await db_session.execute(select(MonthlyUsage))
    monthlies = result.scalars().all()
    assert len(monthlies) == 1  # only one archive row


@pytest.mark.asyncio
async def test_monthly_reset_clears_redis_cache(
    db_session, redis_client, active_license
):
    """UT-BIL-042: reset clears the Redis quota cache for the previous month."""
    await _set_quota(db_session, active_license, used_tokens=100000)
    service = _make_service(db_session, redis_client)

    # Populate cache
    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=100,
        tokens_out=50,
        status=200,
    )

    now = datetime.now(timezone.utc)
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    cache_key = f"quota:cache:{active_license.user_id}:{prev_month}"
    # The cache key uses current month, not previous — set one manually for prev month
    await redis_client.hset(cache_key, "tokens_used", "100000")

    await service.reset_monthly_quota(now=now)

    exists = await redis_client.exists(cache_key)
    assert not exists  # cache cleared


# ── Traffic-light transition tests (UT-BIL-050 … UT-BIL-056) ────────


@pytest.mark.asyncio
async def test_green_to_yellow_transition(
    db_session, redis_client, active_license
):
    """UT-BIL-050: usage crossing 80% → green to yellow."""
    await _set_quota(db_session, active_license, used_tokens=390000)
    service = _make_service(db_session, redis_client)

    # Initially green
    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "green"

    # Record usage that pushes past 80%
    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=0,
        tokens_out=20000,  # 390000 + 20000 = 410000 = 82%
        status=200,
    )

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "yellow"


@pytest.mark.asyncio
async def test_yellow_to_red_transition(
    db_session, redis_client, active_license
):
    """UT-BIL-051: usage crossing 100% → yellow to red."""
    await _set_quota(db_session, active_license, used_tokens=490000)
    service = _make_service(db_session, redis_client)

    # Initially yellow
    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "yellow"

    # Record usage that pushes past 100%
    await service.record_usage(
        user_id=active_license.user_id,
        provider="deepseek",
        model="deepseek-chat",
        request_type="llm",
        tokens_in=0,
        tokens_out=20000,  # 490000 + 20000 = 510000 = 102%
        status=200,
    )

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "red"


@pytest.mark.asyncio
async def test_reset_restores_green(
    db_session, redis_client, active_license
):
    """UT-BIL-056: after monthly reset, traffic light returns to green."""
    await _set_quota(db_session, active_license, used_tokens=500000)
    service = _make_service(db_session, redis_client)

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "red"

    await service.reset_monthly_quota()

    status = await service.check_quota(active_license.user_id)
    assert status.traffic_light == "green"


# ── Usage query tests (tech design §4.3.3) ──────────────────────────


@pytest.mark.asyncio
async def test_get_usage_current_month(
    db_session, redis_client, active_license
):
    """get_usage returns current month usage from license counters."""
    await _set_quota(
        db_session, active_license,
        used_tokens=125000, used_asr=45, used_tts=38, used_ocr=12,
    )
    service = _make_service(db_session, redis_client)

    info = await service.get_usage(active_license.user_id)
    assert info.month == _current_year_month()
    assert info.traffic_light == "green"
    assert info.token_used == 125000
    assert info.token_limit == 500000
    assert info.asr_used == 45
    assert info.tts_used == 38
    assert info.ocr_used == 12


@pytest.mark.asyncio
async def test_get_usage_past_month(
    db_session, redis_client, active_license
):
    """get_usage for a past month reads from monthly_usage."""
    await _set_quota(db_session, active_license)
    service = _make_service(db_session, redis_client)

    # Insert a monthly_usage row for a past month
    past_month = MonthlyUsage(
        user_id=active_license.user_id,
        license_key=active_license.license_key,
        year_month="2026-05",
        total_tokens=420000,
        total_cost_cny=Decimal("0.42"),
        request_count=380,
        asr_count=45,
        tts_count=12,
        ocr_count=3,
        status="yellow",
    )
    db_session.add(past_month)
    await db_session.commit()

    info = await service.get_usage(active_license.user_id, month="2026-05")
    assert info.month == "2026-05"
    assert info.traffic_light == "yellow"
    assert info.token_used == 420000
    assert info.request_count == 380


@pytest.mark.asyncio
async def test_get_usage_no_license(db_session, redis_client):
    """get_usage for a user with no license → red state."""
    service = _make_service(db_session, redis_client)
    info = await service.get_usage("nonexistent_user")
    assert info.traffic_light == "red"
    assert info.token_used == 0
    assert info.token_limit == 0
