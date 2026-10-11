"""Trusted manifest-driven installation and resolution of native runtimes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

from knemora_bootstrap.configuration import AppPaths, read_env

RUNTIME_METADATA_FORMAT_VERSION = 1
MAX_ARCHIVE_ENTRIES = 500
MAX_EXPANDED_BYTES = 1_000_000_000
DOWNLOAD_TIMEOUT_SECONDS = 30
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "releases.astral.sh",
    }
)


class NativeRuntimeError(RuntimeError):
    """A managed native runtime was unsupported, invalid, or unavailable."""


@dataclass(frozen=True)
class RuntimeTarget:
    component: str
    version: str
    source: str
    platform: str
    architecture: str
    backend: str
    status: str
    archive_name: str | None = None
    archive_url: str | None = None
    archive_size: int | None = None
    archive_sha256: str | None = None
    archive_root: str | None = None
    executable: str | None = None
    version_markers: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return f"{self.component}-{self.version}-{self.platform}-{self.architecture}-{self.backend}"


@dataclass(frozen=True)
class RuntimeSelection:
    source: str
    executable: Path
    component: str
    version: str
    platform: str
    architecture: str
    backend: str
    compatible: bool
    integrity: str
    installation_id: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _platform_key(system: str | None = None) -> str:
    value = system or platform.system()
    return {"Darwin": "darwin", "Windows": "win32", "Linux": "linux"}.get(value, value.casefold())


def _architecture_key(machine: str | None = None) -> str:
    value = (machine or platform.machine()).casefold()
    return {"aarch64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(value, value)


def load_runtime_manifest(repository: Path) -> dict[str, Any]:
    path = repository / "infrastructure" / "runtime-manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NativeRuntimeError(f"Managed runtime manifest is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("formatVersion") != 1:
        raise NativeRuntimeError(f"Managed runtime manifest format is unsupported: {path}")
    return payload


def select_runtime_target(
    manifest: Mapping[str, Any],
    component: str,
    *,
    system: str | None = None,
    machine: str | None = None,
    backend: str,
) -> RuntimeTarget:
    component_payload = manifest.get(component)
    if not isinstance(component_payload, dict):
        raise NativeRuntimeError(f"Runtime manifest has no component {component!r}.")
    platform_name = _platform_key(system)
    architecture = _architecture_key(machine)
    targets = component_payload.get("targets")
    if not isinstance(targets, list):
        raise NativeRuntimeError(f"Runtime component {component!r} has no target descriptors.")
    item = next(
        (
            candidate
            for candidate in targets
            if isinstance(candidate, dict)
            and candidate.get("platform") == platform_name
            and candidate.get("architecture") == architecture
            and candidate.get("backend") == backend
        ),
        None,
    )
    if item is None:
        raise NativeRuntimeError(
            f"{component} has no descriptor for {platform_name}/{architecture}/{backend}."
        )
    status = str(item.get("status", "invalid"))
    archive_value = item.get("archive")
    archive = cast(dict[str, Any], archive_value) if isinstance(archive_value, dict) else {}
    target = RuntimeTarget(
        component=component,
        version=str(component_payload.get("version", "")),
        source=str(component_payload.get("source", "")),
        platform=platform_name,
        architecture=architecture,
        backend=backend,
        status=status,
        archive_name=archive.get("name") if isinstance(archive.get("name"), str) else None,
        archive_url=archive.get("url") if isinstance(archive.get("url"), str) else None,
        archive_size=archive.get("size") if isinstance(archive.get("size"), int) else None,
        archive_sha256=(archive.get("sha256") if isinstance(archive.get("sha256"), str) else None),
        archive_root=archive.get("root") if isinstance(archive.get("root"), str) else None,
        executable=item.get("executable") if isinstance(item.get("executable"), str) else None,
        version_markers=tuple(
            marker for marker in item.get("versionMarkers", ()) if isinstance(marker, str)
        ),
    )
    if target.status != "supported":
        raise NativeRuntimeError(
            f"{component} on {platform_name}/{architecture}/{backend} is not supported yet. "
            "macOS Apple Silicon with Metal is the only Milestone 08.5 application target."
        )
    if not all(
        (
            target.version,
            target.source,
            target.archive_name,
            target.archive_url,
            target.archive_size,
            target.archive_sha256,
            target.archive_root,
            target.executable,
        )
    ):
        raise NativeRuntimeError(f"Supported descriptor {target.identity} is incomplete.")
    return target


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise NativeRuntimeError(f"Refusing runtime redirect to {parsed.netloc}.")
        return super().redirect_request(request, fp, code, msg, headers, new_url)


class NativeRuntimeManager:
    """Install, validate, activate, and resolve llama.cpp from one shared contract."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.manifest = load_runtime_manifest(paths.repository)

    def target(self) -> RuntimeTarget:
        self._reject_rosetta()
        return select_runtime_target(self.manifest, "llamaCpp", backend="metal")

    def ensure_llama(self) -> RuntimeSelection:
        override = self._operator_override()
        if override is not None:
            print(f"Preserving configured external llama-server override: {override.executable}")
            return override
        target = self.target()
        current = self._managed_selection(target, verify_inventory=True)
        if current is not None:
            return current
        if self._managed_processes_active():
            raise NativeRuntimeError(
                "Managed services are running; stop Knemora before installing or activating "
                "a native runtime."
            )
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        with self._operation_lock():
            current = self._managed_selection(target, verify_inventory=True)
            if current is not None:
                return current
            return self._install(target)

    def resolve_llama(self, *, validate_capabilities: bool = False) -> RuntimeSelection:
        override = self._operator_override()
        if override is not None:
            return override
        target = self.target()
        managed = self._managed_selection(target, verify_inventory=validate_capabilities)
        if managed is not None:
            return managed
        legacy = self._legacy_override()
        if legacy is not None:
            return legacy
        raise NativeRuntimeError(
            "No verified llama.cpp runtime is active. Run ./knemora setup. Knemora will not "
            "silently use an arbitrary PATH executable."
        )

    def inspect(self) -> RuntimeSelection | None:
        try:
            return self.resolve_llama(validate_capabilities=False)
        except NativeRuntimeError:
            return None

    def _install(self, target: RuntimeTarget) -> RuntimeSelection:
        assert target.archive_name
        assert target.archive_url
        assert target.archive_size
        assert target.archive_sha256
        assert target.archive_root
        assert target.executable
        install_parent = self.paths.bin / "llama.cpp" / target.version
        final = install_parent / f"{target.platform}-{target.architecture}-{target.backend}"
        archive = self.paths.cache / "downloads" / target.archive_name
        staging_parent = self.paths.cache / "runtime-staging"
        for path in (install_parent, archive.parent, staging_parent):
            self._safe_directory(path)
            path.mkdir(parents=True, exist_ok=True)
        required = target.archive_size * 4
        free = shutil.disk_usage(self.paths.data).free
        if free < required:
            raise NativeRuntimeError(
                f"Managed llama.cpp installation needs at least {required / 1_000_000:.0f} MB "
                f"free for download and staging; found {free / 1_000_000:.0f} MB."
            )
        if not self._archive_valid(archive, target):
            self._download(target, archive)
        staging = Path(tempfile.mkdtemp(prefix="llama-install-", dir=staging_parent))
        try:
            self._extract_archive(archive, staging)
            extracted = staging / target.archive_root
            if not extracted.is_dir():
                raise NativeRuntimeError(
                    f"Runtime archive omitted its expected root {target.archive_root!r}."
                )
            self._validate_payload(extracted, target)
            inventory = self._inventory(extracted)
            prepared = install_parent / f".{final.name}.prepared-{uuid.uuid4().hex[:10]}"
            if prepared.exists():
                shutil.rmtree(prepared)
            extracted.replace(prepared)
            previous: Path | None = None
            if final.exists():
                previous = install_parent / f".{final.name}.previous-{int(time.time())}"
                final.replace(previous)
            try:
                prepared.replace(final)
                self._write_active_metadata(target, final, inventory, previous)
            except Exception:
                if final.exists():
                    shutil.rmtree(final)
                if previous and previous.exists():
                    previous.replace(final)
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        selection = self._managed_selection(target, verify_inventory=True)
        if selection is None:
            raise NativeRuntimeError(
                "Managed llama.cpp activation did not produce a resolvable installation."
            )
        return selection

    def _download(self, target: RuntimeTarget, destination: Path) -> None:
        assert target.archive_url
        assert target.archive_size
        assert target.archive_sha256
        parsed = urlparse(target.archive_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise NativeRuntimeError(f"Refusing unapproved runtime source: {target.archive_url}")
        partial = destination.with_suffix(destination.suffix + ".partial")
        partial.unlink(missing_ok=True)
        opener = urllib.request.build_opener(_RestrictedRedirectHandler())
        request = urllib.request.Request(
            target.archive_url,
            headers={"User-Agent": "Knemora/0.1.0-alpha", "Accept-Encoding": "identity"},
        )
        received = 0
        digest = hashlib.sha256()
        try:
            with (
                opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
                partial.open("wb") as handle,
            ):
                declared = response.headers.get("Content-Length")
                if declared and int(declared) != target.archive_size:
                    raise NativeRuntimeError(
                        "Runtime archive declared "
                        f"{declared} bytes; expected {target.archive_size}."
                    )
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > target.archive_size:
                        raise NativeRuntimeError("Runtime archive exceeded its pinned size.")
                    handle.write(chunk)
                    digest.update(chunk)
                    percent = int(received * 100 / target.archive_size)
                    print(f"\rDownloading managed llama.cpp… {percent:3d}%", end="", flush=True)
            print()
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            partial.unlink(missing_ok=True)
            raise NativeRuntimeError(
                f"Runtime download failed; the active installation was unchanged: {exc}"
            ) from exc
        if received != target.archive_size or digest.hexdigest() != target.archive_sha256:
            partial.unlink(missing_ok=True)
            raise NativeRuntimeError(
                "Runtime archive size or SHA-256 did not match the source-controlled manifest."
            )
        partial.replace(destination)

    @staticmethod
    def _extract_archive(archive: Path, destination: Path) -> None:
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                members = bundle.getmembers()
                if not 0 < len(members) <= MAX_ARCHIVE_ENTRIES:
                    raise NativeRuntimeError("Runtime archive has an unsafe entry count.")
                expanded = 0
                seen: set[str] = set()
                symbolic_links: list[tarfile.TarInfo] = []
                archive_names = {item.name for item in members}
                for member in members:
                    pure = PurePosixPath(member.name)
                    if (
                        pure.is_absolute()
                        or not pure.parts
                        or any(part in {"", ".", ".."} for part in pure.parts)
                        or "\\" in member.name
                    ):
                        raise NativeRuntimeError(
                            f"Runtime archive contains an unsafe path: {member.name!r}"
                        )
                    if member.name in seen:
                        raise NativeRuntimeError(
                            f"Runtime archive contains a duplicate path: {member.name!r}"
                        )
                    seen.add(member.name)
                    if member.islnk() or not (member.isdir() or member.isfile() or member.issym()):
                        raise NativeRuntimeError(
                            f"Runtime archive contains an unsupported entry: {member.name!r}"
                        )
                    if member.issym():
                        link = PurePosixPath(member.linkname)
                        linked_name = pure.parent / link
                        if (
                            link.is_absolute()
                            or len(link.parts) != 1
                            or link.parts[0] in {"", ".", ".."}
                            or linked_name.as_posix() not in archive_names
                        ):
                            raise NativeRuntimeError(
                                f"Runtime archive contains an unsafe link: {member.name!r}"
                            )
                        symbolic_links.append(member)
                    expanded += member.size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise NativeRuntimeError("Runtime archive expands beyond the safety limit.")
                bundle.extractall(destination, filter="data")
                # Upstream dylib aliases are same-directory relative links. Materialize them as
                # regular files so the activated tree never depends on links at runtime.
                for member in symbolic_links:
                    link_path = destination.joinpath(*PurePosixPath(member.name).parts)
                    resolved = link_path.resolve(strict=True)
                    resolved.relative_to(destination.resolve())
                    if not resolved.is_file():
                        raise NativeRuntimeError(
                            f"Runtime archive link does not resolve to a file: {member.name!r}"
                        )
                    link_path.unlink()
                    shutil.copy2(resolved, link_path)
        except (OSError, tarfile.TarError) as exc:
            raise NativeRuntimeError(f"Runtime archive extraction failed: {exc}") from exc

    def _validate_payload(self, root: Path, target: RuntimeTarget) -> None:
        assert target.executable
        server = root / target.executable
        if not server.is_file() or server.is_symlink():
            raise NativeRuntimeError(f"Runtime payload omitted {target.executable}.")
        server.chmod(server.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not (root / "LICENSE").is_file():
            raise NativeRuntimeError("Runtime payload omitted the upstream LICENSE.")
        file_result = subprocess.run(
            ["/usr/bin/file", str(server)], capture_output=True, text=True, timeout=10, check=False
        )
        if file_result.returncode or "arm64" not in file_result.stdout:
            raise NativeRuntimeError(
                f"Runtime executable architecture is incompatible: {file_result.stdout.strip()}"
            )
        version = subprocess.run(
            [str(server), "--version"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = f"{version.stdout}\n{version.stderr}"
        if version.returncode or any(marker not in output for marker in target.version_markers):
            raise NativeRuntimeError(
                f"Runtime version/capability check failed for {target.identity}: {output.strip()}"
            )
        help_result = subprocess.run(
            [str(server), "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
        required_flags = (
            "--n-gpu-layers",
            "--cache-type-k",
            "--cache-type-v",
            "--batch-size",
            "--ubatch-size",
            "--metrics",
        )
        if help_result.returncode or any(flag not in help_text for flag in required_flags):
            raise NativeRuntimeError("Runtime does not provide Knemora's required server flags.")
        libraries = subprocess.run(
            ["/usr/bin/otool", "-L", str(server)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if libraries.returncode:
            raise NativeRuntimeError(f"Could not inspect runtime dependencies: {libraries.stderr}")
        forbidden = ("/opt/homebrew", "/usr/local/Homebrew", "/Cellar/")
        if any(prefix in libraries.stdout for prefix in forbidden):
            raise NativeRuntimeError(
                "Managed llama-server still links to a Homebrew installation; activation refused."
            )

    @staticmethod
    def _inventory(root: Path) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise NativeRuntimeError(f"Runtime payload contains a symbolic link: {path}")
            if path.is_file():
                inventory.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
        return inventory

    def _write_active_metadata(
        self,
        target: RuntimeTarget,
        root: Path,
        inventory: list[dict[str, Any]],
        previous: Path | None,
    ) -> None:
        metadata = self._read_metadata(allow_missing=True)
        components = metadata.setdefault("components", {})
        relative_root = root.relative_to(self.paths.data).as_posix()
        components["llama.cpp"] = {
            "activeInstallationId": target.identity,
            "previousInstallation": (
                previous.relative_to(self.paths.data).as_posix() if previous else None
            ),
            "installations": {
                target.identity: {
                    "component": target.component,
                    "version": target.version,
                    "upstreamRelease": target.source,
                    "platform": target.platform,
                    "architecture": target.architecture,
                    "backend": target.backend,
                    "archive": target.archive_name,
                    "archiveSize": target.archive_size,
                    "expectedSha256": target.archive_sha256,
                    "verifiedSha256": target.archive_sha256,
                    "rootRelativePath": relative_root,
                    "executableRelativePath": target.executable,
                    "verifiedAt": _now(),
                    "activatedAt": _now(),
                    "files": inventory,
                }
            },
        }
        _atomic_json(self.paths.runtime_metadata, metadata)

    def _managed_selection(
        self, target: RuntimeTarget, *, verify_inventory: bool
    ) -> RuntimeSelection | None:
        try:
            metadata = self._read_metadata()
            component = metadata["components"]["llama.cpp"]
            identity = component["activeInstallationId"]
            installation = component["installations"][identity]
            if identity != target.identity:
                return None
            root = self._contained_relative(str(installation["rootRelativePath"]))
            executable_relative = PurePosixPath(str(installation["executableRelativePath"]))
            if executable_relative.is_absolute() or ".." in executable_relative.parts:
                raise NativeRuntimeError("Runtime metadata contains an unsafe executable path.")
            executable = root.joinpath(*executable_relative.parts)
            if not executable.is_file() or not os.access(executable, os.X_OK):
                return None
            integrity = "metadata+executable"
            if verify_inventory:
                files = installation.get("files")
                if not isinstance(files, list) or not files:
                    return None
                for entry in files:
                    if not isinstance(entry, dict):
                        return None
                    path = self._contained_relative(
                        f"{installation['rootRelativePath']}/{entry.get('path', '')}"
                    )
                    if (
                        not path.is_file()
                        or path.stat().st_size != entry.get("size")
                        or _sha256(path) != entry.get("sha256")
                    ):
                        return None
                self._validate_payload(root, target)
                integrity = "verified-inventory+capabilities"
            return RuntimeSelection(
                source="managed",
                executable=executable.resolve(),
                component="llama.cpp",
                version=target.version,
                platform=target.platform,
                architecture=target.architecture,
                backend=target.backend,
                compatible=True,
                integrity=integrity,
                installation_id=identity,
            )
        except (KeyError, OSError, TypeError, ValueError, NativeRuntimeError):
            return None

    def _operator_override(self) -> RuntimeSelection | None:
        environment = {**os.environ, **read_env(self.paths.repository / ".env")}
        configured = environment.get("LLAMA_SERVER_BIN")
        if not configured:
            return None
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise NativeRuntimeError("LLAMA_SERVER_BIN must be an absolute path.")
        resolved = path.resolve()
        self._validate_external(resolved)
        return RuntimeSelection(
            source="operator-override",
            executable=resolved,
            component="llama.cpp",
            version="external",
            platform=_platform_key(),
            architecture=_architecture_key(),
            backend="operator-configured",
            compatible=True,
            integrity="version-validated-external",
        )

    def _legacy_override(self) -> RuntimeSelection | None:
        environment = {**os.environ, **read_env(self.paths.repository / ".env")}
        root = environment.get("LLAMA_CPP_DIR")
        if not root:
            return None
        candidate = Path(root).expanduser().resolve() / "build" / "bin" / "llama-server"
        self._validate_external(candidate)
        return RuntimeSelection(
            source="legacy-operator-override",
            executable=candidate,
            component="llama.cpp",
            version="external",
            platform=_platform_key(),
            architecture=_architecture_key(),
            backend="operator-configured",
            compatible=True,
            integrity="version-validated-external",
        )

    @staticmethod
    def _validate_external(path: Path) -> None:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise NativeRuntimeError(f"Configured llama-server is not executable: {path}")
        try:
            result = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, timeout=20, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeRuntimeError(
                f"Configured llama-server could not be validated: {exc}"
            ) from exc
        if result.returncode:
            raise NativeRuntimeError(f"Configured llama-server failed --version: {path}")

    def _read_metadata(self, *, allow_missing: bool = False) -> dict[str, Any]:
        try:
            payload = json.loads(self.paths.runtime_metadata.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if allow_missing:
                return {"formatVersion": RUNTIME_METADATA_FORMAT_VERSION, "components": {}}
            raise
        if not isinstance(payload, dict) or payload.get("formatVersion") != 1:
            raise NativeRuntimeError(
                f"Runtime metadata format is unsupported: {self.paths.runtime_metadata}"
            )
        if not isinstance(payload.get("components"), dict):
            raise NativeRuntimeError("Runtime metadata components are invalid.")
        return payload

    def _contained_relative(self, value: str) -> Path:
        pure = PurePosixPath(value)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts:
            raise NativeRuntimeError(f"Runtime metadata path is unsafe: {value!r}")
        candidate = self.paths.data.joinpath(*pure.parts)
        self._safe_directory(candidate.parent)
        try:
            candidate.resolve(strict=False).relative_to(self.paths.data.resolve())
        except ValueError as exc:
            raise NativeRuntimeError(
                f"Runtime metadata path escapes KNEMORA_HOME: {value}"
            ) from exc
        return candidate

    def _safe_directory(self, path: Path) -> None:
        try:
            relative = path.resolve(strict=False).relative_to(self.paths.data.resolve())
        except ValueError as exc:
            raise NativeRuntimeError(f"Managed runtime path escapes KNEMORA_HOME: {path}") from exc
        current = self.paths.data.resolve()
        for part in relative.parts:
            current /= part
            if current.exists() and current.is_symlink():
                raise NativeRuntimeError(f"Managed runtime path traverses a symlink: {current}")

    @staticmethod
    def _archive_valid(path: Path, target: RuntimeTarget) -> bool:
        return bool(
            path.is_file()
            and path.stat().st_size == target.archive_size
            and _sha256(path) == target.archive_sha256
        )

    def _managed_processes_active(self) -> bool:
        for name in ("llm", "api", "web"):
            pid_file = self.paths.runtime / f"{name}.pid"
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.kill(pid, 0)
                return True
            except (OSError, ValueError):
                continue
        return False

    @staticmethod
    def _reject_rosetta() -> None:
        if platform.system() != "Darwin":
            return
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            raise NativeRuntimeError(
                "Knemora is running under Rosetta. Launch the native arm64 Node.js build; "
                "x64 runtime substitution is not allowed."
            )

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        lock = self.paths.runtime / "home-operation.lock"
        with lock.open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise NativeRuntimeError(
                    "Another setup, restore, migration, or runtime activation is in progress."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
