"""Billing service — quota checking and usage recording.

Reference: Pro_Edition_Tech_Design_Phase0.md §7 Usage Billing Design
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from gateway.config import Settings, get_settings
from gateway.core.exceptions import (
    ASRQuotaExceededError,
    OCRQuotaExceededError,
    QuotaExceededError,
    TTSQuotaExceededError,
)
from gateway.models.tables import License, UsageRecord


class BillingService:
    """Handle quota checking and usage recording.

    Uses an in-memory store for usage records. In production, this would
    persist to PostgreSQL via an async session.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        licenses: dict[str, License] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._licenses = licenses or {}
        self._usage_records: list[UsageRecord] = []

    def set_licenses(self, licenses: dict[str, License]) -> None:
        """Set the license store reference (shared with LicenseService)."""
        self._licenses = licenses

    def check_quota(self, user_id: str, license_key: str, request_type: str = "llm") -> str:
        """Check if the user has remaining quota for the request type.

        Returns the traffic light status: green / yellow / red.

        Raises:
            QuotaExceededError: If LLM token quota is exhausted (red).
            ASRQuotaExceededError: If ASR count quota is exhausted.
            TTSQuotaExceededError: If TTS count quota is exhausted.
            OCRQuotaExceededError: If OCR count quota is exhausted.
        """
        lic = self._licenses.get(license_key)
        if lic is None:
            return "green"  # No license found — allow (will fail elsewhere)

        if request_type == "llm":
            used = lic.quota_used_tokens
            limit = lic.quota_limit_tokens
            percentage = (used / limit * 100) if limit > 0 else 100.0
            if percentage >= 100:
                raise QuotaExceededError(
                    details={
                        "quota_limit": limit,
                        "quota_used": used,
                        "reset_at": lic.quota_reset_at.isoformat(),
                    }
                )
            return "red" if percentage >= 100 else ("yellow" if percentage >= 80 else "green")

        if request_type == "asr":
            if lic.quota_used_asr >= lic.quota_limit_asr:
                raise ASRQuotaExceededError(
                    details={"limit": lic.quota_limit_asr, "used": lic.quota_used_asr}
                )
        elif request_type == "tts":
            if lic.quota_used_tts >= lic.quota_limit_tts:
                raise TTSQuotaExceededError(
                    details={"limit": lic.quota_limit_tts, "used": lic.quota_used_tts}
                )
        elif request_type == "ocr":
            if lic.quota_used_ocr >= lic.quota_limit_ocr:
                raise OCRQuotaExceededError(
                    details={"limit": lic.quota_limit_ocr, "used": lic.quota_used_ocr}
                )

        return "green"

    async def record_usage(
        self,
        request_id: str,
        user_id: str,
        license_key: str,
        request_type: str,
        provider: str,
        model: str,
        key_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int | None = None,
        cost_cny: float = 0.0,
        status_code: int = 200,
        success: bool = True,
    ) -> UsageRecord:
        """Record a usage entry and update license quota.

        This is called asynchronously after the AI response is sent.
        """
        record = UsageRecord(
            request_id=request_id,
            user_id=user_id,
            license_key=license_key,
            request_type=request_type,
            provider=provider,
            model=model,
            key_id=key_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens or (input_tokens + output_tokens),
            duration_ms=duration_ms,
            cost_cny=cost_cny,
            status_code=status_code,
            success=success,
        )
        self._usage_records.append(record)

        # Update license quota
        lic = self._licenses.get(license_key)
        if lic is not None:
            if request_type == "llm":
                lic.quota_used_tokens += total_tokens or (input_tokens + output_tokens)
            elif request_type == "asr":
                lic.quota_used_asr += 1
            elif request_type == "tts":
                lic.quota_used_tts += 1
            elif request_type == "ocr":
                lic.quota_used_ocr += 1
            lic.updated_at = datetime.now(UTC)

        return record

    def get_usage(self, user_id: str, license_key: str, month: str | None = None) -> dict[str, Any]:
        """Return usage summary for the given user/license/month."""
        lic = self._licenses.get(license_key)
        if lic is None:
            return {
                "month": month or datetime.now(UTC).strftime("%Y-%m"),
                "traffic_light": "green",
                "quota": {},
                "cost_cny": 0.0,
                "request_count": 0,
                "reset_at": datetime.now(UTC).isoformat(),
                "history": [],
            }

        tokens_used = lic.quota_used_tokens
        tokens_limit = lic.quota_limit_tokens
        tokens_percentage = (tokens_used / tokens_limit * 100) if tokens_limit > 0 else 0.0
        traffic_light = (
            "red" if tokens_percentage >= 100 else ("yellow" if tokens_percentage >= 80 else "green")
        )

        # Count records for this license
        records = [r for r in self._usage_records if r.license_key == license_key]
        total_cost = sum(r.cost_cny for r in records)

        return {
            "month": month or datetime.now(UTC).strftime("%Y-%m"),
            "traffic_light": traffic_light,
            "quota": {
                "tokens": {
                    "limit": tokens_limit,
                    "used": tokens_used,
                    "remaining": max(0, tokens_limit - tokens_used),
                    "percentage": round(tokens_percentage, 1),
                },
                "asr": {
                    "limit": lic.quota_limit_asr,
                    "used": lic.quota_used_asr,
                    "remaining": max(0, lic.quota_limit_asr - lic.quota_used_asr),
                    "percentage": round(
                        lic.quota_used_asr / lic.quota_limit_asr * 100, 1
                    ) if lic.quota_limit_asr > 0 else 0,
                },
                "tts": {
                    "limit": lic.quota_limit_tts,
                    "used": lic.quota_used_tts,
                    "remaining": max(0, lic.quota_limit_tts - lic.quota_used_tts),
                    "percentage": round(
                        lic.quota_used_tts / lic.quota_limit_tts * 100, 1
                    ) if lic.quota_limit_tts > 0 else 0,
                },
                "ocr": {
                    "limit": lic.quota_limit_ocr,
                    "used": lic.quota_used_ocr,
                    "remaining": max(0, lic.quota_limit_ocr - lic.quota_used_ocr),
                    "percentage": round(
                        lic.quota_used_ocr / lic.quota_limit_ocr * 100, 1
                    ) if lic.quota_limit_ocr > 0 else 0,
                },
            },
            "cost_cny": round(total_cost, 4),
            "request_count": len(records),
            "reset_at": lic.quota_reset_at.isoformat(),
            "history": [],
        }

    def calculate_cost(self, provider: str, total_tokens: int) -> float:
        """Calculate cost in CNY for a given provider and token count."""
        price_per_1k = self.settings.provider_price_per_1k(provider)
        return round(total_tokens / 1000.0 * price_per_1k, 6)
