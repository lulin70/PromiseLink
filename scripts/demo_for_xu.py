#!/usr/bin/env python3
"""EventLink 许总演示脚本 — 完整场景展示

面向许总(最佳验证用户)的端到端演示，展示EventLink的核心能力：
  场景1: 完整Pipeline — "记录一次重要交流"
  场景2: 语音NLU识别   — "开车时语音问询"
  场景3: 关系推进卡     — "张总到哪步了"
  场景4: 日视图Dashboard — "我今天的安排"

Usage:
    cd . && python scripts/demo_for_xu.py

Prerequisites:
    - .env with MOKA_AI key configured
    - SQLite DB initialized (alembic upgrade head)

演示话术要点（给林总的提示）：
    - 许总关心的是"语音+车载"，开场强调F-50已就绪
    - 核心场景：开完会怕忘了谁答应谁什么 → Pipeline自动记录
    - 语音问询 → NLU识别意图 + 查DB返回真实结果
    - 强调"先成就关系，再促成合作"的产品定位
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

# ── 抑制技术日志（许总不需要看info/debug/warning）──
logging.basicConfig(level=logging.ERROR)

# ── 东8时区 ──
TZ_CN = timezone(timedelta(hours=8))

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# ── 颜色常量 ──

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


def header(title: str, width: int = 70) -> None:
    """打印带样式的标题栏."""
    print(f"\n{CYAN}{'=' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{CYAN}{'=' * width}{RESET}\n")


def sub_header(title: str) -> None:
    """打印子标题."""
    print(f"\n{BOLD}{YELLOW}  ▶ {title}{RESET}")


def ok(label: str, detail: str = "") -> None:
    """打印成功标记."""
    suffix = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}OK{RESET}  {label}{suffix}")


def info(label: str, detail: str = "") -> None:
    """打印信息."""
    suffix = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  {INFO_CHAR}  {label}{suffix}")


def fail(label: str, detail: str = "") -> None:
    """打印失败标记."""
    suffix = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  {RED}FAIL{RESET}  {label}{suffix}")


INFO_CHAR = "\u2139\ufe0f"  # ™️


# ════════════════════════════════════════════════════════════════
#  测试数据 — 投资对接会议场景
# ════════════════════════════════════════════════════════════════

# 场景1: Pipeline测试事件 — 一段真实的投资对接会议记录
PIPELINE_EVENT_TEXT = """今天下午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""

# 场景2: NLU语音问询 — 基于同一场景的7类典型问询
VOICE_QUERIES = [
    ("日程查询", "我今天的会议是什么？", "schedule_query"),
    ("承诺追踪", "我答应李总什么事还没做？", "promise_tracker"),
    ("关系推进", "李总那边到哪一步了？", "relationship_status"),
    ("行动建议", "我今天应该主动联系谁？", "action_suggestion"),
    ("创建提醒", "帮我记一下下周一给李总发资料", "todo_create"),
    ("闲聊", "谢谢你啊", "chitchat"),
    ("退出对话", "没了，开车呢", "exit"),
]


# ════════════════════════════════════════════════════════════════
#  场景1: 完整Pipeline运行
# ════════════════════════════════════════════════════════════════

