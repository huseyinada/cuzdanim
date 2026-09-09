"""
APScheduler integration — background jobs wired cleanly into FastAPI's
lifespan, using `AsyncIOScheduler` so job coroutines run on the *same*
event loop as the web server (no thread pools, no blocking).

Jobs never reuse a request-scoped DB session — each run opens its own
`AsyncSession` from `async_session_maker` and closes it when done.

Jobs (all times in `SCHEDULER_TIMEZONE`, default Europe/Istanbul):
    1. `send_daily_motivation`   — every morning (DAILY_MESSAGE_HOUR, default 08:00).
       Generates each user's personalized message and pushes it to their devices.
    2. `check_budget_alerts`     — every evening (BUDGET_CHECK_HOUR, default 20:00).
       Flags a `BudgetAlert` (and pushes a notification for *new* ones) once a
       category's spend crosses `BUDGET_ALERT_THRESHOLD` of its monthly cap.
    3. `generate_monthly_snapshots` — 00:30 on the 1st. Freezes the previous
       month's summary into `MonthlySnapshot` rows.

All jobs are idempotent (upsert semantics), so a missed run, a restart, or a
manual re-trigger never creates duplicates.
"""
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import IS_SQLITE, async_session_maker
from app.models import Category, TransactionType
from app.motivation_texts import MONTHS_TR, category_label, fmt_money
from app.repositories import (
    AlertRepository,
    BudgetRepository,
    PushSubscriptionRepository,
    SnapshotRepository,
    TransactionRepository,
    UserRepository,
    month_bounds,
    shift_month,
)
from app.services import BackupService, MotivationService, PushService, RecurringService
from app.timeutils import local_now_naive, local_today

logger = logging.getLogger("app.scheduler")

TWOPLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        return Decimal("0.00")
    return _q((part / whole) * Decimal(100))


def _category_tr(category: Category) -> str:
    return category_label(category.value)


# ============================================================================
# Job 1 — morning motivation push
# ============================================================================
async def send_daily_motivation() -> None:
    today = local_today()
    pushed = skipped = 0
    async with async_session_maker() as db:
        try:
            users = await UserRepository(db).list_active()
            service = MotivationService(db)
            sub_repo = PushSubscriptionRepository(db)
            for user in users:
                message = await service.get_or_create(user, today)
                if message.pushed_at is not None or not await sub_repo.list_for_user(user.id):
                    skipped += 1
                    continue
                result = await service.push_today(user, today)
                pushed += result.sent
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("send_daily_motivation job failed")
            raise
    logger.info("send_daily_motivation: %s device push(es) sent, %s user(s) skipped", pushed, skipped)


# ============================================================================
# Job 2 — evening budget threshold check
# ============================================================================
async def check_budget_alerts() -> None:
    period = local_today().replace(day=1)
    start, end = month_bounds(period)
    threshold_pct = Decimal(str(settings.BUDGET_ALERT_THRESHOLD)) * 100
    symbol = settings.CURRENCY_SYMBOL
    month_label = f"{MONTHS_TR[period.month - 1]} {period.year}"

    flagged = 0
    async with async_session_maker() as db:
        try:
            users = await UserRepository(db).list_active()
            budget_repo = BudgetRepository(db)
            tx_repo = TransactionRepository(db)
            alert_repo = AlertRepository(db)
            push = PushService(db)

            for user in users:
                for budget in await budget_repo.list_for_period(user.id, period):
                    spent = await tx_repo.sum_amount(
                        user.id,
                        type_=TransactionType.EXPENSE,
                        category=budget.category,
                        start_date=start,
                        end_date=end,
                    )
                    utilization = _pct(spent, budget.monthly_limit)
                    if utilization < threshold_pct:
                        continue

                    label = _category_tr(budget.category)
                    if spent > budget.monthly_limit:
                        message = (
                            f"{month_label} için '{label}' bütçeni aştın: "
                            f"{fmt_money(spent, symbol)} / {fmt_money(budget.monthly_limit, symbol)} (%{utilization})."
                        )
                    else:
                        message = (
                            f"{month_label} için '{label}' bütçenin %{utilization}'ına ulaştın: "
                            f"{fmt_money(spent, symbol)} / {fmt_money(budget.monthly_limit, symbol)}."
                        )

                    _, created = await alert_repo.upsert(
                        user_id=user.id,
                        category=budget.category,
                        period=period,
                        fields={
                            "threshold_percent": threshold_pct,
                            "utilization_percent": utilization,
                            "spent_amount": _q(spent),
                            "budget_limit": budget.monthly_limit,
                            "message": message,
                        },
                    )
                    flagged += 1
                    if created:
                        await push.send_to_user(
                            user.id, title="Bütçe uyarısı ⚠️", body=message, url="/#plan", tag=f"budget-{budget.category.value}"
                        )

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("check_budget_alerts job failed")
            raise

    logger.info("check_budget_alerts: %s user(s) evaluated, %s alert(s) flagged", len(users), flagged)


