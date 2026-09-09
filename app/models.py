"""
SQLAlchemy 2.0 ORM models (the persistence layer).

Design notes:
    - Primary keys are UUID strings (portable across SQLite demo / Postgres
      production, and safe to expose in URLs without leaking row counts).
    - Money is stored as `Numeric(12, 2)` — never `Float` — to avoid binary
      floating-point rounding errors in financial arithmetic.
    - `Category` is a single enum shared by income & expense transactions;
      `INCOME_CATEGORIES` / `EXPENSE_CATEGORIES` define which categories are
      valid for which transaction type, enforced at the schema layer.
    - All user-owned tables cascade-delete with the user and carry composite
      indexes matching the query patterns used by the analytics/service layer.
"""
import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Boolean,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class Category(str, enum.Enum):
    # --- Income categories -----------------------------------------------
    SALARY = "salary"
    FREELANCE = "freelance"
    INVESTMENT = "investment"
    GIFT = "gift"
    OTHER_INCOME = "other_income"
    # --- Expense categories -----------------------------------------------
    FOOD_DINING = "food_dining"
    GROCERIES = "groceries"
    TRANSPORTATION = "transportation"
    HOUSING = "housing"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    EDUCATION = "education"
    TRAVEL = "travel"
    INSURANCE = "insurance"
    SAVINGS_TRANSFER = "savings_transfer"
    DEBT_PAYMENT = "debt_payment"
    SUBSCRIPTIONS = "subscriptions"
    OTHER_EXPENSE = "other_expense"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_PAYMENT = "mobile_payment"
    OTHER = "other"


class PeriodType(str, enum.Enum):
    """How the user gets paid / plans: per calendar month or per ISO week."""

    MONTHLY = "monthly"
    WEEKLY = "weekly"


class Frequency(str, enum.Enum):
    """Recurrence of a scheduled (fixed) transaction."""

    DAILY = "daily"
    WEEKLY = "weekly"    # on the weekdays selected in `weekday_mask`
    MONTHLY = "monthly"  # on `day_of_month` (clamped to the month's length)


class TransactionSource(str, enum.Enum):
    MANUAL = "manual"
    RECURRING = "recurring"  # auto-posted by a RecurringRule


