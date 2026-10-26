from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tomllib
import urllib.error
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.home import HomeCompatibilityService
from app.knowledge.store import WikiStore
from knemora_bootstrap.adk_web import (
    ADK_WEB_PORTS,
    _check_agent_import,
    _check_model_server,
    _select_port,
    launch_adk_web,
)
from knemora_bootstrap.cli import (
    SetupManager,
    StartupProgress,
    _delete_presets,
    _parser,
    _preset_files_available,
    _run_setup_command,
    _virtual_environment_was_relocated,
    main,
)
from knemora_bootstrap.configuration import AppPaths, ensure_repository_env, runtime_environment
from knemora_bootstrap.development_preset import (
    EXPECTED_FACTS,
    build_catalog,
    manifest,
    render_source,
)
from knemora_bootstrap.models import DEFAULT_MODEL_ID, ModelManager, ModelSpec, get_model
from knemora_bootstrap.platforms import MacOSAdapter
from knemora_bootstrap.runtime import RuntimeFailure, RuntimeManager, ServiceStatus
from knemora_bootstrap.seed import seed_sync
from knemora_bootstrap.uninstall import (
    UninstallFailure,
    build_uninstall_plan,
    confirm_uninstall,
    execute_uninstall,
    uninstall,
)


def test_alembic_is_a_locked_runtime_dependency() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    project = tomllib.loads((api_directory / "pyproject.toml").read_text(encoding="utf-8"))
    lock = (api_directory / "uv.lock").read_text(encoding="utf-8")

    assert any(
        dependency.startswith("alembic") for dependency in project["project"]["dependencies"]
    )
    assert 'name = "alembic"' in lock
    assert '{ name = "alembic", specifier = ">=1.15,<2.0" }' in lock


def test_macos_dependency_setup_does_not_invoke_homebrew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(shutil, "which", lambda _: None)

    def record_install(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        subprocess,
        "run",
        record_install,
    )

    MacOSAdapter().prepare_dependencies()

    assert calls == []


def test_runtime_opens_only_the_native_web_interface(tmp_path: Path) -> None:
    class BrowserOnlyPlatform:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def open_url(self, url: str) -> None:
            self.urls.append(url)

    platform = BrowserOnlyPlatform()
    runtime = RuntimeManager(
        AppPaths(repository=tmp_path / "repository", data=tmp_path / "data"),
        platform,  # type: ignore[arg-type]
    )

    runtime.open_apps(demo=True)

    assert platform.urls == ["http://localhost:5173"]


