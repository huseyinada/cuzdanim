"""
Service layer — all business logic lives here.

Routers stay thin (parse request -> call service -> return response);
repositories stay dumb (pure data access). Services own validation that
spans multiple entities, HTTPException raising, and orchestration.
User-facing error messages are in Turkish (the app's UI language).
"""
import asyncio
import calendar
import logging
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import PROJECT_ROOT, sqlite_file_path
from app.models import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    Budget,
    Category,
    DailyMessage,
    Frequency,
    PeriodType,
    PushSubscription,
    RecurringRule,
    SpendingPlan,
    Task,
    Transaction,
    TransactionSource,
    TransactionType,
    User,
)
from app.motivation_texts import WEEKDAYS_TR, category_label, compose_daily_message, fmt_money, status_line
from app.periods import (
    days_in_period,
    period_bounds,
    period_end_exclusive,
    period_label_tr,
    period_start,
)
from app.push import send_web_push
from app.repositories import (
    AlertRepository,
    BudgetRepository,
    DailyMessageRepository,
    PushSubscriptionRepository,
    RecurringRuleRepository,
    SnapshotRepository,
    SpendingPlanRepository,
    TaskRepository,
    TransactionRepository,
    UserRepository,
    month_bounds,
    shift_month,
)
from app.schemas import (
    BackupResult,
    BudgetAlertRead,
    BudgetCreate,
    BudgetStatus,
    CategoryBreakdownItem,
    ChartDataset,
    DailyPlanResponse,
    DailyScheduleItem,
    DashboardResponse,
    MonthlySummary,
    PushSubscriptionIn,
    PushTestResult,
    RecurringRuleCreate,
    RecurringRuleUpdate,
    SpendingPlanUpsert,
    TaskCreate,
    TaskUpdate,
    Token,
    TransactionCreate,
    TransactionUpdate,
    TrendChartResponse,
    TrendPoint,
    UpcomingOccurrence,
    UserCreate,
    WalletResponse,
)
from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.timeutils import local_now_naive, local_today, to_local_naive

logger = logging.getLogger("app.services")

TWOPLACES = Decimal("0.01")

_PAYMENT_TR = {
    "cash": "Nakit", "credit_card": "Kredi Kartı", "debit_card": "Banka Kartı",
    "bank_transfer": "Havale / EFT", "mobile_payment": "Mobil Ödeme", "other": "Diğer",
}


def _q(value: Decimal) -> Decimal:
    """Round a Decimal to 2 places using standard financial rounding."""
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        return Decimal("0.00")
    return _q((part / whole) * Decimal(100))


# ============================================================================
class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)

    async def signup(self, data: UserCreate) -> User:
        existing = await self.users.get_by_email(data.email.lower())
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu e-posta ile kayıtlı bir hesap zaten var.",
            )
        return await self.users.create(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )

    async def authenticate(self, email: str, password: str) -> User:
        invalid_credentials = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        user = await self.users.get_by_email(email.lower())
        if not user or not verify_password(password, user.hashed_password):
            raise invalid_credentials
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hesap pasif durumda.")
        return user

    @staticmethod
    def issue_tokens(user: User) -> Token:
        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def login(self, email: str, password: str) -> Token:
        user = await self.authenticate(email, password)
        return self.issue_tokens(user)

    async def refresh(self, refresh_token: str) -> Token:
        try:
            user_id = decode_token(refresh_token, expected_type="refresh")
        except InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Oturum süresi doldu, lütfen tekrar giriş yap.",
            )
        user = await self.users.get_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı geçerli değil.")
        return self.issue_tokens(user)


