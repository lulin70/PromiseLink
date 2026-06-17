"""Tests for Todo Deduplicator — F-46: Todo deduplication service."""

import uuid

from promiselink.models.todo import Todo
from promiselink.services.todo_deduplicator import (
    DeduplicationResult,
    TodoDeduplicator,
)
from tests.conftest import make_user_id

# ── Helpers ──


def _make_todo(
    title: str = "测试Todo",
    priority: int = 3,
    source_event_id: str | None = None,
    user_id: str | None = None,
    description: str | None = None,
) -> Todo:
    """Create a Todo instance for testing (SQLite-compatible string IDs)."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=user_id or make_user_id(),
        todo_type="promise",
        title=title,
        description=description,
        priority=priority,
        status="pending",
        source_event_id=source_event_id or str(uuid.uuid4()),
    )


def _make_todos_same_event_distinct(
    count: int,
    priorities: list[int] | None = None,
    event_id: str | None = None,
) -> list[Todo]:
    """Create multiple todos with same event_id but DISTINCT titles (low inter-similarity).

    Uses semantically different titles to avoid triggering within-batch similarity dedup.
    """
    eid = event_id or str(uuid.uuid4())
    prios = priorities or list(range(1, count + 1))
    # Distinct titles with minimal Chinese character overlap
    distinct_titles = [
        "发送项目资料给合作方",
        "安排下周团队建设活动",
        "准备季度汇报PPT",
        "更新客户联系信息",
        "审核合同条款细节",
        "确认会议室预订状态",
    ]
    return [
        _make_todo(
            title=distinct_titles[i],
            priority=prios[i],
            source_event_id=eid,
        )
        for i in range(count)
    ]


# ── Test 1: Per-event cap — 4 todos → keep top 3 priority ──


class TestPerEventCap:
    """Test Rule 1: Limit todos per event to MAX_TODOS_PER_EVENT (3)."""

    def test_four_todos_same_event_keeps_three(self):
        """同事件4条todo→只保留最高优先级的3条."""
        dedup = TodoDeduplicator()
        # priorities: 1,2,3,4 → should keep 1,2,3 (drop 4)
        todos = _make_todos_same_event_distinct(4, priorities=[1, 2, 3, 4])
        result = dedup.deduplicate(todos, user_id="user-1")

        assert isinstance(result, DeduplicationResult)
        assert result.original_count == 4
        assert len(result.todos) == 3
        assert result.removed_count == 1
        kept_priorities = sorted([t.priority for t in result.todos])
        assert kept_priorities == [1, 2, 3]

    def test_two_todos_same_event_all_kept(self):
        """同事件2条todo→全部保留(不超过上限)."""
        dedup = TodoDeduplicator()
        todos = _make_todos_same_event_distinct(2)
        result = dedup.deduplicate(todos, user_id="user-1")

        assert result.original_count == 2
        assert len(result.todos) == 2
        assert result.removed_count == 0


# ── Test 3 & 4: Similarity with existing todos ──


class TestSimilarityWithExisting:
    """Test Rule 2: Similarity check against existing todos."""

    def test_high_similarity_new_todo_removed(self):
        """与已有todo高度相似(>0.6)的新todo被移除."""
        dedup = TodoDeduplicator()

        existing = [_make_todo(title="发送AI项目资料给李总", priority=1)]
        new_todo = _make_todo(title="发送AI项目资料给李总", priority=5)

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        assert len(result.todos) == 0
        assert result.removed_count == 1
        assert len(result.duplicates) >= 1

    def test_low_similarity_new_todo_kept(self):
        """与已有todo低相似度(<0.6)的新todo保留."""
        dedup = TodoDeduplicator()

        existing = [_make_todo(title="发送AI项目资料给李总", priority=1)]
        new_todo = _make_todo(title="安排下周团队建设活动", priority=3)

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        assert len(result.todos) == 1
        assert result.removed_count == 0

    def test_existing_todos_none_no_error(self):
        """existing_todos=None时不报错(跳过历史查重)."""
        dedup = TodoDeduplicator()
        todos = [_make_todo(title="新任务")]
        result = dedup.deduplicate(todos, user_id="user-1", existing_todos=None)

        assert len(result.todos) == 1
        assert result.removed_count == 0


# ── Test 5: Within-batch dedup ──


class TestWithinBatchDedup:
    """Test within-batch similarity deduplication."""

    def test_similar_batch_todos_keep_higher_priority(self):
        """新批次内两条互相相似的todo→保留高优先级."""
        dedup = TodoDeduplicator()

        todos = [
            _make_todo(title="发送AI资料给李总", priority=1),
            _make_todo(title="发送AI项目资料给李总", priority=3, source_event_id=str(uuid.uuid4())),
        ]

        result = dedup.deduplicate(todos, user_id="user-1")

        assert len(result.todos) == 1
        assert result.todos[0].priority == 1
        assert result.removed_count == 1


# ── Test 6: Empty input ──


class TestEmptyInput:
    """Test edge cases with empty input."""

    def test_empty_list_returns_empty(self):
        """空列表输入→空输出."""
        dedup = TodoDeduplicator()
        result = dedup.deduplicate([], user_id="user-1")

        assert result.todos == []
        assert result.original_count == 0
        assert result.removed_count == 0
        assert result.duplicates == []


# ── Test 7: All identical todos ──


class TestAllIdenticalTodos:
    """Test when all todos are identical."""

    def test_all_identical_keeps_one(self):
        """全部相同todo→只保留1条."""
        dedup = TodoDeduplicator()
        same_title = "发送AI项目资料给李总"

        todos = [
            _make_todo(title=same_title, priority=i, source_event_id=str(uuid.uuid4()))
            for i in range(1, 5)
        ]

        result = dedup.deduplicate(todos, user_id="user-1")

        assert len(result.todos) == 1
        assert result.removed_count == 3
        # Should keep highest priority (lowest number)
        assert result.todos[0].priority == 1


# ── Test 8 & 9: Similarity algorithm accuracy ──


class TestSimilarityAlgorithm:
    """Test text similarity computation accuracy."""

    def test_chinese_text_similarity(self):
        """中文字符相似度计算准确性."""
        dedup = TodoDeduplicator()

        # Same text → similarity = 1.0
        sim = dedup._compute_similarity("发送AI项目资料给李总", "发送AI项目资料给李总")
        assert sim == 1.0

        # Partial overlap → moderate similarity
        sim = dedup._compute_similarity("发送AI项目资料给李总", "发送AI报告给王总")
        assert 0.0 < sim < 1.0

        # Completely different → low similarity
        sim = dedup._compute_similarity("发送资料", "安排会议")
        assert sim < 0.5

    def test_mixed_chinese_english_similarity(self):
        """英文+中文混合文本相似度."""
        dedup = TodoDeduplicator()

        sim = dedup._compute_similarity(
            "发送AI project资料给李总",
            "发送AI project资料给李总",
        )
        assert sim > 0.8

        sim = dedup._compute_similarity(
            "发送AI project资料",
            "安排meeting讨论",
        )
        assert sim < 0.5

    def test_normalize_text_extracts_tokens(self):
        """_normalize_text correctly extracts Chinese chars and alphanumeric words."""
        tokens = TodoDeduplicator._normalize_text("发送AI Project资料给李总")
        # Should contain Chinese characters
        assert "发" in tokens
        assert "送" in tokens
        assert "李" in tokens
        # Should contain alphanumeric words (min 2 chars)
        assert "ai" in tokens
        assert "project" in tokens
        # Single char alphanumeric should NOT be included
        assert "a" not in tokens  # single 'a' from 'AI' is not min 2 chars

    def test_empty_text_similarity_zero(self):
        """Empty text returns zero similarity."""
        dedup = TodoDeduplicator()
        assert dedup._compute_similarity("", "") == 0.0
        assert dedup._compute_similarity("some text", "") == 0.0
        assert dedup._compute_similarity("", "some text") == 0.0


# ── Test 10: Priority sorting ──


class TestPrioritySorting:
    """Test that results are sorted by priority ascending."""

    def test_result_sorted_by_priority(self):
        """priority排序验证(返回结果按priority升序)."""
        dedup = TodoDeduplicator()

        distinct_titles = [
            " Alpha任务 Bravo方案 ",
            " Charlie数据Delta报告 ",
            " Echo系统Foxtrot检查 ",
            " Golf酒店India预约 ",
            " Juliet知识Kilo培训 ",
        ]
        todos = [
            _make_todo(title=distinct_titles[i], priority=p, source_event_id=str(uuid.uuid4()))
            for i, p in enumerate([5, 1, 3, 2, 4])
        ]

        result = dedup.deduplicate(todos, user_id="user-1")
        priorities = [t.priority for t in result.todos]
        assert priorities == sorted(priorities)


# ── Test 11: Duplicates info accuracy ──


class TestDuplicatesInfo:
    """Test that duplicates_info contains correct details."""

    def test_duplicates_info_contains_similarity_score(self):
        """duplicates_info包含正确的similarity分数."""
        dedup = TodoDeduplicator()

        existing = [_make_todo(title="发送AI项目资料给李总", priority=1)]
        new_todo = _make_todo(title="发送AI项目资料给李总", priority=5)

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        assert result.removed_count == 1
        assert len(result.duplicates) >= 1
        # Find the duplicate entry with similarity
        dup_with_sim = [d for d in result.duplicates if "similarity" in d]
        assert len(dup_with_sim) >= 1
        assert dup_with_sim[0]["similarity"] > 0.6
        assert dup_with_sim[0]["removed_todo"] is new_todo
        assert dup_with_sim[0]["kept_todo"] is existing[0]


# ── Test 12: Priority-based selection when similar to existing ──


class TestPriorityBasedSelection:
    """Test priority-based selection logic when similar to existing todos."""

    def test_new_higher_priority_kept_over_existing(self):
        """New todo with higher priority (lower number) is kept even when similar."""
        dedup = TodoDeduplicator()

        # Existing has lower priority (higher number)
        existing = [_make_todo(title="发送AI项目资料给李总", priority=5)]
        # New has higher priority (lower number)
        new_todo = _make_todo(title="发送AI项目资料给李总", priority=1)

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        # New should be KEPT because it has higher priority than existing
        assert len(result.todos) == 1
        assert result.removed_count == 0

    def test_new_lower_priority_removed_when_similar(self):
        """New todo with lower priority (higher number) is removed when similar."""
        dedup = TodoDeduplicator()

        # Existing has higher priority (lower number)
        existing = [_make_todo(title="发送AI项目资料给李总", priority=1)]
        # New has lower priority (higher number)
        new_todo = _make_todo(title="发送AI项目资料给李总", priority=5)

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        # New should be REMOVED because existing has higher priority
        assert len(result.todos) == 0
        assert result.removed_count == 1


# ── Additional edge case tests ──


class TestMultipleEventsCap:
    """Test per-event cap across multiple events."""

    def test_multiple_events_each_capped_independently(self):
        """Each event's todos are capped independently at MAX_TODOS_PER_EVENT."""
        dedup = TodoDeduplicator()

        event_a = str(uuid.uuid4())
        event_b = str(uuid.uuid4())

        # Event A: 4 todos (should be capped to 3)
        todos_a = [
            _make_todo(title="发送项目资料给合作方", priority=1, source_event_id=event_a),
            _make_todo(title="安排下周团队建设活动", priority=2, source_event_id=event_a),
            _make_todo(title="准备季度汇报PPT", priority=3, source_event_id=event_a),
            _make_todo(title="更新客户联系信息", priority=4, source_event_id=event_a),
        ]
        # Event B: 2 todos (all kept, use DIFFERENT titles from event A)
        todos_b = [
            _make_todo(title="审核合同条款细节", priority=1, source_event_id=event_b),
            _make_todo(title="确认会议室预订状态", priority=2, source_event_id=event_b),
        ]

        result = dedup.deduplicate(todos_a + todos_b, user_id="user-1")

        # Event A: 4 → 3, Event B: 2 → 2 (no cap applied), no cross-event similarity
        assert len(result.todos) == 5
        assert result.removed_count == 1

        # Verify correct events were capped
        event_a_todos = [t for t in result.todos if str(t.source_event_id) == event_a]
        event_b_todos = [t for t in result.todos if str(t.source_event_id) == event_b]
        assert len(event_a_todos) == 3
        assert len(event_b_todos) == 2


