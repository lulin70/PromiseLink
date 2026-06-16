"""Event title generation — uses LLM to generate concise event titles.

Extracted from event_pipeline.py to break the circular dependency:
event_pipeline → steps → event_pipeline.
"""

from promiselink.core.logging import get_logger
from promiselink.services.llm_client import LLMClient

logger = get_logger("promiselink.title_generator")


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
        title = response.strip().strip('"').strip("'")
        # Truncate to 50 chars for safety
        if len(title) > 50:
            title = title[:47] + "..."
        return title if title else None
    except Exception as exc:
        logger.warning("title_generation_failed", error=str(exc))
        return None
