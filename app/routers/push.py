"""Web Push subscription routes."""
from typing import Optional

from fastapi import APIRouter, Header, status
from pydantic import BaseModel

from app.dependencies import CurrentUser, DbSession
from app.push import get_vapid_keys
from app.schemas import PushSubscriptionIn, PushSubscriptionRead, PushTestResult, VapidPublicKeyResponse
from app.services import PushService

router = APIRouter(prefix="/push", tags=["Push"])


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
async def vapid_public_key() -> VapidPublicKeyResponse:
    """Public VAPID key the browser passes as `applicationServerKey`. Unauthenticated by design."""
    return VapidPublicKeyResponse(public_key=get_vapid_keys().public_key)


@router.post("/subscribe", response_model=PushSubscriptionRead, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: PushSubscriptionIn,
    current_user: CurrentUser,
    db: DbSession,
    user_agent: Optional[str] = Header(default=None),
) -> PushSubscriptionRead:
    sub = await PushService(db).subscribe(current_user.id, payload, user_agent)
    return PushSubscriptionRead.model_validate(sub)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(payload: UnsubscribeRequest, current_user: CurrentUser, db: DbSession) -> None:
    await PushService(db).unsubscribe(current_user.id, payload.endpoint)


@router.get("/subscriptions", response_model=list[PushSubscriptionRead])
async def list_subscriptions(current_user: CurrentUser, db: DbSession) -> list[PushSubscriptionRead]:
    rows = await PushService(db).list_for_user(current_user.id)
    return [PushSubscriptionRead.model_validate(r) for r in rows]


@router.post("/test", response_model=PushTestResult)
async def test_push(current_user: CurrentUser, db: DbSession) -> PushTestResult:
    """Send a test notification to every subscribed device of the current user."""
    return await PushService(db).send_to_user(
        current_user.id,
        title="Test bildirimi ✅",
        body="Bildirimler çalışıyor! Her sabah motivasyon mesajın burada olacak.",
        url="/",
        tag="test",
    )