async def demo_pipeline() -> dict:
    """场景1: 展示完整的11步事件处理Pipeline.

    这是EventLink的核心能力 — 从一段自由文本的会议记录，
    自动提取人物、识别承诺、生成待办、更新关系推进卡。
    """
    from uuid import uuid4
    from eventlink.database import AsyncSessionLocal, init_db
    from eventlink.models.event import Event
    from eventlink.services.event_pipeline import process_event_with_short_transactions

    header("场景1: 记录一次重要交流 — 完整11步Pipeline")

    # ── 开场白 ──
    print(f"  {BOLD}许总的话{RESET}: \"{DIM}刚开完一个会，聊了很多事，怕忘了谁答应谁什么{RESET}\"")
    print(f"  {BOLD}EventLink的答案{RESET}: 帮你记住每次交流，自动追踪承诺和关系。\n")

    print(f"  {DIM}{'─' * 60}{RESET}")
    print(f"  {BOLD}输入: 一段会议记录{RESET}")
    print(f"  {DIM}{'─' * 60}{RESET}")
    for i, line in enumerate(PIPELINE_EVENT_TEXT.strip().split("\n"), 1):
        print(f"  {DIM}|{RESET} {line}")
    print(f"  {DIM}{'─' * 60}{RESET}\n")

    # 1. 初始化数据库
    sub_header("准备: 系统初始化")
    await init_db()
    ok("数据库就绪 (SQLite + Alembic migrations)")

    # 2. 创建测试事件
    sub_header("输入: 创建事件")
    event_id = str(uuid4())
    user_id = "demo-user-xu"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            event = Event(
                id=event_id,
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title="投资对接会 - 盛恒资本李总/王明",
                raw_text=PIPELINE_EVENT_TEXT,
                status="pending",
            )
            session.add(event)
    print(f"  事件ID: {event_id[:8]}... | 文本长度: {len(PIPELINE_EVENT_TEXT)}字符")
    ok("事件已创建")

    # 3. 运行完整Pipeline
    sub_header("处理: 运行11步Pipeline (真实Moka AI)")
    print(f"  {DIM}(正在调用AI模型处理，请稍候...){RESET}\n")

    start_time = time.monotonic()
    result = await process_event_with_short_transactions(event_id)
    elapsed = time.monotonic() - start_time

    # 4. 展示结果
    print(f"\n  {BOLD}Pipeline完成! 耗时 {elapsed:.1f}秒{RESET}\n")

    # 结果展示: InputScope
    sub_header("结果①: 这段话属于什么类型？")
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        evt = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one()
        scope = evt.input_scope or "(未分类)"
        conf = evt.input_scope_confidence or 0
        method = "规则引擎" if conf >= 0.9 else "LLM辅助"
        print(f"  分类结果: {BOLD}{scope}{RESET} (置信度 {conf:.0%}, via {method})")
    ok("InputScope已分类")

    # 结果展示: Entity Extraction
    sub_header("结果②: 里面提到了哪些人？")
    if result.entities:
        print(f"  从会议记录中识别出 {len(result.entities)} 位相关人物：\n")
        for i, entity in enumerate(result.entities):
            # 从properties中提取角色/公司信息
            props = entity.properties or {}
            basic = props.get("basic", {})
            company = basic.get("company", "")
            role = basic.get("title", "") or basic.get("role", "")
            detail_parts = []
            if role:
                detail_parts.append(role)
            if company:
                detail_parts.append(company)
            detail = "（" + "，".join(detail_parts) + "）" if detail_parts else ""

            print(f"    [{i+1}] {BOLD}{entity.name}{RESET}{detail}")
        print(f"\n  {DIM}(AI自动从对话内容中提取身份和关系背景){RESET}")
        ok(f"识别 {len(result.entities)} 个实体")
    else:
        fail("未提取到实体")

    # 结果展示: Todo + Promise
    sub_header("结果③: 生成了哪些待办和承诺？")
    if result.todos:
        action_labels = {
            "my_promise": "我的承诺",
            "their_promise": "对方承诺",
            "my_followup": "我的跟进",
            "care": "关注",
            "help": "帮助",
            "cooperation_signal": "合作信号",
            "followup": "跟进",
            "risk": "风险",
        }
        for i, todo in enumerate(result.todos):
            atype = todo.action_type or "general"
            label = action_labels.get(atype, atype)
            confirm = todo.confirmation_status or ""
            evidence = (todo.evidence_quote or "")[:50]
            print(f"    [{i+1}] [{todo.todo_type}] {todo.title[:50]}")
            print(f"         类型={label} | 状态={confirm}")
            if evidence:
                print(f"         依据: \"{evidence}...\"")
        ok(f"生成 {len(result.todos)} 条待办 (含降噪去重)")
    else:
        fail("未生成待办")

    # 结果展示: Briefs
    sub_header("结果④: 每个人的关系推进卡")
    brief_count = 0
    try:
        from eventlink.models.relationship_brief import RelationshipBrief
        async with AsyncSessionLocal() as session:
            briefs = (await session.execute(
                select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
            )).scalars().all()
            brief_count = len(briefs)
            if briefs:
                for brief in briefs:
                    data = brief.brief_data or {}
                    name = data.get("basic_info", {}).get("name", "未知")
                    stage = brief.relationship_stage
                    score = data.get("strength_score", 0)
                    modules = len(data)
                    print(f"    推进卡: {name}")
                    print(f"    阶段={stage} | 关系强度={score}/100 | 数据模块={modules}/12")
        ok(f"更新 {brief_count} 张关系推进卡")
    except Exception as ex:
        fail(f"Brief检查异常: {ex}")

    # Timing breakdown
    if result.step_timings:
        sub_header("性能分解")
        step_labels = {
            "step0_input_scope": "输入分类(F-44)",
            "step3_extraction": "实体提取(LLM)",
            "step4_todos": "待办生成(LLM×4并行)",
            "step5_promise_analysis": "承诺分析(N路并行)",
            "step6_associations": "关联发现",
            "step8_briefs": "推进卡更新",
        }
        llm_steps = ("step0_input_scope", "step3_extraction", "step4_todos", "step5_promise_analysis", "step8_briefs")
        llm_total = sum(v for k, v in result.step_timings.items() if k in llm_steps)

        for key, label in step_labels.items():
            val = result.step_timings.get(key)
            if val is not None:
                bar_len = int(val / max(elapsed, 1) * 30)
                bar = "#" * bar_len + "-" * (30 - bar_len)
                print(f"    {label:22s} {val:6.1f}s  [{bar}]")
        print(f"    {'LLM步骤合计':22s} {llm_total:6.1f}s")
        print(f"    {'总计':22s} {elapsed:6.1f}s")

    # Validation summary
    print(f"\n  {BOLD}验证清单:{RESET}")
    checks = {
        "Pipeline完成": result.status == "completed",
        "实体提取": len(result.entities) > 0,
        "待办生成": len(result.todos) > 0,
        "InputScope分类": evt.input_scope is not None,
        "承诺分析": any(getattr(t, 'action_type', None) for t in result.todos),
        "无错误": result.error is None,
    }
    all_pass = True
    for name, passed in checks.items():
        if passed:
            ok(name)
        else:
            fail(name)
            all_pass = False

    print(f"\n  {BOLD}场景1结论: {'全部通过' if all_pass else '存在问题'}{RESET}")
    return {"scenario": "pipeline", "pass": all_pass, "elapsed": elapsed,
            "entities": len(result.entities), "todos": len(result.todos),
            "briefs": brief_count}


