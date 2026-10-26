"""Shared, pinned update planning and execution for the CLI and HTTP API."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from knemora_bootstrap.configuration import (
    AppPaths,
    read_backup_path,
    read_env,
    runtime_environment,
)

OFFICIAL_REPOSITORY = "https://github.com/federicolaterra/knemora.git"
OFFICIAL_REPOSITORY_WEB = "https://github.com/federicolaterra/knemora"
UPDATE_CHANNEL = "master"
UPDATE_REF = "refs/knemora/updates/master"
CHECK_INTERVAL = timedelta(hours=24)
RETRY_BACKOFF = timedelta(minutes=30)
MAX_CHANGE_ITEMS = 20

UpdateState = Literal[
    "checking",
    "up_to_date",
    "update_available",
    "development",
    "blocked",
    "unavailable",
    "disabled",
]


class UpdateError(RuntimeError):
    """An update check or installation could not safely continue."""


@dataclass(frozen=True)
class Revision:
    sha: str
    short_sha: str
    app_version: str | None
    tag: str | None


@dataclass(frozen=True)
class ChangeItem:
    sha: str
    short_sha: str
    subject: str
    url: str
    pull_request_number: int | None = None
    pull_request_title: str | None = None
    pull_request_url: str | None = None


@dataclass(frozen=True)
class UpdateSnapshot:
    state: UpdateState
    channel: str
    checked_at: str | None
    last_attempt_at: str
    cached: bool
    running: Revision | None
    target: Revision | None
    branch: str | None
    relation: str
    dirty: bool
    installable: bool
    blocked_reason: str | None
    error: str | None
    changes: tuple[ChangeItem, ...]
    changes_truncated: bool
    dependency_changes: tuple[str, ...]
    migration_changes: tuple[str, ...]
    restart_required: bool
    privacy_notice: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> UpdateSnapshot:
        running = value.get("running")
        target = value.get("target")
        return cls(
            state=value["state"],
            channel=str(value.get("channel", UPDATE_CHANNEL)),
            checked_at=value.get("checked_at"),
            last_attempt_at=str(value["last_attempt_at"]),
            cached=bool(value.get("cached", False)),
            running=Revision(**running) if isinstance(running, dict) else None,
            target=Revision(**target) if isinstance(target, dict) else None,
            branch=value.get("branch"),
            relation=str(value.get("relation", "unknown")),
            dirty=bool(value.get("dirty", False)),
            installable=bool(value.get("installable", False)),
            blocked_reason=value.get("blocked_reason"),
            error=value.get("error"),
            changes=tuple(ChangeItem(**item) for item in value.get("changes", [])),
            changes_truncated=bool(value.get("changes_truncated", False)),
            dependency_changes=tuple(value.get("dependency_changes", [])),
            migration_changes=tuple(value.get("migration_changes", [])),
            restart_required=bool(value.get("restart_required", True)),
            privacy_notice=str(value.get("privacy_notice", UpdateService.privacy_notice)),
        )


class UpdateService:
    """One update authority shared by launcher and API adapters."""

    privacy_notice = (
        "Checks contact the official Knemora repository on GitHub and send no documents, "
        "prompts, Wiki content, credentials, or private knowledge."
    )

    def __init__(
        self,
        paths: AppPaths,
        *,
        official_repository: str | None = None,
        system: str | None = None,
        machine: str | None = None,
        network_timeout: int = 20,
    ) -> None:
        self.paths = paths
        self.official_repository = official_repository or self._configured_source()
        self.system = system or platform.system()
        self.machine = machine or platform.machine()
        self.network_timeout = network_timeout
        self._check_guard = threading.Lock()
        self._schedule_guard = threading.Lock()
        self._check_scheduled = False

    def _configured_source(self) -> str:
        source_path = self.paths.repository / "infrastructure/update-source.json"
        try:
            value = json.loads(source_path.read_text(encoding="utf-8"))
            stable = value["channels"]["stable"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise UpdateError(
                f"Official update source configuration is invalid: {source_path}"
            ) from exc
        if (
            value.get("formatVersion") != 1
            or value.get("provider") != "github"
            or value.get("repository") != "federicolaterra/knemora"
            or value.get("transport") != OFFICIAL_REPOSITORY
            or stable != {"kind": "git-branch", "ref": UPDATE_CHANNEL}
        ):
            raise UpdateError("Official update source identity or stable channel is invalid.")
        return OFFICIAL_REPOSITORY

    @property
    def updates_directory(self) -> Path:
        return self.paths.runtime / "updates"

    @property
    def cache_path(self) -> Path:
        return self.paths.config / "update-check.json"

    @property
    def maintenance_path(self) -> Path:
        return self.paths.runtime / "maintenance.json"

    @property
    def checks_enabled(self) -> bool:
        value = read_env(self.paths.repository / ".env").get(
            "KNEMORA_UPDATE_CHECK_ENABLED",
            os.environ.get("KNEMORA_UPDATE_CHECK_ENABLED", "true"),
        )
        value = value.strip().casefold()
        return value not in {"0", "false", "no", "off"}

    def cached(self) -> UpdateSnapshot:
        if not self.checks_enabled:
            return self._neutral("disabled", "Automatic update checks are disabled.")
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            snapshot = UpdateSnapshot.from_dict(value)
            return replace(
                snapshot,
                state="checking" if self._check_scheduled else snapshot.state,
                cached=True,
                installable=False if self._check_scheduled else snapshot.installable,
            )
        except (OSError, ValueError, KeyError, TypeError):
            snapshot = self._neutral("unavailable", "Updates have not been checked yet.")
            return replace(snapshot, state="checking") if self._check_scheduled else snapshot

    def check_if_due(self) -> UpdateSnapshot:
        if not self.checks_enabled:
            return self._neutral("disabled", "Automatic update checks are disabled.")
        cached = self.cached()
        if not self.cache_path.is_file():
            return self.check()
        attempt = _parse_time(cached.last_attempt_at)
        interval = CHECK_INTERVAL if cached.checked_at else RETRY_BACKOFF
        if attempt is not None and datetime.now(UTC) - attempt < interval:
            return cached
        return self.check()

    def schedule_check_if_due(self) -> None:
        """Start a due automatic check without delaying login or startup."""

        with self._schedule_guard:
            if self._check_scheduled or not self.checks_enabled:
                return
            cached = self.cached()
            attempted = _parse_time(cached.last_attempt_at)
            interval = CHECK_INTERVAL if cached.checked_at else RETRY_BACKOFF
            if (
                self.cache_path.is_file()
                and attempted is not None
                and datetime.now(UTC) - attempted < interval
            ):
                return
            self._check_scheduled = True

        def run() -> None:
            try:
                self.check()
            finally:
                with self._schedule_guard:
                    self._check_scheduled = False

        threading.Thread(target=run, name="knemora-update-check", daemon=True).start()

    def check(self) -> UpdateSnapshot:
        if not self.checks_enabled:
            return self._neutral("disabled", "Update checks are disabled.")
        requested_at = datetime.now(UTC)
        with self._check_guard:
            concurrent_result = self.cached()
            checked_at = _parse_time(concurrent_result.checked_at)
            if checked_at is not None and checked_at >= requested_at:
                return concurrent_result
            attempted = _now()
            try:
                self._git(
                    "fetch",
                    "--no-tags",
                    "--force",
                    self.official_repository,
                    f"+refs/heads/{UPDATE_CHANNEL}:{UPDATE_REF}",
                    timeout=self.network_timeout,
                )
                snapshot = self._build_snapshot(attempted)
            except (UpdateError, subprocess.TimeoutExpired) as exc:
                prior = self.cached()
                snapshot = replace(
                    prior,
                    state="unavailable",
                    last_attempt_at=attempted,
                    cached=prior.checked_at is not None,
                    installable=False,
                    error=f"Update check unavailable: {exc}",
                )
            self._write_json(self.cache_path, snapshot.to_dict())
            return snapshot

    def create_job(self, target_sha: str) -> dict[str, Any]:
        snapshot = self.cached()
        if not snapshot.installable or snapshot.target is None:
            raise UpdateError(snapshot.blocked_reason or "No installable update is available.")
        if target_sha != snapshot.target.sha:
            raise UpdateError("The confirmed target no longer matches the checked update.")
        self._git("cat-file", "-e", f"{target_sha}^{{commit}}")
        active = self.active_job()
        if active is not None:
            return {**active, "deduplicated": True}
        with self._update_lock():
            active = self.active_job()
            if active is not None:
                return {**active, "deduplicated": True}
            job_id = str(uuid.uuid4())
            job = {
                "id": job_id,
                "status": "queued",
                "stage": "queued",
                "message": "Update queued.",
                "target_sha": target_sha,
                "running_sha": snapshot.running.sha if snapshot.running else None,
                "created_at": _now(),
                "updated_at": _now(),
                "backup": None,
                "previous_checkout": None,
                "error": None,
                "deduplicated": False,
            }
            self._write_job(job)
            return job

    def spawn_job(self, job_id: str) -> None:
        log_path = self.updates_directory / "jobs" / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "KNEMORA_HOME": str(self.paths.data)}
        with log_path.open("ab") as log:
            subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "knemora_bootstrap.update_worker",
                    "--job-id",
                    job_id,
                    "--repository",
                    str(self.paths.repository),
                ],
                cwd=self.paths.data,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    def mark_worker_started(self, job_id: str) -> None:
        job = self.read_job(job_id)
        job["worker_pid"] = os.getpid()
        job["updated_at"] = _now()
        self._write_job(job)

    def read_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateError(f"Update job {job_id!r} does not exist.") from exc
        if not isinstance(value, dict):
            raise UpdateError(f"Update job {job_id!r} is invalid.")
        return value

    def active_job(self) -> dict[str, Any] | None:
        jobs = self.updates_directory / "jobs"
        for path in sorted(jobs.glob("*.json"), reverse=True) if jobs.is_dir() else ():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict) and value.get("status") in {"queued", "running"}:
                worker_pid = value.get("worker_pid")
                if isinstance(worker_pid, int) and not _process_running(worker_pid):
                    value.update(
                        status="failed",
                        stage="interrupted",
                        message="The independent update worker exited before completion.",
                        error="Update interrupted; inspect the journal and recovery guidance.",
                        updated_at=_now(),
                    )
                    self._write_job(cast(dict[str, Any], value))
                    continue
                return cast(dict[str, Any], value)
        return None

    def execute_job(self, job_id: str) -> None:
        job = self.read_job(job_id)
        with self._update_lock():
            try:
                self._execute(job)
            except Exception as exc:
                job = self.read_job(job_id)
                self._recover_pre_activation(job)
                job.update(
                    status="failed",
                    message="Update failed. Review the journal and recovery guidance.",
                    error=str(exc),
                    updated_at=_now(),
                )
                self._write_job(job)
                raise

    def _execute(self, job: dict[str, Any]) -> None:
        from knemora_bootstrap.local_backup import create_backup
        from knemora_bootstrap.platforms import detect_platform
        from knemora_bootstrap.runtime import RuntimeManager

        job_id = str(job["id"])
        target_sha = str(job["target_sha"])
        snapshot = self._build_snapshot(_now(), fetch_complete=True)
        if not snapshot.installable or snapshot.target is None or snapshot.target.sha != target_sha:
            raise UpdateError(
                snapshot.blocked_reason or "The checkout is no longer safe to update."
            )
        repository = self.paths.repository
        backup_destination = read_backup_path(self.paths)
        if backup_destination == repository or backup_destination.is_relative_to(repository):
            raise UpdateError(
                "The configured backup path is inside the active checkout. "
                "Choose an external path with ./knemora config backup-path."
            )
        staging = repository.parent / f".{repository.name}-update-{job_id}"
        previous = repository.parent / f".{repository.name}-previous-{target_sha[:12]}"
        if staging.exists() or previous.exists():
            raise UpdateError("A staging or retained checkout already uses this update identity.")

        self._advance(job, "validating", "Validating the pinned target and local resources.")
        if shutil.disk_usage(repository.parent).free < 512 * 1024 * 1024:
            raise UpdateError("At least 512 MB of free space is required to stage this update.")
        self._advance(job, "staging", "Downloading and preparing the pinned target checkout.")
        self._git_external("clone", "--no-local", "--no-checkout", str(repository), str(staging))
        self._git_in(
            staging,
            "fetch",
            "--no-tags",
            str(repository),
            f"{UPDATE_REF}:{UPDATE_REF}",
            timeout=120,
        )
        self._git_in(staging, "checkout", UPDATE_CHANNEL)
        self._git_in(staging, "merge", "--ff-only", target_sha)
        self._git_in(staging, "remote", "set-url", "origin", self.official_repository)
        source_env = repository / ".env"
        if source_env.is_file():
            shutil.copy2(source_env, staging / ".env")
            (staging / ".env").chmod(0o600)
        self._prepare_staging(staging)

        runtime = RuntimeManager(self.paths, detect_platform())
        was_running = any(item.running for item in runtime.status() if item.name != "database")
        mode = runtime.current_mode()
        job.update(was_running=was_running, mode=mode)
        self._write_job(job)
        self._write_json(
            self.maintenance_path,
            {"job_id": job_id, "target_sha": target_sha, "started_at": _now()},
        )
        self._advance(job, "maintenance", "Maintenance mode enabled; stopping active work.")
        if was_running:
            runtime.stop()

        self._advance(job, "backup", "Creating a validated portable recovery backup.")
        backup = create_backup(
            backup_destination, "full", self._backup_settings(), paths=self.paths
        )
        job["backup"] = str(backup.archive)
        self._write_job(job)

        self._advance(job, "activating", "Activating the prepared checkout.")
        try:
            repository.rename(previous)
            staging.rename(repository)
        except OSError:
            if previous.exists() and not repository.exists():
                previous.rename(repository)
            raise
        job["previous_checkout"] = str(previous)
        self._write_job(job)

        self._advance(job, "migrating", "Running guarded setup and application migrations.")
        selected_model = self._selected_model_id() or "default"
        self._run_launcher(
            repository,
            "--non-interactive",
            "--yes",
            "--no-open",
            "setup",
            "--model",
            selected_model,
        )
        self._advance(job, "restarting", "Restarting Knemora services.")
        start_arguments = ["--non-interactive", "--no-open", "start"]
        if mode == "development":
            start_arguments.append("--with-presets")
        self._run_launcher(repository, *start_arguments)
        self.maintenance_path.unlink(missing_ok=True)
        self._advance(job, "verifying", "Verifying service readiness and activated revision.")
        if not all(
            RuntimeManager.http_ok(url)
            for url in (
                "http://localhost:8080/health",
                "http://localhost:8000/api/v1/health",
                "http://localhost:5173/",
            )
        ):
            raise UpdateError("One or more services failed final readiness verification.")
        active = self._git_in(repository, "rev-parse", "HEAD")
        if active != target_sha:
            raise UpdateError("Activated checkout does not match the confirmed target SHA.")
        self._advance(job, "complete", "Update installed and verified.", status="complete")

    def _recover_pre_activation(self, job: dict[str, Any]) -> None:
        if job.get("previous_checkout") or not self.maintenance_path.is_file():
            return
        self.maintenance_path.unlink(missing_ok=True)
        if not job.get("was_running"):
            return
        try:
            from knemora_bootstrap.platforms import detect_platform
            from knemora_bootstrap.runtime import RuntimeManager

            RuntimeManager(self.paths, detect_platform()).start(
                demo=job.get("mode") == "development",
                open_apps=False,
                demo_database_prepared=job.get("mode") == "development",
            )
        except Exception as recovery_error:
            job["recovery_error"] = str(recovery_error)

    def _build_snapshot(self, attempted: str, *, fetch_complete: bool = False) -> UpdateSnapshot:
        del fetch_complete
        head = self._git("rev-parse", "HEAD")
        running_sha = os.environ.get("KNEMORA_RUNNING_COMMIT", "").strip() or head
        self._git("cat-file", "-e", f"{running_sha}^{{commit}}")
        target_sha = self._git("rev-parse", UPDATE_REF)
        branch_value = self._git("symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
        branch = branch_value or None
        dirty = bool(self._git("status", "--porcelain=v1", "--untracked-files=all"))
        left, right = self._git(
            "rev-list", "--left-right", "--count", f"{running_sha}...{target_sha}"
        ).split()
        ahead, behind = int(left), int(right)
        relation = (
            "up_to_date"
            if ahead == behind == 0
            else "behind"
            if ahead == 0
            else "ahead"
            if behind == 0
            else "diverged"
        )
        blocked: str | None = None
        state: UpdateState
        supported = self.system == "Darwin" and self.machine == "arm64"
        if branch is None:
            state, blocked = "blocked", "Detached HEAD installations are check-only."
        elif branch == "develop":
            state, blocked = (
                "development",
                "Development checkouts are never switched to the stable master channel.",
            )
        elif branch != UPDATE_CHANNEL:
            state, blocked = (
                "blocked",
                f"Custom branch {branch!r} is check-only; use a clean managed master checkout.",
            )
        elif dirty:
            state, blocked = "blocked", "The checkout has local edits or untracked files."
        elif head != running_sha:
            state, blocked = (
                "blocked",
                "The checkout changed after the running application started; "
                "restart before updating.",
            )
        elif not supported:
            state, blocked = (
                "blocked",
                "Managed updates currently support macOS Apple Silicon only.",
            )
        elif relation == "ahead":
            state, blocked = "blocked", "Local commits are ahead of official master."
        elif relation == "diverged":
            state, blocked = "blocked", "The checkout has diverged from official master."
        elif relation == "behind":
            state = "update_available"
        else:
            state = "up_to_date"
        changed_paths = self._changed_paths(running_sha, target_sha)
        changes, truncated = self._changes(running_sha, target_sha)
        dependency_changes = tuple(
            path
            for path in changed_paths
            if path.endswith(("uv.lock", "pyproject.toml", "package-lock.json", "package.json"))
            or path == "infrastructure/runtime-manifest.json"
        )[:MAX_CHANGE_ITEMS]
        migration_changes = tuple(
            path for path in changed_paths if path.startswith("apps/api/migrations/versions/")
        )[:MAX_CHANGE_ITEMS]
        checked = _now()
        return UpdateSnapshot(
            state=state,
            channel=UPDATE_CHANNEL,
            checked_at=checked,
            last_attempt_at=attempted,
            cached=False,
            running=self._revision(running_sha),
            target=self._revision(target_sha),
            branch=branch,
            relation=relation,
            dirty=dirty,
            installable=state == "update_available",
            blocked_reason=blocked,
            error=None,
            changes=changes,
            changes_truncated=truncated,
            dependency_changes=dependency_changes,
            migration_changes=migration_changes,
            restart_required=relation == "behind",
            privacy_notice=self.privacy_notice,
        )

    def _revision(self, sha: str) -> Revision:
        source = self._git("show", f"{sha}:apps/api/app/product.py", allow_failure=True)
        match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
        tags = self._git("tag", "--points-at", sha, allow_failure=True).splitlines()
        tag = next((item for item in tags if item.startswith("v")), tags[0] if tags else None)
        return Revision(
            sha=sha,
            short_sha=sha[:12],
            app_version=match.group(1) if match else None,
            tag=tag,
        )

    def _changes(self, installed: str, target: str) -> tuple[tuple[ChangeItem, ...], bool]:
        if installed == target:
            return (), False
        raw = self._git(
            "log",
            f"--max-count={MAX_CHANGE_ITEMS + 1}",
            "--format=%H%x1f%s%x1f%b%x1e",
            f"{installed}..{target}",
            allow_failure=True,
        )
        records = [record for record in raw.split("\x1e") if record.strip()]
        result: list[ChangeItem] = []
        for record in records[:MAX_CHANGE_ITEMS]:
            parts = record.strip().split("\x1f", 2)
            if len(parts) < 2:
                continue
            sha, subject = parts[:2]
            body = parts[2] if len(parts) == 3 else ""
            pr_match = re.match(r"Merge pull request #(\d+)", subject) or re.search(
                r"\(#(\d+)\)$", subject
            )
            pr_number = int(pr_match.group(1)) if pr_match else None
            title = next((line.strip() for line in body.splitlines() if line.strip()), None)
            if pr_number and title is None:
                title = re.sub(r"\s*\(#\d+\)$", "", subject).strip()
            result.append(
                ChangeItem(
                    sha=sha,
                    short_sha=sha[:12],
                    subject=subject,
                    url=f"{OFFICIAL_REPOSITORY_WEB}/commit/{sha}",
                    pull_request_number=pr_number,
                    pull_request_title=title if pr_number else None,
                    pull_request_url=(
                        f"{OFFICIAL_REPOSITORY_WEB}/pull/{pr_number}" if pr_number else None
                    ),
                )
            )
        return tuple(result), len(records) > MAX_CHANGE_ITEMS

    def _changed_paths(self, installed: str, target: str) -> tuple[str, ...]:
        if installed == target:
            return ()
        output = self._git("diff", "--name-only", installed, target, allow_failure=True)
        return tuple(line for line in output.splitlines() if line)

    def _prepare_staging(self, staging: Path) -> None:
        env = runtime_environment(AppPaths(repository=staging, data=self.paths.data))
        uv = os.environ.get("KNEMORA_MANAGED_UV")
        if not uv:
            candidates = sorted((self.paths.bin / "uv").glob("**/uv"))
            uv = str(candidates[-1]) if candidates else None
        if uv and Path(uv).is_file():
            manifest = json.loads(
                (staging / "infrastructure/runtime-manifest.json").read_text(encoding="utf-8")
            )
            env.update(
                UV_CACHE_DIR=str(self.paths.cache / "uv"),
                UV_PYTHON_INSTALL_DIR=str(self.paths.python),
                UV_MANAGED_PYTHON="1",
            )
            self._run(
                [
                    uv,
                    "sync",
                    "--frozen",
                    "--dev",
                    "--python",
                    str(manifest["python"]["version"]),
                    "--managed-python",
                ],
                cwd=staging / "apps/api",
                env=env,
                timeout=600,
            )
        else:
            raise UpdateError("The managed uv executable is unavailable; run ./knemora setup.")
        self._run(["npm", "ci"], cwd=staging / "apps/web", env=env, timeout=600)
        self._run(["npm", "run", "build"], cwd=staging / "apps/web", env=env, timeout=600)

    def _backup_settings(self) -> Any:
        from app.config import Settings

        environment = runtime_environment(self.paths)
        return Settings(
            _env_file=None,
            database_url=environment["KNEMORA_DATABASE_URL"],
            source_store_path=environment["KNEMORA_SOURCE_STORE_PATH"],
            knowledge_path=environment["KNEMORA_KNOWLEDGE_PATH"],
        )

    def _selected_model_id(self) -> str | None:
        try:
            value = json.loads((self.paths.config / "model.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        model_id = value.get("model_id") if isinstance(value, dict) else None
        return model_id if isinstance(model_id, str) else None

    def _run_launcher(self, repository: Path, *arguments: str) -> None:
        self._run(
            [str(repository / "knemora"), *arguments],
            cwd=repository,
            env={**os.environ, "KNEMORA_HOME": str(self.paths.data)},
            timeout=1_200,
        )

    def _advance(
        self,
        job: dict[str, Any],
        stage: str,
        message: str,
        *,
        status: str = "running",
    ) -> None:
        job.update(status=status, stage=stage, message=message, updated_at=_now())
        self._write_job(job)

    def _neutral(self, state: UpdateState, detail: str) -> UpdateSnapshot:
        now = _now()
        return UpdateSnapshot(
            state=state,
            channel=UPDATE_CHANNEL,
            checked_at=None,
            last_attempt_at=now,
            cached=False,
            running=None,
            target=None,
            branch=None,
            relation="unknown",
            dirty=False,
            installable=False,
            blocked_reason=detail,
            error=None,
            changes=(),
            changes_truncated=False,
            dependency_changes=(),
            migration_changes=(),
            restart_required=False,
            privacy_notice=self.privacy_notice,
        )

    def _job_path(self, job_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(job_id))
        except ValueError as exc:
            raise UpdateError("Invalid update job ID.") from exc
        return self.updates_directory / "jobs" / f"{normalized}.json"

    def _write_job(self, job: dict[str, Any]) -> None:
        self._write_json(self._job_path(str(job["id"])), job)

    @contextmanager
    def _update_lock(self) -> Iterator[None]:
        self.updates_directory.mkdir(parents=True, exist_ok=True)
        lock = self.updates_directory / "update.lock"
        with lock.open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UpdateError("Another CLI or API update is already running.") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _git(self, *arguments: str, timeout: int = 15, allow_failure: bool = False) -> str:
        return self._git_in(
            self.paths.repository,
            *arguments,
            timeout=timeout,
            allow_failure=allow_failure,
        )

    def _git_in(
        self,
        repository: Path,
        *arguments: str,
        timeout: int = 15,
        allow_failure: bool = False,
    ) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode and not allow_failure:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise UpdateError(f"git {' '.join(arguments)} failed: {detail}")
        return result.stdout.strip() if result.returncode == 0 else ""

    def _git_external(self, *arguments: str) -> None:
        self._run(["git", *arguments], cwd=self.paths.repository.parent, timeout=120)

    @staticmethod
    def _run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int,
    ) -> None:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise UpdateError(f"{Path(command[0]).name} failed: {detail}")

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def wait_for_job(service: UpdateService, job_id: str) -> dict[str, Any]:
    """Wait for a CLI-started worker while showing durable stage changes."""

    previous_stage: str | None = None
    while True:
        job = service.read_job(job_id)
        stage = str(job.get("stage"))
        if stage != previous_stage:
            print(f"{stage}: {job.get('message', '')}")
            previous_stage = stage
        if job.get("status") in {"complete", "failed"}:
            return job
        time.sleep(0.5)


__all__ = [
    "OFFICIAL_REPOSITORY",
    "UPDATE_CHANNEL",
    "UpdateError",
    "UpdateService",
    "UpdateSnapshot",
    "wait_for_job",
]
