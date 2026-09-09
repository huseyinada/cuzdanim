"""initial schema

Revision ID: 319ece25826e
Revises:
Create Date: 2026-09-08 11:07:20.341593

Dialect note: the `category` enum is shared by three tables. On PostgreSQL,
letting each `create_table` emit its own `CREATE TYPE` fails on the second
table, so enum types are created once up front (checkfirst) and the columns
use `create_type=False`. On SQLite enums are plain VARCHARs and nothing
extra is needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "319ece25826e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRANSACTION_TYPES = ("income", "expense")
CATEGORIES = (
    "salary", "freelance", "investment", "gift", "other_income",
    "food_dining", "groceries", "transportation", "housing", "utilities", "healthcare",
    "entertainment", "shopping", "education", "travel", "insurance", "savings_transfer",
    "debt_payment", "subscriptions", "other_expense",
)
PAYMENT_METHODS = ("cash", "credit_card", "debit_card", "bank_transfer", "mobile_payment", "other")
ENUMS = (
    (TRANSACTION_TYPES, "transaction_type"),
    (CATEGORIES, "category"),
    (PAYMENT_METHODS, "payment_method"),
)

NOW = sa.text("(CURRENT_TIMESTAMP)")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _enum(values: tuple[str, ...], name: str):
    """Column type for an enum: PG -> pre-created named type; others -> generic Enum."""
    if _is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    if _is_postgres():
        bind = op.get_bind()
        for values, name in ENUMS:
            postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "budget_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("category", _enum(CATEGORIES, "category"), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("threshold_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("utilization_percent", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("spent_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("budget_limit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "category", "period", name="uq_alert_user_category_period"),
    )
    op.create_index("ix_alerts_user_read", "budget_alerts", ["user_id", "is_read"], unique=False)

    op.create_table(
        "budgets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("category", _enum(CATEGORIES, "category"), nullable=False),
        sa.Column("monthly_limit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("monthly_limit > 0", name="ck_budget_limit_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "category", "period", name="uq_budget_user_category_period"),
    )
    op.create_index("ix_budgets_user_period", "budgets", ["user_id", "period"], unique=False)

    op.create_table(
        "daily_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("message_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "message_date", name="uq_daily_message_user_date"),
    )

    op.create_table(
        "monthly_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("total_income", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_expense", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("net_savings", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("savings_rate", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("category_breakdown", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period", name="uq_snapshot_user_period"),
    )
    op.create_index("ix_snapshots_user_period", "monthly_snapshots", ["user_id", "period"], unique=False)

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
    )
    op.create_index("ix_push_user", "push_subscriptions", ["user_id"], unique=False)

    op.create_table(
        "spending_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("savings_goal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("monthly_income_override", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("savings_goal >= 0", name="ck_plan_savings_nonneg"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period", name="uq_plan_user_period"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("type", _enum(TRANSACTION_TYPES, "transaction_type"), nullable=False),
        sa.Column("category", _enum(CATEGORIES, "category"), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_method", _enum(PAYMENT_METHODS, "payment_method"), nullable=False),
        sa.Column("transaction_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_user_category", "transactions", ["user_id", "category"], unique=False)
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "transaction_date"], unique=False)
    op.create_index("ix_transactions_user_type", "transactions", ["user_id", "type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_user_type", table_name="transactions")
    op.drop_index("ix_transactions_user_date", table_name="transactions")
    op.drop_index("ix_transactions_user_category", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("spending_plans")
    op.drop_index("ix_push_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index("ix_snapshots_user_period", table_name="monthly_snapshots")
    op.drop_table("monthly_snapshots")
    op.drop_table("daily_messages")
    op.drop_index("ix_budgets_user_period", table_name="budgets")
    op.drop_table("budgets")
    op.drop_index("ix_alerts_user_read", table_name="budget_alerts")
    op.drop_table("budget_alerts")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    if _is_postgres():
        bind = op.get_bind()
        for values, name in ENUMS:
            postgresql.ENUM(*values, name=name).drop(bind, checkfirst=True)
