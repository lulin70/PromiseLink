#!/usr/bin/env python3
"""Debug script to diagnose why brief basic_info is empty for event 1 entities."""

import asyncio
import sys
import logging
from pathlib import Path

# Suppress all logging
logging.basicConfig(level=logging.CRITICAL)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Redirect structlog to stderr
import structlog as _structlog
_structlog.configure(
    processors=[_structlog.stdlib.add_log_level, _structlog.dev.ConsoleRenderer()],
    wrapper_class=_structlog.stdlib.BoundLogger,
    logger_factory=_structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=False,
)

from uuid import uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from eventlink.database import AsyncSessionLocal, init_db
from eventlink.models.event import Event
from eventlink.models.entity import Entity
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.services.event_pipeline import process_event_with_short_transactions

TZ_CN = timezone(timedelta(hours=8))

EVENT_TEXT = """今天上午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""


async def main():
    await init_db()
    print("=== DB initialized ===\n")

    # Create event
    event_id = str(uuid4())
    user_id = "debug-user"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            event_ts = datetime.now(TZ_CN).replace(hour=10, minute=30, second=0, microsecond=0)
            event = Event(
                id=event_id,
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title="投资对接会",
                raw_text=EVENT_TEXT,
                status="pending",
                timestamp=event_ts,
            )
            session.add(event)
    print(f"Event created: {event_id[:8]}...\n")

    # Run pipeline
    print("Running pipeline...")
    result = await process_event_with_short_transactions(event_id)
    print(f"Pipeline status: {result.status}")
    print(f"Entities: {len(result.entities)}")
    print(f"Todos: {len(result.todos)}")
    if result.error:
        print(f"Error: {result.error}")
    print()

    # Check entities in DB
    print("=== Entities in DB ===")
    async with AsyncSessionLocal() as session:
        ent_result = await session.execute(
            select(Entity).where(Entity.user_id == user_id)
        )
        entities = ent_result.scalars().all()
        for e in entities:
            props = e.properties or {}
            basic = props.get("basic", {})
            print(f"  Entity: id={str(e.id)[:8]} name='{e.name}' company='{basic.get('company', '')}' "
                  f"title='{basic.get('title', '')}' type={e.entity_type} status={e.status}")
    print()

    # Check briefs in DB
    print("=== Briefs in DB ===")
    async with AsyncSessionLocal() as session:
        brief_result = await session.execute(
            select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
        )
        briefs = brief_result.scalars().all()
        for b in briefs:
            data = b.brief_data or {}
            basic_info = data.get("basic_info", {})
            name = basic_info.get("name", "EMPTY")
            company = basic_info.get("company", "EMPTY")
            role = basic_info.get("role", "EMPTY")
            score = data.get("strength_score", 0)
            version = b.version
            modules = list(data.keys())
            print(f"  Brief: person_entity_id={str(b.person_entity_id)[:8]} "
                  f"name='{name}' company='{company}' role='{role}' "
                  f"score={score} version={version}")
            print(f"    modules: {modules}")
            if not basic_info.get("name"):
                print(f"    *** basic_info is EMPTY! Full basic_info: {basic_info}")
                # Try to find the entity
                ent_check = await session.execute(
                    select(Entity).where(Entity.id == str(b.person_entity_id))
                )
                ent = ent_check.scalar_one_or_none()
                if ent:
                    print(f"    *** Entity found in DB: name='{ent.name}' properties.basic={ent.properties.get('basic', {}) if ent.properties else 'None'}")
                else:
                    print(f"    *** Entity NOT found in DB!")
    print()

    # Now manually update brief using the service
    print("=== Manual brief update test ===")
    from eventlink.services.relationship_brief_service import RelationshipBriefService
    async with AsyncSessionLocal() as session:
        brief_result = await session.execute(
            select(RelationshipBrief).where(RelationshipBrief.user_id == user_id)
        )
        briefs = brief_result.scalars().all()

        for b in briefs:
            data = b.brief_data or {}
            if not data.get("basic_info", {}).get("name"):
                print(f"  Attempting manual update for brief {str(b.person_entity_id)[:8]}...")

                # Query entity
                ent_check = await session.execute(
                    select(Entity).where(Entity.id == str(b.person_entity_id))
                )
                ent = ent_check.scalar_one_or_none()
                if ent:
                    print(f"    Entity: name='{ent.name}' company='{(ent.properties or {}).get('basic', {}).get('company', '')}'")
                    # Try update
                    service = RelationshipBriefService(session=session)
                    # Re-fetch event
                    evt_check = await session.execute(
                        select(Event).where(Event.id == event_id)
                    )
                    evt = evt_check.scalar_one_or_none()

                    # Re-fetch todos
                    from eventlink.models.todo import Todo
                    todo_check = await session.execute(
                        select(Todo).where(Todo.source_event_id == event_id)
                    )
                    todos = list(todo_check.scalars().all())

                    # Re-fetch entities
                    ent_all = await session.execute(
                        select(Entity).where(Entity.source_event_id == event_id)
                    )
                    all_ents = list(ent_all.scalars().all())

                    update_result = await service.update_brief_from_event(
                        user_id=user_id,
                        person_entity_id=str(b.person_entity_id),
                        event=evt,
                        entities=all_ents,
                        todos=todos,
                    )
                    print(f"    Update result: is_new={update_result.is_new} modules={update_result.modules_updated}")
                    await session.commit()

                    # Check again
                    await session.refresh(b)
                    data2 = b.brief_data or {}
                    name2 = data2.get("basic_info", {}).get("name", "STILL EMPTY")
                    print(f"    After update: name='{name2}' score={data2.get('strength_score', 0)}")
                else:
                    print(f"    Entity not found!")


if __name__ == "__main__":
    asyncio.run(main())
