"""
Pydantic v2 schemas — the API contract layer.

Kept strictly separate from `models.py` (the persistence layer) so the wire
format can evolve independently of the database schema. Every response
model sets `model_config = ConfigDict(from_attributes=True)` so it can be
built directly from ORM instances (`Schema.model_validate(orm_obj)`).
"""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    Category,
    Frequency,
    PaymentMethod,
    PeriodType,
    TransactionSource,
    TransactionType,
)

# ============================================================================
# Auth / User
# ============================================================================
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=150)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Şifre en az bir rakam içermeli.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Şifre en az bir harf içermeli.")
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access_token expiry


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: str  # user id
    exp: int
    type: str  # "access" | "refresh"


# ============================================================================
# Transactions
# ============================================================================
class TransactionBase(BaseModel):
    type: TransactionType
    category: Category
    amount: Decimal = Field(gt=0, decimal_places=2, description="Positive monetary amount.")
    description: Optional[str] = Field(default=None, max_length=1000)
    payment_method: PaymentMethod = PaymentMethod.OTHER
    transaction_date: Optional[datetime] = None

    @model_validator(mode="after")
    def _category_matches_type(self) -> "TransactionBase":
        valid = INCOME_CATEGORIES if self.type == TransactionType.INCOME else EXPENSE_CATEGORIES
        if self.category not in valid:
            raise ValueError(
                f"'{self.category.value}' kategorisi '{self.type.value}' türü için geçerli değil."
            )
        return self


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    """All fields optional — PATCH-style partial update, validated as a whole
    against whatever the final merged type/category pairing would be."""

    type: Optional[TransactionType] = None
    category: Optional[Category] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    description: Optional[str] = Field(default=None, max_length=1000)
    payment_method: Optional[PaymentMethod] = None
    transaction_date: Optional[datetime] = None


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    type: TransactionType
    category: Category
    amount: Decimal
    description: Optional[str] = None
    payment_method: PaymentMethod
    transaction_date: datetime
    source: TransactionSource = TransactionSource.MANUAL
    recurring_rule_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Budgets
# ============================================================================
class BudgetCreate(BaseModel):
    category: Category
    monthly_limit: Decimal = Field(gt=0, decimal_places=2)
    period: date = Field(description="Any date within the target month; normalized to the 1st.")

    @field_validator("period")
    @classmethod
    def _normalize_to_month_start(cls, v: date) -> date:
        return v.replace(day=1)

    @model_validator(mode="after")
    def _expense_category_only(self) -> "BudgetCreate":
        if self.category not in EXPENSE_CATEGORIES:
            raise ValueError("Bütçe yalnızca gider kategorileri için tanımlanabilir.")
        return self


class BudgetUpdate(BaseModel):
    monthly_limit: Decimal = Field(gt=0, decimal_places=2)


class BudgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    category: Category
    monthly_limit: Decimal
    period: date
    created_at: datetime
    updated_at: datetime


class BudgetStatus(BaseModel):
    """Budget cap vs. actual spend for one category/month — drives the
    client-side progress bars and the 80%-threshold warning banner."""

    category: Category
    period: date
    monthly_limit: Decimal
    spent: Decimal
    remaining: Decimal
    utilization_percent: Decimal
    is_over_threshold: bool
    is_exceeded: bool


# ============================================================================
# Alerts
# ============================================================================
class BudgetAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: Category
    period: date
    threshold_percent: Decimal
    utilization_percent: Decimal
    spent_amount: Decimal
    budget_limit: Decimal
    message: str
    is_read: bool
    created_at: datetime


# ============================================================================
# Analytics (chart-ready shapes for Chart.js / Recharts)
# ============================================================================
class CategoryBreakdownItem(BaseModel):
    category: Category
    type: TransactionType
    amount: Decimal
    percentage: Decimal


