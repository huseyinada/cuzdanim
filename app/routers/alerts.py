"""Budget alert routes (populated by the daily APScheduler job)."""
from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DbSession
from app.schemas import BudgetAlertRead
from app.services import AlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[BudgetAlertRead])
async def list_alerts(
    current_user: CurrentUser,
    db: DbSession,
    unread_only: bool = Query(default=False),
) -> list[BudgetAlertRead]:
    """List budget-threshold alerts generated for the current user."""
    return await AlertService(db).list_for_user(current_user.id, unread_only=unread_only)


@router.patch("/{alert_id}/read", response_model=BudgetAlertRead)
async def mark_alert_read(alert_id: str, current_user: CurrentUser, db: DbSession) -> BudgetAlertRead:
    """Mark a single alert as read/acknowledged."""
    return await AlertService(db).mark_read(current_user.id, alert_id)
