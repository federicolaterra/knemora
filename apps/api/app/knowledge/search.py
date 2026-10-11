"""Bounded lexical, identity, and graph retrieval over the local Wiki."""

from __future__ import annotations

import json
import math
from collections import Counter, deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import Field

from app.knowledge.errors import WikiConflictError, WikiPageNotFoundError, WikiValidationError
from app.knowledge.store import WikiStore, normalize_name
from app.knowledge.types import PageKind, PageSummary, ProvenanceRef, StrictModel, WikiPage


class SearchHit(StrictModel):
    id: str
    type: PageKind
    title: str
    aliases: tuple[str, ...]
    topics: tuple[str, ...]
    path: str
    score: float = Field(ge=0)
    retrieval_mode: str
    matched_fields: tuple[str, ...]
    snippet: str


class EvidenceCitation(StrictModel):
    wiki_page_id: str
    wiki_page_title: str
    wiki_path: str
    claim_id: str | None
    source_record_id: str
    document_id: str
    document_version_id: str
    original_filename: str
    sha256: str
    locator: dict[str, Any]


class EvidenceClaim(StrictModel):
    id: str
    key: str
    text: str
    classification: str
    status: str
    conflicts_with: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...]


class EvidenceRelationship(StrictModel):
    relation: str
    target_id: str
    target_title: str
    citations: tuple[EvidenceCitation, ...]


class WikiEvidencePage(StrictModel):
    id: str
    type: PageKind
    title: str
    aliases: tuple[str, ...]
    topics: tuple[str, ...]
    path: str
    summary: str
    claims: tuple[EvidenceClaim, ...]
    relationships: tuple[EvidenceRelationship, ...]
    truncated: bool


class RelatedPage(StrictModel):
    id: str
    type: PageKind
    title: str
    aliases: tuple[str, ...]
    topics: tuple[str, ...]
    path: str
    depth: int = Field(ge=1)
    direction: str
    relation: str
    via_page_id: str


class WikiSearchBackend(Protocol):
    """Stable search contract that a future semantic/hybrid backend can implement."""

    def search(
        self,
        *,
        query: str,
        page_types: Sequence[PageKind],
        topics: Sequence[str],
        limit: int,
        allowed_document_version_ids: set[str] | None,
    ) -> tuple[SearchHit, ...]: ...


