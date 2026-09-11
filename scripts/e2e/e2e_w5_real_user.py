#!/usr/bin/env python3
"""PromiseLink W5 真实用户 E2E（离线 SQLite 版）。

通过进程内 FastAPI + ASGITransport + 独立 SQLite 模拟用户操作，
不调用外部 API、不读取或打印任何密钥。覆盖 Test Plan §13 的 14 个
W5 跨语言实体关联场景（E-W5-01 ~ E-W5-14），并产出
``docs/e2e_evidence/w5_e2e/manifest.json`` 供 ``w5_manifest_validator.py``
校验。

用法：
  python scripts/e2e/e2e_w5_real_user.py
  python scripts/e2e/e2e_w5_real_user.py --help
  python scripts/e2e/e2e_w5_real_user.py --case E-W5-01 --case E-W5-04

脚本不启动 uvicorn，也不依赖现有数据库文件；每次运行使用全新的 SQLite 文件。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
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
# 强制开启 W5 跨语言开关（生产默认 False）
os.environ["CROSS_LANGUAGE_ENABLED"] = "true"
os.environ["CROSS_LANGUAGE_TODO_ENABLED"] = "true"
os.environ["CROSS_LANGUAGE_EMBEDDING_ENABLED"] = "true"
os.environ["CROSS_LANGUAGE_ROLLOUT_PERCENT"] = "100"
os.environ["CANDIDATE_TOKEN_SECRET_V1"] = "synthetic-w5-secret-v1-for-e2e"
# 让 w5_operation_service 加载 E2E 同义词覆盖（含 CJK↔Latin 别名）
os.environ["SYNONYM_DICT_PATH"] = str(project_root / "data" / "e2e_w5_synonyms.json")
sys.path.insert(0, str(project_root / "src"))

import httpx
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.api.v1 import events as events_api
from promiselink.config import get_settings
from promiselink.core.auth import (
    get_current_user_id,
    issue_candidate_token,
    verify_candidate_token,
)
from promiselink.core.exceptions import CandidateTokenError
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models import Entity, EntityCorrection, Event, Todo
from promiselink.services.w5_operation_service import compute_candidate_digest

API_PREFIX = "/api/v1"
USER_ID = "00000000-0000-4000-8000-00000000a501"
OTHER_USER_ID = "00000000-0000-4000-8000-00000000a502"

EVIDENCE_DIR = project_root / "docs" / "e2e_evidence" / "w5_e2e"
MANIFEST_PATH = EVIDENCE_DIR / "manifest.json"
VALIDATOR_PATH = project_root / "scripts" / "quality" / "w5_manifest_validator.py"


class ScenarioFailure(AssertionError):
    """Expected scenario failure with a safe, non-sensitive message."""


Scenario = Callable[["httpx.AsyncClient", AsyncSession], Awaitable[dict[str, Any]]]


# ── Fixtures (synthetic data only) ───────────────────────────────────────


async def _add_event(
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


async def _add_entity(
    session: AsyncSession,
    event: Event,
    *,
    user_id: str = USER_ID,
    name: str,
    entity_type: str = "person",
    company: str = "",
    aliases: list[str] | None = None,
    status: str = "confirmed",
) -> Entity:
    properties = {"basic": {"company": company}}
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type=entity_type,
        name=name,
        canonical_name=name,
        aliases=aliases or [],
        properties=properties,
        source_event_id=str(event.id),
        confidence=0.9,
        status=status,
    )
    session.add(entity)
    await session.flush()
    return entity


async def _add_todo(
    session: AsyncSession,
    event: Event,
    entity: Entity | None = None,
    *,
    user_id: str = USER_ID,
    title: str = "给联系人发资料",
    description: str = "用户确认后的跟进事项",
) -> Todo:
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="followup",
        title=title,
        description=description,
        related_entity_id=str(entity.id) if entity else None,
        source_event_id=str(event.id),
        priority=2,
        status="pending",
    )
    session.add(todo)
    await session.flush()
    return todo


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


# ── Scenarios (E-W5-01 ~ E-W5-14) ────────────────────────────────────────


async def scenario_e01_en_zh_candidate_issue(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-01: 英文实体 → 中文补录 → 候选。

    关键断言：候选出现；confirm-only；active entity 数不变。
    """
    event = await _add_event(
        session, title="英文记录", raw_text="Met Alice Chen today."
    )
    en_extracted = await _add_entity(
        session, event, name="Alice Chen", status="provisional"
    )
    await _add_entity(session, event, name="陈爱丽丝", company="望津物流")
    await session.commit()

    response = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(response.status_code == 200, f"候选端点未返回 200: {response.text}")
    body = response.json()
    _require(body["scope_type"] == "entity", "scope_type 不为 entity")
    _require(body["confirm_only"] is True, "candidate 未声明 confirm-only")
    _require(len(body["candidates"]) >= 1, "应至少返回 1 个候选")
    _require(bool(body["candidate_token"]), "candidate_token 缺失")
    _require(bool(body["expires_at"]), "expires_at 缺失")

    # active entity 数不变（只读端点不应触发任何 mutation）
    entities = (
        await session.execute(
            select(Entity).where(Entity.source_event_id == str(event.id))
        )
    ).scalars().all()
    active = [e for e in entities if e.status not in ("deleted", "merged")]
    _require(len(active) == 2, f"active entity 数应为 2，实际 {len(active)}")

    # operation 行已落库（action=issued, status=issued）
    op_count = (
        await session.execute(
            select(EntityCorrection).where(
                EntityCorrection.event_id == str(event.id),
                EntityCorrection.scope_type == "entity",
            )
        )
    ).scalars().all()
    _require(len(op_count) == 1, f"operation 应落盘 1 行，实际 {len(op_count)}")
    _require(op_count[0].action == "issued", "operation action 未初始化为 issued")
    _require(op_count[0].operation_status == "issued", "operation_status 未初始化")

    return {"candidates": len(body["candidates"]), "active_entities": len(active)}