def test_relocated_virtual_environment_is_rebuilt_before_locked_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "current-repository"
    api_directory = repository / "apps" / "api"
    web_directory = repository / "apps" / "web"
    scripts = api_directory / ".venv" / "bin"
    scripts.mkdir(parents=True)
    web_directory.mkdir(parents=True)
    (scripts / "alembic").write_text(
        "#!/old/repository/apps/api/.venv/bin/python\n", encoding="utf-8"
    )
    (scripts / "python").write_text("managed\n", encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    def fake_run(
        command: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool
    ) -> subprocess.CompletedProcess[str]:
        del env
        assert check is True
        calls.append((command, cwd))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    manager = SetupManager(
        AppPaths(repository=repository, data=tmp_path / "data"),
        platform=object(),  # type: ignore[arg-type]
    )

    assert _virtual_environment_was_relocated(api_directory)
    manager._prepare_application()

    assert calls == [
        ([str(scripts / "alembic"), "--version"], api_directory),
        (["npm", "ci"], web_directory),
    ]


def test_setup_command_error_names_step_command_and_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(
        command: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(RuntimeError) as raised:
        _run_setup_command(
            ["uv", "run", "--frozen", "alembic", "upgrade", "head"],
            cwd=tmp_path,
            step="Database migration",
        )

    message = str(raised.value)
    assert "Database migration failed with exit status 7" in message
    assert "uv run --frozen alembic upgrade head" in message
    assert f"Working directory: {tmp_path}" in message


def test_runtime_rejects_health_from_an_unmanaged_api_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    script = repository / "infrastructure" / "scripts" / "start-local-release.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    paths = AppPaths(repository=repository, data=tmp_path / "data")
    paths.config.mkdir(parents=True)
    (paths.config / "model.json").write_text(
        json.dumps(
            {
                "model_id": DEFAULT_MODEL_ID,
                "path": str(tmp_path / "qwen.gguf"),
                "quantization": "Q3_K_M",
                "context_tokens": 8192,
                "context_source": "test",
            }
        ),
        encoding="utf-8",
    )

    class TestPlatform:
        @staticmethod
        def hardware() -> object:
            return type(
                "Hardware",
                (),
                {
                    "memory_gb": 16.0,
                    "unified_memory_gb": 16.0,
                    "available_memory_gb": 16.0,
                },
            )()

        @staticmethod
        def open_url(_url: str) -> None:
            return None

    runtime = RuntimeManager(paths, TestPlatform())  # type: ignore[arg-type]
    statuses = (
        ServiceStatus("database", True, "healthy"),
        ServiceStatus("llm", True, "pid 10"),
        ServiceStatus("api", False, "not running"),
        ServiceStatus("web", True, "pid 12"),
    )

    class FakeNativeRuntime:
        @staticmethod
        def resolve_llama() -> object:
            return type("Selection", (), {"executable": tmp_path / "llama-server"})()

    runtime._native_runtime = FakeNativeRuntime()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "wait_until_ready", lambda: [])
    monkeypatch.setattr(runtime, "status", lambda: statuses)
    monkeypatch.setattr(runtime, "_api_mode_matches", lambda *, demo: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    with pytest.raises(RuntimeFailure, match="managed api process exited after launch"):
        runtime.start(demo=False, open_apps=False)


def test_runtime_verifies_the_api_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response(io.StringIO):
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

    monkeypatch.setattr(
        "knemora_bootstrap.runtime.urllib.request.urlopen",
        lambda *args, **kwargs: Response('{"demo":{"active":true}}'),
    )

    assert RuntimeManager._api_mode_matches(demo=True)
    assert not RuntimeManager._api_mode_matches(demo=False)


def test_runtime_restart_reuses_mode_and_rereads_environment_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(repository=tmp_path / "repository", data=tmp_path / "data")
    HomeCompatibilityService(paths.data).ensure_current()
    runtime = RuntimeManager(paths, MacOSAdapter())
    runtime._write_mode("development")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(runtime, "stop", lambda: calls.append(("stop", None)))

    def start(**kwargs: object) -> None:
        calls.append(("start", kwargs))

    monkeypatch.setattr(runtime, "start", start)

    runtime.restart(open_apps=False)

    assert calls == [
        ("stop", None),
        (
            "start",
            {"demo": True, "open_apps": False},
        ),
    ]


def test_start_script_tracks_direct_service_processes() -> None:
    script = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "scripts"
        / "start-local-release.sh"
    ).read_text(encoding="utf-8")

    assert "nohup make api-start" not in script
    assert "exec .venv/bin/uvicorn" in script
    assert "exec node_modules/.bin/vite preview" in script
    assert "--strictPort" in script

    stop_script = (
        Path(__file__).resolve().parents[3] / "infrastructure" / "scripts" / "stop-local-release.sh"
    ).read_text(encoding="utf-8")
    assert "for service in web api llm" in stop_script
    assert "kill -KILL" in stop_script
    assert "docker" not in script
    assert "docker" not in stop_script


def test_delete_presets_command_is_explicit_and_preserves_model_and_normal_data(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "data")
    paths.initialize()
    (paths.demo / "manifest.json").write_text("{}\n", encoding="utf-8")
    (paths.models / "model.gguf").write_bytes(b"model")
    (paths.wiki / "real-user.md").write_text("real\n", encoding="utf-8")

    class FakeRuntime:
        deleted = False

        @staticmethod
        def current_mode() -> str:
            return "normal"

        @staticmethod
        def status() -> tuple[ServiceStatus, ...]:
            return ()

        @staticmethod
        def stop() -> None:
            raise AssertionError("Normal mode must not be stopped when deleting presets.")

        def delete_demo_database(self) -> None:
            self.deleted = True

    runtime = FakeRuntime()
    _delete_presets(paths, runtime)  # type: ignore[arg-type]

    assert runtime.deleted
    assert not paths.demo.exists()
    assert (paths.models / "model.gguf").read_bytes() == b"model"
    assert (paths.wiki / "real-user.md").read_text(encoding="utf-8") == "real\n"
    canonical = _parser().parse_args(["--yes", "delete", "--presets"])
    alias = _parser().parse_args(["--yes", "delete-presets"])
    assert canonical.command == "delete"
    assert canonical.presets is True
    assert alias.command == "delete-presets"
    assert alias.presets is True
    assert alias.deprecated_replacement == "delete --presets"


def test_delete_requires_an_explicit_supported_target() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["delete"])