# ============================================================================
class TransactionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.transactions = TransactionRepository(db)
        self.push = PushService(db)

    async def _notify_wallet(self, user_id: str) -> None:
        """Best-effort — a push hiccup must never fail the actual transaction."""
        try:
            await self.push.send_wallet_update(user_id)
        except Exception:
            logger.exception("wallet push notification failed for user %s", user_id)

    async def create(self, user_id: str, data: TransactionCreate) -> Transaction:
        payload = data.model_dump()
        payload["transaction_date"] = (
            to_local_naive(payload["transaction_date"]) if payload.get("transaction_date") else local_now_naive()
        )
        transaction = await self.transactions.create(user_id=user_id, data=payload)
        await self._notify_wallet(user_id)
        return transaction

    async def get_or_404(self, user_id: str, transaction_id: str) -> Transaction:
        transaction = await self.transactions.get_by_id(transaction_id, user_id)
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İşlem bulunamadı.")
        return transaction

    async def update(self, user_id: str, transaction_id: str, data: TransactionUpdate) -> Transaction:
        transaction = await self.get_or_404(user_id, transaction_id)
        updates = data.model_dump(exclude_unset=True)

        # Validate the resulting type/category pairing, whether the caller
        # changed one, both, or neither.
        final_type = updates.get("type", transaction.type)
        final_category = updates.get("category", transaction.category)
        valid = INCOME_CATEGORIES if final_type == TransactionType.INCOME else EXPENSE_CATEGORIES
        if final_category not in valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{final_category.value}' kategorisi '{final_type.value}' türü için geçerli değil.",
            )

        if updates.get("transaction_date"):
            updates["transaction_date"] = to_local_naive(updates["transaction_date"])
        if not updates:
            return transaction
        updated = await self.transactions.update(transaction, updates)
        await self._notify_wallet(user_id)
        return updated

    async def delete(self, user_id: str, transaction_id: str) -> None:
        transaction = await self.get_or_404(user_id, transaction_id)
        await self.transactions.delete(transaction)
        await self._notify_wallet(user_id)

    async def list_paginated(
        self,
        user_id: str,
        *,
        type_: Optional[TransactionType],
        category: Optional[Category],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        q: Optional[str] = None,
        page: int,
        page_size: int,
    ) -> tuple[list[Transaction], int]:
        return await self.transactions.list_paginated(
            user_id,
            type_=type_,
            category=category,
            start_date=to_local_naive(start_date) if start_date else None,
            end_date=to_local_naive(end_date) if end_date else None,
            q=(q or None),
            page=page,
            page_size=page_size,
        )

    async def export_csv(
        self,
        user_id: str,
        *,
        type_: Optional[TransactionType] = None,
        category: Optional[Category] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        q: Optional[str] = None,
    ) -> str:
        """All matching transactions as CSV text (Excel-friendly, UTF-8 BOM added by the router)."""
        import csv
        import io

        rows = await self.transactions.list_for_export(
            user_id,
            type_=type_,
            category=category,
            start_date=to_local_naive(start_date) if start_date else None,
            end_date=to_local_naive(end_date) if end_date else None,
            q=(q or None),
        )
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")  # ';' opens cleanly in Turkish-locale Excel
        writer.writerow(["Tarih", "Tür", "Kategori", "Tutar", "Açıklama", "Ödeme Yöntemi", "Kaynak"])
        for t in rows:
            writer.writerow([
                t.transaction_date.strftime("%d.%m.%Y %H:%M"),
                "Gelir" if t.type == TransactionType.INCOME else "Gider",
                category_label(t.category.value),
                f"{t.amount:.2f}".replace(".", ","),
                t.description or "",
                _PAYMENT_TR.get(t.payment_method.value, t.payment_method.value),
                "Otomatik" if t.source == TransactionSource.RECURRING else "Manuel",
            ])
        return buf.getvalue()


# ============================================================================
class BudgetService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.budgets = BudgetRepository(db)
        self.transactions = TransactionRepository(db)

    async def create(self, user_id: str, data: BudgetCreate) -> Budget:
        existing = await self.budgets.get_by_category_period(user_id, data.category, data.period)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu kategori için bu ay zaten bir bütçe var. Güncellemek için mevcut bütçeyi düzenle.",
            )
        return await self.budgets.create(
            user_id=user_id, category=data.category, monthly_limit=data.monthly_limit, period=data.period
        )

    async def get_or_404(self, user_id: str, budget_id: str) -> Budget:
        budget = await self.budgets.get_by_id(budget_id, user_id)
        if budget is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bütçe bulunamadı.")
        return budget

    async def update(self, user_id: str, budget_id: str, monthly_limit: Decimal) -> Budget:
        budget = await self.get_or_404(user_id, budget_id)
        return await self.budgets.update_limit(budget, monthly_limit)

    async def delete(self, user_id: str, budget_id: str) -> None:
        budget = await self.get_or_404(user_id, budget_id)
        await self.budgets.delete(budget)

    async def list_for_period(self, user_id: str, period: date) -> list[Budget]:
        return await self.budgets.list_for_period(user_id, period.replace(day=1))

    async def get_status(self, user_id: str, period: date) -> list[BudgetStatus]:
        period = period.replace(day=1)
        start, end = month_bounds(period)
        budgets = await self.budgets.list_for_period(user_id, period)

        statuses: list[BudgetStatus] = []
        threshold_pct = Decimal(str(settings.BUDGET_ALERT_THRESHOLD)) * 100
        for budget in budgets:
            spent = await self.transactions.sum_amount(
                user_id,
                type_=TransactionType.EXPENSE,
                category=budget.category,
                start_date=start,
                end_date=end,
            )
            utilization = _pct(spent, budget.monthly_limit)
            statuses.append(
                BudgetStatus(
                    category=budget.category,
                    period=period,
                    monthly_limit=budget.monthly_limit,
                    spent=_q(spent),
                    remaining=_q(budget.monthly_limit - spent),
                    utilization_percent=utilization,
                    is_over_threshold=utilization >= threshold_pct,
                    is_exceeded=spent > budget.monthly_limit,
                )
            )
        return statuses


# ============================================================================
class AlertService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.alerts = AlertRepository(db)

    async def list_for_user(self, user_id: str, *, unread_only: bool = False) -> list[BudgetAlertRead]:
        rows = await self.alerts.list_for_user(user_id, unread_only=unread_only)
        return [BudgetAlertRead.model_validate(row) for row in rows]

    async def mark_read(self, user_id: str, alert_id: str) -> BudgetAlertRead:
        alert = await self.alerts.get_by_id(alert_id, user_id)
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uyarı bulunamadı.")
        updated = await self.alerts.mark_read(alert)
        return BudgetAlertRead.model_validate(updated)


