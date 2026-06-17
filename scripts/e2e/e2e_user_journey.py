#!/usr/bin/env python3
"""E2E user journey with clear data transformation chain.

Shows the complete data flow:
  Screen 1: 原始数据 — What the user input
  Screen 2: 实体分解 — What entities were extracted (people, resources, connections)
  Screen 3: 碰撞发现 — What new associations/reminders emerged from existing data
  Screen 4: Todo产出 — What action items were generated

Usage:
  1. Start server: python -m promiselink.main
  2. Run test: python scripts/e2e_user_journey.py
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT = 120.0

# ── Test Data ──

MEETING_RAW = """今天下午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""

CARD_SAVE_RAW = json.dumps({
    "person": {
        "name": "张伟",
        "company": "智源AI研究院",
        "title": "首席科学家",
        "phone": "13812345678",
        "email": "zhangwei@baai.ac.cn",
        "city": "北京",
    },
}, ensure_ascii=False)

# 交流上下文作为单独的manual event
CARD_FOLLOWUP_RAW = """和张伟交换了名片，他是智源AI研究院的首席科学家。
交流中了解到他正在寻找大模型落地场景的合作方。
我答应下周发一份我们团队的AI应用案例集给他。
他对多模态方向很感兴趣，这是个好的跟进切入点。"""


def _divider(title: str, width: int = 70):
    """Print a section divider."""
    print(f"\n{'━' * width}")
    print(f"  {title}")
    print(f"{'━' * width}")


def _sub(label: str, width: int = 70):
    """Print a subsection label."""
    print(f"\n  ┌─ {label} {'─' * (width - len(label) - 6)}")
    print("  │")


def _item(key: str, value: str, indent: int = 2):
    """Print a key-value item."""
    prefix = " " * indent
    val_str = str(value).replace("\n", " ")[:120]
    print(f"{prefix}• {key}: {val_str}")


