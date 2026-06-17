"""Usage billing service for the PromiseLink gateway.

Records AI usage, manages monthly quotas, and computes traffic-light
status (green / yellow / red).

Reference: Pro_Edition_Tech_Design_Phase0.md §7

Key design decisions:

* **Traffic-light thresholds**: green < 80%, yellow 80-100%, red ≥ 100%.
* **Independent media quotas**: ASR/TTS/OCR have separate counters; an
  exhausted LLM token quota does not block ASR/TTS/OCR calls.
* **Fire-and-forget recording**: ``record_usage`` writes to the DB
  synchronously within the call (the tests rely on immediate
  visibility), but the Redis cache update is non-blocking.
* **Monthly reset**: archives the current month's usage into
  ``monthly_usage``, zeros the license counters, and clears the Redis
  cache.  Idempotent — running twice in the same month does not create
  duplicate archive rows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as redis_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.exceptions import (
    ASRQuotaExceeded,
    LicenseNotFound,
    OCRQuotaExceeded,
    QuotaExceeded,
    TTSQuotaExceeded,
)
from gateway.models.tables import License, MonthlyUsage, UsageRecord

logger = logging.getLogger("gateway.usage_service")

# ── Constants (tech design §7.2) ────────────────────────────────────

YELLOW_THRESHOLD = 0.80  # 80% → yellow
RED_THRESHOLD = 1.00  # 100% → red

_QUOTA_CACHE_PREFIX = "quota:cache:"  # Redis hash key prefix

# Provider pricing (CNY per 1K tokens).  Reference: config.py §LLM Providers.
_PROVIDER_PRICING: dict[str, Decimal] = {
    "deepseek": Decimal("0.001"),
    "moka_ai": Decimal("0.002"),
    "openai": Decimal("0.001"),
}


# ── Helper functions ────────────────────────────────────────────────


def _current_year_month(now: datetime | None = None) -> str:
    """Return the current year-month string in ``YYYY-MM`` format.

    Args:
        now: Optional reference datetime (defaults to current UTC).

    Returns:
        Year-month string, e.g. ``"2026-06"``.
    """
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


def _previous_year_month(now: datetime | None = None) -> str:
    """Return the previous year-month string in ``YYYY-MM`` format.

    Args:
        now: Optional reference datetime (defaults to current UTC).

    Returns:
        Previous year-month string, e.g. ``"2026-05"`` for June input.
    """
    dt = now or datetime.now(timezone.utc)
    if dt.month == 1:
        return f"{dt.year - 1}-12"
    return f"{dt.year}-{dt.month - 1:02d}"


def _compute_traffic_light(used: int, limit: int) -> str:
    """Compute the traffic-light colour from usage and limit.

    * ``green``  — usage < 80% of limit
    * ``yellow`` — 80% ≤ usage < 100%
    * ``red``    — usage ≥ 100% (or limit ≤ 0)

    Args:
        used: Tokens or calls consumed.
        limit: Maximum tokens or calls allowed.

    Returns:
        One of ``"green"``, ``"yellow"``, ``"red"``.
    """
    if limit <= 0:
        return "red"
    ratio = used / limit
    if ratio >= RED_THRESHOLD:
        return "red"
    if ratio >= YELLOW_THRESHOLD:
        return "yellow"
    return "green"


def _compute_cost_cny(provider: str, total_tokens: int) -> Decimal:
    """Compute the CNY cost for a request.

    Args:
        provider: Provider name (e.g. ``"deepseek"``, ``"moka_ai"``).
        total_tokens: Total tokens consumed (input + output).

    Returns:
        Cost in CNY as a :class:`Decimal` with 6 decimal places.
    """
    price_per_1k = _PROVIDER_PRICING.get(provider, Decimal("0"))
    cost = Decimal(total_tokens) * price_per_1k / Decimal(1000)
    return cost.quantize(Decimal("0.000001"))


# ── Dataclasses ─────────────────────────────────────────────────────


@dataclass
class QuotaStatus:
    """Result of :meth:`UsageService.check_quota`.

    Attributes:
        traffic_light: ``"green"``, ``"yellow"``, or ``"red"``.
        token_used: Tokens consumed this month.
        token_limit: Monthly token quota.
        token_percentage: Usage as a percentage of the limit.
        is_red: Convenience flag — ``True`` when ``traffic_light == "red"``.
    """

    traffic_light: str
    token_used: int
    token_limit: int
    token_percentage: float
    is_red: bool


@dataclass
class UsageInfo:
    """Result of :meth:`UsageService.get_usage`.

    Attributes:
        month: Year-month string (``YYYY-MM``).
        traffic_light: Traffic-light status for the month.
        token_used: Tokens consumed.
        token_limit: Monthly token quota.
        asr_used: ASR calls consumed.
        tts_used: TTS calls consumed.
        ocr_used: OCR calls consumed.
        request_count: Total API requests (past months only; 0 for
            current month which reads from license counters).
    """

    month: str
    traffic_light: str
    token_used: int
    token_limit: int
    asr_used: int
    tts_used: int
    ocr_used: int
    request_count: int


# ── Service ─────────────────────────────────────────────────────────


class UsageService:
    """Usage recording and quota management service.

    The service is stateless apart from its injected dependencies (DB
    session, Redis client), making it safe to instantiate once per
    request.
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        redis_client: redis_asyncio.Redis,
    ) -> None:
        """Initialize the usage service.

        Args:
            db_session: Async SQLAlchemy session for usage/quota writes.
            redis_client: Async Redis client for quota cache operations.
        """
        self._db = db_session
        self._redis = redis_client

    # ── Quota check (tech design §7.1) ──────────────────────────────

    async def check_quota(
        self,
        user_id: str,
        *,
        request_type: str | None = None,
    ) -> QuotaStatus:
        """Check the user's quota and return the traffic-light status.

        When ``request_type`` is provided, this method also enforces
        the specific quota for that request type, raising the
        appropriate exception if exhausted.

        Args:
            user_id: User identifier.
            request_type: Optional request type — ``"llm"``, ``"asr"``,
                ``"tts"``, or ``"ocr"``.  When omitted, no exception is
                raised regardless of quota status.

        Returns:
            :class:`QuotaStatus` with current token usage info.

        Raises:
            LicenseNotFound: No license found for ``user_id``.
            QuotaExceeded: LLM token quota exhausted (``request_type="llm"``).
            ASRQuotaExceeded: ASR quota exhausted (``request_type="asr"``).
            TTSQuotaExceeded: TTS quota exhausted (``request_type="tts"``).
            OCRQuotaExceeded: OCR quota exhausted (``request_type="ocr"``).
        """
        license_row = await self._load_license(user_id)
        if license_row is None:
            raise LicenseNotFound()

        used = license_row.quota_used_tokens
        limit = license_row.quota_limit_tokens
        light = _compute_traffic_light(used, limit)
        percentage = round((used / limit * 100) if limit > 0 else 100.0, 2)
        status = QuotaStatus(
            traffic_light=light,
            token_used=used,
            token_limit=limit,
            token_percentage=percentage,
            is_red=(light == "red"),
        )

        # Enforce request-type-specific quotas
        if request_type == "llm":
            if light == "red":
                raise QuotaExceeded(
                    details={"used": used, "limit": limit}
                )
        elif request_type == "asr":
            if license_row.quota_used_asr >= license_row.quota_limit_asr:
                raise ASRQuotaExceeded(
                    details={
                        "used": license_row.quota_used_asr,
                        "limit": license_row.quota_limit_asr,
                    }
                )
        elif request_type == "tts":
            if license_row.quota_used_tts >= license_row.quota_limit_tts:
                raise TTSQuotaExceeded(
                    details={
                        "used": license_row.quota_used_tts,
                        "limit": license_row.quota_limit_tts,
                    }
                )
        elif request_type == "ocr":
            if license_row.quota_used_ocr >= license_row.quota_limit_ocr:
                raise OCRQuotaExceeded(
                    details={
                        "used": license_row.quota_used_ocr,
                        "limit": license_row.quota_limit_ocr,
                    }
                )

        return status

    # ── Usage recording (tech design §7.3) ─────────────────────────

    async def record_usage(
        self,
        *,
        user_id: str,
        provider: str,
        model: str,
        request_type: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int | None = None,
        status: int = 200,
    ) -> None:
        """Record a single AI usage event.

        Writes a :class:`UsageRecord` row, updates the license quota
        counters (only for successful requests), upserts the
        :class:`MonthlyUsage` summary, and refreshes the Redis quota
        cache.

        Args:
            user_id: User identifier.
            provider: Provider name (e.g. ``"deepseek"``).
            model: Model name (e.g. ``"deepseek-chat"``).
            request_type: ``"llm"``, ``"asr"``, ``"tts"``, or ``"ocr"``.
            tokens_in: Input tokens consumed (LLM only).
            tokens_out: Output tokens consumed (LLM only).
            latency_ms: Request latency in milliseconds.
            status: HTTP status code of the upstream response.
        """
        license_row = await self._load_license(user_id)
        if license_row is None:
            logger.warning("record_usage: no license for user_id=%s", user_id)
            return

        total_tokens = tokens_in + tokens_out
        success = status < 400
        cost_cny = _compute_cost_cny(provider, total_tokens) if success else Decimal("0")

        # ── 1. Write usage_records row ──
        record = UsageRecord(
            request_id=str(uuid.uuid4()),
            user_id=user_id,
            license_key=license_row.license_key,
            request_type=request_type,
            provider=provider,
            model=model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            total_tokens=total_tokens,
            duration_ms=latency_ms,
            cost_cny=cost_cny,
            status_code=status,
            success=success,
        )
        self._db.add(record)

        # ── 2. Update license quota (only for successful requests) ──
        if success:
            if request_type == "llm":
                license_row.quota_used_tokens += total_tokens
            elif request_type == "asr":
                license_row.quota_used_asr += 1
            elif request_type == "tts":
                license_row.quota_used_tts += 1
            elif request_type == "ocr":
                license_row.quota_used_ocr += 1

        # ── 3. Upsert monthly_usage (only for successful requests) ──
        if success:
            await self._upsert_monthly_usage(
                license_row=license_row,
                request_type=request_type,
                total_tokens=total_tokens,
                cost_cny=cost_cny,
            )

        await self._db.flush()
        await self._db.commit()

        # ── 4. Update Redis quota cache (non-blocking) ──
        await self._update_redis_cache(user_id, license_row)

    # ── Monthly reset (tech design §7.4) ────────────────────────────

    async def reset_monthly_quota(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        """Reset monthly quotas, archive usage, and clear caches.

        This method is designed to be called as a monthly cron job.
        It is **idempotent** — running it twice in the same month will
        not create duplicate archive rows.

        Flow:
        1. Compute the previous year-month.
        2. For each license:
           a. If a ``MonthlyUsage`` row for (user_id, prev_month) does
              not already exist, create one with the current quota
              counters.
           b. Zero the ``quota_used_*`` counters on the license.
        3. Clear the Redis quota cache for the previous month.
        4. Return the number of licenses processed.

        Args:
            now: Reference datetime (defaults to current UTC).  The
                previous month is derived from this value.

        Returns:
            Number of licenses whose counters were reset.
        """
        ref = now or datetime.now(timezone.utc)
        prev_month = _previous_year_month(ref)

        result = await self._db.execute(select(License))
        licenses = list(result.scalars().all())
        reset_count = 0

        for lic in licenses:
            # Check if archive already exists (idempotency)
            existing = await self._db.execute(
                select(MonthlyUsage).where(
                    MonthlyUsage.user_id == lic.user_id,
                    MonthlyUsage.year_month == prev_month,
                )
            )
            if existing.scalar_one_or_none() is None:
                # Create archive row
                archive = MonthlyUsage(
                    user_id=lic.user_id,
                    license_key=lic.license_key,
                    year_month=prev_month,
                    total_tokens=lic.quota_used_tokens,
                    total_cost_cny=Decimal("0"),  # cost tracked separately
                    request_count=0,  # not tracked on license
                    asr_count=lic.quota_used_asr,
                    tts_count=lic.quota_used_tts,
                    ocr_count=lic.quota_used_ocr,
                    status=_compute_traffic_light(
                        lic.quota_used_tokens, lic.quota_limit_tokens
                    ),
                )
                self._db.add(archive)

            # Zero the counters
            lic.quota_used_tokens = 0
            lic.quota_used_asr = 0
            lic.quota_used_tts = 0
            lic.quota_used_ocr = 0
            lic.quota_reset_at = ref
            reset_count += 1

        await self._db.flush()
        await self._db.commit()

        # Clear Redis cache for the previous month
        for lic in licenses:
            if lic.user_id:
                cache_key = f"{_QUOTA_CACHE_PREFIX}{lic.user_id}:{prev_month}"
                await self._redis.delete(cache_key)

        return reset_count

    # ── Usage query (tech design §4.3.3) ────────────────────────────

    async def get_usage(
        self,
        user_id: str,
        *,
        month: str | None = None,
    ) -> UsageInfo:
        """Return usage summary for a user.

        For the current month (or when ``month`` is ``None``), reads
        from the license's live quota counters.  For past months, reads
        from the archived :class:`MonthlyUsage` row.

        Args:
            user_id: User identifier.
            month: Optional year-month string (``YYYY-MM``).  If
                ``None`` or equal to the current month, reads from the
                license.

        Returns:
            :class:`UsageInfo` with usage details.  If no license is
            found, returns a red status with zero usage.
        """
        current_month = _current_year_month()
        target_month = month or current_month

        # Past month → read from monthly_usage archive
        if target_month != current_month:
            result = await self._db.execute(
                select(MonthlyUsage).where(
                    MonthlyUsage.user_id == user_id,
                    MonthlyUsage.year_month == target_month,
                )
            )
            monthly = result.scalar_one_or_none()
            if monthly is None:
                return UsageInfo(
                    month=target_month,
                    traffic_light="red",
                    token_used=0,
                    token_limit=0,
                    asr_used=0,
                    tts_used=0,
                    ocr_used=0,
                    request_count=0,
                )
            return UsageInfo(
                month=monthly.year_month,
                traffic_light=monthly.status,
                token_used=monthly.total_tokens,
                token_limit=0,  # not stored in archive
                asr_used=monthly.asr_count,
                tts_used=monthly.tts_count,
                ocr_used=monthly.ocr_count,
                request_count=monthly.request_count,
            )

        # Current month → read from license
        license_row = await self._load_license(user_id)
        if license_row is None:
            return UsageInfo(
                month=target_month,
                traffic_light="red",
                token_used=0,
                token_limit=0,
                asr_used=0,
                tts_used=0,
                ocr_used=0,
                request_count=0,
            )

        light = _compute_traffic_light(
            license_row.quota_used_tokens, license_row.quota_limit_tokens
        )
        return UsageInfo(
            month=target_month,
            traffic_light=light,
            token_used=license_row.quota_used_tokens,
            token_limit=license_row.quota_limit_tokens,
            asr_used=license_row.quota_used_asr,
            tts_used=license_row.quota_used_tts,
            ocr_used=license_row.quota_used_ocr,
            request_count=0,  # not tracked on license for current month
        )

    # ── Helpers ─────────────────────────────────────────────────────

    async def _load_license(self, user_id: str) -> License | None:
        """Load the license row for a user."""
        result = await self._db.execute(
            select(License).where(License.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _upsert_monthly_usage(
        self,
        *,
        license_row: License,
        request_type: str,
        total_tokens: int,
        cost_cny: Decimal,
    ) -> None:
        """Upsert the monthly_usage summary row for the current month."""
        year_month = _current_year_month()
        result = await self._db.execute(
            select(MonthlyUsage).where(
                MonthlyUsage.user_id == license_row.user_id,
                MonthlyUsage.year_month == year_month,
            )
        )
        monthly = result.scalar_one_or_none()

        if monthly is None:
            monthly = MonthlyUsage(
                user_id=license_row.user_id,
                license_key=license_row.license_key,
                year_month=year_month,
                total_tokens=0,
                total_cost_cny=Decimal("0"),
                request_count=0,
                asr_count=0,
                tts_count=0,
                ocr_count=0,
                status="green",
            )
            self._db.add(monthly)

        monthly.total_tokens += total_tokens
        monthly.total_cost_cny += cost_cny
        monthly.request_count += 1
        if request_type == "asr":
            monthly.asr_count += 1
        elif request_type == "tts":
            monthly.tts_count += 1
        elif request_type == "ocr":
            monthly.ocr_count += 1
        monthly.status = _compute_traffic_light(
            monthly.total_tokens, license_row.quota_limit_tokens
        )
        monthly.last_updated_at = datetime.now(timezone.utc)

    async def _update_redis_cache(
        self, user_id: str, license_row: License
    ) -> None:
        """Update the Redis quota cache with current usage."""
        year_month = _current_year_month()
        cache_key = f"{_QUOTA_CACHE_PREFIX}{user_id}:{year_month}"
        await self._redis.hset(
            cache_key,
            mapping={
                "tokens_used": str(license_row.quota_used_tokens),
                "tokens_limit": str(license_row.quota_limit_tokens),
                "asr_used": str(license_row.quota_used_asr),
                "tts_used": str(license_row.quota_used_tts),
                "ocr_used": str(license_row.quota_used_ocr),
            },
        )
