"""Event title generation — uses LLM to generate concise event titles.

Extracted from event_pipeline.py to break the circular dependency:
event_pipeline → steps → event_pipeline.
"""

import re

from promiselink.core.logging import get_logger
from promiselink.services.llm_client import LLMClient

logger = get_logger("promiselink.title_generator")

# LLM 思考过程泄露标签（Claude/OpenAI o-series 等推理模型可能返回）
# <think>...</think> — DeepSeek-R1/通义千问等推理模型思考过程
# <RichMediaReference>...</RichMediaReference> — 微信小程序转发消息中的媒体引用标签
# 必须先剥离标签再截断，否则截断后标签未闭合会污染 title
_LLM_TAG_PATTERNS = [
    re.compile(r"<think>.*?</think>", re.DOTALL),
    re.compile(r"<think>.*", re.DOTALL),  # 未闭合的 <think>（被截断）
    re.compile(r"</think>", re.DOTALL),  # 残留的闭合标签
    re.compile(r"<RichMediaReference>.*?</RichMediaReference>", re.DOTALL),
    re.compile(r"<RichMediaReference>.*", re.DOTALL),
    re.compile(r"</RichMediaReference>", re.DOTALL),
]


def _strip_llm_tags(text: str) -> str:
    """Remove LLM thinking-process tags and media reference tags from text.

    Some LLM models (e.g. DeepSeek-R1/V4) return
    `` thinking...</think>`` reasoning blocks before the actual answer.
    WeChat mini-app forwarded messages may contain ``<RichMediaReference>``
    tags. These must be stripped before storing as event title.
    """
    cleaned = text
    for pattern in _LLM_TAG_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


async def generate_event_title(llm_client: LLMClient, raw_text: str) -> str | None:
    """Use LLM to generate a concise event title from raw text.

    Returns a title string (max 50 chars) or None on failure.
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return None

    prompt = (
        "请从以下交流记录中提取一个简洁的事件标题（不超过30个字），"
        "格式为「活动类型 - 关键人物/主题」，例如「投资对接会 - 盛恒资本李总」或「下午茶交流 - 智谱AI张总」。"
        "只输出标题，不要解释。\n\n"
        f"交流记录：\n{raw_text[:500]}"
    )

    try:
        response = await llm_client.generate(
            prompt=prompt,
            max_tokens=60,
        )
        # Strip LLM thinking-process tags (<think>...</think>) and media
        # reference tags before any other processing. Some reasoning models
        # (Claude/DeepSeek-R1) leak thinking blocks into the response.
        title = _strip_llm_tags(response)
        title = title.strip().strip('"').strip("'").strip()
        # Truncate to 50 chars for safety
        if len(title) > 50:
            title = title[:47] + "..."
        return title if title else None
    except Exception as exc:  # External API — keep broad catch for resilience
        logger.warning("title_generation_failed", error=str(exc))
        return None
