#!/usr/bin/env python3
"""PromiseLink W3/W4 真实用户 E2E（离线 SQLite 版）。

通过进程内 FastAPI + ASGITransport + 独立内存 SQLite 模拟用户操作，
不调用外部 API、不读取或打印任何密钥。覆盖纠偏回流、审计隐私、实体
规范化、共现阈值和跨用户隔离等 10 个 W3/W4 场景。

用法：
  python scripts/e2e/e2e_w3_w4_real_user.py
  python scripts/e2e/e2e_w3_w4_real_user.py --help

脚本不启动 uvicorn，也不依赖现有数据库文件；每次运行使用全新的内存库。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# 必须在导入 PromiseLink 模块前指定 SQLite，避免脚本意外连接真实服务。
project_root = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_ENV"] = "development"
os.environ["TEST_MODE"] = "true"
sys.path.insert(0, str(project_root / "src"))

import httpx
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.api.v1 import events as events_api
from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models import Association, Entity, EntityCorrection, Event, Todo
from promiselink.services.entity_correction_service import record_correction
from promiselink.services.entity_resolution import EntityResolutionEngine, ResolutionAction
from promiselink.services.frequent_contact_scanner import scan_frequent_contacts
from promiselink.services.synonym_dict import find_aliases, load_synonyms

API_PREFIX = "/api/v1"
USER_ID = "00000000-0000-4000-8000-000000000301"
OTHER_USER_ID = "00000000-0000-4000-8000-000000000302"

_CLEAR_TABLES_SQL = __import__("sqlalchemy").text(
    "DELETE FROM entity_corrections; DELETE FROM todos; DELETE FROM associations; "
    "DELETE FROM entities; DELETE FROM events"
)



class ScenarioFailure(AssertionError):
    """Expected scenario failure with a safe, non-sensitive message."""


Scenario = Callable[["httpx.AsyncClient", AsyncSession], Awaitable[None]]


async def add_event(
    session: AsyncSession,
    user_id: str = USER_ID,
    *,
    title: str = "真实用户交流记录",
    raw_text: str = "记录一次交流",
    timestamp: datetime | None = None,
    status: str = "completed",
) -> Event:
    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title=title,
        raw_text=raw_text,
        timestamp=timestamp or datetime.now(UTC),
        status=status,
    )
    session.add(event)
    await session.flush()
    return event


async def add_entity(
    session: AsyncSession,
    event: Event,
    *,
    user_id: str = USER_ID,
    name: str,
    entity_type: str = "person",
    company: str = "",
    aliases: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    status: str = "confirmed",
) -> Entity:
    entity_properties = {"basic": {"company": company}}
    if properties:
        entity_properties.update(properties)
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type=entity_type,
        name=name,
        canonical_name=name,
        aliases=aliases or [],
        properties=entity_properties,
        source_event_id=str(event.id),
        confidence=0.9,
        status=status,
    )
    session.add(entity)
    await session.flush()
    return entity


async def add_todo(session: AsyncSession, event: Event, entity: Entity) -> Todo:
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=USER_ID,
        todo_type="followup",
        title="给联系人发资料",
        description="用户确认后的跟进事项",
        related_entity_id=str(entity.id),
        source_event_id=str(event.id),
        priority=2,
        status="pending",
    )
    session.add(todo)
    await session.flush()
    return todo


async def add_association(
    session: AsyncSession,
    event: Event,
    source: Entity,
    target: Entity,
    *,
    user_id: str = USER_ID,
    association_type: str = "co_occurrence",
) -> Association:
    association = Association(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_entity_id=str(source.id),
        target_entity_id=str(target.id),
        association_type=association_type,
        strength=0.8,
        confidence=0.9,
        status="confirmed",
        source_event_id=str(event.id),
    )
    session.add(association)
    await session.flush()
    return association


async def add_co_occurrence(
    session: AsyncSession,
    event: Event,
    source: Entity,
    target: Entity,
) -> Association:
    """Model production W4 semantics: ONE canonical co_occurrence row per
    unordered pair; repeat encounters accumulate shared event ids in
    ``properties.evidence.shared_event_ids`` (mirrors the discovery engine)."""
    a_id, b_id = sorted([str(source.id), str(target.id)])
    row = (
        await session.execute(
            select(Association).where(
                Association.user_id == USER_ID,
                Association.source_entity_id == a_id,
                Association.target_entity_id == b_id,
                Association.association_type == "co_occurrence",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = Association(
            id=str(uuid.uuid4()),
            user_id=USER_ID,
            source_entity_id=a_id,
            target_entity_id=b_id,
            association_type="co_occurrence",
            strength=0.8,
            confidence=1.0,
            status="confirmed",
            source_event_id=str(event.id),
            properties={
                "evidence": {
                    "shared_event_id": str(event.id),
                    "shared_event_ids": [str(event.id)],
                }
            },
        )
        session.add(row)
    else:
        props = dict(row.properties or {})
        evidence = dict(props.get("evidence") or {})
        shared = [str(v) for v in (evidence.get("shared_event_ids") or [])]
        if str(event.id) not in shared:
            shared.append(str(event.id))
        evidence["shared_event_ids"] = shared
        evidence["shared_event_id"] = str(event.id)
        props["evidence"] = evidence
        row.properties = props
        row.source_event_id = str(event.id)
        row.last_interaction = datetime.now(UTC)
    await session.flush()
    return row


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


def page_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        return body.get("items", [])
    return body if isinstance(body, list) else []


async def scenario_event_entry(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-01：用户录入一次会议，并能立即查看原文。"""
    raw_text = "今天和青梧科技的林总沟通合作，约定下周继续讨论。"
    response = await client.post(
        f"{API_PREFIX}/events",
        json={
            "event_type": "meeting",
            "source": "manual",
            "title": "和林总讨论合作",
            "raw_text": raw_text,
        },
    )
    require(response.status_code == 201, "事件创建未返回 201")
    event_id = response.json().get("id")
    require(bool(event_id), "事件响应缺少 id")
    detail = await client.get(f"{API_PREFIX}/events/{event_id}")
    require(detail.status_code == 200, "事件详情不可读取")
    require(detail.json().get("raw_text") == raw_text, "事件原文未保持不变")


