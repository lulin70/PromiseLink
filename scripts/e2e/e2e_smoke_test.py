#!/usr/bin/env python3
"""PromiseLink E2E Smoke Test — validates core user journey."""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8002/api/v1"
USER_ID = "e2e-test-user-001"

def api(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def main():
    results = []

    # 1. Health check
    status, data = api("GET", "/health")
    ok = status == 200 and data.get("status") == "healthy"
    results.append(("Health Check", ok, f"status={status}"))
    if not ok:
        print("FAIL: Service not healthy, aborting")
        sys.exit(1)

    # 2. Login
    status, data = api("POST", "/auth/login", {"user_id": USER_ID, "poc_secret": "promiselink2026"})
    ok = status == 200 and "access_token" in data
    token = data.get("access_token", "") if ok else ""
    results.append(("Login", ok, f"status={status}"))
    if not ok:
        print(f"FAIL: Login failed: {data}")
        sys.exit(1)

    # 3. Create event (core user journey step 1)
    status, data = api("POST", "/events", {
        "event_type": "meeting",
        "raw_text": "今天和张总见面，讨论了新项目合作。张总关心项目进度，我承诺下周三前提交方案。张总提到他们公司正在寻找AI解决方案供应商。",
        "source": "manual"
    }, token)
    ok = status in (200, 201) and "id" in data
    event_id = data.get("id", "") if ok else ""
    results.append(("Create Event", ok, f"status={status}, event_id={event_id}"))

    # 4. Wait for pipeline to process (LLM calls take time)
    print("Waiting 45s for pipeline processing...")
    time.sleep(45)

    # 5. Check entities extracted
    status, data = api("GET", "/entities", token=token)
    entities = data if isinstance(data, list) else data.get("items", data.get("entities", []))
    ok = status == 200 and len(entities) > 0
    results.append(("Entities Extracted", ok, f"status={status}, count={len(entities)}"))

    # 6. Check todos generated
    status, data = api("GET", "/todos", token=token)
    todos = data if isinstance(data, list) else data.get("items", data.get("todos", []))
    ok = status == 200 and len(todos) > 0
    results.append(("Todos Generated", ok, f"status={status}, count={len(todos)}"))

    # 7. Check associations
    status, data = api("GET", "/associations", token=token)
    assocs = data if isinstance(data, list) else data.get("items", data.get("associations", []))
    ok = status == 200
    results.append(("Associations API", ok, f"status={status}, count={len(assocs)}"))

    # 8. Dashboard day view
    status, data = api("GET", "/dashboard/day-view", token=token)
    ok = status == 200
    results.append(("Dashboard Day View", ok, f"status={status}"))

    # 9. Export data
    status, data = api("GET", f"/export/{USER_ID}", token=token)
    ok = status == 200 and data.get("export_version") == "1.0"
    results.append(("Data Export", ok, f"status={status}, events={len(data.get('events',[]))}, entities={len(data.get('entities',[]))}, todos={len(data.get('todos',[]))}"))

    # 10. File upload (txt)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    txt_content = "会议纪要：和李总讨论了Q3销售策略，李总希望我们提供定制化方案。"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="meeting.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"{txt_content}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="event_type"\r\n\r\n'
        f"meeting\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    url = f"{BASE}/events/upload"
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status = e.code
        data = json.loads(e.read())
    ok = status in (200, 201) and "id" in data
    results.append(("File Upload (txt)", ok, f"status={status}"))

    # Print results
    print("\n" + "=" * 60)
    print("PromiseLink E2E Smoke Test Results")
    print("=" * 60)
    passed = 0
    for name, ok, detail in results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {name}: {detail}")
        if ok:
            passed += 1
    print(f"\n{passed}/{len(results)} tests passed")
    print("=" * 60)

    sys.exit(0 if passed == len(results) else 1)

if __name__ == "__main__":
    main()
