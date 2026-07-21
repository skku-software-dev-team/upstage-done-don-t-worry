"""add checklist_periods and org_status.period_id

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "checklist_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    bind = op.get_bind()
    current_period_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO checklist_periods (id, label, is_current) "
            "VALUES (:id, '진행중', true)"
        ),
        {"id": current_period_id},
    )

    op.add_column(
        "org_status",
        sa.Column("period_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    bind.execute(
        sa.text("UPDATE org_status SET period_id = :id"),
        {"id": current_period_id},
    )
    op.alter_column("org_status", "period_id", nullable=False)
    op.create_foreign_key(
        "fk_org_status_period_id",
        "org_status",
        "checklist_periods",
        ["period_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_org_status_canonical_period", "org_status", ["canonical_id", "period_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_org_status_canonical_period", "org_status", type_="unique")
    op.drop_constraint("fk_org_status_period_id", "org_status", type_="foreignkey")
    op.drop_column("org_status", "period_id")
    op.drop_table("checklist_periods")