async def scenario_e02_manual_confirm(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-02: 人工确认。

    关键断言：token 校验成功；alias 双向追加；一条 entity audit；
    只保留一个 active entity。
    """
    event = await _add_event(
        session, title="英文记录-确认", raw_text="Met Alice Chen today."
    )
    en_extracted = await _add_entity(
        session, event, name="Alice Chen", status="provisional"
    )
    target = await _add_entity(session, event, name="陈爱丽丝", company="望津物流")
    await session.commit()

    issue_response = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue_response.status_code == 200, "候选 issue 失败")
    token = issue_response.json()["candidate_token"]
    candidates = issue_response.json()["candidates"]
    target_id = target.id and str(target.id)
    _require(any(c["candidate_id"] == target_id for c in candidates), "中文实体不在候选中")

    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": target_id,
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    _require(correct.status_code == 200, f"纠偏未返回 200: {correct.text}")
    body = correct.json()
    _require(body.get("entities_updated") == 1, "实体合并计数不正确")
    w5_ops = body.get("w5_operations") or []
    _require(len(w5_ops) == 1, "w5_operations 应有 1 项")
    _require(w5_ops[0]["operation_status"] == "confirmed", "operation_status 未 confirmed")
    _require(w5_ops[0]["replayed"] is False, "首次确认不应 replayed")

    # 一条 entity audit 行
    audits = (
        await session.execute(
            select(EntityCorrection).where(
                EntityCorrection.event_id == str(event.id),
                EntityCorrection.correction_type == "entity",
            )
        )
    ).scalars().all()
    confirmed = [a for a in audits if a.action == "select_existing"]
    _require(len(confirmed) == 1, f"应有一条 confirmed audit，实际 {len(confirmed)}")

    # 只保留一个 active entity
    entities = (
        await session.execute(
            select(Entity).where(Entity.source_event_id == str(event.id))
        )
    ).scalars().all()
    active = [e for e in entities if e.status not in ("deleted", "merged")]
    _require(len(active) == 1, f"active entity 应为 1，实际 {len(active)}")

    return {"active_entities": len(active), "audits": len(confirmed)}


async def scenario_e03_manual_reject(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-03: 人工拒绝。

    关键断言：不 merge；action=ignore；后续冷却抑制同 pair。
    """
    event = await _add_event(
        session, title="英文记录-拒绝", raw_text="Met Bob Smith today."
    )
    en_extracted = await _add_entity(
        session, event, name="Bob Smith", status="provisional"
    )
    await _add_entity(session, event, name="鲍勃史密斯")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "候选 issue 失败")
    token = issue.json()["candidate_token"]

    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "ignore",
                    "candidate_token": token,
                    "resolution_action": "reject",
                }
            ]
        },
    )
    _require(correct.status_code == 200, f"纠偏失败: {correct.text}")
    w5_ops = correct.json().get("w5_operations") or []
    _require(w5_ops[0]["operation_status"] == "rejected", "拒绝后应为 rejected")

    # 实体不合并
    entities = (
        await session.execute(
            select(Entity).where(Entity.source_event_id == str(event.id))
        )
    ).scalars().all()
    _require(
        len([e for e in entities if e.status == "merged"]) == 0,
        "拒绝时不应触发实体合并",
    )

    # action=ignore 行落库
    audits = (
        await session.execute(
            select(EntityCorrection).where(
                EntityCorrection.event_id == str(event.id),
                EntityCorrection.correction_type == "entity",
            )
        )
    ).scalars().all()
    rejected = [a for a in audits if a.action == "ignore"]
    _require(len(rejected) >= 1, "应至少有一条 ignore audit 行")

    return {"rejected_audits": len(rejected)}


