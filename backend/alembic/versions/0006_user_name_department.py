"""add users.name and users.department_id

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=100), nullable=True))
    op.add_column(
        "users",
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "department_id")
    op.drop_column("users", "name")