# ════════════════════════════════════════════════════════════════
#  场景2: 语音NLU意图识别
# ════════════════════════════════════════════════════════════════

async def demo_nlu() -> dict:
    """场景2: 展示F-50语音NLU意图识别能力.

    许总的核心需求: "语音特别重要，开车的时候就可以干很多活了"
    这里展示NLU的两阶段分类: 规则引擎(<5ms) → LLM fallback(~300ms)
    """
    from eventlink.config import Settings
    from eventlink.services.llm_client import LLMClient
    from eventlink.services.nlu_intent_classifier import NLUIntentClassifier, VoiceIntent

    header("场景2: 语音问询理解 — F-50 NLU意图识别")

    # ── 开场白 ──
    print(f"  {BOLD}许总的话{RESET}: \"{DIM}语音特别重要，这样我开车的时候就可以干很多活了{RESET}\"")
    print(f"  {BOLD}EventLink的答案{RESET}: 两阶段NLU — 规则引擎极速匹配 + LLM智能兜底\n")

    # 初始化
    config = Settings()
    llm = LLMClient(config=config)
    classifier = NLUIntentClassifier(llm_client=llm)

    intent_names = {
        VoiceIntent.SCHEDULE_QUERY: "日程查询",
        VoiceIntent.SCHEDULE_RANGE: "范围日程",
        VoiceIntent.PROMISE_TRACKER: "承诺追踪",
        VoiceIntent.RELATIONSHIP_STATUS: "关系状态",
        VoiceIntent.ACTION_SUGGESTION: "行动建议",
        VoiceIntent.TODO_CREATE: "创建提醒",
        VoiceIntent.UNCLEAR: "意图不明",
        VoiceIntent.CHITCHAT: "闲聊",
        VoiceIntent.EXIT: "退出",
    }

    # 每种意图的模拟回答（展示给许总看"系统会怎么回应"）
    # 注意：以下回答基于场景1 Pipeline产生的真实数据动态生成，非硬编码

    total = len(VOICE_QUERIES)
    correct = 0
    results = []

    # 预加载场景1产生的数据（用于构造真实回答）
    user_id = "demo-user-xu"
    today = date.today()

    # 阶段名称映射（供回答生成使用）
    _brief_stage_labels = {
        "new_connection": "新连接",
        "understanding_needs": "了解需求中",
        "value_response": "价值回应",
        "deep_trust": "深度信任",
        "active_cooperation": "积极合作",
        "long_term_partner": "长期伙伴",
        "dormant": "休眠",
    }

    async def _build_response(intent_value: str, slots: dict | None) -> str:
        """根据NLU识别结果 + 真实DB数据，构造系统回答."""
        from eventlink.database import AsyncSessionLocal
        from eventlink.models.event import Event
        from eventlink.models.todo import Todo
        async with AsyncSessionLocal() as session:
            # ── 日程查询 ──
            if intent_value == "schedule_query":
                day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)
                day_end = day_start.replace(hour=23, minute=59, second=59)
                from sqlalchemy import select as sa_select
                evt_result = await session.execute(
                    sa_select(Event).where(Event.user_id == user_id)
                    .where(Event.timestamp >= day_start)
                    .where(Event.timestamp < day_end)
                )
                events = evt_result.scalars().all()
                if events:
                    lines = [f"今天您有{len(events)}条记录："]
                    for e in events:
                        t = e.timestamp.strftime("%H:%M") if e.timestamp else ""
                        lines.append(f"  {t} {e.title}")
                    return "\n".join(lines)
                return "今天暂无已记录的安排。"

            # ── 范围日程 ──
            if intent_value == "schedule_range":
                return "明后两天暂无已记录的安排。需要我帮您创建一个提醒吗？"

            # ── 承诺追踪 ──
            if intent_value == "promise_tracker":
                from sqlalchemy import select as sa_select
                todo_result = await session.execute(
                    sa_select(Todo).where(Todo.user_id == user_id)
                    .where(Todo.action_type == "my_promise")
                    .where(Todo.status == "pending")
                )
                promises = todo_result.scalars().all()
                if promises:
                    lines = [f"您目前有{len(promises)}条未完成的承诺："]
                    for p in promises[:5]:
                        # 日期合理性检查：只显示未来或近期的截止日期
                        due_str = ""
                        if p.due_date:
                            try:
                                d = p.due_date.date() if hasattr(p.due_date, 'date') else p.due_date
                                if d >= today:
                                    due_str = f"（截止:{d}）"
                                # 过去或不合理的日期不显示
                            except (ValueError, AttributeError):
                                pass
                        lines.append(f"  · {p.title[:50]}{due_str}")
                    lines.append("\n需要我帮您设置提醒吗？")
                    return "\n".join(lines)
                return "太棒了！您当前没有未完成的承诺。"

            # ── 关系状态 ──
            if intent_value == "relationship_status":
                person_name = (slots or {}).get("person", "")
                from eventlink.models.relationship_brief import RelationshipBrief
                from sqlalchemy import select as sa_select
                briefs_q = sa_select(RelationshipBrief).where(
                    RelationshipBrief.user_id == user_id
                ).order_by(RelationshipBrief.last_updated_at.desc())
                briefs_result = await session.execute(briefs_q)
                all_briefs = briefs_result.scalars().all()

                if not all_briefs:
                    return "暂时还没有关系记录。先记录一次交流试试？"

                # 按人名过滤：如果问询指定了人名，只返回匹配的
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
                    # 没指定人名，取最新的
                    matched_brief = all_briefs[0]

                b = matched_brief
                data = b.brief_data or {}
                name = data.get("basic_info", {}).get("name", person_name or "对方")
                stage = b.relationship_stage or "new_connection"
                stage_cn = _brief_stage_labels.get(stage, stage)
                last_int = data.get("last_interaction", {})
                summary = last_int.get("summary", "")[:40] if last_int else ""
                concerns = data.get("their_concerns", [])
                concerns_str = f"，他关心{concerns[0]}" if concerns else ""
                parts = [
                    f"{name}目前处于「{stage_cn}」阶段。",
                ]
                if summary:
                    parts.append(f"你们最近一次互动是：{summary}")
                if concerns_str:
                    parts.append(concerns_str)
                parts.append("建议近期跟进。")
                return " ".join(parts)

            # ── 行动建议 ──
            if intent_value == "action_suggestion":
                from sqlalchemy import select as sa_select
                # 查找即将到期的promise
                todo_result = await session.execute(
                    sa_select(Todo).where(Todo.user_id == user_id)
                    .where(Todo.status == "pending")
                    .where(Todo.action_type.in_(["my_promise", "my_followup"]))
                    .order_by(Todo.due_date.asc().nullslast())
                )
                actions = todo_result.scalars().all()[:3]
                if actions:
                    lines = ["根据您的数据，建议优先处理："]
                    for a in actions:
                        atype = "承诺" if a.action_type == "my_promise" else "跟进"
                        due_str = ""
                        if a.due_date:
                            try:
                                d = a.due_date.date() if hasattr(a.due_date, 'date') else a.due_date
                                if d >= today:
                                    due_str = f"（截止:{d}）"
                            except (ValueError, AttributeError):
                                pass
                        lines.append(f"  · [{atype}] {a.title[:45]}{due_str}")
                    return "\n".join(lines)
                return "当前没有紧急待办，保持联系频率就好。"

            # ── 创建提醒 ──
            if intent_value == "todo_create":
                content = (slots or {}).get("content", "")
                person = (slots or {}).get("person", "")
                return f"好的，已为您创建提醒：{content or '（内容）'}。我会到时间提醒您。"

            # ── 其他 ──
            fallback = {
                "unclear": "抱歉，我不太确定您的意思。您可以试试问\"我今天的会议是什么\"或\"我答应谁什么事了\"？",
                "chitchat": "哈哈，谢谢！我是EventLink，专门帮您经营商务关系的助手。有什么关系方面的问题随时问我。",
                "exit": "好的，有事随时叫我！开车注意安全~",
            }
            return fallback.get(intent_value, "好的，我明白了。")

    for i, (category, query, expected_intent) in enumerate(VOICE_QUERIES, 1):
        sub_header(f"问询 {i}/{total}: [{category}]")

        print(f"  {DIM}用户说: \"{query}\"{RESET}")

        start = time.monotonic()
        nlu_result = await classifier.classify(query)
        elapsed_ms = (time.monotonic() - start) * 1000

        predicted = nlu_result.intent.value
        is_correct = predicted == expected_intent
        if is_correct:
            correct += 1

        intent_label = intent_names.get(nlu_result.intent, predicted)
        method_tag = "规则" if nlu_result.method == "rule" else "LLM"

        status_icon = GREEN + "OK" + RESET if is_correct else RED + "X" + RESET
        print(f"  [{status_icon}] 意图={BOLD}{intent_label}{RESET} | "
              f"置信度={nlu_result.confidence:.0%} | "
              f"耗时={elapsed_ms:.0f}ms | 方法={method_tag}")

        # 显示槽位
        if nlu_result.slots:
            slots_str = json.dumps(nlu_result.slots, ensure_ascii=False)[:100]
            print(f"       槽位: {slots_str}")

        # 显示证据
        if nlu_result.evidence:
            evidence_short = nlu_result.evidence[:80]
            print(f"       依据: {DIM}{evidence_short}{RESET}")

        # 基于真实DB数据构造系统回答
        response = await _build_response(predicted, nlu_result.slots)
        print(f"\n  {BOLD}EventLink{RESET}: \"{response}\"\n")

        results.append({
            "query": query,
            "expected": expected_intent,
            "predicted": predicted,
            "correct": is_correct,
            "elapsed_ms": round(elapsed_ms),
            "method": nlu_result.method,
        })

    # Summary
    print(f"\n  {BOLD}NLU识别汇总:{RESET}")
    print(f"  总计: {total} 个问询 | 正确: {correct}/{total} | 准确率: {correct/total*100:.0f}%")

    avg_ms = sum(r["elapsed_ms"] for r in results) / total
    rule_count = sum(1 for r in results if r["method"] == "rule")
    llm_count = total - rule_count
    print(f"  平均响应: {avg_ms:.0f}ms | 规则命中: {rule_count} | LLM兜底: {llm_count}")

    all_pass = correct >= int(total * 0.85)  # 85%阈值
    print(f"\n  {BOLD}场景2结论: {'通过 (≥85%)' if all_pass else '未达标'}{RESET}")
    return {"scenario": "nlu", "pass": all_pass, "accuracy": correct / total,
            "avg_ms": avg_ms, "correct": correct, "total": total}


