"""Application-data paths and non-destructive local configuration."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knemora_bootstrap.model_context import ContextPlan, ModelContextError
from knemora_bootstrap.models import ModelError, ModelSpec, get_model

MANAGED_EFFECTIVE_CONTEXT_ORIGIN = "managed-effective"


@dataclass(frozen=True)
class ContextPreference:
    tokens: int
    source: str
    explicit: bool


@dataclass(frozen=True)
class AppPaths:
    repository: Path
    data: Path

    @classmethod
    def discover(cls) -> AppPaths:
        repository = Path(
            os.environ.get("KNEMORA_REPOSITORY_ROOT", Path(__file__).resolve().parents[3])
        ).resolve()
        data = configured_data_path()
        return cls(repository=repository, data=data.resolve())

    @property
    def config(self) -> Path:
        return self.data / "config"

    @property
    def bin(self) -> Path:
        return self.data / "bin"

    @property
    def cache(self) -> Path:
        return self.data / "cache"

    @property
    def python(self) -> Path:
        return self.data / "python"

    @property
    def runtime(self) -> Path:
        return self.data / "runtime"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def models(self) -> Path:
        return self.data / "models"

    @property
    def model_registry(self) -> Path:
        return self.config / "models.json"

    @property
    def backup_configuration(self) -> Path:
        return self.config / "backup.json"

    @property
    def home_descriptor(self) -> Path:
        return self.config / "home.json"

    @property
    def runtime_metadata(self) -> Path:
        return self.config / "runtime.json"

    @property
    def wiki(self) -> Path:
        return self.data / "wiki"

    @property
    def sources(self) -> Path:
        return self.data / "sources"

    @property
    def database_directory(self) -> Path:
        return self.data / "data"

    @property
    def database(self) -> Path:
        return self.database_directory / "knemora.db"

    @property
    def demo_database(self) -> Path:
        return self.demo / "data" / "knemora.db"

    @property
    def demo(self) -> Path:
        return self.data / "demo" / "development"

    def initialize(self) -> None:
        for path in (
            self.bin,
            self.cache,
            self.config,
            self.runtime,
            self.logs,
            self.models,
            self.python,
            self.wiki,
            self.sources,
            self.database_directory,
            self.data / "datasets",
            self.demo,
        ):
            path.mkdir(parents=True, exist_ok=True)


def configured_data_path() -> Path:
    """Return the absolute configured data entry without following its final symlink."""

    configured = Path(os.environ.get("KNEMORA_HOME", Path.home() / ".knemora")).expanduser()
    return Path(os.path.abspath(configured))


def read_env(path: Path) -> dict[str, str]:
    """Read simple dotenv assignments without evaluating shell syntax."""

    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key:
            cleaned = value.strip()
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
                cleaned = cleaned[1:-1]
            values[key] = cleaned
    return values


def ensure_repository_env(paths: AppPaths) -> Path:
    """Create a secure local dotenv or append only missing safe defaults."""

    target = paths.repository / ".env"
    existing = read_env(target)
    password = secrets.token_urlsafe(24)
    defaults = {
        "KNEMORA_PRODUCT_NAME": "Knemora",
        "KNEMORA_PRODUCT_EDITION": "community",
        "KNEMORA_APP_ENV": "development",
        "KNEMORA_API_HOST": "127.0.0.1",
        "KNEMORA_API_PORT": "8000",
        "KNEMORA_WEB_ORIGIN": "http://localhost:5173",
        "KNEMORA_DATABASE_URL": f"sqlite+pysqlite:///{paths.database}",
        "KNEMORA_AUTHENTICATION_REQUIRED": "true",
        "KNEMORA_BOOTSTRAP_ADMIN_EMAIL": "admin@knemora.local",
        "KNEMORA_BOOTSTRAP_ADMIN_NAME": "Knemora Administrator",
        "KNEMORA_BOOTSTRAP_ADMIN_PASSWORD": password,
        "KNEMORA_TRUSTED_HOSTS": "127.0.0.1,localhost",
        "KNEMORA_LLM_BASE_URL": "http://localhost:8080",
        "KNEMORA_LLM_TIMEOUT_SECONDS": "180",
        "KNEMORA_LLM_MAX_OUTPUT_TOKENS": "1024",
        "KNEMORA_LLM_ENABLE_THINKING": "false",
        "KNEMORA_WEB_SEARCH_ENABLED": "false",
        "KNEMORA_WEB_SEARCH_TIMEOUT_SECONDS": "8",
        "KNEMORA_WEB_SEARCH_MAX_RESULTS": "5",
        "KNEMORA_UPDATE_CHECK_ENABLED": "true",
        "KNEMORA_SOURCE_STORE_PATH": str(paths.sources),
        "KNEMORA_KNOWLEDGE_PATH": str(paths.wiki),
        "KNEMORA_KNOWLEDGE_COMPILATION_MAX_OUTPUT_TOKENS": "2048",
        "KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS": "300",
    }
    missing = [(key, value) for key, value in defaults.items() if key not in existing]
    if not missing:
        return target
    prefix = "" if not target.exists() or target.stat().st_size == 0 else "\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "# Managed safe defaults added by ./knemora\n")
        for key, value in missing:
            handle.write(f"{key}={value}\n")
    target.chmod(0o600)
    return target


def _read_model_selection(paths: AppPaths) -> dict[str, Any]:
    try:
        payload = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_model_selection(
    paths: AppPaths,
    model: ModelSpec,
    model_path: Path,
    *,
    plan: ContextPlan,
    explicit_context_tokens: int | None = None,
) -> Path:
    """Update only Knemora-owned runtime selection metadata."""

    paths.config.mkdir(parents=True, exist_ok=True)
    target = paths.config / "model.json"
    temporary = target.with_suffix(".tmp")
    existing = _read_model_selection(paths)
    overrides = existing.get("context_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = {
        str(key): int(value)
        for key, value in overrides.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    if explicit_context_tokens is not None:
        overrides[model.id] = explicit_context_tokens
    previous = existing.get("previous_selection")
    selection_changed = any(
        (
            existing.get("model_id") != model.id,
            existing.get("path") != str(model_path),
            existing.get("context_tokens") != plan.effective_context_tokens,
        )
    )
    if (
        existing.get("model_id")
        and selection_changed
        and not (isinstance(previous, dict) and previous)
    ):
        previous = {
            key: value
            for key, value in existing.items()
            if key not in {"previous_selection", "context_overrides"}
        }
    payload = {
        "model_id": model.id,
        "display_name": model.display_name,
        "provider": model.provider,
        "path": str(model_path),
        "quantization": model.quantization,
        "context_tokens": plan.effective_context_tokens,
        "advertised_context_tokens": plan.advertised_context_tokens,
        "configured_context_tokens": plan.configured_context_tokens,
        "context_mode": "explicit" if plan.explicit else "automatic",
        "context_source": plan.source,
        "context_reason": plan.reason,
        "estimated_memory_bytes": plan.memory.total_bytes,
        "safe_memory_budget_bytes": plan.memory.safe_budget_bytes,
        "memory_estimate_uncertainty": plan.memory.uncertainty,
        "sha256": model.sha256,
        "revision": model.revision,
        "thinking_control": model.thinking_control,
        "context_overrides": overrides,
    }
    if isinstance(previous, dict) and previous:
        payload["previous_selection"] = previous
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)
    return target


def context_override_for(paths: AppPaths, model_id: str) -> int | None:
    overrides = _read_model_selection(paths).get("context_overrides", {})
    if not isinstance(overrides, dict):
        return None
    value = overrides.get(model_id)
    return value if isinstance(value, int) else None


def resolve_context_preference(
    paths: AppPaths,
    model: ModelSpec,
    *,
    cli_context_tokens: int | None = None,
) -> ContextPreference:
    """Resolve user intent without mistaking a managed effective value for an override."""

    if cli_context_tokens is not None:
        return ContextPreference(
            cli_context_tokens,
            "explicit setup --context-tokens override",
            True,
        )

    persisted_context = context_override_for(paths, model.id)
    if persisted_context is not None:
        return ContextPreference(
            persisted_context,
            "persisted per-model user override",
            True,
        )

    repository_environment = read_env(paths.repository / ".env")
    raw_environment_context = repository_environment.get("KNEMORA_LLM_CONTEXT_TOKENS")
    if raw_environment_context is None and (
        os.environ.get("KNEMORA_LLM_CONTEXT_ORIGIN") != MANAGED_EFFECTIVE_CONTEXT_ORIGIN
    ):
        raw_environment_context = os.environ.get("KNEMORA_LLM_CONTEXT_TOKENS")
    if raw_environment_context is not None:
        try:
            environment_context = int(raw_environment_context)
        except ValueError as exc:
            raise ModelContextError(
                "KNEMORA_LLM_CONTEXT_TOKENS must be a whole number of tokens."
            ) from exc
        return ContextPreference(
            environment_context,
            "KNEMORA_LLM_CONTEXT_TOKENS environment override",
            True,
        )

    return ContextPreference(
        model.context_tokens,
        "curated model profile" if not model.is_user_import else "GGUF-derived safe profile",
        False,
    )


def rollback_model_selection(paths: AppPaths) -> bool:
    """Restore the prior selection after a failed runtime start, if one was recorded."""

    current = _read_model_selection(paths)
    previous = current.get("previous_selection")
    if not isinstance(previous, dict) or not previous:
        return False
    previous = dict(previous)
    previous["context_overrides"] = current.get("context_overrides", {})
    target = paths.config / "model.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)
    state_path = paths.config / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        state = None
    if isinstance(state, dict) and isinstance(previous.get("model_id"), str):
        state["model_id"] = previous["model_id"]
        state_temporary = state_path.with_suffix(".tmp")
        state_temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        state_temporary.chmod(0o600)
        state_temporary.replace(state_path)
    return True


def confirm_model_selection(paths: AppPaths) -> None:
    """Clear one-shot rollback metadata after the selected model is healthy."""

    current = _read_model_selection(paths)
    if "previous_selection" not in current:
        return
    current.pop("previous_selection", None)
    target = paths.config / "model.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)


def runtime_environment(
    paths: AppPaths,
    *,
    demo: bool = False,
) -> dict[str, str]:
    """Build child-process configuration without printing secret values."""

    values = {**os.environ, **read_env(paths.repository / ".env")}
    model_file = paths.config / "model.json"
    if model_file.is_file():
        model = json.loads(model_file.read_text(encoding="utf-8"))
        selected_model: ModelSpec | None = None
        with suppress(KeyError, ModelError):
            selected_model = get_model(str(model["model_id"]), paths.model_registry)
        revision = model.get("revision") or (
            selected_model.revision if selected_model is not None else None
        )
        model_values = {
            "KNEMORA_MODEL_PATH": str(model["path"]),
            "KNEMORA_LLM_MODEL": str(model["model_id"]),
            "KNEMORA_LLM_DISPLAY_NAME": str(
                model.get("display_name")
                or (
                    selected_model.display_name if selected_model is not None else model["model_id"]
                )
            ),
            "KNEMORA_LLM_THINKING_CONTROL": str(
                model.get("thinking_control")
                or (selected_model.thinking_control if selected_model is not None else "unverified")
            ),
            "KNEMORA_LLM_QUANTIZATION": str(model["quantization"]),
            "KNEMORA_LLM_CONTEXT_TOKENS": str(model["context_tokens"]),
            "KNEMORA_LLM_CONTEXT_ORIGIN": MANAGED_EFFECTIVE_CONTEXT_ORIGIN,
            "KNEMORA_LLM_CONTEXT_SOURCE": str(model.get("context_source", "legacy selection")),
        }
        if revision:
            model_values["KNEMORA_LLM_REVISION"] = str(revision)
        values.update(model_values)
    values["KNEMORA_RUNTIME_DIR"] = str(paths.runtime)
    values["KNEMORA_LOG_DIR"] = str(paths.logs)
    values["KNEMORA_HOME"] = str(paths.data)
    values["KNEMORA_HOME_COMPATIBILITY_REQUIRED"] = "true"
    if demo:
        values["KNEMORA_DEMO_MODE"] = "true"
        values["KNEMORA_DEMO_PRESET"] = "development"
        values["KNEMORA_DEFAULT_USER_EMAIL"] = values.get(
            "KNEMORA_BOOTSTRAP_ADMIN_EMAIL", "admin@knemora.local"
        )
        values["KNEMORA_DEFAULT_USER_NAME"] = values.get(
            "KNEMORA_BOOTSTRAP_ADMIN_NAME", "Knemora Administrator"
        )
        values["KNEMORA_SOURCE_STORE_PATH"] = str(paths.demo / "sources")
        values["KNEMORA_KNOWLEDGE_PATH"] = str(paths.demo / "knowledge")
        values["KNEMORA_DATABASE_URL"] = f"sqlite+pysqlite:///{paths.demo_database}"
    return values


def update_repository_database_url(paths: AppPaths, database_url: str) -> None:
    """Atomically update only the active database URL in the repository dotenv file."""

    target = paths.repository / ".env"
    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    replacement = f"KNEMORA_DATABASE_URL={database_url}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().removeprefix("export ").startswith("KNEMORA_DATABASE_URL="):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        if updated and updated[-1]:
            updated.append("")
        updated.extend(["# Active relational storage", replacement])
    temporary = target.with_suffix(".env.tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)


def mark_setup_complete(paths: AppPaths, model: ModelSpec) -> None:
    state = paths.config / "state.json"
    temporary = state.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"setup_complete": True, "model_id": model.id}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(state)


def setup_is_complete(paths: AppPaths) -> bool:
    try:
        payload = json.loads((paths.config / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("setup_complete") is True


def default_backup_path() -> Path:
    """Return the user-visible portable-backup location."""

    return (Path.home() / "Documents" / "Knemora" / "Backups").resolve()


def read_backup_path(paths: AppPaths) -> Path:
    """Read the persisted backup destination, falling back to the portable default."""

    try:
        payload = json.loads(paths.backup_configuration.read_text(encoding="utf-8"))
        raw_path = payload["path"]
        if payload.get("version") != 1 or not isinstance(raw_path, str):
            raise ValueError("unsupported backup configuration")
    except FileNotFoundError:
        return default_backup_path()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Backup configuration is invalid: {paths.backup_configuration}: {exc}"
        ) from exc
    return Path(raw_path).expanduser().resolve()


def write_backup_path(paths: AppPaths, destination: Path) -> Path:
    """Persist one validated absolute backup destination atomically."""

    resolved = destination.expanduser().resolve()
    if resolved == paths.data or resolved.is_relative_to(paths.data):
        raise RuntimeError(f"Backup destination must be outside Knemora data: {paths.data}")
    if len(resolved.parts) >= 3 and resolved.parts[:2] == ("/", "Volumes"):
        volume = Path(*resolved.parts[:3])
        if not volume.is_dir():
            raise RuntimeError(f"Backup volume is unavailable: {volume}")
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise RuntimeError(f"Backup destination is not a directory: {resolved}")
        paths.config.mkdir(parents=True, exist_ok=True)
        temporary = paths.backup_configuration.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "path": str(resolved)}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(paths.backup_configuration)
    except OSError as exc:
        raise RuntimeError(f"Could not use backup destination {resolved}: {exc}") from exc
    return resolved
