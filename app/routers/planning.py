"""Daily spending plan routes ("günlük harcama çizelgesi") — monthly or weekly pay periods."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DbSession
from app.models import PeriodType
from app.schemas import DailyPlanResponse, SpendingPlanRead, SpendingPlanUpsert
from app.services import PlanningService
from app.timeutils import local_today

router = APIRouter(prefix="/planning", tags=["Planning"])


@router.get("/daily", response_model=DailyPlanResponse)
async def daily_plan(
    current_user: CurrentUser,
    db: DbSession,
    day: date = Query(default_factory=local_today, description="The day to plan for (defaults to today)."),
    period_type: Optional[PeriodType] = Query(default=None, description="Override the pay period; defaults to the user's latest plan."),
) -> DailyPlanResponse:
    """Adaptive daily allowance + a day-by-day schedule for the whole pay
    period (month or week), with recurring fixed costs reserved up front."""
    return await PlanningService(db).daily_plan(current_user.id, day, period_type)


@router.get("", response_model=Optional[SpendingPlanRead])
async def get_plan(
    current_user: CurrentUser,
    db: DbSession,
    day: date = Query(default_factory=local_today),
    period_type: Optional[PeriodType] = Query(default=None),
) -> Optional[SpendingPlanRead]:
    """The raw plan inputs (savings goal, income override) for the period
    containing `day`. `null` (200) when none exists yet."""
    plan = await PlanningService(db).get_plan(current_user.id, period_type, day)
    return SpendingPlanRead.model_validate(plan) if plan else None


@router.put("", response_model=SpendingPlanRead)
async def upsert_plan(payload: SpendingPlanUpsert, current_user: CurrentUser, db: DbSession) -> SpendingPlanRead:
    """Create or update the period's plan inputs (also switches the user's
    pay-period mode: monthly ↔ weekly)."""
    plan = await PlanningService(db).upsert_plan(current_user.id, payload)
    return SpendingPlanRead.model_validate(plan)
