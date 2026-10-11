"""Value types shared by validation, parsers, storage, and orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class IngestionStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    STORING = "STORING"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    READY_FOR_COMPILATION = "READY_FOR_COMPILATION"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ValidatedUpload:
    original_filename: str
    sanitized_filename: str
    extension: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class SourceBlock:
    content: str
    locator: dict[str, Any]


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    parser_version: str
    blocks: tuple[SourceBlock, ...]
    document_metadata: dict[str, Any] = field(default_factory=dict)
    dataset_metadata: dict[str, Any] | None = None


class DocumentParser(Protocol):
    name: str
    version: str
    extensions: frozenset[str]

    def parse(self, upload: ValidatedUpload) -> ParsedDocument:
        """Convert validated bytes to normalized, locator-aware blocks."""
