"""Budget CRUD + status routes."""
from datetime import date

from fastapi import APIRouter, Query, status

from app.dependencies import CurrentUser, DbSession
from app.schemas import BudgetCreate, BudgetRead, BudgetStatus, BudgetUpdate
from app.services import BudgetService
from app.timeutils import local_today

router = APIRouter(prefix="/budgets", tags=["Budgets"])


@router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
async def create_budget(payload: BudgetCreate, current_user: CurrentUser, db: DbSession) -> BudgetRead:
    """Set a monthly spending cap for an expense category."""
    budget = await BudgetService(db).create(current_user.id, payload)
    return BudgetRead.model_validate(budget)


@router.get("", response_model=list[BudgetRead])
async def list_budgets(
    current_user: CurrentUser,
    db: DbSession,
    period: date = Query(default_factory=local_today, description="Any date within the target month."),
) -> list[BudgetRead]:
    """List all budget caps configured for the given month."""
    budgets = await BudgetService(db).list_for_period(current_user.id, period)
    return [BudgetRead.model_validate(b) for b in budgets]


@router.get("/status", response_model=list[BudgetStatus])
async def get_budget_status(
    current_user: CurrentUser,
    db: DbSession,
    period: date = Query(default_factory=local_today, description="Any date within the target month."),
) -> list[BudgetStatus]:
    """Cap vs. actual spend per category for the given month, including the
    80%-threshold warning flag — the data source for client-side budget bars."""
    return await BudgetService(db).get_status(current_user.id, period)


@router.patch("/{budget_id}", response_model=BudgetRead)
async def update_budget(
    budget_id: str, payload: BudgetUpdate, current_user: CurrentUser, db: DbSession
) -> BudgetRead:
    """Update a budget's monthly cap."""
    budget = await BudgetService(db).update(current_user.id, budget_id, payload.monthly_limit)
    return BudgetRead.model_validate(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(budget_id: str, current_user: CurrentUser, db: DbSession) -> None:
    """Remove a budget cap."""
    await BudgetService(db).delete(current_user.id, budget_id)
