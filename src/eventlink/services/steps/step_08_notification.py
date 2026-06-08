"""Step 08: Send notifications for new todos."""

from __future__ import annotations

from eventlink.core.logging import get_logger
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step08_Notification(PipelineStep):
    """Send notifications for new todos."""

    name = "step08_notification"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        event_id = context.event_id
        user_id = context.user_id

        try:
            from eventlink.services.notification_service import notification_service
            for todo in context.result.todos:
                await notification_service.notify_todo_created(
                    user_id=user_id,
                    todo_title=todo.title,
                    todo_type=todo.todo_type,
                    todo_id=str(todo.id),
                )
        except Exception as notif_err:
            logger.warning("pipeline_notification_failed", error=str(notif_err))

        return context
