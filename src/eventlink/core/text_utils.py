"""Shared text and JSON utilities for EventLink services.

Consolidates duplicate logic from entity_extractor, todo_generator, and llm_client.
"""

import json
import logging
import re

logger = logging.getLogger("eventlink.text_utils")

# Prompt injection detection patterns
INJECTION_PATTERNS = [
    re.compile(r"(忽略|ignore)\s*(以上|上面|above|previous)\s*(指令|instructions?|rules?)", re.IGNORECASE),
    re.compile(r"System\s*:", re.IGNORECASE),
    re.compile(r"(你现在是|you are now|act as|pretend to be)\s", re.IGNORECASE),
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
