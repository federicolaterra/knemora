from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ApplicationVersion,
    AuditEvent,
    Conversation,
    Document,
    DocumentVersion,
    Message,
    User,
)
from app.db.session import create_database_engine
from knemora_bootstrap.postgresql_migration import migrate_postgresql_to_sqlite
from knemora_bootstrap.sqlite_backup import backup_sqlite


def test_sqlite_engine_enforces_foreign_keys_and_local_concurrency_settings(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'knemora.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30_000
    with Session(engine) as session:
        session.add(Conversation(user_id=uuid.uuid4(), title="orphan"))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_postgresql_import_preserves_data_validates_and_is_retry_safe(tmp_path: Path) -> None:
    source_path = tmp_path / "representative-postgresql.db"
    source_url = f"sqlite+pysqlite:///{source_path}"
    source_engine = create_database_engine(source_url)
    Base.metadata.create_all(source_engine)
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    with Session(source_engine) as session:
        session.add_all(
            [
                ApplicationVersion(
                    component="core",
                    app_version="0.8.0",
                    schema_version=9,
                    knowledge_schema_version=1,
                ),
                User(
                    id=user_id,
                    email="existing@example.test",
                    display_name="Zoë Δelta",
                    first_name=None,
                    last_name="例",
                    company="Northstar",
                    visualization_name=None,
                    is_active=True,
                    password_hash=None,
                    failed_login_count=0,
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                Conversation(id=conversation_id, user_id=user_id, title=None),
                Document(
                    id=document_id,
                    owner_id=user_id,
                    original_filename="résumé.md",
                    deleted_at=None,
                ),
                AuditEvent(
                    actor_user_id=user_id,
                    event_type="migration.fixture",
                    entity_type="document",
                    entity_id=str(document_id),
                    payload={"content_free": True},
                ),
            ]
        )
        session.commit()
        session.add(
            DocumentVersion(
                id=version_id,
                owner_id=user_id,
                document_id=document_id,
                version_number=1,
                sha256="a" * 64,
                content_type="text/markdown",
                byte_size=42,
                storage_uri="file:///immutable/source",
                extracted_uri=None,
                metadata_uri=None,
                provenance={"page": None, "labels": ["α", "β"]},
            )
        )
        session.add_all(
            [
                Message(
                    conversation_id=conversation_id,
                    sequence=index,
                    role="user",
                    content=f"Unicode row {index}: ċ, 漢字, 🚀",
                    provider_model=None,
                    message_metadata={"nested": {"value": None}, "items": [1, "ż"]},
                )
                for index in range(1, 506)
            ]
        )
        session.commit()
    source_engine.dispose()

    target = tmp_path / "home" / "data" / "knemora.db"
    backup_root = tmp_path / "backups"
    api_directory = Path(__file__).parents[1]
    result = migrate_postgresql_to_sqlite(
        source_url=source_url,
        target=target,
        api_directory=api_directory,
        backup_root=backup_root,
        require_postgresql=False,
    )

    assert not result.already_migrated
    assert result.row_counts["users"] == 1
    assert result.row_counts["messages"] == 505
    assert (result.backup_directory / "manifest.json").is_file()
    assert (result.backup_directory / "messages.jsonl").is_file()
    target_engine = create_database_engine(f"sqlite+pysqlite:///{target}")
    with Session(target_engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.display_name == "Zoë Δelta"
        assert user.first_name is None
        message = session.scalar(select(Message).order_by(Message.sequence))
        assert message is not None
        assert message.content == "Unicode row 1: ċ, 漢字, 🚀"
        assert message.message_metadata["nested"]["value"] is None
        version = session.get(DocumentVersion, version_id)
        assert version is not None
        assert version.provenance == {"page": None, "labels": ["α", "β"]}
        application_version = session.get(ApplicationVersion, "core")
        assert application_version is not None
        assert (application_version.app_version, application_version.schema_version) == (
            "0.8.4",
            10,
        )
    with target_engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
        connection.execute(text("DELETE FROM audit_events"))
    target_engine.dispose()

    repeated = migrate_postgresql_to_sqlite(
        source_url=source_url,
        target=target,
        api_directory=api_directory,
        backup_root=backup_root,
        require_postgresql=False,
    )
    assert repeated.already_migrated


def test_sqlite_backup_api_copies_a_consistent_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "outside-home" / "knemora.db"
    engine = create_database_engine(f"sqlite+pysqlite:///{source}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO application_versions "
                "(component, app_version, schema_version, knowledge_schema_version) "
                "VALUES ('core', '0.8.3', 10, 1)"
            )
        )
    original_replace = Path.replace

    def replace_with_temporary_sidecars(self: Path, target: Path) -> Path:
        if self.name.endswith(".tmp"):
            for suffix in ("-wal", "-shm"):
                self.with_name(self.name + suffix).write_bytes(b"temporary")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_with_temporary_sidecars)
    backup_sqlite(source, destination)
    with create_database_engine(f"sqlite+pysqlite:///{destination}").connect() as connection:
        assert connection.scalar(text("SELECT app_version FROM application_versions")) == "0.8.3"
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    assert not list(destination.parent.glob("knemora.db.tmp*"))
    engine.dispose()
