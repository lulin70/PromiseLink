"""W5 cross-language operation service.

Server-side candidate generation, candidate digest, and the operation state
machine backed by EntityCorrection rows (shared operation/audit fact source,
see TECH_DESIGN_跨语言实体关联_W5_v1 §3.1.2 / §7 / §8).

Security contract enforced here:
- Candidate generation is server-side only; clients can never widen the
  candidate set or supply scores/methods/resolver metadata as facts.
- Only the non-reversible token hash (SHA-256) and operation metadata are
  persisted — never the raw opaque token, never the HMAC secret.
- Operation claim is a compare-and-set transition (issued→pending) so the
  first successful confirm/reject decides the terminal state.
"""

from __future__ import annotations

import difflib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.config import get_settings
from promiselink.core.logging import get_logger
from promiselink.core.text_utils import redact_pii_from_text
from promiselink.database import IS_SQLITE
from promiselink.models.entity import Entity
from promiselink.models.entity_correction import EntityCorrection
from promiselink.models.todo import Todo
from promiselink.services.synonym_dict import find_aliases, load_synonyms

logger = get_logger("promiselink.w5_operation_service")

# Score bands (TECH_DESIGN §7/§8): >= confirm_score → 确认区, >= min_score → 模糊区.
ENTITY_CONFIRM_SCORE = 0.86
TODO_CONFIRM_SCORE = 0.88
W5_MIN_SCORE = 0.78

SYNONYM_MATCH_SCORE = 0.95

# Result summary contract (tests/w5/token_vectors.py): whitelisted keys only.
RESULT_SUMMARY_FIELDS = ("candidate_rank", "method", "score", "language_pair")


@dataclass(frozen=True)
class W5Candidate:
    """Sanitized candidate projection returned to clients."""

    candidate_id: str
    rank: int
    score: float
    method: str
    label: str
    language_pair: str
    confirm_only: bool = True