# ============================================================================
# Job 3 — monthly snapshot generation (runs on the 1st)
# ============================================================================
async def generate_monthly_snapshots() -> None:
    previous_period = shift_month(local_today().replace(day=1), -1)
    start, end = month_bounds(previous_period)

    written = 0
    async with async_session_maker() as db:
        try:
            users = await UserRepository(db).list_active()
            tx_repo = TransactionRepository(db)
            snapshot_repo = SnapshotRepository(db)

            for user in users:
                count = await tx_repo.count_in_range(user.id, start_date=start, end_date=end)
                if count == 0:
                    continue  # nothing meaningful to freeze

                total_income = await tx_repo.sum_amount(
                    user.id, type_=TransactionType.INCOME, start_date=start, end_date=end
                )
                total_expense = await tx_repo.sum_amount(
                    user.id, type_=TransactionType.EXPENSE, start_date=start, end_date=end
                )
                net_savings = total_income - total_expense
                savings_rate = _pct(net_savings, total_income) if total_income > 0 else Decimal("0.00")

                breakdown = []
                for category, tx_type, amount in await tx_repo.category_breakdown(
                    user.id, start_date=start, end_date=end
                ):
                    totals_for_type = total_income if tx_type == TransactionType.INCOME else total_expense
                    breakdown.append(
                        {
                            "category": category.value if isinstance(category, Category) else category,
                            "type": tx_type.value if isinstance(tx_type, TransactionType) else tx_type,
                            "amount": str(_q(Decimal(amount))),
                            "percentage": str(_pct(Decimal(amount), totals_for_type)),
                        }
                    )

                await snapshot_repo.upsert(
                    user_id=user.id,
                    period=previous_period,
                    fields={
                        "total_income": _q(total_income),
                        "total_expense": _q(total_expense),
                        "net_savings": _q(net_savings),
                        "savings_rate": savings_rate,
                        "transaction_count": count,
                        "category_breakdown": breakdown,
                    },
                )
                written += 1

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("generate_monthly_snapshots job failed")
            raise

    logger.info(
        "generate_monthly_snapshots: wrote %s snapshot(s) for %s (%s users evaluated)",
        written, previous_period.isoformat(), len(users),
    )


# ============================================================================
# Job 4 — post due recurring (fixed) transactions, every minute
# ============================================================================
async def post_due_recurring() -> None:
    """Turn every due `RecurringRule` slot into a real transaction (idempotent),
    then tell the user what was deducted and what's left in the wallet."""
    now = local_now_naive()
    async with async_session_maker() as db:
        try:
            posted = await RecurringService(db).post_due(now)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("post_due_recurring job failed")
            raise

        if not posted:
            return

        symbol = settings.CURRENCY_SYMBOL
        tx_repo = TransactionRepository(db)
        push = PushService(db)
        by_user: dict[str, list] = defaultdict(list)
        for rule, slot in posted:
            by_user[rule.user_id].append((rule, slot))

        for user_id, items in by_user.items():
            balance = await tx_repo.balance_total(user_id)
            lines = [f"{rule.name} {fmt_money(rule.amount, symbol)} ({slot:%H:%M})" for rule, slot in items]
            expenses = [r for r, _ in items if r.type == TransactionType.EXPENSE]
            title = "Otomatik düşüldü 💸" if expenses else "Para geldi 💰"
            body = " · ".join(lines) + f"\nKalan bakiye: {fmt_money(balance, symbol)}"
            await push.send_to_user(user_id, title=title, body=body, url="/#today", tag="recurring")
        await db.commit()

    logger.info("post_due_recurring: posted %s transaction(s) for %s user(s)", len(posted), len(by_user))


# ============================================================================
# Job 5 — nightly SQLite backup (no-op on PostgreSQL)
# ============================================================================
async def backup_database() -> None:
    if not IS_SQLITE:
        return
    result = await BackupService.backup_now()
    logger.info("backup_database: wrote %s (%s bytes)", result.path, result.size_bytes)


# ============================================================================
# Scheduler wiring
# ============================================================================
def build_scheduler() -> AsyncIOScheduler:
    """Construct (but do not start) the process-wide scheduler and register jobs."""
    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    common = dict(replace_existing=True, misfire_grace_time=3600, coalesce=True, max_instances=1)

    scheduler.add_job(
        post_due_recurring,
        trigger=IntervalTrigger(minutes=1),
        id="post_due_recurring",
        name="Tekrarlayan işlemleri düş (her dakika)",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        backup_database,
        trigger=CronTrigger(hour=3, minute=30),
        id="backup_database",
        name="Gece veritabanı yedeği (SQLite)",
        **common,
    )

    scheduler.add_job(
        send_daily_motivation,
        trigger=CronTrigger(hour=settings.DAILY_MESSAGE_HOUR, minute=settings.DAILY_MESSAGE_MINUTE),
        id="send_daily_motivation",
        name="Günlük motivasyon mesajı (push)",
        **common,
    )
    scheduler.add_job(
        check_budget_alerts,
        trigger=CronTrigger(hour=settings.BUDGET_CHECK_HOUR, minute=0),
        id="check_budget_alerts",
        name="Günlük bütçe eşik kontrolü (>=80%)",
        **common,
    )
    scheduler.add_job(
        generate_monthly_snapshots,
        trigger=CronTrigger(day=1, hour=0, minute=30),
        id="generate_monthly_snapshots",
        name="Aylık özet (önceki ay)",
        **common,
    )
    return scheduler


scheduler = build_scheduler()


def start_scheduler() -> None:
    if not settings.ENABLE_SCHEDULER:
        logger.info("Scheduler disabled via ENABLE_SCHEDULER=false — skipping startup.")
        return
    if not scheduler.running:
        scheduler.start()
        logger.info(
            "APScheduler started (timezone=%s) with jobs: %s",
            settings.SCHEDULER_TIMEZONE,
            [job.id for job in scheduler.get_jobs()],
        )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down.")
