"""Operational routes for the account owner: on-demand backups."""
from fastapi import APIRouter

from app.dependencies import CurrentUser
from app.schemas import BackupResult
from app.services import BackupService

router = APIRouter(prefix="/system", tags=["System"])


@router.post("/backup", response_model=BackupResult)
async def backup_now(current_user: CurrentUser) -> BackupResult:
    """Write a consistent SQLite snapshot to ./backups (also runs nightly at 03:30)."""
    return await BackupService.backup_now()


@router.get("/backups", response_model=list[BackupResult])
async def list_backups(current_user: CurrentUser) -> list[BackupResult]:
    return BackupService.list_backups()
