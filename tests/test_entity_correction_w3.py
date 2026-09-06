"""Minimal W3 EntityCorrection unit/integration coverage."""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from promiselink.api.v1.event_pipeline_api import (
    CorrectedEntityItem,
    EventCorrectRequest,
    correct_event,
)
from promiselink.models.entity import Entity
from promiselink.models.entity_correction import EntityCorrection
from promiselink.models.event import Event
from promiselink.services.entity_correction_retention import cleanup_entity_corrections
from promiselink.services.entity_correction_service import record_correction

sqlite3.register_adapter(uuid.UUID, str)


TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


async def _create_event(session, user_id: str = TEST_USER_ID) -> Event:
    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="meeting",
        source="test",
        title="W3 test event",
        raw_text="W3 test",
        status="completed",
    )
    session.add(event)
    await session.flush()
    return event


async def _create_entity(
    session,
    event: Event,
    *,
    user_id: str = TEST_USER_ID,
    name: str,
    status: str = "confirmed",
) -> Entity:
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        source_event_id=event.id,
        properties={"basic": {"company": "测试公司"}},
        confidence=0.9,
        status=status,
    )
    session.add(entity)
    await session.flush()
    return entity


async def _create_correction(
    session,
    *,
    user_id: str,
    event_id: str,
    correction_type: str = "entity",
    action: str = "select_existing",
    original_text: str | None = None,
    candidate_ids: list[str] | None = None,
) -> EntityCorrection:
    row = await record_correction(
        session,
        user_id=user_id,
        event_id=event_id,
        correction_type=correction_type,
        action=action,
        original_extracted_text=original_text,
        candidate_entity_ids=candidate_ids,
    )
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_record_correction_redacts_pii_before_persisting(db_session):
    event = await _create_event(db_session)

    row = await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        original_text=(
            "手机13812341234，邮箱user@example.com，"
            "身份证310101199001011234，卡号6222021234561234，"
            "微信号：zhangsan123"
        ),
    )

    assert row.original_extracted_text == (
        "手机138****1234，邮箱u***@example.com，"
        "身份证310***********1234，卡号********1234，"
        "微信号：wx_***23"
    )
    assert "13812341234" not in row.original_extracted_text
    assert "user@example.com" not in row.original_extracted_text


@pytest.mark.asyncio
async def test_audit_projection_excludes_raw_text_and_candidate_ids(db_session):
    event = await _create_event(db_session)
    candidate_id = str(uuid.uuid4())
    row = await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        original_text="手机13812341234",
        candidate_ids=[candidate_id],
    )

    projection = row.to_audit_dict()

    assert set(projection) == {
        "id",
        "user_id",
        "event_id",
        "correction_type",
        "entity_id",
        "selected_entity_id",
        "action",
        "created_at",
    }
    assert "original_extracted_text" not in projection
    assert "candidate_entity_ids" not in projection
    assert projection["action"] == "select_existing"


@pytest.mark.asyncio
async def test_retention_cleanup_deletes_only_expired_rows(db_session):
    event = await _create_event(db_session)
    expired = await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        action="ignore",
    )
    retained = await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        action="create_new",
    )
    expired.created_at = datetime.now(UTC) - timedelta(days=181)
    retained.created_at = datetime.now(UTC) - timedelta(days=179)
    await db_session.commit()

    assert await cleanup_entity_corrections(db_session, retention_days=180) == 1
    remaining = (
        await db_session.execute(select(EntityCorrection).order_by(EntityCorrection.action))
    ).scalars().all()
    assert [str(row.id) for row in remaining] == [str(retained.id)]


