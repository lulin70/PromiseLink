"""Debug script to check why brief basic_info is empty."""
import asyncio
from eventlink.database import AsyncSessionLocal, init_db
from sqlalchemy import select
from eventlink.models.entity import Entity
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.services.relationship_brief_service import RelationshipBriefService

async def main():
    await init_db()
    async with AsyncSessionLocal() as session:
        # Get first entity
        r = await session.execute(select(Entity).where(Entity.name == "李总"))
        entity = r.scalar_one()
        print(f"Entity: name={entity.name}, id={entity.id}")

        # Get existing brief
        r2 = await session.execute(
            select(RelationshipBrief).where(
                RelationshipBrief.person_entity_id == str(entity.id)
            )
        )
        brief = r2.scalar_one_or_none()
        if brief:
            data = brief.brief_data or {}
            bi = data.get("basic_info", {})
            print(f"Before update: basic_info={bi}")
            print(f"Before update: all keys={list(data.keys())}")

            # Now manually update
            svc = RelationshipBriefService(session=session, llm_client=None)
            bi_new = svc._build_basic_info(entity)
            print(f"_build_basic_info returns: {bi_new}")

            # Apply — force SQLAlchemy to see the change
            data["basic_info"] = bi_new
            brief.brief_data = data
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(brief, "brief_data")
            await session.commit()

            # Re-read
            await session.refresh(brief)
            bi_after = (brief.brief_data or {}).get("basic_info", {})
            print(f"After update: basic_info={bi_after}")
        else:
            print("No brief found")

asyncio.run(main())
