"""Entity cleanup service — centralized data deletion logic.

Moves batch delete operations out of the API layer into a proper service.
Uses ORM delete queries instead of raw ``__table__.delete()`` calls.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo

logger = get_logger("promiselink.services.entity_cleanup")


async def delete_entity_cascade(
    session: AsyncSession,
    entity_id: str,
    user_id: str,
) -> None:
    """Delete an entity and all its related associations and todos.

    Uses proper ORM delete queries with user_id scoping for safety.

    Args:
        session: Database session.
        entity_id: The ID of the entity to delete.
        user_id: The owner's user ID (safety filter).
    """
    # Delete related associations (source or target)
    await session.execute(
        delete(Association).where(
            Association.user_id == user_id,
            (
                (Association.source_entity_id == entity_id)
                | (Association.target_entity_id == entity_id)
            ),
        )
    )

    # Delete related todos
    await session.execute(
        delete(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
        )
    )

    # Delete the entity itself
    await session.execute(
        delete(Entity).where(
            Entity.id == entity_id,
            Entity.user_id == user_id,
        )
    )

    logger.info("entity_cascade_deleted", entity_id=entity_id, user_id=user_id)


async def delete_event_cascade(
    session: AsyncSession,
    event_id: str,
    user_id: str,
) -> dict:
    """Delete all data related to an event (associations, todos, entities).

    Uses proper ORM delete queries with user_id scoping for safety.

    Args:
        session: Database session.
        event_id: The ID of the event whose data should be deleted.
        user_id: The owner's user ID (safety filter).

    Returns:
        Dict with counts of deleted items.
    """
    # Find entities sourced from this event
    entity_result = await session.execute(
        select(Entity.id).where(
            Entity.source_event_id == event_id,
            Entity.user_id == user_id,
        )
    )
    entity_ids = [str(eid) for eid in entity_result.scalars().all()]

    deleted = {"associations": 0, "todos": 0, "entities": 0}

    if entity_ids:
        # Delete associations involving these entities
        assoc_result = await session.execute(
            delete(Association).where(
                Association.user_id == user_id,
                (
                    Association.source_entity_id.in_(entity_ids)
                    | Association.target_entity_id.in_(entity_ids)
                ),
            )
        )
        deleted["associations"] = assoc_result.rowcount  # type: ignore[attr-defined]

        # Delete todos referencing these entities
        todo_entity_result = await session.execute(
            delete(Todo).where(
                Todo.user_id == user_id,
                Todo.related_entity_id.in_(entity_ids),
            )
        )
        deleted["todos"] += todo_entity_result.rowcount  # type: ignore[attr-defined]

        # Delete entities
        entity_del_result = await session.execute(
            delete(Entity).where(
                Entity.user_id == user_id,
                Entity.id.in_(entity_ids),
            )
        )
        deleted["entities"] = entity_del_result.rowcount  # type: ignore[attr-defined]

    # Always delete todos from this event (even if no entities)
    todo_event_result = await session.execute(
        delete(Todo).where(
            Todo.user_id == user_id,
            Todo.source_event_id == event_id,
        )
    )
    deleted["todos"] += todo_event_result.rowcount  # type: ignore[attr-defined]

    logger.info(
        "event_cascade_deleted",
        event_id=event_id,
        user_id=user_id,
        **deleted,
    )

    return deleted
