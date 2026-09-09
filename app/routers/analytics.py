"""Analytics routes — aggregated JSON shaped for Chart.js / Recharts consumption."""
from datetime import date

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DbSession
from app.schemas import DashboardResponse, MonthlySummary, TrendChartResponse
from app.services import AnalyticsService
from app.timeutils import local_today

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary", response_model=MonthlySummary)
async def monthly_summary(
    current_user: CurrentUser,
    db: DbSession,
    period: date = Query(default_factory=local_today, description="Any date within the target month."),
) -> MonthlySummary:
    """Income, expense, net savings, savings rate, and category breakdown
    for one month, plus a month-over-month comparison."""
    return await AnalyticsService(db).monthly_summary(current_user.id, period)


@router.get("/trend", response_model=TrendChartResponse)
async def trend(
    current_user: CurrentUser,
    db: DbSession,
    months: int = Query(default=6, ge=1, le=36, description="Number of trailing months to include."),
) -> TrendChartResponse:
    """Trailing N-month income-vs-expense trend, pre-shaped as
    `{ labels, datasets }` for a Chart.js/Recharts line or bar chart."""
    return await AnalyticsService(db).trend(current_user.id, months=months)


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(current_user: CurrentUser, db: DbSession) -> DashboardResponse:
    """One aggregate payload for a landing dashboard: current-month summary,
    a 6-month trend chart, and any unread budget alerts."""
    return await AnalyticsService(db).dashboard(current_user.id)
