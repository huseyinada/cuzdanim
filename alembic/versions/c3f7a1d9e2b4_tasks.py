"""tasks (life-organizer to-do list, unrelated to money)

Revision ID: c3f7a1d9e2b4
Revises: a7c41e9b2d30
Create Date: 2026-09-10 18:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f7a1d9e2b4"
down_revision: Union[str, None] = "a7c41e9b2d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_PRIORITIES = ("low", "normal", "high")
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
        postgresql.ENUM(*TASK_PRIORITIES, name="task_priority").create(bind, checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("priority", _enum(TASK_PRIORITIES, "task_priority"), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("remind", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_user_done", "tasks", ["user_id", "is_done"], unique=False)
    op.create_index("ix_tasks_due", "tasks", ["remind", "is_done", "due_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_due", table_name="tasks")
    op.drop_index("ix_tasks_user_done", table_name="tasks")
    op.drop_table("tasks")

    if _is_postgres():
        bind = op.get_bind()
        postgresql.ENUM(*TASK_PRIORITIES, name="task_priority").drop(bind, checkfirst=True)
