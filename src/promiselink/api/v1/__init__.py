"""API v1 routes."""

from promiselink.api.v1 import (
    associations,
    auth,
    dashboard,
    demand_input,
    entities,
    events,
    export,
    health,
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
    "events",
    "export",
    "health",
    "promises",
    "reminders",
    "relationship_briefs",
    "scheduled_events",
    "todos",
]
