"""Safe explicit relational import from PostgreSQL into Knemora's SQLite store."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, Uuid, create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import create_database_engine


@dataclass(frozen=True)
class MigrationResult:
    target: Path
    backup_directory: Path
    row_counts: dict[str, int]
    already_migrated: bool = False


def _safe_source_identity(source_url: str) -> str:
    return make_url(source_url).render_as_string(hide_password=True)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, (datetime, date, time)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (dict, list)):
        return value
    raise TypeError(f"Unsupported backup value type: {type(value).__name__}")


def _source_tables(source: Connection) -> dict[str, Table]:
    available = set(inspect(source).get_table_names())
    expected = set(Base.metadata.tables)
    missing = expected - available
    if missing:
        raise RuntimeError(
            "Source database is missing Knemora tables: " + ", ".join(sorted(missing))
        )
    metadata = MetaData()
    return {
        table.name: Table(table.name, metadata, autoload_with=source)
        for table in Base.metadata.sorted_tables
    }


def _counts(connection: Connection, tables: dict[str, Table]) -> dict[str, int]:
    return {
        name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
        for name, table in tables.items()
    }


def _export_source_backup(
    source: Connection,
    tables: dict[str, Table],
    backup_directory: Path,
    source_identity: str,
) -> dict[str, int]:
    backup_directory.mkdir(parents=True, exist_ok=False)
    counts: dict[str, int] = {}
    for name, table in tables.items():
        count = 0
        with (backup_directory / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            rows = source.execute(select(table).order_by(*table.primary_key.columns))
            for row in rows.mappings():
                payload = {key: _json_value(value) for key, value in row.items()}
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                count += 1
        counts[name] = count
    manifest = {
        "format": "knemora-postgresql-logical-backup-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source": source_identity,
        "row_counts": counts,
    }
    (backup_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return counts


def _run_sqlite_migrations(api_directory: Path, database_url: str) -> None:
    config = Config(str(api_directory / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def _copy_rows(
    source: Connection,
    target: Connection,
    source_tables: dict[str, Table],
) -> None:
    for target_table in Base.metadata.sorted_tables:
        source_table = source_tables[target_table.name]
        target.execute(target_table.delete())
        rows = source.execute(select(source_table).order_by(*source_table.primary_key.columns))
        while batch := rows.mappings().fetchmany(500):
            converted: list[dict[str, Any]] = []
            for row in batch:
                values = dict(row)
                for column in target_table.columns:
                    value = values.get(column.name)
                    if isinstance(column.type, Uuid) and isinstance(value, str):
                        values[column.name] = UUID(value)
                converted.append(values)
            target.execute(target_table.insert(), converted)
    target.execute(
        text(
            "UPDATE application_versions "
            "SET app_version = '0.8.4', schema_version = 10, updated_at = CURRENT_TIMESTAMP "
            "WHERE component = 'core'"
        )
    )


def _validate_target(engine: Engine, expected: dict[str, int]) -> None:
    with engine.connect() as connection:
        actual = _counts(connection, {table.name: table for table in Base.metadata.sorted_tables})
        if actual != expected:
            mismatches = {
                name: {"source": expected[name], "sqlite": actual.get(name)}
                for name in expected
                if actual.get(name) != expected[name]
            }
            raise RuntimeError(f"SQLite row-count validation failed: {mismatches}")
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
        if violations:
            raise RuntimeError(f"SQLite foreign-key validation failed: {violations[:10]}")
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")


def _existing_receipt_is_valid(
    receipt: Path,
    target: Path,
    source_identity: str,
    source_counts: dict[str, int],
) -> Path | None:
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        recorded_counts = payload["row_counts"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if payload.get("source") != source_identity or recorded_counts != source_counts:
        return None
    engine = create_database_engine(f"sqlite+pysqlite:///{target}")
    try:
        _validate_target(engine, source_counts)
    except Exception:
        return None
    finally:
        engine.dispose()
    backup_directory = payload.get("backup_directory")
    return Path(backup_directory) if isinstance(backup_directory, str) else receipt.parent


def migrate_postgresql_to_sqlite(
    *,
    source_url: str,
    target: Path,
    api_directory: Path,
    backup_root: Path,
    require_postgresql: bool = True,
) -> MigrationResult:
    """Export, import, validate, and atomically promote a SQLite database."""

    source_backend = make_url(source_url).get_backend_name()
    if require_postgresql and source_backend != "postgresql":
        raise RuntimeError("The migration source must be an explicit PostgreSQL URL.")
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup_root.resolve().is_relative_to(target.parent.parent):
        raise RuntimeError(f"Migration backup must be outside Knemora data: {target.parent.parent}")
    source_identity = _safe_source_identity(source_url)
    receipt = target.with_suffix(target.suffix + ".postgresql-import.json")
    source_engine = create_engine(source_url, pool_pre_ping=True)
    temporary = target.with_name(f".{target.name}.importing-{uuid4().hex}")
    target_url = f"sqlite+pysqlite:///{temporary}"
    backup_directory: Path | None = None
    try:
        connection = source_engine.connect()
        if source_backend == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection, connection.begin():
            source_tables = _source_tables(connection)
            source_counts = _counts(connection, source_tables)
            existing_backup = (
                _existing_receipt_is_valid(receipt, target, source_identity, source_counts)
                if target.is_file()
                else None
            )
            if existing_backup is not None:
                return MigrationResult(
                    target, existing_backup, source_counts, already_migrated=True
                )
            if target.is_file() and target.stat().st_size:
                raise RuntimeError(
                    f"Refusing to replace existing SQLite database without a matching "
                    f"migration receipt: {target}"
                )
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            backup_directory = backup_root.resolve() / f"postgresql-migration-{timestamp}"
            exported_counts = _export_source_backup(
                connection, source_tables, backup_directory, source_identity
            )
            if exported_counts != source_counts:
                raise RuntimeError("PostgreSQL changed while its logical backup was being created.")
            _run_sqlite_migrations(api_directory, target_url)
            target_engine = create_database_engine(target_url)
            try:
                with target_engine.begin() as target_connection:
                    _copy_rows(connection, target_connection, source_tables)
                _validate_target(target_engine, source_counts)
                with target_engine.connect() as target_connection:
                    target_connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                target_engine.dispose()
        temporary.replace(target)
        for suffix in ("-wal", "-shm"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        report = {
            "format": "knemora-postgresql-import-v1",
            "completed_at": datetime.now(UTC).isoformat(),
            "source": source_identity,
            "source_fingerprint": hashlib.sha256(source_identity.encode()).hexdigest(),
            "backup_directory": str(backup_directory),
            "target": str(target),
            "row_counts": source_counts,
            "foreign_keys": "ok",
            "integrity": "ok",
        }
        receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return MigrationResult(target, backup_directory, source_counts)
    except Exception:
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        if backup_directory is not None and backup_directory.exists():
            failed = backup_directory.with_name(backup_directory.name + ".failed")
            if failed.exists():
                shutil.rmtree(failed)
            backup_directory.replace(failed)
        raise
    finally:
        source_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--api-directory", required=True, type=Path)
    parser.add_argument("--backup-root", required=True, type=Path)
    args = parser.parse_args(argv)
    result = migrate_postgresql_to_sqlite(
        source_url=args.source_url,
        target=args.target,
        api_directory=args.api_directory,
        backup_root=args.backup_root,
    )
    print(
        json.dumps(
            {
                "target": str(result.target),
                "backup_directory": str(result.backup_directory),
                "row_counts": result.row_counts,
                "already_migrated": result.already_migrated,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