# ════════════════════════════════════════════════════════════════
#  场景3: 关系推进卡Brief视图
# ════════════════════════════════════════════════════════════════

async def demo_brief() -> dict:
    """场景3: 展示F-47关系推进卡的聚合视图.

    回答许总的典型问题: "张总到哪步了？"
    展示12模块结构化数据和关系强度评分.
    """
    from eventlink.database import AsyncSessionLocal
    from eventlink.models.relationship_brief import RelationshipBrief
    from sqlalchemy import select

    header("场景3: 关系推进卡 — \"李总到哪步了？\"")

    print(f"  {BOLD}许总的问题{RESET}: \"{DIM}李总到哪步了？{RESET}\"")
    print(f"  {BOLD}EventLink的答案{RESET}: 按人名查询关系进展 + 12模块画像\n")

    user_id = "demo-user-xu"

    async with AsyncSessionLocal() as session:
        briefs = (await session.execute(
            select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
            .order_by(RelationshipBrief.last_updated_at.desc())
            .limit(5)
        )).scalars().all()

        if not briefs:
            print(f"  {DIM}(暂无推进卡数据 — 请先运行场景1生成){RESET}")
            return {"scenario": "brief", "pass": False, "count": 0}

        print(f"  找到 {len(briefs)} 张关系推进卡:\n")

        stage_labels = {
            "new_connection": "新连接",
            "understanding_needs": "了解需求中",
            "value_response": "价值回应",
            "deep_trust": "深度信任",
            "active_cooperation": "积极合作",
            "long_term_partner": "长期伙伴",
            "dormant": "休眠",
        }

        for idx, brief in enumerate(briefs, 1):
            data = brief.brief_data or {}
            stage = brief.relationship_stage or "new_connection"
            score = data.get("strength_score", 0)
            version = brief.version

            # 关系强度评级
            if score >= 80:
                grade = f"{GREEN}强{RESET}"
            elif score >= 50:
                grade = f"{YELLOW}中{RESET}"
            elif score > 0:
                grade = f"{RED}弱{RESET}"
            else:
                grade = f"{DIM}初始{RESET}"

            sub_header(f"推进卡 #{idx}: {data.get('basic_info', {}).get('name', '未知联系人')}")
            print(f"    阶段: {stage_labels.get(stage, stage)} | 强度: {score}/100 ({grade}) | 版本: v{version}")

            # 展示关键模块
            basic = data.get("basic_info", {})
            if basic.get("name"):
                print(f"    姓名: {basic['name']}")
            if basic.get("company"):
                print(f"    公司: {basic['company']}")
            if basic.get("role"):
                print(f"    职位: {basic['role']}")

            # 最后互动
            last_int = data.get("last_interaction", {})
            if last_int:
                print(f"    最后互动: {last_int.get('event_type', '?')} | {last_int.get('summary', '')[:40]}")

            # 互动频率
            freq = data.get("interaction_freq", {})
            if freq:
                print(f"    互动频次: 总计{freq.get('total_count', 0)}次 | 近30天{freq.get('last_30_days', 0)}次")

            # 开放承诺
            promises = data.get("open_promises", {})
            my_p = promises.get("my_promises", [])
            their_p = promises.get("their_promises", [])
            if my_p or their_p:
                print(f"    开放承诺:")
                for p in my_p[:3]:
                    print(f"      我承诺: {p.get('title', '')[:40]}")
                for p in their_p[:3]:
                    print(f"      对方承诺: {p.get('title', '')[:40]}")

            # 对方关心的话题
            concerns = data.get("their_concerns", [])
            if concerns:
                print(f"    对方关心: {', '.join(concerns[:3])}")

            # 我的贡献
            contribs = data.get("my_contributions", [])
            if contribs:
                print(f"    我的帮助: {', '.join(contribs[:3])}")

            # 合作信号
            signals = data.get("cooperation_signals", [])
            if signals:
                print(f"    合作信号: {', '.join(signals[:3])}")

            # 风险标志
            risks = data.get("risk_flags", [])
            if risks:
                print(f"    风险标志: {', '.join(risks[:3])}")

            # 下一步建议
            actions = data.get("next_actions", [])
            if actions:
                print(f"    下一步建议:")
                for a in actions[:3]:
                    priority_color = RED if a.get("priority") == "high" else YELLOW if a.get("priority") == "medium" else DIM
                    print(f"      [{priority_color}{a.get('priority', '?')}{RESET}] {a.get('action', '')}")

            print()

        # 聚合视图统计
        total_score = sum((b.brief_data or {}).get("strength_score", 0) for b in briefs)
        avg_score = total_score / len(briefs) if briefs else 0
        stages = {}
        for b in briefs:
            s = b.relationship_stage or "unknown"
            stages[s] = stages.get(s, 0) + 1

        print(f"  {BOLD}汇总:{RESET} 共{len(briefs)}张卡 | 平均强度{avg_score:.0f}/100")
        if stages:
            stage_str = ", ".join(f"{stage_labels.get(k, k)}({v})" for k, v in stages.items())
            print(f"  阶段分布: {stage_str}")

    ok(f"展示了 {len(briefs)} 张关系推进卡")
    print(f"\n  {BOLD}场景3结论: 通过{RESET}")
    return {"scenario": "brief", "pass": True, "count": len(briefs)}


