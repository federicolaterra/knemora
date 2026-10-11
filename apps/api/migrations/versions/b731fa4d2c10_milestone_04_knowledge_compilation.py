"""milestone 04 knowledge compilation jobs

Revision ID: b731fa4d2c10
Revises: a4d16f2cb903
Create Date: 2026-09-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b731fa4d2c10"
down_revision: str | Sequence[str] | None = "a4d16f2cb903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_compilation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("compilation_version", sa.String(length=100), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_completed_stage", sa.String(length=40), nullable=True),
        sa.Column("proposal", sa.JSON(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'ANALYZING', 'VALIDATING', 'APPLYING', "
            "'INDEXING', 'LINTING', 'COMPLETED', 'FAILED')",
            name=op.f("ck_knowledge_compilation_jobs_valid_knowledge_compilation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_knowledge_compilation_jobs_document_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_compilation_jobs")),
        sa.UniqueConstraint(
            "document_version_id",
            name=op.f("uq_knowledge_compilation_jobs_document_version_id"),
        ),
    )
    with op.batch_alter_table("knowledge_compilation_jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_compilation_jobs_document_version_id"),
            ["document_version_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_compilation_jobs_status"), ["status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_compilation_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_compilation_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_knowledge_compilation_jobs_document_version_id"))
    op.drop_table("knowledge_compilation_jobs")
