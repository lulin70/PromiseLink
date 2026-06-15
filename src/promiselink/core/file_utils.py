"""Shared file utilities for PromiseLink.

Consolidates duplicate file decoding and processing logic from API endpoints.
"""


def decode_content(content: bytes) -> str:
    """Decode bytes to string, trying UTF-8 first then GBK fallback.

    Args:
        content: Raw bytes to decode.

    Returns:
        Decoded string.
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("gbk")
