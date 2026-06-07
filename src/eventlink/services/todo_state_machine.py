"""Todo State Machine — 5-state transition engine.

Algorithm Design §5:
States: pending, in_progress, snoozed, done, dismissed
Transitions with side effects (feedback, completed_at, snooze scheduling).
"""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.logging import get_logger
from eventlink.core.exceptions import InvalidTransitionError
from eventlink.models.todo import Todo, SnoozeSchedule

logger = get_logger("eventlink.todo_state_machine")


# ── State and Transition Definitions ──

class TodoStatus:
    """Todo status constants."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SNOOZED = "snoozed"
    DONE = "done"
    DISMISSED = "dismissed"


VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["in_progress", "done", "dismissed", "snoozed"],
    "in_progress": ["done", "dismissed", "pending"],
    "snoozed": ["pending"],
    "done": [],
    "dismissed": [],
}

# Terminal states — no further transitions allowed
TERMINAL_STATES = {"done", "dismissed"}


class TodoStateMachine:
    """Todo State Machine with side effects.

    State diagram:
        [*] --> pending : Todo generated
        pending --> in_progress : Start
        pending --> done : Quick complete
        pending --> dismissed : Dismiss
        pending --> snoozed : Snooze
        in_progress --> done : Complete
        in_progress --> dismissed : Dismiss
        in_progress --> pending : Return
        snoozed --> pending : Auto-recover on expiry
        done --> [*]
        dismissed --> [*]
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def transition(
        self,
        todo: Todo,
        new_status: str,
        snoozed_until: Optional[datetime] = None,
        feedback: Optional[str] = None,
    ) -> Todo:
        """Execute a state transition with validation and side effects.

        Args:
            todo: The todo item to transition.
            new_status: Target status.
            snoozed_until: Required when transitioning to 'snoozed'.

        Returns:
            Updated todo item.

        Raises:
            InvalidTransitionError: If the transition is not valid.
        """
        if new_status not in VALID_TRANSITIONS.get(todo.status, []):
            raise InvalidTransitionError(todo.status, new_status)

        old_status = todo.status
        todo.status = new_status
        todo.updated_at = datetime.now(UTC)

        # ── Side Effects ──

        if new_status == "snoozed":
            if not snoozed_until:
                raise ValueError("snoozed_until is required when transitioning to snoozed")
            await self._schedule_recovery(todo, old_status, snoozed_until)

        if new_status == "done":
            todo.completed_at = datetime.now(UTC)
            todo.feedback = feedback or "useful"

        if new_status == "dismissed":
            todo.feedback = feedback or "not_useful"

        await self.session.flush()

        logger.info(
            "todo_transitioned",
            todo_id=str(todo.id),
            from_status=old_status,
            to_status=new_status,
            todo_type=todo.todo_type,
        )
        return todo

    async def recover_expired_snoozes(self) -> int:
        """Recover all expired snooze schedules.

        Called by a background task (e.g., every minute).

        Returns:
            Number of recovered todos.
        """
        now = datetime.now(UTC)
        stmt = select(SnoozeSchedule).where(SnoozeSchedule.recover_at <= now)
        result = await self.session.execute(stmt)
        schedules = list(result.scalars().all())

        recovered = 0
        for schedule in schedules:
            todo_id = schedule.todo_id
            original_status = schedule.original_status

            # Get the todo
            todo = await self.session.get(Todo, todo_id)
            if todo and todo.status == "snoozed":
                todo.status = original_status
                todo.updated_at = datetime.now(UTC)
                recovered += 1
                logger.info(
                    "snooze_recovered",
                    todo_id=str(todo_id),
                    recovered_to=original_status,
                )

            # Remove the schedule
            await self.session.delete(schedule)

        if recovered:
            await self.session.flush()

        logger.info("snooze_recovery_completed", recovered_count=recovered)
        return recovered

    async def _schedule_recovery(
        self, todo: Todo, original_status: str, until: datetime
    ) -> None:
        """Create a snooze recovery schedule.

        Args:
            todo: The snoozed todo.
            original_status: Status to recover to.
            until: When to recover.
        """
        schedule = SnoozeSchedule(
            todo_id=todo.id,
            original_status=original_status,
            recover_at=until,
        )
        self.session.add(schedule)
        logger.info(
            "snooze_scheduled",
            todo_id=str(todo.id),
            original_status=original_status,
            recover_at=until.isoformat(),
        )

    @staticmethod
    def can_transition(from_status: str, to_status: str) -> bool:
        """Check if a transition is valid without executing it."""
        return to_status in VALID_TRANSITIONS.get(from_status, [])

    @staticmethod
    def get_valid_transitions(status: str) -> list[str]:
        """Get all valid target statuses from a given status."""
        return VALID_TRANSITIONS.get(status, [])

    @staticmethod
    def is_terminal(status: str) -> bool:
        """Check if a status is terminal (no further transitions)."""
        return status in TERMINAL_STATES