# ============================================================================
class AnalyticsService:
    """Aggregation logic feeding chart-ready analytics endpoints."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.transactions = TransactionRepository(db)
        self.alerts = AlertRepository(db)

    async def monthly_summary(self, user_id: str, period: date) -> MonthlySummary:
        period = period.replace(day=1)
        start, end = month_bounds(period)

        total_income = await self.transactions.sum_amount(
            user_id, type_=TransactionType.INCOME, start_date=start, end_date=end
        )
        total_expense = await self.transactions.sum_amount(
            user_id, type_=TransactionType.EXPENSE, start_date=start, end_date=end
        )
        net_savings = total_income - total_expense
        savings_rate = _pct(net_savings, total_income) if total_income > 0 else Decimal("0.00")
        count = await self.transactions.count_in_range(user_id, start_date=start, end_date=end)

        raw_breakdown = await self.transactions.category_breakdown(user_id, start_date=start, end_date=end)
        breakdown: list[CategoryBreakdownItem] = []
        for category, tx_type, amount in raw_breakdown:
            totals_for_type = total_income if tx_type == TransactionType.INCOME else total_expense
            breakdown.append(
                CategoryBreakdownItem(
                    category=category,
                    type=tx_type,
                    amount=_q(Decimal(amount)),
                    percentage=_pct(Decimal(amount), totals_for_type),
                )
            )
        breakdown.sort(key=lambda item: item.amount, reverse=True)

        # Month-over-month comparison against the prior calendar month.
        prev_period = shift_month(period, -1)
        prev_start, prev_end = month_bounds(prev_period)
        prev_income = await self.transactions.sum_amount(
            user_id, type_=TransactionType.INCOME, start_date=prev_start, end_date=prev_end
        )
        prev_expense = await self.transactions.sum_amount(
            user_id, type_=TransactionType.EXPENSE, start_date=prev_start, end_date=prev_end
        )
        income_change = _pct(total_income - prev_income, prev_income) if prev_income > 0 else None
        expense_change = _pct(total_expense - prev_expense, prev_expense) if prev_expense > 0 else None

        return MonthlySummary(
            period=period,
            total_income=_q(total_income),
            total_expense=_q(total_expense),
            net_savings=_q(net_savings),
            savings_rate=savings_rate,
            transaction_count=count,
            category_breakdown=breakdown,
            previous_period_income=_q(prev_income),
            previous_period_expense=_q(prev_expense),
            income_change_percent=income_change,
            expense_change_percent=expense_change,
        )

    async def trend(self, user_id: str, *, months: int = 6, anchor: Optional[date] = None) -> TrendChartResponse:
        """Trailing `months` of income/expense totals, oldest -> newest,
        pre-shaped as Chart.js/Recharts `labels` + `datasets`."""
        anchor = (anchor or local_today()).replace(day=1)
        points: list[TrendPoint] = []

        for offset in range(months - 1, -1, -1):
            period = shift_month(anchor, -offset)
            start, end = month_bounds(period)
            income = await self.transactions.sum_amount(
                user_id, type_=TransactionType.INCOME, start_date=start, end_date=end
            )
            expense = await self.transactions.sum_amount(
                user_id, type_=TransactionType.EXPENSE, start_date=start, end_date=end
            )
            points.append(
                TrendPoint(
                    period=period,
                    label=f"{calendar.month_abbr[period.month]} {period.year}",
                    income=_q(income),
                    expense=_q(expense),
                    net_savings=_q(income - expense),
                )
            )

        return TrendChartResponse(
            labels=[p.label for p in points],
            datasets=[
                ChartDataset(label="Income", data=[p.income for p in points]),
                ChartDataset(label="Expense", data=[p.expense for p in points]),
                ChartDataset(label="Net Savings", data=[p.net_savings for p in points]),
            ],
            raw=points,
        )

    async def dashboard(self, user_id: str) -> DashboardResponse:
        current_month = await self.monthly_summary(user_id, local_today())
        trend = await self.trend(user_id, months=6)
        unread = await self.alerts.list_for_user(user_id, unread_only=True)
        return DashboardResponse(
            current_month=current_month,
            trend=trend,
            unread_alerts=[BudgetAlertRead.model_validate(a) for a in unread],
        )


# ============================================================================
class RecurringService:
    """Fixed, scheduled transactions ("Yemek 150 ₺ her gün 12:30").

    - `next_occurrence` is pure calendar math; `next_run_at` on the rule caches
      the next due slot so the scheduler query is a cheap indexed range scan.
    - `post_due` is idempotent: it checks for an existing (rule, slot) row and
      the DB's UNIQUE constraint is the last line of defence.
    - Catch-up is capped at 7 days so a PC that was off for a weekend posts
      the missed lunches, but a rule back-dated by months doesn't flood history.
    """

    CATCH_UP_DAYS = 7
    MAX_SLOTS_PER_RUN = 400

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rules = RecurringRuleRepository(db)
        self.transactions = TransactionRepository(db)
        self.push = PushService(db)

    # ---- calendar math -------------------------------------------------------
    @staticmethod
    def mask_from_weekdays(weekdays: list[int]) -> int:
        return sum(1 << d for d in set(weekdays))

    @staticmethod
    def _matches(rule: RecurringRule, day: date) -> bool:
        if rule.frequency == Frequency.DAILY:
            return True
        if rule.frequency == Frequency.WEEKLY:
            return bool(rule.weekday_mask & (1 << day.weekday()))
        last_day = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(rule.day_of_month or 1, last_day)

    @classmethod
    def next_occurrence(cls, rule: RecurringRule, after: datetime) -> Optional[datetime]:
        """First slot strictly later than `after` (None when the rule has ended)."""
        day = max(after.date(), rule.start_date)
        for _ in range(cls.MAX_SLOTS_PER_RUN):
            if rule.end_date is not None and day > rule.end_date:
                return None
            if cls._matches(rule, day):
                candidate = datetime.combine(day, rule.time_of_day)
                if candidate > after:
                    return candidate
            day += timedelta(days=1)
        return None

    @classmethod
    def occurrences_between(cls, rule: RecurringRule, start: datetime, end: datetime) -> list[datetime]:
        out: list[datetime] = []
        cur = cls.next_occurrence(rule, start - timedelta(microseconds=1))
        while cur is not None and cur < end and len(out) < cls.MAX_SLOTS_PER_RUN:
            out.append(cur)
            cur = cls.next_occurrence(rule, cur)
        return out

    def _initial_anchor(self, start_date: date, now: datetime) -> datetime:
        """Where to start looking for the first slot on create: from start_date
        (so today's already-passed slot still posts), but never more than
        CATCH_UP_DAYS into the past."""
        start_dt = datetime.combine(start_date, time.min)
        floor = now - timedelta(days=self.CATCH_UP_DAYS)
        return max(start_dt, floor) - timedelta(seconds=1)

    # ---- CRUD ----------------------------------------------------------------
    async def get_or_404(self, user_id: str, rule_id: str) -> RecurringRule:
        rule = await self.rules.get_by_id(rule_id, user_id)
        if rule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tekrarlayan işlem bulunamadı.")
        return rule

    async def list_for_user(self, user_id: str) -> list[RecurringRule]:
        return list(await self.rules.list_for_user(user_id))

    async def create(self, user_id: str, data: RecurringRuleCreate) -> RecurringRule:
        fields = data.model_dump(exclude={"weekdays"})
        fields["weekday_mask"] = self.mask_from_weekdays(data.weekdays) if data.frequency == Frequency.WEEKLY else 127
        rule = await self.rules.create(user_id=user_id, fields=fields)
        rule.next_run_at = self.next_occurrence(rule, self._initial_anchor(rule.start_date, local_now_naive()))
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def update(self, user_id: str, rule_id: str, data: RecurringRuleUpdate) -> RecurringRule:
        rule = await self.get_or_404(user_id, rule_id)
        updates = data.model_dump(exclude_unset=True)
        if "weekdays" in updates:
            weekdays = updates.pop("weekdays")
            if weekdays is not None:
                updates["weekday_mask"] = self.mask_from_weekdays(weekdays)

        final_type = rule.type
        final_category = updates.get("category", rule.category)
        valid = INCOME_CATEGORIES if final_type == TransactionType.INCOME else EXPENSE_CATEGORIES
        if final_category not in valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{final_category.value}' kategorisi '{final_type.value}' türü için geçerli değil.",
            )

        schedule_keys = {"frequency", "weekday_mask", "day_of_month", "time_of_day", "start_date", "end_date", "is_active"}
        reschedule = bool(schedule_keys & updates.keys())
        rule = await self.rules.update(rule, updates)
        if reschedule and rule.is_active:
            # Never re-post the past on an edit: next slot is strictly after now.
            rule.next_run_at = self.next_occurrence(rule, local_now_naive())
            await self.db.flush()
            await self.db.refresh(rule)
        return rule

    async def delete(self, user_id: str, rule_id: str) -> None:
        rule = await self.get_or_404(user_id, rule_id)
        await self.rules.delete(rule)  # posted transactions survive (FK ON DELETE SET NULL)

    async def post_now(self, user_id: str, rule_id: str) -> Transaction:
        """Manual "I just spent it" — posts immediately without touching the schedule."""
        rule = await self.get_or_404(user_id, rule_id)
        now = local_now_naive().replace(microsecond=0)
        tx = await self._post(rule, now)
        rule.last_posted_at = now
        await self.db.flush()
        try:
            await self.push.send_wallet_update(user_id, reason=f"{rule.name} şimdi düşüldü")
        except Exception:
            logger.exception("wallet push notification failed for user %s", user_id)
        return tx

    async def _post(self, rule: RecurringRule, slot: datetime) -> Transaction:
        return await self.transactions.create(
            user_id=rule.user_id,
            data={
                "type": rule.type,
                "category": rule.category,
                "amount": rule.amount,
                "description": rule.name,
                "payment_method": rule.payment_method,
                "transaction_date": slot,
                "source": TransactionSource.RECURRING,
                "recurring_rule_id": rule.id,
                "scheduled_for": slot,
            },
        )

    # ---- projections ---------------------------------------------------------
    async def upcoming(
        self, user_id: str, *, start: datetime, end: datetime, auto_post_only: bool = False
    ) -> list[UpcomingOccurrence]:
        today = local_today()
        items: list[UpcomingOccurrence] = []
        for rule in await self.rules.list_active_for_user(user_id):
            if auto_post_only and not rule.auto_post:
                continue
            # A slot that is due but not yet posted (job hasn't ticked) still counts as upcoming.
            scan_from = min(start, rule.next_run_at) if rule.next_run_at else start
            for slot in self.occurrences_between(rule, scan_from, end):
                items.append(
                    UpcomingOccurrence(
                        rule_id=rule.id, name=rule.name, type=rule.type, category=rule.category,
                        amount=_q(rule.amount), scheduled_for=slot, auto_post=rule.auto_post,
                        is_today=slot.date() == today,
                    )
                )
        items.sort(key=lambda i: i.scheduled_for)
        return items

    async def reserved_expenses_by_day(self, user_id: str, *, start: datetime, end: datetime) -> dict[date, Decimal]:
        """Auto-posting expense slots still ahead of us, grouped by day."""
        out: dict[date, Decimal] = {}
        for item in await self.upcoming(user_id, start=start, end=end, auto_post_only=True):
            if item.type == TransactionType.EXPENSE:
                out[item.scheduled_for.date()] = out.get(item.scheduled_for.date(), Decimal("0")) + item.amount
        return out

    # ---- scheduler entry point ----------------------------------------------
    async def post_due(self, now: datetime) -> list[tuple[RecurringRule, datetime]]:
        posted: list[tuple[RecurringRule, datetime]] = []
        for rule in await self.rules.list_due(now):
            slot = rule.next_run_at
            steps = 0
            while slot is not None and slot <= now and steps < self.MAX_SLOTS_PER_RUN:
                if rule.auto_post:
                    exists = await self.transactions.get_by_rule_slot(rule.id, slot)
                    if exists is None:
                        try:
                            await self._post(rule, slot)
                            posted.append((rule, slot))
                        except IntegrityError:
                            await self.db.rollback()  # lost a race: slot already posted
                    rule.last_posted_at = slot
                slot = self.next_occurrence(rule, slot)
                steps += 1
            rule.next_run_at = slot
            if slot is None:
                rule.is_active = False  # end_date reached — nothing more to schedule
        await self.db.flush()
        return posted


# ============================================================================
class PlanningService:
    """Adaptive daily allowance ("envelope" method) over the user's pay period
    (calendar month or ISO week):

        spendable        = income_basis - savings_goal
        reserved         = recurring expenses still to be auto-posted this period
        today_allowance  = (spendable - spent_before_today - reserved_future) / days_remaining
        remaining_today  = today_allowance - spent_today - reserved_today   (truly free)
        future_allowance = (spendable - spent_so_far - reserved) / (days_remaining - 1)

    Overspending one day lowers the remaining days' allowance and underspending
    raises it — the plan always resolves to the period's goal, with fixed costs
    already set aside.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.plans = SpendingPlanRepository(db)
        self.transactions = TransactionRepository(db)
        self.recurring = RecurringService(db)

    async def resolve_period_type(self, user_id: str, requested: Optional[PeriodType]) -> PeriodType:
        if requested is not None:
            return requested
        latest = await self.plans.get_latest(user_id)
        return latest.period_type if latest else PeriodType.MONTHLY

    async def get_plan(self, user_id: str, period_type: Optional[PeriodType], day: date) -> Optional[SpendingPlan]:
        ptype = await self.resolve_period_type(user_id, period_type)
        return await self.plans.get_for_period(user_id, ptype, period_start(day, ptype))

    async def upsert_plan(self, user_id: str, data: SpendingPlanUpsert) -> SpendingPlan:
        return await self.plans.upsert(
            user_id=user_id,
            period_type=data.period_type,
            period=data.period,
            fields={"savings_goal": data.savings_goal, "income_override": data.income_override},
        )

    async def daily_plan(self, user_id: str, day: date, period_type: Optional[PeriodType] = None) -> DailyPlanResponse:
        ptype = await self.resolve_period_type(user_id, period_type)
        start_day = period_start(day, ptype)
        start, end = period_bounds(start_day, ptype)
        n_days = days_in_period(start_day, ptype)
        symbol = settings.CURRENCY_SYMBOL

        # Explicit plan for this period, else the latest plan of the same type as a template.
        plan = await self.plans.get_for_period(user_id, ptype, start_day)
        if plan is None:
            latest = await self.plans.get_latest(user_id)
            plan = latest if latest is not None and latest.period_type == ptype else None
        savings_goal = Decimal(plan.savings_goal) if plan else Decimal("0")
        override = Decimal(plan.income_override) if plan is not None and plan.income_override is not None else None

        actual_income = await self.transactions.sum_amount(
            user_id, type_=TransactionType.INCOME, start_date=start, end_date=end
        )
        income_basis = override if override is not None else actual_income
        spendable = max(income_basis - savings_goal, Decimal("0"))

        totals = await self.transactions.daily_expense_totals(user_id, start_date=start, end_date=end)
        spent_before_today = sum((amt for d, amt in totals.items() if d < day), Decimal("0"))
        spent_today = totals.get(day, Decimal("0"))
        spent_so_far = spent_before_today + spent_today
        days_remaining = (end.date() - day).days

        # Fixed costs still ahead in this period (from now, or from the start of a future period).
        now = local_now_naive()
        reserve_from = max(now, start) if day == now.date() else datetime.combine(day, time.min)
        reserved_by_day = (
            await self.recurring.reserved_expenses_by_day(user_id, start=reserve_from, end=end)
            if reserve_from < end else {}
        )
        reserved_total = sum(reserved_by_day.values(), Decimal("0"))
        reserved_today = reserved_by_day.get(day, Decimal("0"))
        reserved_future = reserved_total - reserved_today

        base_daily = spendable / n_days
        today_allowance = max((spendable - spent_before_today - reserved_future) / days_remaining, Decimal("0"))
        remaining_today = today_allowance - spent_today - reserved_today
        remaining_total = spendable - spent_so_far
        free_remaining = remaining_total - reserved_total
        future_days = days_remaining - 1
        future_free = max(free_remaining, Decimal("0")) / future_days if future_days > 0 else Decimal("0")

        if income_basis <= 0:
            plan_status = "no_income"
        elif remaining_total < 0:
            plan_status = "over"
        elif remaining_today < 0 or today_allowance < base_daily * Decimal("0.7"):
            plan_status = "tight"
        else:
            plan_status = "on_track"

        schedule: list[DailyScheduleItem] = []
        labels: list[str] = []
        planned_data: list[Optional[Decimal]] = []
        spent_data: list[Optional[Decimal]] = []
        for n in range(n_days):
            d = start_day + timedelta(days=n)
            reserved_d = reserved_by_day.get(d, Decimal("0"))
            if d < day:
                planned, spent = base_daily, totals.get(d, Decimal("0"))
            elif d == day:
                planned, spent = today_allowance, spent_today
            else:
                planned, spent = future_free + reserved_d, None
            diff = planned - spent if spent is not None else None
            schedule.append(
                DailyScheduleItem(
                    day=d,
                    weekday=WEEKDAYS_TR[d.weekday()],
                    planned=_q(planned),
                    reserved=_q(reserved_d),
                    spent=_q(spent) if spent is not None else None,
                    difference=_q(diff) if diff is not None else None,
                    is_today=d == day,
                    is_past=d < day,
                )
            )
            labels.append(f"{WEEKDAYS_TR[d.weekday()]} {d.day}" if ptype == PeriodType.WEEKLY else str(d.day))
            planned_data.append(_q(planned))
            spent_data.append(_q(spent) if spent is not None else None)

        chart = TrendChartResponse(
            labels=labels,
            datasets=[ChartDataset(label="Planlanan", data=planned_data), ChartDataset(label="Harcanan", data=spent_data)],
            raw=[],
        )

        return DailyPlanResponse(
            period_type=ptype,
            period=start_day,
            period_end=period_end_exclusive(start_day, ptype) - timedelta(days=1),
            period_label=period_label_tr(start_day, ptype),
            today=day,
            days_in_period=n_days,
            days_remaining=days_remaining,
            income_basis=_q(income_basis),
            income_is_override=override is not None,
            savings_goal=_q(savings_goal),
            spendable_total=_q(spendable),
            reserved_total=_q(reserved_total),
            spent_so_far=_q(spent_so_far),
            spent_today=_q(spent_today),
            remaining_total=_q(remaining_total),
            free_remaining=_q(free_remaining),
            base_daily_allowance=_q(base_daily),
            today_allowance=_q(today_allowance),
            remaining_today=_q(remaining_today),
            status=plan_status,
            status_message=status_line(
                plan_status, remaining_today=_q(remaining_today), today_allowance=_q(today_allowance), symbol=symbol
            ),
            schedule=schedule,
            chart=chart,
        )


# ============================================================================
class TaskService:
    """Görevler (to-do list) — a general life-organizer that lives next to the
    wallet because the user already has the app + push notifications set up,
    not because it has anything to do with money."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.tasks = TaskRepository(db)
        self.push = PushService(db)

    async def list_for_user(self, user_id: str, *, include_done: bool) -> list[Task]:
        return list(await self.tasks.list_for_user(user_id, include_done=include_done))

    async def get_or_404(self, user_id: str, task_id: str) -> Task:
        task = await self.tasks.get_by_id(task_id, user_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Görev bulunamadı.")
        return task

    async def create(self, user_id: str, data: TaskCreate) -> Task:
        payload = data.model_dump()
        if payload.get("due_at"):
            payload["due_at"] = to_local_naive(payload["due_at"])
        return await self.tasks.create(user_id=user_id, data=payload)

    async def update(self, user_id: str, task_id: str, data: TaskUpdate) -> Task:
        task = await self.get_or_404(user_id, task_id)
        updates = data.model_dump(exclude_unset=True)
        if updates.get("due_at"):
            updates["due_at"] = to_local_naive(updates["due_at"])
        if "remind" in updates and updates["remind"] and not (updates.get("due_at") or task.due_at):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Hatırlatma için bir tarih/saat seçmelisin."
            )
        if updates.get("due_at"):
            # A new due date means any past reminder no longer applies.
            updates["reminded_at"] = None
        if updates.get("is_done"):
            updates["done_at"] = local_now_naive()
        elif updates.get("is_done") is False:
            updates["done_at"] = None
        if not updates:
            return task
        return await self.tasks.update(task, updates)

    async def delete(self, user_id: str, task_id: str) -> None:
        task = await self.get_or_404(user_id, task_id)
        await self.tasks.delete(task)

    async def send_due_reminders(self, now: Optional[datetime] = None) -> int:
        """Push a reminder for every due, unreminded task (idempotent via
        `reminded_at`) — called by the local scheduler loop and the
        `/api/cron/task-reminders` endpoint (Vercel + the GitHub Actions pinger)."""
        due = await self.tasks.list_due_reminders(now or local_now_naive())
        sent = 0
        for task in due:
            result = await self.push.send_to_user(
                task.user_id,
                title="⏰ Hatırlatma",
                body=task.title + (f"\n{task.notes}" if task.notes else ""),
                url="/#tasks",
                tag=f"task-{task.id}",
            )
            task.reminded_at = local_now_naive()
            sent += result.sent
        if due:
            await self.db.flush()
        return sent


# ============================================================================
class WalletService:
    """The "kasa" view: balance, what's committed to fixed costs, what's free."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.transactions = TransactionRepository(db)
        self.planning = PlanningService(db)
        self.recurring = RecurringService(db)

    async def overview(self, user_id: str) -> WalletResponse:
        today = local_today()
        now = local_now_naive()
        plan = await self.planning.daily_plan(user_id, today)
        upcoming = await self.recurring.upcoming(user_id, start=now, end=now + timedelta(days=7))
        day_start = datetime.combine(today, time.min)
        auto_today = await self.transactions.sum_amount(
            user_id, type_=TransactionType.EXPENSE, source=TransactionSource.RECURRING,
            start_date=day_start, end_date=day_start + timedelta(days=1),
        )
        return WalletResponse(
            balance_total=_q(await self.transactions.balance_total(user_id)),
            period_type=plan.period_type,
            period=plan.period,
            period_label=plan.period_label,
            period_income=plan.income_basis,
            period_spent=plan.spent_so_far,
            period_remaining=plan.remaining_total,
            reserved_upcoming=plan.reserved_total,
            free_remaining=plan.free_remaining,
            auto_posted_today=_q(auto_today),
            today_deductions=[u for u in upcoming if u.is_today],
            upcoming=upcoming[:20],
        )


# ============================================================================
class BackupService:
    """Consistent SQLite snapshots via `VACUUM INTO` (safe while the app runs
    thanks to WAL). Keeps the newest `KEEP` files in ./backups."""

    KEEP = 14
    BACKUP_DIR = PROJECT_ROOT / "backups"  # PROJECT_ROOT == DATA_DIR (next to the .exe when frozen)

    @classmethod
    def _backup_sync(cls) -> BackupResult:
        src = sqlite_file_path()
        if src is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dosya yedeği yalnızca SQLite için geçerli; PostgreSQL için sağlayıcının yedeğini kullan.",
            )
        cls.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        # Millisecond suffix: two backups in the same second (manual + nightly) must not collide.
        stamp = now.strftime("%Y-%m-%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
        dest = cls.BACKUP_DIR / f"finance_{stamp}.db"
        while dest.exists():
            dest = dest.with_name(dest.stem + "x.db")
        con = sqlite3.connect(str(src))
        try:
            con.execute("VACUUM INTO ?", (str(dest),))
        finally:
            con.close()
        for old in sorted(cls.BACKUP_DIR.glob("finance_*.db"))[: -cls.KEEP]:
            old.unlink(missing_ok=True)
        return BackupResult(path=str(dest), size_bytes=dest.stat().st_size, created_at=datetime.now(timezone.utc))

    @classmethod
    async def backup_now(cls) -> BackupResult:
        return await asyncio.to_thread(cls._backup_sync)

    @classmethod
    def list_backups(cls) -> list[BackupResult]:
        if not cls.BACKUP_DIR.exists():
            return []
        out = []
        for p in sorted(cls.BACKUP_DIR.glob("finance_*.db"), reverse=True):
            st = p.stat()
            out.append(BackupResult(path=str(p), size_bytes=st.st_size, created_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)))
        return out


