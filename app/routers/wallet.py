"""Wallet ("kasa") overview route."""
from fastapi import APIRouter

from app.dependencies import CurrentUser, DbSession
from app.schemas import WalletResponse
from app.services import WalletService

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get("", response_model=WalletResponse)
async def wallet(current_user: CurrentUser, db: DbSession) -> WalletResponse:
    """Balance, this period's remaining money, what's reserved for fixed
    costs, what's truly free, and the upcoming automatic deductions."""
    return await WalletService(db).overview(current_user.id)
