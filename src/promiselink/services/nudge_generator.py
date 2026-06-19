"""Gentle nudge message generator for overdue their_promise todos.

This module was extracted from nlg_service.py (which is Pro-only) to keep
the basic edition's promise nudge feature self-contained.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.config import Settings
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo
from promiselink.services.llm_client import LLMClient

# Beijing timezone
_TZ_CN = timezone(timedelta(hours=8))

TEMPLATE_GENTLE_NUDGE = """你是一个商务关系助手。对方之前答应了一件事但还没兑现。
请生成一条温和、得体的催促消息。要求：
1. 不施加压力，不给对方造成不适感
2. 可以自然地提及之前的约定
3. 给对方一个台阶下（可能是忙忘了）
4. 控制在50字以内
5. 语气友好但不卑微

上下文：
- 对方姓名: {entity_name}
- 对方承诺内容: {promise_description}
- 承诺时间: {promise_due_date}
- 距今已过: {overdue_days}天
"""


async def generate_gentle_nudge(
    session: AsyncSession,
    todo: Todo,
    config: Settings,
) -> str:
    """Generate a gentle nudge message for an overdue their_promise.

    Args:
        session: DB session for looking up entity name.
        todo: The Todo object (their_promise type, overdue).
        config: Application settings for LLM client.

    Returns:
        Generated gentle nudge text (or fallback template if LLM fails).
    """
    from promiselink.core.logging import get_logger as _get_logger
    _logger = _get_logger("promiselink.nudge")

    # Look up entity name
    entity_name = "对方"
    if todo.related_entity_id:
        entity_result = await session.execute(
            select(Entity).where(Entity.id == todo.related_entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        if entity:
            entity_name = entity.name or entity.canonical_name or "对方"

    # Calculate overdue days
    today = datetime.now(_TZ_CN).date()
    overdue_days = 0
    if todo.due_date:
        try:
            d = todo.due_date.date() if hasattr(todo.due_date, 'date') else todo.due_date
            overdue_days = max(0, (today - d).days)
        except (ValueError, AttributeError):
            pass

    due_str = ""
    if todo.due_date:
        try:
            due_str = todo.due_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            due_str = "未设定"

    prompt = TEMPLATE_GENTLE_NUDGE.format(
        entity_name=entity_name,
        promise_description=todo.description or todo.title or "（未明确）",
        promise_due_date=due_str,
        overdue_days=overdue_days,
    )

    # Try LLM generation with fallback to template
    try:
        llm = LLMClient(config)
        message = await llm.generate(prompt, max_tokens=100)
        if message and len(message.strip()) > 5:
            return message.strip()[:120] + " — via PromiseLink"  # Cap at 120 chars + branding
    except Exception as exc:
        _logger.warning("gentle_nudge_llm_fallback", error=str(exc), exc_info=True)

    # Fallback template (no LLM available)
    return f"{entity_name}，之前提到的{todo.description or todo.title or '那件事'}不知进展如何？方便的话跟我同步一下情况，不着急。 — via PromiseLink"
