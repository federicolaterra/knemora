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


class CompactStrictModel(StrictModel):
    """Strict model-facing DTOs that accept descriptive Python names and compact JSON aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CompactPageProposal(CompactStrictModel):
    type: PageKind = Field(alias="k")
    title: str = Field(alias="t", min_length=1, max_length=300)
    aliases: tuple[str, ...] = Field(default=(), alias="a")
    topics: tuple[str, ...] = Field(default=(), alias="g")


class CompactClaimTarget(CompactStrictModel):
    page: int = Field(alias="p", ge=0)
    key: str = Field(alias="k", min_length=1, max_length=120)


class CompactFactProposal(CompactStrictModel):
    claims: tuple[CompactClaimTarget, ...] = Field(alias="on", min_length=1)
    text: str = Field(alias="x", min_length=1, max_length=4000)
    classification: ClaimClassification = Field(default=ClaimClassification.SOURCE_FACT, alias="c")
    source_record_ordinals: tuple[int, ...] = Field(alias="s", min_length=1)


class CompactRelationshipProposal(CompactStrictModel):
    source_page: int = Field(alias="f", ge=0)
    relation: str = Field(alias="r", min_length=1, max_length=100)
    target_title: str = Field(alias="t", min_length=1, max_length=300)
    source_record_ordinals: tuple[int, ...] = Field(alias="s", min_length=1)


class CompactKnowledgeProposal(CompactStrictModel):
    """Version 2 model-facing proposal; durable Wiki and cached proposal schemas stay unchanged."""

    contract_version: Literal[2] = Field(alias="v")
    pages: tuple[CompactPageProposal, ...] = Field(alias="p", min_length=1)
    facts: tuple[CompactFactProposal, ...] = Field(alias="f", min_length=1)
    relationships: tuple[CompactRelationshipProposal, ...] = Field(default=(), alias="r")
    warnings: tuple[str, ...] = Field(default=(), alias="w")

    @model_validator(mode="after")
    def references_are_valid(self) -> CompactKnowledgeProposal:
        normalized = [" ".join(page.title.casefold().split()) for page in self.pages]
        if len(normalized) != len(set(normalized)):
            raise ValueError("compact proposal page titles must be unique")

        assigned_pages: set[int] = set()
        for fact in self.facts:
            fact_pages = [claim.page for claim in fact.claims]
            if len(fact_pages) != len(set(fact_pages)):
                raise ValueError("a compact fact may assign at most one claim key per page")
            for page_index in fact_pages:
                if page_index >= len(self.pages):
                    raise ValueError("compact fact references an unknown page index")
                assigned_pages.add(page_index)
        if assigned_pages != set(range(len(self.pages))):
            raise ValueError("every compact proposal page must receive at least one fact")

        if any(item.source_page >= len(self.pages) for item in self.relationships):
            raise ValueError("compact relationship references an unknown source page index")
        return self

    def expand(self) -> KnowledgeProposal:
        """Expand canonical facts/edges into the unchanged version-1 application proposal."""

        claims_by_page: list[list[ClaimProposal]] = [[] for _ in self.pages]
        relationships_by_page: list[list[RelationshipProposal]] = [[] for _ in self.pages]
        for fact in self.facts:
            for target in fact.claims:
                claims_by_page[target.page].append(
                    ClaimProposal(
                        key=target.key,
                        text=fact.text,
                        classification=fact.classification,
                        source_record_ordinals=fact.source_record_ordinals,
                    )
                )
        for relationship in self.relationships:
            relationships_by_page[relationship.source_page].append(
                RelationshipProposal(
                    relation=relationship.relation,
                    target_title=relationship.target_title,
                    source_record_ordinals=relationship.source_record_ordinals,
                )
            )

        return KnowledgeProposal(
            pages=tuple(
                PageProposal(
                    type=page.type,
                    title=page.title,
                    aliases=page.aliases,
                    topics=page.topics,
                    # The summary is faithful and deterministic: exact text of the first fact
                    # assigned to this page, with no generated biographical connective prose.
                    summary=claims_by_page[index][0].text,
                    claims=tuple(claims_by_page[index]),
                    relationships=tuple(relationships_by_page[index]),
                )
                for index, page in enumerate(self.pages)
            ),
            warnings=self.warnings,
        )


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


class ProviderAttemptMetrics(StrictModel):
    attempt: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    duration_ms: float = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    retry_cause: str | None = None
    budget_basis: str | None = None


class CompilationBatchMetrics(StrictModel):
    batch: int = Field(ge=1)
    batch_count: int = Field(ge=1)
    source_record_count: int = Field(ge=1)
    source_character_count: int = Field(ge=0)
    payload_character_count: int = Field(ge=0)
    response_character_count: int = Field(default=0, ge=0)
    proposal_contract_version: int = Field(default=1, ge=1)
    attempts: tuple[ProviderAttemptMetrics, ...]


class CompilationStageTimings(StrictModel):
    lock_wait_ms: float = Field(default=0, ge=0)
    batch_preparation_ms: float = Field(default=0, ge=0)
    provider_ms: float = Field(default=0, ge=0)
    validation_grounding_relationship_ms: float = Field(default=0, ge=0)
    merge_ms: float = Field(default=0, ge=0)
    transactional_write_ms: float = Field(default=0, ge=0)
    index_ms: float = Field(default=0, ge=0)
    lint_ms: float = Field(default=0, ge=0)
    manifest_and_log_ms: float = Field(default=0, ge=0)
    database_commit_ms: float = Field(default=0, ge=0)


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
    stage_timings: CompilationStageTimings = Field(default_factory=CompilationStageTimings)
    batches: tuple[CompilationBatchMetrics, ...] = ()
    failures: tuple[str, ...] = ()
    lint: WikiLintReport
