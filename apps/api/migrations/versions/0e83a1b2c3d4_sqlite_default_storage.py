"""Milestone 08.3 SQLite default storage safeguards.

Revision ID: 0e83a1b2c3d4
Revises: d91f3e7a4b22
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0e83a1b2c3d4"
down_revision: str | Sequence[str] | None = "d91f3e7a4b22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER audit_events_append_only_update
            BEFORE UPDATE ON audit_events
            BEGIN
              SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_append_only_delete
            BEFORE DELETE ON audit_events
            BEGIN
              SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
    op.execute(
        sa.text(
            "UPDATE application_versions "
            "SET app_version = '0.8.3', schema_version = 10, updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_versions "
            "SET app_version = '0.8.0', schema_version = 9, updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only_delete")
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only_update")
