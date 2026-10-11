"""Typed contracts for Wiki pages, proposals, provenance, and audit reports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageKind(StrEnum):
    ENTITY = "entity"
    CONCEPT = "concept"
    TOPIC = "topic"
    SYNTHESIS = "synthesis"
    DATASET = "dataset"

    @property
    def directory(self) -> str:
        return f"{self.value}s" if self is not PageKind.SYNTHESIS else "syntheses"


class ClaimClassification(StrEnum):
    SOURCE_FACT = "source_fact"
    SYNTHESIS = "synthesis"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    DISPUTED = "disputed"


class CompilationStatus(StrEnum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    VALIDATING = "VALIDATING"
    APPLYING = "APPLYING"
    INDEXING = "INDEXING"
    LINTING = "LINTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProvenanceRef(StrictModel):
    source_record_id: str
    document_id: str
    document_version_id: str
    original_filename: str
    sha256: str
    locator: dict[str, Any]
    parser_name: str
    parser_version: str
    compilation_version: str
    compiled_at: datetime


class WikiClaim(StrictModel):
    id: str
    key: str
    text: str
    classification: ClaimClassification
    status: ClaimStatus = ClaimStatus.SUPPORTED
    provenance: tuple[ProvenanceRef, ...]
    conflicts_with: tuple[str, ...] = ()


class WikiRelationship(StrictModel):
    relation: str
    target_id: str
    target_title: str
    provenance: tuple[ProvenanceRef, ...]


class WikiPage(StrictModel):
    id: str
    type: PageKind
    title: str
    aliases: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    summary: str
    created_at: datetime
    updated_at: datetime
    compilation_version: str
    provenance: tuple[ProvenanceRef, ...]
    claims: tuple[WikiClaim, ...]
    relationships: tuple[WikiRelationship, ...] = ()
    schema_version: int = Field(default=1, ge=1)


class ClaimProposal(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=4000)
    classification: ClaimClassification
    source_record_ordinals: tuple[int, ...] = Field(min_length=1)


class RelationshipProposal(StrictModel):
    relation: str = Field(min_length=1, max_length=100)
    target_title: str = Field(min_length=1, max_length=300)
    source_record_ordinals: tuple[int, ...] = Field(min_length=1)


class PageProposal(StrictModel):
    type: PageKind
    title: str = Field(min_length=1, max_length=300)
    aliases: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    summary: str = Field(min_length=1, max_length=4000)
    claims: tuple[ClaimProposal, ...] = Field(min_length=1)
    relationships: tuple[RelationshipProposal, ...] = ()


class KnowledgeProposal(StrictModel):
    pages: tuple[PageProposal, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def titles_are_unique(self) -> KnowledgeProposal:
        normalized = [" ".join(page.title.casefold().split()) for page in self.pages]
        if len(normalized) != len(set(normalized)):
            raise ValueError("proposal page titles must be unique")
        return self


class PageSummary(StrictModel):
    id: str
    type: PageKind
    title: str
    aliases: tuple[str, ...]
    topics: tuple[str, ...] = ()
    path: str


class WikiIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


class WikiLintReport(StrictModel):
    page_count: int
    errors: int
    warnings: int
    issues: tuple[WikiIssue, ...]


class CompilationConflict(StrictModel):
    page_id: str
    page_title: str
    claim_key: str
    claim_ids: tuple[str, ...]


class CompilationSource(StrictModel):
    document_id: str
    document_version_id: str
    original_filename: str
    sha256: str


class CompilationReport(StrictModel):
    compilation_job_id: str
    source: CompilationSource
    pages_created: tuple[PageSummary, ...]
    pages_updated: tuple[PageSummary, ...]
    links_created: int
    conflicts: tuple[CompilationConflict, ...]
    warnings: tuple[str, ...]
    provenance_coverage: float = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    failures: tuple[str, ...] = ()
    lint: WikiLintReport