class BM25WikiSearch:
    """Weighted BM25 over the deterministic Wiki index."""

    _field_weights = {
        "title": 6,
        "aliases": 5,
        "type": 2,
        "topics": 3,
        "summary": 2,
        "claims": 1,
        "relationships": 1,
    }

    def __init__(self, store: WikiStore) -> None:
        self.store = store
        self.index_path = store.internal_root / "search-index" / "pages.json"

    def search(
        self,
        *,
        query: str,
        page_types: Sequence[PageKind],
        topics: Sequence[str],
        limit: int,
        allowed_document_version_ids: set[str] | None,
    ) -> tuple[SearchHit, ...]:
        normalized_query = normalize_name(query)
        if not normalized_query and not page_types and not topics:
            raise WikiValidationError("Search requires a query, page type, or topic filter.")
        payload = self._load_index()
        indexed_entries = (
            self._authorized_entries(payload, allowed_document_version_ids)
            if allowed_document_version_ids is not None
            else payload["pages"]
        )
        entries = [
            entry
            for entry in indexed_entries
            if self._matches_filters(entry, page_types=page_types, topics=topics)
        ]
        if not entries:
            return ()

        query_terms = self.store._tokens(normalized_query)
        weighted_documents = [self._weighted_tokens(entry) for entry in entries]
        average_length = sum(len(document) for document in weighted_documents) / len(entries)
        document_frequency = {
            term: sum(term in set(document) for document in weighted_documents)
            for term in set(query_terms)
        }
        hits: list[SearchHit] = []
        for entry, document in zip(entries, weighted_documents, strict=True):
            exact = normalized_query and (
                normalized_query == str(entry["id"])
                or normalized_query in entry.get("normalized_names", [])
            )
            score = self._bm25(
                query_terms=query_terms,
                document=document,
                document_count=len(entries),
                document_frequency=document_frequency,
                average_length=average_length,
            )
            if exact:
                score += 100.0
            if query_terms and score <= 0:
                continue
            fields = entry.get("fields", {})
            matched_fields = tuple(
                name
                for name in self._field_weights
                if set(query_terms).intersection(fields.get(name, []))
            )
            hits.append(
                SearchHit(
                    id=str(entry["id"]),
                    type=PageKind(str(entry["type"])),
                    title=str(entry["title"]),
                    aliases=tuple(str(item) for item in entry.get("aliases", [])),
                    topics=tuple(str(item) for item in entry.get("topics", [])),
                    path=str(entry["path"]),
                    score=round(score, 6),
                    retrieval_mode=(
                        "identity" if exact else "bm25" if query_terms else "structured_index"
                    ),
                    matched_fields=matched_fields,
                    snippet=str(entry.get("summary", ""))[:280],
                )
            )
        hits.sort(key=lambda item: (-item.score, normalize_name(item.title), item.id))
        return tuple(hits[:limit])

    def _load_index(self) -> dict[str, Any]:
        self.store.initialize()
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.store.rebuild_index()
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 2:
            self.store.rebuild_index()
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("pages"), list):
            raise WikiValidationError("The Wiki search index is invalid.")
        return cast(dict[str, Any], payload)

    @staticmethod
    def _matches_filters(
        entry: dict[str, Any], *, page_types: Sequence[PageKind], topics: Sequence[str]
    ) -> bool:
        if page_types and str(entry.get("type")) not in {kind.value for kind in page_types}:
            return False
        wanted_topics = {normalize_name(topic) for topic in topics if topic.strip()}
        actual_topics = {normalize_name(str(topic)) for topic in entry.get("topics", [])}
        return not wanted_topics or bool(wanted_topics.intersection(actual_topics))

    def _authorized_entries(
        self, payload: dict[str, Any], allowed_document_version_ids: set[str]
    ) -> list[dict[str, Any]]:
        """Rebuild searchable content from active lineage while a cleanup may be pending."""

        indexed = {str(item["id"]): item for item in payload["pages"]}
        entries: list[dict[str, Any]] = []
        for summary, page in self.store.page_snapshot(
            supported_by_document_version_ids=allowed_document_version_ids
        ):
            claims = [
                claim
                for claim in page.claims
                if any(
                    item.document_version_id in allowed_document_version_ids
                    for item in claim.provenance
                )
            ]
            relationships = [
                relationship
                for relationship in page.relationships
                if any(
                    item.document_version_id in allowed_document_version_ids
                    for item in relationship.provenance
                )
            ]
            if not claims:
                continue
            safe_summary = " ".join(claim.text for claim in claims[:3])[:4000]
            fields = {
                "title": self.store._tokens(page.title),
                "aliases": self.store._tokens(" ".join(page.aliases)),
                "type": self.store._tokens(page.type.value),
                "topics": self.store._tokens(" ".join(page.topics)),
                "summary": self.store._tokens(safe_summary),
                "claims": self.store._tokens(" ".join(claim.text for claim in claims)),
                "relationships": self.store._tokens(
                    " ".join(
                        f"{relationship.relation} {relationship.target_title}"
                        for relationship in relationships
                    )
                ),
            }
            base = indexed.get(page.id, {})
            entries.append(
                {
                    **base,
                    "id": page.id,
                    "type": page.type.value,
                    "title": page.title,
                    "aliases": list(page.aliases),
                    "normalized_names": [
                        normalize_name(name) for name in (page.title, *page.aliases)
                    ],
                    "topics": list(page.topics),
                    "path": summary.path,
                    "summary": safe_summary,
                    "fields": fields,
                    "links": [relationship.target_id for relationship in relationships],
                }
            )
        return entries

    def _weighted_tokens(self, entry: dict[str, Any]) -> list[str]:
        fields = entry.get("fields", {})
        return [
            token
            for name, weight in self._field_weights.items()
            for token in fields.get(name, [])
            for _ in range(weight)
        ]

    @staticmethod
    def _bm25(
        *,
        query_terms: Sequence[str],
        document: Sequence[str],
        document_count: int,
        document_frequency: dict[str, int],
        average_length: float,
    ) -> float:
        if not query_terms or not document:
            return 0.0
        frequencies = Counter(document)
        k1 = 1.5
        b = 0.75
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if frequency == 0:
                continue
            matches = document_frequency[term]
            inverse_frequency = math.log(1 + (document_count - matches + 0.5) / (matches + 0.5))
            normalization = frequency + k1 * (1 - b + b * len(document) / max(average_length, 1.0))
            score += inverse_frequency * frequency * (k1 + 1) / normalization
        return score


