"""Versioned compatibility and migration contract for persistent Knemora homes."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.product import APP_VERSION

HOME_DESCRIPTOR_FORMAT_VERSION = 1
HOME_SCHEMA_VERSION = 1
MINIMUM_HOME_SCHEMA_VERSION = 1
HomeStatus = Literal[
    "empty", "legacy", "ready", "migration-required", "newer", "corrupt", "unknown"
]

KNOWN_HOME_ENTRIES = frozenset(
    {
        "bin",
        "cache",
        "config",
        "data",
        "datasets",
        "demo",
        "logs",
        "models",
        "python",
        "runtime",
        "sources",
        "wiki",
    }
)
LEGACY_INDICATORS = frozenset(
    {"config", "data", "datasets", "demo", "logs", "models", "runtime", "sources", "wiki"}
)


class HomeCompatibilityError(RuntimeError):
    """Persistent application state is incompatible or unsafe to mutate."""


@dataclass(frozen=True)
class HomeDescriptor:
    format_version: int
    home_schema_version: int
    created_by_knemora_version: str
    last_migrated_by_knemora_version: str

    @classmethod
    def from_payload(cls, payload: Any) -> HomeDescriptor:
        if not isinstance(payload, dict):
            raise HomeCompatibilityError("Application-home descriptor root must be an object.")
        required = {
            "formatVersion": int,
            "homeSchemaVersion": int,
            "createdByKnemoraVersion": str,
            "lastMigratedByKnemoraVersion": str,
        }
        for key, expected_type in required.items():
            value = payload.get(key)
            if not isinstance(value, expected_type) or isinstance(value, bool):
                raise HomeCompatibilityError(
                    f"Application-home descriptor field {key!r} is missing or invalid."
                )
        return cls(
            format_version=payload["formatVersion"],
            home_schema_version=payload["homeSchemaVersion"],
            created_by_knemora_version=payload["createdByKnemoraVersion"],
            last_migrated_by_knemora_version=payload["lastMigratedByKnemoraVersion"],
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "formatVersion": self.format_version,
            "homeSchemaVersion": self.home_schema_version,
            "createdByKnemoraVersion": self.created_by_knemora_version,
            "lastMigratedByKnemoraVersion": self.last_migrated_by_knemora_version,
        }


@dataclass(frozen=True)
class HomeInspection:
    status: HomeStatus
    detail: str
    descriptor: HomeDescriptor | None = None


@dataclass(frozen=True)
class HomeMigrationStep:
    """One ordered home migration; SQL schema changes remain owned by Alembic."""

    source_version: int
    target_version: int
    precondition: Callable[[Path], None]
    affected_resources: tuple[str, ...]
    requires_recovery_snapshot: bool
    apply: Callable[[Path], None]
    verify: Callable[[Path], None]
    recovery: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


class HomeCompatibilityService:
    """Single owner for home recognition, version guards, and ordered migrations."""

    def __init__(
        self,
        home: Path,
        *,
        repository: Path | None = None,
        current_version: int = HOME_SCHEMA_VERSION,
        migrations: Sequence[HomeMigrationStep] = (),
        recovery_snapshot: Callable[[HomeMigrationStep], str] | None = None,
        writers_quiesced: Callable[[], bool] | None = None,
    ) -> None:
        self.home = home.expanduser().resolve()
        self.repository = repository.resolve() if repository else None
        self.current_version = current_version
        self.migrations = tuple(migrations)
        self.recovery_snapshot = recovery_snapshot
        self.writers_quiesced = writers_quiesced

    @property
    def descriptor_path(self) -> Path:
        return self.home / "config" / "home.json"

    @property
    def journal_path(self) -> Path:
        return self.home / "config" / "home-migration.json"

    @property
    def lock_path(self) -> Path:
        return self.home / "runtime" / "home-operation.lock"

    def inspect(self) -> HomeInspection:
        if not self.home.exists():
            return HomeInspection("empty", f"new application home: {self.home}")
        if not self.home.is_dir():
            return HomeInspection("corrupt", f"KNEMORA_HOME is not a directory: {self.home}")
        descriptor = self.descriptor_path
        if descriptor.exists():
            try:
                self._assert_safe_path(descriptor)
                if descriptor.is_symlink() or not descriptor.is_file():
                    raise HomeCompatibilityError("descriptor is not a regular file")
                value = HomeDescriptor.from_payload(
                    json.loads(descriptor.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, HomeCompatibilityError) as exc:
                return HomeInspection("corrupt", f"invalid descriptor {descriptor}: {exc}")
            if value.format_version != HOME_DESCRIPTOR_FORMAT_VERSION:
                return HomeInspection(
                    "newer",
                    "application-home descriptor format "
                    f"{value.format_version} is unsupported; supported format is "
                    f"{HOME_DESCRIPTOR_FORMAT_VERSION}",
                    value,
                )
            if value.home_schema_version > self.current_version:
                return HomeInspection(
                    "newer",
                    f"home schema {value.home_schema_version} is newer than supported "
                    f"schema {self.current_version}",
                    value,
                )
            if value.home_schema_version < MINIMUM_HOME_SCHEMA_VERSION:
                return HomeInspection(
                    "corrupt",
                    f"home schema {value.home_schema_version} is invalid",
                    value,
                )
            journal_problem = self._unfinished_journal()
            if journal_problem:
                return HomeInspection("migration-required", journal_problem, value)
            if value.home_schema_version < self.current_version:
                return HomeInspection(
                    "migration-required",
                    f"home schema {value.home_schema_version} requires setup migration to "
                    f"{self.current_version}",
                    value,
                )
            return HomeInspection("ready", f"home schema {self.current_version}", value)

        entries = {item.name for item in self.home.iterdir() if item.name != ".DS_Store"}
        if not entries:
            return HomeInspection("empty", f"empty application home: {self.home}")
        unknown = sorted(entries - KNOWN_HOME_ENTRIES)
        if unknown:
            return HomeInspection(
                "unknown",
                "nonempty home has no descriptor and contains unknown top-level entries: "
                + ", ".join(unknown),
            )
        if entries & LEGACY_INDICATORS:
            return HomeInspection(
                "legacy", "recognized pre-0.8.5 application home; baseline registration required"
            )
        return HomeInspection(
            "legacy", "recognized bootstrap-only home; baseline registration required"
        )

    def validate_ready(self) -> HomeDescriptor:
        inspection = self.inspect()
        if inspection.status != "ready" or inspection.descriptor is None:
            raise HomeCompatibilityError(
                f"Application home is {inspection.status}: {inspection.detail}. "
                "Run ./knemora setup; no persistent data was changed."
            )
        return inspection.descriptor

    def ensure_current(self) -> HomeDescriptor:
        inspection = self.inspect()
        if inspection.status == "ready" and inspection.descriptor is not None:
            return inspection.descriptor
        if inspection.status in {"newer", "corrupt", "unknown"}:
            raise HomeCompatibilityError(
                f"Application home is {inspection.status}: {inspection.detail}. "
                "No files were changed."
            )
        self.home.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._migration_lock():
            inspection = self.inspect()
            if inspection.status == "ready" and inspection.descriptor is not None:
                return inspection.descriptor
            if inspection.status in {"empty", "legacy"}:
                if inspection.status == "legacy":
                    self._validate_legacy_database_revision()
                return self._register_baseline(inspection.status)
            if inspection.status == "migration-required" and inspection.descriptor is not None:
                return self._migrate(inspection.descriptor)
            raise HomeCompatibilityError(
                f"Application home cannot be prepared: {inspection.status}: {inspection.detail}"
            )

    def _register_baseline(self, source: str) -> HomeDescriptor:
        descriptor = HomeDescriptor(
            format_version=HOME_DESCRIPTOR_FORMAT_VERSION,
            home_schema_version=self.current_version,
            created_by_knemora_version=APP_VERSION,
            last_migrated_by_knemora_version=APP_VERSION,
        )
        self._write_journal(
            state="running",
            source_version=0,
            target_version=self.current_version,
            operation=f"{source}-baseline-registration",
            recovery="metadata-only; remove config/home.json to retry before serving",
        )
        _atomic_json(self.descriptor_path, descriptor.as_payload())
        self._write_journal(
            state="completed",
            source_version=0,
            target_version=self.current_version,
            operation=f"{source}-baseline-registration",
            recovery="descriptor committed and verified",
        )
        return self.validate_ready()

    def _migrate(self, descriptor: HomeDescriptor) -> HomeDescriptor:
        plan = self._migration_plan(descriptor.home_schema_version)
        if self.writers_quiesced is not None and not self.writers_quiesced():
            raise HomeCompatibilityError(
                "Managed writers are active; stop Knemora before running the home migration."
            )
        current = descriptor
        for step in plan:
            step.precondition(self.home)
            recovery = step.recovery
            if step.requires_recovery_snapshot:
                if self.recovery_snapshot is None:
                    raise HomeCompatibilityError(
                        f"Migration {step.source_version}->{step.target_version} requires a "
                        "verified external recovery snapshot."
                    )
                recovery = self.recovery_snapshot(step)
                if not recovery:
                    raise HomeCompatibilityError("Recovery snapshot preparation returned no path.")
            self._write_journal(
                state="running",
                source_version=step.source_version,
                target_version=step.target_version,
                operation="home-migration",
                recovery=recovery,
                affected_resources=step.affected_resources,
            )
            try:
                step.apply(self.home)
                step.verify(self.home)
                current = HomeDescriptor(
                    format_version=current.format_version,
                    home_schema_version=step.target_version,
                    created_by_knemora_version=current.created_by_knemora_version,
                    last_migrated_by_knemora_version=APP_VERSION,
                )
                _atomic_json(self.descriptor_path, current.as_payload())
                self._write_journal(
                    state="completed",
                    source_version=step.source_version,
                    target_version=step.target_version,
                    operation="home-migration",
                    recovery=recovery,
                    affected_resources=step.affected_resources,
                )
            except Exception as exc:
                self._write_journal(
                    state="failed",
                    source_version=step.source_version,
                    target_version=step.target_version,
                    operation="home-migration",
                    recovery=recovery,
                    error=str(exc),
                    affected_resources=step.affected_resources,
                )
                raise HomeCompatibilityError(
                    f"Home migration {step.source_version}->{step.target_version} failed. "
                    f"Recovery: {recovery}. Cause: {exc}"
                ) from exc
        return self.validate_ready()

    def _migration_plan(self, source_version: int) -> tuple[HomeMigrationStep, ...]:
        by_source = {step.source_version: step for step in self.migrations}
        plan: list[HomeMigrationStep] = []
        current = source_version
        seen: set[int] = set()
        while current < self.current_version:
            if current in seen or current not in by_source:
                raise HomeCompatibilityError(
                    f"No complete home migration path exists from {source_version} to "
                    f"{self.current_version}."
                )
            seen.add(current)
            step = by_source[current]
            if step.target_version <= current or step.target_version > self.current_version:
                raise HomeCompatibilityError(
                    f"Invalid migration step {step.source_version}->{step.target_version}."
                )
            plan.append(step)
            current = step.target_version
        return tuple(plan)

    def _unfinished_journal(self) -> str | None:
        if not self.journal_path.is_file():
            return None
        try:
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"migration journal is invalid: {exc}"
        state = payload.get("state") if isinstance(payload, dict) else None
        if state in {"running", "failed", "pending"}:
            return (
                f"migration journal is {state}; recovery={payload.get('recovery', 'unavailable')}"
            )
        return None

    def _write_journal(
        self,
        *,
        state: str,
        source_version: int,
        target_version: int,
        operation: str,
        recovery: str,
        error: str | None = None,
        affected_resources: Sequence[str] = (),
    ) -> None:
        payload: dict[str, Any] = {
            "formatVersion": 1,
            "state": state,
            "operation": operation,
            "sourceHomeSchemaVersion": source_version,
            "targetHomeSchemaVersion": target_version,
            "affectedResources": list(affected_resources),
            "recovery": recovery,
            "updatedAt": _utc_now(),
        }
        if error:
            payload["error"] = error
        _atomic_json(self.journal_path, payload)

    def _validate_legacy_database_revision(self) -> None:
        database = self.home / "data" / "knemora.db"
        if not database.is_file():
            return
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.Error as exc:
            raise HomeCompatibilityError(
                f"Legacy SQLite metadata is unreadable; descriptor was not written: {exc}"
            ) from exc
        if row is None or not isinstance(row[0], str):
            raise HomeCompatibilityError(
                "Legacy SQLite database has no Alembic revision; descriptor was not written."
            )
        known = self._known_alembic_revisions()
        if known and row[0] not in known:
            raise HomeCompatibilityError(
                f"SQLite Alembic revision {row[0]!r} is unknown to this checkout; "
                "it may be newer. Use a compatible Knemora build."
            )

    def _known_alembic_revisions(self) -> set[str]:
        if self.repository is None:
            return set()
        revisions: set[str] = set()
        directory = self.repository / "apps" / "api" / "migrations" / "versions"
        for path in directory.glob("*.py"):
            match = re.search(
                r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']',
                path.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                revisions.add(match.group(1))
        return revisions

    def _assert_safe_path(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.home)
        except ValueError as exc:
            raise HomeCompatibilityError(f"Path escapes KNEMORA_HOME: {path}") from exc
        current = self.home
        for part in relative.parts[:-1]:
            current /= part
            if current.exists() and current.is_symlink():
                raise HomeCompatibilityError(f"Path traverses a symbolic link: {current}")

    @contextmanager
    def _migration_lock(self) -> Iterator[None]:
        self._assert_safe_path(self.lock_path)
        with self.lock_path.open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HomeCompatibilityError(
                    f"Another setup, restore, or migration owns {self.lock_path}."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
