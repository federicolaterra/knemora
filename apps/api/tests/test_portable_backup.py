from __future__ import annotations

import json
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ApplicationVersion,
    Conversation,
    Document,
    DocumentVersion,
    Message,
    User,
)
from app.db.session import create_database_engine
from app.home import HomeCompatibilityService
from app.knowledge.store import WikiStore
from app.knowledge.types import (
    ClaimClassification,
    PageKind,
    ProvenanceRef,
    WikiClaim,
    WikiPage,
    WikiRelationship,
)
from knemora_bootstrap.cli import _parser
from knemora_bootstrap.configuration import (
    AppPaths,
    default_backup_path,
    read_backup_path,
    write_backup_path,
)
from knemora_bootstrap.local_backup import (
    BackupError,
    create_backup,
    delete_backup,
    list_backups,
    resolve_backup,
    restore_backup,
    validate_backup,
)


def _create_database(path: Path, *, email: str, display_name: str) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('0e83a1b2c3d4')"
        )
    with Session(engine) as session:
        user_id = uuid.uuid4()
        session.add_all(
            [
                ApplicationVersion(
                    component="core",
                    app_version="0.8.3",
                    schema_version=11,
                    knowledge_schema_version=1,
                ),
                User(
                    id=user_id,
                    email=email,
                    display_name=display_name,
                    first_name="Zoë",
                    last_name="例",
                    company="Northstar ċ",
                    visualization_name="Portable Brain",
                    is_active=True,
                    failed_login_count=0,
                ),
            ]
        )
        session.commit()
        document_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        session.add_all(
            [
                Document(
                    id=document_id,
                    owner_id=user_id,
                    original_filename="résumé-例.md",
                ),
                Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    title="Portable conversation 🚀",
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                DocumentVersion(
                    owner_id=user_id,
                    document_id=document_id,
                    version_number=1,
                    sha256="d" * 64,
                    content_type="text/markdown",
                    byte_size=32,
                    storage_uri="documents/résumé-例/attachment.bin",
                    extracted_uri=None,
                    metadata_uri=None,
                    provenance={"section": "Żółć / 漢字"},
                ),
                Message(
                    conversation_id=conversation_id,
                    sequence=1,
                    role="user",
                    content="Remember Valletta ċ, 漢字, 🚀",
                    provider_model=None,
                    message_metadata={"portable": True},
                ),
            ]
        )
        session.commit()
    engine.dispose()


def _settings(paths: AppPaths) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{paths.database}",
        source_store_path=paths.sources,
        knowledge_path=paths.wiki,
    )


def _provenance() -> ProvenanceRef:
    return ProvenanceRef(
        source_record_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        original_filename="résumé-例.md",
        sha256="a" * 64,
        locator={"section": "Żółć / 漢字"},
        parser_name="markdown",
        parser_version="1",
        compilation_version="knemora-wiki/1",
        compiled_at=datetime.now(UTC),
    )


