"""Health check endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.database import get_async_session

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.
    
    Returns application status without database check.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "eventlink",
    }


@router.get("/health/db")
async def health_check_db(session: AsyncSession = Depends(get_async_session)):
    """
    Health check with database connectivity test.
    
    Verifies that the database connection is working.
    """
    try:
        # Simple query to test connection
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "eventlink",
        "database": db_status,
    }
