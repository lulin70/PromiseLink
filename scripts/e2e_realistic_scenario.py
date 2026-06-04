#!/usr/bin/env python3
"""Realistic scenario test — per-event data transformation chain.

Each event shows its complete transformation:
  原始文本 → 实体辨别 → 关联识别 → Todo提醒

Timeline:
  1. 2026-05-29: 许总名片 (card_save)
  2. 2026-05-29: 林总×许总 初次交流 (meeting)
  3. 2026-06-01: 林总×许总 产品方向确认 (meeting)
  4. 2026-06-01: 李总产品反馈v1 (meeting)
  5. 2026-06-02: 林总×许总 人vs知识 (meeting)
  6. 2026-06-02: 李总产品反馈v2 (meeting)
  7. 2026-06-03: 林总×许总×陈宇欣 产品对接 (meeting)

Constraint: 许总和李总不认识，不应产生关联

Usage:
  1. Start server: python -m eventlink.main
  2. Run test: python scripts/e2e_realistic_scenario.py
"""

import asyncio
import json
import sys
from builtins import print as builtins_print
from pathlib import Path

import httpx

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT = 120.0
OUTPUT_FILE = project_root / "scripts" / "e2e_realistic_output.txt"

# Global output buffer
_output_lines: list[str] = []


def _print(msg: str = ""):
    """Print to both console and output file buffer."""
    builtins_print(msg)
    _output_lines.append(msg)

# ── Real events in chronological order ──

EVENTS = [
    {
        "event_type": "card_save",
        "source": "iamhere",
        "title": "许总名片",
        "raw_text": json.dumps({
            "person": {
                "name": "许总",
                "company": "无界科技",
                "title": "CEO",
                "phone": "13900001111",
                "email": "xuzong@wujie.tech",
                "city": "深圳",
            },
        }, ensure_ascii=False),
        "date": "2026-05-29",
        "desc": "5月底简总介绍认识许总（许永亮），收到名片",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "林总×许总 初次交流 — AI记忆体产品探讨",
        "raw_text": Path("./docs/planning/20260529_许总初次交流纪要.md").read_text(encoding="utf-8"),
        "date": "2026-05-29",
        "desc": "和许总初次交流，探讨AI落地实践与记忆体产品，商定后续合作方向",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "林总×许总 产品方向确认",
        "raw_text": Path("./docs/planning/20260601_会议纪要.md").read_text(encoding="utf-8"),
        "date": "2026-06-01",
        "desc": "和许总正式会议，确认三层架构、事件类型、开发节奏",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "李总产品反馈v1 — 定位升级建议",
        "raw_text": Path("./docs/internal/EventLink_李总反馈_PM+架构师.md").read_text(encoding="utf-8"),
        "date": "2026-06-01",
        "desc": "李总建议从名片工具升级为商务关系管理AI助手",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "林总×许总 人vs知识",
        "raw_text": Path("./docs/planning/20260602_许总团队讨论纪要.md").read_text(encoding="utf-8"),
        "date": "2026-06-02",
        "desc": "和许总、简讨论产品侧重'人'还是'知识'，共识：侧重人",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "李总产品反馈v2 — 7板块30字段+16种角色",
        "raw_text": Path("./docs/internal/EventLink_李总反馈v2_PM+架构师.md").read_text(encoding="utf-8"),
        "date": "2026-06-02",
        "desc": "李总提供合作人员关键信息表、16种角色分类、会议标准知识卡片",
    },
    {
        "event_type": "meeting",
        "source": "manual",
        "title": "林总×许总×陈宇欣 产品对接",
        "raw_text": Path("./docs/planning/20260603_许总陈宇欣会议纪要.md").read_text(encoding="utf-8"),
        "date": "2026-06-03",
        "desc": "和许总、陈宇欣讨论数字名片产品对接，达成数据互通意向",
    },
]


def _divider(title: str, width: int = 72):
    _print(f"\n{'━' * width}")
    _print(f"  {title}")
    _print(f"{'━' * width}")


def _sub_divider(title: str, width: int = 72):
    _print(f"\n  {'─' * (width - 4)}")
    _print(f"  {title}")
    _print(f"  {'─' * (width - 4)}")