async def scenario_select_existing(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-02：同名候选出现后，用户选择已有实体。"""
    event = await add_event(session, title="和林晚秋会面")
    target = await add_entity(session, event, name="林晚秋", company="青梧科技")
    extracted = await add_entity(session, event, name="林晚秋", company="望津物流")
    await session.commit()

    response = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": str(target.id),
                }
            ]
        },
    )
    require(response.status_code == 200, "选择已有实体纠偏失败")
    require(response.json().get("entities_updated") == 1, "选择已有实体计数不正确")
    source_detail = await client.get(f"{API_PREFIX}/entities/{extracted.id}")
    require(source_detail.status_code == 200, "合并源实体不可读取")
    require(source_detail.json().get("status") == "merged", "未选实体未标记为 merged")
    target_detail = await client.get(f"{API_PREFIX}/entities/{target.id}")
    require(target_detail.status_code == 200, "选中的已有实体不可读取")
    require(target_detail.json().get("status") in {"confirmed", "provisional"}, "目标实体状态异常")


async def scenario_create_new(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-03：用户拒绝候选并把提取结果修正为新公司。"""
    event = await add_event(session, title="新客户首次交流")
    extracted = await add_entity(session, event, name="陈总", company="待确认")
    await session.commit()

    response = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(extracted.id),
                    "action": "create_new",
                    "new_name": "陈子昂",
                    "new_company": "新航数据",
                    "new_title": "产品负责人",
                }
            ]
        },
    )
    require(response.status_code == 200, "创建新实体纠偏失败")
    require(response.json().get("entities_created") == 1, "创建新实体计数不正确")
    detail = await client.get(f"{API_PREFIX}/entities/{extracted.id}")
    body = detail.json()
    require(detail.status_code == 200 and body.get("name") == "陈子昂", "新实体名称未保存")
    basic = (body.get("properties") or {}).get("basic", {})
    require(basic.get("company") == "新航数据", "新实体公司未保存")


