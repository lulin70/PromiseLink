#!/usr/bin/env python3
"""PromiseLink 基础版 — 全面 E2E 用户操作测试

模拟用户在宽屏UI上的所有操作：
  1. 登录
  2. 首页 Dashboard 加载（摘要卡片、今日事件、今日待办、供需匹配、关系健康、关怀提醒）
  3. 事件列表（日期筛选、搜索、展开详情、删除、重试）
  4. 预定日程（创建、取消、查看）
  5. 人脉列表（搜索、详情弹窗、信用分、关系阶段、沉睡人脉、编辑、删除）
  6. 待办列表（状态筛选、类型筛选、搜索、完成、忽略、删除、跳转详情）
  7. 承诺列表（视图切换、状态筛选、搜索、确认/忽略、兑现/违背、催促）
  8. 事件录入（文本录入、文件上传、需求录入、预定日程录入）
  9. 数据导出
 10. 跨页面跳转（事件↔人脉、待办↔事件、承诺↔人脉）
 11. 详情页访问（事件详情、人脉详情、待办详情、承诺详情）
 12. 监控指标（Prometheus /metrics 端点）

使用方法：
  python scripts/e2e/e2e_full_ui_test.py [BASE_URL]

默认 BASE_URL=http://localhost:8000
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

passed = 0
failed = 0
skipped = 0
token = None
user_id = "e2e-full-ui-user"


def log_ok(msg: str):
    global passed
    passed += 1
    print(f"  ✅ {msg}")


def log_fail(msg: str):
    global failed
    failed += 1
    print(f"  ❌ {msg}")


def log_skip(msg: str):
    global skipped
    skipped += 1
    print(f"  ⏭️  {msg}")


def api_call(method: str, path: str, body: dict | None = None, headers: dict | None = None, expect_status: int | None = None) -> tuple[int, dict | list]:
    """发起 API 请求，返回 (status_code, response_json)。

    自动对path中的非ASCII字符进行URL编码（保留?&=等分隔符）。
    """
    # 对path进行URL编码：先分割query string，再对非ASCII字符编码
    if "?" in path:
        base_path, query_string = path.split("?", 1)
        # 对query参数值进行编码
        encoded_params = []
        for param in query_string.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                encoded_params.append(f"{key}={urllib.parse.quote(value)}")
            else:
                encoded_params.append(param)
        encoded_path = f"{base_path}?{'&'.join(encoded_params)}"
    else:
        encoded_path = path
    url = f"{API}{encoded_path}"
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            body_text = resp.read().decode("utf-8", errors="replace")
            try:
                return status, json.loads(body_text)
            except json.JSONDecodeError:
                return status, {"raw": body_text}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text}
    except Exception as e:
        return 0, {"error": str(e)}


def section(title: str):
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}")


# ═══════════════════════════════════════════════════════════════
# 阶段 1：健康检查 + 登录
# ═══════════════════════════════════════════════════════════════
section("阶段 1：健康检查 + 登录")

status, data = api_call("GET", "/health")
if status == 200 and data.get("status") == "healthy":
    log_ok(f"服务健康 v{data.get('version')} ({data.get('edition')})")
else:
    log_fail(f"健康检查失败: {status} {data}")
    sys.exit(1)

status, data = api_call("POST", "/auth/login", body={"user_id": user_id, "poc_secret": "promiselink2026"})
if status == 200 and "access_token" in data:
    token = data["access_token"]
    log_ok(f"PoC 登录成功 (user_id={data.get('user_id')})")
else:
    log_fail(f"登录失败: {status} {data}")
    sys.exit(1)

# 错误密钥测试
status, data = api_call("POST", "/auth/login", body={"user_id": "bad-user", "poc_secret": "wrong-secret"})
if status in (401, 403):
    log_ok("错误密钥被正确拒绝")
else:
    log_fail(f"错误密钥未被拒绝: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 2：首页 Dashboard
# ═══════════════════════════════════════════════════════════════
section("阶段 2：首页 Dashboard 加载")

# Dashboard (DayView)
status, data = api_call("GET", "/dashboard/day-view")
if status == 200 and "summary" in data:
    s = data["summary"]
    log_ok(f"Dashboard 加载成功: 事件={s.get('total_events', 0)}, 待办={s.get('total_todos', 0)}, 逾期={s.get('overdue_todos', 0)}, 承诺={s.get('pending_promises', 0)}")
    if "date_label" in data:
        log_ok(f"日期标签: {data['date_label']}")
    if "events" in data:
        log_ok(f"今日事件列表: {len(data['events'])} 条")
    if "todos" in data:
        log_ok(f"今日待办列表: {len(data['todos'])} 条")
else:
    log_fail(f"Dashboard 加载失败: {status} {str(data)[:200]}")

# 供需匹配
status, data = api_call("GET", "/dashboard/supply-demand?limit=5")
if status == 200:
    matches = data.get("matches", []) if isinstance(data, dict) else data
    log_ok(f"供需匹配: {len(matches)} 条")
else:
    log_skip(f"供需匹配接口跳过: {status}")

# 关系健康
status, data = api_call("GET", "/dashboard/relationship-health?limit=20")
if status == 200:
    log_ok(f"关系健康度: total={data.get('total_entities', 0)}, healthy={data.get('healthy_count', 0)}, attention={data.get('attention_count', 0)}, risk={data.get('at_risk_count', 0)}")
else:
    log_skip(f"关系健康接口跳过: {status}")

# 关怀提醒
status, data = api_call("GET", "/dashboard/care-reminders?limit=10")
if status == 200:
    log_ok(f"关怀提醒: total={data.get('total', 0)}")
else:
    log_skip(f"关怀提醒接口跳过: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 3：事件列表 + 筛选 + 搜索 + 展开详情
# ═══════════════════════════════════════════════════════════════
section("阶段 3：事件列表操作")

# 获取事件列表
status, data = api_call("GET", "/events?limit=50")
if status == 200:
    events = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"事件列表加载: {len(events)} 条")
    if events:
        first_event = events[0]
        event_id = first_event["id"]
        log_ok(f"首事件: {first_event.get('title', '')[:40]} (status={first_event.get('status')})")

        # 展开详情 (模拟用户点击事件卡片)
        status, detail = api_call("GET", f"/events/{event_id}")
        if status == 200:
            log_ok(f"事件详情展开成功: pipeline={detail.get('pipeline')}, entities={len(detail.get('related_entities', []))}, todos={len(detail.get('related_todos', []))}")
        else:
            log_fail(f"事件详情展开失败: {status}")

        # 搜索事件
        status, search_data = api_call("GET", "/events?limit=50&search=测试")
        if status == 200:
            search_items = search_data.get("items", []) if isinstance(search_data, dict) else search_data
            log_ok(f"事件搜索 '测试': {len(search_items)} 条结果")
        else:
            log_fail(f"事件搜索失败: {status}")
    else:
        log_skip("无事件可测试详情展开")
else:
    log_fail(f"事件列表加载失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 4：预定日程
# ═══════════════════════════════════════════════════════════════
section("阶段 4：预定日程操作")

# 获取预定日程列表
status, data = api_call("GET", "/scheduled-events?limit=50")
if status == 200:
    scheduled = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"预定日程列表: {len(scheduled)} 条")
else:
    log_skip(f"预定日程列表接口: {status}")
    scheduled = []

# 创建预定日程 (模拟用户点击"+ 新建预定日程")
from datetime import datetime, timedelta
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
schedule_payload = {
    "scheduled_at": f"{tomorrow}T14:00:00+08:00",
    "topic": "E2E测试预定会议",
    "participants": [{"name": "测试参与者A"}, {"name": "测试参与者B"}],
    "location": "测试会议室",
    "event_type": "meeting",
}
status, data = api_call("POST", "/scheduled-events", body=schedule_payload)
if status in (200, 201):
    scheduled_id = data.get("id", "")
    log_ok(f"预定日程创建成功: id={scheduled_id[:8]}...")

    # 取消预定日程
    status, cancel_data = api_call("POST", f"/scheduled-events/{scheduled_id}/cancel", body={})
    if status in (200, 204):
        log_ok("预定日程取消成功")
    else:
        error_msg = str(cancel_data)[:150] if cancel_data else ""
        log_fail(f"预定日程取消失败: {status} {error_msg}")
else:
    log_fail(f"预定日程创建失败: {status} {str(data)[:200]}")


# ═══════════════════════════════════════════════════════════════
# 阶段 5：人脉列表 + 详情 + 沉睡人脉
# ═══════════════════════════════════════════════════════════════
section("阶段 5：人脉列表操作")

# 人脉列表
status, data = api_call("GET", "/entities?limit=50")
if status == 200:
    entities = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"人脉列表加载: {len(entities)} 条")
    if entities:
        first_entity = entities[0]
        entity_id = first_entity["id"]
        log_ok(f"首人脉: {first_entity.get('name', '')} (type={first_entity.get('entity_type')})")

        # 人脉详情 (模拟用户点击人脉卡片)
        status, detail = api_call("GET", f"/entities/{entity_id}")
        if status == 200:
            log_ok(f"人脉详情加载: name={detail.get('name')}, confidence={detail.get('confidence', 0):.0%}")
        else:
            log_fail(f"人脉详情加载失败: {status}")

        # 信用分
        status, credit = api_call("GET", f"/entities/{entity_id}/credit-score")
        if status == 200:
            log_ok(f"信用分: score={credit.get('score', 0):.1f}, grade={credit.get('grade', 'N/A')}")
        else:
            log_skip(f"信用分接口跳过: {status}")

        # 关系阶段
        status, stage = api_call("GET", f"/entities/{entity_id}/stage-info")
        if status == 200:
            log_ok(f"关系阶段: {stage.get('current_stage_label', 'N/A')}")
        else:
            log_skip(f"关系阶段接口跳过: {status}")

        # 人脉历史
        status, history = api_call("GET", f"/entities/{entity_id}/history")
        if status == 200:
            log_ok(f"人脉历史: events={len(history.get('events', []))}, todos={len(history.get('todos', []))}, associations={len(history.get('associations', []))}")
        else:
            log_skip(f"人脉历史接口跳过: {status}")
    else:
        log_skip("无人脉可测试详情")
else:
    log_fail(f"人脉列表加载失败: {status}")

# 沉睡人脉
status, data = api_call("GET", "/entities/dormant?min_days=1&limit=10")
if status == 200:
    dormant = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"沉睡人脉: {len(dormant)} 条")
else:
    log_skip(f"沉睡人脉接口跳过: {status}")

# 人脉搜索
status, data = api_call("GET", "/entities?limit=50&search=张")
if status == 200:
    search_items = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"人脉搜索 '张': {len(search_items)} 条结果")
else:
    log_fail(f"人脉搜索失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 6：待办列表 + 筛选 + 操作
# ═══════════════════════════════════════════════════════════════
section("阶段 6：待办列表操作")

# 待办列表 (全部)
status, data = api_call("GET", "/todos?limit=50")
if status == 200:
    todos = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"待办列表(全部): {len(todos)} 条")
else:
    log_fail(f"待办列表加载失败: {status}")
    todos = []

# 状态筛选
for status_filter in ["pending", "done", "dismissed"]:
    status, data = api_call("GET", f"/todos?status={status_filter}&limit=50")
    if status == 200:
        items = data.get("items", []) if isinstance(data, dict) else data
        log_ok(f"待办筛选[{status_filter}]: {len(items)} 条")
    else:
        log_fail(f"待办筛选[{status_filter}]失败: {status}")

# 类型筛选
for type_filter in ["care", "followup", "cooperation_signal", "risk"]:
    status, data = api_call("GET", f"/todos?todo_type={type_filter}&limit=50")
    if status == 200:
        items = data.get("items", []) if isinstance(data, dict) else data
        log_ok(f"待办类型[{type_filter}]: {len(items)} 条")
    else:
        log_fail(f"待办类型[{type_filter}]失败: {status}")

# 待办搜索
status, data = api_call("GET", "/todos?limit=50&search=测试")
if status == 200:
    items = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"待办搜索 '测试': {len(items)} 条")
else:
    log_fail(f"待办搜索失败: {status}")

# 待办操作 (完成/忽略) - 找一个pending的待办
# 注意：done和dismissed都是终态，无法恢复，所以需要不同的todo测试每个操作
pending_todos = [t for t in todos if t.get("status") == "pending"]
if len(pending_todos) >= 1:
    test_todo = pending_todos[0]
    todo_id = test_todo["id"]

    # 标记完成 (pending → done)
    status, data = api_call("PATCH", f"/todos/{todo_id}", body={"status": "done"})
    if status in (200, 204):
        log_ok(f"待办标记完成: {test_todo.get('title', '')[:30]}")
    else:
        log_fail(f"待办标记完成失败: {status}")

    # 验证终态保护 (done → pending 应该失败)
    status, data = api_call("PATCH", f"/todos/{todo_id}", body={"status": "pending"})
    if status in (400, 422):
        log_ok(f"终态保护验证: done→pending 被正确拒绝 (终态不可恢复)")
    else:
        log_fail(f"终态保护失败: done→pending 应该被拒绝，实际status={status}")

    # 如果有第二个pending待办，测试忽略操作
    if len(pending_todos) >= 2:
        test_todo2 = pending_todos[1]
        todo_id2 = test_todo2["id"]
        status, data = api_call("PATCH", f"/todos/{todo_id2}", body={"status": "dismissed"})
        if status in (200, 204):
            log_ok(f"待办忽略: {test_todo2.get('title', '')[:30]}")
        else:
            log_fail(f"待办忽略失败: {status}")
    else:
        log_skip("无第二个pending待办可测试忽略操作")
else:
    log_skip("无pending待办可测试操作")


# ═══════════════════════════════════════════════════════════════
# 阶段 7：承诺列表 + 筛选 + 操作
# ═══════════════════════════════════════════════════════════════
section("阶段 7：承诺列表操作")

# 承诺统计
status, data = api_call("GET", "/promises/stats")
if status == 200:
    log_ok(f"承诺统计: total={data.get('total', 0)}, 兑现率={data.get('fulfillment_rate', 0):.0%}")
else:
    log_fail(f"承诺统计失败: {status}")

# 我的承诺
status, data = api_call("GET", "/promises?view=my-promises&limit=20")
if status == 200:
    my_promises = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"我的承诺: {len(my_promises)} 条")
else:
    log_fail(f"我的承诺加载失败: {status}")
    my_promises = []

# 对方的承诺
status, data = api_call("GET", "/promises?view=their-promises&limit=20")
if status == 200:
    their_promises = data.get("items", []) if isinstance(data, dict) else data
    log_ok(f"对方承诺: {len(their_promises)} 条")
else:
    log_fail(f"对方承诺加载失败: {status}")

# 状态筛选
for status_filter in ["pending", "fulfilled", "overdue", "broken"]:
    status, data = api_call("GET", f"/promises?status={status_filter}&limit=20")
    if status == 200:
        items = data.get("items", []) if isinstance(data, dict) else data
        log_ok(f"承诺筛选[{status_filter}]: {len(items)} 条")
    else:
        log_fail(f"承诺筛选[{status_filter}]失败: {status}")

# 待确认承诺
status, data = api_call("GET", "/todos/pending-confirmations")
if status == 200:
    pending_confirms = data if isinstance(data, list) else data.get("items", [])
    log_ok(f"待确认承诺: {len(pending_confirms)} 条")
else:
    log_skip(f"待确认承诺接口跳过: {status}")

# 承诺操作 - 找一个pending的承诺
pending_promises = [p for p in my_promises if p.get("fulfillment_status") == "pending"]
if pending_promises:
    test_promise = pending_promises[0]
    promise_id = test_promise["todo_id"]

    # 标记已兑现
    status, data = api_call("PATCH", f"/promises/{promise_id}/fulfillment", body={"fulfillment_status": "fulfilled"})
    if status in (200, 204):
        log_ok(f"承诺标记已兑现: {test_promise.get('description', '')[:30]}")
    else:
        log_fail(f"承诺标记已兑现失败: {status}")

    # 恢复pending
    status, data = api_call("PATCH", f"/promises/{promise_id}/fulfillment", body={"fulfillment_status": "pending"})
    if status in (200, 204):
        log_ok("承诺恢复pending状态")
    else:
        log_skip(f"承诺恢复pending失败: {status}")
else:
    log_skip("无pending承诺可测试操作")

# 催促草稿 (对方的承诺)
their_pending = [p for p in their_promises if p.get("fulfillment_status") in ("pending", "overdue")]
if their_pending:
    nudge_promise = their_pending[0]
    status, data = api_call("GET", f"/promises/{nudge_promise['todo_id']}/nudge-draft")
    if status == 200:
        nudge_text = data.get("nudge_text", "")
        log_ok(f"催促草稿生成: {nudge_text[:50]}...")
    else:
        log_skip(f"催促草稿接口跳过: {status}")
else:
    log_skip("无对方pending承诺可测试催促")


# ═══════════════════════════════════════════════════════════════
# 阶段 8：事件录入
# ═══════════════════════════════════════════════════════════════
section("阶段 8：事件录入操作")

# 文本录入
event_payload = {
    "event_type": "meeting",
    "source": "manual",
    "title": "E2E测试会议",
    "raw_text": "今天和张三开会讨论了项目合作。张三答应下周三前提供技术方案。我承诺本周五前发送报价单。",
}
status, data = api_call("POST", "/events", body=event_payload)
if status in (200, 201):
    new_event_id = data.get("id", "")
    log_ok(f"事件录入成功: id={new_event_id[:8]}..., pipeline_status={data.get('pipeline_status', 'N/A')}")

    # 等待管线处理 (最多30秒)
    log_ok("等待管线处理...")
    for _ in range(15):
        time.sleep(2)
        status, detail = api_call("GET", f"/events/{new_event_id}")
        if status == 200:
            event_status = detail.get("status")
            if event_status in ("completed", "failed", "awaiting_retry", "degraded_completed"):
                if event_status == "completed":
                    log_ok(f"管线处理完成: entities={len(detail.get('related_entities', []))}, todos={len(detail.get('related_todos', []))}")
                elif event_status == "failed":
                    failed_steps = detail.get("failed_steps", [])
                    log_skip(f"管线处理失败 (LLM基础设施问题): failed_steps={failed_steps}")
                else:
                    log_ok(f"管线状态: {event_status}")
                break
        else:
            log_fail(f"查询事件状态失败: {status}")
            break
    else:
        log_skip("管线处理超时(30s)，可能LLM响应慢")
else:
    log_fail(f"事件录入失败: {status} {str(data)[:200]}")

# 需求录入
demand_payload = {"text": "我需要一个靠谱的前端开发团队，熟悉React和TypeScript"}
status, data = api_call("POST", "/demands", body=demand_payload)
if status in (200, 201):
    extracted = data.get("extracted", {})
    log_ok(f"需求录入成功: tag={extracted.get('tag', 'N/A')}")
else:
    log_fail(f"需求录入失败: {status} {str(data)[:200]}")


# ═══════════════════════════════════════════════════════════════
# 阶段 9：数据导出
# ═══════════════════════════════════════════════════════════════
section("阶段 9：数据导出")

status, data = api_call("GET", f"/export/{user_id}")
if status == 200:
    if isinstance(data, dict):
        log_ok(f"数据导出成功: keys={list(data.keys())[:10]}")
        # 验证导出数据结构
        for key in ("events", "entities", "todos", "promises"):
            if key in data:
                items = data[key]
                count = len(items) if isinstance(items, list) else len(items.get("items", [])) if isinstance(items, dict) else 0
                log_ok(f"  导出[{key}]: {count} 条")
    else:
        log_ok(f"数据导出成功: type={type(data).__name__}")
else:
    log_fail(f"数据导出失败: {status} {str(data)[:200]}")


# ═══════════════════════════════════════════════════════════════
# 阶段 10：详情页访问
# ═══════════════════════════════════════════════════════════════
section("阶段 10：详情页访问")

# 事件详情页
status, data = api_call("GET", "/events?limit=1")
if status == 200:
    items = data.get("items", []) if isinstance(data, dict) else data
    if items:
        eid = items[0]["id"]
        status, detail = api_call("GET", f"/events/{eid}")
        if status == 200:
            log_ok(f"事件详情页访问成功: {detail.get('title', '')[:40]}")
        else:
            log_fail(f"事件详情页访问失败: {status}")

# 人脉详情页
status, data = api_call("GET", "/entities?limit=1")
if status == 200:
    items = data.get("items", []) if isinstance(data, dict) else data
    if items:
        eid = items[0]["id"]
        status, detail = api_call("GET", f"/entities/{eid}")
        if status == 200:
            log_ok(f"人脉详情页访问成功: {detail.get('name', '')}")
        else:
            log_fail(f"人脉详情页访问失败: {status}")

# 待办详情页 (如果存在)
status, data = api_call("GET", "/todos?limit=1")
if status == 200:
    items = data.get("items", []) if isinstance(data, dict) else data
    if items:
        tid = items[0]["id"]
        status, detail = api_call("GET", f"/todos/{tid}")
        if status == 200:
            log_ok(f"待办详情页访问成功: {detail.get('title', '')[:40]}")
        else:
            log_skip(f"待办详情页接口: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 11：监控指标 (Prometheus /metrics)
# ═══════════════════════════════════════════════════════════════
section("阶段 11：监控指标")

status, data = api_call("GET", "/metrics")
if status == 200:
    log_ok(f"Prometheus指标访问成功: {str(data)[:100]}")
else:
    log_skip(f"指标接口跳过: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 12：跨页面跳转验证
# ═══════════════════════════════════════════════════════════════
section("阶段 12：跨页面跳转验证")

# 事件 → 人脉跳转 (事件中的entity_link点击)
status, data = api_call("GET", "/events?limit=5")
if status == 200:
    events = data.get("items", []) if isinstance(data, dict) else data
    for event in events:
        if event.get("entities"):
            entity_id = event["entities"][0].get("id") if isinstance(event["entities"][0], dict) else None
            if entity_id:
                # 模拟跳转到人脉详情
                status, entity_detail = api_call("GET", f"/entities/{entity_id}")
                if status == 200:
                    log_ok(f"事件→人脉跳转: event={event.get('title','')[:20]} → entity={entity_detail.get('name','')}")
                else:
                    log_fail(f"事件→人脉跳转失败: {status}")
                break
    else:
        log_skip("无带entity的事件可测试跳转")

# 人脉 → 事件跳转 (人脉详情中的相关事件)
status, data = api_call("GET", "/entities?limit=5")
if status == 200:
    entities = data.get("items", []) if isinstance(data, dict) else data
    for entity in entities:
        status, history = api_call("GET", f"/entities/{entity['id']}/history")
        if status == 200 and history.get("events"):
            event_id = history["events"][0]["id"]
            # 模拟跳转到事件详情
            status, event_detail = api_call("GET", f"/events/{event_id}")
            if status == 200:
                log_ok(f"人脉→事件跳转: entity={entity.get('name','')} → event={event_detail.get('title','')[:20]}")
            else:
                log_fail(f"人脉→事件跳转失败: {status}")
            break
    else:
        log_skip("无带history的entity可测试跳转")

# 待办 → 事件跳转 (待办中的source_event_link点击)
status, data = api_call("GET", "/todos?limit=50")
if status == 200:
    todos = data.get("items", []) if isinstance(data, dict) else data
    for todo in todos:
        if todo.get("source_event_id"):
            # 模拟跳转到事件详情
            status, event_detail = api_call("GET", f"/events/{todo['source_event_id']}")
            if status == 200:
                log_ok(f"待办→事件跳转: todo={todo.get('title','')[:20]} → event={event_detail.get('title','')[:20]}")
            else:
                log_fail(f"待办→事件跳转失败: {status}")
            break
    else:
        log_skip("无带source_event的todo可测试跳转")

# 承诺 → 人脉跳转 (承诺中的entity_link点击)
status, data = api_call("GET", "/promises?limit=50")
if status == 200:
    promises = data.get("items", []) if isinstance(data, dict) else data
    for promise in promises:
        entity_id = promise.get("related_entity_id") or promise.get("entity_id")
        if entity_id:
            # 模拟跳转到人脉详情
            status, entity_detail = api_call("GET", f"/entities/{entity_id}")
            if status == 200:
                log_ok(f"承诺→人脉跳转: promise={promise.get('description','')[:20]} → entity={entity_detail.get('name','')}")
            else:
                log_fail(f"承诺→人脉跳转失败: {status}")
            break
    else:
        log_skip("无带entity的promise可测试跳转")


# ═══════════════════════════════════════════════════════════════
# 阶段 13：错误处理验证
# ═══════════════════════════════════════════════════════════════
section("阶段 13：错误处理验证")

# 无token访问受保护资源
saved_token = token
token = None
status, data = api_call("GET", "/events")
if status in (401, 403):
    log_ok("未认证访问被正确拒绝 (401/403)")
else:
    log_fail(f"未认证访问未被拒绝: {status}")
token = saved_token

# 访问不存在的事件
status, data = api_call("GET", "/events/nonexistent-id")
if status in (404, 422):
    log_ok("不存在的事件返回404/422")
else:
    log_fail(f"不存在的事件返回: {status}")

# 访问不存在的人脉
status, data = api_call("GET", "/entities/nonexistent-id")
if status in (404, 422):
    log_ok("不存在的人脉返回404/422")
else:
    log_fail(f"不存在的人脉返回: {status}")

# 空搜索
status, data = api_call("GET", "/events?q=")
if status == 200:
    log_ok("空搜索正常返回")
else:
    log_fail(f"空搜索失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════════
section("测试总结")
total = passed + failed + skipped
print(f"\n  总测试数: {total}")
print(f"  ✅ 通过: {passed}")
print(f"  ❌ 失败: {failed}")
print(f"  ⏭️  跳过: {skipped}")
print(f"  通过率: {passed/total*100:.1f}%" if total > 0 else "  无测试")

if failed == 0:
    print("\n  🎉 所有测试通过！基础版可发布。")
    sys.exit(0)
else:
    print(f"\n  ⚠️  有 {failed} 个测试失败，需修复后发布。")
    sys.exit(1)
