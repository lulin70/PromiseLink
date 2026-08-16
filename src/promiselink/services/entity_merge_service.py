"""Entity merge service — manual duplicate-customer handling.

Implements the design in docs/design/Duplicate_Entity_Manual_Handling_2026-08-16.md:

- merge_entities(): entity-to-entity merge with reference migration
  (todos / associations / vector_embeddings), source tombstoned as merged
- confirm_entity(): provisional → confirmed
- find_duplicate_groups(): same-name active entity groups

Differs from EntityResolutionEngine.merge_entity (which merges fresh
extraction data into an existing entity): this service merges two
ALREADY-PERSISTED entities and migrates every row that references them.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.crypto import encrypt_pii_in_properties
from promiselink.core.exceptions import ConflictError, NotFoundError, ValidationError
from promiselink.core.logging import get_logger
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo

logger = get_logger("promiselink.services.entity_merge")

ACTIVE_STATUSES = ("provisional", "confirmed")


@dataclass
class MergeResult:
    """Outcome of an entity-to-entity merge."""

    target: Entity
    migrated_todos: int = 0
    migrated_associations: int = 0
    merged_association_conflicts: int = 0
    migrated_embeddings: int = 0
    details: dict[str, Any] = field(default_factory=dict)


async def _get_active_entity(
    session: AsyncSession, entity_id: str, user_id: str
) -> Entity:
    """Fetch an entity owned by user; 404 if missing, 409 if not active."""
    result = await session.execute(
        select(Entity).where(Entity.id == entity_id, Entity.user_id == user_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError("Entity not found")
    if entity.status not in ACTIVE_STATUSES:
        props = entity.properties or {}
        raise ConflictError(
            message=f"Entity status is '{entity.status}' (not mergeable)",
            details={
                "status": entity.status,
                "merged_into": props.get("merged_into"),
            },
        )
    return entity


async def merge_entities(
    session: AsyncSession,
    user_id: str,
    target_id: str,
    source_id: str,
) -> MergeResult:
    """Merge source entity into target entity (target survives).

    Single-transaction semantics: the caller commits; on any exception the
    caller rolls back everything.

    Args:
        session: Database session (caller owns transaction).
        user_id: Owner scope (safety filter).
        target_id: Entity to keep.
        source_id: Entity to merge away (tombstoned as 'merged').

    Returns:
        MergeResult with migration counts.

    Raises:
        ValidationError: source == target.
        NotFoundError: either entity missing (or wrong owner).
        ConflictError: either entity already merged/deleted.
    """
    if target_id == source_id:
        raise ValidationError("Cannot merge an entity into itself")

    target = await _get_active_entity(session, target_id, user_id)
    source = await _get_active_entity(session, source_id, user_id)

    # ── 1. Property merge (target-priority deep merge) ──
    # NOTE: deliberately NOT reusing EntityResolutionEngine.merge_entity here —
    # its semantics are "new values override old" (fresh extraction is more
    # trustworthy in the pipeline). Manual merge is the opposite: the KEPT
    # profile (target) wins conflicts; source only fills gaps (AC2.3).
    target_props = dict(target.properties or {})
    source_props = dict(source.properties or {})

    if source_props:
        merge_history = list(target_props.get("merge_history", []))
        merge_history.append({
            "merged_at": datetime.now(UTC).isoformat(),
            "merged_fields": list(source_props.keys()),
            "merged_from_entity_id": source_id,
        })
        target_props["merge_history"] = merge_history

        for key, value in source_props.items():
            if key == "merge_history":
                continue
            if value is None:
                continue
            if isinstance(value, dict) and isinstance(target_props.get(key), dict):
                # Deep merge nested dicts (basic/resource/…): target wins,
                # source fills missing/empty fields only.
                merged = dict(target_props[key])
                for sk, sv in value.items():
                    if sv is None or sv == "":
                        continue
                    if merged.get(sk) in (None, ""):
                        merged[sk] = sv
                target_props[key] = merged
            elif key not in target_props or target_props[key] in (None, "", {}, []):
                target_props[key] = value

        # Union of event_ids (source's history carries over)
        event_ids = list(target_props.get("event_ids", []))
        for eid in source_props.get("event_ids", []):
            if str(eid) not in event_ids:
                event_ids.append(str(eid))
        if str(source.source_event_id) not in event_ids:
            event_ids.append(str(source.source_event_id))
        target_props["event_ids"] = event_ids

        # 加密 PII 字段（幂等，内部检测 ENC: 前缀不重复加密）
        target.properties = encrypt_pii_in_properties(target_props)
        target.confidence = max(target.confidence, source.confidence)

    # Append source name to aliases if different
    if source.name and source.name != target.name:
        aliases = list(target.aliases or [])
        if source.name not in aliases and source.name != target.canonical_name:
            aliases.append(source.name)
            target.aliases = aliases

    # ── 2. Migrate todos ──
    todo_result = await session.execute(
        update(Todo)
        .where(Todo.user_id == user_id, Todo.related_entity_id == source_id)
        .values(related_entity_id=target_id)
    )
    migrated_todos = cast(CursorResult, todo_result).rowcount or 0

    # ── 3. Migrate associations ──
    migrated_assocs = 0
    merged_conflicts = 0

    # 3a. Direct source→target association: delete (self-association forbidden)
    await session.execute(
        delete(Association).where(
            Association.user_id == user_id,
            ((Association.source_entity_id == source_id) & (Association.target_entity_id == target_id))
            | ((Association.source_entity_id == target_id) & (Association.target_entity_id == source_id)),
        )
    )

    # 3b. Migrate associations where source is either endpoint
    assoc_result = await session.execute(
        select(Association).where(
            Association.user_id == user_id,
            (Association.source_entity_id == source_id)
            | (Association.target_entity_id == source_id),
        )
    )
    source_assocs = list(assoc_result.scalars().all())

    # Existing associations of target for conflict detection
    target_assoc_result = await session.execute(
        select(Association).where(
            Association.user_id == user_id,
            (Association.source_entity_id == target_id)
            | (Association.target_entity_id == target_id),
        )
    )
    target_assoc_index: dict[tuple[str, str, str], Association] = {}
    for ta in target_assoc_result.scalars().all():
        ta_pair = sorted((str(ta.source_entity_id), str(ta.target_entity_id)))
        ta_key = (ta_pair[0], ta_pair[1], ta.association_type)
        target_assoc_index[ta_key] = ta

    for sa in source_assocs:
        new_source = target_id if str(sa.source_entity_id) == source_id else str(sa.source_entity_id)
        new_target_val = target_id if str(sa.target_entity_id) == source_id else str(sa.target_entity_id)
        sa_pair = sorted((new_source, new_target_val))
        sa_key = (sa_pair[0], sa_pair[1], sa.association_type)
        existing = target_assoc_index.get(sa_key)

        if existing is not None and existing.id != sa.id:
            # Conflict: merge rows — keep existing, absorb strength/confidence
            existing.strength = max(existing.strength or 0.0, sa.strength or 0.0)
            existing.confidence = max(existing.confidence or 0.0, sa.confidence or 0.0)
            await session.delete(sa)
            merged_conflicts += 1
        else:
            # SQLite maps UUID columns to String(36) — bind plain str, not UUID
            sa.source_entity_id = new_source  # type: ignore[assignment]
            sa.target_entity_id = new_target_val  # type: ignore[assignment]
            target_assoc_index[sa_key] = sa
            migrated_assocs += 1

    # ── 4. Migrate vector embeddings ──
    # Note: vector_embeddings lives in the semantic-search SQLite file (created
    # by SemanticSearchService via CREATE TABLE IF NOT EXISTS), NOT in the main
    # SQLAlchemy metadata. When the table is absent (fresh install / tests),
    # skip migration instead of failing the whole merge transaction.
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    migrated_embeddings = 0
    try:
        emb_exists = await session.execute(
            text("SELECT 1 FROM vector_embeddings WHERE target_type='entity' AND target_id=:tid"),
            {"tid": target_id},
        )
        if emb_exists.first():
            # Target already embedded — drop source's (avoids UNIQUE conflict)
            del_result = await session.execute(
                text("DELETE FROM vector_embeddings WHERE target_type='entity' AND target_id=:sid"),
                {"sid": source_id},
            )
            del_rowcount = cast(CursorResult, del_result).rowcount or 0
            migrated_embeddings = 0 if del_rowcount == 0 else -del_rowcount
        else:
            upd_result = await session.execute(
                text("UPDATE vector_embeddings SET target_id=:tid WHERE target_type='entity' AND target_id=:sid"),
                {"tid": target_id, "sid": source_id},
            )
            migrated_embeddings = cast(CursorResult, upd_result).rowcount or 0
    except OperationalError as e:
        logger.info(
            "entity_merge_embeddings_skipped",
            reason="vector_embeddings table not present",
            error=str(e),
        )

    # ── 5. Tombstone source ──
    source.status = "merged"
    source_props = dict(source.properties or {})
    source_props["merged_into"] = target_id
    source_props["merged_at"] = datetime.now(UTC).isoformat()
    source_props["merged_reason"] = "manual"
    source.properties = source_props

    logger.info(
        "entity_manual_merged",
        user_id=user_id,
        target_id=target_id,
        source_id=source_id,
        migrated_todos=migrated_todos,
        migrated_associations=migrated_assocs,
        merged_association_conflicts=merged_conflicts,
        migrated_embeddings=migrated_embeddings,
    )

    return MergeResult(
        target=target,
        migrated_todos=migrated_todos,
        migrated_associations=migrated_assocs,
        merged_association_conflicts=merged_conflicts,
        migrated_embeddings=migrated_embeddings,
    )


async def confirm_entity(session: AsyncSession, user_id: str, entity_id: str) -> Entity:
    """Confirm a provisional entity (status → confirmed). Idempotent guard:
    only provisional entities can be confirmed.

    Raises:
        NotFoundError / ConflictError (non-provisional status).
    """
    entity = await _get_active_entity(session, entity_id, user_id)
    if entity.status != "provisional":
        raise ConflictError(
            message=f"Entity status is '{entity.status}', only provisional entities can be confirmed",
            details={"status": entity.status},
        )
    entity.status = "confirmed"
    logger.info("entity_confirmed", user_id=user_id, entity_id=entity_id)
    return entity


async def find_duplicate_groups(
    session: AsyncSession, user_id: str
) -> list[dict[str, Any]]:
    """Find same-name active entity groups (>= 2 members).

    Returns:
        List of groups: {"name", "entities": [{id, company, title, status}], "hint"}.
    """
    result = await session.execute(
        select(Entity)
        .where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
            Entity.status.not_in(("merged", "deleted")),
        )
        .order_by(Entity.name, Entity.created_at)
    )
    entities = result.scalars().all()

    groups: dict[str, list[Entity]] = {}
    for e in entities:
        groups.setdefault(e.name, []).append(e)

    duplicates = []
    for name, members in groups.items():
        if len(members) < 2:
            continue
        duplicates.append({
            "name": name,
            "hint": "同名",
            "entities": [
                {
                    "id": str(m.id),
                    "name": m.name,
                    "company": ((m.properties or {}).get("basic") or {}).get("company"),
                    "title": ((m.properties or {}).get("basic") or {}).get("title"),
                    "status": m.status,
                }
                for m in members
            ],
        })
    return duplicates