INCOME_CATEGORIES: set[Category] = {
    Category.SALARY,
    Category.FREELANCE,
    Category.INVESTMENT,
    Category.GIFT,
    Category.OTHER_INCOME,
}
EXPENSE_CATEGORIES: set[Category] = set(Category) - INCOME_CATEGORIES


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    budgets: Mapped[list["Budget"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list["BudgetAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    snapshots: Mapped[list["MonthlySnapshot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    spending_plans: Mapped[list["SpendingPlan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    daily_messages: Mapped[list["DailyMessage"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    recurring_rules: Mapped[list["RecurringRule"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email}>"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        # Idempotency guarantee for auto-posting: one row per (rule, scheduled slot).
        # NULLs are distinct in UNIQUE on both SQLite and Postgres, so manual rows are unaffected.
        UniqueConstraint("recurring_rule_id", "scheduled_for", name="uq_transaction_rule_slot"),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        Index("ix_transactions_user_category", "user_id", "category"),
        Index("ix_transactions_user_type", "user_id", "type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, name="transaction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    category: Mapped[Category] = mapped_column(
        SAEnum(Category, name="category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, name="payment_method", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PaymentMethod.OTHER,
    )
    # When the transaction actually occurred (as opposed to `created_at`,
    # when the row was written) — this is what all analytics group by.
    # Stored as naive *local wall-clock time* in SCHEDULER_TIMEZONE (see
    # app/timeutils.py) so daily grouping matches the user's calendar day.
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    # Provenance. A deleted rule keeps its posted history (ON DELETE SET NULL);
    # `source` survives that and still says the row was auto-posted.
    source: Mapped[TransactionSource] = mapped_column(
        SAEnum(TransactionSource, name="transaction_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TransactionSource.MANUAL,
        server_default=TransactionSource.MANUAL.value,
    )
    recurring_rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("recurring_rules.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions")
    recurring_rule: Mapped["RecurringRule | None"] = relationship(back_populates="transactions")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction id={self.id} {self.type}={self.amount} category={self.category}>"


class RecurringRule(Base):
    """A fixed, scheduled transaction ("Yemek 150 ₺ her gün 12:30").

    The scheduler posts a real `Transaction` for every due slot when
    `auto_post` is on; either way the upcoming slots are shown to the user as
    *reserved* money and subtracted from the free daily allowance.
    `next_run_at` is the single source of truth for "what's due" and is
    advanced atomically together with each posted row.
    """

    __tablename__ = "recurring_rules"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_rule_amount_positive"),
        CheckConstraint("weekday_mask >= 0 AND weekday_mask <= 127", name="ck_rule_weekday_mask"),
        CheckConstraint("day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 31)", name="ck_rule_dom"),
        Index("ix_rules_due", "is_active", "next_run_at"),
        Index("ix_rules_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # "Öğle yemeği"
    type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, name="transaction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    category: Mapped[Category] = mapped_column(
        SAEnum(Category, name="category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, name="payment_method", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PaymentMethod.CASH,
    )

    frequency: Mapped[Frequency] = mapped_column(
        SAEnum(Frequency, name="frequency", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    weekday_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=127)  # bit i = weekday i (Mon=0)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[time] = mapped_column(Time, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="recurring_rules")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="recurring_rule")

    @property
    def weekdays(self) -> list[int]:
        """Selected weekdays as a list (Mon=0 … Sun=6), decoded from `weekday_mask`."""
        return [i for i in range(7) if self.weekday_mask & (1 << i)]


class Budget(Base):
    """A monthly spending cap for one category. `period` is always
    normalized to the first day of the month it applies to."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "period", name="uq_budget_user_category_period"),
        CheckConstraint("monthly_limit > 0", name="ck_budget_limit_positive"),
        Index("ix_budgets_user_period", "user_id", "period"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[Category] = mapped_column(
        SAEnum(Category, name="category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="budgets")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Budget user={self.user_id} category={self.category} period={self.period} cap={self.monthly_limit}>"


class BudgetAlert(Base):
    """Generated by the daily APScheduler job when a category's spend
    crosses `BUDGET_ALERT_THRESHOLD` of its monthly cap. One alert row per
    (user, category, period) — the job upserts rather than duplicating."""

    __tablename__ = "budget_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "period", name="uq_alert_user_category_period"),
        Index("ix_alerts_user_read", "user_id", "is_read"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[Category] = mapped_column(
        SAEnum(Category, name="category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)

    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    utilization_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    spent_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    budget_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="alerts")


class MonthlySnapshot(Base):
    """Generated by the monthly APScheduler job (runs on the 1st) — a frozen
    summary of the previous calendar month's financial health, so historical
    analytics stay fast and stable even as raw transactions grow."""

    __tablename__ = "monthly_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "period", name="uq_snapshot_user_period"),
        Index("ix_snapshots_user_period", "user_id", "period"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)  # first day of the covered month

    total_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_expense: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net_savings: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    savings_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{ "category": "...", "type": "income|expense", "amount": "123.45", "percentage": "12.30" }, ...]
    category_breakdown: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="snapshots")


class SpendingPlan(Base):
    """Per-month planning inputs for the adaptive daily allowance:

        spendable = income_basis - savings_goal
        today's allowance = (spendable - spent_so_far) / days_remaining

    `monthly_income_override` lets a user who doesn't log salary as
    transactions still get a plan ("maaşım 30.000 ₺")."""

    __tablename__ = "spending_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "period_type", "period", name="uq_plan_user_type_period"),
        CheckConstraint("savings_goal >= 0", name="ck_plan_savings_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period_type: Mapped[PeriodType] = mapped_column(
        SAEnum(PeriodType, name="period_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PeriodType.MONTHLY,
        server_default=PeriodType.MONTHLY.value,
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)  # 1st of month, or Monday of week
    savings_goal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    income_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="spending_plans")


class PushSubscription(Base):
    """A browser/PWA Web Push subscription (one per device/browser profile)."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("ix_push_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="push_subscriptions")


class DailyMessage(Base):
    """The personalized motivational message generated for a user on a given
    day (by the 08:00 scheduler job, or lazily on first app open)."""

    __tablename__ = "daily_messages"
    __table_args__ = (UniqueConstraint("user_id", "message_date", name="uq_daily_message_user_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="daily_messages")
