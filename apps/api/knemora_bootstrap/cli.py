"""Implementation of the repository-root Knemora product launcher."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.home import HomeCompatibilityService
from knemora_bootstrap.adk_web import launch_adk_web
from knemora_bootstrap.configuration import (
    AppPaths,
    ensure_repository_env,
    mark_setup_complete,
    read_backup_path,
    resolve_context_preference,
    rollback_model_selection,
    runtime_environment,
    setup_is_complete,
    update_repository_database_url,
    write_backup_path,
    write_model_selection,
)
from knemora_bootstrap.development_preset import CANONICAL_PROMPT
from knemora_bootstrap.model_context import describe_context_admission, plan_context
from knemora_bootstrap.model_import import HuggingFaceArtifact, ModelImporter, partial_path_for
from knemora_bootstrap.models import (
    DEFAULT_MODEL_ID,
    ModelManager,
    ModelRegistry,
    ModelSpec,
    enrich_model_from_local_gguf,
    get_model,
)
from knemora_bootstrap.native_runtime import NativeRuntimeManager
from knemora_bootstrap.platforms import PlatformAdapter, detect_platform
from knemora_bootstrap.runtime import RuntimeManager

if TYPE_CHECKING:
    from app.config import Settings

BANNER = r"""Welcome to

 _  __