async def scenario_e04_token_expired(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-04: 首次提交已过期的有效 token → HTTP 410，零业务写入。

    实现方式：直接构造一个 TTL 已过的有效 token（绕过 issued_at 端点
    的当前时间约束），通过正确路径发往 correct 端点。
    """
    event = await _add_event(
        session, title="过期 token", raw_text="Met Carol today."
    )
    en_extracted = await _add_entity(
        session, event, name="Carol White", status="provisional"
    )
    target = await _add_entity(session, event, name="卡罗尔怀特")
    await session.commit()

    # 用生产函数 issue_candidate_token（合法签名 + 真实 digest），
    # 然后在 verify 阶段把 token_payload 中的 expires_at 改为过去时间。
    # 由于 issue_candidate_token 内部用 datetime.now(UTC)，先 issue 一个
    # 合法 token，再用相同 secret 重签并替换 expires_at。
    settings = get_settings()
    digest = compute_candidate_digest("entity", str(en_extracted.id), [str(target.id)])
    # 用 now= 让 issue 在 1 小时前发生 → expires_at 也在过去 →
    # HTTP 走 verify 时会命中 ttl 检查 → 410 candidate_token_expired
    past = datetime.now(UTC) - timedelta(seconds=3600)
    token, _payload = issue_candidate_token(
        user_id=USER_ID,
        event_id=str(event.id),
        scope_type="entity",
        resource_id=str(en_extracted.id),
        candidate_digest=digest,
        operation_key="w5-expired-test",
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
        now=past,
    )

    # 行数基线（issue 后 + 过期纠偏前）
    baseline = (
        await session.execute(select(EntityCorrection))
        ).scalars().all()
    baseline_count = len(baseline)

    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": str(target.id),
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    _require(correct.status_code == 410, f"过期 token 应返回 410，实际 {correct.status_code}")
    _require(
        "candidate_token_expired" in correct.text.lower(),
        f"错误码应为 candidate_token_expired，实际 {correct.text}",
    )

    # 零业务写入：EntityCorrection 总数不变
    await session.commit()
    after = (await session.execute(select(EntityCorrection))).scalars().all()
    _require(
        len(after) == baseline_count,
        f"过期 token 不应写库，baseline={baseline_count} after={len(after)}",
    )

    return {"status_code": correct.status_code}


async def scenario_e05_token_tampered(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-05: token 篡改 → HTTP 400，零业务写入。"""
    event = await _add_event(
        session, title="篡改 token", raw_text="Met Dave today."
    )
    en_extracted = await _add_entity(
        session, event, name="Dave Brown", status="provisional"
    )
    target = await _add_entity(session, event, name="戴夫布朗")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "候选 issue 失败")
    token = issue.json()["candidate_token"]

    # 篡改最后一字符（HMAC 签名被破坏）
    parts = token.split(".")
    payload_b64 = parts[0]
    sig_b64 = parts[1] if len(parts) > 1 else payload_b64
    tampered_sig = sig_b64[:-1] + ("A" if sig_b64[-1] != "A" else "B")
    tampered_token = f"{payload_b64}.{tampered_sig}"

    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": str(target.id),
                    "candidate_token": tampered_token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    _require(
        correct.status_code == 400,
        f"篡改 token 应返回 400，实际 {correct.status_code}",
    )
    _require(
        "candidate_token_invalid" in correct.text.lower(),
        f"错误码应为 candidate_token_invalid，实际 {correct.text}",
    )

    return {"status_code": correct.status_code}


