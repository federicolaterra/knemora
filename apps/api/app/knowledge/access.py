"""Owner-scoped access to Wiki retrieval and normalized source evidence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Document, DocumentVersion, SourceRecord
from app.knowledge.errors import SourceReferenceNotFoundError
from app.knowledge.graph import WikiGraph, WikiGraphService, WikiMarkdownPage
from app.knowledge.search import WikiRetrievalService
from app.knowledge.store import WikiStore
from app.knowledge.types import ClaimStatus, PageKind, PageSummary, StrictModel, WikiPage


class SourceReference(StrictModel):
    source_record_id: str
    document_id: str
    document_version_id: str
    original_filename: str
    sha256: str
    locator: dict[str, Any]
    parser_name: str
    parser_version: str
    content: str
    truncated: bool
    immutable_source_uri: str


class KnowledgeAccessService:
    """Build owner-scoped retrieval services and source-record evidence."""

    def __init__(self, *, session: Session, settings: Settings, owner_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.owner_id = owner_id

    def retrieval(self) -> WikiRetrievalService:
        return WikiRetrievalService(
            store=WikiStore(self.settings.knowledge_path),
            allowed_document_version_ids=self._authorized_version_ids(),
            max_results=self.settings.wiki_search_max_results,
            max_graph_depth=self.settings.wiki_graph_max_depth,
            max_evidence_chars=self.settings.wiki_evidence_max_chars,
        )

    def list_pages(self, kind: PageKind | None = None) -> tuple[PageSummary, ...]:
        """List only pages supported by at least one active authorized source."""

        allowed = self._authorized_version_ids()
        store = WikiStore(self.settings.knowledge_path)
        return store.list_pages(
            kind,
            supported_by_document_version_ids=allowed,
        )

    def graph(self, *, root: str | None, depth: int, force_refresh: bool = False) -> WikiGraph:
        """Return the owner-scoped native graph projection."""

        return WikiGraphService(
            WikiStore(self.settings.knowledge_path),
            max_nodes=self.settings.wiki_graph_max_nodes,
            max_edges=self.settings.wiki_graph_max_edges,
            small_graph_threshold=self.settings.wiki_graph_small_graph_threshold,
        ).graph(
            allowed_document_version_ids=self._authorized_version_ids(),
            root=root,
            depth=depth,
            force_refresh=force_refresh,
        )

    def read_markdown_page(self, path: str) -> WikiMarkdownPage:
        """Read one Markdown page under the Wiki root without allowing path escape."""

        return WikiGraphService(WikiStore(self.settings.knowledge_path)).read_markdown_page(
            path, allowed_document_version_ids=self._authorized_version_ids()
        )

    def read_page(self, identifier: str) -> WikiPage:
        """Filter a shared Wiki page down to the caller's active source lineage."""

        allowed = self._authorized_version_ids()
        page = WikiStore(self.settings.knowledge_path).read_page(identifier)
        page_provenance = tuple(
            source for source in page.provenance if source.document_version_id in allowed
        )
        if not page_provenance:
            from app.knowledge.errors import WikiPageNotFoundError

            raise WikiPageNotFoundError(identifier)
        claims = tuple(
            claim.model_copy(
                update={
                    "provenance": tuple(
                        source
                        for source in claim.provenance
                        if source.document_version_id in allowed
                    )
                }
            )
            for claim in page.claims
            if any(source.document_version_id in allowed for source in claim.provenance)
        )
        claim_ids = {claim.id for claim in claims}
        reconciled_claims = []
        for claim in claims:
            conflicts = tuple(item for item in claim.conflicts_with if item in claim_ids)
            status = (
                claim.status
                if conflicts == claim.conflicts_with
                else ClaimStatus.DISPUTED
                if conflicts
                else ClaimStatus.SUPPORTED
            )
            reconciled_claims.append(
                claim.model_copy(update={"conflicts_with": conflicts, "status": status})
            )
        claims = tuple(reconciled_claims)
        allowed_page_ids = {
            summary.id
            for summary in WikiStore(self.settings.knowledge_path).list_pages(
                supported_by_document_version_ids=allowed
            )
        }
        relationships = tuple(
            relationship.model_copy(
                update={
                    "provenance": tuple(
                        source
                        for source in relationship.provenance
                        if source.document_version_id in allowed
                    )
                }
            )
            for relationship in page.relationships
            if relationship.target_id in allowed_page_ids
            and any(source.document_version_id in allowed for source in relationship.provenance)
        )
        safe_summary = " ".join(claim.text for claim in claims[:3])[:4000]
        return page.model_copy(
            update={
                "provenance": page_provenance,
                "claims": claims,
                "relationships": relationships,
                "summary": safe_summary,
            }
        )

    def read_source_reference(self, source_record_id: str, *, max_chars: int) -> SourceReference:
        try:
            record_id = uuid.UUID(source_record_id)
        except ValueError as exc:
            raise SourceReferenceNotFoundError(source_record_id) from exc
        row = self.session.execute(
            select(SourceRecord, DocumentVersion, Document)
            .join(
                DocumentVersion,
                SourceRecord.document_version_id == DocumentVersion.id,
            )
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(SourceRecord.id == record_id, Document.owner_id == self.owner_id)
            .where(Document.deleted_at.is_(None))
        ).one_or_none()
        if row is None:
            raise SourceReferenceNotFoundError(source_record_id)
        record, version, document = row
        bound = max(1, min(max_chars, self.settings.source_reference_max_chars))
        return SourceReference(
            source_record_id=str(record.id),
            document_id=str(document.id),
            document_version_id=str(version.id),
            original_filename=document.original_filename,
            sha256=version.sha256,
            locator=record.locator,
            parser_name=record.parser_name,
            parser_version=record.parser_version,
            content=record.content[:bound],
            truncated=len(record.content) > bound,
            immutable_source_uri=version.storage_uri,
        )

    def _authorized_version_ids(self) -> set[str]:
        return {
            str(version_id)
            for version_id in self.session.scalars(
                select(DocumentVersion.id)
                .join(Document, DocumentVersion.document_id == Document.id)
                .where(Document.owner_id == self.owner_id)
                .where(Document.deleted_at.is_(None))
            )
        }


__all__ = ["KnowledgeAccessService", "SourceReference"]