| |/ /_ __   ___ _ __ ___   ___  _ __ __ _
| ' /| '_ \ / _ \ '_ ` _ \ / _ \| '__/ _` |
| . \| | | |  __/ | | | | | (_) | | | (_| |
|_|\_\_| |_|\___|_| |_| |_|\___/|_|  \__,_|

Local-first knowledge and agents with a native Second Brain
"""


class StartupProgress:
    """Small dependency-free stage bar for the local startup path."""

    def __init__(self, total: int = 4, width: int = 24) -> None:
        self.total = total
        self.width = width

    def update(self, completed: int, message: str) -> None:
        bounded = max(0, min(completed, self.total))
        filled = round(self.width * bounded / self.total)
        percent = round(100 * bounded / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        print(f"[{bar}] {percent:>3}%  {message}", flush=True)


def _run_setup_command(
    command: list[str],
    *,
    cwd: Path,
    step: str,
    env: dict[str, str] | None = None,
) -> None:
    """Run one setup command and retain enough context to diagnose its failure."""

    try:
        subprocess.run(command, cwd=cwd, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{step} failed with exit status {exc.returncode}.\n"
            f"Command: {shlex.join(command)}\nWorking directory: {cwd}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"{step} could not start {command[0]!r}: {exc}.\n"
            f"Command: {shlex.join(command)}\nWorking directory: {cwd}"
        ) from exc


def _virtual_environment_was_relocated(api_directory: Path) -> bool:
    """Detect console scripts whose absolute shebang still names an old checkout."""

    scripts = api_directory / ".venv" / "bin"
    for name in ("alembic", "uvicorn", "pytest"):
        script = scripts / name
        try:
            first_line = script.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, UnicodeError, IndexError):
            continue
        interpreter = first_line.removeprefix("#!").strip()
        interpreter_path = Path(interpreter)
        if (
            first_line.startswith("#!")
            and interpreter_path.name.startswith("python")
            and interpreter_path.parent.name == "bin"
            and interpreter_path.parent.parent.name == ".venv"
            and interpreter_path.parent != scripts
        ):
            return True
    return False


class SetupManager:
    def __init__(self, paths: AppPaths, platform: PlatformAdapter) -> None:
        self.paths = paths
        self.platform = platform

    def run(self, *, model_id: str, context_tokens: int | None = None) -> None:
        model = get_model(model_id, self.paths.model_registry)
        model = enrich_model_from_local_gguf(model, self.paths.models)
        failures = self.platform.check_prerequisites()
        if failures:
            raise RuntimeError("\n".join(f"- {failure}" for failure in failures))
        hardware = self.platform.hardware()
        print(
            f"Detected {hardware.os} {hardware.architecture}; "
            f"accelerator: {hardware.accelerator}; "
            f"memory: {hardware.memory_gb:.1f} GB."
            if hardware.memory_gb is not None
            else (
                f"Detected {hardware.os} {hardware.architecture}; "
                f"accelerator: {hardware.accelerator}."
            )
        )
        preference = resolve_context_preference(
            self.paths,
            model,
            cli_context_tokens=context_tokens,
        )
        context_plan = plan_context(
            model,
            hardware,
            configured_context_tokens=preference.tokens,
            source=preference.source,
            explicit=preference.explicit,
        )
        memory = context_plan.memory
        budget = (
            f"{memory.safe_budget_bytes / 1024**3:.2f} GiB safe budget"
            if memory.safe_budget_bytes is not None
            else "host budget unavailable"
        )
        advertised = (
            f"{context_plan.advertised_context_tokens:,} advertised"
            if context_plan.advertised_context_tokens is not None
            else "advertised maximum unavailable"
        )
        print(
            f"Context preflight: {context_plan.effective_context_tokens:,} effective tokens "
            f"({advertised}; {context_plan.reason})."
        )
        print(describe_context_admission(context_plan))
        print(
            f"Memory preflight: {memory.total_bytes / 1024**3:.2f} GiB estimated, {budget}; "
            f"uncertainty {memory.uncertainty}."
        )
        HomeCompatibilityService(self.paths.data, repository=self.paths.repository).ensure_current()
        self.paths.initialize()
        ensure_repository_env(self.paths)
        self._prepare_application()
        selection = NativeRuntimeManager(self.paths).ensure_llama()
        print(
            "Native runtime ready: "
            f"{selection.source} {selection.version} {selection.platform}/"
            f"{selection.architecture}/{selection.backend} at {selection.executable}"
        )
        print(f"Ensuring model: {model.display_name} ({model.quantization})")
        model_path = ModelManager(self.paths.models).ensure(model)
        self._prepare_database()
        write_model_selection(
            self.paths,
            model,
            model_path,
            plan=context_plan,
            explicit_context_tokens=context_tokens,
        )
        try:
            mark_setup_complete(self.paths, model)
        except OSError:
            rollback_model_selection(self.paths)
            raise
        print("Setup complete. Existing configuration and user data were preserved.")
        print(
            "Local administrator sign-in values are stored only in "
            f"{self.paths.repository / '.env'} (mode 0600); secrets are never printed."
        )

    def _prepare_application(self) -> None:
        api_directory = self.paths.repository / "apps/api"
        python = api_directory / ".venv" / "bin" / "python"
        alembic = api_directory / ".venv" / "bin" / "alembic"
        if not python.is_file() or not alembic.is_file():
            raise RuntimeError(
                "The managed Python environment is incomplete. Rerun ./knemora so the "
                "Node bootstrap can repair it."
            )
        _run_setup_command(
            [str(alembic), "--version"],
            cwd=api_directory,
            step="Alembic availability check",
        )
        _run_setup_command(
            ["npm", "ci"],
            cwd=self.paths.repository / "apps/web",
            step="Web dependency installation",
        )

    def _prepare_database(self) -> None:
        env = runtime_environment(self.paths)
        _run_setup_command(
            [str(self.paths.repository / "apps/api/.venv/bin/alembic"), "upgrade", "head"],
            cwd=self.paths.repository / "apps/api",
            env=env,
            step="Database migration",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="./knemora", description="Knemora local product launcher")
    parser.set_defaults(with_presets=False, presets=False)
    parser.add_argument(
        "--yes", "-y", action="store_true", help="accept the first-run confirmation"
    )
    parser.add_argument("--non-interactive", action="store_true", help="never prompt for input")
    parser.add_argument(
        "--no-open", action="store_true", help="do not open the Knemora web interface"
    )
    parser.add_argument(
        "--dev", action="store_true", help="enable explicitly requested developer commands"
    )
    canonical_commands = (
        "setup",
        "migrate-postgresql",
        "backup",
        "backups",
        "restore",
        "config",
        "load",
        "start",
        "adk-web",
        "delete",
        "uninstall",
        "stop",
        "restart",
        "status",
        "logs",
        "doctor",
        "update",
        "models",
        "model",
    )
    sub = parser.add_subparsers(
        dest="command",
        metavar="{" + ",".join(canonical_commands) + "}",
    )
    setup = sub.add_parser("setup", help="prepare dependencies, model, configuration, and database")
    setup.add_argument("--model", default="default", help="stable model registry ID")
    setup.add_argument(
        "--context-tokens",
        type=int,
        help="validated per-model context override (minimum 4096; never exceeds GGUF capability)",
    )
    migrate = sub.add_parser(
        "migrate-postgresql",
        help="safely import an existing PostgreSQL installation into SQLite",
    )
    migrate.add_argument(
        "--source-url",
        required=True,
        help="explicit PostgreSQL SQLAlchemy URL; the source is never modified",
    )
    migrate.add_argument(
        "--backup-dir",
        type=Path,
        help="backup parent outside KNEMORA_HOME (default: ./backups)",
    )
    backup = sub.add_parser("backup", help="create a validated portable backup archive")
    backup.set_defaults(backup_type="full", backup_command=None)
    backup_type = backup.add_mutually_exclusive_group()
    backup_type.add_argument(
        "--full", dest="backup_type", action="store_const", const="full", help="include all data"
    )
    backup_type.add_argument(
        "--db-only",
        dest="backup_type",
        action="store_const",
        const="database",
        help="include only the SQLite database",
    )
    backup.add_argument(
        "--path", type=Path, help="destination directory; saved as the future default"
    )
    backup_commands = backup.add_subparsers(dest="backup_command")
    delete = backup_commands.add_parser("delete", help="delete one configured backup by ID")
    delete.add_argument("backup_id")
    sub.add_parser("backups", help="list and validate archives in the configured backup path")
    restore = sub.add_parser("restore", help="restore a backup ID or explicit archive path")
    restore.add_argument("backup_reference")
    restore.add_argument(
        "--allow-db-only",
        action="store_true",
        help="acknowledge that current Wiki/source files will be preserved",
    )
    config = sub.add_parser("config", help="inspect or change local Knemora configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    backup_path = config_commands.add_parser(
        "backup-path", help="show or change the portable-backup destination"
    )
    backup_path.add_argument("path", nargs="?", type=Path)
    load = sub.add_parser("load", help="import and register an external Hugging Face GGUF")
    load.add_argument("--model", required=True, help="hf:<owner>/<repository>:<variant>")
    load.add_argument("--id", help="optional unique lowercase Knemora model ID")
    start = sub.add_parser("start", help="start the normal local environment")
    start.add_argument(
        "--with-presets",
        action="store_true",
        help="start the isolated Development demo",
    )
    presets = sub.add_parser("start-with-presets")
    presets.set_defaults(with_presets=True, deprecated_replacement="start --with-presets")
    sub.add_parser("adk-web", help="start the optional Google ADK developer UI")
    delete_target = sub.add_parser("delete", help="delete an explicitly selected Knemora target")
    delete_target.add_argument(
        "--presets",
        action="store_true",
        required=True,
        help="delete only Development demo data and its database",
    )
    delete_presets = sub.add_parser("delete-presets")
    delete_presets.set_defaults(presets=True, deprecated_replacement="delete --presets")
    uninstall = sub.add_parser(
        "uninstall",
        help="remove this repository and optionally its application data",
    )
    uninstall.add_argument(
        "--preserve-data",
        action="store_true",
        help="remove the repository but keep the entire application data directory",
    )
    sub.add_parser("stop", help="stop managed services without deleting data")
    sub.add_parser("restart", help="restart the active normal or demo environment")
    sub.add_parser("status", help="report actual managed service state")
    logs = sub.add_parser("logs", help="show managed service logs")
    logs.add_argument("--follow", "-f", action="store_true")
    logs.add_argument("--lines", type=int, default=80)
    sub.add_parser("doctor", help="run local platform and runtime diagnostics")
    update = sub.add_parser("update", help="check or install the official stable update")
    update.add_argument(
        "--check",
        action="store_true",
        help="check official master without changing application files or restarting",
    )
    sub.add_parser("models", help="list curated and user local model registry entries")
    model = sub.add_parser("model", help="inspect or remove a registered model")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    info = model_commands.add_parser("info", help="show registered model metadata")
    info.add_argument("model_id")
    remove = model_commands.add_parser("remove", help="remove model artifacts or registry metadata")
    remove.add_argument("model_id")
    remove.add_argument(
        "scope",
        nargs="?",
        choices=("registry",),
        help="remove the registry definition after local artifact data is removed",
    )
    return parser


def _interactive_first_run() -> str:
    print("How would you like to start?\n")
    print("  1. Start Knemora\n     Normal local environment.\n")
    print(
        "  2. Start with Development demo\n"
        "     Loads synthetic knowledge, 100+ Wiki pages and the guided demo.\n"
    )
    print(f"Model:\n  Default — {get_model('default').display_name}\n")
    choice = input("Choose 1 or 2 [1]: ").strip() or "1"
    if choice not in {"1", "2"}:
        raise RuntimeError("Please choose 1 or 2.")
    confirm = input("Continue? [Y/n] ").strip().casefold()
    if confirm not in {"", "y", "yes"}:
        raise RuntimeError("Setup cancelled; no data was changed.")
    return "start-with-presets" if choice == "2" else "start"


def _ensure_setup(
    paths: AppPaths, platform: PlatformAdapter, *, model_id: str, approved: bool
) -> None:
    if setup_is_complete(paths):
        HomeCompatibilityService(paths.data, repository=paths.repository).validate_ready()
        return
    if not approved:
        raise RuntimeError("First-run setup requires confirmation; rerun with --yes.")
    SetupManager(paths, platform).run(model_id=model_id)


def _seed_demo(paths: AppPaths) -> bool:
    env = runtime_environment(paths, demo=True)
    env["KNEMORA_DEMO_ROOT"] = str(paths.demo)
    result = subprocess.run(
        [
            str(paths.repository / "apps/api/.venv/bin/python"),
            "-m",
            "knemora_bootstrap.seed_cli",
        ],
        cwd=paths.repository / "apps/api",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"Development preset seeding or validation failed: {detail}")
    print(result.stdout.strip())
    try:
        return bool(json.loads(result.stdout)["created"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Development preset returned an invalid status payload.") from exc


def _preset_files_available(paths: AppPaths) -> bool:
    """Return whether the reusable Development preset exists on disk."""

    return (
        (paths.demo / "manifest.json").is_file()
        and any(paths.demo.glob("northstar-development-v*.md"))
        and (paths.demo / "knowledge" / "wiki").is_dir()
    )


def _delete_presets(paths: AppPaths, runtime: RuntimeManager) -> None:
    expected = (paths.data / "demo" / "development").resolve()
    if paths.demo.resolve() != expected:
        raise RuntimeError(f"Refusing to delete unexpected preset path: {paths.demo}")
    if runtime.current_mode() == "development" and any(
        status.running for status in runtime.status() if status.name != "database"
    ):
        runtime.stop()
    runtime.delete_demo_database()
    bytes_removed = (
        sum(path.stat().st_size for path in paths.demo.rglob("*") if path.is_file())
        if paths.demo.exists()
        else 0
    )
    if paths.demo.exists():
        shutil.rmtree(paths.demo)
    mode_file = paths.runtime / "mode.json"
    if runtime.current_mode() == "development":
        mode_file.unlink(missing_ok=True)
    print(
        "Deleted the Development presets and knemora_demo database; "
        f"freed approximately {bytes_removed / 1_000_000:.1f} MB. "
        "The model and normal user data were preserved."
    )


def _doctor(paths: AppPaths, platform: PlatformAdapter, runtime: RuntimeManager) -> int:
    hardware = platform.hardware()
    disk_base = paths.data if paths.data.exists() else paths.data.parent
    disk_free = shutil.disk_usage(disk_base).free
    model_valid = False
    model_detail = str(paths.config / "model.json")
    try:
        selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
        selected = get_model(str(selection["model_id"]), paths.model_registry)
        model_valid = ModelManager(paths.models).is_valid(selected)
        model_detail = str(ModelManager(paths.models).path_for(selected))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        pass
    wiki_valid = False
    venv_python = paths.repository / "apps/api/.venv/bin/python"
    if paths.wiki.is_dir() and venv_python.is_file():
        wiki_check = subprocess.run(
            [str(venv_python), "-m", "app.cli", "wiki-lint"],
            cwd=paths.repository / "apps/api",
            env=runtime_environment(paths),
            capture_output=True,
            text=True,
            check=False,
        )
        wiki_valid = wiki_check.returncode == 0
    home_inspection = HomeCompatibilityService(paths.data, repository=paths.repository).inspect()
    native = NativeRuntimeManager(paths).inspect()
    checks: list[tuple[str, bool, str, bool]] = [
        (
            "platform",
            hardware.os == "macOS" and hardware.architecture == "arm64",
            f"{hardware.os} {hardware.architecture}",
            True,
        ),
        (
            "application home",
            home_inspection.status == "ready",
            f"{home_inspection.status}: {home_inspection.detail}",
            True,
        ),
        ("Node.js", shutil.which("node") is not None, shutil.which("node") or "missing", True),
        ("npm", shutil.which("npm") is not None, shutil.which("npm") or "missing", True),
        (
            "disk space",
            disk_free >= get_model("default").required_free_bytes,
            f"{disk_free / 1_000_000_000:.1f} GB free",
            True,
        ),
        (
            "llama.cpp runtime",
            native is not None,
            (
                f"{native.source} {native.version} {native.platform}/{native.architecture}/"
                f"{native.backend}; {native.integrity}; {native.executable}"
                if native
                else "missing or invalid; run ./knemora setup"
            ),
            True,
        ),
        ("setup state", setup_is_complete(paths), str(paths.config / "state.json"), True),
        (
            "model checksum",
            model_valid,
            model_detail,
            True,
        ),
        ("Wiki lint", wiki_valid, str(paths.wiki), True),
    ]
    checks.extend((status.name, status.running, status.detail, True) for status in runtime.status())
    checks.extend(
        (
            name,
            runtime.http_ok(url),
            url,
            True,
        )
        for name, url in (
            ("llama.cpp health", "http://localhost:8080/health"),
            ("API health", "http://localhost:8000/api/v1/health"),
            ("frontend health", "http://localhost:5173/"),
        )
    )
    for name, passed, detail, critical in checks:
        label = "PASS" if passed else "FAIL" if critical else "WARN"
        print(f"{label}  {name}: {detail}")
    return 0 if all(passed for _, passed, _, critical in checks if critical) else 1


def _selected_model_id(paths: AppPaths) -> str | None:
    try:
        payload = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    model_id = payload.get("model_id") if isinstance(payload, dict) else None
    return model_id if isinstance(model_id, str) else None


def _print_models(paths: AppPaths) -> None:
    registry = ModelRegistry(paths.model_registry)
    manager = ModelManager(paths.models)
    active = _selected_model_id(paths)
    print("Knemora Models\n")
    print(f"{'ID':30} {'SOURCE':8} {'VERIFICATION':12} {'ARTIFACT':14} FLAGS")
    print("-" * 86)
    for model in registry.effective().values():
        source = "User" if model.is_user_import else "Knemora"
        if model.is_user_import:
            verification = "Custom"
        elif model.verification_status == "knemora-tested":
            verification = "Tested"
        else:
            verification = "Candidate"
        flags = []
        if model.id == DEFAULT_MODEL_ID:
            flags.append("default")
        if model.id == active:
            flags.append("active")
        print(
            f"{model.id:30} {source:8} {verification:12} "
            f"{manager.artifact_status(model):14} {', '.join(flags)}"
        )


def _print_model_info(paths: AppPaths, model_id: str) -> None:
    model = ModelRegistry(paths.model_registry).get(model_id)
    model = enrich_model_from_local_gguf(model, paths.models)
    preference = resolve_context_preference(paths, model)
    manager = ModelManager(paths.models)
    selection: dict[str, object] = {}
    try:
        raw_selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
        if isinstance(raw_selection, dict) and raw_selection.get("model_id") == model.id:
            selection = raw_selection
    except (OSError, ValueError, TypeError):
        pass
    selected_context = selection.get("context_tokens")
    estimated_memory = selection.get("estimated_memory_bytes")
    safe_budget = selection.get("safe_memory_budget_bytes")
    if isinstance(estimated_memory, int):
        budget_detail = (
            f" versus {safe_budget / 1024**3:.2f} GiB safe budget"
            if isinstance(safe_budget, int)
            else "; safe budget unavailable"
        )
        memory_assessment = (
            f"last preflight: {estimated_memory / 1024**3:.2f} GiB estimated{budget_detail} "
            f"({selection.get('memory_estimate_uncertainty', 'uncertainty unavailable')}); "
            "time-dependent and not a launch guarantee"
        )
    else:
        memory_assessment = "not preflighted; launch admission is time-dependent"
    values = (
        ("ID", model.id),
        ("Origin", "user" if model.is_user_import else "Knemora curated"),
        ("Repository", model.repository),
        ("Revision", model.revision),
        ("Artifact", model.artifact or model.filename),
        ("Variant", model.variant or model.quantization),
        ("Runtime", model.runtime),
        ("Local path", str(manager.path_for(model))),
        ("Size", f"{model.size_bytes} bytes ({model.size_bytes / 1_000_000_000:.2f} GB)"),
        ("Checksum", f"sha256:{model.sha256}"),
        ("Verification", model.verification_status),
        ("Compatibility", model.compatibility_status),
        (
            "Advertised context",
            (
                f"{model.advertised_context_tokens:,} tokens"
                if model.advertised_context_tokens is not None
                else "unavailable; conservative profile only"
            ),
        ),
        ("Profile context", f"{model.context_tokens:,} tokens"),
        ("Configured preference", f"{preference.tokens:,} tokens"),
        ("Configuration mode", "explicit" if preference.explicit else "automatic"),
        (
            "Effective context (last preflight)",
            (f"{selected_context:,} tokens" if isinstance(selected_context, int) else "not active"),
        ),
        ("Context source", preference.source),
        ("Last preflight rationale", str(selection.get("context_reason", "not active"))),
        ("Memory assessment", memory_assessment),
        ("Artifact status", manager.artifact_status(model)),
        ("License reference", model.license_url),
        ("Imported at", model.imported_at or "distributed with Knemora"),
        ("Default", "yes" if model.id == DEFAULT_MODEL_ID else "no"),
        ("Active", "yes" if model.id == _selected_model_id(paths) else "no"),
    )
    for label, value in values:
        print(f"{label}: {value}")


def _removal_paths(paths: AppPaths, model: ModelSpec) -> tuple[Path, ...]:
    artifact = ModelManager(paths.models).path_for(model)
    candidates = [
        artifact,
        artifact.with_suffix(artifact.suffix + ".partial"),
        artifact.with_suffix(artifact.suffix + ".invalid"),
        artifact.with_suffix(artifact.suffix + ".removing"),
    ]
    if model.is_user_import:
        candidates.append(
            partial_path_for(
                paths.models, model.id, model.repository, model.artifact or model.filename
            )
        )
    return tuple(dict.fromkeys(candidates))


def _validate_model_removal(paths: AppPaths, model_id: str) -> ModelSpec:
    registry = ModelRegistry(paths.model_registry)
    model = registry.get(model_id)
    if _selected_model_id(paths) == model.id:
        raise RuntimeError(
            f"Model {model.id!r} is active. Select another registered model with setup first."
        )
    return model


def _remove_model(paths: AppPaths, model_id: str) -> None:
    model = _validate_model_removal(paths, model_id)
    removal_paths = _removal_paths(paths, model)
    artifact = removal_paths[0]
    staged = artifact.with_suffix(artifact.suffix + ".removing")
    if staged.exists():
        raise RuntimeError(f"Cannot remove model while a prior staged removal exists: {staged}")
    if artifact.exists():
        artifact.replace(staged)
    staged.unlink(missing_ok=True)
    for path in removal_paths[1:]:
        path.unlink(missing_ok=True)
    print(f"Removed local artifact data for {model.id!r}; its registry entry remains available.")
    print("Wiki, sources, datasets, databases, and other models were unchanged.")


def _remove_registry_definition(paths: AppPaths, model_id: str) -> None:
    registry = ModelRegistry(paths.model_registry)
    model = _validate_model_removal(paths, model_id)
    if model.id == DEFAULT_MODEL_ID:
        raise RuntimeError(
            f"The required default model definition {DEFAULT_MODEL_ID!r} cannot be removed."
        )
    if any(path.exists() for path in _removal_paths(paths, model)):
        raise RuntimeError(
            f"Model {model.id!r} still has local artifact data.\n\n"
            "Run these commands in order:\n"
            f"  ./knemora model remove {model.id}\n"
            f"  ./knemora model remove {model.id} registry"
        )
    if model.is_user_import:
        registry.remove(model.id)
        detail = "user registry entry"
    else:
        registry.hide_curated(model.id)
        detail = "curated registry definition from the local effective registry"
    print(f"Removed {detail} for {model.id!r}.")
    print("Wiki, sources, datasets, databases, and other models were unchanged.")


def _backup_settings(paths: AppPaths) -> Settings:
    """Build normal-mode storage settings without loading repository secrets."""

    from app.config import Settings

    environment = runtime_environment(paths)
    return Settings(
        _env_file=None,
        database_url=environment["KNEMORA_DATABASE_URL"],
        source_store_path=environment["KNEMORA_SOURCE_STORE_PATH"],
        knowledge_path=environment["KNEMORA_KNOWLEDGE_PATH"],
    )


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{size_bytes} B"


def _confirm_or_raise(*, approved: bool, interactive: bool, prompt: str, failure: str) -> None:
    if interactive and not approved:
        answer = input(prompt).strip().casefold()
        approved = answer in {"y", "yes"}
    if not approved:
        raise RuntimeError(failure)


def _runtime_processes_active(runtime: RuntimeManager) -> bool:
    if any(status.running for status in runtime.status() if status.name != "database"):
        return True
    return any(
        runtime.http_ok(url)
        for url in (
            "http://localhost:8080/health",
            "http://localhost:8000/api/v1/health",
            "http://localhost:5173/",
        )
    )


def _print_update_snapshot(snapshot: object) -> None:
    from knemora_bootstrap.update import UpdateSnapshot

    if not isinstance(snapshot, UpdateSnapshot):
        raise TypeError("Expected an update snapshot.")
    running = snapshot.running
    target = snapshot.target
    print(f"Stable channel: {snapshot.channel}")
    if running:
        print(f"Running: {running.app_version or 'unknown version'} ({running.short_sha})")
    if target:
        print(f"Target:  {target.app_version or 'unknown version'} ({target.short_sha})")
    print(f"State:   {snapshot.state.replace('_', ' ')}")
    if snapshot.cached:
        print("Result:  cached")
    if snapshot.error:
        print(snapshot.error)
    if snapshot.blocked_reason:
        print(f"Install: blocked — {snapshot.blocked_reason}")
    if snapshot.changes:
        print("Changes:")
        for change in snapshot.changes:
            label = (
                f"PR #{change.pull_request_number}: {change.pull_request_title}"
                if change.pull_request_number and change.pull_request_title
                else change.subject
            )
            print(f"  {change.short_sha}  {label}")
        if snapshot.changes_truncated:
            print("  … additional commits omitted")
    if snapshot.dependency_changes:
        print("Dependency/runtime files changed; locked preparation runs before activation.")
    if snapshot.migration_changes:
        print("Database migrations are present; backup precedes guarded migration.")
    print(snapshot.privacy_notice)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = AppPaths.discover()
    platform = detect_platform()
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.non_interactive
    if interactive and os.environ.get("KNEMORA_BANNER_SHOWN") != "1":
        print(BANNER)
    command = args.command
    wizard_approved = False
    if command is None and not setup_is_complete(paths) and interactive:
        command = _interactive_first_run()
        args.with_presets = command == "start-with-presets"
        wizard_approved = True
    elif command is None:
        command = "start"
    runtime = RuntimeManager(paths, platform)
    try:
        # Confirmation failures should remain side-effect free and actionable even when setup has
        # not yet registered this home. Compatibility is still checked before any mutation.
        if command == "load" and args.non_interactive and not args.yes:
            raise RuntimeError("Non-interactive model import requires --yes.")
        if command not in {
            "setup",
            "start",
            "start-with-presets",
            "stop",
            "status",
            "logs",
            "doctor",
            "backups",
            "uninstall",
        }:
            HomeCompatibilityService(paths.data, repository=paths.repository).validate_ready()
        replacement = getattr(args, "deprecated_replacement", None)
        if replacement:
            print(
                f"Warning: './knemora {args.command}' is deprecated; use "
                f"'./knemora {replacement}'.",
                file=sys.stderr,
            )
        if command == "uninstall":
            from knemora_bootstrap.uninstall import uninstall

            completed = uninstall(
                paths,
                runtime,
                preserve_data=args.preserve_data,
                interactive=interactive,
                approved_by_global_flag=args.yes,
            )
            return 0 if completed else 1
        if command == "config" and args.config_command == "backup-path":
            if args.path is None:
                print(read_backup_path(paths))
            else:
                destination = write_backup_path(paths, args.path)
                print(f"Backup path saved: {destination}")
            return 0
        if command == "backups":
            from knemora_bootstrap.local_backup import list_backups

            destination = read_backup_path(paths)
            records = list_backups(destination)
            print(f"Backup directory: {destination}")
            if not records:
                print("No portable backups found.")
                return 0
            print(f"{'ID':47} {'CREATED (UTC)':27} {'TYPE':9} {'SIZE':10} VALIDATION")
            print("-" * 112)
            for record in records:
                print(
                    f"{record.id:47} {record.created_at:27} {record.backup_type:9} "
                    f"{_format_size(record.size_bytes):10} {record.validation}"
                )
            return 0
        if command == "backup":
            from knemora_bootstrap.local_backup import create_backup, delete_backup

            destination = args.path.expanduser().resolve() if args.path else read_backup_path(paths)
            if args.backup_command == "delete":
                _confirm_or_raise(
                    approved=args.yes,
                    interactive=interactive,
                    prompt=f"Delete backup {args.backup_id!r}? This cannot be undone. [y/N] ",
                    failure="Backup deletion requires confirmation; rerun with --yes.",
                )
                removed = delete_backup(args.backup_id, destination)
                print(f"Deleted backup archive: {removed}")
                return 0
            settings = _backup_settings(paths)
            services_running = _runtime_processes_active(runtime)
            active_demo = runtime.current_mode() == "development"
            if args.backup_type == "full" and services_running:
                print("Pausing Knemora writers for a coherent full backup…")
                runtime.stop()
            try:
                backup_result = create_backup(
                    destination,
                    args.backup_type,
                    settings,
                    paths=paths,
                )
            finally:
                if args.backup_type == "full" and services_running:
                    runtime.start(
                        demo=active_demo,
                        open_apps=False,
                        demo_database_prepared=active_demo,
                    )
            if args.path is not None:
                write_backup_path(paths, destination)
            print("Backup completed and validated.")
            print(f"ID:      {backup_result.id}")
            print(f"Type:    {'full' if backup_result.backup_type == 'full' else 'database only'}")
            print(f"Archive: {backup_result.archive}")
            print(f"Size:    {_format_size(backup_result.size_bytes)}")
            if backup_result.backup_type == "database":
                print(
                    "Not protected: Wiki notes, immutable sources, attachments, and model config."
                )
            else:
                print("GGUF model files and credentials were intentionally excluded.")
            return 0
        if command == "restore":
            from knemora_bootstrap.local_backup import (
                resolve_backup,
                restore_backup,
                validate_backup,
            )

            destination = read_backup_path(paths)
            archive = resolve_backup(args.backup_reference, destination)
            manifest = validate_backup(archive)
            backup_type = str(manifest["backup_type"])
            if backup_type == "database" and not args.allow_db_only:
                print(
                    "Database-only restore preserves the current Wiki and source files. "
                    "Those files may not match the restored database."
                )
            _confirm_or_raise(
                approved=args.yes,
                interactive=interactive,
                prompt=(
                    f"Restore {archive.name} over the current installation? "
                    "A recovery archive will be created first. [y/N] "
                ),
                failure="Restore requires confirmation; rerun with --yes.",
            )
            if _runtime_processes_active(runtime):
                print("Stopping Knemora services before restore…")
                runtime.stop()
            restore_result = restore_backup(
                archive,
                _backup_settings(paths),
                paths=paths,
                recovery_directory=destination,
                allow_db_only=args.allow_db_only,
            )
            print("Restore completed and validated; the source archive was preserved.")
            print(f"Restored:         {', '.join(restore_result.restored_roots)}")
            print(f"Active database:  {restore_result.database}")
            print(f"Recovery archive: {restore_result.recovery_archive}")
            print(
                "Credentials:      Restored accounts and password hashes are authoritative; "
                "sign in with credentials from the backup. The destination setup password "
                "is no longer authoritative."
            )
            if restore_result.backup_type == "database":
                print("Existing Wiki and source files were preserved by explicit request.")
            if restore_result.archived_model_id:
                print(
                    f"Archived model:   {restore_result.archived_model_id} "
                    "(GGUF excluded; download or select it with ./knemora setup if needed)"
                )
            print("Services remain stopped; run ./knemora start after reviewing the restore.")
            return 0
        if command == "adk-web":
            if not args.dev:
                raise RuntimeError("ADK Web is a developer command; run ./knemora --dev adk-web.")
            return launch_adk_web(paths)
        if command == "update":
            from knemora_bootstrap.update import UpdateService, wait_for_job

            updates = UpdateService(paths)
            snapshot = updates.check()
            _print_update_snapshot(snapshot)
            if args.check:
                if snapshot.state == "update_available":
                    return 10
                return 0 if snapshot.state == "up_to_date" else 2
            if not snapshot.installable or snapshot.target is None:
                if snapshot.state == "up_to_date":
                    print("Knemora is already up to date.")
                    return 0
                raise RuntimeError(
                    snapshot.blocked_reason or snapshot.error or "Update unavailable."
                )
            _confirm_or_raise(
                approved=args.yes,
                interactive=interactive,
                prompt=(
                    f"Install pinned update {snapshot.target.short_sha} and restart Knemora? [y/N] "
                ),
                failure="Update installation requires confirmation; rerun with --yes.",
            )
            update_job = updates.create_job(snapshot.target.sha)
            if not update_job.get("deduplicated"):
                updates.spawn_job(str(update_job["id"]))
            completed_job = wait_for_job(updates, str(update_job["id"]))
            if completed_job["status"] != "complete":
                raise RuntimeError(str(completed_job.get("error") or "Update failed."))
            print("Update installed. Reload the application in your browser.")
            return 0
        if command == "models":
            _print_models(paths)
            return 0
        if command == "load":
            if args.non_interactive and not args.yes:
                raise RuntimeError("Non-interactive model import requires --yes.")

            def confirm_import(artifact: HuggingFaceArtifact, model_id: str) -> bool:
                print("External model import (not tested by Knemora)")
                print(f"Repository: {artifact.repository}")
                print(f"Artifact:   {artifact.filename}")
                print(f"Size:       {artifact.size_bytes / 1_000_000_000:.2f} GB")
                print(f"Knemora ID: {model_id}")
                print(f"License:    {artifact.license_reference}")
                if args.yes:
                    return True
                if not interactive:
                    return False
                answer = input("Import this custom GGUF? [y/N] ").strip().casefold()
                return answer in {"y", "yes"}

            model = ModelImporter(paths.models, ModelRegistry(paths.model_registry)).import_model(
                args.model, alias=args.id, confirm=confirm_import
            )
            print("Custom model imported and registered successfully.")
            print(f"ID:        {model.id}")
            print(f"Size:      {model.size_bytes / 1_000_000_000:.2f} GB")
            print("Status:    Custom / not tested by Knemora")
            print(f"Runtime:   {model.runtime} (compatibility {model.compatibility_status})")
            print("Runtime memory may exceed the GGUF file size.")
            print(f"Select it explicitly with: ./knemora setup --model {model.id}")
            return 0
        if command == "setup":
            if args.non_interactive and not args.yes:
                raise RuntimeError("Non-interactive setup requires --yes.")
            SetupManager(paths, platform).run(
                model_id=args.model,
                context_tokens=args.context_tokens,
            )
            return 0
        if command == "migrate-postgresql":
            api_directory = paths.repository / "apps/api"
            backup_root = (args.backup_dir or paths.repository / "backups").resolve()
            migrated = subprocess.run(
                [
                    str(api_directory / ".venv/bin/python"),
                    "-m",
                    "knemora_bootstrap.postgresql_migration",
                    "--source-url",
                    args.source_url,
                    "--target",
                    str(paths.database),
                    "--api-directory",
                    str(api_directory),
                    "--backup-root",
                    str(backup_root),
                ],
                cwd=api_directory,
                capture_output=True,
                text=True,
                check=False,
            )
            if migrated.returncode:
                detail = migrated.stderr.strip() or migrated.stdout.strip()
                raise RuntimeError(f"PostgreSQL migration failed: {detail}")
            try:
                result = json.loads(migrated.stdout)
                row_counts = result["row_counts"]
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError("PostgreSQL migration returned an invalid result.") from exc
            update_repository_database_url(paths, f"sqlite+pysqlite:///{paths.database}")
            if result["already_migrated"]:
                print("PostgreSQL data was already migrated and revalidated successfully.")
            else:
                print("PostgreSQL migration completed and validated successfully.")
            print(f"SQLite database: {result['target']}")
            print(f"Source backup:   {result['backup_directory']}")
            print(f"Rows migrated:   {sum(int(value) for value in row_counts.values())}")
            print(
                "The PostgreSQL source was not modified. "
                "Start Knemora normally with ./knemora start."
            )
            return 0
        if command == "model":
            if args.model_command == "info":
                _print_model_info(paths, args.model_id)
                return 0
            if args.model_command == "remove":
                if args.non_interactive and not args.yes:
                    raise RuntimeError("Non-interactive model removal requires --yes.")
                model = _validate_model_removal(paths, args.model_id)
                local_data_exists = any(path.exists() for path in _removal_paths(paths, model))
                if args.scope == "registry" and model.id == DEFAULT_MODEL_ID:
                    raise RuntimeError(
                        f"The required default model definition {DEFAULT_MODEL_ID!r} "
                        "cannot be removed."
                    )
                if args.scope == "registry" and local_data_exists:
                    raise RuntimeError(
                        f"Model {model.id!r} still has local artifact data.\n\n"
                        "Run these commands in order:\n"
                        f"  ./knemora model remove {model.id}\n"
                        f"  ./knemora model remove {model.id} registry"
                    )
                if args.scope is None and not local_data_exists:
                    print(
                        f"Model {model.id!r} has no local artifact data to remove; "
                        "its registry entry remains available."
                    )
                    print(
                        "To remove its registry definition, run:\n"
                        f"  ./knemora model remove {model.id} registry"
                    )
                    return 0
                approved = args.yes
                if interactive and not approved:
                    if args.scope == "registry":
                        prompt = (
                            f"Remove registry definition for {model.id!r}? The model will no "
                            "longer appear in ./knemora models. [y/N] "
                        )
                    else:
                        prompt = (
                            f"Remove local artifact data for {model.id!r}? "
                            "Its registry entry will remain. [y/N] "
                        )
                    answer = input(prompt).strip().casefold()
                    approved = answer in {"y", "yes"}
                if not approved:
                    raise RuntimeError("Model removal requires confirmation; rerun with --yes.")
                if args.scope == "registry":
                    _remove_registry_definition(paths, args.model_id)
                else:
                    _remove_model(paths, args.model_id)
                return 0
        if command in {"delete", "delete-presets"}:
            approved = args.yes
            if interactive and not approved:
                answer = (
                    input(
                        "Delete only the Development preset files and knemora_demo database? [y/N] "
                    )
                    .strip()
                    .casefold()
                )
                approved = answer in {"y", "yes"}
            if not approved:
                raise RuntimeError("Preset deletion requires confirmation; rerun with --yes.")
            _delete_presets(paths, runtime)
            return 0
        if command in {"start", "start-with-presets"}:
            _ensure_setup(
                paths,
                platform,
                model_id="default",
                approved=args.yes or wizard_approved,
            )
            demo = args.with_presets
            created = False
            if demo:
                progress = StartupProgress()
                progress.update(0, f"Checking {paths.demo} for a reusable preset…")
                cached = _preset_files_available(paths)
                progress.update(
                    1,
                    (
                        "Preset files found; verifying the cached database link…"
                        if cached
                        else "No reusable preset found; a new preset will be created…"
                    ),
                )
                runtime.prepare_demo_database()
                progress.update(2, "Development database is ready.")
                created = _seed_demo(paths)
                progress.update(
                    3,
                    (
                        "Development preset created; starting local services…"
                        if created
                        else "Cached Development preset loaded; starting local services…"
                    ),
                )
            runtime.start(
                demo=demo,
                open_apps=False,
                demo_database_prepared=demo,
            )
            if demo:
                progress.update(4, "Database, local model, API, and web app are ready.")
                action = "created" if created else "already available"
                print(f"Development preset {action}: 120 synthetic, connected Wiki pages.")
                print(f"Canonical prompt:\n{CANONICAL_PROMPT}")
            if not args.no_open:
                runtime.open_apps(demo=demo)
            web_default = runtime_environment(paths).get(
                "KNEMORA_WEB_SEARCH_ENABLED", "false"
            ).strip().lower() in {"1", "true", "yes", "on"}
            print(
                f"Direct Web startup default: {'ON' if web_default else 'OFF'} "
                "(adjustable per browser session)"
            )
            print("READY — http://localhost:5173")
            return 0
        if command == "stop":
            runtime.stop()
            return 0
        if command == "restart":
            runtime.restart(open_apps=not args.no_open)
            return 0
        if command == "status":
            statuses = runtime.status()
            for status in statuses:
                print(
                    f"{'running' if status.running else 'stopped':7} {status.name}: {status.detail}"
                )
            return 0 if all(status.running for status in statuses) else 1
        if command == "logs":
            return runtime.show_logs(lines=args.lines, follow=args.follow)
        if command == "doctor":
            return _doctor(paths, platform, runtime)
        raise RuntimeError(f"Unknown command: {command}")
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"Knemora: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