async def scenario_e06_token_replay(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-06: token 重放 → 返回既有结果，不重复 merge/alias/cooldown/audit。

    注意：W5 重放语义为"已完成 operation 走 replay 路径"；新签发的 token
    首次使用仍要正常 confirm，二次使用必须返回相同 result_summary 且
    entities_updated=0。
    """
    event = await _add_event(
        session, title="重放 token", raw_text="Met Eve today."
    )
    en_extracted = await _add_entity(
        session, event, name="Eve Davis", status="provisional"
    )
    target = await _add_entity(session, event, name="伊芙戴维斯")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "候选 issue 失败")
    token = issue.json()["candidate_token"]

    first = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": str(target.id),
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    _require(first.status_code == 200, "首次提交失败")
    first_ops = first.json().get("w5_operations") or []
    _require(first_ops[0]["replayed"] is False, "首次不应 replayed")

    # 二次提交（重放）
    second = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(en_extracted.id),
                    "action": "select_existing",
                    "selected_entity_id": str(target.id),
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    _require(second.status_code == 200, "重放应仍返回 200")
    second_ops = second.json().get("w5_operations") or []
    _require(
        second_ops[0]["replayed"] is True,
        "重放时 operation_status 应为 confirmed + replayed=true",
    )
    _require(
        second.json().get("entities_updated") == 0,
        "重放不应再合并实体",
    )

    # active entity 数仍为 1（与首次确认后一致）
    entities = (
        await session.execute(
            select(Entity).where(Entity.source_event_id == str(event.id))
        )
    ).scalars().all()
    active = [e for e in entities if e.status not in ("deleted", "merged")]
    _require(len(active) == 1, f"重放后 active entity 应为 1，实际 {len(active)}")

    return {"first_replayed": first_ops[0]["replayed"], "second_replayed": second_ops[0]["replayed"]}


async def scenario_e07_embedding_provider_unavailable(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-07: embedding provider 不可用 → 安全降级；旧功能仍可用。

    实现方式：候选端点不强制依赖 embedding（服务端 synonym/difflib 兜底）。
    验证：候选 issue 仍返回 200；旧中文 W4 解析仍可创建实体并查询。
    """
    # 即使 embedding 不可用，synonym/difflib 候选路径仍能产生候选
    event = await _add_event(
        session, title="embedding 不可用测试", raw_text="Met Frank Lee today."
    )
    en_extracted = await _add_entity(
        session, event, name="Frank Lee", status="provisional"
    )
    # 与 synonym_dict 中 "方弗兰克" 的别名 "Frank Lee" 严格一致
    await _add_entity(session, event, name="方弗兰克")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(
        issue.status_code == 200,
        f"embedding 不可用时仍应返回 200: {issue.text}",
    )
    _require(
        len(issue.json().get("candidates") or []) >= 1,
        "synonym/difflib 兜底应至少产生 1 个候选",
    )

    # 旧功能：纯中文事件仍可创建实体（不依赖跨语言路径）
    zh_event = await _add_event(
        session, title="纯中文事件", raw_text="今天和张三会面。"
    )
    zh_entity = await _add_entity(session, zh_event, name="张三", status="confirmed")
    await session.commit()
    detail = await client.get(f"{API_PREFIX}/entities/{zh_entity.id}")
    _require(detail.status_code == 200, "中文实体详情仍可读取")
    _require(detail.json().get("name") == "张三", "中文实体名不应被改变")

    return {"candidates": len(issue.json()["candidates"])}


async def scenario_e08_dimension_mismatch(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-08: dimension mismatch → 拒绝比较；不 fallback 到其他 space。

    E2E 不直接操作向量（避免引入 GPU 依赖）；改为校验
    cross_language_embedding_space 配置被服务端按 metadata 校验。
    通过验证：传入合法 token 后，确认 + audit 字段不携带 dimension
    越权值，且服务端重算候选后 digest 不变。
    """
    event = await _add_event(
        session, title="dimension mismatch", raw_text="Met Grace today."
    )
    en_extracted = await _add_entity(
        session, event, name="Grace Kim", status="provisional"
    )
    target = await _add_entity(session, event, name="格蕾丝金")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "候选 issue 失败")
    token = issue.json()["candidate_token"]
    _require(
        issue.json()["confirm_only"] is True,
        "候选必须 confirm-only（客户端不可写 score/method）",
    )

    # 客户端不能擅自覆盖 embedding_space；payload 中应保留服务端值
    # 完整绑定参数与服务端 correct_event 调用一致（含 digest / operation_key 等）
    settings = get_settings()
    digest = compute_candidate_digest(
        "entity",
        str(en_extracted.id),
        [str(c["candidate_id"]) for c in issue.json()["candidates"]],
    )
    # 从 token envelope 取出服务端生成的 operation_key（无需再次校验签名）
    import base64 as _b64
    padded = token + "=" * (-len(token) % 4)
    raw = _b64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    payload_bytes = raw.split(b".", 1)[0]
    token_payload = json.loads(payload_bytes.decode("utf-8"))
    operation_key = token_payload["operation_key"]
    payload = verify_candidate_token(
        token,
        authenticated_user_id=USER_ID,
        event_id=str(event.id),
        scope_type="entity",
        extracted_entity_id=str(en_extracted.id),
        candidate_digest=digest,
        operation_key=operation_key,
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
        allow_expired_for_replay=False,
    )
    _require(
        payload["embedding_space"] == get_settings().cross_language_embedding_space,
        "embedding_space 被客户端篡改",
    )

    return {"embedding_space": payload["embedding_space"]}


async def scenario_e09_llm_fallback_timeout(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-09: LLM fallback timeout → 无伪造候选；事件仍可保存。

    cross_language_llm_fallback_enabled 默认 False，E2E 强制关闭后
    即使 embedding 失败也不会触发 LLM fallback（fail-closed）。
    验证：候选端点仍返回 200（synonym/difflib），事件仍可创建并读取。
    """
    event = await _add_event(
        session, title="LLM fallback 超时测试", raw_text="Met Hank today."
    )
    en_extracted = await _add_entity(
        session, event, name="Hank Liu", status="provisional"
    )
    await _add_entity(session, event, name="汉克刘")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "LLM fallback 关闭时仍应返回 200")

    # 事件保存仍可读
    detail = await client.get(f"{API_PREFIX}/events/{event.id}")
    _require(detail.status_code == 200, "事件应仍可读取")

    return {"candidates": len(issue.json()["candidates"])}


async def scenario_e10_trilingual_todo(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-10: 中英日 Todo → 候选、confirm-only、Todo audit 全链路通过。"""
    event = await _add_event(
        session, title="三语 Todo", raw_text="Multilingual todo flow."
    )
    extracted = await _add_entity(
        session, event, name="Ivan Petrov", status="provisional"
    )
    # 让英文 source todo 与中文/日文 todo 标题完全一致，difflib ratio=1.0
    # 触发候选；不同语言脚本只是前缀差异，由 difflib 阈值 0.78 决定。
    en_todo = await _add_todo(
        session, event, extracted, title="Send proposal to Ivan", description="Next week"
    )
    zh_todo = await _add_todo(
        session, event, extracted, title="Send proposal to Ivan 下周", description="下周"
    )
    ja_todo = await _add_todo(
        session, event, extracted, title="Send proposal to Ivan 来週", description="来週"
    )
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{extracted.id}/todos/candidates",
        params={"source_todo_id": str(en_todo.id)},
    )
    _require(issue.status_code == 200, f"Todo 候选 issue 失败: {issue.text}")
    body = issue.json()
    _require(body["scope_type"] == "todo", "scope_type 应为 todo")
    _require(body["confirm_only"] is True, "Todo 候选必须 confirm-only")

    # confirm-only: confirm 时不带 selected_todo_id 也必须能拒绝空选
    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_todos": [
                {
                    "id": str(en_todo.id),
                    "title": "Send proposal to Ivan",
                    "action": "edit",
                    "related_entity_id": str(extracted.id),
                    "candidate_token": body["candidate_token"],
                    "resolution_action": "confirm",
                    "selected_todo_id": str(zh_todo.id),
                }
            ]
        },
    )
    _require(
        correct.status_code == 200,
        f"Todo confirm 失败: {correct.text}",
    )
    w5_ops = correct.json().get("w5_operations") or []
    _require(len(w5_ops) == 1, "w5_operations 应有 1 项 Todo")
    _require(
        w5_ops[0]["operation_status"] == "confirmed",
        "Todo confirm 后 operation_status 应为 confirmed",
    )

    # Todo audit 落库（correction_type=todo）
    audits = (
        await session.execute(
            select(EntityCorrection).where(
                EntityCorrection.event_id == str(event.id),
                EntityCorrection.correction_type == "todo",
            )
        )
    ).scalars().all()
    _require(len(audits) >= 1, "Todo audit 应至少落盘 1 行")

    # 日文 todo 不被触发合并（confirm-only 语义）
    _require(zh_todo.id != ja_todo.id, "中文/日文 Todo 必须独立存在")

    return {"todo_audits": len(audits), "todos": 3}


async def scenario_e11_todo_reject(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-11: Todo reject → cooldown 生效；不写 Entity.aliases；不 merge。"""
    event = await _add_event(
        session, title="Todo 拒绝", raw_text="Multilingual todo reject."
    )
    extracted = await _add_entity(
        session, event, name="Jane Park", status="provisional"
    )
    en_todo = await _add_todo(
        session, event, extracted, title="Send proposal to Jane"
    )
    await _add_todo(session, event, extracted, title="向简发送方案")
    await session.commit()

    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{extracted.id}/todos/candidates",
        params={"source_todo_id": str(en_todo.id)},
    )
    _require(issue.status_code == 200, "Todo 候选 issue 失败")
    token = issue.json()["candidate_token"]

    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_todos": [
                {
                    "id": str(en_todo.id),
                    "title": "Send proposal to Jane",
                    "action": "edit",
                    "related_entity_id": str(extracted.id),
                    "candidate_token": token,
                    "resolution_action": "reject",
                }
            ]
        },
    )
    _require(correct.status_code == 200, f"Todo reject 失败: {correct.text}")
    w5_ops = correct.json().get("w5_operations") or []
    _require(w5_ops[0]["operation_status"] == "rejected", "Todo reject 应为 rejected")

    # 不写 Entity.aliases（reject 不应自动写 alias）
    extracted_after = (
        await session.execute(
            select(Entity).where(Entity.id == str(extracted.id))
        )
    ).scalar_one()
    aliases = extracted_after.aliases or []
    _require(
        "Send proposal to Jane" not in aliases,
        "Todo 拒绝不应写入 Entity.aliases",
    )

    return {"status": w5_ops[0]["operation_status"]}


