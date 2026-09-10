"""
Application entry point — FastAPI app factory, middleware, routers, static
PWA frontend, and the APScheduler lifecycle wired into FastAPI's `lifespan`.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import async_session_maker, dispose_engine, run_migrations
from app.paths import BUNDLE_DIR
from app.push import get_vapid_keys
from app.routers import (
    alerts,
    analytics,
    auth,
    budgets,
    cron,
    motivation,
    planning,
    push,
    recurring,
    system,
    tasks,
    transactions,
    wallet,
)
from app.scheduler import scheduler, shutdown_scheduler, start_scheduler
from app.services import TaskService

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

STATIC_DIR = BUNDLE_DIR / "app" / "static"

# Vercel sets this on every invocation (local `vercel dev` included). A serverless
# function is not a long-running process, so APScheduler never starts there —
# the same job functions run instead via the secured `/api/cron/*` endpoints
# (see app/routers/cron.py), triggered by Vercel Cron + an external minute pinger.
IS_SERVERLESS = os.environ.get("VERCEL") == "1"


async def _task_reminder_loop() -> None:
    """Local/exe mode only: checks for due task reminders every 60s.

    Deliberately its own small asyncio loop instead of a job on the
    APScheduler instance in scheduler.py — keeps this feature fully
    self-contained in main.py + services.py + routers/tasks.py, no shared
    edits to the scheduler module needed. On Vercel the exact same check runs
    via `/api/cron/task-reminders` instead (see routers/cron.py)."""
    while True:
        try:
            await asyncio.sleep(60)
            async with async_session_maker() as db:
                sent = await TaskService(db).send_due_reminders()
                await db.commit()
                if sent:
                    logger.info("task reminder loop: %s push(es) sent", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("task reminder loop iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: migrate schema to head (any dialect), load VAPID keys, start scheduler
    (skipped on Vercel — see IS_SERVERLESS). Shutdown: scheduler + DB pool, cleanly."""
    logger.info(
        "Starting %s v%s (%s)%s",
        settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT,
        " [serverless]" if IS_SERVERLESS else "",
    )

    await run_migrations()  # Alembic upgrade head — idempotent, handles legacy DBs
    get_vapid_keys()        # create/load push keys once, up front, so the first subscribe never races
    reminder_task = None
    if not IS_SERVERLESS:
        start_scheduler()
        reminder_task = asyncio.create_task(_task_reminder_loop())

    yield

    logger.info("Shutting down %s", settings.APP_NAME)
    if reminder_task:
        reminder_task.cancel()
    if not IS_SERVERLESS:
        shutdown_scheduler()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Kişisel finans takip API'si — işlemler, kategori bütçeleri ve eşik uyarıları, "
            "günlük harcama planı, motivasyon bildirimleri ve grafik-hazır analizler."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers ------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Flat, client-friendly shape for Pydantic validation errors."""
        errors = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        first = errors[0]["message"] if errors else "Doğrulama hatası."
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": first.removeprefix("Value error, "), "errors": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Last-resort safety net: never leak stack traces to clients."""
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Beklenmeyen bir hata oluştu. Lütfen tekrar dene."},
        )

    # --- API routers -----------------------------------------------------------
    api_prefix = settings.API_V1_PREFIX
    for router in (
        auth.router,
        transactions.router,
        budgets.router,
        alerts.router,
        analytics.router,
        planning.router,
        motivation.router,
        push.router,
        recurring.router,
        wallet.router,
        system.router,
        tasks.router,
    ):
        app.include_router(router, prefix=api_prefix)

    # Cron endpoints define their own full path (/api/cron/...) — see app/routers/cron.py.
    app.include_router(cron.router)

    # --- Operational endpoints -------------------------------------------------
    @app.get("/health", tags=["System"])
    async def health():
        return {
            "status": "ok",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "timezone": settings.SCHEDULER_TIMEZONE,
            "scheduler_running": scheduler.running,
            # Jobs on a not-yet-started scheduler (ENABLE_SCHEDULER=false) have no next_run_time attr.
            "jobs": [
                {
                    "id": job.id,
                    "next_run": (nxt.isoformat() if (nxt := getattr(job, "next_run_time", None)) else None),
                }
                for job in scheduler.get_jobs()
            ],
        }

    # --- PWA frontend ----------------------------------------------------------
    # The service worker and manifest are served from the root so the SW scope
    # covers the whole app; everything else lives under /static.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    return app


app = create_app()
