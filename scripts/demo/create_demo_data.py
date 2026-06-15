#!/usr/bin/env python3
"""Create demo data for poc-user so they see real content on login"""
import httpx, time, json

BASE = "http://localhost:8002/api/v1"
c = httpx.Client(timeout=60)

# Login as poc-user
r = c.post(f"{BASE}/auth/login", json={"poc_secret": "promiselink2024", "user_id": "poc-user"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
print(f"Logged in as poc-user")

# Create 3 demo events with real Chinese business scenarios
events = [
    {
        "event_type": "meeting",
        "source": "manual",
        "raw_text": "今天下午2点和张伟总在望京SOHO星巴克见面聊了新项目合作。张总说他们公司正在做数字化转型，需要一套数据中台方案，预算80-100万。要求下周五（6月20日）前提交技术方案和报价。还介绍了技术负责人李明给我对接。另外张总说如果本周能先出初步架构图更好，他下周二要给CEO汇报。"
    },
    {
        "event_type": "call", 
        "source": "manual",
        "raw_text": "刚才给王芳打了个电话跟进上个月CRM系统项目进度。王芳说客户催得比较急问能不能加两个人手。她还提了一个新需求：客户希望增加移动端审批流程模块（合同里没有）。我承诺明天中午12点前给她回复评估结果和额外收费方案。"
    },
    {
        "event_type": "wechat_forward",
        "source": "manual", 
        "raw_text": "微信收到陈建国转发消息，是他们HR总监刘洋发的。刘洋说公司想找供应商做年度培训体系搭建，预算50万内，主要需要领导力培训和新人入职培训两个方向。陈建国推荐了我们。刘洋希望下周安排线上会议聊具体需求。我回复说方便时联系我确定时间。"
    },
]

print(f"\nCreating {len(events)} demo events...")
for i, evt in enumerate(events):
    print(f"\n  [{i+1}/{len(events)}] Creating {evt['event_type']}...")
    r = c.post(f"{BASE}/events", headers=h, json=evt)
    assert r.status_code in (200, 201), f"Failed: {r.status_code} {r.text[:200]}"
    event_id = r.json().get("id") or r.json().get("event", {}).get("id")
    print(f"      Event ID: {event_id}")
    
    # Wait for pipeline
    for j in range(30):
        time.sleep(2)
        er = c.get(f"{BASE}/events/{event_id}", headers=h)
        if er.status_code == 200:
            status = er.json().get("status", "?")
            if status in ("completed", "failed"):
                print(f"      Pipeline: {status}")
                break
            if j % 3 == 2:
                print(f"      ...processing ({j*2}s)")
    else:
        print(f"      Pipeline timeout")

# Check results
print("\n=== Results for poc-user ===")
d = c.get(f"{BASE}/dashboard/day-view", headers=h).json()
s = d.get("summary", {})
print(f"Dashboard: events={s.get('total_events',0)} todos={s.get('total_todos',0)} overdue={s.get('overdue_todos',0)} promises={s.get('pending_promises',0)}")

t = c.get(f"{BASE}/todos?limit=10", headers=h).json()
total_t = t.get("total", 0) if isinstance(t, dict) else len(t)
print(f"Todos: total={total_t}")
if isinstance(t, dict) and t.get("items"):
    for item in t["items"][:8]:
        print(f"  - {item.get('title', '?')[:60]}")

e = c.get(f"{BASE}/entities?limit=10", headers=h).json()
total_e = e.get("total", 0) if isinstance(e, dict) else len(e)
print(f"\nEntities: total={total_e}")
if isinstance(e, dict) and e.get("items"):
    for item in e["items"][:8]:
        print(f"  - {item.get('name', '?')} ({item.get('entity_type', '?')})")

p = c.get(f"{BASE}/promises/stats", headers=h).json()
print(f"\nPromises: {json.dumps(p, ensure_ascii=False)[:250]}")

print("\n✅ Demo data created! User can now log in and see real data.")