class WikiRetrievalService:
    """Assemble bounded, provenance-rich evidence using a replaceable search backend."""

    def __init__(
        self,
        *,
        store: WikiStore,
        search_backend: WikiSearchBackend | None = None,
        allowed_document_version_ids: set[str] | None = None,
        max_results: int = 20,
        max_graph_depth: int = 2,
        max_evidence_chars: int = 12_000,
    ) -> None:
        self.store = store
        self.search_backend = search_backend or BM25WikiSearch(store)
        self.allowed_document_version_ids = allowed_document_version_ids
        self.max_results = max_results
        self.max_graph_depth = max_graph_depth
        self.max_evidence_chars = max_evidence_chars

    def search(
        self,
        *,
        query: str,
        page_types: Sequence[PageKind] = (),
        topics: Sequence[str] = (),
        limit: int = 10,
    ) -> tuple[SearchHit, ...]:
        return self.search_backend.search(
            query=query,
            page_types=page_types,
            topics=topics,
            limit=max(1, min(limit, self.max_results)),
            allowed_document_version_ids=self.allowed_document_version_ids,
        )

    def read_page(self, identifier: str, *, max_claims: int = 20) -> WikiEvidencePage:
        page = self._authorized_page(identifier)
        summary = self.store.resolve_page(page.id)
        if summary is None:
            raise WikiPageNotFoundError(identifier)
        claims: list[EvidenceClaim] = []
        relationships: list[EvidenceRelationship] = []
        allowed_page_ids = set(self._authorized_snapshot())
        authorized_claims = [
            claim for claim in page.claims if self._authorized_sources(claim.provenance)
        ]
        authorized_claim_ids = {claim.id for claim in authorized_claims}
        safe_summary = " ".join(claim.text for claim in authorized_claims[:3])[:4000]
        consumed = len(safe_summary)
        truncated = False
        for claim in authorized_claims:
            sources = self._authorized_sources(claim.provenance)
            if not sources:
                continue
            if len(claims) >= max(1, min(max_claims, 100)):
                truncated = True
                break
            if consumed + len(claim.text) > self.max_evidence_chars:
                truncated = True
                break
            consumed += len(claim.text)
            conflicts = tuple(item for item in claim.conflicts_with if item in authorized_claim_ids)
            claims.append(
                EvidenceClaim(
                    id=claim.id,
                    key=claim.key,
                    text=claim.text,
                    classification=claim.classification.value,
                    status=(
                        claim.status.value
                        if conflicts == claim.conflicts_with
                        else "disputed"
                        if conflicts
                        else "supported"
                    ),
                    conflicts_with=conflicts,
                    citations=self._citations(page, summary.path, claim.id, sources),
                )
            )
        for relationship in page.relationships:
            sources = self._authorized_sources(relationship.provenance)
            if not sources or relationship.target_id not in allowed_page_ids:
                continue
            relationships.append(
                EvidenceRelationship(
                    relation=relationship.relation,
                    target_id=relationship.target_id,
                    target_title=relationship.target_title,
                    citations=self._citations(page, summary.path, None, sources),
                )
            )
        return WikiEvidencePage(
            id=page.id,
            type=page.type,
            title=page.title,
            aliases=page.aliases,
            topics=page.topics,
            path=summary.path,
            summary=safe_summary[: self.max_evidence_chars],
            claims=tuple(claims),
            relationships=tuple(relationships),
            truncated=truncated or len(safe_summary) > self.max_evidence_chars,
        )

    def backlinks(self, identifier: str, *, limit: int = 20) -> tuple[RelatedPage, ...]:
        snapshot = self._authorized_snapshot()
        target_summary, target = self._snapshot_page(identifier, snapshot)
        results: list[RelatedPage] = []
        for summary, source in snapshot.values():
            relations = sorted(
                {
                    relationship.relation
                    for relationship in source.relationships
                    if relationship.target_id == target.id
                    and self._authorized_sources(relationship.provenance)
                }
            )
            for relation in relations:
                results.append(
                    RelatedPage(
                        **summary.model_dump(),
                        depth=1,
                        direction="incoming",
                        relation=relation,
                        via_page_id=target_summary.id,
                    )
                )
        return tuple(results[: max(1, min(limit, self.max_results))])

    def related_pages(
        self, identifier: str, *, max_depth: int = 1, limit: int = 20
    ) -> tuple[RelatedPage, ...]:
        snapshot = self._authorized_snapshot()
        _, root = self._snapshot_page(identifier, snapshot)
        depth_limit = max(1, min(max_depth, self.max_graph_depth))
        result_limit = max(1, min(limit, self.max_results))
        incoming: dict[str, list[tuple[WikiPage, str]]] = {}
        for _, source in snapshot.values():
            for relationship in source.relationships:
                if self._authorized_sources(relationship.provenance):
                    incoming.setdefault(relationship.target_id, []).append(
                        (source, relationship.relation)
                    )
        visited = {root.id}
        queue: deque[tuple[WikiPage, int]] = deque([(root, 0)])
        results: list[RelatedPage] = []
        while queue and len(results) < result_limit:
            current, depth = queue.popleft()
            if depth >= depth_limit:
                continue
            neighbors: list[tuple[str, str, str, str]] = []
            for relationship in current.relationships:
                if self._authorized_sources(relationship.provenance):
                    neighbors.append(
                        (
                            relationship.target_id,
                            "outgoing",
                            relationship.relation,
                            current.id,
                        )
                    )
            neighbors.extend(
                (source.id, "incoming", relation, current.id)
                for source, relation in incoming.get(current.id, ())
            )
            for page_id, direction, relation, via_page_id in neighbors:
                if page_id in visited:
                    continue
                record = snapshot.get(page_id)
                if record is None:
                    continue
                summary, related = record
                visited.add(page_id)
                next_depth = depth + 1
                results.append(
                    RelatedPage(
                        **summary.model_dump(),
                        depth=next_depth,
                        direction=direction,
                        relation=relation,
                        via_page_id=via_page_id,
                    )
                )
                queue.append((related, next_depth))
                if len(results) >= result_limit:
                    break
        return tuple(results)

    def _authorized_snapshot(self) -> dict[str, tuple[PageSummary, WikiPage]]:
        """Load authorized pages once so graph traversal is linear in the vault size."""

        return {
            page.id: (summary, page)
            for summary, page in self.store.page_snapshot(
                supported_by_document_version_ids=self.allowed_document_version_ids
            )
        }

    @staticmethod
    def _snapshot_page(
        identifier: str, snapshot: dict[str, tuple[PageSummary, WikiPage]]
    ) -> tuple[PageSummary, WikiPage]:
        key = normalize_name(identifier)
        matches = [
            (summary, page)
            for summary, page in snapshot.values()
            if identifier == page.id
            or key in {normalize_name(page.title), *(normalize_name(a) for a in page.aliases)}
        ]
        if not matches:
            raise WikiPageNotFoundError(identifier)
        if len(matches) > 1:
            raise WikiConflictError(f"Ambiguous Wiki identifier: {identifier}")
        return matches[0]

    def _authorized_page(self, identifier: str) -> WikiPage:
        page = self.store.read_page(identifier)
        if self.allowed_document_version_ids is not None and not any(
            source.document_version_id in self.allowed_document_version_ids
            for source in page.provenance
        ):
            raise WikiPageNotFoundError(identifier)
        return page

    def _authorized_sources(self, sources: Sequence[ProvenanceRef]) -> tuple[ProvenanceRef, ...]:
        if self.allowed_document_version_ids is None:
            return tuple(sources)
        return tuple(
            source
            for source in sources
            if source.document_version_id in self.allowed_document_version_ids
        )

    @staticmethod
    def _citations(
        page: WikiPage,
        path: str,
        claim_id: str | None,
        sources: Sequence[ProvenanceRef],
    ) -> tuple[EvidenceCitation, ...]:
        return tuple(
            EvidenceCitation(
                wiki_page_id=page.id,
                wiki_page_title=page.title,
                wiki_path=path,
                claim_id=claim_id,
                source_record_id=source.source_record_id,
                document_id=source.document_id,
                document_version_id=source.document_version_id,
                original_filename=source.original_filename,
                sha256=source.sha256,
                locator=source.locator,
            )
            for source in sources
        )


def index_path(store: WikiStore) -> Path:
    """Expose the deterministic index path for diagnostics and acceptance checks."""

    return store.internal_root / "search-index" / "pages.json"


__all__ = [
    "BM25WikiSearch",
    "EvidenceCitation",
    "RelatedPage",
    "SearchHit",
    "WikiEvidencePage",
    "WikiRetrievalService",
    "WikiSearchBackend",
    "index_path",
]