def _populate_installation(paths: AppPaths, *, email: str, marker: str) -> Settings:
    paths.initialize()
    _create_database(paths.database, email=email, display_name=f"Zoë {marker}")
    provenance = _provenance()
    target_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target = WikiPage(
        id=target_id,
        type=PageKind.CONCEPT,
        title=f"Target {marker}",
        summary="A portable target.",
        provenance=(provenance,),
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="unicode",
                text="Valletta ċ, 漢字, 🚀",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=(provenance,),
            ),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="knemora-wiki/1",
    )
    source = WikiPage(
        id=source_id,
        type=PageKind.ENTITY,
        title=f"Source {marker}",
        summary="A linked portable source.",
        provenance=(provenance,),
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="marker",
                text=f"Backup marker {marker}",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=(provenance,),
            ),
        ),
        relationships=(
            WikiRelationship(
                relation="links-to",
                target_id=target_id,
                target_title=target.title,
                provenance=(provenance,),
            ),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="knemora-wiki/1",
    )
    WikiStore(paths.wiki).apply_pages_transactionally((target, source))
    attachment = paths.sources / "documents" / "résumé-例" / "attachment.bin"
    attachment.parent.mkdir(parents=True, exist_ok=True)
    attachment.write_bytes(f"attachment-{marker}-ċ-漢字".encode())
    dataset = paths.data / "datasets" / "trend.json"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_text(json.dumps({"marker": marker, "values": [1, 2, 3]}), encoding="utf-8")
    (paths.config / "model.json").write_text(
        json.dumps(
            {
                "model_id": "qwen3-8b-q3-k-m",
                "display_name": "Qwen3 8B",
                "provider": "llama_cpp",
                "path": str(paths.models / "model.gguf"),
                "quantization": "Q3_K_M",
                "context_tokens": 8192,
                "sha256": "b" * 64,
                "previous_selection": {
                    "model_id": "older-model",
                    "path": str(paths.models / "older.gguf"),
                    "context_tokens": 4096,
                },
            }
        ),
        encoding="utf-8",
    )
    (paths.config / "models.json").write_text(
        json.dumps(
            {
                "version": 2,
                "hidden_curated_ids": [],
                "models": [
                    {
                        "artifact": "portable-custom.gguf",
                        "compatibility_status": "not-checked",
                        "context_tokens": 4096,
                        "display_name": "Portable Custom",
                        "enabled": True,
                        "filename": "portable-custom.gguf",
                        "format": "gguf",
                        "id": "portable-custom",
                        "imported_at": "2026-10-05T00:00:00+00:00",
                        "license_url": "https://example.test/license",
                        "local_path": str(paths.models / "portable-custom.gguf"),
                        "origin": "user",
                        "provider": "llama_cpp",
                        "quantization": "Q4_K_M",
                        "recommended_memory_gb": 4,
                        "repository": "example/portable-custom",
                        "required_free_bytes": 1024,
                        "runtime": "llama.cpp",
                        "sha256": "c" * 64,
                        "size_bytes": 512,
                        "source_provider": "huggingface",
                        "variant": "Q4_K_M",
                        "verification_status": "custom-unverified-by-knemora",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (paths.models / "model.gguf").write_bytes(b"excluded-model")
    HomeCompatibilityService(paths.data).ensure_current()
    return _settings(paths)


def _email(database: Path) -> str:
    engine = create_database_engine(f"sqlite+pysqlite:///{database}")
    with Session(engine) as session:
        email = session.scalar(select(User.email))
    engine.dispose()
    assert email is not None
    return email


def _restored_relational_flow(database: Path) -> tuple[str, str, str]:
    engine = create_database_engine(f"sqlite+pysqlite:///{database}")
    with Session(engine) as session:
        user = session.scalar(select(User))
        document = session.scalar(select(Document))
        message = session.scalar(select(Message))
    engine.dispose()
    assert user is not None and document is not None and message is not None
    return user.visualization_name or "", document.original_filename, message.content


def test_full_backup_is_portable_complete_and_excludes_secrets_and_models(
    tmp_path: Path,
) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    settings = _populate_installation(paths, email="source@example.test", marker="source")
    (paths.repository / ".env").parent.mkdir(parents=True)
    (paths.repository / ".env").write_text("KNEMORA_SECRET=never-archive\n", encoding="utf-8")

    result = create_backup(tmp_path / "backups", "full", settings, paths=paths)
    manifest = validate_backup(result.archive)

    assert result.backup_type == "full"
    assert manifest["schema_version"] == 11
    assert manifest["knowledge_schema_version"] == 1
    assert manifest["model"]["model_id"] == "qwen3-8b-q3-k-m"
    with zipfile.ZipFile(result.archive) as archive:
        names = set(archive.namelist())
        assert "database/knemora.db" in names
        assert any(name.startswith("knowledge/wiki/") for name in names)
        assert "sources/documents/résumé-例/attachment.bin" in names
        assert "datasets/trend.json" in names
        assert "config/model-selection.json" in names
        assert "config/models.json" in names
        assert not any(name.endswith(".gguf") or name.endswith(".env") for name in names)
        selection = json.loads(archive.read("config/model-selection.json"))
        registry = json.loads(archive.read("config/models.json"))
        assert "path" not in selection
        assert "path" not in selection["previous_selection"]
        assert registry["models"][0]["local_path"] == ""


def test_database_only_backup_uses_live_sqlite_snapshot_and_lists_validation(
    tmp_path: Path,
) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    settings = _populate_installation(paths, email="live@example.test", marker="live")
    live = sqlite3.connect(paths.database)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute(
        "UPDATE users SET display_name = ? WHERE email = ?",
        ("Committed while open 🚀", "live@example.test"),
    )
    live.commit()

    result = create_backup(tmp_path / "backups", "database", settings, paths=paths)
    live.close()

    with zipfile.ZipFile(result.archive) as archive:
        assert set(archive.namelist()) == {"database/knemora.db", "manifest.json"}
    records = list_backups(tmp_path / "backups")
    assert records[0].validation == "valid"
    assert records[0].backup_type == "database"


def test_backup_path_persists_and_cannot_point_inside_application_data(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    paths.initialize()
    custom = write_backup_path(paths, tmp_path / "external" / "Knemora")

    assert read_backup_path(paths) == custom
    assert custom.is_dir()
    with pytest.raises(RuntimeError, match="outside Knemora data"):
        write_backup_path(paths, paths.data / "backups")


def test_default_path_and_cli_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "user"))

    assert default_backup_path() == tmp_path / "user/Documents/Knemora/Backups"
    assert _parser().parse_args(["backup"]).backup_type == "full"
    assert _parser().parse_args(["backup", "--db-only"]).backup_type == "database"
    assert _parser().parse_args(["backup", "delete", "backup-id"]).backup_command == "delete"
    assert _parser().parse_args(["restore", "copied.zip"]).backup_reference == "copied.zip"
    assert _parser().parse_args(["config", "backup-path"]).path is None


def test_backup_integrity_and_unsafe_paths_are_rejected_and_reported(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    settings = _populate_installation(paths, email="source@example.test", marker="source")
    result = create_backup(tmp_path / "backups", "full", settings, paths=paths)

    with zipfile.ZipFile(result.archive, "a") as archive:
        archive.writestr("../escape.txt", "unsafe")

    with pytest.raises(BackupError, match="unsafe path"):
        validate_backup(result.archive)
    records = list_backups(tmp_path / "backups")
    assert records[0].validation.startswith("invalid:")
    assert not (tmp_path / "escape.txt").exists()


def test_backup_checksum_corruption_is_rejected(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    settings = _populate_installation(paths, email="source@example.test", marker="source")
    result = create_backup(tmp_path / "backups", "full", settings, paths=paths)
    with zipfile.ZipFile(result.archive) as archive:
        entries = {info.filename: archive.read(info) for info in archive.infolist()}
    entries["sources/documents/résumé-例/attachment.bin"] = b"tampered"
    with zipfile.ZipFile(result.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)

    with pytest.raises(BackupError, match="checksum or size mismatch"):
        validate_backup(result.archive)


def test_full_restore_replaces_existing_installation_and_keeps_recovery_archive(
    tmp_path: Path,
) -> None:
    source_paths = AppPaths(repository=tmp_path / "source-repo", data=tmp_path / "source-home")
    source_settings = _populate_installation(
        source_paths, email="portable@example.test", marker="portable"
    )
    backups = tmp_path / "backups"
    backup = create_backup(backups, "full", source_settings, paths=source_paths)
    target_paths = AppPaths(repository=tmp_path / "target-repo", data=tmp_path / "target-home")
    target_settings = _populate_installation(target_paths, email="old@example.test", marker="old")
    target_selection = (target_paths.config / "model.json").read_bytes()

    result = restore_backup(
        backup.archive,
        target_settings,
        paths=target_paths,
        recovery_directory=backups,
    )

    assert _email(target_paths.database) == "portable@example.test"
    assert _restored_relational_flow(target_paths.database) == (
        "Portable Brain",
        "résumé-例.md",
        "Remember Valletta ċ, 漢字, 🚀",
    )
    assert (target_paths.sources / "documents/résumé-例/attachment.bin").read_bytes().decode() == (
        "attachment-portable-ċ-漢字"
    )
    assert json.loads((target_paths.data / "datasets/trend.json").read_text())["marker"] == (
        "portable"
    )
    restored_page = WikiStore(target_paths.wiki).read_page("Source portable")
    assert restored_page.relationships[0].target_title == "Target portable"
    assert (target_paths.config / "model.json").read_bytes() == target_selection
    assert json.loads(target_paths.model_registry.read_text())["models"][0]["local_path"] == ""
    assert result.recovery_archive.is_file()
    assert result.archive.is_file()
    assert "knowledge" in result.restored_roots


def test_full_restore_into_fresh_setup_preserves_unicode_and_application_flow(
    tmp_path: Path,
) -> None:
    source_paths = AppPaths(repository=tmp_path / "source-repo", data=tmp_path / "source-home")
    source_settings = _populate_installation(
        source_paths, email="fresh@example.test", marker="fresh"
    )
    backups = tmp_path / "backups"
    backup = create_backup(backups, "full", source_settings, paths=source_paths)
    target_paths = AppPaths(repository=tmp_path / "target-repo", data=tmp_path / "target-home")
    target_paths.initialize()
    _create_database(target_paths.database, email="setup@example.test", display_name="Setup")
    HomeCompatibilityService(target_paths.data).ensure_current()
    target_settings = _settings(target_paths)

    restore_backup(
        backup.archive,
        target_settings,
        paths=target_paths,
        recovery_directory=backups,
    )

    assert _email(target_paths.database) == "fresh@example.test"
    store = WikiStore(target_paths.wiki)
    assert store.lint().errors == 0
    assert store.read_page("Target fresh").claims[0].text == "Valletta ċ, 漢字, 🚀"


def test_database_only_restore_requires_acknowledgement_and_preserves_files(
    tmp_path: Path,
) -> None:
    source_paths = AppPaths(repository=tmp_path / "source-repo", data=tmp_path / "source-home")
    source_settings = _populate_installation(
        source_paths, email="database@example.test", marker="database"
    )
    backups = tmp_path / "backups"
    backup = create_backup(backups, "database", source_settings, paths=source_paths)
    target_paths = AppPaths(repository=tmp_path / "target-repo", data=tmp_path / "target-home")
    target_settings = _populate_installation(
        target_paths, email="existing@example.test", marker="existing"
    )
    existing_attachment = target_paths.sources / "documents/résumé-例/attachment.bin"

    with pytest.raises(BackupError, match="--allow-db-only"):
        restore_backup(
            backup.archive,
            target_settings,
            paths=target_paths,
            recovery_directory=backups,
        )
    restore_backup(
        backup.archive,
        target_settings,
        paths=target_paths,
        recovery_directory=backups,
        allow_db_only=True,
    )

    assert _email(target_paths.database) == "database@example.test"
    assert existing_attachment.read_bytes().decode() == "attachment-existing-ċ-漢字"


def test_failed_restore_rolls_back_database_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = AppPaths(repository=tmp_path / "source-repo", data=tmp_path / "source-home")
    source_settings = _populate_installation(
        source_paths, email="source@example.test", marker="source"
    )
    backups = tmp_path / "backups"
    backup = create_backup(backups, "full", source_settings, paths=source_paths)
    target_paths = AppPaths(repository=tmp_path / "target-repo", data=tmp_path / "target-home")
    target_settings = _populate_installation(
        target_paths, email="original@example.test", marker="original"
    )
    original_replace = Path.replace

    def fail_knowledge_activation(self: Path, target: Path) -> Path:
        if self.name.startswith(".wiki.restore-") and Path(target) == target_paths.wiki:
            raise OSError("simulated activation failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_knowledge_activation)
    with pytest.raises(BackupError, match="rolled back"):
        restore_backup(
            backup.archive,
            target_settings,
            paths=target_paths,
            recovery_directory=backups,
        )

    assert _email(target_paths.database) == "original@example.test"
    assert WikiStore(target_paths.wiki).read_page("Source original").title == "Source original"
    assert len(list_backups(backups)) >= 2


def test_backup_id_resolution_and_deletion_stay_in_configured_directory(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "home")
    settings = _populate_installation(paths, email="source@example.test", marker="source")
    backups = tmp_path / "backups"
    backup = create_backup(backups, "database", settings, paths=paths)

    assert resolve_backup(backup.id, backups) == backup.archive
    with pytest.raises(BackupError, match="ID, not an archive path"):
        delete_backup(str(backup.archive), backups)
    removed = delete_backup(backup.id, backups)
    assert removed == backup.archive
    assert not removed.exists()
