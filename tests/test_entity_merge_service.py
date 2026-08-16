"""Unit tests for entity_merge_service — manual duplicate-customer handling.

Design: docs/design/Duplicate_Entity_Manual_Handling_2026-08-16.md §3.1.
"""

import uuid

import pytest
from sqlalchemy import select

from promiselink.core.exceptions import ConflictError, NotFoundError, ValidationError
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo
from promiselink.services.entity_merge_service import (
    confirm_entity,
    find_duplicate_groups,
    merge_entities,
)

from .conftest import create_test_event, make_user_id


async def _make_entity(
    session,
    user_id: str,
    name: str,
    *,
    status: str = "confirmed",
    company: str | None = None,
    title: str | None = None,
    aliases: list[str] | None = None,
) -> Entity:
    """Create a persisted person entity with a source event."""
    event = await create_test_event(session, user_id=user_id)
    props: dict = {}
    basic = {k: v for k, v in {"company": company, "title": title}.items() if v}
    if basic:
        props["basic"] = basic
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=aliases or [],
        properties=props,
        source_event_id=event.id,
        status=status,
        confidence=0.9,
    )
    session.add(entity)
    await session.flush()
    return entity


async def _make_todo(session, user_id: str, entity_id: str, title: str) -> Todo:
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="followup",
        title=title,
        related_entity_id=entity_id,
        status="pending",
        priority=3,
    )
    session.add(todo)
    await session.flush()
    return todo


async def _make_association(
    session,
    user_id: str,
    source_id: str,
    target_id: str,
    *,
    assoc_type: str = "co_occurrence",
    strength: float = 0.5,
) -> Association:
    assoc = Association(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        association_type=assoc_type,
        strength=strength,
        confidence=0.9,
    )
    session.add(assoc)
    await session.flush()
    return assoc


# ── merge_entities ──


@pytest.mark.asyncio
async def test_merge_migrates_todo_and_association_references(db_session):
    """Merge migrates todos/associations; no row references source afterwards."""
    user_id = make_user_id()
    target = await _make_entity(session=db_session, user_id=user_id, name="王志强")
    source = await _make_entity(session=db_session, user_id=user_id, name="王总")
    third = await _make_entity(session=db_session, user_id=user_id, name="李四")

    todo = await _make_todo(db_session, user_id, str(source.id), "跟进王总")
    # source as association endpoint (both directions)
    a1 = await _make_association(db_session, user_id, str(source.id), str(third.id))
    a2 = await _make_association(db_session, user_id, str(third.id), str(source.id))

    result = await merge_entities(
        db_session, user_id, str(target.id), str(source.id)
    )

    assert result.migrated_todos == 1
    # a1 (source→third) and a2 (third→source) both become target↔third of the
    # same type — the unique constraint (user, source, target, type) forces
    # them to merge into a single row: 1 migrated + 1 conflict-absorbed.
    assert result.migrated_associations == 1
    assert result.merged_association_conflicts == 1

    # Todo now references target
    refreshed_todo = await db_session.get(Todo, todo.id)
    assert str(refreshed_todo.related_entity_id) == str(target.id)

    # No association references source
    remaining = (
        await db_session.execute(
            select(Association).where(
                Association.user_id == user_id,
                (Association.source_entity_id == str(source.id))
                | (Association.target_entity_id == str(source.id)),
            )
        )
    ).scalars().all()
    assert remaining == []

    # Exactly one association links target and third (both absorbed)
    target_third = (
        await db_session.execute(
            select(Association).where(
                Association.user_id == user_id,
                (Association.source_entity_id == str(target.id))
                | (Association.target_entity_id == str(target.id)),
            )
        )
    ).scalars().all()
    assert len(target_third) == 1


@pytest.mark.asyncio
async def test_merge_deep_merges_properties_and_appends_alias(db_session):
    """Non-empty fields inherit; merge_history appended; alias added."""
    user_id = make_user_id()
    target = await _make_entity(
        db_session, user_id=user_id, name="王志强", company="创新科技", title=None
    )
    source = await _make_entity(
        db_session, user_id=user_id, name="王总", company="旧公司", title="CEO"
    )

    await merge_entities(db_session, user_id, str(target.id), str(source.id))

    # Source name appended to aliases
    assert "王总" in (target.aliases or [])

    props = target.properties or {}
    # Non-empty target field kept (conflicts resolve to target — kept profile)
    assert props["basic"]["company"] == "创新科技"
    # Empty target field inherited from source
    assert props["basic"]["title"] == "CEO"
    # merge_history audit entry appended
    assert len(props.get("merge_history", [])) == 1

    # Source tombstoned with audit fields
    assert source.status == "merged"
    assert props_of(source).get("merged_into") == str(target.id)
    assert props_of(source).get("merged_reason") == "manual"


def props_of(entity: Entity) -> dict:
    return entity.properties or {}


@pytest.mark.asyncio
async def test_merge_already_merged_source_raises_conflict(db_session):
    """Idempotency: merging an already-merged source raises 409 with merged_into."""
    user_id = make_user_id()
    target = await _make_entity(session=db_session, user_id=user_id, name="王志强")
    source = await _make_entity(session=db_session, user_id=user_id, name="王总")
    await merge_entities(db_session, user_id, str(target.id), str(source.id))

    with pytest.raises(ConflictError) as exc_info:
        await merge_entities(db_session, user_id, str(target.id), str(source.id))
    assert exc_info.value.details.get("merged_into") == str(target.id)