# ============================================================================
class PushService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.subs = PushSubscriptionRepository(db)

    async def subscribe(self, user_id: str, data: PushSubscriptionIn, user_agent: Optional[str]) -> PushSubscription:
        return await self.subs.upsert(
            user_id=user_id,
            endpoint=data.endpoint,
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
            user_agent=(user_agent or "")[:300] or None,
        )

    async def unsubscribe(self, user_id: str, endpoint: str) -> None:
        sub = await self.subs.get_by_endpoint(endpoint)
        if sub is None or sub.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Abonelik bulunamadı.")
        await self.subs.delete(sub)

    async def list_for_user(self, user_id: str) -> list[PushSubscription]:
        return list(await self.subs.list_for_user(user_id))

    async def send_to_user(
        self,
        user_id: str,
        *,
        title: str,
        body: str,
        url: str = "/",
        tag: Optional[str] = None,
        actions: Optional[list[dict]] = None,
        renotify: bool = True,
    ) -> PushTestResult:
        """Fan a notification out to every device of one user. Stale
        subscriptions (push service says 404/410) are pruned as we go.

        `tag` + `renotify=False` makes an update *replace* the previous
        notification of the same tag in place — no new sound/vibration if it's
        still on screen, but it reappears normally if the user had dismissed
        it. That's how `send_wallet_update` below keeps a single "Kasa"
        notification quietly in sync instead of stacking up a new one per event.
        """
        subs = await self.subs.list_for_user(user_id)
        payload = {
            "title": title,
            "body": body,
            "url": url,
            "tag": tag or "finance",
            "renotify": renotify,
            "icon": "/static/icons/icon-192.png",
            "badge": "/static/icons/icon-192.png",
        }
        if actions:
            payload["actions"] = actions
        sent = failed = removed = 0
        for sub in subs:
            ok, stale, _ = await asyncio.to_thread(
                send_web_push, endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth, payload=payload
            )
            if ok:
                sent += 1
            else:
                failed += 1
                if stale:
                    await self.subs.delete(sub)
                    removed += 1
        return PushTestResult(sent=sent, failed=failed, removed_stale=removed)

    WALLET_TAG = "wallet-balance"

    async def send_wallet_update(self, user_id: str, *, reason: Optional[str] = None) -> PushTestResult:
        """The always-current "Kasa" notification: current balance, a
        + Gelir / − Gider quick-action pair, same tag every time so it updates
        in place instead of piling up. Call this after anything that changes
        the balance (manual add/edit/delete, an auto-post, "şimdi düş").

        A web notification can never be made truly undismissable — that's an
        Android *native app* capability (foreground service), not something a
        website/PWA can request — so this is the closest real equivalent:
        it re-appears the moment anything changes, and again every morning
        (see `send_daily_motivation` in scheduler.py) even if it was swiped away.
        """
        balance = await TransactionRepository(self.db).balance_total(user_id)
        symbol = settings.CURRENCY_SYMBOL
        body = f"Güncel bakiye: {fmt_money(balance, symbol)}"
        if reason:
            body += f"\n{reason}"
        return await self.send_to_user(
            user_id,
            title="💰 Kasa",
            body=body,
            url="/#today",
            tag=self.WALLET_TAG,
            renotify=False,
            actions=[
                {"action": "quick-income", "title": "+ Gelir"},
                {"action": "quick-expense", "title": "− Gider"},
            ],
        )


