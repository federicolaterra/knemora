"""Platform detection and the implemented macOS Apple Silicon adapter."""

from __future__ import annotations

import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class PlatformError(RuntimeError):
    """The current platform is unsupported or missing a required prerequisite."""


@dataclass(frozen=True)
class Hardware:
    os: str
    architecture: str
    memory_gb: float | None
    accelerator: str
    unified_memory_gb: float | None
    available_memory_gb: float | None = None


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


class PlatformAdapter(ABC):
    """Boundary for host detection and presentation launch behavior."""

    @abstractmethod
    def hardware(self) -> Hardware: ...

    @abstractmethod
    def check_prerequisites(self) -> list[str]: ...

    @abstractmethod
    def open_url(self, url: str) -> None: ...


class MacOSAdapter(PlatformAdapter):
    """Supported bootstrap implementation for macOS on Apple Silicon."""

    def hardware(self) -> Hardware:
        memory: float | None = None
        available: float | None = None
        with suppress(OSError, ValueError, subprocess.CalledProcessError):
            memory = int(_run(["sysctl", "-n", "hw.memsize"]).stdout.strip()) / 1024**3
        with suppress(OSError, ValueError, subprocess.CalledProcessError):
            output = _run(["vm_stat"]).stdout
            page_size_match = next(
                (part for part in output.splitlines()[0].split() if part.isdigit()),
                "4096",
            )
            page_size = int(page_size_match)
            pages: dict[str, int] = {}
            for line in output.splitlines()[1:]:
                if ":" not in line:
                    continue
                name, raw = line.split(":", 1)
                pages[name.strip()] = int(raw.strip().rstrip("."))
            available_pages = sum(
                pages.get(name, 0)
                for name in (
                    "Pages free",
                    "Pages inactive",
                    "Pages speculative",
                    "Pages purgeable",
                )
            )
            available = available_pages * page_size / 1024**3
        architecture = platform.machine()
        return Hardware(
            os="macOS",
            architecture=architecture,
            memory_gb=memory,
            accelerator="Apple Metal" if architecture == "arm64" else "unsupported",
            unified_memory_gb=memory if architecture == "arm64" else None,
            available_memory_gb=available,
        )

    def check_prerequisites(self) -> list[str]:
        failures: list[str] = []
        if platform.machine() != "arm64":
            failures.append(
                "Knemora zero-config setup currently supports macOS Apple Silicon only; "
                "use docs/open-source/installation.md for manual installation."
            )
        if shutil.which("node") is None:
            failures.append("Node.js 24+ is required: https://nodejs.org/")
        if shutil.which("npm") is None:
            failures.append("npm is required with Node.js: https://nodejs.org/")
        return failures

    def prepare_dependencies(self) -> None:
        """Compatibility no-op; managed components are installed by their owning services."""

    def llama_server(self) -> Path | None:
        """Deprecated compatibility hook; use NativeRuntimeManager for runtime selection."""
        return None

    def open_url(self, url: str) -> None:
        subprocess.run(["open", url], check=False)


class UnsupportedPlatformAdapter(PlatformAdapter):
    """Honest extension boundary for platforms not implemented in Milestone 08.1."""

    def hardware(self) -> Hardware:
        return Hardware(platform.system(), platform.machine(), None, "unknown", None)

    def check_prerequisites(self) -> list[str]:
        return [
            "Zero-config bootstrap is not implemented for this platform. Follow the manual "
            "installation guide in docs/open-source/installation.md."
        ]

    def open_url(self, url: str) -> None:
        del url


def detect_platform() -> PlatformAdapter:
    return MacOSAdapter() if platform.system() == "Darwin" else UnsupportedPlatformAdapter()
