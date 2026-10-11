"""Milestone 03 secure ingestion metadata.

Revision ID: 8c2b58e7d8f1
Revises: f39d9ce47eec
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c2b58e7d8f1"
down_revision: str | None = "f39d9ce47eec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint("uq_document_versions_sha256", type_="unique")
        batch_op.add_column(
            sa.Column("byte_size", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("extracted_uri", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("metadata_uri", sa.Text(), nullable=True))
        batch_op.create_index("ix_document_versions_sha256", ["sha256"], unique=False)

    with op.batch_alter_table("ingestion_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(sa.Column("last_completed_stage", sa.String(length=40)))
        batch_op.add_column(
            sa.Column("processing_uri", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("processing_metadata", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True)))
        batch_op.create_unique_constraint(
            "uq_ingestion_jobs_document_version_id", ["document_version_id"]
        )
        batch_op.create_check_constraint(
            "ck_ingestion_jobs_valid_status",
            "status IN ('UPLOADED', 'VALIDATING', 'STORING', 'PARSING', "
            "'NORMALIZING', 'READY_FOR_COMPILATION', 'FAILED')",
        )

    with op.batch_alter_table("source_records") as batch_op:
        batch_op.add_column(sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("content", sa.Text(), server_default="", nullable=False))
        batch_op.create_unique_constraint(
            "uq_source_records_document_version_id", ["document_version_id", "ordinal"]
        )


def downgrade() -> None:
    with op.batch_alter_table("source_records") as batch_op:
        batch_op.drop_constraint("uq_source_records_document_version_id", type_="unique")
        batch_op.drop_column("content")
        batch_op.drop_column("ordinal")

    with op.batch_alter_table("ingestion_jobs") as batch_op:
        batch_op.drop_constraint("ck_ingestion_jobs_valid_status", type_="check")
        batch_op.drop_constraint("uq_ingestion_jobs_document_version_id", type_="unique")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("processing_metadata")
        batch_op.drop_column("processing_uri")
        batch_op.drop_column("last_completed_stage")
        batch_op.drop_column("attempt_count")

    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_index("ix_document_versions_sha256")
        batch_op.drop_column("metadata_uri")
        batch_op.drop_column("extracted_uri")
        batch_op.drop_column("byte_size")
        batch_op.create_unique_constraint("uq_document_versions_sha256", ["sha256"])
