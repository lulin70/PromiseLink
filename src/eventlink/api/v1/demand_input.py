"""F-36: Demand input API — voice/text one-line demand recording.

Users submit a single sentence (via voice or text) describing a need.
The system extracts demand keywords, attempts to associate with an
existing Entity, and stores the concern in Entity.properties.concern.
If no Entity matches, an orphan_demand record is created.
"""

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.config import get_settings
from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.services.llm_client import LLMClient

logger = get_logger("eventlink.api.demand_input")
router = APIRouter()

settings = get_settings()

# ── Pydantic Models ──


class DemandInputRequest(BaseModel):
    """Request body for demand input."""

    user_id: str = Field(..., min_length=1, description="用户ID")
    text: str = Field(..., min_length=1, max_length=2000, description="需求文本")
    source: str = Field(default="text", pattern="^(voice|text)$", description="输入来源: voice/text")


class ExtractedDemand(BaseModel):
    """Extracted demand information."""

    tag: str
    detail: str
    related_entity_id: str | None = None


class DemandInputResponse(BaseModel):
    """Response for demand input."""

    status: str
    demand_id: str
    extracted: ExtractedDemand


# ── LLM Prompt ──

_DEMAND_EXTRACTION_PROMPT = """你是一个需求信息提取助手。从用户的一句话中提取需求标签和需求详情。

规则：
1. tag：需求的核心类别，用2-4个字概括（如：装修、融资、招聘、培训）
2. detail：用户的具体需求描述，保留原始语义但精简表达
3. person_name：如果文本中提到了具体人名，提取出来；没有则为null

用户文本：{text}

请以JSON格式输出：
```json
{{"tag": "...", "detail": "...", "person_name": "..." 或 null}}
```"""


# ── Fallback keyword extraction ──

# Common demand keyword patterns
_DEMAND_KEYWORD_PATTERNS = [
    (r"装修|设计|翻新", "装修"),
    (r"融资|投资|资金|贷款", "融资"),
    (r"招聘|招人|人才|猎头", "招聘"),
    (r"培训|学习|课程|教育", "培训"),
    (r"律师|法律|合同|诉讼", "法律"),
    (r"保险|理财|税务", "财务"),
    (r"搬家|物流|运输", "物流"),
    (r"医疗|看病|体检|保健", "医疗"),
    (r"需要|想要|寻找|求|找|帮忙|推荐", "需求"),
]

# Common Chinese person name pattern (2-3 chars after common surname chars)
_PERSON_NAME_PATTERN = re.compile(
    r"([王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文][\u4e00-\u9fff]{1,2})"
)


def _fallback_extract(text: str) -> dict:
    """Extract demand info using keyword matching when LLM is unavailable.

    Returns a dict with tag, detail, and person_name fields.
    """
    tag = "其他"
    for pattern, label in _DEMAND_KEYWORD_PATTERNS:
        if re.search(pattern, text):
            tag = label
            break

    # Try to extract person name
    person_match = _PERSON_NAME_PATTERN.search(text)
    person_name = person_match.group(1) if person_match else None

    return {
        "tag": tag,
        "detail": text[:100],
        "person_name": person_name,
    }


# ── Endpoint ──