def test_deprecated_delete_alias_routes_to_canonical_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = AppPaths(repository=tmp_path / "repository", data=tmp_path / "data")
    HomeCompatibilityService(paths.data).ensure_current()
    observed: list[tuple[AppPaths, RuntimeManager]] = []
    monkeypatch.setattr("knemora_bootstrap.cli.AppPaths.discover", lambda: paths)
    monkeypatch.setattr(
        "knemora_bootstrap.cli._delete_presets",
        lambda actual_paths, runtime: observed.append((actual_paths, runtime)),
    )

    assert main(["--yes", "delete-presets"]) == 0

    assert observed and observed[0][0] == paths
    error = capsys.readouterr().err
    assert "deprecated" in error
    assert "./knemora delete --presets" in error


def test_web_search_flag_is_rejected_everywhere(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root_defaults = _parser().parse_args([])
    standard_start = _parser().parse_args(["start"])
    playground = _parser().parse_args(["--dev", "adk-web"])

    assert root_defaults.command is None
    assert standard_start.command == "start"
    assert playground.command == "adk-web"
    assert playground.dev is True
    assert Settings(_env_file=None).web_search_enabled is False
    for arguments in (
        ["start", "--yes-web-search"],
        ["start", "--with-presets", "--yes-web-search"],
        ["start-with-presets", "--yes-web-search"],
        ["--dev", "adk-web", "--yes-web-search"],
    ):
        with pytest.raises(SystemExit) as error:
            _parser().parse_args(arguments)
        assert error.value.code == 2
        assert "unrecognized arguments: --yes-web-search" in capsys.readouterr().err

    migration = _parser().parse_args(
        ["migrate-postgresql", "--source-url", "postgresql+psycopg://example/db"]
    )
    assert migration.source_url == "postgresql+psycopg://example/db"


def test_start_help_hides_the_deprecated_web_search_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["start", "--help"])

    assert "--yes-web-search" not in capsys.readouterr().out


def test_root_help_hides_deprecated_preset_aliases() -> None:
    help_text = _parser().format_help()

    assert "start-with-presets" not in help_text
    assert "delete-presets" not in help_text
    assert "start               start the normal local environment" in help_text
    assert "delete              delete an explicitly selected Knemora target" in help_text


def _uninstall_repository(path: Path) -> None:
    (path / "apps" / "api" / "knemora_bootstrap").mkdir(parents=True)
    (path / "docs").mkdir()
    (path / "knemora").write_text("#!/bin/sh\n", encoding="utf-8")
    (path / "README.md").write_text("Knemora\n", encoding="utf-8")
    (path / "apps" / "api" / "knemora_bootstrap" / "__init__.py").write_text("", encoding="utf-8")


