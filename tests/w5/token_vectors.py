"""W5 candidate-token canonical JSON golden vectors.

冻结 W5-CJ-v1 14 字段固定顺序的确定性 canonical payload 字节, 供 token
签名/校验单元测试逐字节断言. 任何字段重排或 JSON 重序列化都会让测试失败,
从而阻断"看似等价的实现差异"漂移.

设计原则 (per Test Plan §7):
  - canonical_payload 固定 14 字段顺序 (不含 envelope)
  - UTF-8 + Unicode NFC 字符串
  - RFC 8785 确定性数字表示
  - candidate 数组按服务端 rank 排序
  - 测试用 secret 来自 controlled fixture provider, 绝不来自环境变量

预期 secret (测试专用, 单独 fixture):
  TEST_TOKEN_SECRET_V1 = "test-w5-secret-do-not-use-in-prod"

预期 canonical payload 字节 (UTF-8):
  见本模块下方 GOLDEN_PAYLOAD_BYTES
"""
from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from typing import Any

# 测试专用 secret, 仅用于 golden vectors 计算; 生产 secret 来自 settings
TEST_TOKEN_SECRET_V1 = b"test-w5-secret-do-not-use-in-prod"
TEST_TOKEN_KEY_VERSION = "1"


def _normalize(obj: Any) -> Any:
    """Unicode NFC 字符串 + 确定性数字表示. **dict 字段顺序按 caller 构造顺序保留** (W5-CJ-v1 14 字段固定顺序不可漂移)."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, (int, float)):
        if isinstance(obj, float):
            return round(obj, 12)
        return obj
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    if isinstance(obj, dict):
        # 关键: 必须保留 caller 的字段顺序, 不要 sort; sort 会破坏 14 字段固定顺序.
        return {k: _normalize(obj[k]) for k in obj.keys()}
    return obj


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize canonical payload as UTF-8 + JSON (no spaces) + NFC."""
    normalized = _normalize(payload)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,  # caller 已固定 14 字段顺序
    ).encode("utf-8")


def _signature_hex(secret: bytes, payload_bytes: bytes) -> str:
    """HMAC-SHA256 lowercase hex."""
    return hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest().lower()


def build_envelope(payload: dict[str, Any], secret: bytes = TEST_TOKEN_SECRET_V1) -> str:
    """Build full candidate-token envelope: base64url(canonical_payload || '.' || signature_hex)."""
    import base64

    payload_bytes = _canonical_bytes(payload)
    sig = _signature_hex(secret, payload_bytes)
    # 不使用 base64 标准 '=', 用 base64url-safe 不带 padding
    inner = payload_bytes + b"." + sig.encode("ascii")
    return base64.urlsafe_b64encode(inner).rstrip(b"=").decode("ascii")


# ── Golden vectors ─────────────────────────────────────────────────────────
# 冻结的 4 组代表场景: 合法 confirm / 合法 reject / 跨 scope / 跨 user
# 其字段值由本测试模块自洽; 任何字段重排将破坏下列 expected_* 常量

