from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

from app.home import (
    HOME_DESCRIPTOR_FORMAT_VERSION,
    HOME_SCHEMA_VERSION,
    HomeCompatibilityError,
    HomeCompatibilityService,
    HomeMigrationStep,
)
from app.product import APP_VERSION
from knemora_bootstrap.configuration import AppPaths
from knemora_bootstrap.native_runtime import (
    NativeRuntimeError,
    NativeRuntimeManager,
    load_runtime_manifest,
    select_runtime_target,
)

REPOSITORY = Path(__file__).resolve().parents[3]


def _write_descriptor(home: Path, schema_version: int) -> None:
    config = home / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "home.json").write_text(
        json.dumps(
            {
                "formatVersion": HOME_DESCRIPTOR_FORMAT_VERSION,
                "homeSchemaVersion": schema_version,
                "createdByKnemoraVersion": "0.8.4",
                "lastMigratedByKnemoraVersion": "0.8.4",
            }
        ),
        encoding="utf-8",
    )


def _runtime_paths(tmp_path: Path) -> AppPaths:
    repository = tmp_path / "repository"
    manifest = repository / "infrastructure" / "runtime-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes((REPOSITORY / "infrastructure/runtime-manifest.json").read_bytes())
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.initialize()
    return paths


def test_fresh_and_legacy_homes_get_a_metadata_only_baseline(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    descriptor = HomeCompatibilityService(fresh, repository=REPOSITORY).ensure_current()

    assert descriptor.home_schema_version == HOME_SCHEMA_VERSION
    assert descriptor.created_by_knemora_version == APP_VERSION
    assert HomeCompatibilityService(fresh).inspect().status == "ready"

    legacy = tmp_path / "legacy"
    sentinel = legacy / "models" / "keep.gguf"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")

    first = HomeCompatibilityService(legacy, repository=REPOSITORY).ensure_current()
    second = HomeCompatibilityService(legacy, repository=REPOSITORY).ensure_current()

    assert first == second
    assert sentinel.read_text(encoding="utf-8") == "keep"
    journal = json.loads((legacy / "config/home-migration.json").read_text(encoding="utf-8"))
    assert journal["state"] == "completed"
    assert journal["operation"] == "legacy-baseline-registration"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"unexpected": True}, "corrupt"),
        (
            {
                "formatVersion": HOME_DESCRIPTOR_FORMAT_VERSION + 1,
                "homeSchemaVersion": HOME_SCHEMA_VERSION,
                "createdByKnemoraVersion": APP_VERSION,
                "lastMigratedByKnemoraVersion": APP_VERSION,
            },
            "newer",
        ),
        (
            {
                "formatVersion": HOME_DESCRIPTOR_FORMAT_VERSION,
                "homeSchemaVersion": HOME_SCHEMA_VERSION + 1,
                "createdByKnemoraVersion": APP_VERSION,
                "lastMigratedByKnemoraVersion": APP_VERSION,
            },
            "newer",
        ),
    ],
)
def test_invalid_or_newer_descriptor_is_refused_without_rewrite(
    tmp_path: Path, payload: dict[str, object], status: str
) -> None:
    descriptor = tmp_path / "home/config/home.json"
    descriptor.parent.mkdir(parents=True)
    original = json.dumps(payload)
    descriptor.write_text(original, encoding="utf-8")
    service = HomeCompatibilityService(tmp_path / "home")

    assert service.inspect().status == status
    with pytest.raises(HomeCompatibilityError, match=f"home is {status}"):
        service.ensure_current()
    assert descriptor.read_text(encoding="utf-8") == original


def test_unknown_nonempty_home_is_not_claimed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    unknown = home / "someone-elses-data"
    unknown.mkdir(parents=True)

    with pytest.raises(HomeCompatibilityError, match="unknown"):
        HomeCompatibilityService(home).ensure_current()

    assert not (home / "config/home.json").exists()


def test_legacy_database_with_unknown_revision_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    database = home / "data/knemora.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('newer-than-this-checkout')")

    with pytest.raises(HomeCompatibilityError, match="unknown to this checkout"):
        HomeCompatibilityService(home, repository=REPOSITORY).ensure_current()

    assert not (home / "config/home.json").exists()


