#!/usr/bin/env python3
"""
PromiseLink PoC Demo - 模拟许总的真实使用场景
完整用户旅程：登录 → 记录交流 → 查看待办 → 查看关系 → 记录承诺 → 完成待办
"""
import httpx, uuid, time, json, os

BASE = "http://localhost:8001/api/v1"
SECRET = os.environ.get("POC_SECRET", "promiselink2024")

def demo():
    with httpx.Client(timeout=30) as c:
        print("=" * 70)
        print("  PromiseLink PoC Demo - 模拟许总的真实使用场景")
        print("=" * 70)

        # ═══════════════════════════════════════════════════════════
        # Scene 1: 许总首次登录
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 1: 许总首次登录")
        print("─" * 70)
        uid = str(uuid.uuid4())
        fake_ip = "10.0.99.1"
        r = c.post(f"{BASE}/auth/login",
                   json={"user_id": uid, "poc_secret": SECRET},
                   headers={"X-Forwarded-For": fake_ip})
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        print(f"  [POST /auth/login] status={r.status_code}")
        print(f"  user_id: {uid[:8]}...")
        print(f"  token:   {token[:20]}...")

        # 查看空状态
        r = c.get(f"{BASE}/events", headers=h)
        print(f"\n  [GET /events] 空状态: {r.json().get('total', 0)} events")
        r = c.get(f"{BASE}/todos", headers=h)
        print(f"  [GET /todos]  空状态: {r.json().get('total', 0)} todos")
        r = c.get(f"{BASE}/entities", headers=h)
        print(f"  [GET /entities] 空状态: {r.json().get('total', 0)} contacts")

        # ═══════════════════════════════════════════════════════════
        # Scene 2: 许总记录一次重要交流（与陈宇鑫讨论数字名片）
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 2: 许总记录一次重要交流")
        print("  「今天和陈宇鑫讨论了数字名片对接方案」")
        print("─" * 70)
        r = c.post(f"{BASE}/events", headers=h, json={
            "event_type": "meeting",
            "raw_text": "今天和陈宇鑫讨论了数字名片对接方案。陈宇鑫是数字名片公司的技术负责人，他表示可以提供API接口，包含姓名、公司、职位、联系方式等字段。我承诺本周五之前评估技术可行性并给反馈。陈宇鑫关心我们系统的数据安全合规性。",
            "source": "manual",
            "title": "与陈宇鑫讨论数字名片对接"
        })
        event1 = r.json()
        print(f"  [POST /events] status={r.status_code}")
        print(f"  event_id: {event1.get('id', '?')[:8]}")
        print(f"  title:    {event1.get('title', '?')}")
        print(f"  status:   {event1.get('status', '?')}")

        # ═══════════════════════════════════════════════════════════
        # Scene 3: 等待Pipeline处理，查看提取结果
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 3: 等待Pipeline处理（LLM提取实体和Todo）...")
        print("─" * 70)
        for i in range(5):
            print(f"  ... 等待中 ({(i+1)*5}s)")
            time.sleep(5)

        # 查看联系人
        r = c.get(f"{BASE}/entities", headers=h)
        entities = r.json().get("items", [])
        print(f"\n  [GET /entities] 提取到 {len(entities)} 个联系人:")
        for e in entities:
            name = e.get("name", "?")
            company = e.get("company", "")
            props = e.get("properties", {})
            concern = props.get("concern", "")
            capability = props.get("capability", "")
            print(f"    - {name}" + (f" ({company})" if company else ""))
            if concern:
                print(f"      关注: {concern}")
            if capability:
                print(f"      能力: {capability}")

        # 查看待办
        r = c.get(f"{BASE}/todos", headers=h)
        todos = r.json().get("items", [])
        print(f"\n  [GET /todos] 生成 {len(todos)} 个待办:")
        for t in todos:
            ttype = t.get("todo_type", "?")
            title = t.get("title", "?")
            priority = t.get("priority", "?")
            status = t.get("status", "?")
            print(f"    [{ttype}] {title} (优先级:{priority}, 状态:{status})")

        # ═══════════════════════════════════════════════════════════
        # Scene 4: 许总记录第二次交流（与李总讨论项目方案）
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 4: 许总记录第二次交流")
        print("  「与李总讨论项目方案，承诺周五前发送技术方案」")
        print("─" * 70)
        r = c.post(f"{BASE}/events", headers=h, json={
            "event_type": "meeting",
            "raw_text": "与李总开会讨论项目方案。李总是华创科技的CEO，他关心项目交付时间，希望7月底前上线。我承诺本周五前发送技术方案给他。李总答应安排技术团队下周做评审。",
            "source": "manual",
            "title": "与李总讨论项目方案"
        })
        print(f"  [POST /events] status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # Scene 5: 许总记录一次电话跟进
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 5: 许总记录一次电话跟进")
        print("  「给王总打电话确认合作意向」")
        print("─" * 70)
        r = c.post(f"{BASE}/events", headers=h, json={
            "event_type": "call",
            "raw_text": "给王总打电话确认合作意向。王总是盛达集团的采购总监，他说正在寻找新的供应商，对我们的方案感兴趣。我答应明天发详细报价单给他。王总担心售后服务响应速度。",
            "source": "manual",
            "title": "与王总电话确认合作意向"
        })
        print(f"  [POST /events] status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # Scene 6: 等待Pipeline处理所有事件
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 6: 等待Pipeline处理所有事件...")
        print("─" * 70)
        for i in range(6):
            print(f"  ... 等待中 ({(i+1)*5}s)")
            time.sleep(5)

        # ═══════════════════════════════════════════════════════════
        # Scene 7: 查看完整的仪表盘
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 7: 查看今日仪表盘")
        print("─" * 70)
        r = c.get(f"{BASE}/dashboard/day-view", headers=h)
        dash = r.json()
        s = dash.get("summary", {})
        print(f"  日期: {dash.get('date_label', '?')}")
        print(f"  事件总数:   {s.get('total_events', 0)}")
        print(f"  待办总数:   {s.get('total_todos', 0)}")
        print(f"  逾期待办:   {s.get('overdue_todos', 0)}")
        print(f"  待履约承诺: {s.get('pending_promises', 0)}")

        # 查看所有联系人
        r = c.get(f"{BASE}/entities", headers=h)
        entities = r.json()
        total_ents = entities.get("total", 0)
        ent_items = entities.get("items", [])
        print(f"\n  联系人总数: {total_ents}")
        for e in ent_items:
            name = e.get("name", "?")
            company = e.get("company", "")
            props = e.get("properties", {})
            concern = props.get("concern", "")
            print(f"    - {name}" + (f" ({company})" if company else ""))
            if concern:
                print(f"      关注: {concern}")

        # 查看所有待办
        r = c.get(f"{BASE}/todos", headers=h)
        todos = r.json()
        total_todos = todos.get("total", 0)
        todo_items = todos.get("items", [])
        print(f"\n  待办总数: {total_todos}")
        for t in todo_items:
            ttype = t.get("todo_type", "?")
            title = t.get("title", "?")
            priority = t.get("priority", "?")
            status = t.get("status", "?")
            print(f"    [{ttype}] {title} (优先级:{priority}, 状态:{status})")

        # ═══════════════════════════════════════════════════════════
        # Scene 8: 完成一个待办
        # ═══════════════════════════════════════════════════════════
        if todo_items:
            print("\n" + "─" * 70)
            print("  Scene 8: 完成一个待办")
            print("─" * 70)
            todo_id = todo_items[0]["id"]
            todo_title = todo_items[0].get("title", "?")
            print(f"  完成待办: {todo_title}")
            r = c.patch(f"{BASE}/todos/{todo_id}", headers=h, json={"status": "in_progress"})
            print(f"  [PATCH /todos/{todo_id[:8]} -> in_progress] status={r.status_code}")
            if r.status_code == 200:
                r = c.patch(f"{BASE}/todos/{todo_id}", headers=h, json={"status": "done"})
                print(f"  [PATCH /todos/{todo_id[:8]} -> done] status={r.status_code}")
                if r.status_code == 200:
                    print(f"  待办已标记为完成!")
                else:
                    print(f"  响应: {r.text[:100]}")

        # ═══════════════════════════════════════════════════════════
        # Scene 9: 查看隐私数据摘要
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 9: 查看隐私数据摘要")
        print("─" * 70)
        r = c.get(f"{BASE}/privacy/data-summary", headers=h)
        if r.status_code == 200:
            summary = r.json()
            print(f"  数据摘要: {json.dumps(summary, ensure_ascii=False, indent=2)[:200]}...")
        else:
            print(f"  status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # Scene 10: 最终状态总览
        # ═══════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  Scene 10: 最终状态总览")
        print("─" * 70)
        r = c.get(f"{BASE}/events", headers=h)
        total_events = r.json().get("total", 0)
        r = c.get(f"{BASE}/entities", headers=h)
        total_entities = r.json().get("total", 0)
        r = c.get(f"{BASE}/todos", headers=h)
        total_todos = r.json().get("total", 0)
        completed = sum(1 for t in r.json().get("items", []) if t.get("status") == "done")

        print(f"  +──────────────────────────────────────+")
        print(f"  | 事件记录:  {total_events:>3} 条                     |")
        print(f"  | 联系人:    {total_entities:>3} 人                     |")
        print(f"  | 待办事项:  {total_todos:>3} 项 (已完成: {completed})       |")
        print(f"  +──────────────────────────────────────+")

        # ═══════════════════════════════════════════════════════════
        # Final
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        if total_events >= 3 and total_entities >= 1:
            print("  DEMO PASSED - PoC核心功能验证通过!")
        else:
            print("  DEMO PARTIAL - 部分功能需检查")
        print("=" * 70)

if __name__ == "__main__":
    demo()
