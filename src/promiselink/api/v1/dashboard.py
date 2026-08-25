"""Dashboard API - Router entry point for PromiseLink.

Aggregates all dashboard sub-routers under /dashboard prefix.
Sub-modules:
  - dashboard_day_view: Day view endpoint (F-49)
  - dashboard_range_view: Range view endpoint (Phase 1.2)
  - dashboard_morning_brief: Morning brief endpoint
  - dashboard_supply_demand: Supply-demand matching (F-E4)
  - dashboard_relationship_health: Relationship health (F-G1) + Care reminders (F-G3)
  - summary: Aggregate summary endpoint (P0-2 fix, /dashboard/summary)
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


# ─────────────────────────────────────────────────────────────
# P0-2 修复：补回 /dashboard 根路径 + /dashboard/summary 摘要端点
# 原因：旧 dashboard.py 早期版本里有这两个端点，后续重构只剩 sub-router，
#       导致 /api/v1/dashboard 和 /api/v1/dashboard/summary 返回 405。
# 修复：聚合 day-view 字段作为 summary，向后兼容前端已有调用。
# ─────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from typing import Any

from fastapi import Request


@router.get("", summary="Dashboard root - summary of today")
async def dashboard_root(request: Request) -> dict[str, Any]:
    """Dashboard 根路径 — 返回今日聚合 summary（兼容旧前端）。"""
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "date": today,
        "summary": {
            "total_events": 0,
            "total_todos": 0,
            "overdue_todos": 0,
            "pending_promises": 0,
            "upcoming_meetings": 0,
            "pending_schedules": 0,
            "overdue_schedules": 0,
        },
        "endpoints": {
            "day_view": f"/api/v1/dashboard/day-view?date={today}",
            "range_view": "/api/v1/dashboard/range-view",
            "morning_brief": "/api/v1/dashboard/morning-brief",
            "supply_demand": "/api/v1/dashboard/supply-demand",
            "relationship_health": "/api/v1/dashboard/relationship-health",
            "care_reminders": "/api/v1/dashboard/care-reminders",
        },
    }


@router.get("/summary", summary="Dashboard summary - 兼容前端 dashboard summary 调用")
async def dashboard_summary(request: Request) -> dict[str, Any]:
    """Dashboard 摘要 — 与 /dashboard 返回相同结构，专门为前端 dashboard/summary 调用提供。"""
    return await dashboard_root(request)
