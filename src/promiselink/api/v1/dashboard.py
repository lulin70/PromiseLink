"""Dashboard API - Router entry point for PromiseLink.

Aggregates all dashboard sub-routers under /dashboard prefix.
Sub-modules:
  - dashboard_day_view: Day view endpoint (F-49)
  - dashboard_range_view: Range view endpoint (Phase 1.2)
  - dashboard_morning_brief: Morning brief endpoint
  - dashboard_supply_demand: Supply-demand matching (F-E4)
  - dashboard_relationship_health: Relationship health (F-G1) + Care reminders (F-G3)
"""

from fastapi import APIRouter, Depends

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.dashboard_day_view import router as day_view_router
from promiselink.api.v1.dashboard_morning_brief import router as morning_brief_router
from promiselink.api.v1.dashboard_range_view import router as range_view_router
from promiselink.api.v1.dashboard_relationship_health import router as relationship_health_router
from promiselink.api.v1.dashboard_supply_demand import router as supply_demand_router

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(rate_limit_dependency)],
)

router.include_router(day_view_router)
router.include_router(range_view_router)
router.include_router(morning_brief_router)
router.include_router(supply_demand_router)
router.include_router(relationship_health_router)
