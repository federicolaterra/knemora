from app.db import models  # noqa: F401
from app.db.base import Base


def test_milestone_metadata_tables_are_registered() -> None:
    expected = {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "conversations",
        "messages",
        "agent_sessions",
        "documents",
        "document_versions",
        "ingestion_jobs",
        "source_records",
        "source_deletion_jobs",
        "dataset_records",
        "knowledge_compilation_jobs",
        "wiki_changes",
        "feedback",
        "audit_events",
        "auth_sessions",
        "application_versions",
    }

    assert set(Base.metadata.tables) == expected
