"""NLG (Natural Language Generation) Service — generates natural language responses from DB data.

Given an NLU intent + slots, queries the database and generates a user-facing
response text. This replaces the placeholder template responses in the Voice API.

Supported intents:
  - schedule_query: Query today's events
  - promise_tracker: Query pending promises
  - relationship_status: Query person's relationship stage
  - action_suggestion: Suggest priority actions
  - todo_create: Confirm reminder creation
"""

import re
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.event import Event
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.models.todo import Todo
from eventlink.services.nlu_intent_classifier import VoiceIntent

# Beijing timezone
_TZ_CN = timezone(timedelta(hours=8))

# Stage labels
_STAGE_LABELS = {
    "new_connection": "新连接",
    "initial_contact": "初步接触",
    "value_exchange": "价值交换",
    "value_response": "价值回应",
    "deep_trust": "深度信任",
    "active_cooperation": "积极合作",
    "long_term_partner": "长期伙伴",
    "dormant": "休眠",
}


def _clean_concern(text: str) -> str:
    """Remove [type] prefix and person name prefix from concern text."""
    clean = re.sub(r'^\[[^\]]+\]\s*', '', str(text))
    clean = re.sub(r'^[^—]+—\s*', '', clean).strip()
    return clean


async def generate_nlu_response(
    session: AsyncSession,
    intent: VoiceIntent,
    slots: dict | None,
    user_id: str,
) -> str:
    """Generate a natural language response based on NLU intent and DB data.

    Args:
        session: DB session for querying data.
        intent: Classified NLU intent.
        slots: Extracted slots (e.g., person name, date).
        user_id: User ID for data isolation.

    Returns:
        Natural language response text.
    """
    slots = slots or {}

    if intent == VoiceIntent.SCHEDULE_QUERY:
        return await _response_schedule_query(session, user_id, slots)
    elif intent == VoiceIntent.PROMISE_TRACKER:
        return await _response_promise_tracker(session, user_id, slots)
    elif intent == VoiceIntent.RELATIONSHIP_STATUS:
        return await _response_relationship_status(session, user_id, slots)
    elif intent == VoiceIntent.ACTION_SUGGESTION:
        return await _response_action_suggestion(session, user_id)
    elif intent == VoiceIntent.TODO_CREATE:
        content = slots.get("content", "事项")
        return f"好的，已为您创建提醒：{content}。我会到时间提醒您。"
    elif intent == VoiceIntent.UNCLEAR:
        return "抱歉，我没有完全理解您的意思，能再说一遍吗？"
    elif intent == VoiceIntent.EXIT:
        return "好的，再见！"
    else:
        return "已收到您的指令。"


async def _response_schedule_query(
    session: AsyncSession, user_id: str, slots: dict
) -> str:
    """Generate response for schedule query intent."""
    today = datetime.now(_TZ_CN).date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=_TZ_CN)
    day_end = day_start + timedelta(days=1)

    result = await session.execute(
        select(Event)
        .where(Event.user_id == user_id)
        .where(Event.timestamp >= day_start)
        .where(Event.timestamp < day_end)
        .order_by(Event.timestamp.asc())
    )
    events = list(result.scalars().all())

    if not events:
        return "今天暂时没有安排。"

    lines = [f"今天您有{len(events)}条记录："]
    for evt in events:
        t = evt.timestamp.astimezone(_TZ_CN).strftime("%H:%M") if evt.timestamp else "??:??"
        lines.append(f"  {t} {evt.title}")

    return "\n".join(lines)


async def _response_promise_tracker(
    session: AsyncSession, user_id: str, slots: dict
) -> str:
    """Generate response for promise tracker intent."""
    person_name = slots.get("person", "")

    query = select(Todo).where(
        Todo.user_id == user_id,
        Todo.todo_type.in_(["promise", "care"]),
        Todo.status != "completed",
    )
    if person_name:
        query = query.where(Todo.title.contains(person_name))

    result = await session.execute(query.order_by(Todo.created_at.asc()))
    todos = list(result.scalars().all())

    if not todos:
        if person_name:
            return f"没有找到关于{person_name}的未完成承诺。"
        return "目前没有未完成的承诺。"

    lines = [f"您目前有{len(todos)}条未完成的承诺："]
    for t in todos[:5]:
        # Clean title: remove [type] prefix like [承诺], [关注]
        clean_title = re.sub(r'^\[[^\]]+\]\s*', '', t.title)
        lines.append(f"  · {clean_title}")

    lines.append("\n需要我帮您设置提醒吗？")
    return "\n".join(lines)


async def _response_relationship_status(
    session: AsyncSession, user_id: str, slots: dict
) -> str:
    """Generate response for relationship status intent."""
    person_name = slots.get("person", "")

    briefs_result = await session.execute(
        select(RelationshipBrief)
        .where(RelationshipBrief.user_id == user_id)
        .order_by(RelationshipBrief.last_updated_at.desc())
    )
    all_briefs = list(briefs_result.scalars().all())

    if not all_briefs:
        return "暂时还没有关系记录。先记录一次交流试试？"

    # Find matching brief
    matched_brief = None
    if person_name:
        for b in all_briefs:
            bname = (b.brief_data or {}).get("basic_info", {}).get("name", "")
            if person_name in bname or bname in person_name:
                matched_brief = b
                break
        if not matched_brief:
            return f"还没有{person_name}的关系记录。先和他/她交流一次试试？"
    else:
        matched_brief = all_briefs[0]

    data = matched_brief.brief_data or {}
    name = data.get("basic_info", {}).get("name", person_name or "对方")
    stage = matched_brief.relationship_stage or "new_connection"
    stage_cn = _STAGE_LABELS.get(stage, stage)
    last_int = data.get("last_interaction", {})
    summary = last_int.get("summary", "")[:40] if last_int else ""
    concerns = data.get("their_concerns", [])

    parts = [f"{name}目前处于「{stage_cn}」阶段。"]
    if summary:
        parts.append(f"你们最近一次互动是：{summary}")

    # Clean concern text
    concern_items = []
    for c in concerns[:2]:
        clean = _clean_concern(c)
        if clean:
            concern_items.append(clean)
    if concern_items:
        parts.append(f"他关心{concern_items[0]}")

    parts.append("建议近期跟进。")
    return " ".join(parts)


async def _response_action_suggestion(
    session: AsyncSession, user_id: str
) -> str:
    """Generate response for action suggestion intent."""
    # Priority: pending promises > pending care > pending followup
    result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id, Todo.status != "completed")
        .order_by(Todo.priority.asc(), Todo.created_at.asc())
        .limit(5)
    )
    todos = list(result.scalars().all())

    if not todos:
        return "目前没有待处理的事项，做得不错！"

    type_cn = {
        "promise": "承诺",
        "care": "关注",
        "help": "帮助",
        "followup": "跟进",
        "cooperation_signal": "合作信号",
        "risk": "风险",
    }

    lines = ["根据您的数据，建议优先处理："]
    today = datetime.now(_TZ_CN).date()
    for t in todos[:5]:
        atype = type_cn.get(t.todo_type, t.todo_type)
        # Clean title: remove [type] prefix like [承诺], [关注]
        clean_title = re.sub(r'^\[[^\]]+\]\s*', '', t.title)
        due_str = ""
        if t.due_date:
            try:
                d = t.due_date.date() if hasattr(t.due_date, 'date') else t.due_date
                if d >= today:
                    due_str = f"（截止:{d}）"
            except (ValueError, AttributeError):
                pass
        lines.append(f"  · [{atype}] {clean_title}{due_str}")

    return "\n".join(lines)