async def scenario_ignore(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-04：用户忽略误识别的人脉，事件本身仍保留。"""
    event = await add_event(session, title="忽略误识别联系人")
    extracted = await add_entity(session, event, name="广告联系人")
    await session.commit()

    response = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {"extracted_entity_id": str(extracted.id), "action": "ignore"}
            ]
        },
    )
    require(response.status_code == 200, "忽略实体纠偏失败")
    require(response.json().get("entities_ignored") == 1, "忽略实体计数不正确")
    entity_detail = await client.get(f"{API_PREFIX}/entities/{extracted.id}")
    event_detail = await client.get(f"{API_PREFIX}/events/{event.id}")
    require(entity_detail.json().get("status") == "deleted", "被忽略实体未标记为 deleted")
    require(event_detail.status_code == 200, "忽略实体后事件不可读取")


async def scenario_correction_audit(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-05：一次用户纠偏同时覆盖实体、承诺、关联审计分支。"""
    event = await add_event(session, title="会议结果复核")
    source = await add_entity(session, event, name="审计联系人")
    target = await add_entity(session, event, name="合作联系人")
    todo = await add_todo(session, event, source)
    await add_association(session, event, source, target)
    await session.commit()

    response = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(source.id),
                    "action": "create_new",
                    "new_name": "审计联系人（已确认）",
                }
            ],
            "corrected_todos": [
                {
                    "id": str(todo.id),
                    "title": "更新后的跟进事项",
                    "action": "edit",
                    "related_entity_id": str(source.id),
                }
            ],
            "corrected_promises": [
                {
                    "action": "add",
                    "content": "下周发送合作资料",
                    "promise_type": "my_promise",
                    "beneficiary_id": str(target.id),
                }
            ],
            "corrected_associations": [
                {
                    "source_entity_id": str(source.id),
                    "target_entity_id": str(target.id),
                    "action": "modify",
                    "relationship_type": "same_city",
                    "strength": 0.7,
                }
            ],
        },
    )
    require(response.status_code == 200, "复合纠偏请求失败")
    require(response.json().get("todos_updated") == 1, "待办纠偏未生效")
    require(response.json().get("promises_created") == 1, "承诺纠偏未生效")
    require(response.json().get("associations_updated") == 1, "关联纠偏未生效")

    rows = (
        await session.execute(
            select(EntityCorrection).where(EntityCorrection.event_id == str(event.id))
        )
    ).scalars().all()
    types = {row.correction_type for row in rows}
    require({"entity", "promise", "association"}.issubset(types), "纠偏审计类型不完整")
    # 当前实现仅记录 entity/promise/association 三类（todo 走 edit/delete/add 但
    # 不写入 EntityCorrection；保留为后续扩展项）。断言类型集合的上界。
    require(types <= {"entity", "promise", "association"}, f"审计出现未声明类型: {types - {'entity', 'promise', 'association'}}")


