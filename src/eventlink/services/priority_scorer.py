"""PriorityScorer — Dynamic priority scoring for Todos.

Implements F-51: Two-dimensional priority model (urgency + importance).
Score = 0.4 × urgency + 0.6 × importance

Design reference: Algorithm_Design_v1.md v2.5 §2.10
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from eventlink.core.logging import get_logger

logger = get_logger("eventlink.priority_scorer")

# ── Constants ──

# Importance weights by todo_type (0.0 ~ 1.0)
IMPORTANCE_WEIGHTS: dict[str, float] = {
    "promise": 0.9,
    "risk": 0.9,
    "help": 0.8,
    "cooperation_signal": 0.7,
    "care": 0.6,
    "followup": 0.5,
}

DEFAULT_IMPORTANCE = 0.5

# Urgency coefficients
URGENCY_OVERDUE = 1.0       # past due_date
URGENCY_TODAY = 0.9         # due today
URGENCY_3_DAYS = 0.7        # due within 3 days
URGENCY_7_DAYS = 0.5        # due within 7 days
URGENCY_NO_DUE = 0.3        # no due date

# Scoring formula weights
W_URGENCY = 0.4
W_IMPORTANCE = 0.6


@dataclass
class PriorityScore:
    """Result of priority scoring."""
    score: float           # 0.0 ~ 1.0, composite dynamic score
    urgency: float         # 0.0 ~ 1.0
    importance: float      # 0.0 ~ 1.0
    breakdown: dict[str, Any]  # detailed breakdown for audit


class PriorityScorer:
    """Calculate dynamic priority scores for Todos.

    Two-dimensional model: Score = 0.4 × urgency + 0.6 × importance
    """

    def calculate(
        self,
        todo_type: str,
        due_date: datetime | None = None,
        priority: int = 3,
        now: datetime | None = None,
    ) -> PriorityScore:
        """Calculate dynamic priority score for a Todo.

        Args:
            todo_type: Type of todo (promise, help, care, etc.)
            due_date: Due date for urgency calculation
            priority: Static priority (1=highest, 5=lowest), used as tiebreaker
            now: Current time (defaults to utcnow for testability)

        Returns:
            PriorityScore with composite score and breakdown
        """
        if now is None:
            now = datetime.now(timezone.utc)

        urgency = self._calc_urgency(due_date, now)
        importance = self._calc_importance(todo_type)

        # Composite score
        score = W_URGENCY * urgency + W_IMPORTANCE * importance

        # Priority tiebreaker: lower static priority number = slightly higher score
        # Adjust by up to ±0.05 based on static priority (1→+0.05, 5→-0.05)
        priority_adj = 0.05 * (3 - priority) / 2  # maps 1→+0.05, 3→0, 5→-0.05
        score = max(0.0, min(1.0, score + priority_adj))

        return PriorityScore(
            score=round(score, 4),
            urgency=round(urgency, 4),
            importance=round(importance, 4),
            breakdown={
                "urgency_raw": urgency,
                "importance_raw": importance,
                "urgency_weight": W_URGENCY,
                "importance_weight": W_IMPORTANCE,
                "priority_adjustment": round(priority_adj, 4),
                "due_date": due_date.isoformat() if due_date else None,
                "todo_type": todo_type,
                "static_priority": priority,
            },
        )

    def _calc_urgency(self, due_date: datetime | None, now: datetime) -> float:
        """Calculate urgency based on due_date proximity."""
        if due_date is None:
            return URGENCY_NO_DUE

        # Ensure timezone-aware comparison
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        delta = due_date - now
        days_remaining = delta.total_seconds() / 86400

        if days_remaining < 0:
            return URGENCY_OVERDUE
        elif days_remaining < 1:
            return URGENCY_TODAY
        elif days_remaining <= 3:
            return URGENCY_3_DAYS
        elif days_remaining <= 7:
            return URGENCY_7_DAYS
        else:
            # Beyond 7 days: linear decay from 0.5 to 0.3 over 30 days
            if days_remaining <= 30:
                return URGENCY_7_DAYS - (URGENCY_7_DAYS - URGENCY_NO_DUE) * (days_remaining - 7) / 23
            return URGENCY_NO_DUE

    def _calc_importance(self, todo_type: str) -> float:
        """Calculate importance based on todo_type."""
        return IMPORTANCE_WEIGHTS.get(todo_type, DEFAULT_IMPORTANCE)

    async def score_and_update_todo(self, todo, session) -> float:
        """Score a Todo ORM object and update its dynamic_score field.

        Args:
            todo: Todo ORM instance
            session: AsyncSession for committing changes

        Returns:
            The calculated dynamic_score
        """
        result = self.calculate(
            todo_type=todo.todo_type,
            due_date=todo.due_date,
            priority=todo.priority,
        )

        todo.dynamic_score = result.score
        # Also store score_calculated_at
        todo.score_calculated_at = datetime.now(timezone.utc)

        await session.commit()

        logger.info(
            "priority_scored",
            todo_id=str(todo.id),
            score=result.score,
            urgency=result.urgency,
            importance=result.importance,
        )

        return result.score

    async def batch_score_todos(self, todos, session) -> list[PriorityScore]:
        """Score multiple todos in batch.

        Args:
            todos: List of Todo ORM instances
            session: AsyncSession

        Returns:
            List of PriorityScore results
        """
        results = []
        for todo in todos:
            result = self.calculate(
                todo_type=todo.todo_type,
                due_date=todo.due_date,
                priority=todo.priority,
            )
            todo.dynamic_score = result.score
            todo.score_calculated_at = datetime.now(timezone.utc)
            results.append(result)

        await session.commit()

        logger.info(
            "batch_priority_scored",
            count=len(todos),
            avg_score=sum(r.score for r in results) / len(results) if results else 0,
        )

        return results
