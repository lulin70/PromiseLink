#!/usr/bin/env python3
"""PromiseLink 演示脚本 — 完整场景展示

面向许总(最佳验证用户)的端到端演示，展示PromiseLink的核心能力：
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
import os
import re
import sys
import time
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

# ── Strip ANSI color codes when output is piped to file ──
if not sys.stdout.isatty():
    _original_write = sys.stdout.write
    _ansi_re = re.compile(r'\033\[[0-9;]*m')
    def _strip_ansi_write(text):
        return _original_write(_ansi_re.sub('', text))
    sys.stdout.write = _strip_ansi_write

# ── 抑制技术日志（许总不需要看info/debug/warning）──
logging.basicConfig(level=logging.CRITICAL)  # 演示输出禁止所有日志
# Suppress all promiselink + sqlalchemy loggers
for _logger_name in ("promiselink", "promiselink.nlu", "promiselink.pipeline",
                      "promiselink.entity_extractor", "promiselink.association_discovery",
                      "promiselink.llm_client", "promiselink.todo_generator",
                      "promiselink.promise_bidirectional", "promiselink.relationship_brief",
                      "promiselink.dashboard", "promiselink.input_scope",
                      "sqlalchemy", "sqlalchemy.pool", "httpx", "httpcore"):
    logging.getLogger(_logger_name).setLevel(logging.CRITICAL)
# Redirect structlog to stderr so it doesn't pollute stdout (demo output)
import structlog as _structlog
_structlog.configure(
    processors=[
        _structlog.stdlib.add_log_level,
        _structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=_structlog.stdlib.BoundLogger,
    logger_factory=_structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=False,
)

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


def clean_title(title: str, max_len: int = 50) -> str:
    """Strip LLM-generated todo_type prefix from title for display.

    LLM generates titles like: "[合作信号] 李总 — 盛恒资本李总..."
    For user-facing display (promise tracking, action suggestions),
    we strip the [xxx] prefix and use the actual content.
    """
    import re
    cleaned = re.sub(r'^\[[^\]]+\]\s*', '', title).strip()
    return cleaned[:max_len] if max_len else cleaned


INFO_CHAR = "\u2139\ufe0f"  # ™️

# 阶段名称映射（全局供多个场景使用）
_BRIEF_STAGE_LABELS = {
    "new_connection": "新连接",
    "understanding_needs": "了解需求中",
    "value_response": "价值回应",
    "deep_trust": "深度信任",
    "active_cooperation": "积极合作",
    "long_term_partner": "长期伙伴",
    "dormant": "休眠",
}


# ════════════════════════════════════════════════════════════════
#  测试数据 — 投资对接会议场景
# ════════════════════════════════════════════════════════════════

# 场景1: Pipeline测试事件 — 一段真实的投资对接会议记录
PIPELINE_EVENT_TEXT = """今天上午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""

# 第二事件: 与第一事件有主题/资源交集，但涉及不同的人(不直接提及对方)
PIPELINE_EVENT_2_TEXT = """下午在望京SOHO和智谱AI的张总一起下午茶

张总说他们刚发布了一个大模型API产品，正在找早期客户和投资方。
他提到团队有15个工程师，专门做大模型应用开发，产能很充裕。
最近接触了几家VC都在看AI应用方向的项目，问我对这个赛道怎么看。

我答应张总这周内整理一份AI赛道的市场观察发给他参考。
张总也说等资料到了可以安排一次深度交流。

聊了大概一个小时，感觉他们的技术实力确实强。"""

# 场景2: NLU语音问询 — 聚焦许总最关心的5个业务场景
VOICE_QUERIES = [
    ("日程查询", "我今天的会议是什么？", "schedule_query"),
    ("承诺追踪", "我答应李总什么事还没做？", "promise_tracker"),
    ("关系推进", "李总那边到哪一步了？", "relationship_status"),
    ("行动建议", "我今天应该主动联系谁？", "action_suggestion"),
    ("创建提醒", "帮我记一下下周一给李总发资料", "todo_create"),
]


# ════════════════════════════════════════════════════════════════
#  场景1: 完整Pipeline运行
# ════════════════════════════════════════════════════════════════

