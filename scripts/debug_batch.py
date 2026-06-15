#!/usr/bin/env python3
"""Debug batch API."""
import urllib.request, json, sys, os

BASE = "http://localhost:8000/api/v1"

# Login
data = json.dumps({"user_id": "debug_user_001", "poc_secret": os.environ.get("POC_SECRET", "promiselink2024")}).encode()
req = urllib.request.Request(f"{BASE}/auth/login", data=data, headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.55"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    token = json.loads(resp.read())["access_token"]
    print(f"Login OK")
except urllib.error.HTTPError as e:
    print(f"Login failed: {e.code} {e.read().decode()[:200]}")
    sys.exit(1)

# Single event
data = json.dumps({"event_type": "meeting", "source": "manual", "title": "debug test", "raw_text": "test"}).encode()
req = urllib.request.Request(f"{BASE}/events", data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Forwarded-For": "10.0.0.55"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    r = json.loads(resp.read())
    print(f"Single: {resp.status} id={r.get('id','?')[:8]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(f"Single error: {e.code} {body}")

# Batch event
payload = {"events": [{"event_type": "meeting", "source": "manual", "title": "batch debug", "raw_text": "batch test"}]}
data = json.dumps(payload).encode()
req = urllib.request.Request(f"{BASE}/events/batch", data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Forwarded-For": "10.0.0.55"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    r = json.loads(resp.read())
    print(f"Batch: created={r['total_created']} failed={r['failed']}")
    for e in r.get("created", []):
        print(f"  {e.get('title','?')} id={e.get('id','?')[:8]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:500]
    print(f"Batch error: {e.code} {body}")