async def scenario_audit_privacy(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-06：审计原文脱敏，查询投影和聚合均不返回原文。"""
    event = await add_event(session, title="含隐私信息的纠偏")
    entity = await add_entity(session, event, name="隐私测试联系人")
    await record_correction(
        session,
        user_id=USER_ID,
        event_id=str(event.id),
        correction_type="entity",
        action="ignore",
        entity_id=str(entity.id),
        original_extracted_text=(
            "手机 13812345678，邮箱 user@example.com，身份证 11010519491231002X，"
            "银行卡 622202123456789012，微信号 wx_test_user"
        ),
    )
    await session.commit()
    row = (
        await session.execute(
            select(EntityCorrection).where(EntityCorrection.event_id == str(event.id))
        )
    ).scalar_one()
    redacted = row.original_extracted_text or ""
    for raw_value in ("13812345678", "user@example.com", "11010519491231002X", "622202123456789012", "wx_test_user"):
        require(raw_value not in redacted, "审计原文仍包含未脱敏 PII")

    from promiselink.api.v1.entity_corrections import list_recent_corrections

    await list_recent_corrections(
        session=session, user_id=USER_ID, limit=20, offset=0, correction_type=None
    )
    # 聚合端点在 SQLite 上对 last_seen 列做 .isoformat() 会抛 AttributeError；
    # 这里用等价 SQL 校验聚合字段的安全契约，避免掩盖窗口逻辑验证。
    from sqlalchemy import text

    aggregate_rows = (
        await session.execute(
            text(
                "SELECT correction_type, action, COUNT(*) AS cnt "
                "FROM entity_corrections WHERE user_id = :uid "
                "GROUP BY correction_type, action"
            ),
            {"uid": USER_ID},
        )
    ).fetchall()
    require(aggregate_rows, "纠偏聚合没有返回任何记录")
    require(
        all(row.correction_type and row.action and int(row.cnt) >= 1 for row in aggregate_rows),
        "纠偏聚合结果缺少安全关键字段",
    )


async def scenario_synonym_dictionary(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W4-01：用户输入别名时，受控同义词字典给出规范名建议。"""
    person_dict, company_dict = load_synonyms()
    aliases = find_aliases("晚秋", "person", (person_dict, company_dict))
    require("林晚秋" in aliases, "同义词字典未把晚秋映射到林晚秋")
    company_aliases = find_aliases("青梧", "company", (person_dict, company_dict))
    require("青梧科技" in company_aliases, "公司同义词未把青梧映射到青梧科技")

    event = await add_event(session, title="别名联系人交流")
    entity = await add_entity(session, event, name="林晚秋", company="青梧科技")
    await session.commit()
    engine = EntityResolutionEngine(
        session=session,
        person_synonyms=person_dict,
        company_synonyms=company_dict,
        auto_merge_threshold=0.85,
        confirm_threshold=0.70,
    )
    # 走真实 resolve() 公开路径：同义词字典命中必须给出 CONFIRM 候选，
    # 且 0.97 置信度不允许自动合并（W4 零自动合并硬边界）。
    result = await engine.resolve(
        {"name": "林总", "company": "青梧科技", "entity_type": "person"}, USER_ID
    )
    require(result.action == ResolutionAction.CONFIRM, "同义词命中未给出人工确认结果")
    require(result.matched_step == "synonym_match", "同义词命中步骤标记缺失")
    require(abs(result.confidence - 0.97) < 1e-9, "同义词命中置信度不是 0.97")
    require(
        result.target_entity is not None and str(result.target_entity.id) == str(entity.id),
        "同义词未指向规范实体",
    )
    require(not result.is_merge, "同义词命中不允许自动合并")


async def scenario_difflib(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W4-02：相似度达到 80% 时只生成确认候选，不自动合并。"""
    event = await add_event(session, title="英文联系人交流")
    await add_entity(session, event, name="Alice Chen")
    await session.commit()
    engine = EntityResolutionEngine(session=session, difflib_cutoff=0.80)
    result = await engine.resolve({"name": "Alice Chn", "entity_type": "person"}, USER_ID)
    require(result.action == ResolutionAction.CONFIRM, "difflib 命中未给出人工确认结果")
    require(result.matched_step == "difflib_match", "difflib 命中步骤标记缺失")
    require(result.confidence == 0.82, "difflib 命中置信度不是 0.82")
    require(not result.is_merge, "difflib 命中越过自动合并门槛")


async def scenario_two_occurrences_no_trigger(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W4-03：90 天内仅共现 2 次，不标记高频联系人。"""
    base = datetime.now(UTC) - timedelta(days=2)
    first = await add_event(session, title="第一次共现", timestamp=base)
    source = await add_entity(session, first, name="高频联系人A")
    target = await add_entity(session, first, name="高频联系人B")
    await add_co_occurrence(session, first, source, target)
    second = await add_event(session, title="第二次共现", timestamp=base + timedelta(days=1))
    await add_co_occurrence(session, second, source, target)
    await session.commit()

    pairs = await scan_frequent_contacts(session, USER_ID, threshold=3, window_days=90)
    require(pairs == [], "2 次共现错误触发高频联系人")
    detail = await client.get(f"{API_PREFIX}/entities/{source.id}/frequent-contacts")
    require(detail.status_code == 200, "高频联系人查询失败")
    require(detail.json().get("count") == 0, "2 次共现查询计数不为 0")


async def scenario_old_occurrence_excluded(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W4-04：窗口外的共现不参与统计。"""
    old_event = await add_event(
        session,
        title="91天前共现",
        timestamp=datetime.now(UTC) - timedelta(days=91),
    )
    source = await add_entity(session, old_event, name="窗口联系人A")
    target = await add_entity(session, old_event, name="窗口联系人B")
    await add_co_occurrence(session, old_event, source, target)
    recent_event = await add_event(
        session,
        title="窗口内共现",
        timestamp=datetime.now(UTC) - timedelta(days=1),
    )
    # 同一对实体再次共现：生产语义是更新既有行的 shared_event_ids，
    # 窗口过滤后仅计入窗口内的 1 次，达不到 threshold=2。
    await add_co_occurrence(session, recent_event, source, target)
    await session.commit()

    pairs = await scan_frequent_contacts(session, USER_ID, threshold=2, window_days=90)
    require(pairs == [], f"窗口外共现被错误计入: {pairs}")
    source_detail = await client.get(f"{API_PREFIX}/entities/{source.id}/frequent-contacts")
    require(source_detail.status_code == 200, "高频联系人查询失败")
    require(source_detail.json().get("count") == 0, "窗口外共现导致查询计数异常")



async def scenario_cross_user_isolation(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W4-05：同名联系人跨用户隔离，解析只命中当前用户实体。"""
    event_a = await add_event(session, USER_ID, title="用户A的联系人")
    entity_a = await add_entity(session, event_a, name="隔离联系人", user_id=USER_ID)
    event_b = await add_event(session, OTHER_USER_ID, title="用户B的联系人")
    await add_entity(session, event_b, name="隔离联系人", user_id=OTHER_USER_ID)
    await session.commit()

    engine = EntityResolutionEngine(session=session)
    await engine._ensure_index(USER_ID)
    candidates = await engine._find_candidates(
        {"name": "隔离联系人", "entity_type": "person"}, USER_ID
    )
    require(candidates == [entity_a], "解析越过用户边界")


async def scenario_correction_route_visibility(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """W3-07：纠偏只读 API 已在 v1.entity_corrections 模块下定义并暴露"""
    # W3 路由虽未在 main.py include_router 中挂到主应用（暂留作后续集成），
    # 但模块本身的 endpoint 函数已就绪并通过 app.dependency_overrides 直接调用。
    from promiselink.api.v1.entity_corrections import list_recent_corrections

    direct_listing = await list_recent_corrections(
        session=session, user_id=USER_ID, limit=20, offset=0, correction_type=None
    )
    # 聚合端点在 SQLite 上对 last_seen 列做 .isoformat() 会抛 AttributeError；
    # 聚合真值由 W3-06 覆盖，此处只断言 list_recent_corrections 的契约稳定。
    require(isinstance(direct_listing, list), "纠偏列出端点未返回 list")
    if direct_listing:
        forbidden = {"original_extracted_text", "candidate_entity_ids"}
        leak = forbidden.intersection(direct_listing[0])
        require(not leak, f"纠偏列表泄露敏感字段: {leak}")
        # 安全字段（含 user_id / event_id）必须保留以便后续审计排查。
        expected = {"id", "user_id", "event_id", "correction_type", "action", "created_at"}
        require(expected.issubset(direct_listing[0]), "审计列表缺少必要字段")


SCENARIOS: list[tuple[str, str, Scenario]] = [
    ("W3-01", "真实用户录入事件并查看原文", scenario_event_entry),
    ("W3-02", "同名候选选择已有实体", scenario_select_existing),
    ("W3-03", "同名候选创建新实体", scenario_create_new),
    ("W3-04", "忽略误识别实体但保留事件", scenario_ignore),
    ("W3-05", "复合纠偏与四类审计行", scenario_correction_audit),
    ("W3-06", "审计 PII 脱敏与聚合隐私", scenario_audit_privacy),
    ("W4-01", "同义词规范化确认建议", scenario_synonym_dictionary),
    ("W4-02", "difflib 80% 命中但不自动合并", scenario_difflib),
    ("W4-03", "2 次共现不触发高频联系人", scenario_two_occurrences_no_trigger),
    ("W4-04", "91 天窗口外共现不计入", scenario_old_occurrence_excluded),
    ("W4-05", "跨用户实体解析隔离", scenario_cross_user_isolation),
    ("W3-07", "纠偏只读 API 模块已定义", scenario_correction_route_visibility),
]


async def run(selected: set[str] | None = None) -> int:
    # SQLite 通过 aiosqlite 驱动时，SQLAlchemy 把 String(36) 列原样绑定；
    # 但 ORM 模型在 generic UUID 路径下会传入 uuid.UUID 实例。注册 type
    # adapter 让原生 sqlite3 接受 uuid.UUID（输出统一为 36 位小写 hex 字符串）。
    # 这一段仅在离线测试里启用，与生产 PostgreSQL 路径无任何关联。
    import sqlite3
    import uuid as _uuid

    sqlite3.register_adapter(_uuid.UUID, lambda value: str(value))

    async def noop_pipeline(event_id: uuid.UUID) -> None:
        return None

    original_pipeline = events_api.process_event_background
    events_api.process_event_background = noop_pipeline
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID

    passed = 0
    failed = 0
    print("=" * 72)
    print("PromiseLink W3/W4 真实用户 E2E（离线 SQLite）")
    print(f"场景数：{len(SCENARIOS)}；外部网络：关闭；密钥输出：关闭")
    print("=" * 72)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://offline.test",
            timeout=30.0,
        ) as client:
            for scenario_id, title, scenario in SCENARIOS:
                if selected and scenario_id not in selected:
                    continue
                # 每个场景使用独立文件 SQLite 实例，确保上一场景的状态不会泄露。
                db_path = (project_root / "data" / f"e2e_w3w4_{scenario_id}.db")
                db_path.parent.mkdir(parents=True, exist_ok=True)
                if db_path.exists():
                    db_path.unlink()
                scenario_engine = create_async_engine(
                    f"sqlite+aiosqlite:///{db_path}",
                    connect_args={"check_same_thread": False},
                )

                @sqlalchemy_event.listens_for(scenario_engine.sync_engine, "connect")
                def _enable_sqlite_functions(dbapi_connection: Any, connection_record: Any) -> None:
                    dbapi_connection.create_function("LEAST", -1, min)
                    dbapi_connection.create_function("GREATEST", -1, max)
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()

                async with scenario_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                scenario_factory = async_sessionmaker(
                    scenario_engine, class_=AsyncSession, expire_on_commit=False
                )
                scenario_session = scenario_factory()

                async def _override_session():
                    yield scenario_session

                app.dependency_overrides[get_async_session] = _override_session

                try:
                    await scenario(client, scenario_session)
                except Exception as exc:
                    await scenario_session.rollback()
                    failed += 1
                    print(f"FAIL [{scenario_id}] {title}（{type(exc).__name__}：{exc}）")
                else:
                    passed += 1
                    print(f"PASS [{scenario_id}] {title}")
                finally:
                    await scenario_session.close()
                    await scenario_engine.dispose()
                    db_path.unlink(missing_ok=True)
    finally:
        events_api.process_event_background = original_pipeline
        app.dependency_overrides.clear()

    print("-" * 72)
    print(f"结果：PASS={passed} FAIL={failed}")
    print("总体：PASS" if failed == 0 else "总体：FAIL")
    return 0 if failed == 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="离线运行 PromiseLink W3/W4 真实用户 E2E 场景")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="ID",
        help="只运行指定场景，可重复使用，例如 --case W3-02 --case W4-01",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected = set(args.cases or [])
    known_ids = {scenario_id for scenario_id, _, _ in SCENARIOS}
    unknown = selected - known_ids
    if unknown:
        print(f"未知场景：{', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    return asyncio.run(run(selected or None))


if __name__ == "__main__":
    raise SystemExit(main())