class TestDeduplicationResultDataclass:
    """Test DeduplicationResult dataclass structure."""

    def test_result_has_expected_fields(self):
        """DeduplicationResult has all expected fields."""
        dedup = TodoDeduplicator()
        todo = _make_todo()
        result = dedup.deduplicate([todo], user_id="user-1")

        assert hasattr(result, "todos")
        assert hasattr(result, "original_count")
        assert hasattr(result, "removed_count")
        assert hasattr(result, "duplicates")
        assert isinstance(result.todos, list)
        assert isinstance(result.original_count, int)
        assert isinstance(result.removed_count, int)
        assert isinstance(result.duplicates, list)


class TestMaxTodosPerEventConstant:
    """Test MAX_TODOS_PER_EVENT constant value."""

    def test_max_todos_per_event_is_three(self):
        """MAX_TODOS_PER_EVENT should be 3."""
        assert TodoDeduplicator.MAX_TODOS_PER_EVENT == 3

    def test_similarity_threshold_value(self):
        """SIMILARITY_THRESHOLD should be 0.6."""
        assert TodoDeduplicator.SIMILARITY_THRESHOLD == 0.6


# ── Test: pending_deletions (F-46b: DB-level deletion) ──


class TestPendingDeletions:
    """Test pending_deletions field for DB-level deletion support."""

    def test_pending_deletions_exists_on_result(self):
        """DeduplicationResult always has pending_deletions attribute."""
        dedup = TodoDeduplicator()
        todo = _make_todo()
        result = dedup.deduplicate([todo], user_id="user-1")

        assert hasattr(result, "pending_deletions")
        assert isinstance(result.pending_deletions, list)

    def test_empty_list_has_empty_pending_deletions(self):
        """Empty input → empty pending_deletions."""
        dedup = TodoDeduplicator()
        result = dedup.deduplicate([], user_id="user-1")

        assert result.pending_deletions == []
        assert len(result.pending_deletions) == 0

    def test_no_removals_has_empty_pending_deletions(self):
        """No todos removed → empty pending_deletions."""
        dedup = TodoDeduplicator()
        todos = _make_todos_same_event_distinct(2)
        result = dedup.deduplicate(todos, user_id="user-1")

        assert result.removed_count == 0
        assert result.pending_deletions == []

    def test_per_event_cap_collects_ids_with_persistent_todos(self):
        """per_event_cap removes todos with IDs → pending_deletions contains those IDs."""
        dedup = TodoDeduplicator()
        # 4 todos same event, priorities 1-4 → priority 4 gets capped
        todos = _make_todos_same_event_distinct(4, priorities=[1, 2, 3, 4])
        # All have IDs assigned by _make_todo
        removed_todo = todos[3]  # priority=4, will be capped
        removed_id = removed_todo.id

        result = dedup.deduplicate(todos, user_id="user-1")

        assert result.removed_count == 1
        assert len(result.pending_deletions) == 1
        assert removed_id in result.pending_deletions

    def test_similarity_dedup_collects_ids(self):
        """Similarity dedup removes todo with ID → pending_deletions contains that ID."""
        dedup = TodoDeduplicator()

        existing = [_make_todo(title="发送AI项目资料给李总", priority=1)]
        new_todo = _make_todo(title="发送AI项目资料给李总", priority=5)
        new_id = new_todo.id

        result = dedup.deduplicate([new_todo], user_id="user-1", existing_todos=existing)

        assert result.removed_count == 1
        assert len(result.pending_deletions) == 1
        assert new_id in result.pending_deletions

    def test_within_batch_dedup_collects_ids(self):
        """Within-batch dedup removes todo with ID → pending_deletions contains that ID."""
        dedup = TodoDeduplicator()

        todo_high = _make_todo(title="发送AI资料给李总", priority=1)
        todo_low = _make_todo(title="发送AI项目资料给李总", priority=3, source_event_id=str(uuid.uuid4()))
        low_id = todo_low.id

        result = dedup.deduplicate([todo_high, todo_low], user_id="user-1")

        assert result.removed_count == 1
        assert len(result.pending_deletions) == 1
        assert low_id in result.pending_deletions

    def test_multiple_removals_collect_all_ids(self):
        """Multiple removals across different rules → all IDs in pending_deletions."""
        dedup = TodoDeduplicator()

        # Same event, 5 distinct-title todos → cap removes 2 (priority 4 and 5)
        # Use titles with minimal token overlap to avoid triggering within-batch similarity
        event_id = str(uuid.uuid4())
        distinct_titles = [
            "发送项目资料给合作方",
            "安排下周团队建设活动",
            "准备季度汇报PPT",
            "更新客户联系信息",
            "审核合同条款细节",
        ]
        todos = [
            _make_todo(title=distinct_titles[i], priority=i + 1, source_event_id=event_id)
            for i in range(5)
        ]
        capped_ids = {todos[3].id, todos[4].id}  # priority 4, 5 get capped

        result = dedup.deduplicate(todos, user_id="user-1")

        assert result.removed_count == 2
        assert len(result.pending_deletions) == 2
        assert set(result.pending_deletions) == capped_ids