@pytest.mark.asyncio
async def test_merge_self_raises_validation_error(db_session):
    user_id = make_user_id()
    entity = await _make_entity(session=db_session, user_id=user_id, name="王志强")

    with pytest.raises(ValidationError):
        await merge_entities(db_session, user_id, str(entity.id), str(entity.id))


@pytest.mark.asyncio
async def test_merge_cross_user_raises_not_found(db_session):
    """Merging another user's entity is invisible (404, not 403)."""
    user_a = make_user_id()
    user_b = make_user_id()
    target = await _make_entity(session=db_session, user_id=user_a, name="王志强")
    source = await _make_entity(session=db_session, user_id=user_b, name="王总")

    with pytest.raises(NotFoundError):
        await merge_entities(db_session, user_a, str(target.id), str(source.id))


@pytest.mark.asyncio
async def test_merge_association_conflict_keeps_stronger_row(db_session):
    """Duplicate (user, source, target, type) rows merge — count unchanged, max strength."""
    user_id = make_user_id()
    target = await _make_entity(session=db_session, user_id=user_id, name="王志强")
    source = await _make_entity(session=db_session, user_id=user_id, name="王总")
    third = await _make_entity(session=db_session, user_id=user_id, name="李四")

    # Existing target-third association AND source-third of same type → conflict
    await _make_association(
        db_session, user_id, str(target.id), str(third.id), strength=0.3
    )
    await _make_association(
        db_session, user_id, str(source.id), str(third.id), strength=0.8
    )

    before = (
        await db_session.execute(
            select(Association).where(
                Association.user_id == user_id,
                (Association.source_entity_id == str(third.id))
                | (Association.target_entity_id == str(third.id)),
            )
        )
    ).scalars().all()

    result = await merge_entities(db_session, user_id, str(target.id), str(source.id))

    after = (
        await db_session.execute(
            select(Association).where(
                Association.user_id == user_id,
                (Association.source_entity_id == str(third.id))
                | (Association.target_entity_id == str(third.id)),
            )
        )
    ).scalars().all()

    assert len(after) == len(before) - 1  # conflict rows merged, no new row
    assert result.merged_association_conflicts == 1
    # Surviving row keeps the stronger value
    assert any(a.strength == 0.8 for a in after)


@pytest.mark.asyncio
async def test_merge_direct_source_target_association_deleted(db_session):
    """A direct source↔target association is removed (no self-association)."""
    user_id = make_user_id()
    target = await _make_entity(session=db_session, user_id=user_id, name="王志强")
    source = await _make_entity(session=db_session, user_id=user_id, name="王总")
    await _make_association(db_session, user_id, str(source.id), str(target.id))

    await merge_entities(db_session, user_id, str(target.id), str(source.id))

    self_assocs = (
        await db_session.execute(
            select(Association).where(
                Association.user_id == user_id,
                Association.source_entity_id == str(target.id),
                Association.target_entity_id == str(target.id),
            )
        )
    ).scalars().all()
    assert self_assocs == []


# ── confirm_entity ──


@pytest.mark.asyncio
async def test_confirm_provisional_entity(db_session):
    user_id = make_user_id()
    entity = await _make_entity(
        session=db_session, user_id=user_id, name="王总", status="provisional"
    )

    confirmed = await confirm_entity(db_session, user_id, str(entity.id))
    assert confirmed.status == "confirmed"


@pytest.mark.asyncio
async def test_confirm_non_provisional_raises_conflict(db_session):
    user_id = make_user_id()
    entity = await _make_entity(session=db_session, user_id=user_id, name="王总")

    with pytest.raises(ConflictError):
        await confirm_entity(db_session, user_id, str(entity.id))


@pytest.mark.asyncio
async def test_confirm_missing_entity_raises_not_found(db_session):
    user_id = make_user_id()
    with pytest.raises(NotFoundError):
        await confirm_entity(db_session, user_id, str(uuid.uuid4()))


# ── find_duplicate_groups ──


@pytest.mark.asyncio
async def test_find_duplicate_groups_same_name(db_session):
    user_id = make_user_id()
    other_user = make_user_id()
    e1 = await _make_entity(session=db_session, user_id=user_id, name="王总", company="A公司")
    e2 = await _make_entity(
        session=db_session, user_id=user_id, name="王总", company="B公司", title="CTO"
    )
    # Noise: unique name, other user's same name, merged same name
    await _make_entity(session=db_session, user_id=user_id, name="李四")
    await _make_entity(session=db_session, user_id=other_user, name="王总")
    e3 = await _make_entity(session=db_session, user_id=user_id, name="赵五")
    e3.status = "merged"

    groups = await find_duplicate_groups(db_session, user_id)

    assert len(groups) == 1
    group = groups[0]
    assert group["name"] == "王总"
    assert group["hint"] == "同名"
    assert {e["id"] for e in group["entities"]} == {str(e1.id), str(e2.id)}
    by_id = {e["id"]: e for e in group["entities"]}
    assert by_id[str(e2.id)]["company"] == "B公司"
    assert by_id[str(e2.id)]["title"] == "CTO"


@pytest.mark.asyncio
async def test_find_duplicate_groups_empty_when_unique(db_session):
    user_id = make_user_id()
    await _make_entity(session=db_session, user_id=user_id, name="王总")
    await _make_entity(session=db_session, user_id=user_id, name="李四")

    groups = await find_duplicate_groups(db_session, user_id)
    assert groups == []
