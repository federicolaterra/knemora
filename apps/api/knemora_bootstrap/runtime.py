"""Lifecycle and health management for local Knemora services."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from knemora_bootstrap.configuration import (
    AppPaths,
    confirm_model_selection,
    resolve_context_preference,
    rollback_model_selection,
    runtime_environment,
    write_model_selection,
)
from knemora_bootstrap.model_context import (
    ModelContextError,
    describe_context_admission,
    plan_context,
)
from knemora_bootstrap.models import ModelRegistry, enrich_model_from_local_gguf
from knemora_bootstrap.native_runtime import NativeRuntimeError, NativeRuntimeManager
from knemora_bootstrap.platforms import PlatformAdapter


class RuntimeFailure(RuntimeError):
    """A managed service failed to start or pass its health check."""


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    running: bool
    detail: str


class RuntimeManager:
    def __init__(self, paths: AppPaths, platform: PlatformAdapter) -> None:
        self.paths = paths
        self.platform = platform
        self._native_runtime: NativeRuntimeManager | None = None

    @property
    def native_runtime(self) -> NativeRuntimeManager:
        if self._native_runtime is None:
            self._native_runtime = NativeRuntimeManager(self.paths)
        return self._native_runtime

    def start(
        self,
        *,
        demo: bool = False,
        open_apps: bool = True,
        demo_database_prepared: bool = False,
    ) -> None:
        requested_mode = "development" if demo else "normal"
        try:
            selection_payload = json.loads(
                (self.paths.config / "model.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeFailure(f"Model selection is missing or invalid: {exc}.") from exc
        profile_changed = self.current_mode() != requested_mode
        selection_changed = isinstance(selection_payload.get("previous_selection"), dict)
        if (profile_changed or selection_changed) and any(
            status.running for status in self.status() if status.name != "database"
        ):
            print(f"Switching to {requested_mode} mode.")
            self.stop()
        try:
            selected_model = ModelRegistry(self.paths.model_registry).get(
                str(selection_payload["model_id"])
            )
            selected_model = enrich_model_from_local_gguf(selected_model, self.paths.models)
            selected_model_path = Path(str(selection_payload["path"]))
            preference = resolve_context_preference(self.paths, selected_model)
            startup_plan = plan_context(
                selected_model,
                self.platform.hardware(),
                configured_context_tokens=preference.tokens,
                source=preference.source,
                explicit=preference.explicit,
            )
        except (OSError, ValueError, KeyError, TypeError, ModelContextError, RuntimeError) as exc:
            rolled_back = rollback_model_selection(self.paths)
            suffix = " The prior model selection was restored." if rolled_back else ""
            detail = str(exc).rstrip(".")
            raise RuntimeFailure(f"Model startup preflight failed: {detail}.{suffix}") from exc
        print(f"Starting {selected_model.display_name}. {describe_context_admission(startup_plan)}")
        try:
            write_model_selection(
                self.paths,
                selected_model,
                selected_model_path,
                plan=startup_plan,
            )
        except OSError as exc:
            rolled_back = rollback_model_selection(self.paths)
            suffix = " The prior model selection was restored." if rolled_back else ""
            detail = str(exc).rstrip(".")
            raise RuntimeFailure(
                f"Could not record the startup context plan: {detail}.{suffix}"
            ) from exc
        env = runtime_environment(self.paths, demo=demo)
        try:
            selection = self.native_runtime.resolve_llama()
        except NativeRuntimeError as exc:
            rolled_back = rollback_model_selection(self.paths)
            suffix = " The prior model selection was restored." if rolled_back else ""
            raise RuntimeFailure(str(exc) + suffix) from exc
        env["LLAMA_SERVER_BIN"] = str(selection.executable)
        if demo and not demo_database_prepared:
            self.prepare_demo_database()
        script = self.paths.repository / "infrastructure" / "scripts" / "start-local-release.sh"
        result = subprocess.run([str(script)], cwd=self.paths.repository, env=env, check=False)
        if result.returncode:
            self._cleanup_failed_start(env)
            rolled_back = rollback_model_selection(self.paths)
            suffix = " The prior model selection was restored." if rolled_back else ""
            raise RuntimeFailure("A local service failed to launch. Run ./knemora logs." + suffix)
        failures = self.wait_until_ready()
        failures.extend(
            f"managed {status.name} process exited after launch; another process may own its port"
            for status in self.status()
            if status.name != "database" and not status.running
        )
        if not self._api_mode_matches(demo=demo):
            failures.append(
                "FastAPI is healthy in the wrong mode; stop existing Knemora services and retry"
            )
        if failures:
            self._cleanup_failed_start(env)
            rolled_back = rollback_model_selection(self.paths)
            suffix = " The prior model selection was restored." if rolled_back else ""
            raise RuntimeFailure("; ".join(failures) + suffix)
        confirm_model_selection(self.paths)
        self._write_mode(requested_mode)
        if open_apps:
            self.open_apps(demo=demo)

    def open_apps(self, *, demo: bool) -> None:
        del demo
        self.platform.open_url("http://localhost:5173")

    def stop(self) -> None:
        env = runtime_environment(self.paths, demo=self.current_mode() == "development")
        script = self.paths.repository / "infrastructure" / "scripts" / "stop-local-release.sh"
        subprocess.run([str(script)], cwd=self.paths.repository, env=env, check=True)
        running = [
            status.name for status in self.status() if status.name != "database" and status.running
        ]
        endpoints = {
            "llama.cpp": "http://localhost:8080/health",
            "FastAPI": "http://localhost:8000/api/v1/health",
            "Vue": "http://localhost:5173/",
        }
        running.extend(name for name, url in endpoints.items() if self.http_ok(url))
        if running:
            raise RuntimeFailure(
                "Stop did not shut down every Knemora service: " + ", ".join(sorted(set(running)))
            )

    def _cleanup_failed_start(self, env: dict[str, str]) -> None:
        """Best-effort cleanup for processes launched by the failed attempt."""

        script = self.paths.repository / "infrastructure" / "scripts" / "stop-local-release.sh"
        subprocess.run([str(script)], cwd=self.paths.repository, env=env, check=False)

    def prepare_demo_database(self) -> None:
        """Create and migrate the isolated demo database before preset seeding."""

        env = runtime_environment(self.paths, demo=True)
        self.paths.demo_database.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(self.paths.repository / "apps/api/.venv/bin/alembic"), "upgrade", "head"],
            cwd=self.paths.repository / "apps/api",
            env=env,
            check=True,
        )

    def delete_demo_database(self) -> None:
        """Drop only the isolated Development preset database."""

        self.paths.demo_database.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            self.paths.demo_database.with_name(self.paths.demo_database.name + suffix).unlink(
                missing_ok=True
            )

    def restart(self, *, open_apps: bool = True) -> None:
        demo = self.current_mode() == "development"
        self.stop()
        self.start(
            demo=demo,
            open_apps=open_apps,
        )

    def status(self) -> tuple[ServiceStatus, ...]:
        statuses: list[ServiceStatus] = []
        for name in ("llm", "api", "web"):
            path = self.paths.runtime / f"{name}.pid"
            pid = self._read_pid(path)
            running = pid is not None and self._pid_running(pid)
            statuses.append(
                ServiceStatus(name, running, f"pid {pid}" if running else "not running")
            )
        environment = runtime_environment(self.paths, demo=self.current_mode() == "development")
        database_url = environment.get("KNEMORA_DATABASE_URL", "")
        prefix = next(
            (
                value
                for value in ("sqlite+pysqlite:///", "sqlite:///")
                if database_url.startswith(value)
            ),
            None,
        )
        database_path = (
            Path(unquote(database_url.removeprefix(prefix))).expanduser()
            if prefix is not None
            else None
        )
        db_running = False
        detail = str(database_path or "configured external database")
        if database_path is not None and database_path.is_file():
            try:
                with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=2) as db:
                    db_running = db.execute("PRAGMA quick_check").fetchone() == ("ok",)
                detail = (
                    f"ready at {database_path}" if db_running else f"invalid at {database_path}"
                )
            except sqlite3.Error as exc:
                detail = f"unavailable at {database_path}: {exc}"
        statuses.insert(0, ServiceStatus("database", db_running, detail))
        return tuple(statuses)

    def wait_until_ready(self, timeout_seconds: int = 180) -> list[str]:
        checks = {
            "llama.cpp": "http://localhost:8080/health",
            "FastAPI": "http://localhost:8000/api/v1/health",
            "Vue": "http://localhost:5173/",
        }
        deadline = time.monotonic() + timeout_seconds
        pending = dict(checks)
        while pending and time.monotonic() < deadline:
            for name, url in tuple(pending.items()):
                if self.http_ok(url):
                    pending.pop(name)
            if pending:
                time.sleep(1)
        return [f"{name} did not become healthy at {url}" for name, url in pending.items()]

    def show_logs(self, *, lines: int = 80, follow: bool = False) -> int:
        files = [self.paths.logs / f"{name}.log" for name in ("llm", "api", "web")]
        existing = [path for path in files if path.is_file()]
        if not existing:
            print(f"No Knemora logs exist under {self.paths.logs}.")
            return 1
        command = ["tail", f"-{max(1, lines)}"]
        if follow:
            command.append("-f")
        command.extend(str(path) for path in existing)
        return subprocess.run(command, check=False).returncode

    def current_mode(self) -> str:
        try:
            mode = json.loads((self.paths.runtime / "mode.json").read_text())["mode"]
        except (OSError, ValueError, KeyError):
            return "normal"
        return mode if isinstance(mode, str) else "normal"

    def _write_mode(self, mode: str) -> None:
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        (self.paths.runtime / "mode.json").write_text(
            json.dumps({"mode": mode}, sort_keys=True) + "\n"
        )

    @staticmethod
    def _api_mode_matches(*, demo: bool) -> bool:
        try:
            with urllib.request.urlopen(  # noqa: S310
                "http://localhost:8000/api/v1/system", timeout=2
            ) as response:
                payload = json.load(response)
        except (OSError, ValueError, TypeError):
            return False
        metadata = payload.get("demo") if isinstance(payload, dict) else None
        return isinstance(metadata, dict) and metadata.get("active") is demo

    @staticmethod
    def http_ok(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                return 200 <= int(response.status) < 300
        except (urllib.error.URLError, TimeoutError):
            return False

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            value = int(path.read_text().strip())
        except (OSError, ValueError):
            return None
        return value if value > 1 else None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True
