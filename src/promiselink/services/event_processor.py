"""Shared event processing utilities for PromiseLink.

Consolidates duplicate background pipeline processing logic from API endpoints.
"""

import uuid

from promiselink.core.logging import get_logger

logger = get_logger("promiselink.services.event_processor")


async def process_event_background(event_id: uuid.UUID) -> None:
    """Process an event through the pipeline in the background.

    Delegates to the unified pipeline entry point in event_pipeline.py.
    This is the single entry point for all background event processing.

    Args:
        event_id: The ID of the event to process.
    """
    from promiselink.services.event_pipeline import process_event_with_short_transactions

    await process_event_with_short_transactions(event_id=str(event_id))
