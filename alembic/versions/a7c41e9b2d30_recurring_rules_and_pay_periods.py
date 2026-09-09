"""recurring rules, transaction provenance, weekly/monthly pay periods

Revision ID: a7c41e9b2d30
Revises: 319ece25826e
Create Date: 2026-09-08 12:30:00

Uses batch_alter_table so the ALTERs work on SQLite (table rebuild) and
emit plain ALTER TABLE on PostgreSQL. New PG enum types are created once
up front with checkfirst (same pattern as the initial migration).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c41e9b2d30"
down_revision: Union[str, None] = "319ece25826e"
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
FREQUENCIES = ("daily", "weekly", "monthly")
PERIOD_TYPES = ("monthly", "weekly")
SOURCES = ("manual", "recurring")
NEW_ENUMS = ((FREQUENCIES, "frequency"), (PERIOD_TYPES, "period_type"), (SOURCES, "transaction_source"))
NOW = sa.text("(CURRENT_TIMESTAMP)")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _enum(values, name):
    if _is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    if _is_postgres():
        bind = op.get_bind()
        for values, name in NEW_ENUMS:
            postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", _enum(TRANSACTION_TYPES, "transaction_type"), nullable=False),
        sa.Column("category", _enum(CATEGORIES, "category"), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_method", _enum(PAYMENT_METHODS, "payment_method"), nullable=False),
        sa.Column("frequency", _enum(FREQUENCIES, "frequency"), nullable=False),
        sa.Column("weekday_mask", sa.Integer(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("time_of_day", sa.Time(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("auto_post", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_posted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_rule_amount_positive"),
        sa.CheckConstraint("weekday_mask >= 0 AND weekday_mask <= 127", name="ck_rule_weekday_mask"),
        sa.CheckConstraint("day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 31)", name="ck_rule_dom"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rules_due", "recurring_rules", ["is_active", "next_run_at"], unique=False)
    op.create_index("ix_rules_user", "recurring_rules", ["user_id"], unique=False)

    with op.batch_alter_table("transactions") as batch:
        batch.add_column(
            sa.Column("source", _enum(SOURCES, "transaction_source"), nullable=False, server_default="manual")
        )
        batch.add_column(sa.Column("recurring_rule_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("scheduled_for", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_transactions_recurring_rule", "recurring_rules", ["recurring_rule_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_unique_constraint("uq_transaction_rule_slot", ["recurring_rule_id", "scheduled_for"])

    with op.batch_alter_table("spending_plans") as batch:
        batch.add_column(
            sa.Column("period_type", _enum(PERIOD_TYPES, "period_type"), nullable=False, server_default="monthly")
        )
        batch.alter_column("monthly_income_override", new_column_name="income_override")
        batch.drop_constraint("uq_plan_user_period", type_="unique")
        batch.create_unique_constraint("uq_plan_user_type_period", ["user_id", "period_type", "period"])


def downgrade() -> None:
    with op.batch_alter_table("spending_plans") as batch:
        batch.drop_constraint("uq_plan_user_type_period", type_="unique")
        batch.create_unique_constraint("uq_plan_user_period", ["user_id", "period"])
        batch.alter_column("income_override", new_column_name="monthly_income_override")
        batch.drop_column("period_type")

    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("uq_transaction_rule_slot", type_="unique")
        batch.drop_constraint("fk_transactions_recurring_rule", type_="foreignkey")
        batch.drop_column("scheduled_for")
        batch.drop_column("recurring_rule_id")
        batch.drop_column("source")

    op.drop_index("ix_rules_user", table_name="recurring_rules")
    op.drop_index("ix_rules_due", table_name="recurring_rules")
    op.drop_table("recurring_rules")

    if _is_postgres():
        bind = op.get_bind()
        for values, name in NEW_ENUMS:
            postgresql.ENUM(*values, name=name).drop(bind, checkfirst=True)