async def wait_for_server(client: httpx.AsyncClient) -> bool:
    for i in range(10):
        try:
            resp = await client.get(f"{BASE_URL}/health")
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def wait_for_pipeline(client: httpx.AsyncClient, event_id: str) -> dict | None:
    for _ in range(90):
        await asyncio.sleep(2)
        try:
            resp = await client.get(f"{BASE_URL}/events/{event_id}", timeout=TIMEOUT)
            if resp.status_code == 200:
                event = resp.json()
                if event.get("status") in ("completed", "failed"):
                    return event
        except Exception:
            pass
    return None


async def snapshot_state(client: httpx.AsyncClient) -> dict:
    """Take a snapshot of current entities, associations, todos."""
    # Small delay to ensure WAL-mode SQLite has committed and readers see latest
    await asyncio.sleep(0.5)

    entities = []
    try:
        resp = await client.get(f"{BASE_URL}/entities", params={"limit": 200}, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            entities = data.get("items", data) if isinstance(data, dict) else data
    except Exception:
        pass

    associations = []
    try:
        resp = await client.get(f"{BASE_URL}/associations", params={"limit": 200}, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            associations = data.get("items", data) if isinstance(data, dict) else data
    except Exception:
        pass

    todos = []
    try:
        resp = await client.get(f"{BASE_URL}/todos", params={"limit": 200}, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            todos = data.get("items", data) if isinstance(data, dict) else data
    except Exception:
        pass

    return {
        "entity_ids": {str(e["id"]) for e in entities},
        "association_ids": {str(a["id"]) for a in associations},
        "todo_ids": {str(t["id"]) for t in todos},
        "entities": entities,
        "associations": associations,
        "todos": todos,
    }


def show_entity_detail(entity: dict):
    """Show a single entity's key info."""
    props = entity.get("properties", {}) or {}
    basic = props.get("basic", {}) or {}
    resource = props.get("resource", {}) or {}
    concern = props.get("concern", []) or []
    caps = resource.get("capabilities", []) or []

    parts = []
    if basic.get("title") or basic.get("company"):
        parts.append(f"{basic.get('title', '')} @ {basic.get('company', '')}")
    if basic.get("city"):
        parts.append(f"城市:{basic['city']}")
    if caps:
        parts.append(f"资源:{', '.join(caps[:3])}")
    if concern:
        concern_strs = [str(c)[:20] for c in concern[:2]]
        parts.append(f"关注:{', '.join(concern_strs)}")

    status = entity.get("status", "?")
    conf = entity.get("confidence", 0)
    _print(f"      {entity['name']} [{status}, 置信度={conf:.2f}]")
    if parts:
        _print(f"        {' | '.join(parts)}")


def show_association_detail(assoc: dict, entity_map: dict):
    """Show a single association's key info."""
    src = entity_map.get(str(assoc.get("source_entity_id", "")), "???")
    tgt = entity_map.get(str(assoc.get("target_entity_id", "")), "???")
    atype = assoc.get("association_type", "?")
    strength = assoc.get("strength", 0)
    props = assoc.get("properties", {}) or {}
    evidence = props.get("evidence", {}) or {}

    type_labels = {
        "same_city": "同城", "co_occurrence": "共现",
        "competitor": "竞对", "alumni": "校友",
        "ex_colleague": "前同事", "tech_overlap": "技术重叠",
        "deal_link": "交易", "risk_link": "风险",
        "supply_chain": "供应链",
    }
    label = type_labels.get(atype, atype)
    detail = ""
    if evidence.get("city"):
        detail = f" ({evidence['city']})"
    elif evidence.get("shared_event_id"):
        detail = " (同一事件)"

    _print(f"      {label}: {src} ↔ {tgt} [强度={strength:.2f}]{detail}")


def show_todo_detail(todo: dict):
    """Show a single todo's key info."""
    type_labels = {
        "promise": "承诺", "help": "帮助", "care": "关注",
        "followup": "跟进", "cooperation_signal": "合作信号", "risk": "风险",
    }
    label = type_labels.get(todo.get("todo_type", "?"), todo.get("todo_type", "?"))
    priority = todo.get("priority", 0)
    title = todo.get("title", "?")
    desc = todo.get("description", "") or ""
    # Avoid repeating title in description
    if desc and desc != title and not title.endswith(desc[:30]):
        desc_preview = desc[:60] + "..." if len(desc) > 60 else desc
    else:
        desc_preview = ""

    _print(f"      [{label}] P{priority} {title}")
    if desc_preview:
        _print(f"        {desc_preview}")


async def process_event(
    client: httpx.AsyncClient,
    event_data: dict,
    index: int,
    total: int,
):
    """Process a single event and show its complete data transformation chain."""
    desc = event_data.pop("desc", "")
    date = event_data.pop("date", "")
    _divider(f"Event {index + 1}/{total}: {event_data['title']}")

    # ── Screen 1: Raw Text ──
    _sub_divider("1. 原始文本")
    _print(f"  日期: {date} | 类型: {event_data['event_type']} | {desc}")

    raw = event_data["raw_text"]
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            person = data.get("person", {})
            _print(f"  名片: {person.get('name', '')} | {person.get('title', '')} @ {person.get('company', '')} | {person.get('city', '')}")
        except json.JSONDecodeError:
            _print(f"  {raw[:100]}...")
    else:
        preview = raw[:150].replace("\n", " ")
        _print(f"  {preview}...")

    # Snapshot state BEFORE processing
    before = await snapshot_state(client)

    # Create event
    try:
        resp = await client.post(f"{BASE_URL}/events", json=event_data, timeout=TIMEOUT)
        if resp.status_code != 201:
            _print(f"\n  创建失败: {resp.status_code} {resp.text[:200]}")
            return
        event_id = resp.json()["id"]
    except Exception as e:
        _print(f"\n  请求异常: {e}")
        return

    _print(f"\n  管线处理中 (event_id={event_id})...")
    event = await wait_for_pipeline(client, event_id)
    if not event or event.get("status") != "completed":
        _print(f"  管线处理失败: {event.get('status', 'timeout') if event else 'timeout'}")
        if event and event.get("status") == "failed":
            try:
                detail = await client.get(f"{BASE_URL}/events/{event_id}", timeout=TIMEOUT)
                if detail.status_code == 200:
                    _print(f"  详情: {json.dumps(detail.json(), ensure_ascii=False)[:300]}")
            except Exception:
                pass
        return

    # Snapshot state AFTER processing
    after = await snapshot_state(client)

    # Build entity name map for association display
    entity_map = {str(e["id"]): e["name"] for e in after["entities"]}

    # ── Screen 2: Entity Extraction (delta) ──
    new_entity_ids = after["entity_ids"] - before["entity_ids"]
    new_entities = [e for e in after["entities"] if str(e["id"]) in new_entity_ids]

    # Also check for merged entities (name changed but id existed before)
    merged_entities = []
    for e in after["entities"]:
        eid = str(e["id"])
        if eid in before["entity_ids"]:
            # Check if this entity's name or properties changed
            before_e = next((b for b in before["entities"] if str(b["id"]) == eid), None)
            if before_e and (before_e.get("name") != e.get("name") or before_e.get("properties") != e.get("properties")):
                merged_entities.append(e)

    _sub_divider(f"2. 实体辨别 (新增 {len(new_entities)} 个, 合并更新 {len(merged_entities)} 个)")
    if new_entities:
        _print("    新增实体:")
        for e in new_entities:
            show_entity_detail(e)
    if merged_entities:
        _print("    合并更新:")
        for e in merged_entities:
            show_entity_detail(e)
    if not new_entities and not merged_entities:
        _print("      (本次无实体变更)")

    # ── Screen 3: Association Discovery (delta) ──
    new_assoc_ids = after["association_ids"] - before["association_ids"]
    new_associations = [a for a in after["associations"] if str(a["id"]) in new_assoc_ids]

    _sub_divider(f"3. 关联识别 (新增 {len(new_associations)} 条)")
    if new_associations:
        for a in new_associations:
            show_association_detail(a, entity_map)
    else:
        _print("      (本次无新增关联)")

    # ── Screen 4: Todo Generation (delta) ──
    new_todo_ids = after["todo_ids"] - before["todo_ids"]
    new_todos = [t for t in after["todos"] if str(t["id"]) in new_todo_ids]

    _sub_divider(f"4. Todo提醒 (新增 {len(new_todos)} 条)")
    if new_todos:
        # Group by type
        by_type: dict[str, list] = {}
        for t in new_todos:
            by_type.setdefault(t.get("todo_type", "?"), []).append(t)
        type_labels = {
            "promise": "承诺", "help": "帮助", "care": "关注",
            "followup": "跟进", "cooperation_signal": "合作信号", "risk": "风险",
        }
        for tt, items in by_type.items():
            label = type_labels.get(tt, tt)
            _print(f"    [{label}] ({len(items)}条):")
            for t in items:
                show_todo_detail(t)
    else:
        _print("      (本次无新增Todo)")

    # ── Running totals ──
    _sub_divider("累计统计")
    _print(f"  实体: {len(after['entity_ids'])} | 关联: {len(after['association_ids'])} | Todo: {len(after['todo_ids'])}")


async def show_final_summary(client: httpx.AsyncClient):
    """Show the final summary with cross-validation."""
    _divider("最终汇总 — 全局数据变换验证")

    after = await snapshot_state(client)
    entities = after["entities"]
    associations = after["associations"]
    todos = after["todos"]
    entity_map = {str(e["id"]): e["name"] for e in entities}

    # Entity summary
    _print(f"\n  实体 ({len(entities)}个):")
    for e in entities:
        show_entity_detail(e)

    # Association summary
    _print(f"\n  关联 ({len(associations)}条):")
    if associations:
        for a in associations:
            show_association_detail(a, entity_map)
    else:
        _print("    (暂无关联)")

    # Todo summary
    _print(f"\n  Todo ({len(todos)}条):")
    by_type: dict[str, list] = {}
    for t in todos:
        by_type.setdefault(t.get("todo_type", "?"), []).append(t)
    type_labels = {
        "promise": "承诺", "help": "帮助", "care": "关注",
        "followup": "跟进", "cooperation_signal": "合作信号", "risk": "风险",
    }
    for tt, items in by_type.items():
        label = type_labels.get(tt, tt)
        _print(f"    [{label}] ({len(items)}条)")

    # Virtual character check
    virtual_roles = {"PM", "架构师", "产品经理", "设计师", "开发", "测试", "运营"}
    virtual_entities = [e for e in entities if e.get("name", "") in virtual_roles]
    if virtual_entities:
        _print(f"  ⚠️ 虚拟角色误识别: {[e['name'] for e in virtual_entities]}")
    else:
        _print(f"  验证: 无虚拟角色误识别（正确）")


async def main():
    _print("=" * 72)
    _print("  EventLink PoC — 真实会议记录测试（每个Event展示完整数据变换链）")
    _print("  时间线: 5/29许总名片+初次交流 → 6/1产品确认+李总v1 → 6/2人vs知识+李总v2 → 6/3产品对接")
    _print("=" * 72)

    # Verify clean database
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(f"{BASE_URL}/entities", params={"limit": 200})
            if resp.status_code == 200:
                data = resp.json()
                # Handle PaginatedResponse format
                if isinstance(data, dict) and "items" in data:
                    existing = len(data["items"])
                elif isinstance(data, list):
                    existing = len(data)
                else:
                    existing = 0
                if existing > 0:
                    _print(f"  ⚠️ 数据库非空（{existing}个实体），请先清空数据库再运行测试")
                    sys.exit(1)
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        if not await wait_for_server(client):
            _print("服务器未就绪")
            sys.exit(1)
        _print("服务器就绪（数据库已清空）\n")

        # Process events in chronological order
        total = len(EVENTS)
        for i, event_data in enumerate(EVENTS):
            await process_event(client, event_data.copy(), i, total)
            _print()

        # Final summary
        await show_final_summary(client)

    _print("\n" + "=" * 72)
    _print("  真实场景测试完成")
    _print("=" * 72)

    # Write output to file
    OUTPUT_FILE.write_text("\n".join(_output_lines), encoding="utf-8")
    builtins_print(f"\n  输出已保存到: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
