"""Upload allow-list, name safety, type checks, and archive limits."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import Settings
from app.ingestion.errors import IngestionRequestError, UnsupportedFileError
from app.ingestion.types import ValidatedUpload


@dataclass(frozen=True)
class FilePolicy:
    content_type: str
    accepted_content_types: frozenset[str]


POLICIES: dict[str, FilePolicy] = {
    ".pdf": FilePolicy("application/pdf", frozenset({"application/pdf"})),
    ".txt": FilePolicy("text/plain", frozenset({"text/plain"})),
    ".md": FilePolicy("text/markdown", frozenset({"text/markdown", "text/plain"})),
    ".markdown": FilePolicy("text/markdown", frozenset({"text/markdown", "text/plain"})),
    ".docx": FilePolicy(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ),
    ".csv": FilePolicy(
        "text/csv", frozenset({"text/csv", "application/csv", "application/vnd.ms-excel"})
    ),
    ".xlsx": FilePolicy(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    ),
}

_SAFE_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")
_REQUIRED_OFFICE_ENTRIES = {
    ".docx": {"[Content_Types].xml", "word/document.xml"},
    ".xlsx": {"[Content_Types].xml", "xl/workbook.xml"},
}


def sanitize_filename(filename: str) -> str:
    """Return a display-safe name while rejecting path-bearing input outright."""

    normalized = unicodedata.normalize("NFKC", filename).strip()
    if not normalized or len(normalized) > 500:
        raise IngestionRequestError("A filename between 1 and 500 characters is required.")
    if "\x00" in normalized or "/" in normalized or "\\" in normalized:
        raise IngestionRequestError("The filename must not contain a path.")
    if normalized in {".", ".."}:
        raise IngestionRequestError("The filename is not valid.")
    sanitized = _SAFE_CHARACTER.sub("_", normalized).strip("._")
    if not sanitized:
        raise IngestionRequestError("The filename has no safe characters.")
    return sanitized[:255]


def _validate_text(data: bytes) -> None:
    if b"\x00" in data:
        raise UnsupportedFileError("The uploaded text file contains binary data.")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedFileError("Text sources must be valid UTF-8.") from exc


def _validate_office_archive(data: bytes, extension: str, settings: Settings) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > settings.max_archive_entries:
                raise UnsupportedFileError("The Office archive contains too many entries.")
            total_uncompressed = 0
            names: set[str] = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\x00" in entry.filename:
                    raise UnsupportedFileError("The Office archive contains an unsafe path.")
                if entry.flag_bits & 0x1:
                    raise UnsupportedFileError("Encrypted Office documents are not supported.")
                total_uncompressed += entry.file_size
                if total_uncompressed > settings.max_archive_uncompressed_bytes:
                    raise UnsupportedFileError("The Office archive expands beyond the safe limit.")
                if entry.file_size and entry.compress_size == 0:
                    raise UnsupportedFileError(
                        "The Office archive has an invalid compression ratio."
                    )
                if entry.compress_size:
                    ratio = entry.file_size / entry.compress_size
                    if ratio > settings.max_archive_compression_ratio:
                        raise UnsupportedFileError(
                            "The Office archive exceeds the safe compression ratio."
                        )
                names.add(entry.filename)
            if not _REQUIRED_OFFICE_ENTRIES[extension].issubset(names):
                raise UnsupportedFileError(
                    f"The file is not a valid {extension.removeprefix('.').upper()} document."
                )
    except zipfile.BadZipFile as exc:
        raise UnsupportedFileError("The Office document is not a valid ZIP container.") from exc


def validate_upload(
    *, filename: str, declared_content_type: str | None, data: bytes, settings: Settings
) -> ValidatedUpload:
    """Apply the complete pre-storage upload policy and return canonical metadata."""

    sanitized = sanitize_filename(filename)
    dot = sanitized.rfind(".")
    extension = sanitized[dot:].lower() if dot >= 0 else ""
    policy = POLICIES.get(extension)
    if policy is None:
        raise UnsupportedFileError(
            "Supported extensions are PDF, TXT, Markdown, DOCX, CSV, and XLSX."
        )
    if not data:
        raise IngestionRequestError("The uploaded file is empty.")
    normalized_type = (declared_content_type or "").partition(";")[0].strip().lower()
    if normalized_type not in policy.accepted_content_types:
        raise UnsupportedFileError(
            f"Content type {normalized_type or '(missing)'} is not allowed for {extension}."
        )

    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise UnsupportedFileError("The PDF signature does not match its extension.")
    elif extension in {".docx", ".xlsx"}:
        _validate_office_archive(data, extension, settings)
    else:
        _validate_text(data)

    return ValidatedUpload(
        original_filename=filename,
        sanitized_filename=sanitized,
        extension=extension,
        content_type=policy.content_type,
        data=data,
    )
