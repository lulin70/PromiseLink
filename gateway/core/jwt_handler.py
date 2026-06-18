"""JWT signing and verification utilities for the gateway.

Supports both HS256 (symmetric, for dev/test) and RS256 (asymmetric,
for production). The algorithm is selected via ``Settings.jwt_algorithm``.

Token structure (tech design §6.6)::

    {
      "user_id": "u_abc123",
      "license_key": "PL-PRO-A1B2-C3D4-E5F6",
      "plan_type": "pro",
      "device_fingerprint": "sha256:abc123...",
      "jti": "550e8400-e29b-41d4-a716-446655440000",
      "iat": 1718037056,
      "exp": 1718037956,
      "iss": "promiselink-gateway",
      "aud": "promiselink-relay",
      "token_type": "access"
    }
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.config import Settings, get_settings
from gateway.core.exceptions import JWTExpired, JWTInvalid

# ── Constants (tech design §6.6, §10.2) ─────────────────────────────

ALGORITHM = "RS256"
DEFAULT_ACCESS_TOKEN_TTL = 900  # 15 minutes
DEFAULT_REFRESH_TOKEN_TTL = 604800  # 7 days
DEFAULT_ISSUER = "promiselink-gateway"
DEFAULT_AUDIENCE = "promiselink-relay"


# ── Standalone RS256 functions (used by LicenseService) ─────────────


@dataclass(frozen=True)
class TokenPayload:
    """Decoded JWT payload as a typed structure.

    Attributes:
        user_id: User identifier from the user JWT.
        license_key: Bound license key.
        plan_type: ``pro`` or ``trial``.
        device_fingerprint: SHA256 device fingerprint.
        jti: Unique JWT ID (used for CRL revocation).
        iat: Issued-at timestamp (Unix seconds).
        exp: Expiry timestamp (Unix seconds).
        iss: Issuer claim.
        aud: Audience claim.
        token_type: ``access`` or ``refresh``.
    """

    user_id: str
    license_key: str
    plan_type: str
    device_fingerprint: str
    jti: str
    iat: int
    exp: int
    iss: str
    aud: str
    token_type: str = "access"

    def to_dict(self) -> dict[str, Any]:
        """Return the payload as a plain dict (for JWT encoding)."""
        return {
            "user_id": self.user_id,
            "license_key": self.license_key,
            "plan_type": self.plan_type,
            "device_fingerprint": self.device_fingerprint,
            "jti": self.jti,
            "iat": self.iat,
            "exp": self.exp,
            "iss": self.iss,
            "aud": self.aud,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenPayload:
        """Build a :class:`TokenPayload` from a decoded JWT dict."""
        return cls(
            user_id=str(data["user_id"]),
            license_key=str(data["license_key"]),
            plan_type=str(data["plan_type"]),
            device_fingerprint=str(data["device_fingerprint"]),
            jti=str(data["jti"]),
            iat=int(data["iat"]),
            exp=int(data["exp"]),
            iss=str(data["iss"]),
            aud=str(data["aud"]),
            token_type=str(data.get("token_type", "access")),
        )


def generate_rsa_keypair() -> tuple[str, str]:
    """Generate a fresh RSA keypair and return ``(private_pem, public_pem)``.

    Used by tests to create ephemeral signing keys. Production keys are
    loaded from ``GATEWAY_JWT_PRIVATE_KEY`` / ``GATEWAY_JWT_PUBLIC_KEY``
    environment variables (see tech design §10.2).
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def sign_token(
    *,
    user_id: str,
    license_key: str,
    plan_type: str,
    device_fingerprint: str,
    private_key_pem: str,
    ttl: int = DEFAULT_ACCESS_TOKEN_TTL,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    token_type: str = "access",
    jti: str | None = None,
) -> str:
    """Sign and return a compact RS256 JWT string.

    Args:
        user_id: User identifier.
        license_key: Bound license key.
        plan_type: ``pro`` or ``trial``.
        device_fingerprint: SHA256 device fingerprint.
        private_key_pem: RSA private key in PEM format.
        ttl: Token lifetime in seconds (default 900 = 15 min).
        issuer: ``iss`` claim.
        audience: ``aud`` claim.
        token_type: ``access`` or ``refresh``.
        jti: Optional JWT ID. A random UUID is generated if omitted.

    Returns:
        Compact JWT string signed with RS256.
    """
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "plan_type": plan_type,
        "device_fingerprint": device_fingerprint,
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl,
        "iss": issuer,
        "aud": audience,
        "token_type": token_type,
    }
    return jwt.encode(payload, private_key_pem, algorithm=ALGORITHM)


