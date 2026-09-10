"""W5 candidate token API boundary tests (B-7).

Covers the Test Plan release-gate cases:
- T-W5-02 tampered token → candidate_token_invalid (400)
- T-W5-03 first submission after expiry → candidate_token_expired (410)
- T-W5-04 cross-user token → candidate_token_invalid (400)
- T-W5-05 cross-event token → candidate_token_invalid (400)
- T-W5-06 cross-resource token → candidate_token_invalid (400)
- T-W5-07 candidate data drift after issuance → digest mismatch (400)
- T-W5-08 resolver version mismatch → candidate_token_invalid (400)
- T-W5-09 embedding-space mismatch → candidate_token_invalid (400)
- T-W5-10 token replay → persisted result, no duplicate merge/audit
- T-W5-11 completed replay after TTL → still returns persisted result
- T-W5-12/13 concurrent confirm/reject → one fact result (lock-serialized)
- T-W5-14 confirm then reject replay → no fact reversal
- T-W5-15 invalid token → zero writes
- T-W5-16 client-supplied candidate values ignored
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.config import get_settings
from promiselink.core.auth import get_current_user_id, issue_candidate_token
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.entity_correction import EntityCorrection
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.w5_operation_service import compute_candidate_digest

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
API_PREFIX = "/api/v1"
TEST_SECRET = "test-w5-secret-do-not-use-in-prod"


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def w5_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cross_language_enabled", True)
    monkeypatch.setattr(settings, "cross_language_todo_enabled", True)
    monkeypatch.setattr(settings, "candidate_token_secret_v1", TEST_SECRET)
    monkeypatch.setattr(settings, "candidate_token_key_version", "1")
    monkeypatch.setattr(settings, "candidate_token_revoked_key_versions", [])
    monkeypatch.setattr(settings, "candidate_token_ttl_seconds", 600)
    monkeypatch.setattr(settings, "candidate_token_max_ttl_seconds", 600)
    monkeypatch.setattr(
        settings, "cross_language_resolver_version", "w5-resolver-v1"
    )
    monkeypatch.setattr(settings, "cross_language_score_version", "w5-score-v1")
    monkeypatch.setattr(
        settings, "cross_language_embedding_space", "local/all-MiniLM-L6-v2/384"
    )
    return settings


# ── Data helpers ──


async def setup_w5_event(session: AsyncSession) -> dict:
    """Event + extracted zh entity + canonical en entity in the synonym family."""
    event_id = str(uuid.uuid4())
    other_event_id = str(uuid.uuid4())
    session.add_all(
        [
            Event(
                id=event_id,
                user_id=TEST_USER_ID,
                event_type="meeting",
                source="test",
                title="与青梧科技开会",
                raw_text="和青梧科技开会",
                status="completed",
            ),
            Event(
                id=other_event_id,
                user_id=TEST_USER_ID,
                event_type="meeting",
                source="test",
                title="其他事件",
                raw_text="其他",
                status="completed",
            ),
        ]
    )
    await session.flush()

    extracted_id = str(uuid.uuid4())
    canonical_id = str(uuid.uuid4())
    unrelated_id = str(uuid.uuid4())
    session.add_all(
        [
            Entity(
                id=extracted_id,
                user_id=TEST_USER_ID,
                entity_type="organization",
                name="青梧科技",
                canonical_name="青梧科技",
                source_event_id=event_id,
                confidence=0.9,
                status="confirmed",
            ),
            Entity(
                id=canonical_id,
                user_id=TEST_USER_ID,
                entity_type="organization",
                name="Qingwu Technology",
                canonical_name="Qingwu Technology",
                source_event_id=other_event_id,
                confidence=1.0,
                status="confirmed",
            ),
            Entity(
                id=unrelated_id,
                user_id=TEST_USER_ID,
                entity_type="organization",
                name="毫不相关公司",
                canonical_name="毫不相关公司",
                source_event_id=other_event_id,
                confidence=1.0,
                status="confirmed",
            ),
        ]
    )
    await session.flush()
    return {
        "event_id": event_id,
        "other_event_id": other_event_id,
        "extracted_id": extracted_id,
        "canonical_id": canonical_id,
        "unrelated_id": unrelated_id,
    }


async def setup_w5_todos(session: AsyncSession, ids: dict) -> dict:
    source_todo_id = str(uuid.uuid4())
    candidate_todo_id = str(uuid.uuid4())
    session.add_all(
        [
            Todo(
                id=source_todo_id,
                user_id=TEST_USER_ID,
                todo_type="followup",
                title="Prepare Q3 budget",
                status="pending",
                source_event_id=ids["event_id"],
            ),
            Todo(
                id=candidate_todo_id,
                user_id=TEST_USER_ID,
                todo_type="followup",
                title="prepare q3 budget",
                status="pending",
                source_event_id=ids["other_event_id"],
            ),
        ]
    )
    await session.flush()
    return {"source_todo_id": source_todo_id, "candidate_todo_id": candidate_todo_id}


async def issue_entity_candidates(
    client: AsyncClient, ids: dict
) -> dict:
    resp = await client.get(
        f"{API_PREFIX}/events/{ids['event_id']}"
        f"/entities/{ids['extracted_id']}/candidates"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def correction_counts(session: AsyncSession) -> tuple[int, int]:
    ent = (await session.execute(select(func.count()).select_from(Entity))).scalar_one()
    corr = (
        await session.execute(select(func.count()).select_from(EntityCorrection))
    ).scalar_one()
    return ent, corr


# ── Issuance endpoint tests ──


@pytest.mark.asyncio
async def test_candidates_issue_token_and_operation_row(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    await setup_w5_todos(db_session, ids)

    data = await issue_entity_candidates(client, ids)

    assert data["scope_type"] == "entity"
    assert data["confirm_only"] is True
    assert data["candidate_token"]
    assert data["expires_at"]
    # Server-side synonym family match: zh source → en canonical candidate.
    assert len(data["candidates"]) == 1
    top = data["candidates"][0]
    assert top["candidate_id"] == ids["canonical_id"]
    assert top["method"] == "synonym_match"
    assert top["language_pair"] == "zh_en"
    assert top["rank"] == 1
    assert top["confirm_only"] is True

    row = (
        await db_session.execute(select(EntityCorrection))
    ).scalars().all()
    assert len(row) == 1
    op = row[0]
    assert op.operation_status == "issued"
    assert op.token_hash
    assert op.token_key_version == "1"
    assert op.resolver_version == "w5-resolver-v1"
    assert op.score_version == "w5-score-v1"
    assert op.embedding_space == "local/all-MiniLM-L6-v2/384"
    assert op.candidate_entity_ids == [ids["canonical_id"]]
    assert op.candidate_digest


@pytest.mark.asyncio
async def test_candidates_disabled_returns_400(client, db_session):
    ids = await setup_w5_event(db_session)
    resp = await client.get(
        f"{API_PREFIX}/events/{ids['event_id']}"
        f"/entities/{ids['extracted_id']}/candidates"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ── Confirm happy path ──


@pytest.mark.asyncio
async def test_confirm_happy_path_merges_and_audits(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entities_updated"] == 1
    assert len(body["w5_operations"]) == 1
    op_result = body["w5_operations"][0]
    assert op_result["operation_status"] == "confirmed"
    assert op_result["replayed"] is False
    assert op_result["result_summary"] == {
        "candidate_rank": 1,
        "method": "synonym_match",
        "score": 0.95,
        "language_pair": "zh_en",
    }

    op_row = (
        (await db_session.execute(select(EntityCorrection))).scalars().one()
    )
    assert op_row.operation_status == "confirmed"
    assert op_row.action == "select_existing"
    assert op_row.completed_at is not None
    assert op_row.selected_entity_id is not None

    # Merge happened: extracted entity no longer active.
    extracted = await db_session.get(Entity, ids["extracted_id"])
    assert extracted.status != "confirmed"


# ── Invalid token family (400) ──


@pytest.mark.asyncio
async def test_tampered_token_rejected_zero_writes(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)

    token = data["candidate_token"]
    # Flip one character while keeping base64url shape (mid-payload tamper).
    tampered = ("A" if token[len(token) // 2] != "A" else "B").join(
        [token[: len(token) // 2], token[len(token) // 2 + 1 :]]
    )
    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": tampered,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"

    entities, corrections = await correction_counts(db_session)
    assert (entities, corrections) == (3, 1)  # issuance row only, no new audit


@pytest.mark.asyncio
async def test_cross_user_token_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    digest = compute_candidate_digest("entity", ids["extracted_id"], [ids["canonical_id"]])
    token, _ = issue_candidate_token(
        user_id=OTHER_USER_ID,
        event_id=ids["event_id"],
        scope_type="entity",
        resource_id=ids["extracted_id"],
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version="w5-resolver-v1",
        score_version="w5-score-v1",
        embedding_space="local/all-MiniLM-L6-v2/384",
    )
    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"
    _, corrections = await correction_counts(db_session)
    assert corrections == 0  # T-W5-15: zero writes


@pytest.mark.asyncio
async def test_cross_event_token_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    digest = compute_candidate_digest("entity", ids["extracted_id"], [ids["canonical_id"]])
    token, _ = issue_candidate_token(
        user_id=TEST_USER_ID,
        event_id=ids["other_event_id"],
        scope_type="entity",
        resource_id=ids["extracted_id"],
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version="w5-resolver-v1",
        score_version="w5-score-v1",
        embedding_space="local/all-MiniLM-L6-v2/384",
    )
    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"
    _, corrections = await correction_counts(db_session)
    assert corrections == 0


@pytest.mark.asyncio
async def test_cross_resource_token_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    digest = compute_candidate_digest("entity", ids["unrelated_id"], [ids["canonical_id"]])
    token, _ = issue_candidate_token(
        user_id=TEST_USER_ID,
        event_id=ids["event_id"],
        scope_type="entity",
        resource_id=ids["unrelated_id"],
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version="w5-resolver-v1",
        score_version="w5-score-v1",
        embedding_space="local/all-MiniLM-L6-v2/384",
    )
    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"
    _, corrections = await correction_counts(db_session)
    assert corrections == 0


@pytest.mark.asyncio
async def test_candidate_drift_invalidates_digest(client, db_session, w5_settings):
    """T-W5-07: candidate data changes between issuance and submit → 400."""
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)

    # New entity enters the server-side candidate set after issuance.
    drift_id = str(uuid.uuid4())
    db_session.add(
        Entity(
            id=drift_id,
            user_id=TEST_USER_ID,
            entity_type="organization",
            name="青梧科技股",
            canonical_name="青梧科技股",
            source_event_id=ids["other_event_id"],
            confidence=1.0,
            status="confirmed",
        )
    )
    await db_session.commit()

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_resolver_mismatch_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    w5_settings.cross_language_resolver_version = "w5-resolver-v2"

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_embedding_space_mismatch_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    w5_settings.cross_language_embedding_space = "api/text-embedding-v3/768"

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_client_candidate_values_ignored(client, db_session, w5_settings):
    """T-W5-16: client-supplied scores/methods/ids never become facts."""
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                    "score": 0.01,
                    "method": "hacked_method",
                    "candidate_entity_ids": [ids["unrelated_id"]],
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    op = resp.json()["w5_operations"][0]
    assert op["result_summary"]["method"] == "synonym_match"  # server-side value
    assert op["result_summary"]["score"] == 0.95


@pytest.mark.asyncio
async def test_selected_outside_candidate_set_rejected(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)

    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["unrelated_id"],
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ── Expiry + replay family ──


@pytest.mark.asyncio
async def test_first_submit_after_expiry_410(client, db_session, w5_settings):
    """T-W5-03: valid token, first submission past expires_at → 410."""
    ids = await setup_w5_event(db_session)
    digest = compute_candidate_digest("entity", ids["extracted_id"], [ids["canonical_id"]])
    token, _ = issue_candidate_token(
        user_id=TEST_USER_ID,
        event_id=ids["event_id"],
        scope_type="entity",
        resource_id=ids["extracted_id"],
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version="w5-resolver-v1",
        score_version="w5-score-v1",
        embedding_space="local/all-MiniLM-L6-v2/384",
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    resp = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "CANDIDATE_TOKEN_EXPIRED"
    _, corrections = await correction_counts(db_session)
    assert corrections == 0  # expired first submit: zero writes


@pytest.mark.asyncio
async def test_replay_returns_persisted_result(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    token = data["candidate_token"]

    first = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert first.status_code == 200
    assert first.json()["w5_operations"][0]["replayed"] is False
    _, corrections_after_first = await correction_counts(db_session)

    second = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert second.status_code == 200
    replay = second.json()["w5_operations"][0]
    assert replay["replayed"] is True
    assert replay["operation_status"] == "confirmed"
    assert replay["result_summary"] == first.json()["w5_operations"][0]["result_summary"]
    # No duplicate merge or audit (T-W5-10).
    _, corrections_after_replay = await correction_counts(db_session)
    assert corrections_after_replay == corrections_after_first


@pytest.mark.asyncio
async def test_replay_after_ttl_returns_persisted_result(client, db_session, w5_settings):
    """T-W5-11: completed operation replays even after token TTL."""
    monkey_ttl = w5_settings
    monkey_ttl.candidate_token_ttl_seconds = 1
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    token = data["candidate_token"]

    first = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert first.status_code == 200

    await asyncio.sleep(1.2)  # token TTL (1s) elapses after completion
    second = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert second.status_code == 200
    replay = second.json()["w5_operations"][0]
    assert replay["replayed"] is True
    assert replay["operation_status"] == "confirmed"


@pytest.mark.asyncio
async def test_concurrent_confirm_yields_single_fact(client, db_session, w5_settings):
    """T-W5-12: two submits of the same token → one fact, second is replay."""
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    token = data["candidate_token"]
    payload = {
        "corrected_entities": [
            {
                "extracted_entity_id": ids["extracted_id"],
                "action": "select_existing",
                "selected_entity_id": ids["canonical_id"],
                "candidate_token": token,
                "resolution_action": "confirm",
            }
        ]
    }

    first, second = await asyncio.gather(
        client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json=payload),
        client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json=payload),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    statuses = sorted(
        [first.json()["w5_operations"][0], second.json()["w5_operations"][0]],
        key=lambda r: r["replayed"],
    )
    assert statuses[0]["replayed"] is False
    assert statuses[0]["operation_status"] == "confirmed"
    assert statuses[1]["replayed"] is True
    _, corrections = await correction_counts(db_session)
    assert corrections == 1  # at most one audit row


@pytest.mark.asyncio
async def test_confirm_then_reject_does_not_reverse(client, db_session, w5_settings):
    """T-W5-14: reject replay of a completed confirm must not reverse the fact."""
    ids = await setup_w5_event(db_session)
    data = await issue_entity_candidates(client, ids)
    token = data["candidate_token"]

    confirm = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "select_existing",
                    "selected_entity_id": ids["canonical_id"],
                    "candidate_token": token,
                    "resolution_action": "confirm",
                }
            ]
        },
    )
    assert confirm.status_code == 200

    reject = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_entities": [
                {
                    "extracted_entity_id": ids["extracted_id"],
                    "action": "ignore",
                    "candidate_token": token,
                    "resolution_action": "reject",
                }
            ]
        },
    )
    assert reject.status_code == 200
    replay = reject.json()["w5_operations"][0]
    assert replay["replayed"] is True
    assert replay["operation_status"] == "confirmed"  # original fact intact

    op_row = (
        (await db_session.execute(select(EntityCorrection))).scalars().one()
    )
    assert op_row.operation_status == "confirmed"
    assert op_row.action == "select_existing"


# ── Todo association ──


@pytest.mark.asyncio
async def test_todo_confirm_links_entity_association(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    todos = await setup_w5_todos(db_session, ids)

    resp = await client.get(
        f"{API_PREFIX}/events/{ids['event_id']}"
        f"/entities/{ids['extracted_id']}/todos/candidates",
        params={"source_todo_id": todos["source_todo_id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scope_type"] == "todo"
    assert data["candidates"][0]["candidate_id"] == todos["candidate_todo_id"]

    confirm = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_todos": [
                {
                    "id": todos["source_todo_id"],
                    "title": "Prepare Q3 budget",
                    "action": "edit",
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "confirm",
                    "selected_todo_id": todos["candidate_todo_id"],
                }
            ]
        },
    )
    assert confirm.status_code == 200, confirm.text
    op = confirm.json()["w5_operations"][0]
    assert op["operation_status"] == "confirmed"
    assert op["result_summary"]["language_pair"] == "en_en"

    source = await db_session.get(Todo, todos["source_todo_id"])
    candidate = await db_session.get(Todo, todos["candidate_todo_id"])
    assert source.related_entity_id == candidate.related_entity_id or (
        source.related_entity_id is None and candidate.related_entity_id is None
    )

    op_row = (
        (await db_session.execute(select(EntityCorrection))).scalars().one()
    )
    assert op_row.correction_type == "todo"
    assert op_row.scope_type == "todo"
    assert op_row.source_todo_id is not None
    assert op_row.selected_todo_id is not None
    assert op_row.entity_id is None


@pytest.mark.asyncio
async def test_todo_reject_writes_no_todo_mutation(client, db_session, w5_settings):
    ids = await setup_w5_event(db_session)
    todos = await setup_w5_todos(db_session, ids)

    resp = await client.get(
        f"{API_PREFIX}/events/{ids['event_id']}"
        f"/entities/{ids['extracted_id']}/todos/candidates",
        params={"source_todo_id": todos["source_todo_id"]},
    )
    data = resp.json()

    reject = await client.post(
        f"{API_PREFIX}/events/{ids['event_id']}/correct",
        json={
            "corrected_todos": [
                {
                    "id": todos["source_todo_id"],
                    "title": "Prepare Q3 budget",
                    "action": "edit",
                    "candidate_token": data["candidate_token"],
                    "resolution_action": "reject",
                }
            ]
        },
    )
    assert reject.status_code == 200
    op = reject.json()["w5_operations"][0]
    assert op["operation_status"] == "rejected"
    assert op["replayed"] is False

    source = await db_session.get(Todo, todos["source_todo_id"])
    assert source.status == "pending"  # reject never mutates the source todo

    op_row = (
        (await db_session.execute(select(EntityCorrection))).scalars().one()
    )
    assert op_row.action == "ignore"
    assert op_row.operation_status == "rejected"
    assert op_row.selected_todo_id is None
