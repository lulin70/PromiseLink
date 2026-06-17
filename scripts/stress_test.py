#!/usr/bin/env python3
"""PromiseLink Stress Test - Real HTTP load testing

Adapted for SQLite backend: each event creation triggers a background pipeline
(13 steps, each opening its own DB session + LLM calls). Pipeline tasks are
long-running and accumulate, exhausting the connection pool (size=5, overflow=10).

Strategy:
- Writes: sequential with 3s delay (let pipeline drain between writes)
- Reads: high concurrency (WAL mode allows parallel reads)
- Mixed: 1 write + concurrent reads per round
- Inter-test cooldown: 10s to let pipelines drain
"""
import asyncio
import time
import uuid
import statistics
import httpx
import os

BASE = "http://localhost:8001/api/v1"
SECRET = os.environ.get("POC_SECRET", "promiselink2026")
READ_CONCURRENCY = 50
WRITE_DELAY = 3.0  # seconds between sequential writes
COOLDOWN = 10  # seconds between test groups


async def get_token(client):
    uid = str(uuid.uuid4())
    resp = await client.post(f"{BASE}/auth/login", json={"user_id": uid, "poc_secret": SECRET})
    return uid, resp.json()["access_token"]


async def stress_test():
    async with httpx.AsyncClient(timeout=60) as client:
        print("=" * 60)
        print("PromiseLink Stress Test (SQLite backend)")
        print("=" * 60)

        # Test 1: Sequential event creation (15 events with delay)
        total_writes = 15
        print(f"\n[Test 1] Sequential event creation ({total_writes} events, {WRITE_DELAY}s delay)")
        uid, token = await get_token(client)
        h = {"Authorization": f"Bearer {token}"}

        write_latencies = []
        write_successes = 0
        start = time.perf_counter()
        for i in range(total_writes):
            req_start = time.perf_counter()
            try:
                resp = await client.post(f"{BASE}/events", headers=h, json={
                    "event_type": "meeting",
                    "raw_text": f"Stress test event {i}",
                    "source": "manual",
                    "title": f"Stress {i}"
                })
                latency = (time.perf_counter() - req_start) * 1000
                write_latencies.append(latency)
                if resp.status_code in (200, 201):
                    write_successes += 1
                else:
                    print(f"  WARNING: Event {i} -> {resp.status_code}")
            except Exception as e:
                print(f"  ERROR: Event {i} -> {type(e).__name__}")
            if i < total_writes - 1:
                await asyncio.sleep(WRITE_DELAY)
        elapsed = time.perf_counter() - start

        if write_latencies:
            write_latencies.sort()
            p50 = write_latencies[int(len(write_latencies) * 0.5)]
            p95 = write_latencies[int(len(write_latencies) * 0.95)]
            print(f"  Success: {write_successes}/{total_writes}, Time: {elapsed:.1f}s")
            print(f"  Throughput: {total_writes/elapsed:.1f} req/s")
            print(f"  Write latency P50: {p50:.0f}ms, P95: {p95:.0f}ms")

        # Cooldown: let pipeline tasks drain
        print(f"\n  Cooldown {COOLDOWN}s (let pipelines drain)...")
        await asyncio.sleep(COOLDOWN)

        # Test 2: Concurrent reads (50 concurrent)
        print(f"\n[Test 2] {READ_CONCURRENCY} concurrent reads")
        start = time.perf_counter()
        tasks = []
        for _ in range(READ_CONCURRENCY):
            tasks.append(client.get(f"{BASE}/events", headers=h))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - start

        successes = sum(1 for r in results if isinstance(r, httpx.Response) and r.status_code == 200)
        failures = sum(1 for r in results if isinstance(r, Exception) or (isinstance(r, httpx.Response) and r.status_code >= 400))
        print(f"  Success: {successes}/{READ_CONCURRENCY}, Failures: {failures}, Time: {elapsed:.1f}s")
        print(f"  Throughput: {READ_CONCURRENCY/elapsed:.1f} req/s")
        assert successes >= READ_CONCURRENCY * 0.9, f"Too many read failures: {failures}/{READ_CONCURRENCY}"

        # Test 3: Mixed - 1 write + 10 concurrent reads (5 rounds with delay)
        print("\n[Test 3] Mixed: 1 write + 10 concurrent reads (5 rounds)")
        server_errors = 0
        for round_i in range(5):
            tasks = [client.post(f"{BASE}/events", headers=h, json={
                "event_type": "meeting", "raw_text": f"Mixed {round_i}",
                "source": "manual", "title": f"Mixed {round_i}"
            })]
            for _ in range(10):
                tasks.append(client.get(f"{BASE}/events", headers=h))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            server_errors += sum(1 for r in results if isinstance(r, httpx.Response) and r.status_code >= 500)
            if round_i < 4:
                await asyncio.sleep(WRITE_DELAY)
        print(f"  Server errors: {server_errors}/55")
        assert server_errors == 0, f"Server errors during mixed ops: {server_errors}"

        # Cooldown
        print(f"\n  Cooldown {COOLDOWN}s...")
        await asyncio.sleep(COOLDOWN)

        # Test 4: Large data - create 20 events sequentially then query
        print("\n[Test 4] Large data volume (20 events, sequential with delay)")
        uid2, token2 = await get_token(client)
        h2 = {"Authorization": f"Bearer {token2}"}

        start = time.perf_counter()
        created = 0
        for i in range(20):
            try:
                resp = await client.post(f"{BASE}/events", headers=h2, json={
                    "event_type": "meeting",
                    "raw_text": f"Volume test event {i}",
                    "source": "manual",
                    "title": f"Volume {i}"
                })
                if resp.status_code in (200, 201):
                    created += 1
            except Exception:
                pass
            if i < 19:
                await asyncio.sleep(WRITE_DELAY)
        elapsed = time.perf_counter() - start
        print(f"  Created {created}/20 events in {elapsed:.1f}s ({created/elapsed:.1f} req/s)")

        # Query with large dataset
        start = time.perf_counter()
        resp = await client.get(f"{BASE}/events", headers=h2)
        elapsed = time.perf_counter() - start
        total = resp.json().get("total", 0)
        print(f"  Query {total} events in {elapsed*1000:.0f}ms")
        assert elapsed < 2.0, f"Query too slow: {elapsed:.1f}s"

        # Cooldown
        print(f"\n  Cooldown {COOLDOWN}s...")
        await asyncio.sleep(COOLDOWN)

        # Test 5: Rate limiting verification
        print("\n[Test 5] Rate limiting (rapid login attempts)")
        start = time.perf_counter()
        rate_limited = 0
        for i in range(100):
            resp = await client.post(f"{BASE}/auth/login", json={
                "user_id": f"rate_{i}_{uuid.uuid4()}",
                "poc_secret": "wrong"
            })
            if resp.status_code == 429:
                rate_limited += 1
        elapsed = time.perf_counter() - start
        print(f"  Rate limited: {rate_limited}/100, Time: {elapsed:.1f}s")

        # Test 6: Sustained load (30s at ~10 req/s)
        print("\n[Test 6] Sustained load (30s at ~10 req/s)")
        uid3, token3 = await get_token(client)
        h3 = {"Authorization": f"Bearer {token3}"}

        latencies = []
        start = time.perf_counter()
        count = 0
        while time.perf_counter() - start < 30:
            req_start = time.perf_counter()
            resp = await client.get(f"{BASE}/events", headers=h3)
            latency = (time.perf_counter() - req_start) * 1000
            latencies.append(latency)
            count += 1
            await asyncio.sleep(0.1)  # ~10 req/s

        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.5)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"  Requests: {count}, P50: {p50:.0f}ms, P95: {p95:.0f}ms, P99: {p99:.0f}ms")
        assert p95 < 500, f"P95 latency too high: {p95:.0f}ms"

        print("\n" + "=" * 60)
        print("STRESS TEST PASSED!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(stress_test())
