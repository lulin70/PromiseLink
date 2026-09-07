"""W4 semantic contract coverage: synonyms, resolution, co-occurrence, and registration."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.services import event_pipeline
from promiselink.services.entity_resolution import EntityResolutionEngine, ResolutionAction
from promiselink.services.frequent_contact_scanner import scan_frequent_contacts
from promiselink.services.steps import Step10b_FrequentContactScan
from promiselink.services.synonym_dict import find_aliases, load_synonyms
from tests.conftest import create_test_event, make_entity_data, make_user_id


async def _entity(session, user_id: str, name: str, event_id: str | None = None) -> Entity:
    if event_id is None:
        event = await create_test_event(session, user_id=user_id)
        event_id = event.id
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=[],
        properties={"basic": {}},
        source_event_id=event_id,
        confidence=1.0,
        status="confirmed",
    )
    session.add(entity)
    await session.flush()
    return entity


async def _co_occurrence(
    session,
    user_id: str,
    source: Entity,
    target: Entity,
    when: datetime,
) -> None:
    """Model production W4 semantics: ONE canonical co_occurrence row per
    unordered pair; repeat encounters accumulate shared event ids in
    ``properties.evidence.shared_event_ids`` (mirrors the discovery engine's
    ``_append_shared_event``)."""
    event = await create_test_event(session, user_id=user_id)
    event.timestamp = when
    a_id, b_id = sorted([str(source.id), str(target.id)])
    row = (
        await session.execute(
            select(Association).where(
                Association.user_id == user_id,
                Association.source_entity_id == a_id,
                Association.target_entity_id == b_id,
                Association.association_type == "co_occurrence",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = Association(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_entity_id=a_id,
            target_entity_id=b_id,
            association_type="co_occurrence",
            strength=0.8,
            confidence=1.0,
            status="confirmed",
            source_event_id=str(event.id),
            properties={
                "evidence": {
                    "shared_event_id": str(event.id),
                    "shared_event_ids": [str(event.id)],
                }
            },
        )
        session.add(row)
    else:
        props = dict(row.properties or {})
        evidence = dict(props.get("evidence") or {})
        shared = [str(v) for v in (evidence.get("shared_event_ids") or [])]
        if str(event.id) not in shared:
            shared.append(str(event.id))
        evidence["shared_event_ids"] = shared
        evidence["shared_event_id"] = str(event.id)
        props["evidence"] = evidence
        row.properties = props
        row.source_event_id = str(event.id)
        row.last_interaction = when
    await session.flush()


def test_synonym_dict_resolves_canonical_and_alias_in_both_directions():
    dictionaries = ({"林晚秋": ["林总", "晚秋"]}, {"青梧科技": ["青梧"]})

    assert find_aliases("林晚秋", "person", dictionaries) == ["林晚秋", "林总", "晚秋"]
    assert find_aliases("林总", "person", dictionaries) == ["林晚秋", "晚秋"]
    assert find_aliases("晚秋", "person", dictionaries) == ["林晚秋", "林总"]
    assert find_aliases("青梧", "company", dictionaries) == ["青梧科技"]
    assert find_aliases("不存在", "person", dictionaries) == []


def test_load_synonyms_extends_seed_without_duplicate_aliases(tmp_path):
    path = tmp_path / "synonyms.json"
    path.write_text(
        json.dumps(
            {
                "person": {"林晚秋": ["林总", "新别名"], "新人物": ["新称呼"]},
                "company": {"青梧科技": ["青梧", "新简称"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    person, company = load_synonyms(path)

    assert person["林晚秋"] == ["林总", "晚秋", "新别名"]
    assert person["新人物"] == ["新称呼"]
    assert company["青梧科技"] == ["青梧", "Qingwu Technology", "新简称"]


@pytest.mark.asyncio
async def test_entity_resolution_synonym_match_is_confirm_only(db_session):
    user_id = make_user_id()
    existing_event = await create_test_event(db_session, user_id=user_id)
    existing = await _entity(db_session, user_id, "林晚秋", existing_event.id)
    await db_session.flush()

    engine = EntityResolutionEngine(
        db_session,
        person_synonyms={"林晚秋": ["林总"]},
        company_synonyms={},
    )
    result = await engine.resolve(make_entity_data(name="林总"), user_id)

    assert result.action == ResolutionAction.CONFIRM
    assert result.matched_step == "synonym_match"
    assert result.confidence == pytest.approx(0.97)
    assert result.target_entity.id == existing.id
    assert result.matched_fields["method"] == "synonym"


@pytest.mark.asyncio
async def test_entity_resolution_difflib_cutoff_returns_confirm(db_session):
    user_id = make_user_id()
    existing = await _entity(db_session, user_id, "Alice")
    await db_session.flush()

    engine = EntityResolutionEngine(db_session, difflib_cutoff=0.80)
    result = await engine.resolve(make_entity_data(name="Alic"), user_id)

    assert result.action == ResolutionAction.CONFIRM
    assert result.matched_step == "difflib_match"
    assert result.confidence == pytest.approx(0.82)
    assert result.matched_fields["method"] == "difflib"
    assert result.matched_fields["name"] >= 0.80


@pytest.mark.asyncio
async def test_normalization_does_not_auto_merge_or_change_entity_count(db_session):
    user_id = make_user_id()
    existing = await _entity(db_session, user_id, "林晚秋")
    await db_session.flush()
    before = await db_session.scalar(
        select(func.count()).select_from(Entity).where(Entity.user_id == user_id)
    )

    engine = EntityResolutionEngine(
        db_session,
        person_synonyms={"林晚秋": ["林总"]},
    )
    result = await engine.resolve(make_entity_data(name="林总"), user_id)
    after = await db_session.scalar(
        select(func.count()).select_from(Entity).where(Entity.user_id == user_id)
    )
    await db_session.refresh(existing)

    assert result.action == ResolutionAction.CONFIRM
    assert result.is_merge is False
    assert before == after == 1
    assert existing.status == "confirmed"


@pytest.mark.asyncio
async def test_frequent_contact_marks_pair_after_three_events_within_90_days(db_session):
    user_id = make_user_id()
    source = await _entity(db_session, user_id, "A")
    target = await _entity(db_session, user_id, "B")
    now = datetime.now(UTC)

    for days_ago in (1, 10, 30):
        await _co_occurrence(db_session, user_id, source, target, now - timedelta(days=days_ago))

    pairs = await scan_frequent_contacts(db_session, user_id=user_id)
    await db_session.refresh(source)
    await db_session.refresh(target)

    assert len(pairs) == 1
    assert pairs[0]["count"] == 3
    assert source.properties["frequent_contact"]["count"] == 3
    assert target.properties["frequent_contact"]["window_days"] == 90


@pytest.mark.asyncio
async def test_frequent_contact_does_not_mark_two_events_or_events_older_than_90_days(db_session):
    user_two = make_user_id()
    source_two = await _entity(db_session, user_two, "A2")
    target_two = await _entity(db_session, user_two, "B2")
    now = datetime.now(UTC)
    for days_ago in (1, 10):
        await _co_occurrence(db_session, user_two, source_two, target_two, now - timedelta(days=days_ago))

    user_old = make_user_id()
    source_old = await _entity(db_session, user_old, "A-old")
    target_old = await _entity(db_session, user_old, "B-old")
    for days_ago in (91, 100, 110):
        await _co_occurrence(db_session, user_old, source_old, target_old, now - timedelta(days=days_ago))

    assert await scan_frequent_contacts(db_session, user_id=user_two) == []
    assert await scan_frequent_contacts(db_session, user_id=user_old) == []
    await db_session.refresh(source_two)
    await db_session.refresh(target_two)
    await db_session.refresh(source_old)
    await db_session.refresh(target_old)
    assert "frequent_contact" not in (source_two.properties or {})
    assert "frequent_contact" not in (target_two.properties or {})
    assert "frequent_contact" not in (source_old.properties or {})
    assert "frequent_contact" not in (target_old.properties or {})


@pytest.mark.asyncio
async def test_frequent_contact_is_scoped_to_user(db_session):
    user_a = make_user_id()
    source_a = await _entity(db_session, user_a, "A")
    target_a = await _entity(db_session, user_a, "B")
    user_b = make_user_id()
    source_b = await _entity(db_session, user_b, "A")
    target_b = await _entity(db_session, user_b, "B")
    now = datetime.now(UTC)
    for days_ago in (1, 2, 3):
        await _co_occurrence(db_session, user_a, source_a, target_a, now - timedelta(days=days_ago))

    pairs_b = await scan_frequent_contacts(db_session, user_id=user_b)
    assert pairs_b == []
    await db_session.refresh(source_b)
    await db_session.refresh(target_b)
    assert "frequent_contact" not in (source_b.properties or {})
    assert "frequent_contact" not in (target_b.properties or {})

    pairs_a = await scan_frequent_contacts(db_session, user_id=user_a)
    assert len(pairs_a) == 1



def test_step10b_is_registered_between_step10_and_step11():
    assert Step10b_FrequentContactScan.name == "step10b_frequent_contact"
    assert "Step10_AssociationDiscovery" in event_pipeline._PIPELINE_STEPS
    assert "Step10b_FrequentContactScan" in event_pipeline._PIPELINE_STEPS
    assert "Step11_AssociationTodos" in event_pipeline._PIPELINE_STEPS
    step10 = event_pipeline._PIPELINE_STEPS.index("Step10_AssociationDiscovery")
    step10b = event_pipeline._PIPELINE_STEPS.index("Step10b_FrequentContactScan")
    step11 = event_pipeline._PIPELINE_STEPS.index("Step11_AssociationTodos")
    assert step10 < step10b < step11
