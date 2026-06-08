"""PII encryption utilities for EventLink.

Uses AES-256-GCM to encrypt sensitive fields (phone, email) in Entity.properties.
The encryption key is derived from settings.secret_key using PBKDF2.
"""

import base64
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eventlink.config import get_settings

PII_FIELDS = {"phone", "email"}
PII_PREFIX = "enc:"  # Prefix to identify encrypted values


def _derive_key() -> bytes:
    """Derive a 256-bit key from secret_key using PBKDF2.

    Uses secret_key as salt source (deterministic per deployment but unique per instance).
    Each deployment with a different secret_key produces a different derived key.
    """
    settings = get_settings()
    # Use secret_key as both password and salt source — deterministic per deployment,
    # but unique per instance (unlike a hardcoded salt shared across all deployments)
    salt = hashlib.sha256(settings.secret_key.encode()).digest()
    return hashlib.pbkdf2_hmac(
        "sha256",
        settings.secret_key.encode(),
        salt,
        100_000,
    )


def encrypt_value(plaintext: str) -> str:
    """Encrypt a PII value. Returns 'enc:' + base64(nonce+ciphertext)."""
    key = _derive_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return PII_PREFIX + base64.b64encode(nonce + ciphertext).decode()


def decrypt_value(encrypted: str) -> str:
    """Decrypt a PII value. Expects 'enc:' + base64(nonce+ciphertext)."""
    if not encrypted.startswith(PII_PREFIX):
        return encrypted  # Not encrypted, return as-is
    key = _derive_key()
    data = base64.b64decode(encrypted[len(PII_PREFIX):])
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def encrypt_pii_in_properties(properties: dict) -> dict:
    """Encrypt PII fields in Entity.properties.basic dict."""
    if not properties:
        return properties
    basic = properties.get("basic", {})
    if not basic:
        return properties
    result = dict(properties)
    result["basic"] = dict(basic)
    for field in PII_FIELDS:
        val = result["basic"].get(field)
        if val and isinstance(val, str) and not val.startswith(PII_PREFIX):
            result["basic"][field] = encrypt_value(val)
    return result


def decrypt_pii_in_properties(properties: dict) -> dict:
    """Decrypt PII fields in Entity.properties.basic dict."""
    if not properties:
        return properties
    basic = properties.get("basic", {})
    if not basic:
        return properties
    result = dict(properties)
    result["basic"] = dict(basic)
    for field in PII_FIELDS:
        val = result["basic"].get(field)
        if val and isinstance(val, str) and val.startswith(PII_PREFIX):
            result["basic"][field] = decrypt_value(val)
    return result
