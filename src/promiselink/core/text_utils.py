"""Shared text and JSON utilities for PromiseLink services.

Consolidates duplicate logic from entity_extractor, todo_generator, and llm_client.
"""

import json
import logging
import re

logger = logging.getLogger("promiselink.text_utils")

# Prompt injection detection patterns
INJECTION_PATTERNS = [
    re.compile(
        r"(忽略|ignore)\s*(以上|上面|above|previous|all)?\s*"
        r"(指令|instructions?|rules?|prompts?)",
        re.IGNORECASE,
    ),
    re.compile(r"System\s*:", re.IGNORECASE),
    re.compile(r"(你现在是|you are now|act as|pretend to be)\s", re.IGNORECASE),
    re.compile(r"(?i)(new\s+instructions?|system\s+prompt|you\s+are\s+now)"),
    re.compile(r"(?i)(forget\s+(everything|all|previous))"),
    re.compile(r"(?i)(disregard\s+(all\s+)?previous)"),
    re.compile(r"(?i)(act\s+as\s+(if\s+you\s+are|a|an))"),
    re.compile(r"(?i)(jailbreak|DAN\s+mode|developer\s+mode)"),
    re.compile(r"(\[/?(system|instruction|prompt)\])", re.IGNORECASE),
    re.compile(r"(?i)(override\s+(safety|security|filter|guidelines?))"),
]


def extract_json_from_text(text: str | None) -> dict:
    """Extract JSON object from text with multiple fallback strategies.

    Tries in order:
    1. Direct json.loads of the full text
    2. Extract from ```json...``` code block
    3. Find first { ... } brace-delimited object

    Args:
        text: Raw text that should contain a JSON object.

    Returns:
        Parsed JSON dict.

    Raises:
        json.JSONDecodeError: If no valid JSON can be extracted.
    """
    if not text or not text.strip():
        raise json.JSONDecodeError("Empty response", "", 0)

    # Strategy 1: Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from ```json...``` code block
    json_block_pattern = re.compile(r"```json\s*\n?(.*?)\n?\s*```", re.DOTALL)
    match = json_block_pattern.search(text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find first { ... } brace-delimited object
    brace_pattern = re.compile(r"\{[\s\S]*\}")
    match = brace_pattern.search(text)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(
        f"Could not extract JSON from response: {text[:200]}", text, 0
    )


def sanitize_llm_input(text: str, max_len: int = 8000) -> str:
    """Sanitize input text before sending to LLM.

    Truncates to max_len and removes characters that could interfere
    with JSON output parsing or prompt injection.

    Args:
        text: Raw input text.
        max_len: Maximum allowed length.

    Returns:
        Sanitized text safe for LLM input.
    """
    if not text:
        return ""
    text = text[:max_len]
    # Remove null bytes, replacement chars, and code block markers
    text = text.replace("\x00", "").replace("\ufffd", "")
    text = re.sub(r"```\w*\n?", "", text)

    # Detect and remove prompt injection patterns
    for pattern in INJECTION_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            logger.warning("prompt_injection_detected", extra={"pattern": pattern.pattern, "matches": matches})
            text = pattern.sub("", text)

    return text.strip()


def redact_pii_from_text(text: str) -> str:
    """Redact PII (Personally Identifiable Information) from text.

    Detects and masks: phone numbers, email addresses, ID card numbers,
    bank card numbers, and WeChat IDs.

    Args:
        text: Input text that may contain PII

    Returns:
        Text with PII replaced by masked versions
    """
    if not text:
        return text

    # 1. 手机号: 1[3-9]开头的11位数字
    def _redact_phone(m: re.Match) -> str:
        phone = m.group(0)
        return f"{phone[:3]}****{phone[7:]}"
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", _redact_phone, text)

    # 2. 邮箱
    def _redact_email(m: re.Match) -> str:
        local = m.group(1)
        domain = m.group(2)
        return f"{local[0]}***@{domain}"
    text = re.sub(r"([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", _redact_email, text)

    # 3. 身份证号: 18位，最后一位可能是X
    def _redact_id_card(m: re.Match) -> str:
        card = m.group(0)
        return f"{card[:3]}***********{card[14:]}"
    text = re.sub(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)", _redact_id_card, text)

    # 4. 银行卡号: 16-19位纯数字
    def _redact_bank_card(m: re.Match) -> str:
        card = m.group(0)
        return f"********{card[-4:]}"
    text = re.sub(r"(?<!\d)\d{16,19}(?!\d)", _redact_bank_card, text)

    # 5. 微信号: 6-20位，字母开头，字母数字下划线，谨慎匹配
    def _redact_wechat(m: re.Match) -> str:
        label = m.group(1)
        sep = m.group(2)
        wid = m.group(3)
        return f"{label}{sep}wx_***{wid[-2:]}"
    text = re.sub(r"(微信号|微信|wechat|WeChat)([:\s：]+)([a-zA-Z][a-zA-Z0-9_]{5,19})", _redact_wechat, text)

    return text