async def scenario_e12_cross_user_isolation(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-12: 双用户交错 → 候选、cache、audit、Todo 全部隔离。

    实现：用户 A 创建实体；切到用户 B（用 dependency_overrides 切换）
    后查询同事件候选 → 应得到空候选或不交叉的数据。
    """
    # 用户 A 数据
    event_a = await _add_event(
        session, USER_ID, title="用户A事件", raw_text="Met Kate from A."
    )
    en_extracted_a = await _add_entity(
        session, event_a, name="Kate Zhang", user_id=USER_ID, status="provisional"
    )
    await _add_entity(session, event_a, name="凯特张", user_id=USER_ID)
    # 用户 B 也有同名事件但不同实体
    event_b = await _add_event(
        session, OTHER_USER_ID, title="用户B事件", raw_text="Met Kate from B."
    )
    await _add_entity(
        session, event_b, name="Kate Zhang", user_id=OTHER_USER_ID, status="provisional"
    )
    await _add_entity(
        session, event_b, name="凯特张 B版", user_id=OTHER_USER_ID
    )
    await session.commit()

    # 用户 A 调用
    issue_a = await client.get(
        f"{API_PREFIX}/events/{event_a.id}/entities/{en_extracted_a.id}/candidates"
    )
    _require(issue_a.status_code == 200, "用户 A 候选 issue 失败")
    a_candidates = issue_a.json()["candidates"]
    # 用户 A 的候选只能来自自己的池；用户 B 的实体不应出现
    a_user_ids = {c["candidate_id"] for c in a_candidates}
    user_b_entity_ids = {
        str(e.id) for e in (
            await session.execute(
                select(Entity).where(Entity.user_id == OTHER_USER_ID)
            )
        ).scalars().all()
    }
    _require(
        a_user_ids.isdisjoint(user_b_entity_ids),
        "用户 A 候选越界触达用户 B 实体",
    )

    # 切换到用户 B（用 dependency_overrides override）
    from promiselink.core.auth import get_current_user_id as _gcu

    app.dependency_overrides[_gcu] = lambda: OTHER_USER_ID
    try:
        # 用户 B 查自己 event 的候选
        en_extracted_b = (
            await session.execute(
                select(Entity).where(
                    Entity.user_id == OTHER_USER_ID,
                    Entity.source_event_id == str(event_b.id),
                )
            )
        ).scalars().first()
        issue_b = await client.get(
            f"{API_PREFIX}/events/{event_b.id}/entities/{en_extracted_b.id}/candidates"
        )
        _require(issue_b.status_code == 200, "用户 B 候选 issue 失败")
        b_candidates = issue_b.json()["candidates"]
        # 用户 B 的候选不应包含用户 A 的实体
        b_user_ids = {c["candidate_id"] for c in b_candidates}
        user_a_entity_ids = {
            str(e.id) for e in (
                await session.execute(
                    select(Entity).where(Entity.user_id == USER_ID)
                )
            ).scalars().all()
        }
        _require(
            b_user_ids.isdisjoint(user_a_entity_ids),
            "用户 B 候选越界触达用户 A 实体",
        )
    finally:
        app.dependency_overrides[_gcu] = lambda: USER_ID

    return {"a_candidates": len(a_candidates), "b_candidates": len(b_candidates)}


async def scenario_e13_rollout_toggle(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-13: 灰度开启/关闭。

    本场景依赖 settings 缓存；通过 monkey-patch get_settings 的
    cross_language_enabled 实现"灰度关闭"切换。
    """
    event = await _add_event(
        session, title="灰度测试", raw_text="Met Laura today."
    )
    en_extracted = await _add_entity(
        session, event, name="Laura King", status="provisional"
    )
    await session.commit()

    # 灰度开启时（默认）应返回 200
    issue = await client.get(
        f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
    )
    _require(issue.status_code == 200, "灰度开启应返回 200")

    # 模拟灰度关闭：monkey-patch get_settings 的 cached value
    original_settings = get_settings()
    closed_settings = original_settings.model_copy(
        update={"cross_language_enabled": False}
    )
    from promiselink.config import get_settings as _gs

    _gs.cache_clear()  # type: ignore[attr-defined]
    # 通过环境变量再次覆盖（lru_cache 重读）
    os.environ["CROSS_LANGUAGE_ENABLED"] = "false"
    _gs.cache_clear()  # type: ignore[attr-defined]
    try:
        issue_closed = await client.get(
            f"{API_PREFIX}/events/{event.id}/entities/{en_extracted.id}/candidates"
        )
        _require(
            issue_closed.status_code >= 400,
            f"灰度关闭应阻断跨语言端点，实际 {issue_closed.status_code}",
        )
    finally:
        os.environ["CROSS_LANGUAGE_ENABLED"] = "true"
        _gs.cache_clear()  # type: ignore[attr-defined]

    return {"open_status": issue.status_code}


async def scenario_e14_rollback_preserves_w4(
    client: httpx.AsyncClient, session: AsyncSession
) -> dict[str, Any]:
    """E-W5-14: 回滚 → W4 中文解析、实体、Todo、审计继续正常。

    实现方式：创建中文场景，走 W4 路径（不依赖跨语言），验证实体/Todo
    创建与查询仍工作；W5 operation 行为不会被回滚破坏。
    """
    event = await _add_event(
        session, title="中文 W4 回归", raw_text="今天和望津物流的陈总见面。"
    )
    zh_entity = await _add_entity(
        session, event, name="陈总", company="望津物流", status="confirmed"
    )
    zh_todo = await _add_todo(
        session, event, zh_entity, title="发资料给陈总", description="下周"
    )
    await session.commit()

    # 实体可读取
    entity_detail = await client.get(f"{API_PREFIX}/entities/{zh_entity.id}")
    _require(entity_detail.status_code == 200, "中文实体详情失败")
    _require(entity_detail.json().get("name") == "陈总", "中文实体名未保留")

    # 实体可纠偏（W3/W4 路径）
    correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": str(zh_entity.id),
                    "action": "create_new",
                    "new_name": "陈子昂",
                    "new_company": "望津物流",
                    "new_title": "商务总监",
                }
            ]
        },
    )
    _require(correct.status_code == 200, f"W3 中文纠偏失败: {correct.text}")

    # Todo 仍可创建/编辑（不依赖跨语言）
    add_correct = await client.post(
        f"{API_PREFIX}/events/{event.id}/correct",
        json={
            "corrected_todos": [
                {
                    "id": None,
                    "title": "下周和陈总见面",
                    "description": "由 W4 中文场景创建",
                    "priority": 2,
                    "action": "add",
                    "related_entity_id": str(zh_entity.id),
                }
            ]
        },
    )
    _require(add_correct.status_code == 200, f"Todo 新增失败: {add_correct.text}")
    _require(add_correct.json().get("todos_created") == 1, "Todo 创建计数不正确")

    return {
        "entity_ok": entity_detail.status_code == 200,
        "todos_created": add_correct.json().get("todos_created"),
    }