def _language_of(text: str) -> str:
    """Coarse script-based language tag: ja (kana) > zh (Han) > en (Latin)."""
    if any("\u3040" <= ch <= "\u30ff" for ch in text):
        return "ja"
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh" if han > 0 and han >= latin else "en"


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def compute_candidate_digest(
    scope_type: str,
    resource_id: str,
    candidate_ids: list[str],
) -> str:
    """Deterministic digest binding the ordered server-side candidate set."""
    import hashlib

    canonical = json.dumps(
        {
            "scope_type": scope_type,
            "resource_id": resource_id,
            "candidate_ids": list(candidate_ids),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _language_pair(source_name: str, candidate_name: str) -> str:
    return f"{_language_of(source_name)}_{_language_of(candidate_name)}"


async def generate_entity_candidates(
    session: AsyncSession,
    *,
    user_id: str,
    extracted_entity: Entity,
    limit: int = 10,
    include_ambiguous: bool = True,
) -> list[W5Candidate]:
    """Generate entity merge candidates for an extracted entity.

    Deterministic ordering: score desc, then candidate_id asc, so the same
    database state always reproduces the same candidate set (and digest).
    """
    settings = get_settings()
    dictionaries = load_synonyms()
    source_name = extracted_entity.name
    confirm_score = ENTITY_CONFIRM_SCORE

    result = await session.execute(
        select(Entity).where(
            Entity.user_id == user_id,
            Entity.id != extracted_entity.id,
            Entity.status != "deleted",
        )
    )
    pool = result.scalars().all()

    scored: list[tuple[float, str, str]] = []  # (score, method, candidate_id)
    labels: dict[str, str] = {}
    pairs: dict[str, str] = {}
    for candidate in pool:
        candidate_name = candidate.name
        aliases = find_aliases(source_name, "person", dictionaries) or find_aliases(
            source_name, "company", dictionaries
        )
        if candidate_name in aliases and candidate_name != source_name:
            scored.append((SYNONYM_MATCH_SCORE, "synonym_match", str(candidate.id)))
        else:
            ratio = difflib.SequenceMatcher(
                None, _normalize(source_name), _normalize(candidate_name)
            ).ratio()
            if ratio >= W5_MIN_SCORE:
                scored.append((round(ratio, 4), "difflib_match", str(candidate.id)))
            else:
                continue
        labels[str(candidate.id)] = candidate_name
        pairs[str(candidate.id)] = _language_pair(source_name, candidate_name)

    scored.sort(key=lambda item: (-item[0], item[2]))
    threshold = W5_MIN_SCORE if include_ambiguous else confirm_score
    candidates: list[W5Candidate] = []
    for rank, (score, method, candidate_id) in enumerate(scored, start=1):
        if score < threshold:
            break
        candidates.append(
            W5Candidate(
                candidate_id=candidate_id,
                rank=rank,
                score=score,
                method=method,
                label=labels[candidate_id],
                language_pair=pairs[candidate_id],
            )
        )
        if len(candidates) >= min(limit, settings.cross_language_embedding_candidate_limit):
            break
    return candidates


async def generate_todo_candidates(
    session: AsyncSession,
    *,
    user_id: str,
    source_todo: Todo,
    limit: int = 10,
    include_ambiguous: bool = True,
) -> list[W5Candidate]:
    """Generate todo association candidates for a source todo."""
    settings = get_settings()
    source_title = source_todo.title

    result = await session.execute(
        select(Todo).where(
            Todo.user_id == user_id,
            Todo.id != source_todo.id,
            Todo.status.in_(("pending", "in_progress")),
        )
    )
    pool = result.scalars().all()

    scored: list[tuple[float, str, str]] = []
    labels: dict[str, str] = {}
    pairs: dict[str, str] = {}
    for candidate in pool:
        candidate_title = candidate.title
        if _normalize(source_title) == _normalize(candidate_title):
            scored.append((SYNONYM_MATCH_SCORE, "synonym_match", str(candidate.id)))
        else:
            ratio = difflib.SequenceMatcher(
                None, _normalize(source_title), _normalize(candidate_title)
            ).ratio()
            if ratio >= W5_MIN_SCORE:
                scored.append((round(ratio, 4), "difflib_match", str(candidate.id)))
            else:
                continue
        labels[str(candidate.id)] = candidate_title
        pairs[str(candidate.id)] = _language_pair(source_title, candidate_title)

    scored.sort(key=lambda item: (-item[0], item[2]))
    threshold = W5_MIN_SCORE if include_ambiguous else TODO_CONFIRM_SCORE
    candidates: list[W5Candidate] = []
    for rank, (score, method, candidate_id) in enumerate(scored, start=1):
        if score < threshold:
            break
        candidates.append(
            W5Candidate(
                candidate_id=candidate_id,
                rank=rank,
                score=score,
                method=method,
                label=labels[candidate_id],
                language_pair=pairs[candidate_id],
            )
        )
        if len(candidates) >= min(limit, settings.cross_language_embedding_candidate_limit):
            break
    return candidates


def _uid(value: str | uuid.UUID) -> uuid.UUID | str:
    if IS_SQLITE:
        return str(value)
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def build_result_summary(candidate: W5Candidate | None) -> dict[str, Any]:
    """Whitelisted, non-PII result summary for a completed operation."""
    if candidate is None:
        # Rejections carry the top-ranked candidate context when available;
        # with no candidates the summary still satisfies the 4-field contract.
        return {
            "candidate_rank": 0,
            "method": "synonym_match",
            "score": 0.0,
            "language_pair": "zh_zh",
        }
    return {
        "candidate_rank": candidate.rank,
        "method": candidate.method,
        "score": candidate.score,
        "language_pair": candidate.language_pair,
    }


async def create_issued_operation(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    scope_type: str,
    resource_id: str,
    candidate_ids: list[str],
    candidate_digest: str,
    token: str,
    token_payload: dict[str, Any],
) -> EntityCorrection:
    """Persist operation metadata for a freshly issued candidate token.

    Only the token hash plus resolver/score/space metadata are stored; the raw
    opaque token and the HMAC secret are never persisted.
    """
    from promiselink.core.auth import candidate_token_hash

    def _ts(value: Any) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC)

    now = datetime.now(UTC)
    row = EntityCorrection(
        id=_uid(str(uuid.uuid4())),
        user_id=_uid(user_id),
        event_id=_uid(event_id),
        correction_type="entity" if scope_type == "entity" else "todo",
        # Placeholder until the user's confirm/reject overwrites it.
        action="issued",
        scope_type=scope_type,
        entity_id=_uid(resource_id) if scope_type == "entity" else None,
        source_todo_id=_uid(resource_id) if scope_type == "todo" else None,
        candidate_entity_ids=candidate_ids if scope_type == "entity" else None,
        candidate_todo_ids=candidate_ids if scope_type == "todo" else None,
        candidate_digest=candidate_digest,
        operation_key=str(token_payload["operation_key"]),
        token_hash=candidate_token_hash(token),
        token_key_version=str(token_payload["key_version"]),
        resolver_version=str(token_payload["resolver_version"]),
        score_version=str(token_payload["score_version"]),
        embedding_space=str(token_payload["embedding_space"]),
        token_issued_at=_ts(token_payload["issued_at"]),
        token_expires_at=_ts(token_payload["expires_at"]),
        operation_status="issued",
        created_at=now,
    )
    session.add(row)
    logger.info(
        "w5_operation_issued",
        scope_type=scope_type,
        event_id=event_id,
        operation_key=row.operation_key,
        candidate_count=len(candidate_ids),
    )
    return row


async def find_operation_by_token_hash(
    session: AsyncSession,
    *,
    token_hash: str,
) -> EntityCorrection | None:
    result = await session.execute(
        select(EntityCorrection).where(EntityCorrection.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def claim_operation(session: AsyncSession, operation: EntityCorrection) -> str:
    """Compare-and-set claim: issued→pending.

    Returns one of:
    - "claimed"          → caller owns the operation and may mutate.
    - "confirmed"/"rejected" → terminal replay (return persisted result).
    - "in_progress"      → another request holds the claim (HTTP 409).
    - "expired"          → operation expired/superseded (HTTP 410).
    """
    if operation.operation_status in ("confirmed", "rejected", "expired"):
        return operation.operation_status
    result = await session.execute(
        update(EntityCorrection)
        .where(
            EntityCorrection.id == operation.id,
            EntityCorrection.operation_status == "issued",
        )
        .values(operation_status="pending")
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        operation.operation_status = "pending"
        # W5 Anti-ghost hook: real CAS state machine reached via the
        # production issue→pending transition.
        try:  # never let observability break the production path
            from promiselink.core.activation import record as _record_w5
            _record_w5("operation_state_machine")
        except Exception:
            pass
        return "claimed"
    await session.refresh(operation)
    status = operation.operation_status
    if status in ("confirmed", "rejected", "expired"):
        return status
    return "in_progress"


def complete_operation(
    operation: EntityCorrection,
    *,
    status: str,
    action: str,
    result_summary: dict[str, Any],
    selected_entity_id: str | None = None,
    selected_todo_id: str | None = None,
    original_canonical_name: str | None = None,
    original_extracted_text: str | None = None,
) -> None:
    """Close an operation row in-place (operation row becomes the audit row)."""
    operation.operation_status = status
    operation.action = action
    operation.result_summary = {
        field: result_summary[field]
        for field in RESULT_SUMMARY_FIELDS
        if field in result_summary
    }
    operation.completed_at = datetime.now(UTC)
    if selected_entity_id is not None:
        operation.selected_entity_id = _uid(selected_entity_id)
    if selected_todo_id is not None:
        operation.selected_todo_id = _uid(selected_todo_id)
    if original_canonical_name is not None:
        operation.original_canonical_name = original_canonical_name[:200]
    if original_extracted_text is not None:
        operation.original_extracted_text = redact_pii_from_text(original_extracted_text) or None
