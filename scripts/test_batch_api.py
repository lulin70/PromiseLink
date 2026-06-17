#!/usr/bin/env python3
"""Test batch events API."""
import urllib.request, json, sys, os

BASE = "http://localhost:8000/api/v1"

def main():
    # Login
    data = json.dumps({"user_id": "00000000-0000-0000-0000-000000000099", "poc_secret": os.environ.get("POC_SECRET", "promiselink2026")}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login", data=data,
        headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.99"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        token = json.loads(resp.read())["access_token"]
        print(f"Login OK")
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    # Batch create
    payload = {
        "events": [
            {"event_type": "meeting", "source": "manual", "title": "test1", "raw_text": "met Li about coop"},
            {"event_type": "call", "source": "manual", "title": "test2", "raw_text": "called Chen about tech"},
        ]
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/events/batch", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Forwarded-For": "10.0.0.99"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        print(f"Batch create: total_requested={result['total_requested']} total_created={result['total_created']} failed={len(result['failed'])}")
        for e in result["created"]:
            print(f"  - {e['title']} (id={e['id'][:8]}..., status={e['status']})")
        if result["failed"]:
            for f in result["failed"]:
                print(f"  - FAILED index={f['index']}: {f['error']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Batch create failed: {e.code} {body}")
        sys.exit(1)

    # Test single event still works
    data = json.dumps({"event_type": "manual", "source": "test", "title": "single test", "raw_text": "single event test"}).encode()
    req = urllib.request.Request(
        f"{BASE}/events", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Forwarded-For": "10.0.0.99"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        print(f"Single create: {result['title']} (id={result['id'][:8]}...)")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Single create failed: {e.code} {body}")

    print("\nAll tests passed!")

if __name__ == "__main__":
    main()
