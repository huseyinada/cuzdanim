"""
Serverless cron entry points (Vercel).

APScheduler needs a long-running process, which a Vercel serverless function
is not — so on Vercel the in-process scheduler is never started (see
`app/main.py`) and these HTTP endpoints run the exact same job functions
instead, triggered externally:

    - Vercel's own Cron Jobs (vercel.json) call `/api/cron/motivation`,
      `/api/cron/budget-check` and `/api/cron/monthly-snapshot` once a day
      each — Vercel invokes cron paths with GET and, when `CRON_SECRET` is
      set, automatically attaches `Authorization: Bearer <CRON_SECRET>`.
    - Vercel's free plan cannot run a cron more than once a day, so the
      once-a-minute "post due recurring transactions" job is instead pinged
      by a free external scheduler (e.g. cron-job.org) hitting
      `/api/cron/tick?key=<CRON_SECRET>` every minute.

Every job function is already idempotent (upsert / "already posted" checks),
so calling one twice, out of order, or slightly off-schedule is harmless.
"""
import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.database import async_session_maker
from app.scheduler import (
    check_budget_alerts,
    generate_monthly_snapshots,
    post_due_recurring,
    send_daily_motivation,
)
from app.services import TaskService

router = APIRouter(prefix="/api/cron", tags=["Cron (internal)"])


def _guard(authorization: str | None, key: str | None) -> None:
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        # No secret configured — refuse rather than leave the trigger open to anyone.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CRON_SECRET tanımlı değil.")
    bearer = (authorization or "").removeprefix("Bearer ").strip()
    if hmac.compare_digest(bearer, secret) or (key and hmac.compare_digest(key, secret)):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Yetkisiz.")


@router.get("/tick")
async def tick(authorization: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Every few minutes (external pinger): post any due recurring transactions
    and push any due Görevler (task) reminders — both idempotent, safe to share
    one cadence."""
    _guard(authorization, key)
    await post_due_recurring()
    async with async_session_maker() as db:
        await TaskService(db).send_due_reminders()
        await db.commit()
    return {"ok": True}


@router.get("/motivation")
async def motivation_job(authorization: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Once a day (Vercel cron): push today's motivational message."""
    _guard(authorization, key)
    await send_daily_motivation()
    return {"ok": True}


@router.get("/budget-check")
async def budget_check_job(authorization: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Once a day (Vercel cron): flag budgets crossing the alert threshold."""
    _guard(authorization, key)
    await check_budget_alerts()
    return {"ok": True}


@router.get("/monthly-snapshot")
async def monthly_snapshot_job(authorization: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Once a day (Vercel cron): refresh the previous month's frozen snapshot."""
    _guard(authorization, key)
    await generate_monthly_snapshots()
    return {"ok": True}