class MonthlySummary(BaseModel):
    period: date
    total_income: Decimal
    total_expense: Decimal
    net_savings: Decimal
    savings_rate: Decimal = Field(description="net_savings / total_income * 100, 0 if no income.")
    transaction_count: int
    category_breakdown: list[CategoryBreakdownItem]
    previous_period_income: Optional[Decimal] = None
    previous_period_expense: Optional[Decimal] = None
    income_change_percent: Optional[Decimal] = None
    expense_change_percent: Optional[Decimal] = None


class TrendPoint(BaseModel):
    """One point on a monthly income-vs-expense trend line."""

    period: date
    label: str  # e.g. "Jan 2026" — ready to drop straight into a chart's labels array
    income: Decimal
    expense: Decimal
    net_savings: Decimal


class ChartDataset(BaseModel):
    label: str
    data: list[Optional[Decimal]]  # None = no data point (e.g. future days) — Chart.js renders a gap


class TrendChartResponse(BaseModel):
    """Chart.js/Recharts-ready: `labels` pairs positionally with each dataset's `data`."""

    labels: list[str]
    datasets: list[ChartDataset]
    raw: list[TrendPoint]


class DashboardResponse(BaseModel):
    """One aggregate call for a landing dashboard: current-month summary,
    a trailing trend chart, and any unread budget alerts."""

    current_month: MonthlySummary
    trend: TrendChartResponse
    unread_alerts: list[BudgetAlertRead]


# ============================================================================
# Daily spending plan ("günlük harcama çizelgesi")
# ============================================================================
class SpendingPlanUpsert(BaseModel):
    period_type: PeriodType = PeriodType.MONTHLY
    period: date = Field(default_factory=lambda: date.today(), description="Any date in the target period.")
    savings_goal: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    income_override: Optional[Decimal] = Field(
        default=None, gt=0, decimal_places=2,
        description="Monthly salary or weekly pay, if the user doesn't log income as transactions.",
    )

    @model_validator(mode="after")
    def _normalize_period(self) -> "SpendingPlanUpsert":
        from app.periods import period_start

        self.period = period_start(self.period, self.period_type)
        return self


class SpendingPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    period_type: PeriodType
    period: date
    savings_goal: Decimal
    income_override: Optional[Decimal] = None
    updated_at: datetime


class DailyScheduleItem(BaseModel):
    day: date
    weekday: str                 # localized short weekday label, e.g. "Pzt"
    planned: Decimal             # total expected spend that day (free allowance + reserved fixed costs)
    reserved: Decimal            # fixed/recurring expenses still to be auto-posted that day
    spent: Optional[Decimal]     # None for future days
    difference: Optional[Decimal]  # planned - spent (positive = under budget)
    is_today: bool
    is_past: bool


class DailyPlanResponse(BaseModel):
    period_type: PeriodType
    period: date                 # period start (1st of month / Monday)
    period_end: date             # last day of the period (inclusive)
    period_label: str            # "Eylül 2026" / "8–14 Eylül 2026"
    today: date
    days_in_period: int
    days_remaining: int          # including today
    income_basis: Decimal        # override if set, else actual income in the period
    income_is_override: bool
    savings_goal: Decimal
    spendable_total: Decimal     # income_basis - savings_goal
    reserved_total: Decimal      # upcoming recurring expenses (not yet posted) until period end
    spent_so_far: Decimal        # period-to-date expenses (incl. today, incl. auto-posted)
    spent_today: Decimal
    remaining_total: Decimal     # spendable_total - spent_so_far
    free_remaining: Decimal      # remaining_total - reserved_total  (truly free money)
    base_daily_allowance: Decimal    # spendable_total / days_in_period
    today_allowance: Decimal         # (spendable - spent_before_today - reserved_future) / days_remaining
    remaining_today: Decimal         # today_allowance - spent_today - reserved_today
    status: str                  # "on_track" | "tight" | "over" | "no_income"
    status_message: str
    schedule: list[DailyScheduleItem]
    chart: TrendChartResponse    # labels=days, datasets=[Planlanan, Harcanan]