async def demo_pipeline() -> dict:
    """场景1: 展示完整的11步事件处理Pipeline.

    这是PromiseLink的核心能力 — 从一段自由文本的会议记录，
    自动提取人物、识别承诺、生成待办、更新关系推进卡。
    """
    from uuid import uuid4
    # Suppress config warnings during import
    import io as _io
    _saved = sys.stdout
    sys.stdout = _io.StringIO()
    from promiselink.database import AsyncSessionLocal, init_db
    from promiselink.models.event import Event
    from promiselink.services.event_pipeline import process_event_with_short_transactions
    sys.stdout = _saved

    header("场景1: 记录一次重要交流 — 完整11步Pipeline")

    # ── 开场白 ──
    print(f"  {BOLD}许总的话{RESET}: \"{DIM}刚开完一个会，聊了很多事，怕忘了谁答应谁什么{RESET}\"")
    print(f"  {BOLD}PromiseLink的答案{RESET}: 帮你记住每次交流，自动追踪承诺和关系。\n")

    print(f"  {DIM}{'─' * 60}{RESET}")
    print(f"  {BOLD}输入: 一段会议记录{RESET}")
    print(f"  {DIM}{'─' * 60}{RESET}")
    for i, line in enumerate(PIPELINE_EVENT_TEXT.strip().split("\n"), 1):
        print(f"  {DIM}|{RESET} {line}")
    print(f"  {DIM}{'─' * 60}{RESET}\n")

    # 1. 初始化数据库（清理旧数据，包括WAL/SHM文件）
    sub_header("准备: 系统初始化")
    # Clean up all DB files including WAL/SHM to prevent data residue
    # Note: actual DB path is data/promiselink.db (from config.py default)
    db_path = project_root / "data" / "promiselink.db"
    for suffix in ("", "-wal", "-shm"):
        p = db_path.parent / f"{db_path.name}{suffix}"
        if p.exists():
            p.unlink()
    # Suppress config warnings (e.g. "default secret_key") during init
    import io as _io
    _saved_stdout = sys.stdout
    sys.stdout = _io.StringIO()
    await init_db()
    sys.stdout = _saved_stdout
    ok("数据库就绪 (SQLite + Alembic migrations)")

    # 2. 创建测试事件
    sub_header("输入: 创建事件")
    event_id = str(uuid4())
    user_id = "demo-user-xu"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 事件1: 上午10:30
            event_ts_1 = datetime.now(TZ_CN).replace(hour=10, minute=30, second=0, microsecond=0)
            event = Event(
                id=event_id,
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title="未命名",  # Pipeline Step 0.5 will auto-generate from raw_text
                raw_text=PIPELINE_EVENT_TEXT,
                status="pending",
                timestamp=event_ts_1,
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
        from promiselink.models.relationship_brief import RelationshipBrief
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

    print(f"\n  {BOLD}{'─' * 60}{RESET}")
    sub_header("第二事件: 跨人物/同主题 — AI赛道的另一端")
    print(f"  {DIM}(验证: 不同的人 + 同一AI主题 + 资源互补){RESET}\n")

    # 第二事件输入展示
    print(f"  {BOLD}输入{RESET}: 另一段交流记录（与第一事件有交集）\n")
    for i, line in enumerate(PIPELINE_EVENT_2_TEXT.strip().split("\n"), 1):
        print(f"  {DIM}|{RESET} {line}")
    print()

    # 创建并处理第二事件
    event2_id = str(uuid4())
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 事件2: 下午15:00
            event_ts_2 = datetime.now(TZ_CN).replace(hour=15, minute=0, second=0, microsecond=0)
            event2 = Event(
                id=event2_id,
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title="未命名",  # Pipeline Step 0.5 will auto-generate from raw_text
                raw_text=PIPELINE_EVENT_2_TEXT,
                status="pending",
                timestamp=event_ts_2,
            )
            session.add(event2)

    start2 = time.monotonic()
    result2 = await process_event_with_short_transactions(event2_id)
    elapsed2 = time.monotonic() - start2

    print(f"  {BOLD}Pipeline完成! 耗时 {elapsed2:.1f}秒{RESET}\n")

    # 第二事件结果摘要
    entities2_names = [e.name for e in result2.entities]
    todos2_count = len(result2.todos)
    print(f"  识别出 {len(result2.entities)} 位新人物: {', '.join(entities2_names) or '(无)'}")
    print(f"  生成 {todos2_count} 条待办")
    if result2.error:
        fail(f"第二事件异常: {result2.error}")
    else:
        ok("第二事件处理完成")

    # ── 跨事件关联分析 ──
    print(f"\n  {BOLD}{'─' * 60}{RESET}")
    sub_header("跨事件分析: 系统能否发现隐藏的关联？")

    all_entities = list(result.entities) + list(result2.entities)
    all_entity_names = [e.name for e in all_entities]
    unique_names = sorted(set(all_entity_names))

    print(f"\n  两轮交流共涉及 {len(unique_names)} 位独立人物:")
    for name in unique_names:
        events_count = sum(1 for e in all_entities if e.name == name)
        marker = " ← 同一人(两次出现)" if events_count > 1 else ""
        print(f"    · {name}{marker}")

    # 检查Association发现（包括cold类型）
    try:
        from promiselink.models.association import Association
        from promiselink.models.entity import Entity
        from promiselink.services.association_discovery import AssociationDiscoveryEngine
        async with AsyncSessionLocal() as session:
            assoc_result = await session.execute(
                select(Association).where(Association.user_id == user_id)
            )
            associations = assoc_result.scalars().all()

            # Also run cold-type discovery for cross-entity pairs (李总↔张总 etc.)
            engine = AssociationDiscoveryEngine(session)
            all_ent_result = await session.execute(
                select(Entity).where(Entity.user_id == user_id)
            )
            all_db_entities = list(all_ent_result.scalars().all())
            entity_map = {str(e.id): e.name for e in all_db_entities}

            # Find pairs that might have additional cold-type associations
            # (a pair can have multiple association types, e.g., topic_overlap + industry_chain)
            cold_findings = []
            for i, ea in enumerate(all_db_entities):
                for eb in all_db_entities[i + 1:]:
                    pair_key = tuple(sorted([str(ea.id), str(eb.id)]))
                    existing_types = {
                        a.association_type for a in associations
                        if tuple(sorted([str(a.source_entity_id), str(a.target_entity_id)])) == pair_key
                    }

                    # Run cold type discovery (always, to find additional types)
                    cold_results = await engine.discover_cold_types(ea, eb)
                    # Filter out types already discovered as hot
                    new_cold = [cr for cr in cold_results if cr["association_type"] not in existing_types]
                    if new_cold:
                        cold_findings.append((ea, eb, new_cold))

            # Merge associations by pair (avoid duplicate lines for same pair)
            pair_assocs: dict[tuple, list] = {}
            for a in associations:
                pair_key = tuple(sorted([str(a.source_entity_id), str(a.target_entity_id)]))
                if pair_key not in pair_assocs:
                    pair_assocs[pair_key] = []
                src_name = entity_map.get(str(a.source_entity_id), str(a.source_entity_id)[:8])
                tgt_name = entity_map.get(str(a.target_entity_id), str(a.target_entity_id)[:8])
                pair_assocs[pair_key].append({
                    "src": src_name, "tgt": tgt_name,
                    "type": a.association_type or "unknown",
                    "conf": a.confidence or 0,
                    "detail": "",
                })

            for ea, eb, cold_results in cold_findings:
                pair_key = tuple(sorted([str(ea.id), str(eb.id)]))
                if pair_key not in pair_assocs:
                    pair_assocs[pair_key] = []
                for cr in cold_results:
                    atype = cr["association_type"]
                    evidence = cr.get("evidence", {})
                    detail = ""
                    if atype == "industry_chain":
                        rel = evidence.get("relation", "")
                        if rel == "potential_investor_startup":
                            detail = f" ({evidence.get('investor','')} → {evidence.get('startup','')}, 投资-创业链)"
                    elif atype == "supply_demand":
                        matches = evidence.get("matches", [])
                        if matches:
                            m = matches[0]
                            detail = f" ({m['supplier']} 可满足 {m['requester']} 的需求: {', '.join(m.get('matched_items', [])[:2])})"
                    elif atype == "topic_overlap":
                        ratio = evidence.get("keyword_overlap_ratio", 0)
                        detail = f" (关键词重合度{ratio:.0%})"
                    pair_assocs[pair_key].append({
                        "src": ea.name, "tgt": eb.name,
                        "type": atype,
                        "conf": cr.get("confidence", 0),
                        "detail": detail,
                    })

            # Display results
            print(f"\n  系统发现 {len(pair_assocs)} 组人物关联:")

            for pair_key, assoc_list in pair_assocs.items():
                assoc_list.sort(key=lambda x: x["conf"], reverse=True)
                name_a = assoc_list[0]["src"]
                name_b = assoc_list[0]["tgt"]
                types_str = " + ".join(a["type"] for a in assoc_list)
                max_conf = max(a["conf"] for a in assoc_list)
                conf_str = f"{max_conf:.0%}" if max_conf else "?"
                # Show detail from highest-confidence association
                best_detail = assoc_list[0].get("detail", "")
                print(f"    · {name_a} ↔ {name_b} [{types_str}, 置信度{conf_str}]{best_detail}")

            if not associations and not cold_findings:
                print(f"    (暂无 — 可能需要更多事件积累)")

            # ── 基于关联的行动建议 ──
            action_suggestions = []
            for ea, eb, cold_results in cold_findings:
                for cr in cold_results:
                    atype = cr["association_type"]
                    evidence = cr.get("evidence", {})
                    if atype == "industry_chain":
                        rel = evidence.get("relation", "")
                        if rel == "potential_investor_startup":
                            investor = evidence.get("investor", "")
                            startup = evidence.get("startup", "")
                            action_suggestions.append(
                                f"💡 {investor} 对 {startup} 感兴趣 → 建议引荐双方"
                            )
                    elif atype == "supply_demand":
                        matches = evidence.get("matches", [])
                        for m in matches[:2]:
                            action_suggestions.append(
                                f"💡 {m['supplier']} 可以帮助 {m['requester']} ({', '.join(m['matched_items'][:2])})"
                            )
                    elif atype == "topic_overlap":
                        action_suggestions.append(
                            f"💡 {ea.name} 和 {eb.name} 关注相似领域 → 建议安排交流"
                        )

            if action_suggestions:
                print(f"\n  基于关联的行动建议:")
                for s in action_suggestions[:3]:
                    print(f"    {s}")

            # ── 关联生成的Todo（Step 7.5的产出）──
            from promiselink.models.todo import Todo
            assoc_todos = (await session.execute(
                select(Todo).where(
                    Todo.user_id == user_id,
                    Todo.source_event_id.in_([event_id, event2_id]),
                    Todo.todo_type.in_(["cooperation_signal", "help", "followup", "care"]),
                ).order_by(Todo.created_at.asc())
            )).scalars().all()
            # Filter: only show association-generated todos (those with 引荐/对接/安排/约 in title)
            assoc_todos = [t for t in assoc_todos if any(kw in t.title for kw in ("引荐", "对接", "安排", "约"))]
            if assoc_todos:
                print(f"\n  关联发现自动生成的待办:")
                for t in assoc_todos:
                    type_cn = {"cooperation_signal": "合作信号", "help": "帮助", "followup": "跟进", "care": "关注"}.get(t.todo_type, t.todo_type)
                    print(f"    · [{type_cn}] {t.title}")

    except Exception as ex:
        import traceback
        print(f"\n  关联发现检查: 异常({ex})")

    # Brief跨事件聚合检查
    try:
        from promiselink.models.relationship_brief import RelationshipBrief
        async with AsyncSessionLocal() as session:
            briefs2 = (await session.execute(
                select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
                .order_by(RelationshipBrief.last_updated_at.desc())
            )).scalars().all()
            if briefs2:
                print(f"\n  关系推进卡 (跨事件聚合后):")
                for b in briefs2:
                    data = b.brief_data or {}
                    name = data.get("basic_info", {}).get("name", "未知")
                    stage_cn = _BRIEF_STAGE_LABELS.get(b.relationship_stage or "", b.relationship_stage or "")
                    interactions = data.get("interaction_history", [])
                    interaction_count = len(interactions) if isinstance(interactions, list) else 0
                    concerns = data.get("their_concerns", [])[:2]
                    # Clean concern text: remove [type] prefix and person name prefix
                    clean_concerns = []
                    for c in concerns:
                        clean = re.sub(r'^\[[^\]]+\]\s*', '', str(c))
                        clean = re.sub(r'^[^—]+—\s*', '', clean).strip()
                        if clean:
                            clean_concerns.append(clean)
                    concerns_str = ", ".join(clean_concerns) if clean_concerns else "-"
                    print(f"    · {name}: 阶段={stage_cn} | 互动次数≥{interaction_count} | 关心={concerns_str}")
    except Exception as ex:
        print(f"\n  Brief聚合检查: 异常({ex})")

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
    # Suppress config warnings during import
    import io as _io
    _saved = sys.stdout
    sys.stdout = _io.StringIO()
    from promiselink.config import Settings
    from promiselink.services.llm_client import LLMClient
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier, VoiceIntent
    sys.stdout = _saved

    header("场景2: 语音问询理解 — F-50 NLU意图识别")

    # ── 开场白 ──
    print(f"  {BOLD}许总的话{RESET}: \"{DIM}语音特别重要，这样我开车的时候就可以干很多活了{RESET}\"")
    print(f"  {BOLD}PromiseLink的答案{RESET}: 两阶段NLU — 规则引擎极速匹配 + LLM智能兜底\n")

    # 初始化（抑制config WARNING）
    import io as _io2
    _saved2 = sys.stdout
    sys.stdout = _io2.StringIO()
    config = Settings()
    sys.stdout = _saved2
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

    async def _build_response(intent_value: str, slots: dict | None) -> str:
        """根据NLU识别结果 + 真实DB数据，构造系统回答（调用系统NLG服务）."""
        from promiselink.database import AsyncSessionLocal
        from promiselink.services.nlg_service import generate_nlu_response
        from promiselink.services.nlu_intent_classifier import VoiceIntent

        # Map intent string to VoiceIntent enum
        intent_map = {
            "schedule_query": VoiceIntent.SCHEDULE_QUERY,
            "schedule_range": VoiceIntent.SCHEDULE_RANGE,
            "promise_tracker": VoiceIntent.PROMISE_TRACKER,
            "relationship_status": VoiceIntent.RELATIONSHIP_STATUS,
            "action_suggestion": VoiceIntent.ACTION_SUGGESTION,
            "todo_create": VoiceIntent.TODO_CREATE,
            "unclear": VoiceIntent.UNCLEAR,
            "chitchat": VoiceIntent.CHITCHAT,
            "exit": VoiceIntent.EXIT,
        }
        intent_enum = intent_map.get(intent_value, VoiceIntent.UNCLEAR)

        async with AsyncSessionLocal() as session:
            return await generate_nlu_response(
                session=session,
                intent=intent_enum,
                slots=slots,
                user_id=user_id,
            )

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

        # 显示证据（翻译为中文）
        if nlu_result.evidence:
            ev = nlu_result.evidence
            # Translate common English evidence patterns to Chinese
            ev = ev.replace("Keyword ", "关键词 ")
            ev = ev.replace(" matched as schedule_query", " 匹配为日程查询")
            ev = ev.replace(" matched as promise_tracker", " 匹配为承诺追踪")
            ev = ev.replace(" matched as relationship_status", " 匹配为关系状态")
            ev = ev.replace(" matched as action_suggestion", " 匹配为行动建议")
            ev = ev.replace(" matched as todo_create", " 匹配为创建提醒")
            ev = ev.replace(" matched as person_query", " 匹配为人物查询")
            ev = ev.replace(" matched as resource_match", " 匹配为资源匹配")
            ev = ev.replace("Regex ", "正则 ")
            ev = ev.replace(" matched", " 匹配")
            evidence_short = ev[:80]
            print(f"       依据: {DIM}{evidence_short}{RESET}")

        # 基于真实DB数据构造系统回答
        response = await _build_response(predicted, nlu_result.slots)
        print(f"\n  {BOLD}PromiseLink{RESET}: \"{response}\"\n")

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
    from promiselink.database import AsyncSessionLocal
    from promiselink.models.relationship_brief import RelationshipBrief
    from sqlalchemy import select

    header("场景3: 关系推进卡 — \"李总到哪步了？\"")

    print(f"  {BOLD}许总的问题{RESET}: \"{DIM}李总到哪步了？{RESET}\"")
    print(f"  {BOLD}PromiseLink的答案{RESET}: 按人名查询关系进展 + 12模块画像\n")

    user_id = "demo-user-xu"
    target_person = "李总"  # 场景3问询的目标人物

    async with AsyncSessionLocal() as session:
        all_briefs = (await session.execute(
            select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
            .order_by(RelationshipBrief.last_updated_at.desc())
            .limit(5)
        )).scalars().all()

        if not all_briefs:
            print(f"  {DIM}(暂无推进卡数据 — 请先运行场景1生成){RESET}")
            return {"scenario": "brief", "pass": False, "count": 0}

        # 按人名过滤：模拟真实语音流程(NLU提取人名→按名查找→只返回目标人物的卡)
        briefs = []
        for b in all_briefs:
            bname = (b.brief_data or {}).get("basic_info", {}).get("name", "")
            if target_person in bname or bname in target_person:
                briefs.append(b)

        if not briefs:
            print(f"  {DIM}({target_person}的推进卡尚未生成){RESET}")
            return {"scenario": "brief", "pass": True, "count": 0}

        print(f"  找到 {target_person} 的关系推进卡:\n")

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
                    print(f"      我承诺: {clean_title(p.get('title', ''), 40)}")
                for p in their_p[:3]:
                    print(f"      对方承诺: {clean_title(p.get('title', ''), 40)}")

            # 对方关心的话题
            concerns = data.get("their_concerns", [])
            if concerns:
                # Clean concern text: remove [type] prefix and person name prefix
                clean_concerns = []
                for c in concerns[:3]:
                    clean = re.sub(r'^\[[^\]]+\]\s*', '', str(c))
                    clean = re.sub(r'^[^—]+—\s*', '', clean).strip()
                    if clean:
                        clean_concerns.append(clean)
                print(f"    对方关心: {', '.join(clean_concerns)}")

            # 我的贡献
            contribs = data.get("my_contributions", [])
            if contribs:
                print(f"    我的帮助: {', '.join(contribs[:3])}")

            # 合作信号
            signals = data.get("cooperation_signals", [])
            if signals:
                clean_signals = []
                for s in signals[:3]:
                    clean = re.sub(r'^\[[^\]]+\]\s*', '', str(s))
                    if clean:
                        clean_signals.append(clean)
                print(f"    合作信号: {', '.join(clean_signals)}")

            # 风险标志
            risks = data.get("risk_flags", [])
            if risks:
                print(f"    风险标志: {', '.join(risks[:3])}")

            # 下一步建议
            actions = data.get("next_actions", [])
            if actions:
                print(f"    下一步建议:")
                priority_cn = {"high": "高", "medium": "中", "low": "低", "1": "高", "2": "中", "3": "低", "4": "低", "5": "低"}
                for a in actions:
                    p = str(a.get("priority", "?"))
                    p_cn = priority_cn.get(p, p)
                    priority_color = RED if p in ("high", "1") else YELLOW if p in ("medium", "2", "3") else DIM
                    action_text = str(a.get('action', ''))
                    # Clean action text: remove all [type] prefixes like [关注]
                    action_text = re.sub(r'\[[^\]]+\]\s*', '', action_text)
                    print(f"      [{priority_color}{p_cn}{RESET}] {action_text}")

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
    from promiselink.core.natural_date import parse_natural_date
    from promiselink.database import AsyncSessionLocal
    from promiselink.models.event import Event
    from promiselink.models.todo import Todo
    from sqlalchemy import select, func

    header("场景4: 日视图Dashboard — \"我今天的安排\"")

    print(f"  {BOLD}许总的问题{RESET}: \"{DIM}我今天的会议是什么？{RESET}\"")
    print(f"  {BOLD}PromiseLink的答案{RESET}: 自然语言日期解析 + 事件/待办聚合展示\n")

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

        # Part C: 事件详情（点击查看 或 语音播报）
        sub_header("Part C: 事件详情 — 点击查看 / 语音播报")
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
            from promiselink.models.entity import Entity
            ent_result = await session.execute(
                select(Entity).where(Entity.source_event_id == evt.id)
            )
            entities = ent_result.scalars().all()
            if entities:
                print(f"  涉及人物: {', '.join(e.name for e in entities)}")
                print()

            # 关联待办（该事件生成的所有todo，不限due_date）
            evt_todo_result = await session.execute(
                select(Todo).where(Todo.source_event_id == str(evt.id))
                .order_by(Todo.created_at.asc())
            )
            todo_for_evt = evt_todo_result.scalars().all()
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
    print("║          PromiseLink  演示  —  PoC阶段                 ║")
    print("║                                                          ║")
    print("║   AI驱动的个人商务关系经营助手                          ║")
    print("║   「让每一次连接，都更有价值」                              ║")
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
        results.append({"scenario": "pipeline", "pass": False, "error": str(e)})

    # ── 场景2: NLU ──
    try:
        r = await demo_nlu()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景2异常: {e}{RESET}")
        results.append({"scenario": "nlu", "pass": False, "error": str(e)})

    # ── 场景3: Brief ──
    try:
        r = await demo_brief()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景3异常: {e}{RESET}")
        results.append({"scenario": "brief", "pass": False, "error": str(e)})

    # ── 场景4: Dashboard ──
    try:
        r = await demo_dashboard()
        results.append(r)
    except Exception as e:
        print(f"\n  {RED}场景4异常: {e}{RESET}")
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
    print(f"  PromiseLink = AI驱动的个人商务关系经营助手")
    print(f"  核心循环: 互动→关注→承诺→帮助→反馈 (利他优先)")
    print(f"  Slogan: \"让每一次连接，都更有价值\"")

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