async def wait_for_server(client: httpx.AsyncClient, max_retries: int = 10) -> bool:
    """Wait for the FastAPI server to be ready."""
    for i in range(max_retries):
        try:
            resp = await client.get(f"{BASE_URL}/health")
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def wait_for_pipeline(client: httpx.AsyncClient, event_id: str, max_wait: int = 120) -> dict | None:
    """Wait for the pipeline to complete processing an event."""
    for _ in range(max_wait // 2):
        await asyncio.sleep(2)
        try:
            resp = await client.get(f"{BASE_URL}/events/{event_id}", timeout=TIMEOUT)
            if resp.status_code == 200:
                event = resp.json()
                if event.get("status") == "completed":
                    return event
                elif event.get("status") == "failed":
                    return event
        except Exception:
            pass
    return None


async def screen1_raw_data(
    client: httpx.AsyncClient, event_type: str, raw_text: str, title: str
) -> str | None:
    """Screen 1: Show the raw data the user input."""
    _divider("Screen 1: 原始数据 — 用户输入了什么")

    print(f"\n  事件类型: {event_type}")
    print(f"  事件标题: {title}")
    print("\n  原始文本:")
    for line in raw_text.split("\n"):
        print(f"    {line}")

    # Create the event
    payload = {
        "event_type": event_type,
        "source": "manual" if event_type == "meeting" else "iamhere",
        "title": title,
        "raw_text": raw_text,
    }

    try:
        resp = await client.post(f"{BASE_URL}/events", json=payload, timeout=TIMEOUT)
        if resp.status_code == 201:
            data = resp.json()
            event_id = data["id"]
            print(f"\n  ✅ 事件已创建 (id={event_id[:8]}...)")
            print("  ⏳ 管线处理中...")
            return event_id
        else:
            print(f"\n  ❌ 创建失败: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"\n  ❌ 请求异常: {e}")
        return None


async def screen2_entity_extraction(
    client: httpx.AsyncClient, event_id: str
) -> list[dict]:
    """Screen 2: Show what entities were extracted."""
    _divider("Screen 2: 实体分解 — 提取了哪些人/资源/联系")

    # Wait for pipeline
    event = await wait_for_pipeline(client, event_id)
    if not event:
        print("  ❌ 管线处理超时")
        return []

    if event.get("status") == "failed":
        print("  ❌ 管线处理失败")
        return []

    print("  ✅ 管线处理完成")

    # Fetch entities
    try:
        resp = await client.get(f"{BASE_URL}/entities", params={"limit": 20}, timeout=TIMEOUT)
        if resp.status_code != 200:
            print(f"  ⚠️ 实体查询失败: {resp.status_code}")
            return []
        entities = resp.json()
    except Exception as e:
        print(f"  ⚠️ 实体查询异常: {e}")
        return []

    # Group by type
    persons = [e for e in entities if e.get("entity_type") == "person"]
    others = [e for e in entities if e.get("entity_type") != "person"]

    _sub(f"人物实体 ({len(persons)}个)")
    for p in persons:
        props = p.get("properties", {}) or {}
        basic = props.get("basic", {}) or {}
        resource = props.get("resource", {}) or {}
        concern = props.get("concern", []) or []

        print("  │")
        print(f"  │  👤 {p['name']}")
        if basic.get("title") or basic.get("company"):
            print(f"  │     职位: {basic.get('title', '未知')} @ {basic.get('company', '未知')}")
        if basic.get("city"):
            print(f"  │     城市: {basic['city']}")
        if basic.get("industry"):
            print(f"  │     行业: {basic['industry']}")

        # Resources
        capabilities = resource.get("capabilities", []) or []
        if capabilities:
            print(f"  │     资源/能力: {', '.join(capabilities)}")

        # Concerns/demands
        if concern:
            print(f"  │     关注/需求: {', '.join(str(c) for c in concern[:5])}")

        # Confidence
        conf = p.get("confidence", 1.0)
        status = p.get("status", "confirmed")
        conf_label = "✅确认" if status == "confirmed" else "⚠️待确认"
        print(f"  │     置信度: {conf:.0%} {conf_label}")

    if others:
        _sub(f"其他实体 ({len(others)}个)")
        for o in others:
            print(f"  │  🏢 {o['name']} ({o['entity_type']})")

    print("  │")
    print(f"  └{'─' * 66}")

    return entities


async def screen3_collision_discovery(
    client: httpx.AsyncClient, entities: list[dict]
) -> list[dict]:
    """Screen 3: Show what new associations/reminders emerged."""
    _divider("Screen 3: 碰撞发现 — 和已有数据碰撞出了什么")

    # Fetch associations
    try:
        # Try associations endpoint (may not exist yet)
        resp = await client.get(f"{BASE_URL}/associations", params={"limit": 20}, timeout=TIMEOUT)
        if resp.status_code == 200:
            associations = resp.json()
        else:
            associations = []
    except Exception:
        associations = []

    # Also check for existing entities that share properties with new ones
    _sub("关联发现")
    if associations:
        for a in associations:
            atype = a.get("association_type", "unknown")
            strength = a.get("strength", 0)
            source = a.get("source_entity_id", "")[:8]
            target = a.get("target_entity_id", "")[:8]
            props = a.get("properties", {}) or {}
            evidence = props.get("evidence", {}) or {}

            type_labels = {
                "same_city": "🏙️ 同城",
                "co_occurrence": "🤝 共现",
                "competitor": "⚔️ 竞对",
                "alumni": "🎓 校友",
                "ex_colleague": "💼 前同事",
                "tech_overlap": "🔧 技术重叠",
                "deal_link": "💰 交易关联",
                "risk_link": "⚠️ 风险关联",
                "supply_chain": "🔗 供应链",
            }
            label = type_labels.get(atype, f"❓ {atype}")
            print(f"  │  {label}: {source}... ↔ {target}... (强度={strength:.2f})")
            if evidence:
                for k, v in evidence.items():
                    if isinstance(v, (str, int, float)):
                        print(f"  │     证据: {k}={v}")
    else:
        # Manual collision analysis from entities
        cities = {}
        industries = {}
        for e in entities:
            props = e.get("properties", {}) or {}
            basic = props.get("basic", {}) or {}
            city = basic.get("city", "")
            industry = basic.get("industry", "")
            if city:
                cities.setdefault(city, []).append(e["name"])
            if industry:
                industries.setdefault(industry, []).append(e["name"])

        found = False
        for city, names in cities.items():
            if len(names) > 1:
                print(f"  │  🏙️ 同城关联: {', '.join(names)} → {city}")
                found = True
        for industry, names in industries.items():
            if len(names) > 1:
                print(f"  │  ⚔️ 同行业: {', '.join(names)} → {industry}")
                found = True

        # Co-occurrence: entities from same event
        event_groups = {}
        for e in entities:
            eid = e.get("source_event_id", "")
            if eid:
                event_groups.setdefault(eid, []).append(e["name"])
        for eid, names in event_groups.items():
            if len(names) > 1:
                print(f"  │  🤝 共现关联: {', '.join(names)} (同一事件)")
                found = True

        if not found:
            print("  │  (暂无碰撞发现，数据量较少)")

    print("  │")
    print(f"  └{'─' * 66}")

    return associations


async def screen4_todo_output(
    client: httpx.AsyncClient, event_id: str | None = None
) -> list[dict]:
    """Screen 4: Show what action items were generated."""
    _divider("Screen 4: Todo产出 — 最终生成了什么行动项")

    try:
        resp = await client.get(f"{BASE_URL}/todos", params={"limit": 20}, timeout=TIMEOUT)
        if resp.status_code != 200:
            print(f"  ⚠️ Todo查询失败: {resp.status_code}")
            return []
        todos = resp.json()
    except Exception as e:
        print(f"  ⚠️ Todo查询异常: {e}")
        return []

    # Group by type
    type_labels = {
        "promise": ("🔘 雾绿 承诺", "我答应过什么"),
        "help": ("🔘 雾紫 帮助", "我能为他做什么"),
        "care": ("🔘 雾蓝 关注", "对方正在关心什么"),
        "followup": ("🔘 雾金 跟进", "需跟进的事项"),
        "cooperation_signal": ("🔘 雾白 合作信号", "合作可能"),
        "risk": ("🔘 烟粉 风险", "潜在风险"),
    }

    by_type: dict[str, list] = {}
    for t in todos:
        by_type.setdefault(t.get("todo_type", "unknown"), []).append(t)

    for todo_type, items in by_type.items():
        label, desc = type_labels.get(todo_type, (f"❓ {todo_type}", ""))
        _sub(f"{label} — {desc} ({len(items)}条)")
        for t in items:
            title = t.get("title", "")
            priority = t.get("priority", 3)
            status = t.get("status", "pending")
            due = t.get("due_date", "")

            priority_labels = {1: "🔴高", 2: "🟠较高", 3: "🟡中", 4: "🟢较低", 5: "⚪低"}
            p_label = priority_labels.get(priority, f"p{priority}")
            s_label = {"pending": "⏳待办", "in_progress": "🔄进行中", "done": "✅完成", "dismissed": "❌忽略", "snoozed": "💤延后"}.get(status, status)

            print(f"  │  {p_label} {title}")
            print(f"  │     状态: {s_label}  截止: {due or '未定'}")

            # Show context/reason if available
            props = t.get("properties", {}) or {}
            context = props.get("context", {}) or {}
            reason = context.get("reason", "")
            if reason:
                print(f"  │     原因: {reason[:80]}")

    print("  │")
    print(f"  └{'─' * 66}")

    # Summary
    _sub("汇总")
    total = len(todos)
    by_type_count = {t: len(items) for t, items in by_type.items()}
    print(f"  │  共 {total} 条Todo:")
    for tt, count in by_type_count.items():
        label, _ = type_labels.get(tt, (tt, ""))
        print(f"  │    {label}: {count}条")

    print("  │")
    print(f"  └{'─' * 66}")

    return todos


async def run_journey(
    client: httpx.AsyncClient,
    event_type: str,
    raw_text: str,
    title: str,
    journey_label: str,
):
    """Run a complete 4-screen user journey."""
    _divider(f"🚀 {journey_label}", width=70)

    # Screen 1: Raw data
    event_id = await screen1_raw_data(client, event_type, raw_text, title)
    if not event_id:
        return

    # Screen 2: Entity extraction
    entities = await screen2_entity_extraction(client, event_id)

    # Screen 3: Collision discovery
    associations = await screen3_collision_discovery(client, entities)

    # Screen 4: Todo output
    todos = await screen4_todo_output(client, event_id)

    return event_id, entities, associations, todos


async def main():
    """Run the 4-screen user journey test."""
    print("=" * 70)
    print("  PromiseLink PoC — 用户旅程验证")
    print("  核心闭环: 互动 → 关注 → 承诺 → 帮助 → 反馈")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Check server
        if not await wait_for_server(client):
            print("❌ 服务器未就绪，请先启动: python -m promiselink.main")
            sys.exit(1)
        print("✅ 服务器就绪\n")

        # ── Journey 1: Meeting ──
        await run_journey(
            client,
            event_type="meeting",
            raw_text=MEETING_RAW,
            title="与李总的投资对接会",
            journey_label="旅程1: 记录一次重要会议",
        )

        # ── Journey 2: Card Save + Follow-up ──
        await run_journey(
            client,
            event_type="card_save",
            raw_text=CARD_SAVE_RAW,
            title="张伟名片",
            journey_label="旅程2a: 保存一张名片（纯名片信息）",
        )

        await run_journey(
            client,
            event_type="manual",
            raw_text=CARD_FOLLOWUP_RAW,
            title="和张伟的交流记录",
            journey_label="旅程2b: 补充交流上下文（文字/语音记录）",
        )

    print("\n" + "=" * 70)
    print("  用户旅程验证完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
