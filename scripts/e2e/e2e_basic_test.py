#!/usr/bin/env python3
"""PromiseLink 基础版 E2E 测试 — 6 阶段 15 步，stdlib-only，中文输出。

使用方法：
  python scripts/e2e/e2e_basic_test.py [BASE_URL]

默认 BASE_URL=http://localhost:8000
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

E2E_USER_ID = "00000000-0000-4000-8000-000000000001"

passed = 0
failed = 0
token = None


def log_ok(msg: str):
    global passed
    passed += 1
    print(f"  ✅ {msg}")


def log_fail(msg: str):
    global failed
    failed += 1
    print(f"  ❌ {msg}")


def api_call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    """发起 API 请求，返回 (status_code, response_json)。"""
    url = f"{API}{path}"
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text}
    except Exception as e:
        return 0, {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# 阶段 1：健康检查
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 1：健康检查")

status, data = api_call("GET", "/health")
if status == 200 and data.get("status") == "healthy":
    log_ok(f"服务健康，版本 {data.get('version')}，版本类型 {data.get('edition')}")
else:
    log_fail(f"健康检查失败: {status} {data}")


# ═══════════════════════════════════════════════════════════════
# 阶段 2：认证
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 2：认证")

# 步骤 1: PoC 登录
status, data = api_call("POST", "/auth/login", body={
    "user_id": E2E_USER_ID,
    "poc_secret": "promiselink2026",
})
if status == 200 and "access_token" in data:
    token = data["access_token"]
    log_ok("PoC 登录成功，获取 token")
else:
    log_fail(f"登录失败: {status} {data}")

# 步骤 2: 无 token 访问受保护 API
saved_token = token
token = None
status, _ = api_call("GET", "/events")
if status == 401:
    log_ok("无 token 访问返回 401")
else:
    log_fail(f"无 token 应返回 401，实际 {status}")
token = saved_token


# ═══════════════════════════════════════════════════════════════
# 阶段 3：事件录入
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 3：事件录入")

# 步骤 3: 创建手动事件
status, data = api_call("POST", "/events", body={
    "event_type": "meeting",
    "source": "e2e-test",
    "title": "E2E测试会议",
    "raw_text": "和张总讨论了Q3合作方案，张总承诺下周提供技术方案",
})
if status == 201:
    event_id = data.get("id")
    log_ok(f"创建事件成功，id={event_id}")
else:
    log_fail(f"创建事件失败: {status} {data}")
    event_id = None

# 步骤 4: 查询事件列表
status, data = api_call("GET", "/events")
if status == 200 and data.get("total", 0) >= 1:
    log_ok(f"事件列表查询成功，共 {data['total']} 条")
else:
    log_fail(f"事件列表查询失败: {status} {data}")

# 步骤 5: 查询事件详情
if event_id:
    status, data = api_call("GET", f"/events/{event_id}")
    if status == 200:
        log_ok(f"事件详情查询成功，状态={data.get('status')}")
    else:
        log_fail(f"事件详情查询失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 4：实体与 Todo
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 4：实体与 Todo")

# 等待管道处理 — 轮询 event.status 直到 completed 或超时 30s
if event_id:
    print(f"  ⏳ 轮询事件 {event_id} 直到 status=completed (超时 30s)...")
    pipeline_ok = False
    deadline = time.time() + 30
    while time.time() < deadline:
        status, data = api_call("GET", f"/events/{event_id}")
        if status == 200:
            ev_status = data.get("status")
            if ev_status == "completed":
                log_ok("管道处理完成 (status=completed)")
                pipeline_ok = True
                break
            elif ev_status == "failed":
                log_fail(f"管道处理失败 (status=failed): {data.get('error', 'unknown')}")
                break
            else:
                print(f"  ... 当前 status={ev_status}, 继续等待")
        else:
            log_fail(f"轮询事件详情失败: {status}")
            break
        time.sleep(1)
    if not pipeline_ok and status == 200 and data.get("status") != "failed":
        log_fail(f"管道处理超时 30s (final status={data.get('status') if status == 200 else 'N/A'})")

# 步骤 6: 查询实体 — 录入"张总承诺下周提供技术方案"必须提取出至少 1 个 Person 实体
status, data = api_call("GET", "/entities")
if status == 200:
    entity_count = data.get("total", 0)
    if entity_count >= 1:
        log_ok(f"实体查询成功，共 {entity_count} 个 (≥1，AI 提取正常)")
    else:
        log_fail("实体查询 0 个 — 录入'张总承诺下周提供技术方案'应至少提取 1 个 Person 实体 (LLM_API_KEY 是否配置?)")
else:
    log_fail(f"实体查询失败: {status}")

# 步骤 7: 查询 Todo — 必须至少 1 个 (LLM 应识别"提供技术方案"为 todo)
status, data = api_call("GET", "/todos")
if status == 200:
    todo_count = data.get("total", 0)
    if todo_count >= 1:
        log_ok(f"Todo 查询成功，共 {todo_count} 个 (≥1，Todo 生成正常)")
        first_todo = data["items"][0]
        todo_id = first_todo["id"]
    else:
        log_fail("Todo 查询 0 个 — 录入承诺类文本应至少生成 1 个 Todo (LLM_API_KEY 是否配置?)")
        todo_id = None
else:
    log_fail(f"Todo 查询失败: {status}")
    todo_id = None

# 步骤 8: 更新 Todo 状态
if todo_id:
    status, data = api_call("PATCH", f"/todos/{todo_id}", body={"status": "in_progress"})
    if status == 200:
        log_ok("Todo 状态更新成功")
    else:
        log_fail(f"Todo 状态更新失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 阶段 5：承诺与仪表盘
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 5：承诺与仪表盘")

# 步骤 9: 查询承诺列表 — 录入"张总承诺下周提供技术方案"应识别为 their_promise
status, data = api_call("GET", "/promises")
promise_count = 0
if status == 200:
    promise_count = data.get("total", 0)
    if promise_count >= 1:
        log_ok(f"承诺列表查询成功，共 {promise_count} 条 (≥1，承诺分析正常)")
    else:
        log_fail("承诺列表 0 条 — 录入'张总承诺下周提供技术方案'应识别为 their_promise (LLM_API_KEY 是否配置?)")
else:
    log_fail(f"承诺列表查询失败: {status}")

# 步骤 10: 查询承诺统计
status, data = api_call("GET", "/promises/stats")
if status == 200:
    log_ok(f"承诺统计查询成功，履约率 {data.get('fulfillment_rate', 0):.1%}")
else:
    log_fail(f"承诺统计查询失败: {status}")

# 步骤 11: 查询仪表盘
status, data = api_call("GET", "/dashboard/day-view")
if status == 200:
    summary = data.get("summary", {})
    log_ok(f"仪表盘查询成功，事件 {summary.get('total_events', 0)} 条，Todo {summary.get('total_todos', 0)} 个")
else:
    log_fail(f"仪表盘查询失败: {status}")

# 步骤 11b: 4 zone 整合断言 — 人脉/关系/待办/承诺 至少 1 项有真实内容
# (用户硬约束: 录入事件后AI解析结果需分区展示)
zone_non_empty = 0
zone_summary = []

# 人脉 zone (entities)
status, ent_data = api_call("GET", "/entities")
if status == 200 and ent_data.get("total", 0) > 0:
    zone_non_empty += 1
    zone_summary.append(f"人脉={ent_data['total']}")

# 关系 zone (relationship-briefs)
status, rb_data = api_call("GET", "/relationship-briefs")
if status == 200 and rb_data.get("total", 0) > 0:
    zone_non_empty += 1
    zone_summary.append(f"关系={rb_data['total']}")

# 待办 zone (todos)
status, td_data = api_call("GET", "/todos")
if status == 200 and td_data.get("total", 0) > 0:
    zone_non_empty += 1
    zone_summary.append(f"待办={td_data['total']}")

# 承诺 zone (promises)
if promise_count > 0:
    zone_non_empty += 1
    zone_summary.append(f"承诺={promise_count}")

if zone_non_empty >= 1:
    log_ok(f"4 zone 断言通过: {', '.join(zone_summary)} ({zone_non_empty}/4 zone 有内容)")
else:
    log_fail("4 zone 全空 — 录入事件后 AI 解析结果分区展示无内容 (管道未运行或 LLM 未配置)")


# ═══════════════════════════════════════════════════════════════
# 阶段 6：搜索与导出
# ═══════════════════════════════════════════════════════════════
print("\n📋 阶段 6：搜索与导出")

# 步骤 12: 搜索事件 — 录入"和张总讨论了Q3合作方案"应匹配"合作"
import urllib.parse

search_url = f"/events?search={urllib.parse.quote('合作')}"
status, data = api_call("GET", search_url)
if status == 200:
    total = data.get('total', 0)
    if total > 0:
        log_ok(f"事件搜索成功，匹配 {total} 条")
    else:
        log_fail("事件搜索 0 条 — 录入文本含'合作'应匹配 (管道是否完成?)")
else:
    log_fail(f"事件搜索失败: {status}")

# 步骤 13: 搜索实体 — 录入"张总"应匹配"张"
status, data = api_call("GET", f"/entities?search={urllib.parse.quote('张')}")
if status == 200:
    total = data.get('total', 0)
    if total > 0:
        log_ok(f"实体搜索成功，匹配 {total} 个")
    else:
        log_fail("实体搜索 0 个 — 录入'张总'应匹配'张' (实体提取是否完成?)")
else:
    log_fail(f"实体搜索失败: {status}")

# 步骤 14: 关系简报
status, data = api_call("GET", "/relationship-briefs")
if status == 200:
    log_ok("关系简报查询成功")
else:
    log_fail(f"关系简报查询失败: {status}")

# 步骤 15: 数据导出
status, data = api_call("GET", f"/export/{E2E_USER_ID}")
if status == 200:
    log_ok("数据导出成功")
else:
    log_fail(f"数据导出失败: {status}")


# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"测试完成：✅ {passed} 通过，❌ {failed} 失败")
if failed == 0:
    print("🎉 所有测试通过！")
    sys.exit(0)
else:
    print("⚠️  部分测试失败，请检查服务状态")
    sys.exit(1)
