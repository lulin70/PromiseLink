"""Step 08: Send notifications for new todos + auto-mark overdue promises (F-68)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, select, update

from promiselink.core.logging import get_logger
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step08_Notification(PipelineStep):
    """Send notifications for new todos + auto-mark overdue promises."""

    name = "step08_notification"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        event_id = context.event_id
        user_id = context.user_id

        try:
            from promiselink.services.notification_service import notification_service
            for todo in context.result.todos:
                await notification_service.notify_todo_created(
                    user_id=user_id,
                    todo_title=todo.title,
                    todo_type=todo.todo_type,
                    todo_id=str(todo.id),
                )
        except Exception as notif_err:
            logger.warning("pipeline_notification_failed", error=str(notif_err))
            context.failed_steps.append(self.name)

        # F-68: Auto-mark overdue promises
        # When my_promise type Todo's due_date has passed and fulfillment_status is still pending,
        # automatically mark as overdue.
        try:
            from promiselink.database import AsyncSessionLocal, commit_with_retry

            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as session:
                overdue_q = (
                    update(Todo)
                    .where(
                        and_(
                            Todo.user_id == user_id,
                            Todo.action_type == "my_promise",
                            Todo.fulfillment_status == "pending",
                            Todo.due_date.isnot(None),
                            Todo.due_date < now,
                        )
                    )
                    .values(fulfillment_status="overdue")
                )
                result = await session.execute(overdue_q)
                overdue_count = result.rowcount  # type: ignore[attr-defined]

                if overdue_count > 0:
                    logger.info(
                        "pipeline_auto_overdue_marked",
                        user_id=user_id,
                        overdue_count=overdue_count,
                    )
                    await commit_with_retry(session)
        except Exception as overdue_err:
            logger.warning("pipeline_auto_overdue_failed", error=str(overdue_err))

        return context