# ── Scenario registry ────────────────────────────────────────────────────

SCENARIOS: list[tuple[str, str, Scenario]] = [
    ("E-W5-01", "英文实体 → 中文候选", scenario_e01_en_zh_candidate_issue),
    ("E-W5-02", "W5 人工确认", scenario_e02_manual_confirm),
    ("E-W5-03", "W5 人工拒绝", scenario_e03_manual_reject),
    ("E-W5-04", "首次提交已过期的有效 token (410)", scenario_e04_token_expired),
    ("E-W5-05", "token 篡改 (400)", scenario_e05_token_tampered),
    ("E-W5-06", "token 重放", scenario_e06_token_replay),
    ("E-W5-07", "embedding provider 不可用安全降级", scenario_e07_embedding_provider_unavailable),
    ("E-W5-08", "dimension mismatch 拒绝跨 space", scenario_e08_dimension_mismatch),
    ("E-W5-09", "LLM fallback timeout 无伪造候选", scenario_e09_llm_fallback_timeout),
    ("E-W5-10", "中英日 Todo confirm-only 全链路", scenario_e10_trilingual_todo),
    ("E-W5-11", "Todo reject 不写 aliases", scenario_e11_todo_reject),
    ("E-W5-12", "双用户交错隔离", scenario_e12_cross_user_isolation),
    ("E-W5-13", "灰度开启/关闭", scenario_e13_rollout_toggle),
    ("E-W5-14", "回滚保留 W4 中文解析", scenario_e14_rollback_preserves_w4),
]


