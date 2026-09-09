"""
Repository layer — the only place that speaks raw SQLAlchemy queries.

Services depend on these repositories, never on `AsyncSession` directly for
anything beyond a plain `db.get(...)`. This keeps query logic centralized,
testable in isolation, and easy to swap (e.g. add caching) without touching
business logic.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import case

from app.models import (
    Budget,
    BudgetAlert,
    Category,
    DailyMessage,
    MonthlySnapshot,
    PeriodType,
    PushSubscription,
    RecurringRule,
    SpendingPlan,
    Transaction,
    TransactionSource,
    TransactionType,
    User,
)


def month_bounds(period: date) -> tuple[datetime, datetime]:
    """Return [start, end) datetime bounds for the calendar month containing `period`."""
    start = datetime(period.year, period.month, 1)
    if period.month == 12:
        end = datetime(period.year + 1, 1, 1)
    else:
        end = datetime(period.year, period.month + 1, 1)
    return start, end


def shift_month(period: date, delta_months: int) -> date:
    """Return the 1st of the month `delta_months` away from `period` (may be negative)."""
    total = period.year * 12 + (period.month - 1) + delta_months
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


# ============================================================================
class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[User]:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, *, email: str, hashed_password: str, full_name: Optional[str]) -> User:
        user = User(email=email, hashed_password=hashed_password, full_name=full_name)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def list_active(self) -> Sequence[User]:
        """Used by the scheduler to iterate every active user."""
        result = await self.db.execute(select(User).where(User.is_active.is_(True)))
        return result.scalars().all()


# ============================================================================
class TransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, transaction_id: str, user_id: str) -> Optional[Transaction]:
        result = await self.db.execute(
            select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, user_id: str, data: dict) -> Transaction:
        transaction = Transaction(user_id=user_id, **data)
        self.db.add(transaction)
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def get_by_rule_slot(self, rule_id: str, slot: datetime) -> Optional[Transaction]:
        """Idempotency probe for auto-posting (backed by uq_transaction_rule_slot)."""
        result = await self.db.execute(
            select(Transaction).where(
                Transaction.recurring_rule_id == rule_id, Transaction.scheduled_for == slot
            )
        )
        return result.scalar_one_or_none()

    async def update(self, transaction: Transaction, data: dict) -> Transaction:
        for key, value in data.items():
            setattr(transaction, key, value)
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def delete(self, transaction: Transaction) -> None:
        await self.db.delete(transaction)
        await self.db.flush()

    def _filtered_query(
        self,
        user_id: str,
        *,
        type_: Optional[TransactionType] = None,
        category: Optional[Category] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Select:
        query = select(Transaction).where(Transaction.user_id == user_id)
        if type_ is not None:
            query = query.where(Transaction.type == type_)
        if category is not None:
            query = query.where(Transaction.category == category)
        if start_date is not None:
            query = query.where(Transaction.transaction_date >= start_date)
        if end_date is not None:
            query = query.where(Transaction.transaction_date < end_date)
        return query

    async def list_paginated(
        self,
        user_id: str,
        *,
        type_: Optional[TransactionType] = None,
        category: Optional[Category] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Transaction], int]:
        base = self._filtered_query(
            user_id, type_=type_, category=category, start_date=start_date, end_date=end_date
        )

        count_result = await self.db.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar_one()

        result = await self.db.execute(
            base.order_by(Transaction.transaction_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), total

    async def sum_amount(
        self,
        user_id: str,
        *,
        type_: Optional[TransactionType] = None,
        category: Optional[Category] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        source: Optional[TransactionSource] = None,
    ) -> Decimal:
        query = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id
        )
        if type_ is not None:
            query = query.where(Transaction.type == type_)
        if category is not None:
            query = query.where(Transaction.category == category)
        if source is not None:
            query = query.where(Transaction.source == source)
        if start_date is not None:
            query = query.where(Transaction.transaction_date >= start_date)
        if end_date is not None:
            query = query.where(Transaction.transaction_date < end_date)
        result = await self.db.execute(query)
        return Decimal(result.scalar_one() or 0)

    async def balance_total(self, user_id: str) -> Decimal:
        """All-time wallet balance: income adds, expense subtracts — one aggregate query."""
        signed = case(
            (Transaction.type == TransactionType.INCOME, Transaction.amount),
            else_=-Transaction.amount,
        )
        result = await self.db.execute(
            select(func.coalesce(func.sum(signed), 0)).where(Transaction.user_id == user_id)
        )
        return Decimal(result.scalar_one() or 0)

    async def category_breakdown(
        self, user_id: str, *, start_date: datetime, end_date: datetime
    ) -> Sequence[tuple[Category, TransactionType, Decimal]]:
        query = (
            select(Transaction.category, Transaction.type, func.sum(Transaction.amount))
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date < end_date,
            )
            .group_by(Transaction.category, Transaction.type)
        )
        result = await self.db.execute(query)
        return result.all()

    async def count_in_range(self, user_id: str, *, start_date: datetime, end_date: datetime) -> int:
        query = select(func.count(Transaction.id)).where(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date < end_date,
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def daily_expense_totals(
        self, user_id: str, *, start_date: datetime, end_date: datetime
    ) -> dict[date, Decimal]:
        """Expense sum per calendar day in [start, end) — feeds the daily plan schedule.
        `func.date()` works on both SQLite and PostgreSQL."""
        day_col = func.date(Transaction.transaction_date)
        query = (
            select(day_col, func.sum(Transaction.amount))
            .where(
                Transaction.user_id == user_id,
                Transaction.type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date < end_date,
            )
            .group_by(day_col)
        )
        result = await self.db.execute(query)
        totals: dict[date, Decimal] = {}
        for day_value, amount in result.all():
            # SQLite returns the date as an ISO string; Postgres as a `date`.
            day = day_value if isinstance(day_value, date) else date.fromisoformat(str(day_value)[:10])
            totals[day] = Decimal(amount or 0)
        return totals


# ============================================================================
class BudgetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, budget_id: str, user_id: str) -> Optional[Budget]:
        result = await self.db.execute(
            select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_category_period(
        self, user_id: str, category: Category, period: date
    ) -> Optional[Budget]:
        result = await self.db.execute(
            select(Budget).where(
                Budget.user_id == user_id, Budget.category == category, Budget.period == period
            )
        )
        return result.scalar_one_or_none()

    async def list_for_period(self, user_id: str, period: date) -> Sequence[Budget]:
        result = await self.db.execute(
            select(Budget).where(Budget.user_id == user_id, Budget.period == period)
        )
        return result.scalars().all()

    async def create(self, *, user_id: str, category: Category, monthly_limit: Decimal, period: date) -> Budget:
        budget = Budget(user_id=user_id, category=category, monthly_limit=monthly_limit, period=period)
        self.db.add(budget)
        await self.db.flush()
        await self.db.refresh(budget)
        return budget

    async def update_limit(self, budget: Budget, monthly_limit: Decimal) -> Budget:
        budget.monthly_limit = monthly_limit
        await self.db.flush()
        await self.db.refresh(budget)
        return budget

    async def delete(self, budget: Budget) -> None:
        await self.db.delete(budget)
        await self.db.flush()


# ============================================================================
class AlertRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, alert_id: str, user_id: str) -> Optional[BudgetAlert]:
        result = await self.db.execute(
            select(BudgetAlert).where(BudgetAlert.id == alert_id, BudgetAlert.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_existing(self, user_id: str, category: Category, period: date) -> Optional[BudgetAlert]:
        result = await self.db.execute(
            select(BudgetAlert).where(
                BudgetAlert.user_id == user_id,
                BudgetAlert.category == category,
                BudgetAlert.period == period,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str, *, unread_only: bool = False) -> Sequence[BudgetAlert]:
        query = select(BudgetAlert).where(BudgetAlert.user_id == user_id)
        if unread_only:
            query = query.where(BudgetAlert.is_read.is_(False))
        result = await self.db.execute(query.order_by(BudgetAlert.created_at.desc()))
        return result.scalars().all()

    async def upsert(
        self, *, user_id: str, category: Category, period: date, fields: dict
    ) -> tuple[BudgetAlert, bool]:
        """Returns `(alert, created)` so callers can notify only on *new* alerts."""
        existing = await self.get_existing(user_id, category, period)
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.db.flush()
            return existing, False
        alert = BudgetAlert(user_id=user_id, category=category, period=period, **fields)
        self.db.add(alert)
        await self.db.flush()
        return alert, True

    async def mark_read(self, alert: BudgetAlert) -> BudgetAlert:
        alert.is_read = True
        await self.db.flush()
        await self.db.refresh(alert)
        return alert


# ============================================================================
class SnapshotRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_period(self, user_id: str, period: date) -> Optional[MonthlySnapshot]:
        result = await self.db.execute(
            select(MonthlySnapshot).where(
                MonthlySnapshot.user_id == user_id, MonthlySnapshot.period == period
            )
        )
        return result.scalar_one_or_none()

    async def list_recent(self, user_id: str, *, months: int) -> Sequence[MonthlySnapshot]:
        result = await self.db.execute(
            select(MonthlySnapshot)
            .where(MonthlySnapshot.user_id == user_id)
            .order_by(MonthlySnapshot.period.desc())
            .limit(months)
        )
        return result.scalars().all()

    async def upsert(self, *, user_id: str, period: date, fields: dict) -> MonthlySnapshot:
        existing = await self.get_for_period(user_id, period)
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.db.flush()
            return existing
        snapshot = MonthlySnapshot(user_id=user_id, period=period, **fields)
        self.db.add(snapshot)
        await self.db.flush()
        return snapshot


# ============================================================================
class SpendingPlanRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_period(self, user_id: str, period_type: PeriodType, period: date) -> Optional[SpendingPlan]:
        result = await self.db.execute(
            select(SpendingPlan).where(
                SpendingPlan.user_id == user_id,
                SpendingPlan.period_type == period_type,
                SpendingPlan.period == period,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(self, user_id: str) -> Optional[SpendingPlan]:
        """Most recently *edited* plan — defines the user's current pay-period
        mode and serves as the template for periods with no explicit plan."""
        result = await self.db.execute(
            select(SpendingPlan)
            .where(SpendingPlan.user_id == user_id)
            .order_by(SpendingPlan.updated_at.desc(), SpendingPlan.period.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, *, user_id: str, period_type: PeriodType, period: date, fields: dict) -> SpendingPlan:
        existing = await self.get_for_period(user_id, period_type, period)
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        plan = SpendingPlan(user_id=user_id, period_type=period_type, period=period, **fields)
        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan


# ============================================================================
class RecurringRuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, rule_id: str, user_id: str) -> Optional[RecurringRule]:
        result = await self.db.execute(
            select(RecurringRule).where(RecurringRule.id == rule_id, RecurringRule.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> Sequence[RecurringRule]:
        result = await self.db.execute(
            select(RecurringRule)
            .where(RecurringRule.user_id == user_id)
            .order_by(RecurringRule.is_active.desc(), RecurringRule.time_of_day.asc(), RecurringRule.name.asc())
        )
        return result.scalars().all()

    async def list_active_for_user(self, user_id: str) -> Sequence[RecurringRule]:
        result = await self.db.execute(
            select(RecurringRule).where(RecurringRule.user_id == user_id, RecurringRule.is_active.is_(True))
        )
        return result.scalars().all()

    async def list_due(self, now: datetime) -> Sequence[RecurringRule]:
        """Active rules whose next slot is in the past (uses ix_rules_due)."""
        result = await self.db.execute(
            select(RecurringRule).where(
                RecurringRule.is_active.is_(True),
                RecurringRule.next_run_at.is_not(None),
                RecurringRule.next_run_at <= now,
            )
        )
        return result.scalars().all()

    async def create(self, *, user_id: str, fields: dict) -> RecurringRule:
        rule = RecurringRule(user_id=user_id, **fields)
        self.db.add(rule)
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def update(self, rule: RecurringRule, fields: dict) -> RecurringRule:
        for key, value in fields.items():
            setattr(rule, key, value)
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def delete(self, rule: RecurringRule) -> None:
        await self.db.delete(rule)
        await self.db.flush()


# ============================================================================
class PushSubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_endpoint(self, endpoint: str) -> Optional[PushSubscription]:
        result = await self.db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> Sequence[PushSubscription]:
        result = await self.db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        return result.scalars().all()

    async def upsert(
        self, *, user_id: str, endpoint: str, p256dh: str, auth: str, user_agent: Optional[str]
    ) -> PushSubscription:
        existing = await self.get_by_endpoint(endpoint)
        if existing:
            # Same device re-subscribing (possibly as a different user) — re-own it.
            existing.user_id = user_id
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        sub = PushSubscription(
            user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent
        )
        self.db.add(sub)
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def delete(self, sub: PushSubscription) -> None:
        await self.db.delete(sub)
        await self.db.flush()


# ============================================================================
class DailyMessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_date(self, user_id: str, message_date: date) -> Optional[DailyMessage]:
        result = await self.db.execute(
            select(DailyMessage).where(
                DailyMessage.user_id == user_id, DailyMessage.message_date == message_date
            )
        )
        return result.scalar_one_or_none()

    async def list_recent(self, user_id: str, *, limit: int) -> Sequence[DailyMessage]:
        result = await self.db.execute(
            select(DailyMessage)
            .where(DailyMessage.user_id == user_id)
            .order_by(DailyMessage.message_date.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def create(self, *, user_id: str, message_date: date, title: str, body: str, quote: str) -> DailyMessage:
        message = DailyMessage(
            user_id=user_id, message_date=message_date, title=title, body=body, quote=quote
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def mark_pushed(self, message: DailyMessage, when: datetime) -> None:
        message.pushed_at = when
        await self.db.flush()
