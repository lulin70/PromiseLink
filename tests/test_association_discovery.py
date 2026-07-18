"""Tests for Association Discovery Engine."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.services.association_discovery import (
    VALID_ASSOCIATION_TYPES,
    AssociationDiscoveryEngine,
)
from tests.conftest import create_test_event, make_user_id


def _wrap_discoverers_with_counter(engine: AssociationDiscoveryEngine) -> dict[str, int]:
    """Wrap every cold discoverer with a call counter.

    Returns a dict mapping discoverer name to call count. The dict is shared
    by all wrappers, so reading it after a call reflects the total invocations.
    """
    counts = {name: 0 for name in engine.cold_discoverers}
    original = dict(engine.cold_discoverers)
    for name, fn in original.items():
        async def _counting(ea, eb, _fn=fn, _name=name):
            counts[_name] += 1
            return await _fn(ea, eb)
        engine.cold_discoverers[name] = _counting
    return counts


async def _make_entity(
    session: AsyncSession,
    user_id: str,
    name: str,
    city: str = "",
    company: str = "",
    industry: str = "",
    event_id: str | None = None,
    properties: dict | None = None,
) -> Entity:
    """Helper to create an Entity object (not yet committed).

    If event_id is not provided, creates a test Event first for the FK constraint.
    """
    if event_id is None:
        evt = await create_test_event(session, user_id=user_id)
        event_id = evt.id
    props = properties or {}
    if city or company or industry:
        basic = props.get("basic", {})
        if city:
            basic["city"] = city
        if company:
            basic["company"] = company
        if industry:
            basic["industry"] = industry
        props["basic"] = basic

    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        properties=props,
        source_event_id=event_id,
        status="confirmed",
    )
    session.add(entity)
    return entity


# ── Discovery Methods ──


class TestDiscoverAlumni:
    """Test _discover_alumni method."""

    @pytest.mark.asyncio
    async def test_discover_alumni_same_school(self, db_session):
        """Alumni with same school → confidence 0.75 (cold type, on-demand)."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        # Alumni is a cold type — use discover_cold_types
        results = await engine.discover_cold_types(a, b)
        alumni = [r for r in results if r["association_type"] == "alumni"]
        assert len(alumni) == 1
        assert alumni[0]["confidence"] == 0.75
        assert "清华大学" in alumni[0]["evidence"]["common_schools"]

    @pytest.mark.asyncio
    async def test_discover_alumni_same_school_same_major(self, db_session):
        """Alumni with same school AND same major → confidence 0.95 (cold type)."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={
                "basic": {"schools": ["清华大学"], "majors": ["计算机科学"]},
            },
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={
                "basic": {"schools": ["清华大学"], "majors": ["计算机科学"]},
            },
        )
        await db_session.flush()

        results = await engine.discover_cold_types(a, b)
        alumni = [r for r in results if r["association_type"] == "alumni"]
        assert len(alumni) == 1
        assert alumni[0]["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_discover_alumni_no_match(self, db_session):
        """Alumni with different schools → confidence 0.0."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["北京大学"]}},
        )
        await db_session.flush()

        results = engine.discover_pair(a, b)
        alumni = [r for r in results if r["association_type"] == "alumni"]
        assert len(alumni) == 0


class TestDiscoverSameCity:
    """Test _discover_same_city method."""

    @pytest.mark.asyncio
    async def test_discover_same_city_match(self, db_session):
        """Same city → confidence 0.7."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(db_session, user_id, "Alice", city="北京")
        b = await _make_entity(db_session, user_id, "Bob", city="北京")
        await db_session.flush()

        results = engine.discover_pair(a, b)
        same_city = [r for r in results if r["association_type"] == "same_city"]
        assert len(same_city) == 1
        assert same_city[0]["confidence"] == 0.7
        assert same_city[0]["evidence"]["city"] == "北京"

    @pytest.mark.asyncio
    async def test_discover_same_city_no_match(self, db_session):
        """Different cities → no same_city association."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(db_session, user_id, "Alice", city="北京")
        b = await _make_entity(db_session, user_id, "Bob", city="上海")
        await db_session.flush()

        results = engine.discover_pair(a, b)
        same_city = [r for r in results if r["association_type"] == "same_city"]
        assert len(same_city) == 0


