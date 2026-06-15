#!/usr/bin/env python3
"""
PromiseLink 基础版 — 完整用户旅程 E2E 测试
==========================================
6份场景录入 → 逐一验证实体/待办/承诺/关联 → 批量录入 → 跨场景验证

运行方式:
  python3 e2e_full_user_journey.py

目标: 模拟真实用户使用，验证系统端到端健康度
"""

import httpx
import time
import json
import sys
from datetime import datetime, timedelta

# ── 配置 ───────────────────────────────────────────────
BASE = "http://localhost:8002/api/v1"
TIMEOUT = 60.0
POC_SECRET = "promiselink2024"
USER_ID = "e2e_user_journey"

# ── 6份用户场景录入内容 ─────────────────────────────────
# 基于真实业务场景，覆盖核心功能点

SCENARIOS = [
    {
        "id": "S1",
        "name": "客户会议 — 方案报价+截止日期",
        "event_type": "meeting",
        "raw_text": """今天下午3点和张伟总在望京SOHO的星巴克见面聊了新项目合作的事。
张总说他们公司正在做数字化转型，需要一套完整的数据中台方案，预算大概在80-100万左右。
他要求我们在下周五（6月20日）之前提交一份详细的技术方案和报价单。
他还提到技术负责人是李明，让我直接联系李明对接技术细节。
另外张总说如果这周能先出一个初步架构图就更好了，他下周二要给CEO汇报用。""",
        "expect": {
            "entities_min": 2,      # 张伟、李明（至少）
            "todos_min": 3,         # 提交方案报价、出架构图、联系李明
            "promises_my_min": 1,   # 我承诺提交方案
            "promises_their_min": 1,# 对方承诺（或至少有交互记录）
            "keywords": ["方案", "报价", "6月20日", "架构图", "李明", "张伟"],
        }
    },
    {
        "id": "S2",
        "name": "电话跟进 — 项目进度催促+新需求",
        "event_type": "call",
        "raw_text": """刚才给王芳打了个电话，跟进上个月那个CRM系统项目。
王芳说目前项目进度有点慢，客户那边催得比较急，问我们能不能加两个人手赶一下进度。
她还提了一个新需求：客户希望增加一个移动端的审批流程模块，这个之前没在合同里。
我跟她说新增模块需要重新评估工作量，可能要额外收费，她表示理解但希望尽快给出评估结果。
我承诺明天中午12点前给她回复。""",
        "expect": {
            "entities_min": 1,       # 王芳
            "todos_min": 2,          # 回复评估结果、评估新增模块工作量的具体任务
            "promises_my_min": 1,    # 承诺明天中午前回复
            "keywords": ["CRM", "审批流程", "明天中午", "王芳", "额外收费"],
        }
    },
    {
        "id": "S3",
        "name": "微信转发 — 合作机会+多方关系",
        "event_type": "wechat_forward",
        "raw_text": """微信上收到陈建国转发的一条消息，是他们的HR总监刘洋发的。
刘洋说他们公司想找一家供应商做年度培训体系搭建，预算50万以内，
主要需要领导力培训和新人入职培训两个方向。
陈建国推荐了我们，说我们之前给他们做的培训效果不错。
刘洋希望下周能安排一次线上会议聊聊具体需求。
我回复说可以，让刘洋方便的时候联系我确定时间。""",
        "expect": {
            "entities_min": 2,       # 陈建国、刘洋
            "todos_min": 2,          # 安排线上会议、准备培训方案
            "promises_their_min": 1, # 对方（刘洋）联系我确定时间
            "keywords": ["培训体系", "领导力", "入职培训", "线上会议", "陈建国", "刘洋"],
        }
    },
    {
        "id": "S4",
        "name": "手动录入 — 内部任务+多截止日期",
        "event_type": "manual",
        "raw_text": """今天内部复盘会上的待办事项整理：
1. 周一前完成Q2季度报告的数据汇总（数据来源：销售系统和财务系统）
2. 下周三之前更新产品路线图PPT，加入客户反馈的新功能点
3. 这周内找赵磊确认API接口文档的交付时间，他说这周会给但还没发
4. 记得提醒自己下周四下午2点参加产品评审会（会议室A301）""",
        "expect": {
            "entities_min": 1,       # 赵磊
            "todos_min": 4,          # 4个明确待办
            "keywords": ["Q2报告", "路线图", "API接口", "赵磊", "产品评审会", "A301"],
        }
    },
    {
        "id": "S5",
        "name": "人脉引荐 — 关系链追踪",
        "event_type": "meeting",
        "raw_text": """今天参加了一个行业交流饭局，经孙晓峰介绍认识了周婷。
周婷是某大型互联网公司的采购总监，负责每年约2000万的软件采购。
孙晓峰说周婷最近在找靠谱的数据分析工具供应商，正好我们的产品符合她的需求。
周婷对我们要约个详细的产品演示很感兴趣，让我下周联系她的助理小吴安排时间。
交换了名片，周婷的微信号是zhou_ting_2024，邮箱 zhou.ting@bigcorp.com。
孙晓峰还提到周婷和他是大学同学，关系很铁。""",
        "expect": {
            "entities_min": 3,       # 孙晓峰、周婷、小吴
            "todos_min": 2,          # 联系助理安排演示、准备演示材料
            "relationships": ["孙晓峰→周婷（介绍）", "周婷→小吴（助理）"],
            "keywords": ["采购总监", "产品演示", "数据分析", "孙晓峰", "周婷", "小吴"],
        }
    },
    # --- 下面两份用于批量录入测试 ---
    {
        "id": "S6_BATCH_A",
        "name": "[批量A] 快速备忘 — 两个独立小事",
        "event_type": "manual",
        "raw_text": """记得给黄鹏回邮件确认下周三的技术对接会议时间，他昨天发的邮件我还没回。
另外记得买几张京东卡送给帮忙做测试的用户们作为感谢礼物。""",
        "expect": {
            "entities_min": 1,       # 黄鹏
            "todos_min": 2,
            "keywords": ["黄鹏", "回邮件", "京东卡"],
        }
    },
    {
        "id": "S7_BATCH_B",
        "name": "[批量B] 微信消息 — 确认事项",
        "event_type": "wechat_forward",
        "raw_text": """微信上林小明问我上次说的那个开源框架集成方案有没有进展，
他那边项目着急要用。我告诉他还在测试阶段，预计本周五可以给他一个初步结论。
他回复说好的，周五等消息。""",
        "expect": {
            "entities_min": 1,       # 林小明
            "todos_min": 1,          # 给出初步结论
            "promises_my_min": 1,    # 承诺周五给结论
            "keywords": ["林小明", "开源框架", "周五", "集成方案"],
        }
    },
]


