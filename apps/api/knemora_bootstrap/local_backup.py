"""Versioned portable backups for Knemora's SQLite-backed local installation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from sqlalchemy.engine import make_url

from app.config import Settings
from app.home import (
    HOME_DESCRIPTOR_FORMAT_VERSION,
    HOME_SCHEMA_VERSION,
    HomeCompatibilityService,
)
from app.knowledge.store import WikiStore
from app.product import APP_VERSION, KNOWLEDGE_SCHEMA_VERSION, SCHEMA_VERSION
from knemora_bootstrap.configuration import AppPaths
from knemora_bootstrap.models import ModelError, ModelRegistry
from knemora_bootstrap.sqlite_backup import backup_sqlite, restore_sqlite

BACKUP_FORMAT = "knemora-portable-backup"
BACKUP_FORMAT_VERSION = 1
BackupType = Literal["full", "database"]


class BackupError(RuntimeError):
    """A portable backup could not be created, validated, or restored safely."""


@dataclass(frozen=True)
class BackupResult:
    id: str
    archive: Path
    backup_type: BackupType
    size_bytes: int
    created_at: str


@dataclass(frozen=True)
class BackupRecord:
    id: str
    archive: Path
    backup_type: str
    size_bytes: int
    created_at: str
    validation: str


@dataclass(frozen=True)
class RestoreResult:
    archive: Path
    backup_type: BackupType
    recovery_archive: Path
    database: Path
    restored_roots: tuple[str, ...]
    archived_model_id: str | None


def _database_path(settings: Settings) -> Path:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError("Portable backup requires a file-backed SQLite database.")
    return Path(url.database).expanduser().resolve()


def _normalize_type(value: str) -> BackupType:
    aliases = {"full": "full", "all": "full", "database": "database", "db-only": "database"}
    normalized = aliases.get(value)
    if normalized is None:
        raise BackupError(f"Unsupported backup type: {value}")
    return cast(BackupType, normalized)


def _assert_outside_data(path: Path, paths: AppPaths) -> None:
    resolved = path.expanduser().resolve()
    if resolved == paths.data or resolved.is_relative_to(paths.data):
        raise BackupError(f"Backup location must be outside Knemora data: {paths.data}")


def _assert_outside_active_stores(path: Path, settings: Settings, paths: AppPaths) -> None:
    _assert_outside_data(path, paths)
    resolved = path.expanduser().resolve()
    for store in (
        _database_path(settings).parent,
        settings.knowledge_path.resolve(),
        settings.source_store_path.resolve(),
    ):
        if resolved == store or resolved.is_relative_to(store):
            raise BackupError(f"Backup location must be outside active data store: {store}")


def _assert_available_volume(path: Path) -> None:
    if len(path.parts) >= 3 and path.parts[:2] == ("/", "Volumes"):
        volume = Path(*path.parts[:3])
        if not volume.is_dir():
            raise BackupError(f"Backup volume is unavailable: {volume}")


@contextmanager
def _operation_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".knemora-backup.lock"
    with lock.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError(f"Another backup or restore is already using {directory}.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _home_operation_lock(paths: AppPaths) -> Iterator[None]:
    paths.runtime.mkdir(parents=True, exist_ok=True)
    lock = paths.runtime / "home-operation.lock"
    with lock.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError(
                "Another setup, restore, migration, or runtime activation is in progress."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_path(
    archive: zipfile.ZipFile, source: Path, archive_path: str, inventory: list[dict[str, Any]]
) -> None:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as input_file, archive.open(archive_path, "w") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    inventory.append({"path": archive_path, "size": size, "sha256": digest.hexdigest()})


def _excluded_knowledge_path(relative: Path) -> bool:
    parts = relative.parts
    return (
        relative.name == ".DS_Store"
        or relative.as_posix() == "index.md"
        or parts[:2] == (".knemora", "search-index")
        or relative.as_posix() == ".knemora/graph-index.json"
        or parts[:2] == (".knemora", "locks")
        or relative.as_posix() == ".knemora/state.json"
    )


def _write_tree(
    archive: zipfile.ZipFile,
    source: Path,
    archive_root: str,
    inventory: list[dict[str, Any]],
    *,
    exclude_generated_knowledge: bool = False,
) -> None:
    if not source.exists():
        return
    if source.is_symlink():
        raise BackupError(f"Backup source cannot be a symlink: {source}")
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise BackupError(f"Backup source cannot contain symlinks: {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        if exclude_generated_knowledge and _excluded_knowledge_path(relative):
            continue
        _write_path(archive, item, f"{archive_root}/{relative.as_posix()}", inventory)


def _portable_model_configuration(paths: AppPaths) -> tuple[dict[str, Any] | None, bytes | None]:
    def without_local_paths(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: without_local_paths(item) for key, item in value.items() if key != "path"}
        if isinstance(value, list):
            return [without_local_paths(item) for item in value]
        return value

    selection: dict[str, Any] | None = None
    try:
        raw_selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
        if isinstance(raw_selection, dict):
            selection = without_local_paths(raw_selection)
    except (OSError, ValueError):
        pass

    registry_bytes: bytes | None = None
    try:
        registry = json.loads(paths.model_registry.read_text(encoding="utf-8"))
        if isinstance(registry, dict) and isinstance(registry.get("models"), list):
            for model in registry["models"]:
                if isinstance(model, dict):
                    model["local_path"] = ""
            registry_bytes = (json.dumps(registry, indent=2, sort_keys=True) + "\n").encode()
    except (OSError, ValueError):
        pass
    return selection, registry_bytes


def _write_bytes(
    archive: zipfile.ZipFile, data: bytes, archive_path: str, inventory: list[dict[str, Any]]
) -> None:
    archive.writestr(archive_path, data)
    inventory.append(
        {"path": archive_path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    )


def _database_metadata(database: Path) -> dict[str, Any]:
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise BackupError(f"SQLite integrity check failed: {integrity!r}")
            row = connection.execute(
                "SELECT app_version, schema_version, knowledge_schema_version "
                "FROM application_versions WHERE component = 'core'"
            ).fetchone()
            alembic = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f"Could not inspect SQLite database {database}: {exc}") from exc
    if row is None or alembic is None:
        raise BackupError("SQLite database is missing Knemora version metadata.")
    return {
        "application_version": str(row[0]),
        "schema_version": int(row[1]),
        "knowledge_schema_version": int(row[2]),
        "alembic_revision": str(alembic[0]),
    }


def _next_archive_path(destination: Path, created_at: datetime, backup_type: BackupType) -> Path:
    timestamp = created_at.astimezone(UTC).strftime("%Y-%m-%d-%H%M%S")
    base = destination / f"knemora-backup-{timestamp}-{backup_type}"
    candidate = base.with_suffix(".zip")
    sequence = 2
    while candidate.exists():
        candidate = destination / f"{base.name}-{sequence}.zip"
        sequence += 1
    return candidate


def create_backup(
    destination: Path,
    backup_type: str,
    settings: Settings,
    *,
    paths: AppPaths | None = None,
    created_at: datetime | None = None,
) -> BackupResult:
    """Create and validate one atomic portable archive."""

    active_paths = paths or AppPaths.discover()
    home_descriptor = HomeCompatibilityService(
        active_paths.data, repository=active_paths.repository
    ).validate_ready()
    resolved_destination = destination.expanduser().resolve()
    _assert_outside_active_stores(resolved_destination, settings, active_paths)
    _assert_available_volume(resolved_destination)
    normalized_type = _normalize_type(backup_type)
    created = (created_at or datetime.now(UTC)).astimezone(UTC)
    database = _database_path(settings)
    try:
        resolved_destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(
            f"Could not create backup destination {resolved_destination}: {exc}"
        ) from exc

    with _operation_lock(resolved_destination):
        final_archive = _next_archive_path(resolved_destination, created, normalized_type)
        partial = final_archive.with_suffix(".zip.partial")
        partial.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix=".knemora-backup-", dir=resolved_destination
            ) as temporary_directory:
                snapshot = Path(temporary_directory) / "knemora.db"
                backup_sqlite(database, snapshot)
                database_metadata = _database_metadata(snapshot)
                inventory: list[dict[str, Any]] = []
                with zipfile.ZipFile(
                    partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                ) as archive:
                    _write_path(archive, snapshot, "database/knemora.db", inventory)
                    selection, registry_bytes = _portable_model_configuration(active_paths)
                    if normalized_type == "full":
                        _write_tree(
                            archive,
                            settings.knowledge_path,
                            "knowledge",
                            inventory,
                            exclude_generated_knowledge=True,
                        )
                        _write_tree(archive, settings.source_store_path, "sources", inventory)
                        _write_tree(archive, active_paths.data / "datasets", "datasets", inventory)
                        if selection is not None:
                            _write_bytes(
                                archive,
                                (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode(),
                                "config/model-selection.json",
                                inventory,
                            )
                        if registry_bytes is not None:
                            _write_bytes(archive, registry_bytes, "config/models.json", inventory)
                    manifest = {
                        "format": BACKUP_FORMAT,
                        "format_version": BACKUP_FORMAT_VERSION,
                        "home_descriptor_format_version": home_descriptor.format_version,
                        "home_schema_version": home_descriptor.home_schema_version,
                        "knemora_version": APP_VERSION,
                        "created_at": created.isoformat(),
                        "backup_type": normalized_type,
                        **database_metadata,
                        "model": selection,
                        "components": (
                            ["database", "knowledge", "sources", "datasets", "config"]
                            if normalized_type == "full"
                            else ["database"]
                        ),
                        "inventory": sorted(inventory, key=lambda item: item["path"]),
                        "excluded": [
                            "GGUF model artifacts",
                            "repository .env and credentials",
                            "logs and runtime PID files",
                            "rebuildable Wiki indexes",
                            "Development demo data",
                        ],
                    }
                    archive.writestr(
                        "manifest.json",
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    )
                validate_backup(partial)
                partial.replace(final_archive)
        except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
            raise BackupError(f"Backup creation failed: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)
    return BackupResult(
        id=final_archive.stem,
        archive=final_archive,
        backup_type=normalized_type,
        size_bytes=final_archive.stat().st_size,
        created_at=created.isoformat(),
    )


def _safe_member_name(name: str) -> str:
    if "\\" in name:
        raise BackupError(f"Archive contains an unsafe path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError(f"Archive contains an unsafe path: {name!r}")
    return path.as_posix()


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = archive.getinfo("manifest.json")
        if info.file_size > 2_000_000:
            raise BackupError("Backup manifest is unreasonably large.")
        manifest = json.loads(archive.read(info))
    except (KeyError, ValueError, UnicodeError) as exc:
        raise BackupError(f"Backup manifest is missing or invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BackupError("Backup manifest root must be an object.")
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("Archive is not a supported Knemora portable backup.")
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupError("Backup format version is not supported by this Knemora release.")
    if manifest.get("backup_type") not in {"full", "database"}:
        raise BackupError("Backup manifest has an invalid backup type.")
    home_format = manifest.get("home_descriptor_format_version", HOME_DESCRIPTOR_FORMAT_VERSION)
    home_schema = manifest.get("home_schema_version", HOME_SCHEMA_VERSION)
    if home_format != HOME_DESCRIPTOR_FORMAT_VERSION:
        raise BackupError(
            f"Backup home descriptor format {home_format!r} is unsupported by this release."
        )
    if not isinstance(home_schema, int) or isinstance(home_schema, bool):
        raise BackupError("Backup home schema version is invalid.")
    if home_schema > HOME_SCHEMA_VERSION:
        raise BackupError(
            f"Backup home schema {home_schema} is newer than supported schema "
            f"{HOME_SCHEMA_VERSION}."
        )
    schema_version = manifest.get("schema_version")
    knowledge_version = manifest.get("knowledge_schema_version")
    if not isinstance(schema_version, int) or schema_version > SCHEMA_VERSION:
        raise BackupError(
            f"Backup schema {schema_version!r} is newer than supported schema {SCHEMA_VERSION}."
        )
    if not isinstance(knowledge_version, int) or knowledge_version > KNOWLEDGE_SCHEMA_VERSION:
        raise BackupError("Backup knowledge schema is newer than this Knemora release supports.")
    return manifest


def validate_backup(archive_path: Path) -> dict[str, Any]:
    """Validate paths, inventory, checksums, schema compatibility, and SQLite integrity."""

    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise BackupError(f"Backup archive does not exist: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > 1_000_000:
                raise BackupError("Backup contains too many entries.")
            names: set[str] = set()
            for info in infos:
                safe_name = _safe_member_name(info.filename)
                if safe_name in names:
                    raise BackupError(f"Backup contains duplicate entry: {safe_name}")
                names.add(safe_name)
                mode = (info.external_attr >> 16) & 0o170000
                if stat.S_ISLNK(mode):
                    raise BackupError(f"Backup contains a symbolic link: {safe_name}")
                if info.file_size > 100_000_000 and (
                    info.compress_size == 0 or info.file_size / info.compress_size > 10_000
                ):
                    raise BackupError(f"Backup entry has an unsafe compression ratio: {safe_name}")
            manifest = _read_manifest(archive)
            inventory = manifest.get("inventory")
            if not isinstance(inventory, list):
                raise BackupError("Backup manifest inventory is invalid.")
            expected = {"manifest.json"}
            for entry in inventory:
                if not isinstance(entry, dict):
                    raise BackupError("Backup inventory entry is invalid.")
                name = _safe_member_name(str(entry.get("path", "")))
                if name in expected:
                    raise BackupError(f"Backup inventory contains duplicate path: {name}")
                expected.add(name)
                try:
                    info = archive.getinfo(name)
                except KeyError as exc:
                    raise BackupError(f"Backup is missing inventoried file: {name}") from exc
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if entry.get("size") != size or entry.get("sha256") != digest.hexdigest():
                    raise BackupError(f"Backup checksum or size mismatch: {name}")
            if names != expected:
                extras = sorted(names - expected)
                missing = sorted(expected - names)
                raise BackupError(f"Backup inventory mismatch; extra={extras}, missing={missing}")
            if "database/knemora.db" not in names:
                raise BackupError("Backup does not contain database/knemora.db.")
            with tempfile.TemporaryDirectory(prefix="knemora-validate-") as temporary:
                temporary_root = Path(temporary)
                database = temporary_root / "knemora.db"
                with archive.open("database/knemora.db") as source, database.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                metadata = _database_metadata(database)
                if metadata["schema_version"] != manifest["schema_version"]:
                    raise BackupError("Database schema does not match the backup manifest.")
                if "config/models.json" in names:
                    registry = temporary_root / "models.json"
                    registry.write_bytes(archive.read("config/models.json"))
                    try:
                        ModelRegistry(registry).user_models()
                    except ModelError as exc:
                        raise BackupError(f"Archived model registry is invalid: {exc}") from exc
                if "config/model-selection.json" in names:
                    try:
                        selection = json.loads(archive.read("config/model-selection.json"))
                    except (ValueError, UnicodeError) as exc:
                        raise BackupError(f"Archived model selection is invalid: {exc}") from exc
                    if not isinstance(selection, dict) or not isinstance(
                        selection.get("model_id"), str
                    ):
                        raise BackupError("Archived model selection is invalid.")
    except zipfile.BadZipFile as exc:
        raise BackupError(f"Backup archive is not a valid ZIP file: {exc}") from exc
    return manifest


def list_backups(destination: Path) -> tuple[BackupRecord, ...]:
    destination = destination.expanduser().resolve()
    if not destination.exists():
        return ()
    records: list[BackupRecord] = []
    for archive in sorted(destination.glob("*.zip"), reverse=True):
        try:
            manifest = validate_backup(archive)
            validation = "valid"
            backup_type = str(manifest["backup_type"])
            created_at = str(manifest["created_at"])
        except (BackupError, OSError) as exc:
            validation = f"invalid: {exc}"
            backup_type = "unknown"
            created_at = "unknown"
        records.append(
            BackupRecord(
                id=archive.stem,
                archive=archive,
                backup_type=backup_type,
                size_bytes=archive.stat().st_size,
                created_at=created_at,
                validation=validation,
            )
        )
    return tuple(records)


def resolve_backup(reference: str, destination: Path) -> Path:
    candidate = Path(reference).expanduser()
    if candidate.is_absolute() or candidate.parent != Path(".") or candidate.is_file():
        return candidate.resolve()
    if "/" in reference or "\\" in reference:
        raise BackupError("Backup ID cannot contain path separators.")
    name = reference if reference.endswith(".zip") else f"{reference}.zip"
    configured = destination.expanduser().resolve()
    resolved = (configured / name).resolve()
    if resolved.parent != configured:
        raise BackupError("Backup ID escapes the configured backup directory.")
    return resolved


def delete_backup(backup_id: str, destination: Path) -> Path:
    if Path(backup_id).name != backup_id or "/" in backup_id or "\\" in backup_id:
        raise BackupError("Backup deletion accepts an ID, not an archive path.")
    archive = resolve_backup(backup_id, destination)
    configured = destination.expanduser().resolve()
    if archive.parent != configured or not archive.is_file():
        raise BackupError(f"Backup ID was not found in {configured}: {backup_id}")
    archive.unlink()
    return archive


def _extract_validated(archive_path: Path, destination: Path) -> dict[str, Any]:
    manifest = validate_backup(archive_path)
    with zipfile.ZipFile(archive_path, "r") as archive:
        for entry in manifest["inventory"]:
            name = _safe_member_name(entry["path"])
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return manifest


def _has_user_files(path: Path) -> bool:
    return path.is_dir() and any(item.is_file() for item in path.rglob("*"))


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _activate_replacements(replacements: Sequence[tuple[Path, Path]], token: str) -> None:
    activated: list[tuple[Path, Path, bool]] = []
    try:
        for target, prepared in replacements:
            rollback = target.with_name(f".{target.name}.rollback-{token}")
            _remove_path(rollback)
            had_original = target.exists()
            if had_original:
                target.replace(rollback)
            activated.append((target, rollback, had_original))
            prepared.replace(target)
    except Exception:
        for target, rollback, had_original in reversed(activated):
            _remove_path(target)
            if had_original and rollback.exists():
                rollback.replace(target)
        raise
    for _, rollback, _ in activated:
        _remove_path(rollback)


def _prepare_directory(source: Path, target: Path, token: str) -> Path:
    prepared = target.with_name(f".{target.name}.restore-{token}")
    _remove_path(prepared)
    if source.is_dir():
        shutil.copytree(source, prepared)
    else:
        prepared.mkdir(parents=True)
    return prepared


def _checkpoint_database(database: Path) -> None:
    if not database.is_file():
        return
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        raise BackupError(
            f"Could not checkpoint active SQLite database before restore: {exc}"
        ) from exc


def restore_backup(
    source: Path,
    settings: Settings,
    *,
    paths: AppPaths | None = None,
    recovery_directory: Path,
    allow_db_only: bool = False,
) -> RestoreResult:
    """Validate, stage, and atomically activate a portable backup with rollback."""

    active_paths = paths or AppPaths.discover()
    archive_path = source.expanduser().resolve()
    _assert_outside_active_stores(archive_path, settings, active_paths)
    recovery_root = recovery_directory.expanduser().resolve()
    _assert_outside_active_stores(recovery_root, settings, active_paths)
    manifest = validate_backup(archive_path)
    backup_type = _normalize_type(str(manifest["backup_type"]))
    if (
        backup_type == "database"
        and not allow_db_only
        and (
            _has_user_files(settings.knowledge_path) or _has_user_files(settings.source_store_path)
        )
    ):
        raise BackupError(
            "Database-only restore would preserve the current Wiki and sources and may create "
            "a mismatched installation; rerun with --allow-db-only after reviewing this risk."
        )
    recovery_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    with _home_operation_lock(active_paths):
        recovery = create_backup(recovery_root, "full", settings, paths=active_paths)
        prepared_paths: list[Path] = []
        try:
            with tempfile.TemporaryDirectory(
                prefix=".knemora-restore-", dir=recovery_root
            ) as temporary_directory:
                extracted = Path(temporary_directory)
                manifest = _extract_validated(archive_path, extracted)
                staged_database = extracted / "database" / "knemora.db"
                _database_metadata(staged_database)
                database = _database_path(settings)
                database.parent.mkdir(parents=True, exist_ok=True)
                prepared_database = database.with_name(f".{database.name}.restore-{token}")
                _remove_path(prepared_database)
                restore_sqlite(staged_database, prepared_database)
                prepared_paths.append(prepared_database)
                replacements: list[tuple[Path, Path]] = [(database, prepared_database)]
                restored_roots = ["database"]

                if backup_type == "full":
                    for name, target in (
                        ("knowledge", settings.knowledge_path),
                        ("sources", settings.source_store_path),
                        ("datasets", active_paths.data / "datasets"),
                    ):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        prepared = _prepare_directory(extracted / name, target, token)
                        prepared_paths.append(prepared)
                        replacements.append((target, prepared))
                        restored_roots.append(name)
                    prepared_wiki = replacements[1][1]
                    wiki = WikiStore(prepared_wiki)
                    wiki.rebuild_index()
                    lint = wiki.lint()
                    if lint.errors:
                        raise BackupError(
                            f"Restored Wiki failed validation with {lint.errors} error(s)."
                        )
                    archived_registry = extracted / "config" / "models.json"
                    if archived_registry.is_file():
                        target = active_paths.model_registry
                        target.parent.mkdir(parents=True, exist_ok=True)
                        prepared = target.with_name(f".{target.name}.restore-{token}")
                        _remove_path(prepared)
                        shutil.copy2(archived_registry, prepared)
                        try:
                            ModelRegistry(prepared).user_models()
                        except ModelError as exc:
                            raise BackupError(f"Archived model registry is invalid: {exc}") from exc
                        prepared_paths.append(prepared)
                        replacements.append((target, prepared))
                        restored_roots.append("config/models.json")

                _checkpoint_database(database)
                for suffix in ("-wal", "-shm"):
                    database.with_name(database.name + suffix).unlink(missing_ok=True)
                _activate_replacements(replacements, token)
        except Exception as exc:
            for prepared in prepared_paths:
                _remove_path(prepared)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(
                f"Restore failed; the active installation was rolled back: {exc}"
            ) from exc
    model = manifest.get("model")
    model_id = model.get("model_id") if isinstance(model, dict) else None
    return RestoreResult(
        archive=archive_path,
        backup_type=backup_type,
        recovery_archive=recovery.archive,
        database=_database_path(settings),
        restored_roots=tuple(restored_roots),
        archived_model_id=model_id if isinstance(model_id, str) else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument("component", choices=("full", "all", "database", "db-only"))
    validate = subparsers.add_parser("validate")
    validate.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.operation == "backup":
        result = create_backup(args.destination, args.component, settings)
        print(result.archive)
    else:
        manifest = validate_backup(args.archive)
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