class _UninstallRuntime:
    def __init__(self, *, running: bool = False, stop_failure: bool = False) -> None:
        self.running = running
        self.stop_failure = stop_failure
        self.stopped = False

    def status(self) -> tuple[ServiceStatus, ...]:
        return (ServiceStatus("api", self.running, "test"),)

    def stop(self) -> None:
        self.stopped = True
        if self.stop_failure:
            raise RuntimeFailure("stubbed shutdown failure")
        self.running = False


def test_uninstall_confirmation_reprompts_and_is_default_negative(
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(["maybe", "YES"])
    assert confirm_uninstall(read=lambda _prompt: next(answers))
    assert "Please answer y or n." in capsys.readouterr().out

    assert not confirm_uninstall(read=lambda _prompt: "")
    assert "no services were stopped" in capsys.readouterr().out

    for exception in (EOFError(), KeyboardInterrupt()):

        def interrupt(_prompt: str, *, error: BaseException = exception) -> str:
            raise error

        assert not confirm_uninstall(read=interrupt)
        assert "no services were stopped" in capsys.readouterr().out


def test_uninstall_cancellation_and_noninteractive_refusal_change_nothing(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "Knemora checkout"
    data = tmp_path / "Knemora data"
    _uninstall_repository(repository)
    data.mkdir()
    runtime = _UninstallRuntime(running=True)
    paths = AppPaths(repository=repository, data=data)

    assert not uninstall(
        paths,
        runtime,
        preserve_data=False,
        interactive=True,
        approved_by_global_flag=False,
        read=lambda _prompt: "no",
        data_entry=data,
    )
    assert repository.exists()
    assert data.exists()
    assert not runtime.stopped

    with pytest.raises(UninstallFailure, match="interactive terminal"):
        uninstall(
            paths,
            runtime,
            preserve_data=False,
            interactive=False,
            approved_by_global_flag=False,
            data_entry=data,
        )
    with pytest.raises(UninstallFailure, match="--yes cannot confirm"):
        uninstall(
            paths,
            runtime,
            preserve_data=False,
            interactive=True,
            approved_by_global_flag=True,
            data_entry=data,
        )


def test_uninstall_removes_spaced_repository_and_data_but_keeps_external_backup(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "Knemora checkout with spaces"
    data = tmp_path / "Knemora application data"
    backup = tmp_path / "independent backups" / "backup.zip"
    _uninstall_repository(repository)
    data.mkdir()
    (data / "knemora.db").write_bytes(b"database")
    backup.parent.mkdir()
    backup.write_bytes(b"backup")
    runtime = _UninstallRuntime(running=True)
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=data),
        preserve_data=False,
        data_entry=data,
    )

    execute_uninstall(plan, runtime)

    assert runtime.stopped
    assert not repository.exists()
    assert not data.exists()
    assert backup.read_bytes() == b"backup"


def test_uninstall_can_remove_repository_while_invoked_from_inside_it(tmp_path: Path) -> None:
    repository = tmp_path / "checkout with spaces"
    data = tmp_path / "data with spaces"
    _uninstall_repository(repository)
    data.mkdir()
    source_root = Path(__file__).resolve().parents[1]
    program = """
import sys
from pathlib import Path
from knemora_bootstrap.configuration import AppPaths
from knemora_bootstrap.uninstall import build_uninstall_plan, execute_uninstall

class Runtime:
    def status(self):
        return ()

repository = Path(sys.argv[1])
data = Path(sys.argv[2])
plan = build_uninstall_plan(
    AppPaths(repository=repository, data=data),
    preserve_data=False,
    data_entry=data,
)
execute_uninstall(plan, Runtime())
"""
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    result = subprocess.run(
        [sys.executable, "-c", program, str(repository), str(data)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Knemora uninstall completed." in result.stdout
    assert not repository.exists()
    assert not data.exists()


def test_uninstall_preserve_data_removes_only_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    data = tmp_path / "data"
    _uninstall_repository(repository)
    data.mkdir()
    (data / "wiki.md").write_text("user data\n", encoding="utf-8")
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=data),
        preserve_data=True,
        data_entry=data,
    )

    execute_uninstall(plan, _UninstallRuntime())

    assert not repository.exists()
    assert (data / "wiki.md").read_text(encoding="utf-8") == "user data\n"


def test_uninstall_refuses_unsafe_or_unpreservable_paths(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _uninstall_repository(repository)
    nested_data = repository / "data"
    nested_data.mkdir()

    with pytest.raises(UninstallFailure, match="Cannot preserve"):
        build_uninstall_plan(
            AppPaths(repository=repository, data=nested_data),
            preserve_data=True,
            data_entry=nested_data,
        )
    with pytest.raises(UninstallFailure, match="unsafe application data"):
        build_uninstall_plan(
            AppPaths(repository=repository, data=tmp_path),
            preserve_data=False,
            data_entry=tmp_path,
            home=tmp_path,
        )
    with pytest.raises(UninstallFailure, match="unsafe application data"):
        build_uninstall_plan(
            AppPaths(repository=repository, data=Path("/")),
            preserve_data=False,
            data_entry=Path("/"),
        )
    parent_data = tmp_path / "parent"
    nested_repository = parent_data / "repository"
    _uninstall_repository(nested_repository)
    with pytest.raises(UninstallFailure, match="parent of the repository"):
        build_uninstall_plan(
            AppPaths(repository=nested_repository, data=parent_data),
            preserve_data=False,
            data_entry=parent_data,
        )


def test_uninstall_does_not_follow_application_data_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    external = tmp_path / "external user files"
    data_link = tmp_path / "knemora-data-link"
    _uninstall_repository(repository)
    external.mkdir()
    (external / "keep.txt").write_text("keep\n", encoding="utf-8")
    data_link.symlink_to(external, target_is_directory=True)
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=external),
        preserve_data=False,
        data_entry=data_link,
    )

    execute_uninstall(plan, _UninstallRuntime())

    assert not repository.exists()
    assert not data_link.exists()
    assert (external / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_uninstall_removes_data_symlink_pointing_inside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    nested_data = repository / "runtime-data"
    data_link = tmp_path / "knemora-data-link"
    _uninstall_repository(repository)
    nested_data.mkdir()
    data_link.symlink_to(nested_data, target_is_directory=True)
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=nested_data),
        preserve_data=False,
        data_entry=data_link,
    )

    execute_uninstall(plan, _UninstallRuntime())

    assert not repository.exists()
    assert not data_link.is_symlink()


