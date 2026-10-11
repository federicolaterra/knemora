from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.main import create_app
from knemora_bootstrap.configuration import AppPaths
from knemora_bootstrap.update import UpdateError, UpdateService, UpdateSnapshot
from tests.fakes import FakeLLMProvider


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repository: Path, subject: str, marker: str) -> str:
    product = repository / "apps/api/app/product.py"
    product.parent.mkdir(parents=True, exist_ok=True)
    product.write_text(f'APP_VERSION = "0.1.0-alpha"\n# {marker}\n', encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", subject)
    return _git(repository, "rev-parse", "HEAD")


def _repositories(tmp_path: Path) -> tuple[Path, Path, str]:
    official = tmp_path / "official"
    official.mkdir()
    _git(official, "init", "-b", "master")
    _git(official, "config", "user.email", "tests@knemora.local")
    _git(official, "config", "user.name", "Knemora Tests")
    (official / ".gitignore").write_text(".env\n", encoding="utf-8")
    first = _commit(official, "initial", "one")
    installed = tmp_path / "installed"
    subprocess.run(
        ["git", "clone", str(official), str(installed)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(installed, "config", "user.email", "tests@knemora.local")
    _git(installed, "config", "user.name", "Knemora Tests")
    return official, installed, first


def _service(home: Path, installed: Path, official: Path) -> UpdateService:
    return UpdateService(
        AppPaths(repository=installed, data=home),
        official_repository=str(official),
        system="Darwin",
        machine="arm64",
    )


def test_check_detects_new_commit_even_when_application_version_is_unchanged(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    target = _commit(official, "feat: newer stable code", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)

    snapshot = _service(tmp_path / "home", installed, official).check()

    assert snapshot.state == "update_available"
    assert snapshot.installable is True
    assert snapshot.running and snapshot.running.app_version == "0.1.0-alpha"
    assert snapshot.target and snapshot.target.app_version == "0.1.0-alpha"
    assert snapshot.target.sha == target
    assert snapshot.changes[0].subject == "feat: newer stable code"


def test_development_dirty_and_diverged_checkouts_are_never_installable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    _commit(official, "official change", "official")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    _git(installed, "checkout", "-b", "develop")
    development = _service(tmp_path / "home-dev", installed, official).check()
    assert development.state == "development"
    assert development.installable is False

    _git(installed, "checkout", "master")
    (installed / "untracked.txt").write_text("local", encoding="utf-8")
    dirty = _service(tmp_path / "home-dirty", installed, official).check()
    assert dirty.state == "blocked"
    assert "local edits" in str(dirty.blocked_reason)
    (installed / "untracked.txt").unlink()

    _commit(installed, "local commit", "local")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", _git(installed, "rev-parse", "HEAD"))
    diverged = _service(tmp_path / "home-diverged", installed, official).check()
    assert diverged.relation == "diverged"
    assert diverged.installable is False


def test_offline_check_preserves_cache_without_claiming_current(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    _commit(official, "stable change", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    home = tmp_path / "home"
    service = _service(home, installed, official)
    available = service.check()
    service.official_repository = str(tmp_path / "missing")

    offline = service.check()

    assert available.state == "update_available"
    assert offline.state == "unavailable"
    assert offline.cached is True
    assert offline.checked_at == available.checked_at
    assert offline.installable is False


def test_target_is_pinned_and_duplicate_jobs_are_deduplicated(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    target = _commit(official, "stable change", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    service = _service(tmp_path / "home", installed, official)
    snapshot = service.check()
    assert snapshot.target and snapshot.target.sha == target
    _commit(official, "later stable change", "three")

    first = service.create_job(target)
    second = service.create_job(target)

    assert first["target_sha"] == target
    assert second["id"] == first["id"]


def test_staging_and_post_migration_failures_are_journaled_for_recovery(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    target = _commit(official, "stable change", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    service = _service(tmp_path / "home", installed, official)
    service.check()
    staging_job = service.create_job(target)
    monkeypatch.setattr(
        service,
        "_execute",
        lambda _job: (_ for _ in ()).throw(UpdateError("staging failed")),
    )
    with pytest.raises(UpdateError, match="staging failed"):
        service.execute_job(str(staging_job["id"]))
    assert service.read_job(str(staging_job["id"]))["status"] == "failed"

    migration_job = service.create_job(target)
    migration_job.update(
        status="running",
        stage="migrating",
        previous_checkout=str(tmp_path / "retained-checkout"),
        backup=str(tmp_path / "recovery.zip"),
    )
    service._write_job(migration_job)
    service._write_json(service.maintenance_path, {"job_id": migration_job["id"]})
    with pytest.raises(UpdateError, match="staging failed"):
        service.execute_job(str(migration_job["id"]))
    failed = service.read_job(str(migration_job["id"]))
    assert failed["status"] == "failed"
    assert failed["backup"].endswith("recovery.zip")
    assert service.maintenance_path.is_file()


def test_dead_worker_is_marked_interrupted(tmp_path: Path, monkeypatch: Any) -> None:
    official, installed, running = _repositories(tmp_path)
    target = _commit(official, "stable change", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    service = _service(tmp_path / "home", installed, official)
    service.check()
    job = service.create_job(target)
    job.update(status="running", worker_pid=99_999_999)
    service._write_job(job)

    assert service.active_job() is None
    interrupted = service.read_job(str(job["id"]))
    assert interrupted["status"] == "failed"
    assert interrupted["stage"] == "interrupted"


def test_full_flow_activates_pinned_checkout_and_preserves_isolated_home(
    tmp_path: Path, monkeypatch: Any
) -> None:
    official, installed, running = _repositories(tmp_path)
    target = _commit(official, "stable change", "two")
    monkeypatch.setenv("KNEMORA_RUNNING_COMMIT", running)
    home = tmp_path / "home"
    home.mkdir()
    user_data = home / "user-data.txt"
    user_data.write_text("preserve me", encoding="utf-8")
    (installed / ".env").write_text("KNEMORA_UPDATE_CHECK_ENABLED=true\n", encoding="utf-8")
    service = _service(home, installed, official)
    service.check()
    job = service.create_job(target)
    lifecycle: list[str] = []

    class FakeRuntime:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def status(self) -> tuple[SimpleNamespace, ...]:
            return (SimpleNamespace(name="api", running=True),)

        def current_mode(self) -> str:
            return "normal"

        def current_web_search_enabled(self) -> bool:
            return False

        def stop(self) -> None:
            lifecycle.append("stop")

        @staticmethod
        def http_ok(_url: str) -> bool:
            return True

    def fake_backup(*_args: object, **_kwargs: object) -> SimpleNamespace:
        assert user_data.read_text(encoding="utf-8") == "preserve me"
        lifecycle.append("backup")
        return SimpleNamespace(archive=tmp_path / "recovery.zip")

    monkeypatch.setattr("knemora_bootstrap.local_backup.create_backup", fake_backup)
    monkeypatch.setattr("knemora_bootstrap.platforms.detect_platform", lambda: object())
    monkeypatch.setattr("knemora_bootstrap.runtime.RuntimeManager", FakeRuntime)
    monkeypatch.setattr(service, "_prepare_staging", lambda _path: lifecycle.append("prepare"))
    monkeypatch.setattr(service, "_backup_settings", lambda: object())
    monkeypatch.setattr(service, "_selected_model_id", lambda: "default")
    monkeypatch.setattr(
        service,
        "_run_launcher",
        lambda _repository, *arguments: lifecycle.append(str(arguments[-1])),
    )

    service.execute_job(str(job["id"]))

    completed = service.read_job(str(job["id"]))
    assert completed["status"] == "complete"
    assert _git(installed, "rev-parse", "HEAD") == target
    assert user_data.read_text(encoding="utf-8") == "preserve me"
    assert (installed / ".env").is_file()
    assert Path(str(completed["previous_checkout"])).is_dir()
    assert not service.maintenance_path.exists()
    assert lifecycle[:3] == ["prepare", "stop", "backup"]


class StubUpdateService:
    def __init__(self, snapshot: UpdateSnapshot) -> None:
        self.snapshot = snapshot
        self.maintenance_path = Path("/definitely-not-present/maintenance.json")
        self.checked = 0

    def cached(self) -> UpdateSnapshot:
        return self.snapshot

    def active_job(self) -> None:
        return None

    def check(self) -> UpdateSnapshot:
        self.checked += 1
        return self.snapshot

    def check_if_due(self) -> UpdateSnapshot:
        return self.snapshot

    def schedule_check_if_due(self) -> None:
        return None


def _api_app(tmp_path: Path, service: StubUpdateService) -> FastAPI:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        llm_model="fake-local",
        source_store_path=tmp_path / "sources",
        knowledge_path=tmp_path / "knowledge",
        authentication_required=True,
        bootstrap_admin_email="admin@example.test",
        bootstrap_admin_password="correct horse battery staple",
        web_origin="http://localhost:5173",
    )
    return create_app(
        settings=settings,
        provider=FakeLLMProvider(),
        engine=engine,
        update_service=cast(UpdateService, service),
    )


def test_update_api_requires_administrator_and_local_origin(tmp_path: Path) -> None:
    async def exercise() -> None:
        neutral = UpdateService(
            AppPaths(repository=tmp_path, data=tmp_path / "home"),
            official_repository="unused",
        )._neutral("unavailable", "Not checked.")
        updates = StubUpdateService(neutral)
        app = _api_app(tmp_path, updates)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            denied = await client.get("/api/v1/updates")
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "admin@example.test",
                    "password": "correct horse battery staple",
                },
            )
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            allowed = await client.get("/api/v1/updates", headers=headers)
            await client.post(
                "/api/v1/roles",
                headers=headers,
                json={
                    "name": "reader",
                    "description": "No update authority",
                    "permissions": ["document.read"],
                },
            )
            await client.post(
                "/api/v1/users",
                headers=headers,
                json={
                    "email": "reader@example.test",
                    "display_name": "Reader",
                    "password": "reader password long enough",
                    "role_names": ["reader"],
                },
            )
            reader_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "reader@example.test",
                    "password": "reader password long enough",
                },
            )
            reader_denied = await client.get(
                "/api/v1/updates",
                headers={"Authorization": f"Bearer {reader_login.json()['access_token']}"},
            )
            wrong_origin = await client.post("/api/v1/updates/check", headers=headers)
            checked = await client.post(
                "/api/v1/updates/check",
                headers={**headers, "Origin": "http://localhost:5173"},
            )

        assert denied.status_code == 401
        assert allowed.status_code == 200
        assert reader_denied.status_code == 403
        assert wrong_origin.status_code == 403
        assert checked.status_code == 200
        assert updates.checked == 1

    asyncio.run(exercise())