def test_home_migrations_are_ordered_verified_and_recoverable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_descriptor(home, 1)
    events: list[str] = []

    def step(name: str, source: int, target: int) -> HomeMigrationStep:
        def apply(path: Path) -> None:
            events.append(f"apply-{name}")
            (path / f"migration-{name}").write_text(name, encoding="utf-8")

        def verify(path: Path) -> None:
            events.append(f"verify-{name}")
            assert (path / f"migration-{name}").read_text(encoding="utf-8") == name

        return HomeMigrationStep(
            source_version=source,
            target_version=target,
            precondition=lambda path: events.append(f"precondition-{name}"),
            affected_resources=(f"migration-{name}",),
            requires_recovery_snapshot=True,
            apply=apply,
            verify=verify,
            recovery=f"restore migration {name}",
        )

    service = HomeCompatibilityService(
        home,
        current_version=3,
        migrations=(step("one", 1, 2), step("two", 2, 3)),
        recovery_snapshot=lambda migration: f"snapshot-{migration.source_version}",
        writers_quiesced=lambda: True,
    )

    descriptor = service.ensure_current()

    assert descriptor.home_schema_version == 3
    assert descriptor.created_by_knemora_version == "0.8.4"
    assert descriptor.last_migrated_by_knemora_version == APP_VERSION
    assert events == [
        "precondition-one",
        "apply-one",
        "verify-one",
        "precondition-two",
        "apply-two",
        "verify-two",
    ]
    journal = json.loads(service.journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "completed"
    assert journal["recovery"] == "snapshot-2"


def test_failed_home_migration_keeps_last_committed_descriptor(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_descriptor(home, 1)

    def fail(_: Path) -> None:
        raise RuntimeError("synthetic failure")

    migration = HomeMigrationStep(
        source_version=1,
        target_version=2,
        precondition=lambda _: None,
        affected_resources=("config",),
        requires_recovery_snapshot=False,
        apply=fail,
        verify=lambda _: None,
        recovery="restore the saved config",
    )
    service = HomeCompatibilityService(home, current_version=2, migrations=(migration,))

    with pytest.raises(HomeCompatibilityError, match="synthetic failure"):
        service.ensure_current()

    descriptor = json.loads(service.descriptor_path.read_text(encoding="utf-8"))
    journal = json.loads(service.journal_path.read_text(encoding="utf-8"))
    assert descriptor["homeSchemaVersion"] == 1
    assert journal["state"] == "failed"
    assert service.inspect().status == "migration-required"


def test_runtime_manifest_declares_supported_and_future_platform_boundaries() -> None:
    manifest = load_runtime_manifest(REPOSITORY)
    target = select_runtime_target(
        manifest, "llamaCpp", system="Darwin", machine="arm64", backend="metal"
    )

    assert target.version == "b11146"
    assert target.archive_sha256 == (
        "1ad3f9eff80edb9dbef4259ad564d1720612ef7eea48fa4afed0e54f5f3d5711"
    )
    for system, machine in (("Linux", "x86_64"), ("Linux", "aarch64"), ("Windows", "AMD64")):
        with pytest.raises(NativeRuntimeError, match="not supported yet"):
            select_runtime_target(
                manifest, "llamaCpp", system=system, machine=machine, backend="cpu"
            )


@pytest.mark.parametrize(("name", "kind"), [("../escape", "file"), ("payload/link", "link")])
def test_native_archive_rejects_traversal_and_links(tmp_path: Path, name: str, kind: str) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo(name)
        if kind == "link":
            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/escape"
            bundle.addfile(info)
        else:
            body = b"unsafe"
            info.size = len(body)
            bundle.addfile(info, io.BytesIO(body))

    with pytest.raises(NativeRuntimeError, match="unsafe path|unsafe link|unsupported entry"):
        NativeRuntimeManager._extract_archive(archive, tmp_path / "output")


def test_runtime_resolution_never_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _runtime_paths(tmp_path)
    fake_bin = tmp_path / "path-bin"
    fake_bin.mkdir()
    fake = fake_bin / "llama-server"
    fake.write_text("#!/bin/sh\necho should-not-run\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("LLAMA_SERVER_BIN", raising=False)
    monkeypatch.delenv("LLAMA_CPP_DIR", raising=False)

    with pytest.raises(NativeRuntimeError, match="No verified llama.cpp runtime"):
        NativeRuntimeManager(paths).resolve_llama()


def test_operator_override_must_be_absolute_and_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _runtime_paths(tmp_path)
    monkeypatch.setenv("LLAMA_SERVER_BIN", "relative/llama-server")

    with pytest.raises(NativeRuntimeError, match="absolute path"):
        NativeRuntimeManager(paths).resolve_llama()