# ============================================================================
class MotivationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.messages = DailyMessageRepository(db)
        self.planning = PlanningService(db)
        self.push = PushService(db)

    async def get_or_create(self, user: User, today: date) -> DailyMessage:
        existing = await self.messages.get_for_date(user.id, today)
        if existing:
            return existing

        plan = await self.planning.daily_plan(user.id, today)

        # Yesterday's verdict comes from a plan anchored *on* yesterday, so
        # "planned" is exactly the allowance the user was shown that morning.
        yesterday = today - timedelta(days=1)
        y_plan = await self.planning.daily_plan(user.id, yesterday)
        y_item = next((i for i in y_plan.schedule if i.day == yesterday), None)

        first_name = user.full_name.split()[0] if user.full_name else None
        title, body, quote = compose_daily_message(
            first_name=first_name,
            today=today,
            status=plan.status,
            today_allowance=plan.remaining_today if plan.remaining_today > 0 else plan.today_allowance,
            remaining_total=plan.remaining_total,
            days_remaining=plan.days_remaining,
            yesterday_planned=y_item.planned if y_item and y_plan.status != "no_income" else None,
            yesterday_spent=y_item.spent if y_item else None,
            symbol=settings.CURRENCY_SYMBOL,
            seed=f"{user.id}:{today.isoformat()}",
            period_word="Hafta" if plan.period_type == PeriodType.WEEKLY else "Ay",
            reserved_total=plan.reserved_total,
        )
        return await self.messages.create(
            user_id=user.id, message_date=today, title=title, body=body, quote=quote
        )

    async def history(self, user_id: str, *, limit: int) -> list[DailyMessage]:
        return list(await self.messages.list_recent(user_id, limit=limit))

    async def push_today(self, user: User, today: date) -> PushTestResult:
        message = await self.get_or_create(user, today)
        result = await self.push.send_to_user(
            user.id,
            title=message.title,
            body=f"{message.body}\n\n“{message.quote}”",
            url="/",
            tag="daily-motivation",
        )
        if result.sent > 0:
            await self.messages.mark_pushed(message, datetime.now(timezone.utc))
        return result