class TestDiscoverCompetitor:
    """Test _discover_competitor method."""

    @pytest.mark.asyncio
    async def test_discover_competitor_same_industry(self, db_session):
        """Same industry → competitor confidence 0.7."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        a = await _make_entity(db_session, user_id, "Alice", company="公司A", industry="人工智能")
        b = await _make_entity(db_session, user_id, "Bob", company="公司B", industry="人工智能")
        await db_session.flush()

        results = engine.discover_pair(a, b)
        competitor = [r for r in results if r["association_type"] == "competitor"]
        assert len(competitor) == 1
        assert competitor[0]["confidence"] == 0.7
        assert competitor[0]["evidence"]["source"] == "same_industry"

    @pytest.mark.asyncio
    async def test_discover_competitor_from_list(self, db_session):
        """Competitor from config competitor_pairs → confidence 0.95."""
        config = {"competitor_pairs": {"公司A": ["公司B"]}}
        engine = AssociationDiscoveryEngine(db_session, config=config)
        user_id = make_user_id()

        a = await _make_entity(db_session, user_id, "Alice", company="公司A", industry="人工智能")
        b = await _make_entity(db_session, user_id, "Bob", company="公司B", industry="人工智能")
        await db_session.flush()

        results = engine.discover_pair(a, b)
        competitor = [r for r in results if r["association_type"] == "competitor"]
        assert len(competitor) == 1
        assert competitor[0]["confidence"] == 0.95
        assert competitor[0]["evidence"]["source"] == "competitor_list"


class TestDiscoverCoOccurrence:
    """Test _discover_co_occurrence method."""

    @pytest.mark.asyncio
    async def test_discover_co_occurrence_same_event(self, db_session):
        """Entities from same event → co_occurrence via event-based discovery."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        evt = await create_test_event(db_session, user_id=user_id)
        event_id = evt.id

        a = await _make_entity(db_session, user_id, "Alice", event_id=event_id)
        b = await _make_entity(db_session, user_id, "Bob", event_id=event_id)
        await db_session.commit()

        # co_occurrence is now event-based: discover_all_pairs fetches from DB
        results = await engine.discover_all_pairs(user_id, event_id=event_id)
        co_occ = [r for r in results if r.association_type == "co_occurrence"]
        assert len(co_occ) >= 1

    @pytest.mark.asyncio
    async def test_discover_co_occurrence_different_events(self, db_session):
        """Entities from different events → no co_occurrence (0.0)."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        evt_a = await create_test_event(db_session, user_id=user_id)
        evt_b = await create_test_event(db_session, user_id=user_id)
        a = await _make_entity(db_session, user_id, "Alice", event_id=evt_a.id)
        b = await _make_entity(db_session, user_id, "Bob", event_id=evt_b.id)
        await db_session.flush()

        results = engine.discover_pair(a, b)
        co_occ = [r for r in results if r["association_type"] == "co_occurrence"]
        assert len(co_occ) == 0


# ── discover_pair ──


class TestDiscoverPair:
    """Test discover_pair public method."""

    @pytest.mark.asyncio
    async def test_discover_pair_multiple_types(self, db_session):
        """Pair with same_city → same_city association type."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        evt = await create_test_event(db_session, user_id=user_id)
        event_id = evt.id

        a = await _make_entity(db_session, user_id, "Alice", city="北京", event_id=event_id)
        b = await _make_entity(db_session, user_id, "Bob", city="北京", event_id=event_id)
        await db_session.flush()

        results = engine.discover_pair(a, b)
        types = {r["association_type"] for r in results}
        assert "same_city" in types
        # co_occurrence is now event-based only, not in discover_pair

    @pytest.mark.asyncio
    async def test_discover_pair_no_associations(self, db_session):
        """Pair with no matching attributes → empty results."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()

        evt_a = await create_test_event(db_session, user_id=user_id)
        evt_b = await create_test_event(db_session, user_id=user_id)

        a = await _make_entity(
            db_session, user_id, "Alice",
            city="北京", company="公司A", industry="行业A",
            event_id=evt_a.id,
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            city="上海", company="公司B", industry="行业B",
            event_id=evt_b.id,
        )
        await db_session.flush()

        results = engine.discover_pair(a, b)
        assert len(results) == 0


# ── discover_all_pairs ──


class TestDiscoverAllPairs:
    """Test discover_all_pairs async method."""

    @pytest.mark.asyncio
    async def test_discover_all_pairs_creates_associations(self, db_session):
        """3 entities → multiple associations created."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        evt = await create_test_event(db_session, user_id=user_id)
        event_id = evt.id
        evt_c = await create_test_event(db_session, user_id=user_id)

        a = await _make_entity(db_session, user_id, "Alice", city="北京", industry="AI", event_id=event_id)
        b = await _make_entity(db_session, user_id, "Bob", city="北京", industry="AI", event_id=event_id)
        c = await _make_entity(db_session, user_id, "Carol", city="上海", industry="AI", event_id=evt_c.id)
        await db_session.flush()

        new_assocs = await engine.discover_all_pairs(user_id, event_id=event_id)
        assert len(new_assocs) > 0

        # Verify associations are in the session
        for assoc in new_assocs:
            assert isinstance(assoc, Association)
            assert assoc.user_id == user_id

    @pytest.mark.asyncio
    async def test_discover_all_pairs_skips_insufficient_entities(self, db_session):
        """0 or 1 entity → empty list, no associations created."""
        engine = AssociationDiscoveryEngine(db_session)

        # No entities
        result = await engine.discover_all_pairs(make_user_id())
        assert result == []

        # Only 1 entity
        user_id = make_user_id()
        await _make_entity(db_session, user_id, "Alice", city="北京")
        await db_session.flush()

        result = await engine.discover_all_pairs(user_id)
        assert result == []


