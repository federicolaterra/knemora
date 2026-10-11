"""Milestone 08 application and knowledge schema version tracking.

Revision ID: c42a8e9f2d11
Revises: 5fd2a7619c10
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c42a8e9f2d11"
down_revision: str | Sequence[str] | None = "5fd2a7619c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_versions",
        sa.Column("component", sa.String(length=50), nullable=False),
        sa.Column("app_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("knowledge_schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("component"),
    )
    op.execute(
        sa.text(
            "INSERT INTO application_versions "
            "(component, app_version, schema_version, knowledge_schema_version) "
            "VALUES ('core', '0.8.0', 8, 1)"
        )
    )


def downgrade() -> None:
    op.drop_table("application_versions")
