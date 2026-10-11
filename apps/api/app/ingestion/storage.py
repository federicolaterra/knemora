"""Filesystem-backed immutable source store with atomic artifact writes."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Any

MAX_STORAGE_FILENAME_LENGTH = 120
RESERVED_ARTIFACT_NAMES = frozenset(
    {"extracted.md", "metadata.json", "processing.json", "source-name-migration.json"}
)


def readable_storage_filename(
    uploaded_filename: str,
    *,
    extension: str,
    identity: uuid.UUID,
    existing_names: set[str] | None = None,
) -> str:
    """Return a portable recognizable leaf name without trusting it as a path."""

    normalized = unicodedata.normalize("NFKD", uploaded_filename)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    normalized_extension = extension.lower()
    if ascii_name.casefold().endswith(normalized_extension.casefold()):
        ascii_name = ascii_name[: -len(normalized_extension)]
    ascii_name = "".join("_" if char.isspace() else char for char in ascii_name)
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name)
    ascii_name = re.sub(r"[_ .-]+", "_", ascii_name).strip("_.-")
    stem = ascii_name
    if not stem:
        stem = "source"

    devices = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    stable_suffix = f"_{identity.hex[:8]}"
    reserved = {name.casefold() for name in RESERVED_ARTIFACT_NAMES}
    reserved.update(name.casefold() for name in (existing_names or set()))
    candidate = f"{stem}{normalized_extension}"
    if stem.casefold() in devices or candidate.casefold() in reserved:
        stem = f"{stem}{stable_suffix}"

    maximum_stem = max(1, MAX_STORAGE_FILENAME_LENGTH - len(normalized_extension))
    stem = stem[:maximum_stem].rstrip("_.-") or "source"
    candidate = f"{stem}{normalized_extension}"
    if candidate.casefold() in reserved:
        room = max(1, maximum_stem - len(stable_suffix))
        candidate = f"{stem[:room].rstrip('_.-') or 'source'}{stable_suffix}{normalized_extension}"
    return candidate


class SourceStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def version_directory(
        self, *, stored_on: date, document_id: uuid.UUID, version_id: uuid.UUID
    ) -> Path:
        return self.root / stored_on.isoformat() / str(document_id) / str(version_id)

    def relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Source artifact escaped the configured storage root.")
        return resolved.relative_to(self.root).as_posix()

    def artifact_paths(
        self,
        *,
        stored_on: date,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        extension: str,
        uploaded_filename: str,
    ) -> dict[str, Path]:
        directory = self.version_directory(
            stored_on=stored_on, document_id=document_id, version_id=version_id
        )
        original_name = readable_storage_filename(
            uploaded_filename,
            extension=extension,
            identity=version_id,
            existing_names=set(RESERVED_ARTIFACT_NAMES),
        )
        return {
            "directory": directory,
            "original": directory / original_name,
            "extracted": directory / "extracted.md",
            "metadata": directory / "metadata.json",
            "processing": directory / "processing.json",
        }

    def store_original(self, *, path: Path, data: bytes, processing: dict[str, Any]) -> None:
        """Publish a new version directory atomically and make original bytes read-only."""

        directory = path.parent
        if directory.exists():
            existing = path.read_bytes() if path.exists() else None
            if existing != data:
                raise FileExistsError("An immutable source version already exists at this path.")
            return
        directory.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{directory.name}-", dir=directory.parent))
        try:
            staged_original = staging / path.name
            with staged_original.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged_original.chmod(0o444)
            self._write_json(staging / "processing.json", processing)
            os.replace(staging, directory)
        except Exception:
            self._remove_empty_staging(staging)
            raise

    def write_derived(
        self, *, extracted_path: Path, metadata_path: Path, markdown: str, metadata: dict[str, Any]
    ) -> None:
        self._atomic_write(extracted_path, markdown.encode("utf-8"))
        self._atomic_write(
            metadata_path,
            (json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )

    def write_processing(self, path: Path, processing: dict[str, Any]) -> None:
        if path.parent.exists():
            self._write_json(path, processing)

    def read_original(self, path: Path) -> bytes:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Stored source path escaped the configured storage root.")
        return resolved.read_bytes()

    def resolve_relative(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Stored source URI escaped the configured storage root.")
        return path

    def remove_version_directory(self, storage_uri: str) -> None:
        """Remove one generated version directory without following links outside the store."""

        original = self.resolve_relative(storage_uri)
        directory = original.parent
        if not directory.is_relative_to(self.root) or directory == self.root:
            raise ValueError("Refusing to remove a shared source-store directory.")
        if directory.is_symlink():
            raise ValueError("Refusing to follow a symlinked source version directory.")
        if directory.exists():
            shutil.rmtree(directory)
        for parent in (directory.parent, directory.parent.parent):
            if parent == self.root or not parent.is_relative_to(self.root):
                break
            try:
                parent.rmdir()
            except OSError:
                break

    @staticmethod
    def _remove_empty_staging(staging: Path) -> None:
        if not staging.exists():
            return
        for child in staging.iterdir():
            child.unlink(missing_ok=True)
        staging.rmdir()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _write_json(cls, path: Path, payload: dict[str, Any]) -> None:
        cls._atomic_write(
            path,
            (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