# ── Time Decay ──


class TestApplyTimeDecay:
    """Test apply_time_decay async method."""

    @pytest.mark.asyncio
    async def test_apply_time_decay_reduces_strength(self, db_session):
        """Time decay should reduce association strength."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        evt = await create_test_event(db_session, user_id=user_id)
        event_id = evt.id

        # Create entities and associations
        a = await _make_entity(db_session, user_id, "Alice", city="北京")
        b = await _make_entity(db_session, user_id, "Bob", city="北京")
        await db_session.flush()

        new_assocs = await engine.discover_all_pairs(user_id, event_id=event_id)
        assert len(new_assocs) > 0

        # Set last_interaction to 180 days ago (one half-life)
        assoc = new_assocs[0]
        assoc.last_interaction = datetime.now(UTC) - timedelta(days=180)
        original_strength = assoc.strength
        await db_session.flush()

        # Apply decay
        updated = await engine.apply_time_decay(user_id)
        assert updated > 0

        # After one half-life, strength should be roughly halved
        await db_session.refresh(assoc)
        assert assoc.strength < original_strength
        assert assoc.strength > 0.1  # Not rejected yet

    @pytest.mark.asyncio
    async def test_apply_time_decay_rejects_below_threshold(self, db_session):
        """Associations with very low strength after decay → rejected."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        evt = await create_test_event(db_session, user_id=user_id)
        event_id = evt.id

        # Create entities and associations
        a = await _make_entity(db_session, user_id, "Alice", city="北京")
        b = await _make_entity(db_session, user_id, "Bob", city="北京")
        await db_session.flush()

        new_assocs = await engine.discover_all_pairs(user_id, event_id=event_id)
        assert len(new_assocs) > 0

        # Set last_interaction very far back and low strength
        assoc = new_assocs[0]
        assoc.last_interaction = datetime.now(UTC) - timedelta(days=2000)
        assoc.strength = 0.15
        await db_session.flush()

        # Apply decay
        updated = await engine.apply_time_decay(user_id)
        assert updated > 0

        # Association should be rejected (strength < 0.1 after decay)
        await db_session.refresh(assoc)
        assert assoc.status == "rejected"
        assert assoc.strength < 0.1


# ── Constants ──


class TestConstants:
    """Test module-level constants."""

    def test_valid_association_types_count(self):
        """VALID_ASSOCIATION_TYPES should contain 12 types (9 structural + 3 semantic)."""
        assert len(VALID_ASSOCIATION_TYPES) == 12
        expected = {
            # Structural types (exact field match)
            "alumni", "ex_colleague", "same_city", "competitor",
            "tech_overlap", "deal_link", "risk_link", "supply_chain",
            "co_occurrence",
            # Semantic types (LLM-assisted inference)
            "topic_overlap", "supply_demand", "industry_chain",
        }
        assert VALID_ASSOCIATION_TYPES == expected


# ── P1-3: In-process LRU+TTL cache ──


