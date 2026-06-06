"""PriorityScorer — Dynamic priority scoring for Todos.

Implements F-51: Two-dimensional priority model (urgency + importance).
Score = 0.4 × urgency + 0.6 × importance

Implements F-55+F-56: Phase 1 four-dimensional priority model.
Score = 0.3×urgency + 0.35×importance + 0.2×dependency + 0.15×context

Design reference: Algorithm_Design_v1.md v2.5 §2.10, Tech Design v2.7 §4.10.1a
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


# ── Phase 1: Four-Dimensional Scorer (F-55 + F-56) ──


class PriorityScorerV2(PriorityScorer):
    """Phase 1 four-dimensional priority scorer.

    Extends PoC two-dimensional scorer with:
    - F-55: Dependency (full graph path analysis)
    - F-56: Context match (Event table driven)

    Score = 0.3×urgency + 0.35×importance + 0.2×dependency + 0.15×context
    """

    WEIGHTS_PHASE1 = {
        "urgency": 0.3,
        "importance": 0.35,
        "dependency": 0.2,
        "context": 0.15,
    }

    def __init__(self):
        super().__init__()
        from eventlink.services.dependency_analyzer import DependencyAnalyzer
        from eventlink.services.context_matcher import ContextMatcher

        self.dependency_analyzer = DependencyAnalyzer()
        self.context_matcher = ContextMatcher()

    async def score_with_context(self, todo, session, brief=None) -> PriorityScore:
        """Four-dimensional scoring (requires session for graph queries).

        Args:
            todo: Todo ORM instance
            session: AsyncSession for DB queries
            brief: Optional RelationshipBrief (unused in Phase 1)

        Returns:
            PriorityScore with four-dimensional breakdown
        """
        now = datetime.now(timezone.utc)

        # Dimensions 1-2: PoC baseline
        urgency = self._calc_urgency(todo.due_date, now)
        importance = self._calc_importance(todo.todo_type)

        # Dimension 3: Dependency (F-55)
        dependency = await self.dependency_analyzer.compute_dependency_score(
            todo, session
        )

        # Dimension 4: Context match (F-56)
        context = await self.context_matcher.compute_context_score(todo, session)

        # Composite score
        score = (
            self.WEIGHTS_PHASE1["urgency"] * urgency
            + self.WEIGHTS_PHASE1["importance"] * importance
            + self.WEIGHTS_PHASE1["dependency"] * dependency
            + self.WEIGHTS_PHASE1["context"] * context
        )

        # Priority tiebreaker (same as PoC)
        priority_adj = 0.05 * (3 - todo.priority) / 2
        score = max(0.0, min(1.0, score + priority_adj))

        return PriorityScore(
            score=round(score, 4),
            urgency=round(urgency, 4),
            importance=round(importance, 4),
            breakdown={
                "urgency_raw": urgency,
                "importance_raw": importance,
                "dependency_raw": dependency,
                "context_raw": context,
                "weights": self.WEIGHTS_PHASE1,
                "priority_adjustment": round(priority_adj, 4),
                "todo_type": todo.todo_type,
                "due_date": todo.due_date.isoformat() if todo.due_date else None,
            },
        )

    async def batch_score_with_context(self, todos, session) -> list[PriorityScore]:
        """Score multiple todos with four-dimensional model.

        Args:
            todos: List of Todo ORM instances
            session: AsyncSession

        Returns:
            List of PriorityScore results
        """
        results = []
        for todo in todos:
            result = await self.score_with_context(todo, session)
            todo.dynamic_score = result.score
            todo.score_calculated_at = datetime.now(timezone.utc)
            results.append(result)

        await session.commit()

        logger.info(
            "batch_phase1_scored",
            count=len(todos),
            avg_score=sum(r.score for r in results) / len(results) if results else 0,
        )

        return results
