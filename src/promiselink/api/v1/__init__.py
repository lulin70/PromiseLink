"""API v1 routes."""

from promiselink.api.v1 import (
    associations,
    auth,
    dashboard,
    demand_input,
    entities,
    entity_corrections,
    events,
    export,
    health,
    metrics,
    promises,
    relationship_briefs,
    reminders,
    scheduled_events,
    todos,
)

# Pro-only modules are imported conditionally in main.py when app_edition == "pro"

__all__ = [
    "associations",
    "auth",
    "dashboard",
    "demand_input",
    "entities",
    "entity_corrections",
    "events",
    "export",
    "health",
    "metrics",
    "promises",
    "relationship_briefs",
    "reminders",
    "scheduled_events",
    "todos",
]
