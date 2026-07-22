"""add departments table and canonical_items.department_id

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-22
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEPARTMENTS = [
    "정보보안팀",
    "IT운영팀",
    "개발팀",
    "인사팀",
    "법무·컴플라이언스팀",
    "시설관리팀",
    "구매·외주관리팀",
    "경영지원팀",
]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
    )

    bind = op.get_bind()
    for name in DEPARTMENTS:
        bind.execute(
            sa.text("INSERT INTO departments (id, name) VALUES (:id, :name) ON CONFLICT (name) DO NOTHING"),
            {"id": uuid.uuid4(), "name": name},
        )

    op.add_column(
        "canonical_items",
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("canonical_items", "department_id")
    op.drop_table("departments")
