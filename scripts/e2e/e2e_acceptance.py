#!/usr/bin/env python3
"""PromiseLink PoC E2E Acceptance Test — 模拟许总的核心用户旅程"""
import asyncio
import os
import uuid

import httpx

BASE = "http://localhost:8001/api/v1"
SECRET = os.environ.get("POC_SECRET", "promiselink2026")
UID = str(uuid.uuid4())

async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        print("=" * 60)
        print("PromiseLink PoC E2E Acceptance Test")
        print("=" * 60)

        # Step 1: Login
        print("\n[Step 1] POC Secret Login")
        r = await c.post(f"{BASE}/auth/login", json={"user_id": UID, "poc_secret": SECRET})
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        print(f"  OK - user_id={UID[:8]}...")

        # Step 2: Record a meeting
        print("\n[Step 2] Record a meeting (discussing digital card integration)")
        r = await c.post(f"{BASE}/events", headers=h, json={
            "event_type": "meeting",
            "raw_text": "Today discussed digital card integration with Chen Yuxin. He promised to provide API docs next week. I promised to evaluate and give feedback.",
            "source": "manual",
            "title": "Discuss digital card integration with Chen Yuxin"
        })
        assert r.status_code in (200, 201), f"Create event failed: {r.status_code} {r.text[:200]}"
        event = r.json()
        event_id = event.get("id")
        print(f"  OK - event_id={event_id}, title={event.get('title', 'N/A')}")

        # Step 3: View todos
        print("\n[Step 3] View todos")
        r = await c.get(f"{BASE}/todos", headers=h)
        assert r.status_code == 200, f"Get todos failed: {r.status_code}"
        todos = r.json()
        items = todos.get("items", [])
        print(f"  OK - {len(items)} todos found")
        for t in items[:5]:
            print(f"    [{t.get('todo_type','?')}] {t.get('title','N/A')} (priority:{t.get('priority','?')})")

        # Step 4: View contacts
        print("\n[Step 4] View contacts")
        r = await c.get(f"{BASE}/entities", headers=h)
        assert r.status_code == 200, f"Get entities failed: {r.status_code}"
        entities = r.json()
        ent_items = entities.get("items", [])
        print(f"  OK - {len(ent_items)} contacts found")
        for e in ent_items[:5]:
            name = e.get("name", "N/A")
            company = e.get("company", "")
            print(f"    {name}" + (f" @ {company}" if company else ""))

        # Step 5: View dashboard
        print("\n[Step 5] View dashboard")
        r = await c.get(f"{BASE}/dashboard/day-view", headers=h)
        assert r.status_code == 200, f"Get dashboard failed: {r.status_code}"
        dash = r.json()
        summary = dash.get("summary", {})
        print(f"  OK - date: {dash.get('date_label', 'N/A')}")
        print(f"    events:{summary.get('total_events',0)} todos:{summary.get('total_todos',0)} overdue:{summary.get('overdue_todos',0)} pending_promises:{summary.get('pending_promises',0)}")

        # Step 6: Record a second event
        print("\n[Step 6] Record a second event (deployment discussion)")
        r = await c.post(f"{BASE}/events", headers=h, json={
            "event_type": "call",
            "raw_text": "Discussed deployment options. Client has no server or LLM key. I promised to provide a hosted deployment solution.",
            "source": "manual",
            "title": "Discuss deployment with client"
        })
        assert r.status_code in (200, 201), f"Create event2 failed: {r.status_code}"
        print("  OK - Second event recorded")

        # Step 7: View updated todos
        print("\n[Step 7] View updated todos")
        r = await c.get(f"{BASE}/todos", headers=h)
        todos2 = r.json().get("items", [])
        print(f"  OK - {len(todos2)} todos (was {len(items)})")
        for t in todos2[:3]:
            print(f"    [{t.get('todo_type','?')}] {t.get('title','N/A')}")

        # Step 8: Privacy data summary
        print("\n[Step 8] Privacy data summary")
        r = await c.get(f"{BASE}/privacy/data-summary", headers=h)
        if r.status_code == 200:
            print("  OK - data summary retrieved")
        else:
            print(f"  WARN - status: {r.status_code}")

        # Step 9: Health check
        print("\n[Step 9] Health check")
        r = await c.get(f"{BASE}/health")
        assert r.status_code == 200
        print(f"  OK - status: {r.json().get('status', 'N/A')}")

        print("\n" + "=" * 60)
        print("POC E2E ACCEPTANCE TEST PASSED!")
        print("=" * 60)

asyncio.run(main())
