#!/usr/bin/env python3
"""Check event pipeline status"""
import httpx, asyncio, json, sys

async def check():
    async with httpx.AsyncClient(base_url="http://localhost:8002", timeout=60) as c:
        BASE = "http://localhost:8002/api/v1"
        r = await c.post(f"{BASE}/auth/login", json={"user_id": "demo-user", "poc_secret": "promiselink2026"})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # List events
        r = await c.get(f"{BASE}/events", headers=headers)
        events = r.json()
        items = events if isinstance(events, list) else events.get("items", [])
        for e in items:
            eid = e["id"]
            status = e.get("status", "?")
            print(f"Event {eid[:8]}: status={status}")

            # Get event detail
            r2 = await c.get(f"{BASE}/events/{eid}", headers=headers)
            if r2.status_code == 200:
                detail = r2.json()
                print(f"  pipeline_status={detail.get('pipeline_status', '?')}")
                if detail.get("error"):
                    print(f"  error={detail['error']}")

        # Check todos
        r = await c.get(f"{BASE}/todos", headers=headers)
        todos = r.json()
        todo_items = todos if isinstance(todos, list) else todos.get("items", [])
        print(f"\nTodos: {len(todo_items)}")
        for t in todo_items:
            print(f"  - [{t.get('todo_type','?')}] {t.get('title','?')[:50]} ({t.get('status','?')})")

        # Check server logs for pipeline errors
        print("\n--- Recent server logs (pipeline related) ---")

asyncio.run(check())
