"""Record the native Second Brain application release.

Revision ID: a084b7c9d2e1
Revises: 0e83a1b2c3d4
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a084b7c9d2e1"
down_revision: str | Sequence[str] | None = "0e83a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_versions "
            "SET app_version = '0.8.4', updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_versions "
            "SET app_version = '0.8.3', updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )
