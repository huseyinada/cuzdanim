"""Daily motivation message routes."""
from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DbSession
from app.schemas import DailyMessageRead, PushTestResult
from app.services import MotivationService
from app.timeutils import local_today

router = APIRouter(prefix="/motivation", tags=["Motivation"])


@router.get("/today", response_model=DailyMessageRead)
async def today_message(current_user: CurrentUser, db: DbSession) -> DailyMessageRead:
    """Today's personalized message (generated on first request if the
    scheduler hasn't produced it yet)."""
    message = await MotivationService(db).get_or_create(current_user, local_today())
    return DailyMessageRead.model_validate(message)


@router.get("/history", response_model=list[DailyMessageRead])
async def message_history(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=30, ge=1, le=365),
) -> list[DailyMessageRead]:
    rows = await MotivationService(db).history(current_user.id, limit=limit)
    return [DailyMessageRead.model_validate(r) for r in rows]


@router.post("/send-now", response_model=PushTestResult)
async def send_now(current_user: CurrentUser, db: DbSession) -> PushTestResult:
    """Push today's message to all of the user's subscribed devices right now
    (handy for testing notifications without waiting for 08:00)."""
    return await MotivationService(db).push_today(current_user, local_today())
