"""Recurring (fixed, scheduled) transaction routes."""
from datetime import timedelta

from fastapi import APIRouter, Query, status

from app.dependencies import CurrentUser, DbSession
from app.schemas import RecurringRuleCreate, RecurringRuleRead, RecurringRuleUpdate, TransactionRead, UpcomingOccurrence
from app.services import RecurringService
from app.timeutils import local_now_naive

router = APIRouter(prefix="/recurring", tags=["Recurring"])


@router.get("", response_model=list[RecurringRuleRead])
async def list_rules(current_user: CurrentUser, db: DbSession) -> list[RecurringRuleRead]:
    rules = await RecurringService(db).list_for_user(current_user.id)
    return [RecurringRuleRead.model_validate(r) for r in rules]


@router.post("", response_model=RecurringRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RecurringRuleCreate, current_user: CurrentUser, db: DbSession) -> RecurringRuleRead:
    """Define a fixed transaction, e.g. lunch 150 ₺ every day at 12:30. Slots
    already passed today (up to 7 days back) are posted on the next tick."""
    rule = await RecurringService(db).create(current_user.id, payload)
    return RecurringRuleRead.model_validate(rule)


@router.patch("/{rule_id}", response_model=RecurringRuleRead)
async def update_rule(rule_id: str, payload: RecurringRuleUpdate, current_user: CurrentUser, db: DbSession) -> RecurringRuleRead:
    rule = await RecurringService(db).update(current_user.id, rule_id, payload)
    return RecurringRuleRead.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, current_user: CurrentUser, db: DbSession) -> None:
    """Delete the rule; transactions it already posted are kept."""
    await RecurringService(db).delete(current_user.id, rule_id)


@router.post("/{rule_id}/post-now", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
async def post_now(rule_id: str, current_user: CurrentUser, db: DbSession) -> TransactionRead:
    """'I just spent it' — deduct this rule's amount right now (schedule unchanged)."""
    tx = await RecurringService(db).post_now(current_user.id, rule_id)
    return TransactionRead.model_validate(tx)


@router.get("/upcoming", response_model=list[UpcomingOccurrence])
async def upcoming(
    current_user: CurrentUser,
    db: DbSession,
    days: int = Query(default=7, ge=1, le=60),
) -> list[UpcomingOccurrence]:
    now = local_now_naive()
    return await RecurringService(db).upcoming(current_user.id, start=now, end=now + timedelta(days=days))