def verify_token(
    token: str,
    *,
    public_key_pem: str,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    leeway: int = 0,
) -> TokenPayload:
    """Verify a JWT signature and claims, returning the decoded payload.

    Args:
        token: Compact JWT string.
        public_key_pem: RSA public key in PEM format.
        issuer: Expected ``iss`` claim.
        audience: Expected ``aud`` claim.
        leeway: Grace period in seconds for ``exp`` (used by refresh flow
            to accept tokens up to 5 minutes past expiry).

    Returns:
        Decoded :class:`TokenPayload`.

    Raises:
        JWTInvalid: Signature invalid, malformed token, wrong iss/aud,
            or wrong algorithm (HS256 tokens are rejected).
        JWTExpired: Token past its ``exp`` (after leeway).
    """
    try:
        decoded = jwt.decode(
            token,
            public_key_pem,
            algorithms=[ALGORITHM],  # Only RS256 accepted
            issuer=issuer,
            audience=audience,
            leeway=leeway,
            options={"require": ["exp", "iat", "iss", "aud", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise JWTExpired() from exc
    except jwt.InvalidIssuerError as exc:
        raise JWTInvalid(f"Invalid issuer: {exc}") from exc
    except jwt.InvalidAudienceError as exc:
        raise JWTInvalid(f"Invalid audience: {exc}") from exc
    except jwt.InvalidAlgorithmError as exc:
        raise JWTInvalid(f"Algorithm not allowed: {exc}") from exc
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise JWTInvalid(f"Token verification failed: {exc}") from exc

    return TokenPayload.from_dict(decoded)


# ── JWTHandler class (HS256/RS256, settings-driven) ─────────────────


class JWTHandler:
    """JWT handler supporting HS256 (dev/test) and RS256 (production).

    The algorithm is determined by ``settings.jwt_algorithm``:
    - ``HS256``: uses ``settings.jwt_secret_key`` (symmetric).
    - ``RS256``: uses ``settings.jwt_private_key_path`` /
      ``settings.jwt_public_key_path`` (asymmetric).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the JWT handler.

        Args:
            settings: Gateway settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self.algorithm = self.settings.jwt_algorithm
        self.issuer = self.settings.jwt_issuer
        self.audience = self.settings.jwt_audience
        self.access_ttl = self.settings.jwt_access_token_ttl
        self.refresh_ttl = self.settings.jwt_refresh_token_ttl

        if self.algorithm == "RS256":
            self._private_key = self._load_private_key()
            self._public_key = self._load_public_key()
            self._secret = None
        else:
            self._private_key = None
            self._public_key = None
            self._secret = self.settings.jwt_secret_key

    def _load_private_key(self) -> str:
        """Load the RSA private key from the configured path."""
        path = self.settings.jwt_private_key_path
        if not path:
            raise JWTInvalid("jwt_private_key_path not configured for RS256")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _load_public_key(self) -> str:
        """Load the RSA public key from the configured path."""
        path = self.settings.jwt_public_key_path
        if not path:
            raise JWTInvalid("jwt_public_key_path not configured for RS256")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _get_signing_key(self) -> str:
        """Return the key used for signing."""
        if self.algorithm == "RS256":
            return self._private_key  # type: ignore[return-value]
        return self._secret  # type: ignore[return-value]

    def _get_verify_key(self) -> str:
        """Return the key used for verification."""
        if self.algorithm == "RS256":
            return self._public_key  # type: ignore[return-value]
        return self._secret  # type: ignore[return-value]

    def create_access_token(
        self,
        *,
        user_id: str,
        license_key: str = "",
        plan_type: str = "pro",
        device_fingerprint: str = "",
        expires_in: int | None = None,
    ) -> str:
        """Create a signed access JWT.

        Args:
            user_id: User identifier.
            license_key: Bound license key.
            plan_type: ``pro`` or ``trial``.
            device_fingerprint: Device fingerprint.
            expires_in: Override TTL in seconds.

        Returns:
            Compact JWT string.
        """
        return self._sign(
            user_id=user_id,
            license_key=license_key,
            plan_type=plan_type,
            device_fingerprint=device_fingerprint,
            ttl=expires_in if expires_in is not None else self.access_ttl,
            token_type="access",
        )

    def create_refresh_token(
        self,
        *,
        user_id: str,
        license_key: str = "",
        plan_type: str = "pro",
        device_fingerprint: str = "",
        expires_in: int | None = None,
    ) -> str:
        """Create a signed refresh JWT.

        Args:
            user_id: User identifier.
            license_key: Bound license key.
            plan_type: ``pro`` or ``trial``.
            device_fingerprint: Device fingerprint.
            expires_in: Override TTL in seconds.

        Returns:
            Compact JWT string.
        """
        return self._sign(
            user_id=user_id,
            license_key=license_key,
            plan_type=plan_type,
            device_fingerprint=device_fingerprint,
            ttl=expires_in if expires_in is not None else self.refresh_ttl,
            token_type="refresh",
        )

    def _sign(
        self,
        *,
        user_id: str,
        license_key: str,
        plan_type: str,
        device_fingerprint: str,
        ttl: int,
        token_type: str,
    ) -> str:
        """Sign and return a compact JWT string."""
        now = int(time.time())
        payload: dict[str, Any] = {
            "user_id": user_id,
            "license_key": license_key,
            "plan_type": plan_type,
            "device_fingerprint": device_fingerprint,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl,
            "iss": self.issuer,
            "aud": self.audience,
            "token_type": token_type,
        }
        return jwt.encode(payload, self._get_signing_key(), algorithm=self.algorithm)

    def verify_token(
        self,
        token: str,
        *,
        expected_type: str | None = None,
        leeway: int = 0,
    ) -> dict[str, Any]:
        """Verify a JWT signature and claims, returning the decoded payload.

        Args:
            token: Compact JWT string.
            expected_type: If set, verify ``token_type`` matches.
            leeway: Grace period in seconds for ``exp``.

        Returns:
            Decoded payload as a dict.

        Raises:
            JWTInvalid: Signature invalid, malformed token, wrong iss/aud.
            JWTExpired: Token past its ``exp`` (after leeway).
        """
        try:
            decoded = jwt.decode(
                token,
                self._get_verify_key(),
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                leeway=leeway,
                options={"require": ["exp", "iat", "iss", "aud", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise JWTExpired() from exc
        except jwt.InvalidIssuerError as exc:
            raise JWTInvalid(f"Invalid issuer: {exc}") from exc
        except jwt.InvalidAudienceError as exc:
            raise JWTInvalid(f"Invalid audience: {exc}") from exc
        except jwt.InvalidAlgorithmError as exc:
            raise JWTInvalid(f"Algorithm not allowed: {exc}") from exc
        except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
            raise JWTInvalid(f"Token verification failed: {exc}") from exc

        if expected_type is not None:
            token_type = decoded.get("token_type", "access")
            if token_type != expected_type:
                raise JWTInvalid(
                    f"Expected token_type '{expected_type}', got '{token_type}'"
                )

        return decoded