class TestColdCache:
    """Test in-process LRU+TTL cache for discover_cold_types (P1-3)."""

    @pytest.mark.asyncio
    async def test_cold_cache_miss_on_first_call(self, db_session):
        """First call should miss cache and populate it."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        assert len(engine._cold_cache) == 0
        results = await engine.discover_cold_types(a, b)
        assert len(results) > 0  # alumni match
        assert len(engine._cold_cache) == 1

    @pytest.mark.asyncio
    async def test_cold_cache_hit_on_second_call(self, db_session):
        """Second call with same entities should hit cache (no recompute)."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        counts = _wrap_discoverers_with_counter(engine)

        # First call — miss, should invoke discoverers
        r1 = await engine.discover_cold_types(a, b)
        first_total = sum(counts.values())
        assert first_total > 0

        # Second call — hit, should NOT invoke any discoverer
        r2 = await engine.discover_cold_types(a, b)
        assert sum(counts.values()) == first_total  # no new calls
        assert r1 == r2

    @pytest.mark.asyncio
    async def test_cold_cache_key_order_independent(self, db_session):
        """Cache key should be order-independent: (a,b) == (b,a)."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        counts = _wrap_discoverers_with_counter(engine)

        await engine.discover_cold_types(a, b)
        assert len(engine._cold_cache) == 1
        first_total = sum(counts.values())

        # Reversed order should hit the same cache entry
        await engine.discover_cold_types(b, a)
        assert len(engine._cold_cache) == 1
        assert sum(counts.values()) == first_total  # no new calls

    @pytest.mark.asyncio
    async def test_cold_cache_ttl_expiry(self, db_session):
        """Expired cache entry should be recomputed."""
        from promiselink.services.association_discovery import _COLD_CACHE_TTL_SECONDS

        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        # First call populates cache
        r1 = await engine.discover_cold_types(a, b)
        assert len(engine._cold_cache) == 1

        # Backdate the cache entry to simulate TTL expiry
        cache_key = tuple(sorted([str(a.id), str(b.id)]))
        old_ts, cached_results = engine._cold_cache[cache_key]
        engine._cold_cache[cache_key] = (old_ts - _COLD_CACHE_TTL_SECONDS - 1, cached_results)

        counts = _wrap_discoverers_with_counter(engine)

        # Second call should recompute (expired)
        r2 = await engine.discover_cold_types(a, b)
        assert sum(counts.values()) > 0  # discoverers were invoked
        # Cache entry should be refreshed with a fresh timestamp
        new_ts, _ = engine._cold_cache[cache_key]
        assert new_ts > old_ts - _COLD_CACHE_TTL_SECONDS - 1
        assert r1 == r2  # content equivalent

    @pytest.mark.asyncio
    async def test_clear_cache_empties_cache(self, db_session):
        """clear_cache() should empty the cache; next call recomputes."""
        engine = AssociationDiscoveryEngine(db_session)
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "Alice",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        b = await _make_entity(
            db_session, user_id, "Bob",
            properties={"basic": {"schools": ["清华大学"]}},
        )
        await db_session.flush()

        await engine.discover_cold_types(a, b)
        assert len(engine._cold_cache) == 1

        engine.clear_cache()
        assert len(engine._cold_cache) == 0

        # Next call should recompute and repopulate
        results = await engine.discover_cold_types(a, b)
        assert len(results) > 0
        assert len(engine._cold_cache) == 1

    @pytest.mark.asyncio
    async def test_cold_cache_lru_eviction(self, db_session):
        """Cache should evict LRU entry when maxsize exceeded."""
        from promiselink.services.association_discovery import _COLD_CACHE_MAXSIZE

        engine = AssociationDiscoveryEngine(db_session)

        # Stub all discoverers to avoid DB dependency for this logic test
        async def _stub(ea, eb):
            return 0.0, {}
        for t in list(engine.cold_discoverers.keys()):
            engine.cold_discoverers[t] = _stub

        # Pre-fill cache to maxsize with dummy entries
        for i in range(_COLD_CACHE_MAXSIZE):
            engine._cold_cache[(f"old-{i:03d}", f"old-{i:03d}-b")] = (0.0, [])
        assert len(engine._cold_cache) == _COLD_CACHE_MAXSIZE

        # New call should evict the oldest (first inserted) entry
        a = Entity(
            id="new-a", user_id="u1", entity_type="person",
            name="A", canonical_name="A", source_event_id="evt", status="confirmed",
        )
        b = Entity(
            id="new-b", user_id="u1", entity_type="person",
            name="B", canonical_name="B", source_event_id="evt", status="confirmed",
        )
        await engine.discover_cold_types(a, b)

        # Size stays at maxsize (one evicted, one added)
        assert len(engine._cold_cache) == _COLD_CACHE_MAXSIZE
        # Oldest entry evicted
        assert ("old-000", "old-000-b") not in engine._cold_cache
        # New entry present
        new_key = tuple(sorted(["new-a", "new-b"]))
        assert new_key in engine._cold_cache
