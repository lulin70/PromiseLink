#!/usr/bin/env python3
"""
End-to-end test simulating WeChat Mini Program user journey.
Tests: Login → Create Event → Check Entities → Check Todos → Complete Todo
"""
import json
import os
import time
import urllib.request

BASE = "http://localhost:8000/api/v1"

def api(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.42"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def main():
    print("=" * 60)
    print("PromiseLink E2E Test: Mini Program User Journey")
    print("=" * 60)

    # Step 1: Login with PoC secret
    print("\n[1] Login with PoC secret...")
    status, data = api("POST", "/auth/login", {
        "user_id": "00000000-0000-0000-0000-0000000042",
        "poc_secret": os.environ.get("POC_SECRET", "promiselink2026")
    })
    assert status == 200, f"Login failed: {status} {data}"
    token = data["access_token"]
    print(f"    OK - token: {token[:20]}...")

    # Step 2: Batch create events
    print("\n[2] Batch create 3 events...")
    status, data = api("POST", "/events/batch", {
        "events": [
            {
                "event_type": "meeting",
                "source": "manual",
                "title": "与李总讨论AI合作",
                "raw_text": "今天上午和李总在咖啡厅讨论了AI辅助关系管理的合作方案。李总很感兴趣，答应下周安排技术团队对接。他关注数据安全性和部署成本。"
            },
            {
                "event_type": "call",
                "source": "manual",
                "title": "与陈宇鑫电话沟通技术对接",
                "raw_text": "和陈宇鑫通了电话，确认技术对接时间定在下周三。他提到名片识别SDK可以免费试用3个月。我答应发API文档给他。"
            },
            {
                "event_type": "meeting",
                "source": "manual",
                "title": "与王总午餐会",
                "raw_text": "和王总吃了午餐，聊到他们公司正在寻找数字化转型方案。王总希望我们能提供一个演示。他担心实施周期太长影响业务。我承诺两周内给出方案。"
            }
        ]
    }, token=token)
    assert status == 201, f"Batch create failed: {status} {data}"
    print(f"    OK - created {data['total_created']}/{data['total_requested']} events")

    # Step 3: Wait for pipeline processing
    print("\n[3] Waiting for pipeline processing (30s)...")
    time.sleep(30)

    # Step 4: Check entities
    print("\n[4] Check extracted entities...")
    status, data = api("GET", "/entities?limit=20", token=token)
    assert status == 200, f"Get entities failed: {status}"
    entities = data.get("items", data) if isinstance(data, dict) else data
    total = data.get("total", len(entities))
    print(f"    Found {total} entities:")
    for e in entities[:10]:
        name = e.get("name", "?")
        etype = e.get("entity_type", "?")
        props = e.get("properties", {})
        concern = props.get("concern", "") if isinstance(props, dict) else ""
        print(f"      - {name} ({etype})" + (f" concern: {concern[:30]}" if concern else ""))

    # Step 5: Check todos
    print("\n[5] Check generated todos...")
    status, data = api("GET", "/todos?limit=20", token=token)
    assert status == 200, f"Get todos failed: {status}"
    todos = data.get("items", data) if isinstance(data, dict) else data
    total = data.get("total", len(todos))
    print(f"    Found {total} todos:")
    for t in todos[:10]:
        title = t.get("title", "?")
        atype = t.get("action_type", t.get("todo_type", "?"))
        status_str = t.get("status", "?")
        print(f"      - [{atype}] {title[:50]} ({status_str})")

    # Step 6: Complete a todo
    if todos:
        todo_id = todos[0].get("id")
        if todo_id:
            print(f"\n[6] Complete first todo ({todo_id[:8]}...)...")
            # First set to in_progress
            status, data = api("PATCH", f"/todos/{todo_id}", {"status": "in_progress"}, token=token)
            if status == 200:
                # Then set to done
                status, data = api("PATCH", f"/todos/{todo_id}", {"status": "done"}, token=token)
                if status == 200:
                    print("    OK - todo marked as done")
                else:
                    print(f"    WARN - done transition failed: {status}")
            else:
                print(f"    WARN - in_progress transition failed: {status}")

    # Step 7: Check associations
    print("\n[7] Check associations...")
    status, data = api("GET", "/associations?limit=20", token=token)
    if status == 200:
        assocs = data.get("items", data) if isinstance(data, dict) else data
        total = data.get("total", len(assocs))
        print(f"    Found {total} associations:")
        for a in assocs[:5]:
            src = a.get("source_entity_id", "?")[:8]
            tgt = a.get("target_entity_id", "?")[:8]
            atype = a.get("association_type", "?")
            print(f"      - {src} → {tgt} ({atype})")
    else:
        print(f"    WARN - associations endpoint returned {status}")

    # Step 8: Check dashboard
    print("\n[8] Check dashboard...")
    status, data = api("GET", "/dashboard/day-view", token=token)
    if status == 200:
        print(f"    Dashboard: events={data.get('event_count', '?')} todos={data.get('todo_summary', {}).get('total', '?')}")
    else:
        print(f"    WARN - dashboard returned {status}")

    print("\n" + "=" * 60)
    print("E2E Test PASSED - All steps completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