def test_uninstall_aborts_before_deletion_when_shutdown_fails(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    data = tmp_path / "data"
    _uninstall_repository(repository)
    data.mkdir()
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=data),
        preserve_data=False,
        data_entry=data,
    )

    with pytest.raises(UninstallFailure, match="nothing was deleted"):
        execute_uninstall(
            plan,
            _UninstallRuntime(running=True, stop_failure=True),
        )

    assert repository.exists()
    assert data.exists()


def test_uninstall_reports_partial_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    data = tmp_path / "data"
    _uninstall_repository(repository)
    data.mkdir()
    plan = build_uninstall_plan(
        AppPaths(repository=repository, data=data),
        preserve_data=False,
        data_entry=data,
    )
    real_rmtree = shutil.rmtree

    def fail_repository(path: Path) -> None:
        if path == repository:
            raise OSError("stubbed repository failure")
        real_rmtree(path)

    monkeypatch.setattr("knemora_bootstrap.uninstall.shutil.rmtree", fail_repository)

    with pytest.raises(UninstallFailure, match="partially completed") as raised:
        execute_uninstall(plan, _UninstallRuntime())

    assert "Removed:" in str(raised.value)
    assert "Remaining:" in str(raised.value)
    assert repository.exists()
    assert not data.exists()


def test_adk_web_port_selection_covers_free_occupied_and_repeated_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(repository=tmp_path, data=tmp_path / "data")
    monkeypatch.setattr("knemora_bootstrap.adk_web._configured_service_ports", lambda *args: {})

    monkeypatch.setattr("knemora_bootstrap.adk_web._port_is_available", lambda port: True)
    assert _select_port(paths, {}) == (8080, False)

    monkeypatch.setattr("knemora_bootstrap.adk_web._port_is_available", lambda port: port != 8080)
    monkeypatch.setattr("knemora_bootstrap.adk_web._is_knemora_adk_web", lambda port: False)
    assert _select_port(paths, {}) == (8081, False)

    monkeypatch.setattr("knemora_bootstrap.adk_web._is_knemora_adk_web", lambda port: True)
    assert _select_port(paths, {}) == (8080, True)

    monkeypatch.setattr("knemora_bootstrap.adk_web._port_is_available", lambda port: False)
    monkeypatch.setattr("knemora_bootstrap.adk_web._is_knemora_adk_web", lambda port: False)
    assert _select_port(paths, {}) == (None, False)


