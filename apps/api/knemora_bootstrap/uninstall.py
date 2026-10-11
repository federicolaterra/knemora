"""Guarded removal of one Knemora checkout and its configured application data."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from knemora_bootstrap.configuration import AppPaths, configured_data_path
from knemora_bootstrap.runtime import ServiceStatus


class ManagedRuntime(Protocol):
    def status(self) -> tuple[ServiceStatus, ...]: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class UninstallPlan:
    repository: Path
    data: Path
    data_entry: Path
    preserve_data: bool
    data_entry_is_symlink: bool

    @property
    def repository_contains_data(self) -> bool:
        return self.data == self.repository or self.data.is_relative_to(self.repository)


class UninstallFailure(RuntimeError):
    """An uninstall stopped before completion or completed only partially."""


def _absolute_without_following_final_symlink(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _is_root(path: Path) -> bool:
    return path == Path(path.anchor)


def _validate_repository_identity(repository: Path) -> None:
    required = (
        repository / "knemora",
        repository / "README.md",
        repository / "apps" / "api" / "knemora_bootstrap" / "__init__.py",
    )
    if not repository.is_dir() or not all(path.is_file() for path in required):
        raise UninstallFailure(
            f"Refusing to uninstall: {repository} is not a recognized Knemora repository."
        )


def build_uninstall_plan(
    paths: AppPaths,
    *,
    preserve_data: bool,
    data_entry: Path | None = None,
    home: Path | None = None,
) -> UninstallPlan:
    """Resolve and validate every deletion boundary before prompting or stopping services."""

    repository = paths.repository.resolve()
    user_home = (home or Path.home()).resolve()
    entry = _absolute_without_following_final_symlink(data_entry or configured_data_path())
    entry_is_symlink = entry.is_symlink()
    data = entry.resolve()

    _validate_repository_identity(repository)
    if _is_root(repository) or repository == user_home or user_home.is_relative_to(repository):
        raise UninstallFailure(f"Refusing unsafe repository target: {repository}")
    if _is_root(data) or data == user_home:
        raise UninstallFailure(f"Refusing unsafe application data target: {data}")
    if data != repository and repository.is_relative_to(data):
        raise UninstallFailure(
            "Refusing to uninstall because the application data directory is a parent of "
            f"the repository: {data}"
        )
    if preserve_data and (data == repository or data.is_relative_to(repository)):
        raise UninstallFailure(
            "Cannot preserve application data stored inside the repository. Move KNEMORA_HOME "
            "outside the repository through the supported configuration, then retry."
        )
    return UninstallPlan(
        repository=repository,
        data=data,
        data_entry=entry,
        preserve_data=preserve_data,
        data_entry_is_symlink=entry_is_symlink,
    )


def describe_plan(plan: UninstallPlan) -> None:
    print("Knemora uninstall")
    print(f"Repository:       {plan.repository}")
    print(f"Application data: {plan.data}")
    print()
    print("The repository and every file inside it will be deleted.")
    print("This includes uncommitted changes and untracked files in the repository.")
    if plan.preserve_data:
        print("The entire application data directory will be preserved.")
    elif plan.data_entry_is_symlink and not plan.repository_contains_data:
        print(f"The application-data symlink will be removed: {plan.data_entry}")
        print(f"Its external target and contents will be preserved: {plan.data}")
    else:
        print("The application data directory and all of its contents will also be deleted.")
    print("Shared dependencies and files outside these targets will not be removed.")


def confirm_uninstall(*, read: Callable[[str], str] | None = None) -> bool:
    """Require an explicit interactive yes, reprompting only for invalid text."""

    reader = read or input
    while True:
        try:
            answer = reader("Proceed? [y/N] ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print("\nUninstall cancelled; no services were stopped and no files were changed.")
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            print("Uninstall cancelled; no services were stopped and no files were changed.")
            return False
        print("Please answer y or n.")


def _remove_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def execute_uninstall(plan: UninstallPlan, runtime: ManagedRuntime) -> None:
    """Stop managed services and remove only the prevalidated targets."""

    if any(status.running for status in runtime.status() if status.name != "database"):
        print("Stopping services managed by this Knemora installation…")
        try:
            runtime.stop()
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            raise UninstallFailure(
                f"Safe service shutdown failed; nothing was deleted: {exc}"
            ) from exc

    removed: list[Path] = []
    try:
        if not plan.preserve_data and (
            plan.data_entry_is_symlink or not plan.repository_contains_data
        ):
            data_target = plan.data_entry if plan.data_entry_is_symlink else plan.data
            _remove_path(data_target)
            if not data_target.exists() and not data_target.is_symlink():
                removed.append(data_target)
        _remove_path(plan.repository)
        if not plan.repository.exists():
            removed.append(plan.repository)
    except OSError as exc:
        remaining = [
            path
            for path in (plan.repository, plan.data_entry)
            if path.exists() or path.is_symlink()
        ]
        removed_text = ", ".join(str(path) for path in removed) or "nothing completely"
        remaining_text = ", ".join(str(path) for path in remaining) or "no validated root"
        raise UninstallFailure(
            f"Uninstall was only partially completed: {exc}. "
            f"Removed: {removed_text}. Remaining: {remaining_text}."
        ) from exc

    if plan.repository.exists():
        raise UninstallFailure(f"Repository removal did not complete: {plan.repository}")
    if not plan.preserve_data and not plan.data_entry_is_symlink and plan.data.exists():
        raise UninstallFailure(f"Application data removal did not complete: {plan.data}")

    print("Knemora uninstall completed.")
    print(f"Removed repository: {plan.repository}")
    if plan.preserve_data:
        print(f"Preserved application data: {plan.data}")
        print(
            "A fresh clone can reuse it by keeping the same KNEMORA_HOME and running "
            "./knemora setup followed by ./knemora start."
        )
    elif plan.data_entry_is_symlink and not plan.repository_contains_data:
        print(f"Removed application-data symlink: {plan.data_entry}")
        print(f"Preserved external symlink target: {plan.data}")
    else:
        print(f"Removed application data: {plan.data}")


def uninstall(
    paths: AppPaths,
    runtime: ManagedRuntime,
    *,
    preserve_data: bool,
    interactive: bool,
    approved_by_global_flag: bool,
    read: Callable[[str], str] | None = None,
    data_entry: Path | None = None,
) -> bool:
    """Run the complete fail-safe uninstall interaction."""

    if approved_by_global_flag:
        raise UninstallFailure(
            "--yes cannot confirm uninstall; an interactive y/yes response is always required."
        )
    if not interactive:
        raise UninstallFailure(
            "Uninstall requires an interactive terminal and cannot run non-interactively."
        )
    plan = build_uninstall_plan(
        paths,
        preserve_data=preserve_data,
        data_entry=data_entry,
    )
    describe_plan(plan)
    if not confirm_uninstall(read=read):
        return False
    execute_uninstall(plan, runtime)
    return True