@pytest.mark.asyncio
async def test_aggregations_aggregate_by_type_and_user_and_exclude_sensitive_columns(db_session):
    event = await _create_event(db_session, TEST_USER_ID)
    other_event = await _create_event(db_session, OTHER_USER_ID)
    await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        action="select_existing",
        original_text="手机13812341234",
        candidate_ids=[str(uuid.uuid4())],
    )
    await _create_correction(
        db_session,
        user_id=TEST_USER_ID,
        event_id=str(event.id),
        action="create_new",
        original_text="邮箱user@example.com",
        candidate_ids=[str(uuid.uuid4())],
    )
    await _create_correction(
        db_session,
        user_id=OTHER_USER_ID,
        event_id=str(other_event.id),
        action="select_existing",
        original_text="另一用户原文",
        candidate_ids=[str(uuid.uuid4())],
    )
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT correction_type, action, COUNT(*) AS cnt, MAX(created_at) AS last_seen "
                "FROM entity_corrections "
                "WHERE user_id = :uid AND created_at >= :since "
                "GROUP BY correction_type, action "
                "ORDER BY cnt DESC"
            ),
            {"uid": TEST_USER_ID, "since": datetime.now(UTC) - timedelta(days=30)},
        )
    ).fetchall()

    aggregate_keys = {row.correction_type for row in rows}
    assert aggregate_keys == {"entity"}, "only current user's rows should aggregate"
    actions = {row.action for row in rows}
    assert actions == {"select_existing", "create_new"}
    counts = {row.action: int(row.cnt) for row in rows}
    assert counts == {"select_existing": 1, "create_new": 1}
    for row in rows:
        row_keys = set(row._mapping)
        assert row_keys == {"correction_type", "action", "cnt", "last_seen"}
        assert "original_extracted_text" not in row_keys
        assert "candidate_entity_ids" not in row_keys
        assert "user_id" not in row_keys
        assert "event_id" not in row_keys
        assert "entity_id" not in row_keys
        assert "selected_entity_id" not in row_keys


@pytest.mark.asyncio
async def test_select_existing_commits_business_merge_and_audit_together(db_session):
    event = await _create_event(db_session)
    historical_event = await _create_event(db_session)
    source = await _create_entity(db_session, event, name="李总")
    target = await _create_entity(db_session, historical_event, name="李建国")
    source_id = str(source.id)
    target_id = str(target.id)
    event_id = str(event.id)
    await db_session.commit()

    response = await correct_event(
        uuid.UUID(event_id),
        EventCorrectRequest(
            corrected_entities=[
                CorrectedEntityItem(
                    extracted_entity_id=source_id,
                    action="select_existing",
                    selected_entity_id=target_id,
                )
            ]
        ),
        db_session,
        TEST_USER_ID,
    )

    assert response.entities_updated == 1
    await db_session.commit()
    source_after = await db_session.get(Entity, uuid.UUID(source_id))
    audit = (
        await db_session.execute(
            select(EntityCorrection).where(
                EntityCorrection.event_id == event_id,
                EntityCorrection.action == "select_existing",
            )
        )
    ).scalar_one()
    assert source_after.status == "merged"
    assert str(audit.entity_id) == source_id
    assert str(audit.selected_entity_id) == target_id


@pytest.mark.asyncio
async def test_select_existing_rolls_back_merge_when_audit_record_fails(db_session, monkeypatch):
    event = await _create_event(db_session)
    historical_event = await _create_event(db_session)
    source = await _create_entity(db_session, event, name="李总")
    target = await _create_entity(db_session, historical_event, name="李建国")
    source_id = str(source.id)
    target_id = str(target.id)
    event_id = str(event.id)
    await db_session.commit()

    async def fail_record_correction(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(
        "promiselink.api.v1.event_pipeline_api.record_correction",
        fail_record_correction,
    )

    with pytest.raises(RuntimeError, match="audit write failed"):
        await correct_event(
            uuid.UUID(event_id),
            EventCorrectRequest(
                corrected_entities=[
                    CorrectedEntityItem(
                        extracted_entity_id=source_id,
                        action="select_existing",
                        selected_entity_id=target_id,
                    )
                ]
            ),
            db_session,
            TEST_USER_ID,
        )
    await db_session.rollback()

    source_after = (
        await db_session.execute(select(Entity).where(Entity.id == source_id))
    ).scalar_one()
    audit_count = await db_session.scalar(
        select(func.count()).select_from(EntityCorrection).where(EntityCorrection.event_id == event_id)
    )
    assert source_after.status == "confirmed"
    assert audit_count == 0
