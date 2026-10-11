"""Owner-scope source checksum uniqueness.

Revision ID: a4d16f2cb903
Revises: 8c2b58e7d8f1
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d16f2cb903"
down_revision: str | None = "8c2b58e7d8f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE document_versions SET owner_id = "
            "(SELECT documents.owner_id FROM documents "
            "WHERE documents.id = document_versions.document_id)"
        )
    )

    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.alter_column("owner_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            "fk_document_versions_owner_id_users", "users", ["owner_id"], ["id"]
        )
        batch_op.create_index("ix_document_versions_owner_id", ["owner_id"], unique=False)
        batch_op.create_unique_constraint("uq_document_versions_owner_id", ["owner_id", "sha256"])


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint("uq_document_versions_owner_id", type_="unique")
        batch_op.drop_index("ix_document_versions_owner_id")
        batch_op.drop_constraint("fk_document_versions_owner_id_users", type_="foreignkey")
        batch_op.drop_column("owner_id")
