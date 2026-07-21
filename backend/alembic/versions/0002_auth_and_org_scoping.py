"""add users table and organization_id scoping columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21
"""
import uuid
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BOOTSTRAP_EMAIL = "admin@example.com"
BOOTSTRAP_PASSWORD = "changeme123"

# (table, whether the FK should cascade-delete on organization removal)
ORG_SCOPED_TABLES = ["documents", "laws", "canonical_items", "checklist_periods", "org_status"]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    for table in ORG_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    bind = op.get_bind()
    for table in ORG_SCOPED_TABLES:
        bind.execute(
            sa.text(f"UPDATE {table} SET organization_id = :org_id"),
            {"org_id": DEFAULT_ORG_ID},
        )

    for table in ORG_SCOPED_TABLES:
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_organization_id",
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Bootstrap admin account for the pre-existing default org's dev data.
    hashed = bcrypt.hashpw(BOOTSTRAP_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    bind.execute(
        sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password) "
            "VALUES (:id, :org_id, :email, :hashed) ON CONFLICT (email) DO NOTHING"
        ),
        {"id": uuid.uuid4(), "org_id": DEFAULT_ORG_ID, "email": BOOTSTRAP_EMAIL, "hashed": hashed},
    )


def downgrade() -> None:
    for table in ORG_SCOPED_TABLES:
        op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
    op.drop_table("users")
