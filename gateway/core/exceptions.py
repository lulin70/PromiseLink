"""Custom exceptions for the PromiseLink gateway.

Each exception maps to an HTTP error code and an error code string
defined in the tech design doc §11.
"""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for all gateway errors.

    Attributes:
        code: Stable error code string (e.g. ``JWT_INVALID``).
        http_status: HTTP status code to return to the client.
        message: Human-readable error message.
    """

    code: str = "GATEWAY_INTERNAL_ERROR"
    http_status: int = 500
    message: str = "Gateway internal error"

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 http_status: int | None = None, details: dict | None = None) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details or {}
        super().__init__(self.message)

    @property
    def status_code(self) -> int:
        """Alias for http_status (compatibility property)."""
        return self.http_status


# ── Validation errors (400) ──────────────────────────────────────────

class ValidationError(GatewayError):
    code = "VALIDATION_ERROR"
    http_status = 400
    message = "Request validation error"


class InvalidLicenseKeyFormat(GatewayError):
    code = "INVALID_LICENSE_KEY_FORMAT"
    http_status = 400
    message = "Invalid license key format"


class InvalidDeviceFingerprint(GatewayError):
    code = "INVALID_DEVICE_FINGERPRINT"
    http_status = 400
    message = "Invalid device fingerprint format"


# ── Authentication errors (401) ─────────────────────────────────────

class JWTInvalid(GatewayError):
    code = "JWT_INVALID"
    http_status = 401
    message = "JWT is invalid"


class JWTExpired(GatewayError):
    code = "JWT_EXPIRED"
    http_status = 401
    message = "JWT has expired"


class JWTRevoked(GatewayError):
    code = "JWT_REVOKED"
    http_status = 401
    message = "JWT has been revoked"


class JWTMissing(GatewayError):
    code = "JWT_MISSING"
    http_status = 401
    message = "Authorization header is missing"


class APIKeyInvalidError(GatewayError):
    code = "API_KEY_INVALID"
    http_status = 401
    message = "API key is missing or invalid"


# ── Authorization errors (403) ──────────────────────────────────────

class LicenseInactive(GatewayError):
    code = "LICENSE_INACTIVE"
    http_status = 403
    message = "License is not active"


class LicenseExpired(GatewayError):
    code = "LICENSE_EXPIRED"
    http_status = 403
    message = "License has expired"


class LicenseCancelled(GatewayError):
    code = "LICENSE_CANCELLED"
    http_status = 403
    message = "License has been cancelled"


class LicenseSuspended(GatewayError):
    code = "LICENSE_SUSPENDED"
    http_status = 403
    message = "License has been suspended"


class DeviceFingerprintMismatch(GatewayError):
    code = "DEVICE_FINGERPRINT_MISMATCH"
    http_status = 403
    message = "Device fingerprint does not match"


class DeviceLimitExceeded(GatewayError):
    code = "DEVICE_LIMIT_EXCEEDED"
    http_status = 409
    message = "Maximum device limit exceeded"


class PermissionDeniedError(GatewayError):
    code = "PERMISSION_DENIED"
    http_status = 403
    message = "Permission denied"


# ── Quota errors (402) ──────────────────────────────────────────────

class QuotaExceeded(GatewayError):
    code = "QUOTA_EXCEEDED"
    http_status = 402
    message = "Monthly AI quota has been exhausted"


class ASRQuotaExceeded(GatewayError):
    code = "ASR_QUOTA_EXCEEDED"
    http_status = 402
    message = "Monthly ASR quota has been exhausted"


class TTSQuotaExceeded(GatewayError):
    code = "TTS_QUOTA_EXCEEDED"
    http_status = 402
    message = "Monthly TTS quota has been exhausted"


class OCRQuotaExceeded(GatewayError):
    code = "OCR_QUOTA_EXCEEDED"
    http_status = 402
    message = "Monthly OCR quota has been exhausted"


# ── Not found (404) ─────────────────────────────────────────────────

class LicenseNotFound(GatewayError):
    code = "LICENSE_NOT_FOUND"
    http_status = 404
    message = "License not found"


# ── Conflict (409) ──────────────────────────────────────────────────

class LicenseAlreadyActivated(GatewayError):
    code = "LICENSE_ALREADY_ACTIVATED"
    http_status = 409
    message = "License has already been activated by another user"


# ── Rate limit (429) ────────────────────────────────────────────────

class RateLimitExceeded(GatewayError):
    code = "RATE_LIMIT_EXCEEDED"
    http_status = 429
    message = "Too many requests"


class LicenseActivateTooFrequent(GatewayError):
    code = "LICENSE_ACTIVATE_TOO_FREQUENT"
    http_status = 429
    message = "License activation too frequent"


# ── Upstream / provider errors (502/504) ────────────────────────────

class UpstreamError(GatewayError):
    code = "UPSTREAM_ERROR"
    http_status = 502
    message = "Upstream provider returned an error"


class UpstreamTimeoutError(GatewayError):
    code = "UPSTREAM_TIMEOUT"
    http_status = 504
    message = "Upstream provider timed out"


class ProviderRateLimitedError(GatewayError):
    code = "PROVIDER_RATE_LIMITED"
    http_status = 502
    message = "Upstream provider rate limited"


class NoAvailableKeyError(GatewayError):
    code = "NO_AVAILABLE_KEY"
    http_status = 503
    message = "No available API keys in the pool"


# ── Aliases (``*Error`` suffix variants used across the codebase) ──

QuotaExceededError = QuotaExceeded
ASRQuotaExceededError = ASRQuotaExceeded
TTSQuotaExceededError = TTSQuotaExceeded
OCRQuotaExceededError = OCRQuotaExceeded
JWTInvalidError = JWTInvalid
JWTExpiredError = JWTExpired
JWTRevokedError = JWTRevoked
JWTMissingError = JWTMissing
RateLimitExceededError = RateLimitExceeded