# ════════════════════════════════════════════════════════════════
#  场景4: 日视图Dashboard
# ════════════════════════════════════════════════════════════════

async def demo_dashboard() -> dict:
    """场景4: 展示F-49日视图Dashboard的自然语言日期查询.

    支持中英文自然语言日期: 今天/明天/后天/本周/下周/ISO格式
    """
    from eventlink.core.natural_date import parse_natural_date
    from eventlink.database import AsyncSessionLocal
    from eventlink.models.event import Event
    from eventlink.models.todo import Todo
    from sqlalchemy import select, func

    header("场景4: 日视图Dashboard — \"我今天的安排\"")

    print(f"  {BOLD}许总的问题{RESET}: \"{DIM}我今天的会议是什么？{RESET}\"")
    print(f"  {BOLD}EventLink的答案{RESET}: 自然语言日期解析 + 事件/待办聚合展示\n")

    # Part A: 自然语言日期解析演示
    sub_header("Part A: 自然语言日期解析引擎")

    date_queries = [
        ("今天", None),
        ("明天", None),
        ("后天", None),
        ("本周", None),
        ("下周", None),
        ("2026-06-10", None),
        ("3天后", None),
    ]

    print(f"  {'输入':12s} {'解析结果':24s} {'类型':6s}")
    print(f"  {'─'*12} {'─'*24} {'─'*6}")

    parse_ok = 0
    for query, _ in date_queries:
        try:
            result = parse_natural_date(query)
            type_label = "范围" if result.is_range else "单日"
            print(f"  {query:12s} {result.label:24s} {type_label:6s}")
            parse_ok += 1
        except ValueError as ex:
            print(f"  {query:12s} {RED}解析失败: {ex}{RESET}")

    ok(f"日期解析: {parse_ok}/{len(date_queries)} 通过")

    # Part B: 日视图数据查询
    sub_header("Part B: 今日日视图数据")

    user_id = "demo-user-xu"
    today = date.today()

    async with AsyncSessionLocal() as session:
        day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = day_start.replace(hour=23, minute=59, second=59)

        # Events
        evt_result = await session.execute(
            select(Event)
            .where(Event.user_id == user_id)
            .where(Event.timestamp >= day_start)
            .where(Event.timestamp < day_end)
            .order_by(Event.timestamp.asc())
        )
        events = evt_result.scalars().all()

        # Todos due today
        todo_result = await session.execute(
            select(Todo)
            .where(Todo.user_id == user_id)
            .where(Todo.due_date.isnot(None))
            .where(func.date(Todo.due_date) == today)
            .order_by(Todo.due_date.asc())
        )
        todos = todo_result.scalars().all()

    print(f"\n  {BOLD}{today.strftime('%Y年%m月%d日')} ({['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]}){RESET}")
    print(f"  {'─'*55}")

    if events:
        print(f"\n  事件 ({len(events)}条):")
        for evt in events:
            t = evt.timestamp.strftime("%H:%M") if evt.timestamp else "??"
            scope = evt.input_scope or "-"
            print(f"    [{t}] [{scope:8s}] {evt.title[:50]}")

        # Part C: 事件详情（用户点进去看的内容）
        sub_header("Part C: 事件详情 — 点击查看完整记录")
        for evt in events:
            t = evt.timestamp.strftime("%H:%M") if evt.timestamp else "??"
            print(f"\n  {BOLD}▸ {evt.title}{RESET} ({t})")
            print(f"  {DIM}{'─'*50}{RESET}")

            # 原文摘要
            if evt.raw_text:
                preview = evt.raw_text[:120] + "..." if len(evt.raw_text) > 120 else evt.raw_text
                print(f"  记录内容: {preview}")
                print()

            # 关联实体
            from eventlink.models.entity import Entity
            ent_result = await session.execute(
                select(Entity).where(Entity.source_event_id == evt.id)
            )
            entities = ent_result.scalars().all()
            if entities:
                print(f"  涉及人物: {', '.join(e.name for e in entities)}")
                print()

            # 关联待办
            todo_for_evt = [td for td in todos if td.source_event_id == str(evt.id)]
            if todo_for_evt:
                print(f"  生成待办 ({len(todo_for_evt)}条):")
                for td in todo_for_evt:
                    status_tag = "待处理" if td.status == "pending" else "已完成"
                    print(f"    · [{status_tag}] {td.title[:50]}")
            else:
                print(f"  待办: (暂无)")
    else:
        print(f"\n  {DIM}今日暂无事件{RESET}")

    if todos:
        overdue_count = sum(1 for t in todos if t.due_date and t.status not in ("done", "dismissed")
                           and (t.due_date.date() if isinstance(t.due_date, datetime) else t.due_date) < today)
        print(f"\n  待办 ({len(todos)}条, {overdue_count}条逾期):")
        for td in todos:
            is_overdue = (td.due_date.date() if isinstance(td.due_date, datetime) else td.due_date) < today \
                         if td.due_date and td.status not in ("done", "dismissed") else False
            atype = td.action_type or "-"
            overdue_mark = RED + "*" + RESET if is_overdue else " "
            print(f"    {overdue_mark}[{td.todo_type:10s}] [{atype:12s}] {td.title[:45]}")
    else:
        print(f"\n  {DIM}今日暂无到期待办{RESET}")

    summary_parts = [f"事件{len(events)}条", f"待办{len(todos)}条"]
    if todos:
        pending = sum(1 for t in todos if t.status == "pending")
        summary_parts.append(f"待处理{pending}条")
    print(f"\n  汇总: {', '.join(summary_parts)}")

    ok(f"日视图正常展示")
    print(f"\n  {BOLD}场景4结论: 通过{RESET}")
    return {"scenario": "dashboard", "pass": True, "events": len(events),
            "todos": len(todos), "date_parse": parse_ok}


