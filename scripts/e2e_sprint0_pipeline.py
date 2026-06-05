#!/usr/bin/env python3
"""Sprint 0 E2E Validation — Full 11-step Pipeline with Real Moka AI.

Validates F-44~F-50 integration by running one realistic event through
the complete pipeline and printing results for each step.

Usage:
    cd . && python scripts/e2e_sprint0_pipeline.py

Prerequisites:
    - .env with MOKA_AI key configured
    - SQLite DB initialized (alembic upgrade head)
"""

import asyncio
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# ── Test Event: A realistic meeting record ──

TEST_EVENT_RAW = """今天下午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""


async def run_e2e_validation():
    """Run full pipeline E2E with real LLM."""
    from uuid import uuid4
    from eventlink.database import AsyncSessionLocal, init_db
    from eventlink.models.event import Event
    from eventlink.services.event_pipeline import process_event_with_short_transactions

    print("=" * 70)
    print("  Sprint 0 E2E Validation — Full 11-Step Pipeline")
    print("  Using REAL Moka AI (moka/claude-sonnet-4-6)")
    print("=" * 70)

    # 1. Initialize DB
    print("\n[Init] Initializing database...")
    await init_db()
    print("[Init] OK")

    # 2. Create test event
    print("\n[Setup] Creating test event...")
    event_id = str(uuid4())
    user_id = str(uuid4())  # Fixed test user

    async with AsyncSessionLocal() as session:
        async with session.begin():
            event = Event(
                id=event_id,
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title="投资对接会 - 盛恒资本李总/王明",
                raw_text=TEST_EVENT_RAW,
                status="pending",
            )
            session.add(event)
    print(f"[Setup] Event created: {event_id[:8]}...")
    print(f"[Setup] Raw text length: {len(TEST_EVENT_RAW)} chars")

    # 3. Run FULL pipeline
    print("\n" + "=" * 70)
    print("  ▶ RUNNING 11-STEP PIPELINE (real LLM calls)")
    print("=" * 70)

    start_time = time.monotonic()

    result = await process_event_with_short_transactions(event_id)

    elapsed = time.monotonic() - start_time

    # 4. Print results per step
    print(f"\n{'=' * 70}")
    print(f"  PIPELINE RESULT (elapsed: {elapsed:.1f}s)")
    print(f"{'=' * 70}")
    print(f"  Status:   {result.status}")
    print(f"  Error:    {result.error or 'None'}")
    print(f"  Success:  {result.success}")

    if result.entities:
        print(f"\n  ── Step 3: Entity Extraction ({len(result.entities)} entities) ──")
        for i, entity in enumerate(result.entities):
            print(f"    [{i+1}] {entity.name} ({entity.entity_type}) | "
                  f"conf={entity.confidence:.2f}")

    if result.todos:
        print(f"\n  ── Step 4+5: Todo Generation + Promise Enrichment ({len(result.todos)} todos) ──")
        for i, todo in enumerate(result.todos):
            atype = todo.action_type or "(none)"
            confirm = todo.confirmation_status or "(none)"
            evidence = (todo.evidence_quote or "")[:40]
            print(f"    [{i+1}] [{todo.todo_type}] {todo.title[:50]}")
            print(f"         action_type={atype} | confirm={confirm}")
            if evidence:
                print(f"         evidence: \"{evidence}...\"")

    # 5. Verify Step 0: InputScope was classified
    print(f"\n  ── Step 0: InputScope Classification ──")
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        evt = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one()
        print(f"    input_scope:       {evt.input_scope}")
        print(f"    input_scope_conf:  {evt.input_scope_confidence}")

    # 6. Verify Step 8: RelationshipBriefs were created/updated
    print(f"\n  ── Step 8: Relationship Brief Update ──")
    try:
        from eventlink.models.relationship_brief import RelationshipBrief
        briefs = (await session.execute(
            select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
        )).scalars().all()
        if briefs:
            for brief in briefs:
                stage = brief.relationship_stage
                score = (brief.brief_data or {}).get("strength_score", "N/A")
                modules_updated = len(brief.brief_data or {}) if brief.brief_data else 0
                print(f"    person_entity={brief.person_entity_id[:8] if brief.person_entity_id else '?'}...")
                print(f"    stage={stage} | strength={score} | data_modules={modules_updated}")
        else:
            print("    No briefs created (may need person entities)")
    except Exception as ex:
        print(f"    Brief check error: {ex}")

    # 7. Summary validation
    print(f"\n{'=' * 70}")
    print("  VALIDATION CHECKLIST")
    print(f"{'=' * 70}")

    checks = [
        ("Pipeline completed", result.status == "completed"),
        ("Entities extracted", len(result.entities) > 0),
        ("Todos generated", len(result.todos) > 0),
        ("InputScope classified", evt.input_scope is not None),
        ("Todos have action_type", any(t.action_type for t in result.todos)),
        ("No errors", result.error is None),
        ("Reasonable time", elapsed < 120),  # Should complete within 2min
    ]

    all_pass = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        symbol = "OK" if passed else "XX"
        if not passed:
            all_pass = False
        print(f"  [{symbol}] {name}: {status}")

    print(f"\n  Overall: {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
    print(f"  Total time: {elapsed:.1f}s | Entities: {len(result.entities)} | Todos: {len(result.todos)}")

    return all_pass


if __name__ == "__main__":
    try:
        ok = asyncio.run(run_e2e_validation())
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\n[E2E] Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[E2E] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