# ============================================================================
# Recurring (fixed) transactions
# ============================================================================
class RecurringRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=120, description='e.g. "Öğle yemeği"')
    type: TransactionType = TransactionType.EXPENSE
    category: Category
    amount: Decimal = Field(gt=0, decimal_places=2)
    payment_method: PaymentMethod = PaymentMethod.CASH
    frequency: Frequency
    weekdays: list[int] = Field(default=[0, 1, 2, 3, 4, 5, 6], description="0=Mon … 6=Sun (weekly frequency)")
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31, description="monthly frequency")
    time_of_day: time
    start_date: date = Field(default_factory=lambda: date.today())
    end_date: Optional[date] = None
    auto_post: bool = Field(default=True, description="Post the expense automatically when the time comes.")

    @field_validator("weekdays")
    @classmethod
    def _weekdays_valid(cls, v: list[int]) -> list[int]:
        v = sorted(set(v))
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Haftanın günleri 0 (Pzt) ile 6 (Paz) arasında olmalı.")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "RecurringRuleBase":
        valid = INCOME_CATEGORIES if self.type == TransactionType.INCOME else EXPENSE_CATEGORIES
        if self.category not in valid:
            raise ValueError(f"'{self.category.value}' kategorisi '{self.type.value}' türü için geçerli değil.")
        if self.frequency == Frequency.WEEKLY and not self.weekdays:
            raise ValueError("Haftalık tekrar için en az bir gün seç.")
        if self.frequency == Frequency.MONTHLY and self.day_of_month is None:
            raise ValueError("Aylık tekrar için ayın gününü seç.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Bitiş tarihi başlangıçtan önce olamaz.")
        return self


class RecurringRuleCreate(RecurringRuleBase):
    pass


class RecurringRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    amount: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    category: Optional[Category] = None
    payment_method: Optional[PaymentMethod] = None
    frequency: Optional[Frequency] = None
    weekdays: Optional[list[int]] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    time_of_day: Optional[time] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    auto_post: Optional[bool] = None


class RecurringRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: TransactionType
    category: Category
    amount: Decimal
    payment_method: PaymentMethod
    frequency: Frequency
    weekdays: list[int]
    day_of_month: Optional[int] = None
    time_of_day: time
    start_date: date
    end_date: Optional[date] = None
    is_active: bool
    auto_post: bool
    next_run_at: Optional[datetime] = None
    last_posted_at: Optional[datetime] = None
    created_at: datetime


class UpcomingOccurrence(BaseModel):
    rule_id: str
    name: str
    type: TransactionType
    category: Category
    amount: Decimal
    scheduled_for: datetime
    auto_post: bool
    is_today: bool


class WalletResponse(BaseModel):
    """The "kasa": what you have, what's committed, what's really free."""

    balance_total: Decimal          # all-time income - all-time expenses
    period_type: PeriodType
    period: date
    period_label: str
    period_income: Decimal
    period_spent: Decimal
    period_remaining: Decimal       # spendable - spent
    reserved_upcoming: Decimal      # recurring expenses still due this period
    free_remaining: Decimal         # period_remaining - reserved_upcoming
    auto_posted_today: Decimal      # sum of recurring expenses already deducted today
    today_deductions: list[UpcomingOccurrence]
    upcoming: list[UpcomingOccurrence]  # next 7 days


class BackupResult(BaseModel):
    path: str
    size_bytes: int
    created_at: datetime


# ============================================================================
# Motivation & Push
# ============================================================================
class DailyMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_date: date
    title: str
    body: str
    quote: str
    pushed_at: Optional[datetime] = None


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    """Mirrors `PushSubscription.toJSON()` from the browser."""

    endpoint: str = Field(min_length=10)
    keys: PushKeys
    expirationTime: Optional[int] = None


class PushSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    endpoint: str
    user_agent: Optional[str] = None
    created_at: datetime


class VapidPublicKeyResponse(BaseModel):
    public_key: str


class PushTestResult(BaseModel):
    sent: int
    failed: int
    removed_stale: int
