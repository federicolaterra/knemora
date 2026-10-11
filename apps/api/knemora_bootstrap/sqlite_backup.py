"""Consistent SQLite backup/restore helpers using the standard backup API."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backup_sqlite(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"SQLite database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(temporary) as destination_connection,
        ):
            source_connection.backup(destination_connection)
            result = destination_connection.execute("PRAGMA integrity_check").fetchone()
            if result != ("ok",):
                raise RuntimeError(f"SQLite backup integrity check failed: {result!r}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_sqlite(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"SQLite backup does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restoring")
    backup_sqlite(source, temporary)
    temporary.replace(destination)
    for suffix in ("-wal", "-shm"):
        destination.with_name(destination.name + suffix).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if args.operation == "backup":
        backup_sqlite(args.source, args.destination)
    else:
        restore_sqlite(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
