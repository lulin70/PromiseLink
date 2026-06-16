"""Dashboard Relationship Health & Care Reminders — F-G1: 关系健康诊断 + F-G3: 关怀提醒."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.event import Event

logger = get_logger("promiselink.api.dashboard.relationship_health")
router = APIRouter(tags=["Dashboard"])


# ── Pydantic Models ──


class HealthItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    stage: str
    stage_label: str
    stage_color: str
    health_score: float
    health_level: str  # "healthy" / "attention" / "at_risk"
    interaction_count: int
    last_interaction: str | None = None
    days_since_last: int | None = None
    pending_todos: int = 0
    pending_promises: int = 0
    suggestion: str = ""


class RelationshipHealthResponse(BaseModel):
    total_entities: int = 0
    healthy_count: int = 0
    attention_count: int = 0
    at_risk_count: int = 0
    items: list[HealthItem] = []
    summary_text: str = ""


class CareReminderItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    concern_category: str = ""
    concern_detail: str = ""
    care_type: str = ""           # "personal" / "business" / "mixed"
    relevance_score: float = 0.0
    source_event_title: str | None = None
    days_since_mentioned: int = 0
    suggested_action: str = ""
    care_icon: str = ""


class CareRemindersResponse(BaseModel):
    total: int = 0
    personal_items: list[CareReminderItem] = []
    business_items: list[CareReminderItem] = []
    summary_text: str = ""


# ── Constants ──


PERSONAL_KEYWORDS = {
    "family_milestone": [
        "孩子", "子女", "儿子", "女儿", "高考", "中考", "留学",
        "毕业", "入学", "升学", "开学", "录取", "考研", "考博",
        "结婚", "生子", "宝宝", "夫人", "太太", "先生",
        "满月", "百日", "周岁", "生日", "寿辰",
    ],
    "personal_health": [
        "手术", "住院", "体检", "康复", "生病", "身体", "健康",
    ],
    "hobby_interest": [
        "跑步", "马拉松", "健身", "高尔夫", "网球", "摄影",
        "茶", "咖啡", "酒", "旅行", "旅游", "书法", "画画",
    ],
    "project_milestone": [
        "上线", "发布", "融资", "A轮", "B轮", "搬", "迁",
        "扩张", "招人", "扩团队", "新产品",
    ],
    "life_change": [
        "搬家", "换房", "换城市", "回国", "离职", "跳槽", "创业",
    ],
}

CARE_TYPE_ICONS = {
    "family_milestone": "\U0001f3e0",   # house
    "personal_health": "\U0001febf",     # medical
    "hobby_interest": "\U0001f3c3",      # runner
    "project_milestone": "\U0001f3af",   # flag
    "life_change": "\U0001f4cb",         # clipboard
}

ACTION_TEMPLATES = {
    "family_milestone": "可以问一句{detail}怎么样了",
    "personal_health": "合适的时候问候一下{detail}的情况",
    "hobby_interest": "聊聊{detail}的近况，这是个很好的破冰话题",
    "project_milestone": "恭喜{detail}，可以问进展如何",
    "life_change": "{detail}后适应得怎么样",
    "default": "记得{detail}，可以在下次交流时提起",
}


# ── Helper functions ──


def _classify_care_type(detail_text: str) -> tuple[str, float]:
    """Classify a concern detail into a care type using keyword matching.

    Returns (care_type, relevance_score).
    """
    if not detail_text:
        return ("business", 0.0)

    best_type = "business"
    best_score = 0.0

    for ctype, keywords in PERSONAL_KEYWORDS.items():
        hit_count = sum(1 for kw in keywords if kw in detail_text)
        if hit_count > 0:
            score = min(1.0, hit_count * 0.35)
            if score > best_score:
                best_score = score
                best_type = ctype

    return (best_type, best_score)


def _generate_care_action(care_type: str, detail: str) -> str:
    """Generate a suggested action for a care reminder."""
    template = ACTION_TEMPLATES.get(care_type, ACTION_TEMPLATES["default"])
    try:
        return template.format(detail=detail[:50])
    except (KeyError, IndexError):
        return f"记得{detail[:30]}，可以适时关心"


# ── Endpoints ──


@router.get("/relationship-health", response_model=RelationshipHealthResponse)
async def get_relationship_health(
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> RelationshipHealthResponse:
    """F-G1: Scan all person entities and compute relationship health scores."""
    from promiselink.services.health_diagnostic import scan_all_entity_health

    rid = new_request_id()
    logger.info("rid=%s get_relationship_health user_id=%s limit=%d", rid, user_id, limit)

    items_data = await scan_all_entity_health(session, user_id, limit)

    healthy = sum(1 for i in items_data if i["health_level"] == "healthy")
    attention = sum(1 for i in items_data if i["health_level"] == "attention")
    at_risk = sum(1 for i in items_data if i["health_level"] == "at_risk")

    # Generate summary text
    total = len(items_data)
    if total == 0:
        summary = "暂无联系人数据，记录第一次互动后即可查看关系健康度。"
    elif at_risk > 0:
        summary = f"共{total}位联系人，{at_risk}位需要立即关注，{attention}位建议保持互动。"
    elif attention > 0:
        summary = f"共{total}位联系人，整体健康。{attention}位可适当增加互动频率。"
    else:
        summary = f"共{total}位联系人，关系状态良好，继续保持！"

    items = [HealthItem(**item) for item in items_data]

    return RelationshipHealthResponse(
        total_entities=total,
        healthy_count=healthy,
        attention_count=attention,
        at_risk_count=at_risk,
        items=items,
        summary_text=summary,
    )


@router.get("/care-reminders", response_model=CareRemindersResponse)
async def get_care_reminders(
    limit: int = Query(10, ge=1, le=30),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> CareRemindersResponse:
    """F-G3: Scan entity concerns and identify personal care reminders."""
    from datetime import date as _date

    rid = new_request_id()
    logger.info("rid=%s get_care_reminders user_id=%s limit=%d", rid, user_id, limit)

    today = _date.today()

    # Get all person entities with concerns
    entity_q = select(Entity).where(
        Entity.user_id == user_id,
        Entity.entity_type == "person",
        Entity.status.in_(["provisional", "confirmed"]),
    )
    entity_result = await session.execute(entity_q)
    entities = entity_result.scalars().all()

    # Batch-fetch source event titles to avoid N+1 queries
    source_event_ids = [e.source_event_id for e in entities if e.source_event_id]
    event_title_map: dict[str, str] = {}
    if source_event_ids:
        evt_result = await session.execute(
            select(Event.id, Event.title).where(Event.id.in_(source_event_ids))
        )
        event_title_map = {str(row[0]): row[1] for row in evt_result.fetchall()}

    personal_items = []
    business_items = []

    for entity in entities:
        props = entity.properties or {}
        concerns = props.get("concern", [])
        if not concerns or not isinstance(concerns, list):
            continue

        # Find source event title from batch-fetched map
        source_title = event_title_map.get(str(entity.source_event_id)) if entity.source_event_id else None

        # Days since entity created (proxy for when mentioned)
        days_since = 999
        if entity.created_at:
            if isinstance(entity.created_at, datetime):
                days_since = (today - entity.created_at.date()).days
            else:
                days_since = (today - entity.created_at).days

        # Company
        company = None
        basic = props.get("basic", {})
        if isinstance(basic, dict):
            company = basic.get("company")

        # Process each concern entry
        best_personal = None  # Keep only the best personal match per entity

        for concern_entry in concerns:
            if isinstance(concern_entry, dict):
                category = concern_entry.get("category", "")
                detail = concern_entry.get("detail", "")
            elif isinstance(concern_entry, str):
                detail = concern_entry
                category = ""
            else:
                continue

            if not detail:
                continue

            care_type, relevance = _classify_care_type(detail)

            icon = CARE_TYPE_ICONS.get(care_type, "\U0001f4a1")
            action = _generate_care_action(care_type, detail)

            item_data = {
                "entity_id": str(entity.id),
                "name": entity.name,
                "company": company,
                "concern_category": category,
                "concern_detail": detail,
                "care_type": care_type,
                "relevance_score": round(relevance, 2),
                "source_event_title": source_title,
                "days_since_mentioned": days_since,
                "suggested_action": action,
                "care_icon": icon,
            }

            if care_type != "business":
                # Personal/mixed care type
                if best_personal is None or relevance > best_personal.get("relevance_score", 0):
                    best_personal = item_data
            else:
                # Business concern - add to business list (limit later)
                business_items.append(CareReminderItem(**item_data))

        if best_personal:
            personal_items.append(CareReminderItem(**best_personal))

    # Sort personal by relevance * recency
    personal_items.sort(
        key=lambda c: c.relevance_score * (1.0 / (c.days_since_mentioned + 1)),
        reverse=True,
    )

    # Sort business by relevance
    business_items.sort(key=lambda c: c.relevance_score, reverse=True)
    business_items = business_items[:5]

    total = len(personal_items) + len(business_items)

    # Summary text
    if total == 0:
        summary = "暂无关怀提醒。多记录互动，AI会发现更多值得关心的细节。"
    elif len(personal_items) > 0:
        names = [p.name for p in personal_items[:3]]
        summary = f"发现{len(personal_items)}条个人关怀点：{'、'.join(names)}等。合适的时机表达关心，让关系更有温度。"
    else:
        summary = f"关注了{len(business_items)}位联系人的业务关切，继续深挖可能发现更多个人层面的关怀点。"

    return CareRemindersResponse(
        total=total,
        personal_items=personal_items[:limit],
        business_items=business_items,
        summary_text=summary,
    )
