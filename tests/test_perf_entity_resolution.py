"""Performance benchmark: Entity resolution + API endpoints with large entity counts.

Tests:
1. Entity resolution speed (cold/warm) at 1000/2000/5000 entities
2. API endpoint response times at 1000 entities
3. Pipeline Step02 extraction time with large entity counts

Usage: python -m tests.perf_entity_resolution
       python -m tests.perf_entity_resolution --api   # Also test API endpoints
"""

import argparse
import asyncio
import time
import uuid
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import select, func
from promiselink.database import AsyncSessionLocal, init_db
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.entity_resolution import EntityResolutionEngine


# ── Chinese name data for realistic seeding ──

SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
]
GIVEN_NAMES = [
    "伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "洋",
    "勇", "艳", "杰", "军", "娟", "涛", "明", "超", "秀兰", "霞",
    "鑫", "浩", "宇", "婷", "欣", "睿", "博", "瑶", "晨", "楠",
]
COMPANIES = [
    "华为", "腾讯", "阿里巴巴", "字节跳动", "百度", "京东", "美团",
    "小米", "网易", "滴滴", "快手", "拼多多", "携程", "蚂蚁", "微众",
]
CITIES = ["北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "武汉"]


def _make_canonical_name(name: str) -> str:
    """Simple canonical name: lowercase, strip whitespace."""
    return name.strip().lower()


async def seed_entities(user_id: str, count: int) -> float:
    """Create N test entities with Chinese names. Returns seed time in seconds."""
    start = time.monotonic()

    # Batch insert for performance
    batch_size = 200
    created = 0
    while created < count:
        batch_count = min(batch_size, count - created)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for i in range(batch_count):
                    idx = created + i
                    surname = SURNAMES[idx % len(SURNAMES)]
                    given = GIVEN_NAMES[(idx // len(SURNAMES)) % len(GIVEN_NAMES)]
                    name = f"{surname}{given}"
                    # Add unique suffix for names that would collide
                    if idx >= len(SURNAMES) * len(GIVEN_NAMES):
                        name = f"{surname}{given}{idx // (len(SURNAMES) * len(GIVEN_NAMES)) + 1}"
                    company = COMPANIES[idx % len(COMPANIES)]
                    city = CITIES[idx % len(CITIES)]

                    # Create a parent event for FK constraint
                    event_id = str(uuid.uuid4())
                    event = Event(
                        id=event_id,
                        user_id=user_id,
                        event_type="manual",
                        source="perf_test",
                        title=f"测试事件{idx}",
                        raw_text=f"和{name}讨论{company}项目",
                        status="completed",
                    )
                    session.add(event)
                    # Flush to ensure event exists before entity references it
                    await session.flush()

                    entity = Entity(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        entity_type="person",
                        name=name,
                        canonical_name=_make_canonical_name(name),
                        status="confirmed",
                        confidence=0.9,
                        source_event_id=event_id,
                        properties={
                            "basic": {
                                "company": f"{company}{idx // len(COMPANIES) + 1}部",
                                "title": "总监" if idx % 5 == 0 else "经理",
                                "city": city,
                            },
                            "concern": [
                                {"category": "项目进度", "detail": f"关注第{idx % 10 + 1}季度交付"}
                            ] if idx % 3 == 0 else [],
                        },
                    )
                    session.add(entity)
            await session.commit()
        created += batch_count

    seed_time = time.monotonic() - start
    return seed_time


async def benchmark_resolution(user_id: str, entity_count: int) -> dict:
    """Benchmark entity resolution with given entity count."""
    print(f"\n--- Entity Resolution: {entity_count} entities ---")

    # Seed entities
    seed_time = await seed_entities(user_id, entity_count)
    print(f"  Seed time: {seed_time:.2f}s ({entity_count/seed_time:.0f} entities/s)")

    # Verify count
    async with AsyncSessionLocal() as session:
        count_result = await session.execute(
            select(func.count()).select_from(Entity).where(Entity.user_id == user_id)
        )
        actual_count = count_result.scalar()
        print(f"  Verified: {actual_count} entities in DB")

    # Test names for resolution (mix of matches and non-matches)
    test_names = [
        {"name": "王伟", "company": "华为1部", "entity_type": "person"},
        {"name": "李芳", "company": "腾讯2部", "entity_type": "person"},
        {"name": "张娜", "company": "新公司", "entity_type": "person"},  # No match
        {"name": "刘秀英", "company": "字节跳动", "entity_type": "person"},
        {"name": "陈敏", "company": "百度", "entity_type": "person"},
    ]

    results = {"entity_count": entity_count, "seed_time": seed_time}

    async with AsyncSessionLocal() as session:
        # Cold resolve (first call, index needs loading)
        engine_cold = EntityResolutionEngine(session)
        start = time.monotonic()
        for data in test_names:
            await engine_cold.resolve(data, user_id)
        cold_time = time.monotonic() - start
        cold_per = cold_time / len(test_names) * 1000
        print(f"  Cold resolve ({len(test_names)} queries): {cold_time:.3f}s ({cold_per:.1f}ms/entity)")
        results["cold_per_entity_ms"] = cold_per

        # Warm resolve (index already loaded)
        engine_warm = EntityResolutionEngine(session)
        await engine_warm._ensure_index(user_id)
        start = time.monotonic()
        for data in test_names:
            await engine_warm.resolve(data, user_id)
        warm_time = time.monotonic() - start
        warm_per = warm_time / len(test_names) * 1000
        print(f"  Warm resolve ({len(test_names)} queries): {warm_time:.3f}s ({warm_per:.1f}ms/entity)")
        results["warm_per_entity_ms"] = warm_per

        # Bulk resolve: 50 entities at once (simulates pipeline batch)
        bulk_names = [
            {"name": f"{SURNAMES[i % len(SURNAMES)]}{GIVEN_NAMES[i % len(GIVEN_NAMES)]}",
             "company": f"测试公司{i}", "entity_type": "person"}
            for i in range(50)
        ]
        engine_bulk = EntityResolutionEngine(session)
        await engine_bulk._ensure_index(user_id)
        start = time.monotonic()
        for data in bulk_names:
            await engine_bulk.resolve(data, user_id)
        bulk_time = time.monotonic() - start
        bulk_per = bulk_time / len(bulk_names) * 1000
        print(f"  Bulk resolve (50 queries): {bulk_time:.3f}s ({bulk_per:.1f}ms/entity)")
        results["bulk_per_entity_ms"] = bulk_per

    return results


async def benchmark_api(user_id: str) -> dict:
    """Benchmark API endpoint response times with existing entities."""
    import requests

    BASE = "http://localhost:8002/api/v1"
    SECRET = "promiselink2024"

    print(f"\n--- API Performance: user={user_id} ---")

    # Login
    r = requests.post(f"{BASE}/auth/login", json={"user_id": user_id, "poc_secret": SECRET})
    if r.status_code != 200:
        print(f"  Login failed: {r.status_code}, skipping API tests")
        return {}
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    results = {}
    endpoints = [
        ("GET /entities", f"{BASE}/entities?limit=100"),
        ("GET /entities (all)", f"{BASE}/entities?limit=2000"),
        ("GET /dashboard/relationship-health", f"{BASE}/dashboard/relationship-health"),
        ("GET /dashboard/care-reminders", f"{BASE}/dashboard/care-reminders"),
        ("GET /entities/stage-map", f"{BASE}/entities/stage-map"),
        ("GET /dashboard/day-view", f"{BASE}/dashboard/day-view"),
        ("GET /dashboard/morning-brief", f"{BASE}/dashboard/morning-brief"),
    ]

    for name, url in endpoints:
        times = []
        for _ in range(3):
            start = time.monotonic()
            r = requests.get(url, headers=h)
            elapsed = time.monotonic() - start
            times.append(elapsed)
        avg = sum(times) / len(times)
        status = "OK" if r.status_code == 200 else f"HTTP {r.status_code}"
        print(f"  {name}: {avg*1000:.0f}ms avg ({status})")
        results[name] = {"avg_ms": avg * 1000, "status": status}

    return results


async def cleanup(user_id: str):
    """Delete all test data for a user."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            from promiselink.models.association import Association
            from promiselink.models.todo import Todo

            await session.execute(
                Todo.__table__.delete().where(Todo.user_id == user_id)
            )
            await session.execute(
                Association.__table__.delete().where(Association.user_id == user_id)
            )
            result = await session.execute(
                select(Entity.id).where(Entity.user_id == user_id)
            )
            ids = [str(r[0]) for r in result.all()]
            if ids:
                # Delete in batches to avoid SQL variable limit
                batch = 500
                for i in range(0, len(ids), batch):
                    await session.execute(
                        Entity.__table__.delete().where(
                            Entity.id.in_(ids[i:i + batch])
                        )
                    )
            # Delete events
            await session.execute(
                Event.__table__.delete().where(Event.user_id == user_id)
            )
    print(f"  Cleaned up {len(ids)} entities + events for {user_id}")


async def main():
    parser = argparse.ArgumentParser(description="PromiseLink Performance Benchmark")
    parser.add_argument("--api", action="store_true", help="Also run API endpoint benchmarks")
    parser.add_argument("--counts", type=str, default="1000,2000,5000",
                        help="Entity counts to test (comma-separated)")
    args = parser.parse_args()

    counts = [int(c) for c in args.counts.split(",")]
    await init_db()

    resolution_results = []
    for count in counts:
        user_id = f"perf-test-{count}"
        try:
            result = await benchmark_resolution(user_id, count)
            resolution_results.append(result)
        finally:
            await cleanup(user_id)

    # API benchmarks (only with 1000 entities)
    api_results = {}
    if args.api:
        api_user = "perf-api-1000"
        try:
            await seed_entities(api_user, 1000)
            api_results = await benchmark_api(api_user)
        finally:
            await cleanup(api_user)

    # ── Summary Report ──
    print("\n" + "=" * 80)
    print("PROMISELINK PERFORMANCE BENCHMARK REPORT")
    print("=" * 80)

    print(f"\n{'Entity Resolution':^80}")
    print("-" * 80)
    print(f"{'Entities':>10} | {'Cold ms/ent':>12} | {'Warm ms/ent':>12} | {'Bulk ms/ent':>12} | {'Seed (s)':>10}")
    print("-" * 80)
    for r in resolution_results:
        print(f"{r['entity_count']:>10} | {r.get('cold_per_entity_ms', 0):>12.1f} | "
              f"{r.get('warm_per_entity_ms', 0):>12.1f} | {r.get('bulk_per_entity_ms', 0):>12.1f} | "
              f"{r['seed_time']:>10.2f}")
    print("-" * 80)

    # Performance targets
    target_1k = next((r for r in resolution_results if r["entity_count"] == 1000), None)
    if target_1k:
        warm = target_1k.get("warm_per_entity_ms", 999)
        bulk = target_1k.get("bulk_per_entity_ms", 999)
        print(f"\n  Target: Warm resolve < 50ms/entity at 1000 entities")
        print(f"  Result: {warm:.1f}ms/entity → {'PASS' if warm < 50 else 'FAIL'}")
        print(f"  Target: Bulk resolve < 30ms/entity at 1000 entities")
        print(f"  Result: {bulk:.1f}ms/entity → {'PASS' if bulk < 30 else 'FAIL'}")

    if api_results:
        print(f"\n{'API Endpoints (1000 entities)':^80}")
        print("-" * 80)
        for name, data in api_results.items():
            print(f"  {name:<45} {data['avg_ms']:>8.0f}ms  {data['status']}")

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
