"""Tests for PII encryption utilities."""
from promiselink.core.crypto import (
    encrypt_value, decrypt_value,
    encrypt_pii_in_properties, decrypt_pii_in_properties,
    PII_PREFIX,
)


class TestPIIEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        original = "13800138000"
        encrypted = encrypt_value(original)
        assert encrypted.startswith(PII_PREFIX)
        assert decrypt_value(encrypted) == original

    def test_decrypt_non_encrypted_returns_as_is(self):
        assert decrypt_value("plain_text") == "plain_text"

    def test_encrypt_pii_in_properties(self):
        props = {"basic": {"phone": "13800138000", "email": "test@example.com", "name": "张三"}}
        result = encrypt_pii_in_properties(props)
        assert result["basic"]["phone"].startswith(PII_PREFIX)
        assert result["basic"]["email"].startswith(PII_PREFIX)
        assert result["basic"]["name"] == "张三"  # Non-PII not encrypted

    def test_decrypt_pii_in_properties(self):
        props = {"basic": {"phone": encrypt_value("13800138000"), "email": encrypt_value("t@e.com"), "name": "张三"}}
        result = decrypt_pii_in_properties(props)
        assert result["basic"]["phone"] == "13800138000"
        assert result["basic"]["email"] == "t@e.com"
        assert result["basic"]["name"] == "张三"

    def test_empty_properties(self):
        assert encrypt_pii_in_properties(None) is None
        assert encrypt_pii_in_properties({}) == {}
        assert decrypt_pii_in_properties(None) is None
