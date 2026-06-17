#!/usr/bin/env python3
"""PromiseLink Basic Security Check.

Verifies key security controls are in place.
"""
import asyncio
import uuid
import httpx
import os

BASE_URL = "http://localhost:8001/api/v1"
POC_SECRET = os.environ.get("POC_SECRET", "promiselink2026")

async def main():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        checks = []

        # 1. Unauthenticated access should be rejected
        resp = await client.get(f"{BASE_URL}/events")
        checks.append(("Unauth access rejected", resp.status_code == 401, f"got {resp.status_code}"))

        # 2. Wrong poc_secret should be rejected
        resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": "attacker", "poc_secret": "wrong_secret"})
        checks.append(("Wrong secret rejected", resp.status_code == 401, f"got {resp.status_code}"))

        # 3. Empty poc_secret should be rejected
        resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": "attacker", "poc_secret": ""})
        checks.append(("Empty secret rejected", resp.status_code in (401, 403), f"got {resp.status_code}"))

        # 4. Cross-user data isolation
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())
        token1_resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": user_a_id, "poc_secret": POC_SECRET})
        token1 = token1_resp.json()["access_token"]
        await asyncio.sleep(0.5)
        token2_resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": user_b_id, "poc_secret": POC_SECRET})
        token2 = token2_resp.json()["access_token"]

        # User A creates an event
        await asyncio.sleep(1)
        resp = await client.post(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token1}"}, json={"event_type": "meeting", "raw_text": "User A secret event", "source": "manual", "title": "Secret"})
        event_id = resp.json().get("id")

        # User B should not see User A's events
        await asyncio.sleep(1)
        resp = await client.get(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token2}"})
        user_b_events = resp.json().get("items", [])
        user_b_has_a_event = any(e.get("id") == event_id for e in user_b_events)
        checks.append(("Cross-user isolation", not user_b_has_a_event, f"user_b sees {len(user_b_events)} events"))

        # 5. Rate limiting exists on authenticated endpoints
        # Test by making rapid requests to /events with same user token
        # Authenticated limit is 60/min, so 70 rapid requests should trigger 429
        rate_limited = False
        for i in range(70):
            resp = await client.get(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token1}"})
            if resp.status_code == 429:
                rate_limited = True
                break
        checks.append(("Rate limiting active", rate_limited, f"{'triggered' if rate_limited else 'not triggered in 70 requests'}"))

        # Wait for rate limit to reset before continuing
        await asyncio.sleep(65)

        # 6. SQL injection attempt
        # Re-login to get a fresh token after rate limit
        token1_resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": user_a_id, "poc_secret": POC_SECRET})
        token1 = token1_resp.json()["access_token"]
        await asyncio.sleep(1)
        resp = await client.get(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token1}"}, params={"search": "'; DROP TABLE events; --"})
        checks.append(("SQL injection safe", resp.status_code == 200, f"got {resp.status_code}"))

        # 7. XSS in input
        await asyncio.sleep(1.5)
        resp = await client.post(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token1}"}, json={"event_type": "meeting", "raw_text": "<script>alert('xss')</script>", "source": "manual", "title": "<img onerror=alert(1) src=x>"})
        checks.append(("XSS input handled", resp.status_code in (200, 201), f"got {resp.status_code}"))

        # 8. Invalid JWT rejected
        resp = await client.get(f"{BASE_URL}/events", headers={"Authorization": "Bearer invalid.jwt.token"})
        checks.append(("Invalid JWT rejected", resp.status_code == 401, f"got {resp.status_code}"))

        # Print results
        print(f"{'Check':<30} {'Result':>8} {'Detail':<40}")
        print("-" * 80)
        all_pass = True
        for name, passed, detail in checks:
            all_pass = all_pass and passed
            print(f"{name:<30} {'✅ PASS' if passed else '❌ FAIL':>8} {detail:<40}")

        print(f"\nOverall: {'PASS ✅' if all_pass else 'FAIL ❌'}")
        return all_pass

if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