def test_adk_web_launch_uses_locked_environment_existing_agent_and_selected_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = tmp_path / "repository"
    api = repository / "apps" / "api"
    (api / ".venv" / "bin").mkdir(parents=True)
    (api / "knowledge_agent").mkdir()
    for executable in ("adk", "python"):
        (api / ".venv" / "bin" / executable).write_text("", encoding="utf-8")
    (repository / ".env").write_text(
        "KNEMORA_LLM_BASE_URL=http://localhost:11434\nKNEMORA_WEB_SEARCH_ENABLED=true\n",
        encoding="utf-8",
    )
    paths = AppPaths(repository=repository, data=tmp_path / "data")
    monkeypatch.setattr("knemora_bootstrap.adk_web._select_port", lambda *args: (8080, False))
    monkeypatch.setattr("knemora_bootstrap.adk_web._check_agent_import", lambda *args: None)
    monkeypatch.setattr("knemora_bootstrap.adk_web._check_model_server", lambda *args: None)
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert launch_adk_web(paths) == 0
    command = observed["command"]
    assert isinstance(command, list)
    assert command[:6] == [
        str(api / ".venv" / "bin" / "adk"),
        "web",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]
    assert command[-1] == str(api / "knowledge_agent")
    env = observed["env"]
    assert isinstance(env, dict)
    assert env["KNEMORA_WEB_SEARCH_ENABLED"] == "true"
    assert observed["cwd"] == api
    assert observed["stdin"] is subprocess.DEVNULL
    assert "Knemora ADK Web: http://localhost:8080" in capsys.readouterr().out


