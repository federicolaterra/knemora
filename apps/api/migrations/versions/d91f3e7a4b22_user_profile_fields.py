"""Add local user profile fields.

Revision ID: d91f3e7a4b22
Revises: c42a8e9f2d11
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d91f3e7a4b22"
down_revision: str | Sequence[str] | None = "c42a8e9f2d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("company", sa.String(length=200), nullable=True))
    op.add_column("users", sa.Column("visualization_name", sa.String(length=200), nullable=True))
    op.execute(
        sa.text(
            "UPDATE application_versions SET schema_version = 9, updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_versions SET schema_version = 8, updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )
    op.drop_column("users", "visualization_name")
    op.drop_column("users", "company")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