@router.post("/demands", response_model=DemandInputResponse)
async def create_demand(
    body: DemandInputRequest,
    session: AsyncSession = Depends(get_async_session),
    authenticated_user_id: str = Depends(get_optional_user_id),
) -> DemandInputResponse:
    """Accept a one-line demand input (voice or text).

    Extracts demand keywords via LLM, associates with an existing
    Entity if possible, and stores the concern. Falls back to keyword
    extraction if LLM is unavailable.
    """
    new_request_id()

    logger.info(
        "demand_input_received",
        user_id=body.user_id,
        text_preview=body.text[:100],
        source=body.source,
    )

    # Use authenticated user_id, fall back to body.user_id
    user_id = authenticated_user_id or body.user_id

    # ── Step 1: Extract demand info via LLM ──
    extracted = await _extract_demand(body.text)

    tag = extracted.get("tag", "其他")
    detail = extracted.get("detail", body.text[:100])
    person_name = extracted.get("person_name")

    # ── Step 2: Try to find a matching Entity ──
    related_entity = None
    if person_name:
        related_entity = await _find_entity_by_name(session, user_id, person_name)

    # ── Step 3: Build concern entry ──
    concern_entry = {
        "tag": tag,
        "detail": detail,
        "source": body.source,
        "created_at": datetime.now(UTC).isoformat(),
    }

    demand_id = str(uuid.uuid4())

    if related_entity:
        # Append concern to existing entity
        props = related_entity.properties or {}
        concerns = props.get("concern", [])
        concerns.append(concern_entry)
        props["concern"] = concerns
        related_entity.properties = props

        await session.flush()

        logger.info(
            "demand_linked_to_entity",
            demand_id=demand_id,
            entity_id=str(related_entity.id),
            tag=tag,
        )

        return DemandInputResponse(
            status="success",
            demand_id=demand_id,
            extracted=ExtractedDemand(
                tag=tag,
                detail=detail,
                related_entity_id=str(related_entity.id),
            ),
        )
    else:
        # Create a placeholder event first (FK constraint requires it)
        placeholder_event_id = str(uuid.uuid4())
        placeholder_event = Event(
            id=placeholder_event_id,
            user_id=user_id,
            event_type="manual",
            source="demand_input",
            title=f"[需求录入] {tag}",
            raw_text=body.text,
            status="completed",
        )
        session.add(placeholder_event)
        await session.flush()

        # Create orphan_demand entity record
        orphan_entity = Entity(
            id=demand_id,
            user_id=user_id,
            entity_type="topic",
            name=f"[需求] {tag}",
            canonical_name=f"[需求] {tag}",
            aliases=[],
            properties={
                "orphan_demand": True,
                "concern": [concern_entry],
                "original_text": body.text,
            },
            source_event_id=placeholder_event_id,
            confidence=0.5,
            status="provisional",
        )
        session.add(orphan_entity)
        await session.flush()

        logger.info(
            "demand_orphan_created",
            demand_id=demand_id,
            tag=tag,
        )

        return DemandInputResponse(
            status="success",
            demand_id=demand_id,
            extracted=ExtractedDemand(
                tag=tag,
                detail=detail,
                related_entity_id=None,
            ),
        )


async def _extract_demand(text: str) -> dict:
    """Extract demand info from text using LLM, with keyword fallback."""
    try:
        llm_client = LLMClient(config=settings)
        prompt = _DEMAND_EXTRACTION_PROMPT.format(text=text)
        result = await llm_client.call_json(prompt, max_tokens=200, temperature=0.1)

        # Validate required fields
        if "tag" in result and "detail" in result:
            return {
                "tag": str(result["tag"])[:20],
                "detail": str(result["detail"])[:200],
                "person_name": result.get("person_name"),
            }

        logger.warning("demand_llm_missing_fields", result=result)
        return _fallback_extract(text)

    except Exception as exc:
        logger.warning(
            "demand_llm_fallback",
            error=str(exc),
        )
        return _fallback_extract(text)


async def _find_entity_by_name(
    session: AsyncSession, user_id: str, name: str
) -> Entity | None:
    """Find an existing person Entity by name (exact or alias match)."""
    # Exact name match
    result = await session.execute(
        select(Entity).where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
            Entity.name == name,
            Entity.status.in_(["confirmed", "provisional"]),
        )
    )
    entity = result.scalar_one_or_none()
    if entity:
        return entity

    # Try alias match (JSON contains check)
    result = await session.execute(
        select(Entity).where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
            Entity.status.in_(["confirmed", "provisional"]),
        )
    )
    candidates = result.scalars().all()
    for candidate in candidates:
        aliases = candidate.aliases or []
        if name in aliases:
            return candidate

    return None