def test_adk_web_reports_missing_locked_install(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repository", data=tmp_path / "data")

    with pytest.raises(RuntimeError, match="Google ADK is missing"):
        launch_adk_web(paths)


def test_adk_web_preflights_have_actionable_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(["python"], 1)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: failed)
    with pytest.raises(RuntimeError, match="could not be imported"):
        _check_agent_import(tmp_path, tmp_path / "python", {})

    def unavailable(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("knemora_bootstrap.adk_web._read_json", unavailable)
    with pytest.raises(RuntimeError, match="local model server is unavailable"):
        _check_model_server({"KNEMORA_LLM_BASE_URL": "http://localhost:9999"})

    assert tuple(ADK_WEB_PORTS) == tuple(range(8080, 8091))


def test_model_registry_resolves_default_and_validates_existing_artifact(tmp_path: Path) -> None:
    payload = b"GGUF" + struct.pack("<IQQ", 3, 0, 0)
    model = ModelSpec(
        id="test-model",
        display_name="Test model",
        provider="llama_cpp",
        repository="example/test",
        filename="test.gguf",
        quantization="test",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        required_free_bytes=len(payload),
        recommended_memory_gb=1,
        context_tokens=512,
        license_url="https://example.test/license",
    )
    manager = ModelManager(tmp_path)
    manager.path_for(model).write_bytes(payload)

    default = get_model("default")
    assert default.id == DEFAULT_MODEL_ID == "qwen3-8b-q3-k-m"
    assert default.filename == "qwen3-8b-Q3_K_M.gguf"
    assert default.context_tokens == 8192
    assert get_model("qwen3.8-27b-iq2-s").filename == "Qwen3.8-27B-GSQ-RCO-IQ2_S.gguf"
    gemma = get_model("gemma-4-e4b-q4-k-m")
    assert gemma.filename == "gemma-4-E4B-it-Q4_K_M.gguf"
    assert gemma.revision == "bfc15c382204943c3a8fff0c750b94ae2364d7a3"
    assert gemma.sha256 == "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87"
    assert gemma.size_bytes == 4_977_171_584
    assert gemma.context_tokens == 8192
    assert gemma.advertised_context_tokens == 131_072
    assert gemma.verification_status == "knemora-tested"
    assert gemma.compatibility_status == "knemora-tested"
    assert default.thinking_control == "chat_template_enable_thinking"
    assert gemma.thinking_control == "chat_template_enable_thinking"
    assert gemma.download_url == (
        "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/"
        "bfc15c382204943c3a8fff0c750b94ae2364d7a3/"
        "gemma-4-E4B-it-Q4_K_M.gguf?download=true"
    )
    assert manager.ensure(model) == tmp_path / "test.gguf"


def test_configuration_preserves_existing_values_and_fills_missing_defaults(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / ".env"
    target.write_text("KNEMORA_API_PORT=9876\nKNEMORA_CUSTOM=value\n", encoding="utf-8")
    paths = AppPaths(repository=repository, data=tmp_path / "data")

    ensure_repository_env(paths)
    values = target.read_text(encoding="utf-8")

    assert values.count("KNEMORA_API_PORT=9876") == 1
    assert "KNEMORA_CUSTOM=value" in values
    assert "KNEMORA_BOOTSTRAP_ADMIN_PASSWORD=" in values
    assert "replace-with-a-unique-local-password" not in values
    assert f"KNEMORA_DATABASE_URL=sqlite+pysqlite:///{paths.database}" in values
    assert "KNEMORA_KNOWLEDGE_COMPILATION_MAX_OUTPUT_TOKENS=2048" in values
    assert "KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS=300" in values
    assert "POSTGRES_" not in values


def test_demo_runtime_owns_seeded_knowledge_as_the_bootstrap_administrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".env").write_text(
        "KNEMORA_BOOTSTRAP_ADMIN_EMAIL=owner@example.test\n"
        "KNEMORA_BOOTSTRAP_ADMIN_NAME=Demo Owner\n"
        f"KNEMORA_DATABASE_URL=sqlite+pysqlite:///{tmp_path / 'normal.db'}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("knemora_bootstrap.configuration.os.environ", {})
    paths = AppPaths(repository=repository, data=tmp_path / "data")
    ensure_repository_env(paths)

    values = runtime_environment(paths, demo=True)

    assert values["KNEMORA_DEFAULT_USER_EMAIL"] == "owner@example.test"
    assert values["KNEMORA_DEFAULT_USER_NAME"] == "Demo Owner"
    assert values["KNEMORA_DATABASE_URL"] == f"sqlite+pysqlite:///{paths.demo_database}"
    assert values["KNEMORA_SOURCE_STORE_PATH"].endswith("/demo/development/sources")
    assert values["KNEMORA_KNOWLEDGE_PATH"].endswith("/demo/development/knowledge")

    normal = runtime_environment(paths, demo=False)
    assert normal["KNEMORA_DATABASE_URL"].endswith("/normal.db")
    assert normal["KNEMORA_SOURCE_STORE_PATH"] != values["KNEMORA_SOURCE_STORE_PATH"]
    assert normal["KNEMORA_KNOWLEDGE_PATH"] != values["KNEMORA_KNOWLEDGE_PATH"]
    assert normal["KNEMORA_WEB_SEARCH_ENABLED"] == "false"

    repository_env = repository / ".env"
    repository_env.write_text(
        repository_env.read_text(encoding="utf-8").replace(
            "KNEMORA_WEB_SEARCH_ENABLED=false",
            "KNEMORA_WEB_SEARCH_ENABLED=true",
        ),
        encoding="utf-8",
    )

    assert runtime_environment(paths, demo=False)["KNEMORA_WEB_SEARCH_ENABLED"] == "true"


def test_development_catalog_is_deterministic_meaningful_and_connected() -> None:
    first = build_catalog()
    second = build_catalog()

    assert first == second
    assert len(first) == 120
    assert len({page.title for page in first}) == 120
    assert all(page.claim and page.relationships for page in first)
    assert all(value in render_source().decode() for value in EXPECTED_FACTS.values())
    assert manifest()["generated_wiki_pages"] == 120


def test_development_seed_uses_ingestion_compiler_index_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        authentication_required=False,
        source_store_path=tmp_path / "immutable-sources",
        knowledge_path=tmp_path / "demo-wiki",
        knowledge_compilation_batch_chars=12_000,
    )

    first = seed_sync(settings, engine=engine, preset_root=tmp_path / "preset")
    parse_count = 0
    original_parse = WikiStore._parse_page

    def counted_parse(self: WikiStore, path: Path):  # type: ignore[no-untyped-def]
        nonlocal parse_count
        parse_count += 1
        return original_parse(self, path)

    monkeypatch.setattr(WikiStore, "_parse_page", counted_parse)
    second = seed_sync(settings, engine=engine, preset_root=tmp_path / "preset")
    cached_seed_parse_count = parse_count
    cached_source_count = len(list((settings.knowledge_path / "sources").glob("*.md")))

    fresh_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(fresh_engine)
    with fresh_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    parse_count = 0
    relinked = seed_sync(
        settings,
        engine=fresh_engine,
        preset_root=tmp_path / "preset",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert relinked["created"] is True
    assert first["pages"] == 120
    assert second["pages"] == 120
    assert relinked["pages"] == 120
    assert cached_seed_parse_count <= 240
    assert parse_count <= 1_500
    assert first["orphans"] == 0
    assert first["clusters"] >= 17
    assert first["lint_errors"] == 0
    store = WikiStore(settings.knowledge_path)
    orbit = store.read_page("Project ORBIT-LANTERN")
    assert orbit.provenance
    assert {link.target_title for link in orbit.relationships} >= {
        "Cedar Gate",
        "Atlas Platform Team",
        "DEV-POL-017",
        "Development Freeze",
    }
    index = json.loads((store.internal_root / "search-index" / "pages.json").read_text())
    assert len(index["pages"]) == 120
    assert cached_source_count == 1
    assert len(list((settings.knowledge_path / "sources").glob("*.md"))) == 2


def test_preset_cache_detection_uses_the_development_directory(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    paths.demo.mkdir(parents=True)
    assert not _preset_files_available(paths)

    (paths.demo / "manifest.json").write_text("{}\n", encoding="utf-8")
    (paths.demo / "northstar-development-v1.md").write_text("demo\n", encoding="utf-8")
    (paths.demo / "knowledge" / "wiki").mkdir(parents=True)

    assert _preset_files_available(paths)


def test_startup_progress_reports_stage_and_percentage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    StartupProgress(total=4, width=8).update(2, "Development database is ready.")

    assert capsys.readouterr().out == "[####----]  50%  Development database is ready.\n"