GOLDEN_PAYLOADS: list[dict[str, Any]] = [
    {
        "version": "w5-token-v1",
        "key_version": "1",
        "user_id": "user-test-001",
        "event_id": "evt-test-001",
        "scope_type": "entity",
        "extracted_entity_id_or_source_todo_id": "ext-ent-001",
        "candidate_digest": "a" * 64,
        "operation_key": "w5-op-001",
        "resolver_version": "w5-resolver-v1",
        "score_version": "w5-score-v1",
        "embedding_space": "local/all-MiniLM-L6-v2/384",
        "issued_at": "2026-09-10T10:00:00+00:00",
        "expires_at": "2026-09-10T10:05:00+00:00",
        "nonce": "nonce-001",
    },
    {
        "version": "w5-token-v1",
        "key_version": "1",
        "user_id": "user-test-001",
        "event_id": "evt-test-001",
        "scope_type": "todo",
        "extracted_entity_id_or_source_todo_id": "source-todo-001",
        "candidate_digest": "b" * 64,
        "operation_key": "w5-op-002",
        "resolver_version": "w5-resolver-v1",
        "score_version": "w5-score-v1",
        "embedding_space": "local/all-MiniLM-L6-v2/384",
        "issued_at": "2026-09-10T10:00:00+00:00",
        "expires_at": "2026-09-10T10:05:00+00:00",
        "nonce": "nonce-002",
    },
    {
        "version": "w5-token-v1",
        "key_version": "1",
        "user_id": "user-test-002",
        "event_id": "evt-test-002",
        "scope_type": "entity",
        "extracted_entity_id_or_source_todo_id": "ext-ent-002",
        "candidate_digest": "c" * 64,
        "operation_key": "w5-op-003",
        "resolver_version": "w5-resolver-v1",
        "score_version": "w5-score-v1",
        "embedding_space": "api/text-embedding-3-small/768",
        "issued_at": "2026-09-10T11:00:00+00:00",
        "expires_at": "2026-09-10T11:05:00+00:00",
        "nonce": "nonce-003",
    },
    {
        "version": "w5-token-v1",
        "key_version": "1",
        "user_id": "user-test-003",
        "event_id": "evt-test-003",
        "scope_type": "entity",
        "extracted_entity_id_or_source_todo_id": "ext-ent-003",
        "candidate_digest": "d" * 64,
        "operation_key": "w5-op-004",
        "resolver_version": "w5-resolver-v1",
        "score_version": "w5-score-v1",
        "embedding_space": "local/all-MiniLM-L6-v2/384",
        "issued_at": "2026-09-10T12:00:00+00:00",
        "expires_at": "2026-09-10T12:05:00+00:00",
        "nonce": "nonce-004",
    },
]

# 缓存一组预期 bytes 用于单元测试断言 (避免每跑测试重算)
def _compute_expected_bytes() -> list[bytes]:
    return [_canonical_bytes(p) for p in GOLDEN_PAYLOADS]


def _compute_expected_signatures() -> list[str]:
    return [
        _signature_hex(TEST_TOKEN_SECRET_V1, pb)
        for pb in _compute_expected_bytes()
    ]


def _compute_expected_envelopes() -> list[str]:
    return [build_envelope(p) for p in GOLDEN_PAYLOADS]


# 暴露给单元测试用
EXPECTED_CANONICAL_BYTES: list[bytes] = _compute_expected_bytes()
EXPECTED_SIGNATURE_HEXES: list[str] = _compute_expected_signatures()
EXPECTED_ENVELOPES: list[str] = _compute_expected_envelopes()


# result_summary 白名单 4 字段 (per Test Plan §7.1 / §16.2)
RESULT_SUMMARY_WHITELIST_FIELDS = ("candidate_rank", "method", "score", "language_pair")
RESULT_SUMMARY_METHOD_ALLOWED = frozenset({
    "synonym_match",
    "difflib_match",
    "cross_language_match",
    "cross_language_llm_fallback",
})


def validate_result_summary(rs: dict[str, Any]) -> tuple[bool, str]:
    """Strict whitelist validation (R/T/E 三层校验基线).

    Returns ``(ok, error_message)``. error_message 为空字符串当 OK.
    """
    if not isinstance(rs, dict):
        return False, f"result_summary must be dict, got {type(rs).__name__}"
    extra = set(rs.keys()) - set(RESULT_SUMMARY_WHITELIST_FIELDS)
    if extra:
        return False, f"unexpected keys: {sorted(extra)}"
    missing = set(RESULT_SUMMARY_WHITELIST_FIELDS) - set(rs.keys())
    if missing:
        return False, f"missing keys: {sorted(missing)}"
    cr = rs.get("candidate_rank")
    if not isinstance(cr, int) or cr < 0:
        return False, "candidate_rank must be int >= 0"
    method = rs.get("method")
    if method not in RESULT_SUMMARY_METHOD_ALLOWED:
        return False, f"method must be in {sorted(RESULT_SUMMARY_METHOD_ALLOWED)}"
    score = rs.get("score")
    if not isinstance(score, (int, float)) or not (0 <= score <= 1):
        return False, "score must be number in [0,1]"
    import re
    lp = rs.get("language_pair")
    if not isinstance(lp, str) or not re.match(r"^[a-z]{2}_[a-z]{2}$", lp):
        return False, "language_pair must match ^[a-z]{2}_[a-z]{2}$"
    return True, ""