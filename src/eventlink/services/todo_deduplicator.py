"""Todo Deduplicator Service — F-46: Deduplicate generated todos to reduce noise.

Rules (PRD v4.4 F-46 + Algorithm_Design §4.9):
1. Per-event cap: max MAX_TODOS_PER_EVENT todos per source_event_id
2. Similarity dedup: new todo vs existing todo (same user) title similarity > SIMILARITY_THRESHOLD → duplicate
3. Priority retention: when duplicate, keep higher priority (lower number)
4. Merge strategy: merge evidence_quote, keep more detailed description
"""

import re
import uuid
from dataclasses import dataclass, field

from eventlink.models.todo import Todo


@dataclass
class DeduplicationResult:
    """Result of todo deduplication."""

    todos: list[Todo]
    original_count: int
    removed_count: int
    duplicates: list[dict]  # [{removed_todo, kept_todo, similarity}]
    pending_deletions: list[uuid.UUID] = field(default_factory=list)  # IDs of persisted todos to delete from DB


class TodoDeduplicator:
    """F-46: Deduplicate generated todos to reduce noise.

    Applies three layers of deduplication:
    1. Per-event cap: limit to MAX_TODOS_PER_EVENT per source_event
    2. Similarity check: against existing_todos (same user)
    3. Within-batch dedup: among the new todos themselves
    """

    # Same event max todo count
    MAX_TODOS_PER_EVENT = 3

    # Similarity threshold
    SIMILARITY_THRESHOLD = 0.6

    def __init__(self) -> None: ...

    def deduplicate(
        self,
        todos: list[Todo],
        user_id: str,
        existing_todos: list[Todo] | None = None,
    ) -> DeduplicationResult:
        """Apply all deduplication rules.

        Steps:
        1. Per-event cap: limit to MAX_TODOS_PER_EVENT per source_event
        2. Similarity check: against existing_todos (same user)
        3. Within-batch dedup: among the new todos themselves
        4. Sort by priority and return

        Args:
            todos: Newly generated Todo list to deduplicate.
            user_id: Owner user ID (for logging context).
            existing_todos: Existing todos for this user (for similarity check).

        Returns:
            DeduplicationResult with deduplicated todos and metadata.
        """
        original_count = len(todos)
        if original_count == 0:
            return DeduplicationResult(
                todos=[],
                original_count=0,
                removed_count=0,
                duplicates=[],
                pending_deletions=[],
            )

        all_duplicates: list[dict] = []
        pending_deletions: list[uuid.UUID] = []

        # Step 1: Per-event cap
        todos, removed_cap = self._apply_per_event_cap(todos)
        for r in removed_cap:
            all_duplicates.append({
                "removed_todo": r,
                "kept_todo": None,
                "reason": "per_event_cap",
            })
            if r.id is not None:
                pending_deletions.append(r.id)

        # Step 2: Similarity check against existing todos
        if existing_todos:
            todos, dup_info = self._apply_similarity_dedup(todos, existing_todos)
            all_duplicates.extend(dup_info)
            for d in dup_info:
                removed_todo = d.get("removed_todo")
                if removed_todo is not None and removed_todo.id is not None:
                    pending_deletions.append(removed_todo.id)

        # Step 3: Within-batch similarity dedup
        todos, within_dup_info = self._within_batch_dedup(todos)
        all_duplicates.extend(within_dup_info)
        for d in within_dup_info:
            removed_todo = d.get("removed_todo")
            if removed_todo is not None and removed_todo.id is not None:
                pending_deletions.append(removed_todo.id)

        # Step 4: Sort by priority (ascending: 1=highest first)
        todos.sort(key=lambda t: t.priority)

        return DeduplicationResult(
            todos=todos,
            original_count=original_count,
            removed_count=original_count - len(todos),
            duplicates=all_duplicates,
            pending_deletions=pending_deletions,
        )

    def _apply_per_event_cap(self, todos: list[Todo]) -> tuple[list[Todo], list[Todo]]:
        """Rule 1: Limit todos per event to MAX_TODOS_PER_EVENT.

        Keeps highest priority (lowest number) todos.
        Returns (kept, removed).
        """
        from collections import defaultdict

        by_event: dict[str, list[Todo]] = defaultdict(list)
        for t in todos:
            key = str(t.source_event_id)
            by_event[key].append(t)

        kept: list[Todo] = []
        removed: list[Todo] = []

        for event_id, event_todos in by_event.items():
            # Sort by priority ascending (highest priority first)
            event_todos.sort(key=lambda t: t.priority)
            kept.extend(event_todos[: self.MAX_TODOS_PER_EVENT])
            removed.extend(event_todos[self.MAX_TODOS_PER_EVENT :])

        return kept, removed

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute text similarity using simple token overlap ratio.

        Uses character-level Jaccard-like similarity on normalized text:
        1. Lowercase both texts
        2. Extract Chinese characters + alphanumeric tokens
        3. Compute intersection/union ratio

        This is intentionally simple (no external NLP lib needed).
        For PoC this gives reasonable results; can upgrade to embedding similarity later.
        """
        tokens_a = self._normalize_text(text_a)
        tokens_b = self._normalize_text(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) if union else 0.0

    def _apply_similarity_dedup(
        self,
        new_todos: list[Todo],
        existing_todos: list[Todo],
    ) -> tuple[list[Todo], list[dict]]:
        """Rule 2+3: Remove new todos similar to existing or each other.

        Returns (kept, duplicates_info).
        """
        kept: list[Todo] = []
        duplicates_info: list[dict] = []

        for new_todo in new_todos:
            is_duplicate = False
            best_match_existing = None
            best_similarity = 0.0

            for existing in existing_todos:
                sim = self._compute_similarity(new_todo.title, existing.title)
                if sim > self.SIMILARITY_THRESHOLD and sim > best_similarity:
                    best_similarity = sim
                    best_match_existing = existing

            if best_match_existing is not None:
                # Priority-based selection
                if new_todo.priority <= best_match_existing.priority:
                    # New one is more important or equal: keep new, record but don't remove existing
                    # (we only filter new_todos, not modify existing_todos)
                    pass  # Keep the new todo
                else:
                    # Existing is more important: skip the new one
                    is_duplicate = True
                    duplicates_info.append({
                        "removed_todo": new_todo,
                        "kept_todo": best_match_existing,
                        "similarity": round(best_similarity, 4),
                    })

            if not is_duplicate:
                kept.append(new_todo)

        return kept, duplicates_info

    def _within_batch_dedup(self, todos: list[Todo]) -> tuple[list[Todo], list[dict]]:
        """Deduplicate among todos within the same batch.

        Greedy approach: sort by priority ascending, then iterate.
        For each todo, check if any already-kept todo is similar.
        If similar, skip (the kept one has higher or equal priority).
        """
        if len(todos) <= 1:
            return list(todos), []

        # Sort by priority ascending (highest priority first) for deterministic results
        sorted_todos = sorted(todos, key=lambda t: t.priority)

        kept: list[Todo] = []
        duplicates_info: list[dict] = []

        for candidate in sorted_todos:
            is_duplicate = False
            for existing_kept in kept:
                sim = self._compute_similarity(candidate.title, existing_kept.title)
                if sim > self.SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    duplicates_info.append({
                        "removed_todo": candidate,
                        "kept_todo": existing_kept,
                        "similarity": round(sim, 4),
                    })
                    break  # Found a match, no need to check other kept items

            if not is_duplicate:
                kept.append(candidate)

        return kept, duplicates_info

    @staticmethod
    def _normalize_text(text: str) -> set[str]:
        """Normalize text for comparison: extract tokens.

        Extract meaningful tokens: Chinese chars (\\u4e00-\\u9fff) + alphanumeric words (min 2 chars).
        """
        # Chinese characters
        chinese = set(re.findall(r"[\u4e00-\u9fff]", text.lower()))
        # Alphanumeric words (min 2 chars)
        alpha = set(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
        return chinese | alpha
