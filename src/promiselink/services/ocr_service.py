"""OCR (Optical Character Recognition) Service — image-to-text via Moka AI Vision API.

Uses Moka AI Vision API (OpenAI-compatible: POST /v1/chat/completions with image_url)
to extract text and structured data from images (e.g., business cards, documents).

Fallback: if Vision API fails, return raw text extraction attempt.
"""

import asyncio
import base64
import json
from dataclasses import dataclass, field

import httpx

from promiselink.config import Settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.ocr_service")

OCR_SYSTEM_PROMPT = """你是一个专业的OCR助手。请从图片中提取所有文字内容，并尝试结构化以下信息：
- names: 人名列表
- companies: 公司/组织名列表
- titles: 职位/头衔列表
- phone: 电话号码列表
- email: 邮箱地址列表
- notes: 其他备注信息

请以JSON格式返回，格式如下：
{
  "text": "图片中提取的完整文字",
  "structured_data": {
    "names": [],
    "companies": [],
    "titles": [],
    "phone": [],
    "email": [],
    "notes": []
  }
}

如果无法提取某项信息，对应字段返回空列表。只返回JSON，不要其他内容。"""


@dataclass
class OCRResult:
    """Result of OCR processing."""

    text: str
    structured_data: dict | None
    provider: str


class OCRService:
    """Async OCR service using Moka AI Vision API (OpenAI-compatible).

    Features:
        - httpx async client with retry
        - Base64 image encoding for Vision API
        - Structured data extraction (names, companies, titles, phone, email, notes)
        - Fallback: returns raw text if structured extraction fails
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.api_key: str = config.llm_api_key
        self.base_url: str = config.llm_base_url.rstrip("/")
        self.model: str = config.llm_model
        self.timeout: int = config.llm_timeout
        self.max_retries: int = config.llm_max_retries
        self.max_image_size: int = config.media_max_image_size_mb * 1024 * 1024

        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def recognize(
        self,
        image_bytes: bytes,
        filename: str = "image.jpg",
    ) -> OCRResult:
        """Recognize text from image bytes.

        Args:
            image_bytes: Raw image file bytes (jpg/png).
            filename: Original filename for content type detection.

        Returns:
            OCRResult with text, structured_data, and provider.

        Raises:
            ValueError: If image exceeds max size.
        """
        if len(image_bytes) > self.max_image_size:
            raise ValueError(
                f"Image file too large: {len(image_bytes)} bytes "
                f"(max {self.max_image_size} bytes)"
            )

        # Determine content type
        content_type = self._detect_content_type(filename, image_bytes)

        # Try Moka AI Vision API
        try:
            return await self._recognize_moka_ai(image_bytes, content_type)
        except Exception as exc:
            logger.warning("ocr_moka_ai_failed", error=str(exc))

        # Fallback: return raw text extraction attempt
        return OCRResult(
            text="",
            structured_data=None,
            provider="none",
        )

    async def _recognize_moka_ai(
        self, image_bytes: bytes, content_type: str
    ) -> OCRResult:
        """Recognize using Moka AI Vision API (OpenAI-compatible)."""
        url = f"{self.base_url}/chat/completions"

        # Encode image as base64
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{content_type};base64,{b64_image}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": OCR_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                        {
                            "type": "text",
                            "text": "请提取这张图片中的文字信息。",
                        },
                    ],
                },
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        }

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                client = self._get_client()
                response = await client.post(url, json=payload)
            except httpx.TimeoutException:
                last_error = RuntimeError(f"Moka AI OCR timeout after {self.timeout}s")
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "ocr_timeout_retrying",
                        attempt=attempt + 1,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise last_error
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Moka AI OCR HTTP error: {exc}") from exc

            if response.status_code == 429:
                last_error = RuntimeError("Moka AI OCR rate limited")
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Moka AI OCR API error: HTTP {response.status_code}"
                )

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Parse structured data from response
            text, structured_data = self._parse_ocr_response(content)

            logger.info(
                "ocr_moka_ai_completed",
                text_length=len(text),
                has_structured_data=structured_data is not None,
                attempt=attempt + 1,
            )

            return OCRResult(
                text=text,
                structured_data=structured_data,
                provider="moka_ai",
            )

        raise last_error  # type: ignore[misc]

    @staticmethod
    def _parse_ocr_response(content: str) -> tuple[str, dict | None]:
        """Parse OCR response to extract text and structured data.

        Args:
            content: Raw LLM response text.

        Returns:
            Tuple of (text, structured_data).
        """
        # Try direct JSON parse
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                text = data.get("text", "")
                structured_data = data.get("structured_data")
                return text, structured_data
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json...``` code block
        import re
        json_block_pattern = re.compile(r"```json\s*\n?(.*?)\n?\s*```", re.DOTALL)
        match = json_block_pattern.search(content)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                if isinstance(data, dict):
                    text = data.get("text", "")
                    structured_data = data.get("structured_data")
                    return text, structured_data
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } object
        brace_pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = brace_pattern.search(content)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    text = data.get("text", "")
                    structured_data = data.get("structured_data")
                    return text, structured_data
            except json.JSONDecodeError:
                pass

        # Fallback: return raw text, no structured data
        return content, None

    @staticmethod
    def _detect_content_type(filename: str, image_bytes: bytes) -> str:
        """Detect image content type from filename or magic bytes.

        Args:
            filename: Original filename.
            image_bytes: Image bytes for magic byte detection.

        Returns:
            MIME type string.
        """
        # Check filename extension first
        lower = filename.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".gif"):
            return "image/gif"

        # Fallback: check magic bytes
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if image_bytes[:2] == b"\xff\xd8":
            return "image/jpeg"

        # Default to jpeg
        return "image/jpeg"

    async def close(self) -> None:
        """Close the httpx async client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
