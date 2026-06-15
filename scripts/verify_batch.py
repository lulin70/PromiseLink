#!/usr/bin/env python3
"""Verify batch events were processed by pipeline."""
import urllib.request, json, sys, os

BASE = "http://localhost:8000/api/v1"

def api_call(path, token):
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "10.0.0.99"}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())

def main():
    # Login
    data = json.dumps({"user_id": "00000000-0000-0000-0000-000000000099", "poc_secret": os.environ.get("POC_SECRET", "promiselink2024")}).encode()
    req = urllib.request.Request(f"{BASE}/auth/login", data=data, headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.99"})
    resp = urllib.request.urlopen(req, timeout=10)
    token = json.loads(resp.read())["access_token"]

    # Check events
    events = api_call("/events?limit=5", token)
    print(f"=== Events ({events['total']} total) ===")
    for e in events["items"]:
        print(f"  {e['title']} status={e['status']}")

    # Check todos
    todos = api_call("/todos?limit=10", token)
    print(f"\n=== Todos ({todos['total']} total) ===")
    for t in todos["items"][:8]:
        atype = t.get('action_type', t.get('todo_type', '?'))
        print(f"  [{atype}] {t['title']} status={t['status']}")

    # Check entities
    entities = api_call("/entities?limit=10", token)
    print(f"\n=== Entities ({entities['total']} total) ===")
    for e in entities["items"][:8]:
        print(f"  {e['name']} ({e['entity_type']})")

if __name__ == "__main__":
    main()
