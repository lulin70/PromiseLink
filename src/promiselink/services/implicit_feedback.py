"""ImplicitFeedbackCollector — Track todo completion order as implicit feedback.

Implements F-52: Implicit feedback learning from todo completion patterns.
PoC scope: Record completed_rank only; weight adjustment deferred to Phase 1.

Design reference: Algorithm_Design_v1.md v2.5 §2.11
"""

from datetime import datetime, timezone

from sqlalchemy import select, func

from promiselink.core.logging import get_logger
from promiselink.models.todo import Todo

logger = get_logger("promiselink.implicit_feedback")


class ImplicitFeedbackCollector:
    """Collect implicit feedback from todo completion order.

    PoC scope:
    - When a todo is marked as done, record its completed_rank
    - completed_rank = (number of already-done todos for this user) + 1
    - This data feeds Phase 1 weight adjustment algorithms

    Phase 1 scope (deferred):
    - Adjust importance weights based on completion patterns
    - Long-press to downweight (explicit negative feedback)
    """

    async def record_completion(self, todo: Todo, session) -> int:
        """Record the completion rank for a todo.

        Args:
            todo: The Todo being marked as done
            session: AsyncSession

        Returns:
            The assigned completed_rank
        """
        # Count existing completed todos for this user
        result = await session.execute(
            select(func.count(Todo.id)).where(
                Todo.user_id == todo.user_id,
                Todo.status == "done",
                Todo.completed_rank.isnot(None),
            )
        )
        existing_count = result.scalar() or 0

        rank = existing_count + 1
        todo.completed_rank = rank

        logger.info(
            "implicit_feedback_recorded",
            todo_id=str(todo.id),
            completed_rank=rank,
            todo_type=todo.todo_type,
            user_id=str(todo.user_id),
        )

        return rank

    async def get_completion_stats(self, user_id: str, session) -> dict:
        """Get completion statistics for a user.

        Args:
            user_id: User ID
            session: AsyncSession

        Returns:
            Dict with completion stats by todo_type
        """
        result = await session.execute(
            select(
                Todo.todo_type,
                func.count(Todo.id).label("count"),
                func.avg(Todo.dynamic_score).label("avg_score"),
            )
            .where(
                Todo.user_id == user_id,
                Todo.status == "done",
                Todo.completed_rank.isnot(None),
            )
            .group_by(Todo.todo_type)
        )

        stats = {}
        for row in result:
            stats[row.todo_type] = {
                "completed_count": row.count,
                "avg_dynamic_score": round(row.avg_score, 4) if row.avg_score else None,
            }

        return stats
