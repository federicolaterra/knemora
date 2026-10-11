"""Add durable source-deletion operations.

Revision ID: e6b4c7d9a201
Revises: a084b7c9d2e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6b4c7d9a201"
down_revision: str | Sequence[str] | None = "a084b7c9d2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_deletion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("display_filename", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("target_version_ids", sa.JSON(), nullable=False),
        sa.Column("artifact_uris", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')",
            name="valid_source_deletion_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "document_id"),
    )
    op.create_index("ix_source_deletion_jobs_owner_id", "source_deletion_jobs", ["owner_id"])
    op.create_index("ix_source_deletion_jobs_document_id", "source_deletion_jobs", ["document_id"])
    op.create_index("ix_source_deletion_jobs_status", "source_deletion_jobs", ["status"])
    op.create_index(
        "ix_source_deletion_jobs_lease_expires_at",
        "source_deletion_jobs",
        ["lease_expires_at"],
    )
    op.execute(
        sa.text(
            "UPDATE application_versions SET schema_version = 11, "
            "updated_at = CURRENT_TIMESTAMP WHERE component = 'core'"
        )
    )


def downgrade() -> None:
    op.drop_table("source_deletion_jobs")
    op.execute(
        sa.text(
            "UPDATE application_versions SET schema_version = 10, "
            "updated_at = CURRENT_TIMESTAMP WHERE component = 'core'"
        )
    )