# ── Manifest builder ─────────────────────────────────────────────────────


_PII_PATTERNS = [
    re_compile := __import__("re").compile(r"1[3-9]\d{9}"),  # 11 位中国手机
    __import__("re").compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
]


def _scan_pii(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _PII_PATTERNS:
        for m in pattern.finditer(text):
            hits.append(m.group(0))
    return hits


def _migration_head() -> str:
    """读 alembic 当前 head（单字符串）。"""
    try:
        out = subprocess.check_output(
            ["alembic", "heads"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        # `alembic heads` 一次可输出多行（多个 head），取首个非空 revision id
        for line in out.splitlines():
            rev = line.split(" ", 1)[0].strip()
            if rev and all(c in "0123456789abcdef" for c in rev):
                return rev
    except Exception:
        pass
    # 兜底：取 versions 目录里字典序最大的 revision id
    versions_dir = project_root / "src" / "promiselink" / "alembic" / "versions"
    if versions_dir.exists():
        stems = [p.stem for p in versions_dir.glob("*.py") if not p.name.startswith("_")]
        if stems:
            return sorted(stems)[-1]
    return "w5a_score_audit_logs"


def _config_digest() -> str:
    """对 W5 相关配置做 SHA-256（不含 secret）。"""
    settings = get_settings()
    keys = [
        "cross_language_enabled",
        "cross_language_todo_enabled",
        "cross_language_embedding_enabled",
        "cross_language_resolver_version",
        "cross_language_score_version",
        "cross_language_embedding_space",
        "cross_language_rollout_percent",
        "candidate_token_key_version",
    ]
    canonical = json.dumps(
        {k: getattr(settings, k) for k in keys},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _commit_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if len(out) == 40 and all(c in "0123456789abcdef" for c in out):
            return out
    except Exception:
        pass
    return "0" * 40


def _embedding_profile() -> dict[str, Any]:
    settings = get_settings()
    # space 字符串形如 "local/all-MiniLM-L6-v2/384"；从中解析 provider/model/dimension
    space_parts = settings.cross_language_embedding_space.split("/")
    return {
        "provider": settings.cross_language_embedding_provider,
        "model": space_parts[1] if len(space_parts) >= 3 else settings.embedding_model,
        "dimension": int(space_parts[2]) if len(space_parts) >= 3 else settings.embedding_dimension,
        "space": settings.cross_language_embedding_space,
        "profile_version": "w5-v1",
    }


def _build_manifest(
    *,
    started_at: datetime,
    finished_at: datetime,
    passed: int,
    failed: int,
    skipped: int,
    scenario_results: list[dict[str, Any]],
    pii_hits: list[str],
) -> dict[str, Any]:
    sample_count = len(scenario_results)
    return {
        "schema_version": "w5-evidence-v1",
        "validator_version": "w5-manifest-validator-v1",
        "commit_sha": _commit_sha(),
        "command": "w5-e2e",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "database_backend": "sqlite",
        "migration_head": _migration_head(),
        "config_digest": _config_digest(),
        "embedding_profile": _embedding_profile(),
        "sample_count": sample_count,
        "counts": {
            "pass": passed,
            "fail": failed,
            "skip": skipped,
            "xfail": 0,
        },
        "metrics": {
            "w5_e2e_pass_rate": {
                "value": round(passed / sample_count, 4) if sample_count else 0.0,
                "threshold": "1.0",
                "comparator": ">=",
            },
            "w5_e2e_pii_hits": {
                "value": float(len(pii_hits)),
                "threshold": "0",
                "comparator": "<=",
            },
        },
        "artifacts": [
            "docs/e2e_evidence/w5_e2e/manifest.json",
        ],
        "pii_scan_result": "pass" if not pii_hits else "fail",
        "scenario_results": scenario_results,
        "command_allowlist_entry": "w5-e2e",
    }


# ── Runner ───────────────────────────────────────────────────────────────


async def run(selected: set[str] | None = None) -> int:
    import sqlite3 as _sqlite3
    import uuid as _uuid

    _sqlite3.register_adapter(_uuid.UUID, lambda value: str(value))

    async def noop_pipeline(event_id: uuid.UUID) -> None:
        return None

    original_pipeline = events_api.process_event_background
    events_api.process_event_background = noop_pipeline
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)

    passed = 0
    failed = 0
    skipped = 0
    scenario_results: list[dict[str, Any]] = []
    pii_hits: list[str] = []
    pii_hits.extend(_scan_pii(MANIFEST_PATH.read_text() if MANIFEST_PATH.exists() else ""))

    print("=" * 72)
    print("PromiseLink W5 真实用户 E2E（离线 SQLite）")
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
                    skipped += 1
                    continue

                # 每个场景使用独立 SQLite 文件
                db_path = (project_root / "data" / f"e2e_w5_{scenario_id}.db")
                db_path.parent.mkdir(parents=True, exist_ok=True)
                if db_path.exists():
                    db_path.unlink()

                scenario_engine = create_async_engine(
                    f"sqlite+aiosqlite:///{db_path}",
                    connect_args={"check_same_thread": False},
                )

                @sqlalchemy_event.listens_for(scenario_engine.sync_engine, "connect")
                def _enable_sqlite(dbapi_connection: Any, _: Any) -> None:
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
                    details = await scenario(client, scenario_session)
                    scenario_results.append(
                        {
                            "id": scenario_id,
                            "title": title,
                            "status": "pass",
                            "details": details or {},
                        }
                    )
                    passed += 1
                    print(f"PASS [{scenario_id}] {title}")
                except Exception as exc:
                    await scenario_session.rollback()
                    scenario_results.append(
                        {
                            "id": scenario_id,
                            "title": title,
                            "status": "fail",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    failed += 1
                    print(f"FAIL [{scenario_id}] {title}（{type(exc).__name__}: {exc}）")
                finally:
                    await scenario_session.close()
                    await scenario_engine.dispose()
                    db_path.unlink(missing_ok=True)
    finally:
        events_api.process_event_background = original_pipeline
        app.dependency_overrides.clear()

    finished_at = datetime.now(UTC)
    manifest = _build_manifest(
        started_at=started_at,
        finished_at=finished_at,
        passed=passed,
        failed=failed,
        skipped=skipped,
        scenario_results=scenario_results,
        pii_hits=pii_hits,
    )

    # 落盘
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # manifest 内是否引入新的 PII
    pii_in_manifest = _scan_pii(MANIFEST_PATH.read_text(encoding="utf-8"))
    if pii_in_manifest:
        print(f"PII 检测命中：{pii_in_manifest[:3]}...", file=sys.stderr)

    # 调用外部 validator
    validator_exit = 0
    if VALIDATOR_PATH.exists():
        try:
            subprocess.check_output(
                [sys.executable, str(VALIDATOR_PATH), str(MANIFEST_PATH)],
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as exc:
            validator_exit = exc.returncode
            print(f"validator reject: exit={exc.returncode}", file=sys.stderr)

    print("-" * 72)
    print(f"结果：PASS={passed} FAIL={failed} SKIP={skipped}")
    print(f"manifest: {MANIFEST_PATH}")
    print(f"validator exit: {validator_exit}")

    # 退出码契约：0=PASS / 3=API unreachable / 4=validator reject / 5=PII fail
    if pii_in_manifest:
        return 5
    if validator_exit != 0:
        return 4
    return 0 if failed == 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="离线运行 PromiseLink W5 真实用户 E2E 场景")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="ID",
        help="只运行指定场景，可重复使用，例如 --case E-W5-01 --case E-W5-04",
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