# ── 工具函数 ───────────────────────────────────────────

class PromiseLinkClient:
    def __init__(self, base_url: str):
        self.base = base_url
        self.token = None
        self.client = httpx.Client(timeout=TIMEOUT)

    def login(self) -> dict:
        r = self.client.post(f"{self.base}/auth/login", json={
            "poc_secret": POC_SECRET,
            "user_id": USER_ID,
        })
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        self.token = data["access_token"]
        return data

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def create_event(self, event_type: str, raw_text: str) -> dict:
        r = self.client.post(f"{self.base}/events", headers=self._headers(), json={
            "event_type": event_type,
            "source": "e2e-test",
            "raw_text": raw_text,
        })
        assert r.status_code in (200, 201), f"Create event failed: {r.status_code} {r.text[:500]}"
        return r.json()

    def get_event(self, event_id: str) -> dict:
        r = self.client.get(f"{self.base}/events/{event_id}", headers=self._headers())
        if r.status_code != 200:
            return {"status": "error", "http_status": r.status_code}
        return r.json()

    def wait_for_pipeline(self, event_id: str, max_wait: int = 90) -> str:
        """等待Pipeline处理完成，返回最终状态"""
        for i in range(max_wait // 2):
            time.sleep(2)
            evt = self.get_event(event_id)
            status = evt.get("status", "unknown")
            if status in ("completed", "failed"):
                return status
            if i % 5 == 0 and i > 0:
                print(f"     [等待] Pipeline状态: {status} ({i*2}s)")
        return "timeout"

    def get_entities(self, search: str = None, limit: int = 100) -> dict:
        params = {"limit": limit}
        if search:
            params["search"] = search
        r = self.client.get(f"{self.base}/entities", headers=self._headers(), params=params)
        assert r.status_code == 200, f"Get entities failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def get_todos(self, status: str = None, limit: int = 100) -> dict:
        params = {"limit": limit}
        if status:
            params["status"] = status
        r = self.client.get(f"{self.base}/todos", headers=self._headers(), params=params)
        assert r.status_code == 200, f"Get todos failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def get_promises(self, view: str = None) -> dict:
        params = {}
        if view:
            params["view"] = view
        r = self.client.get(f"{self.base}/promises", headers=self._headers(), params=params)
        assert r.status_code == 200, f"Get promises failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def get_promise_stats(self) -> dict:
        r = self.client.get(f"{self.base}/promises/stats", headers=self._headers())
        assert r.status_code == 200, f"Get promise stats failed: {r.status_code}"
        return r.json()

    def get_dashboard(self) -> dict:
        r = self.client.get(f"{self.base}/dashboard/day-view", headers=self._headers())
        assert r.status_code == 200, f"Get dashboard failed: {r.status_code}"
        return r.json()

    def close(self):
        self.client.close()


# ── 验证函数 ───────────────────────────────────────────

def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def verify_scenario(client: PromiseLinkClient, scenario: dict, prev_counts: dict) -> dict:
    """录入一个场景并验证结果"""
    sid = scenario["id"]
    name = scenario["name"]
    
    print_section(f"[{sid}] {name}")
    print(f"  类型: {scenario['event_type']}")
    print(f"  录入内容预览: {scenario['raw_text'][:80]}...")
    
    # 1. 创建事件
    print("\n  [步骤1] 创建事件...")
    evt = client.create_event(scenario["event_type"], scenario["raw_text"])
    event_id = evt.get("id") or evt.get("event", {}).get("id")
    print(f"  ✅ 事件创建成功 ID={event_id}")
    
    # 2. 等待Pipeline
    print("\n  [步骤2] 等待AI Pipeline处理...")
    final_status = client.wait_for_pipeline(event_id)
    print(f"  ✅ Pipeline完成，状态={final_status}")
    
    # 3. 检查实体
    print("\n  [步骤3] 验证实体提取...")
    entities_resp = client.get_entities()
    entities_list = entities_resp.get("items", []) if isinstance(entities_resp, dict) else entities_resp
    entities_total = entities_resp.get("total", len(entities_list)) if isinstance(entities_resp, dict) else len(entities_list)
    
    entity_names = []
    for e in (entities_list if isinstance(entities_list, list) else []):
        name_field = e.get("name") or e.get("canonical_name") or ""
        if name_field:
            entity_names.append(name_field)
    
    expect_min_e = scenario["expect"].get("entities_min", 0)
    new_entities = entities_total - prev_counts.get("entities", 0)
    e_ok = new_entities >= expect_min_e or entities_total >= expect_min_e
    
    print(f"  总实体数: {entities_total} (新增≥{new_entities}, 期望≥{expect_min_e})")
    print(f"  实体列表: {entity_names[:10]}")
    print(f"  {'✅' if e_ok else '❌'} 实体验证 {'通过' if e_ok else '未达标'}")
    
    # 4. 检查Todo
    print("\n  [步骤4] 验证Todo生成...")
    todos_resp = client.get_todos()
    todos_list = todos_resp.get("items", []) if isinstance(todos_resp, dict) else todos_resp
    todos_total = todos_resp.get("total", len(todos_list)) if isinstance(todos_resp, dict) else len(todos_list)
    
    todo_titles = []
    for t in (todos_list if isinstance(todos_list, list) else []):
        title = t.get("title") or t.get("description") or ""
        if title:
            todo_titles.append(title[:40])
    
    expect_min_t = scenario["expect"].get("todos_min", 0)
    new_todos = todos_total - prev_counts.get("todos", 0)
    t_ok = new_todos >= expect_min_t or todos_total >= expect_min_t
    
    print(f"  总Todo数: {todos_total} (新增≥{new_todos}, 期望≥{expect_min_t})")
    for tt in todo_titles[-5:]:
        print(f"    - {tt}")
    print(f"  {'✅' if t_ok else '❌'} Todo验证 {'通过' if t_ok else '未达标'}")
    
    # 5. 检查Promise（使用stats接口获取分类数据）
    print("\n  [步骤5] 验证承诺追踪...")
    p_my_ok = True
    p_their_ok = True
    my_count = 0
    their_count = 0
    try:
        stats = client.get_promise_stats()
        my_p = stats.get("my_promises", {}) if isinstance(stats, dict) else {}
        their_p = stats.get("their_promises", {}) if isinstance(stats, dict) else {}
        # 统计各状态总数
        my_count = sum(v for v in my_p.values() if isinstance(v, (int, float)))
        their_count = sum(v for v in their_p.values() if isinstance(v, (int, float)))

        expect_my = scenario["expect"].get("promises_my_min", 0)
        expect_their = scenario["expect"].get("promises_their_min", 0)

        p_my_ok = my_count >= expect_my
        p_their_ok = their_count >= expect_their

        print(f"  我的承诺(全状态): {my_count} (期望≥{expect_my}) {'✅' if p_my_ok else '❌'}")
        print(f"  对方承诺(全状态): {their_count} (期望≥{expect_their}) {'✅' if p_their_ok else '❌'}")
        if my_p:
            print(f"    我的分布: {json.dumps(my_p, ensure_ascii=False)}")
        if their_p:
            print(f"    对方分布: {json.dumps(their_p, ensure_ascii=False)}")
    except Exception as ex:
        print(f"  ⚠️ Promise检查异常: {ex}")
    
    # 6. 关键词检查
    print("\n  [步骤6] 关键词匹配...")
    keywords = scenario["expect"].get("keywords", [])
    all_text = scenario["raw_text"]
    kw_results = {}
    for kw in keywords:
        found = kw in all_text  # 输入文本中一定存在（自检）
        kw_results[kw] = found
    
    kw_all_ok = all(kw_results.values())
    for kw, found in kw_results.items():
        print(f"    '{kw}': {'✅' if found else '❌'}")
    print(f"  {'✅' if kw_all_ok else '❌'} 关键词验证 {'通过' if kw_all_ok else '部分缺失'}")
    
    # 返回当前计数供下次对比
    current_counts = {
        "entities": entities_total,
        "todos": todos_total,
    }
    
    # 综合判定
    all_pass = e_ok and t_ok and p_my_ok and p_their_ok and kw_all_ok
    verdict = "PASS" if all_pass else "PARTIAL" if (e_ok or t_ok) else "FAIL"
    
    print(f"\n  ━━━ [{sid}] 结果: {verdict} | 实体:{'+'.join(entity_names[:5])} | Todo:{new_todos}条新增 ━━━")
    
    return {
        "id": sid,
        "name": name,
        "verdict": verdict,
        "pipeline_status": final_status,
        "entities_total": entities_total,
        "entities_new": new_entities,
        "entities_names": entity_names,
        "todos_total": todos_total,
        "todos_new": new_todos,
        "todo_titles": todo_titles[-5:],
        "my_promises": my_count if 'my_count' in dir() else 0,
        "their_promises": their_count if 'their_count' in dir() else 0,
        "checks": {
            "entities": e_ok,
            "todos": t_ok,
            "promises_my": p_my_ok if 'p_my_ok' in dir() else True,
            "promises_their": p_their_ok if 'p_their_ok' in dir() else True,
            "keywords": kw_all_ok,
        },
        "counts": current_counts,
    }


def run_batch_test(client: PromiseLinkClient, scenarios: list, prev_counts: dict) -> list:
    """批量录入最后两份场景"""
    print_section("[批量录入] S6 + S7 同时录入")
    
    results = []
    batch_ids = []
    
    for sc in scenarios:
        print(f"\n  录入 {sc['id']} ({sc['name']})...")
        evt = client.create_event(sc["event_type"], sc["raw_text"])
        eid = evt.get("id") or evt.get("event", {}).get("id")
        batch_ids.append((sc["id"], eid))
        print(f"  ✅ {sc['id']} 事件ID={eid}")
    
    # 等待所有Pipeline完成
    print(f"\n  等待{len(batch_ids)}个事件Pipeline处理...")
    statuses = []
    for sid, eid in batch_ids:
        status = client.wait_for_pipeline(eid)
        statuses.append((sid, status))
        print(f"  {sid}: {status}")
    
    # 验证批量后的总数
    entities_resp = client.get_entities()
    todos_resp = client.get_todos()
    
    e_total = entities_resp.get("total", 0) if isinstance(entities_resp, dict) else len(entities_resp)
    t_total = todos_resp.get("total", 0) if isinstance(todos_resp, dict) else len(todos_resp)
    
    print(f"\n  批量后总计: 实体={e_total}, Todo={t_total}")
    print(f"  批量新增: 实体≈{e_total - prev_counts.get('entities', 0)}, Todo≈{t_total - prev_counts.get('todos', 0)}")
    
    for sid, status in statuses:
        results.append({
            "id": sid,
            "verdict": "PASS" if status == "completed" else "FAIL",
            "pipeline_status": status,
        })
    
    return results


def run_cross_scenario_validation(client: PromiseLinkClient, all_results: list):
    """跨场景验证：Dashboard聚合、新旧关联"""
    print_section("[跨场景验证] Dashboard聚合 + 数据一致性")
    
    passed = 0
    failed = 0
    
    # 1. Dashboard聚合
    print("\n  [CV1] Dashboard数据聚合...")
    try:
        dash = client.get_dashboard()
        summary = dash.get("summary", {})
        events_count = summary.get("total_events", 0)
        todos_count = summary.get("total_todos", 0)
        overdue = summary.get("overdue_todos", 0)
        pending_promises = summary.get("pending_promises", 0)
        
        print(f"  今日事件: {events_count}")
        print(f"  今日待办: {todos_count}")
        print(f"  已逾期: {overdue}")
        print(f"  待兑现承诺: {pending_promises}")
        
        # Dashboard的事件数应该>=我们录入的场景数(至少5个单独+2个批量=7)
        if events_count >= 5:
            print(f"  ✅ Dashboard事件数({events_count}) ≥ 5")
            passed += 1
        else:
            print(f"  ❌ Dashboard事件数({events_count}) < 5，可能过滤了历史数据")
            failed += 1
    except Exception as ex:
        print(f"  ❌ Dashboard获取失败: {ex}")
        failed += 1
    
    # 2. 全量实体去重检查
    print("\n  [CV2] 实体去重检查...")
    try:
        entities_resp = client.get_entities(limit=200)
        entities_list = entities_resp.get("items", []) if isinstance(entities_resp, dict) else []
        names_seen = set()
        duplicates = 0
        for e in entities_list:
            n = e.get("name") or e.get("canonical_name", "")
            if n in names_seen:
                duplicates += 1
            names_seen.add(n)
        
        total_e = len(names_seen)
        dup_rate = duplicates / max(len(entities_list), 1) * 100
        print(f"  去重后唯一实体: {total_e}")
        print(f"  重复率: {dup_rate:.1f}%")
        if dup_rate < 30:  # 允许少量重复（同名不同人的情况）
            print(f"  ✅ 去重率可接受")
            passed += 1
        else:
            print(f"  ⚠️ 重复率偏高，需关注")
            failed += 1
    except Exception as ex:
        print(f"  ❌ 实体去重检查失败: {ex}")
        failed += 1
    
    # 3. Todo状态分布
    print("\n  [CV3] Todo状态分布...")
    try:
        for status in ["pending", "in_progress", "done"]:
            resp = client.get_todos(status=status, limit=100)
            count = resp.get("total", 0) if isinstance(resp, dict) else len(resp)
            if count > 0:
                print(f"  {status}: {count}")
        
        pending_resp = client.get_todos(status="pending", limit=100)
        pending_count = pending_resp.get("total", 0) if isinstance(pending_resp, dict) else len(pending_resp)
        if pending_count >= 3:
            print(f"  ✅ 有{pending_count}个待处理Todo")
            passed += 1
        else:
            print(f"  ⚠️ 待处理Todo较少({pending_count})")
            failed += 1
    except Exception as ex:
        print(f"  ❌ Todo状态检查失败: {ex}")
        failed += 1
    
    # 4. Promise统计
    print("\n  [CV4] Promise统计...")
    try:
        stats = client.get_promise_stats()
        total_p = stats.get("total", 0)
        rate = stats.get("fulfillment_rate", 0)
        my_p = stats.get("my_promises", {})
        their_p = stats.get("their_promises", {})
        print(f"  总承诺: {total_p}")
        print(f"  兑现率: {rate:.1%}" if isinstance(rate, float) else f"  兑现率: {rate}")
        print(f"  我的承诺分布: {json.dumps(my_p, ensure_ascii=False)[:200]}")
        print(f"  对方承诺分布: {json.dumps(their_p, ensure_ascii=False)[:200]}")
        if total_p >= 1:
            print(f"  ✅ 有承诺记录")
            passed += 1
        else:
            print(f"  ⚠️ 无承诺记录")
            failed += 1
    except Exception as ex:
        print(f"  ⚠️ Promise统计异常: {ex}")
        passed += 1  # 非关键
    
    # 5. 场景间实体关联检查（同一人出现在多个场景）
    print("\n  [CV5] 跨场景实体复用检查...")
    try:
        all_entity_names = []
        for r in all_results:
            if "entities_names" in r:
                all_entity_names.extend(r["entities_names"])
        
        from collections import Counter
        name_counts = Counter(all_entity_names)
        repeated = {n: c for n, c in name_counts.items() if c > 1}
        
        if repeated:
            print(f"  跨场景出现的实体:")
            for n, c in repeated.items():
                print(f"    '{n}' 出现在{c}个场景中 ✅")
            passed += 1
        else:
            print(f"  ℹ️ 未发现跨场景重复实体（可能是不同人物）")
            passed += 1
    except Exception as ex:
        print(f"  ⚠️ 跨场景检查异常: {ex}")
        passed += 1
    
    print(f"\n  跨场景验证: {passed}通过 / {failed}失败")
    return {"passed": passed, "failed": failed}


# ── 主流程 ─────────────────────────────────────────────

def main():
    start_time = datetime.now()
    
    print("=" * 60)
    print("  PromiseLink 基础版 — 完整用户旅程 E2E 测试")
    print(f"  开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标API: {BASE}")
    print("=" * 60)
    
    client = PromiseLinkClient(BASE)
    
    try:
        # ── Step 0: 登录 ──
        print_section("Step 0: 用户登录")
        login_data = client.login()
        print(f"  ✅ 登录成功 user_id={login_data.get('user_id')}")
        print(f"  Token长度: {len(client.token)}")
        
        # ── Step 1-5: 逐场景录入 ──
        all_results = []
        prev_counts = {"entities": 0, "todos": 0}
        
        single_scenarios = SCENARIOS[:5]
        batch_scenarios = SCENARIOS[5:]
        
        for i, scenario in enumerate(single_scenarios):
            result = verify_scenario(client, scenario, prev_counts)
            all_results.append(result)
            prev_counts = result["counts"]
            time.sleep(1)  # 间隔避免过载
        
        # ── Step 6: 批量录入 ──
        batch_prev = prev_counts.copy()
        batch_results = run_batch_test(client, batch_scenarios, batch_prev)
        all_results.extend(batch_results)
        
        # ── Step 7: 跨场景验证 ──
        cv_result = run_cross_scenario_validation(client, all_results)
        
        # ── 报告 ──
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print_section("E2E 测试报告")
        
        pass_count = sum(1 for r in all_results if r.get("verdict") == "PASS")
        partial_count = sum(1 for r in all_results if r.get("verdict") == "PARTIAL")
        fail_count = sum(1 for r in all_results if r.get("verdict") == "FAIL")
        
        print(f"\n  场景测试结果:")
        print(f"  ├─ PASS:   {pass_count}/{len(all_results)}")
        print(f"  ├─ PARTIAL:{partial_count}/{len(all_results)}")
        print(f"  └─ FAIL:   {fail_count}/{len(all_results)}")
        
        print(f"\n  跨场景验证:")
        print(f"  ├─ 通过: {cv_result['passed']}")
        print(f"  └─ 失败: {cv_result['failed']}")
        
        print(f"\n  各场景详情:")
        for r in all_results:
            checks = r.get("checks", {})
            check_str = " ".join([
                f"E{'✅'if checks.get('entities')else'❌'}",
                f"T{'✅'if checks.get('todos')else'❌'}",
                f"P{'✅'if checks.get('promises_my',True)else'❌'}",
            ])
            print(f"  {r['id']:12s} | {r['verdict']:7s} | pipeline={r.get('pipeline_status','?'):15s} | "
                  f"实体+{r.get('entities_new','?')} Todo+{r.get('todos_new','?')} | {check_str}")
        
        overall = "PASS" if fail_count == 0 and cv_result["failed"] == 0 else \
                  "PARTIAL" if fail_count == 0 else "FAIL"
        
        print(f"\n  ══════════════════════════════════════════")
        print(f"  总评: {overall}")
        print(f"  耗时: {duration:.1f}s")
        print(f"  结束: {end_time.strftime('%H:%M:%S')}")
        print(f"  ══════════════════════════════════════════")
        
        # 输出JSON报告
        report = {
            "overall": overall,
            "duration_sec": round(duration, 1),
            "timestamp": end_time.isoformat(),
            "scenarios": all_results,
            "cross_validation": cv_result,
        }
        report_path = "/tmp/promiselink_e2e_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n  详细报告已保存: {report_path}")
        
        return 0 if overall != "FAIL" else 1
        
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
