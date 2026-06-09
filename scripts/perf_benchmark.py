#!/usr/bin/env python3
"""EventLink API Performance Benchmark.

Tests P95 latency < 500ms for all core endpoints.
Rate limit: 60 req/min for authenticated users. We use 10 req/endpoint with delays.
"""
import asyncio
import time
import statistics
import uuid
import httpx

BASE_URL = "http://localhost:8001/api/v1"
POC_SECRET = "eventlink2024"
USER_ID = str(uuid.uuid4())

async def get_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{BASE_URL}/auth/login", json={"user_id": USER_ID, "poc_secret": POC_SECRET})
    return resp.json()["access_token"]

async def benchmark(client: httpx.AsyncClient, token: str, endpoint: str, method: str = "GET", json_data: dict = None, n: int = 10) -> list[float]:
    """Run n requests and return latencies in ms. Adds delay to avoid rate limiting."""
    latencies = []
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(n):
        start = time.perf_counter()
        if method == "GET":
            resp = await client.get(f"{BASE_URL}{endpoint}", headers=headers)
        else:
            resp = await client.post(f"{BASE_URL}{endpoint}", headers=headers, json=json_data)
        elapsed = (time.perf_counter() - start) * 1000
        if resp.status_code < 400:
            latencies.append(elapsed)
        elif resp.status_code == 429:
            # Rate limited - wait and retry this request
            await asyncio.sleep(5)
            start = time.perf_counter()
            if method == "GET":
                resp = await client.get(f"{BASE_URL}{endpoint}", headers=headers)
            else:
                resp = await client.post(f"{BASE_URL}{endpoint}", headers=headers, json=json_data)
            elapsed = (time.perf_counter() - start) * 1000
            if resp.status_code < 400:
                latencies.append(elapsed)
        # Delay between requests to stay under rate limit (60/min = 1/sec)
        await asyncio.sleep(1.2)
    return latencies

async def main():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        token = await get_token(client)

        # First create some test data
        for i in range(3):
            resp = await client.post(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token}"}, json={"event_type": "meeting", "raw_text": f"和张三讨论项目{i}", "source": "manual", "title": f"项目讨论{i}"})
            if resp.status_code == 429:
                await asyncio.sleep(5)
                await client.post(f"{BASE_URL}/events", headers={"Authorization": f"Bearer {token}"}, json={"event_type": "meeting", "raw_text": f"和张三讨论项目{i}", "source": "manual", "title": f"项目讨论{i}"})
            await asyncio.sleep(1.2)

        # Wait for rate limit window to reset
        await asyncio.sleep(5)

        endpoints = [
            ("GET", "/health", None),
            ("GET", "/events", None),
            ("GET", "/todos", None),
            ("GET", "/entities", None),
            ("GET", "/dashboard/day-view", None),
            ("POST", "/events", {"event_type": "meeting", "raw_text": "性能测试事件", "source": "manual", "title": "PerfTest"}),
        ]

        print(f"{'Endpoint':<30} {'N':>4} {'Mean':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8} {'Pass':>6}")
        print("-" * 90)

        all_pass = True
        for method, endpoint, data in endpoints:
            latencies = await benchmark(client, token, endpoint, method, data, n=10)
            if not latencies:
                print(f"{endpoint:<30} {'NO DATA':>8}")
                all_pass = False
                continue
            latencies.sort()
            mean = statistics.mean(latencies)
            p50 = latencies[int(len(latencies) * 0.5)]
            p95 = latencies[int(len(latencies) * 0.95)]
            p99 = latencies[int(len(latencies) * 0.99)]
            max_lat = max(latencies)
            passed = p95 < 500
            all_pass = all_pass and passed
            print(f"{endpoint:<30} {len(latencies):>4} {mean:>7.1f}ms {p50:>7.1f}ms {p95:>7.1f}ms {p99:>7.1f}ms {max_lat:>7.1f}ms {'✅' if passed else '❌':>6}")

            # Wait between endpoints to allow rate limit window to reset
            await asyncio.sleep(5)

        print(f"\nOverall: {'PASS ✅' if all_pass else 'FAIL ❌'}")
        return all_pass

if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