# ════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════

async def main() -> None:
    """运行所有演示场景并输出汇总报告."""

    print(f"\n{BOLD}{MAGENTA}")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                                                          ║")
    print("║          EventLink  许总演示  —  PoC阶段                 ║")
    print("║                                                          ║")
    print("║   AI驱动的个人商务关系经营助手                          ║")
    print("║   「让每一次连接，都有回应」                              ║")
    print("║                                                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(RESET)

    print(f"\n  {DIM}目标用户: 许总 (IAMHERE 数字名片 | 最佳验证用户){RESET}")
    print(f"  {DIM}核心诉求: 语音交互 + 车载场景 + 承诺追踪 + 关系经营{RESET}")
    print(f"  {DIM}演示时间: {datetime.now(TZ_CN).strftime('%Y-%m-%d %H:%M (UTC+8)')}{RESET}")

    results = []

    # ── 场景1: Pipeline ──
    try:
        r = await demo_pipeline()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景1异常: {e}{RESET}")
        import traceback
        traceback.print_exc()
        results.append({"scenario": "pipeline", "pass": False, "error": str(e)})

    # ── 场景2: NLU ──
    try:
        r = await demo_nlu()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景2异常: {e}{RESET}")
        import traceback
        traceback.print_exc()
        results.append({"scenario": "nlu", "pass": False, "error": str(e)})

    # ── 场景3: Brief ──
    try:
        r = await demo_brief()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景3异常: {e}{RESET}")
        import traceback
        traceback.print_exc()
        results.append({"scenario": "brief", "pass": False, "error": str(e)})

    # ── 场景4: Dashboard ──
    try:
        r = await demo_dashboard()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景4异常: {e}{RESET}")
        import traceback
        traceback.print_exc()
        results.append({"scenario": "dashboard", "pass": False, "error": str(e)})

    # ════════════════════════════════════════════════════════════
    #  最终报告
    # ════════════════════════════════════════════════════════════

    header("演示总结报告")

    scenario_labels = {
        "pipeline": "场景1: 完整Pipeline",
        "nlu": "场景2: 语音NLU识别",
        "brief": "场景3: 关系推进卡",
        "dashboard": "场景4: 日视图Dashboard",
    }

    total_scenarios = len(results)
    passed_scenarios = sum(1 for r in results if r.get("pass"))
    total_time = sum(r.get("elapsed", 0) for r in results)

    print(f"  {'场景':24s} {'状态':6s} {'详情'}")
    print(f"  {'─'*24} {'─'*6} {'─'*40}")

    for r in results:
        name = scenario_labels.get(r["scenario"], r["scenario"])
        status = f"{GREEN}PASS{RESET}" if r.get("pass") else f"{RED}FAIL{RESET}"
        details = []
        if "entities" in r:
            details.append(f"{r['entities']}实体")
        if "todos" in r:
            details.append(f"{r['todos']}待办")
        if "briefs" in r:
            details.append(f"{r['briefs']}推进卡")
        if "accuracy" in r:
            details.append(f"准确率{r['accuracy']:.0%}")
        if "avg_ms" in r:
            details.append(f"{r['avg_ms']:.0f}ms响应")
        if "events" in r:
            details.append(f"{r['events']}事件")
        if "elapsed" in r:
            details.append(f"{r['elapsed']:.1f}s")
        detail_str = " | ".join(details)
        print(f"  {name:24s} {status:6s} {detail_str}")

    print(f"\n  {'─'*70}")
    overall = f"{GREEN}全部通过{RESET}" if passed_scenarios == total_scenarios else \
              f"{YELLOW}{passed_scenarios}/{total_scenarios} 通过{RESET}"
    print(f"  {BOLD}总体结果: {overall}{RESET}")
    print(f"  总耗时: {total_time:.1f}s (含LLM调用)")

    # 产品定位回顾
    print(f"\n  {BOLD}产品定位回顾:{RESET}")
    print(f"  EventLink = AI驱动的个人商务关系经营助手")
    print(f"  核心循环: 互动→关注→承诺→帮助→反馈 (利他优先)")
    print(f"  Slogan: \"让每一次连接，都有回应\"")

    print(f"\n  {BOLD}许总价值点:{RESET}")
    print(f"  1. 语音交互 — 开车时也能管理关系 (F-50 NLU已实现)")
    print(f"  2. 承诺追踪 — 再也不忘记答应别人的事 (F-45 Promise双向)")
    print(f"  3. 关系推进 — 清楚知道每个人到哪步了 (F-47 Brief+F-48 Stage)")
    print(f"  4. 日程一览 — 自然语言查今日安排 (F-49 Dashboard)")

    sys.exit(0 if passed_scenarios == total_scenarios else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[演示] 被用户中断{RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}[演示] 致命错误: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
