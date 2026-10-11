"""Atomic filesystem operations for the portable Markdown Wiki."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.knowledge.errors import (
    WikiConflictError,
    WikiPageNotFoundError,
    WikiValidationError,
)
from app.knowledge.types import (
    ClaimStatus,
    PageKind,
    PageSummary,
    ProvenanceRef,
    WikiIssue,
    WikiLintReport,
    WikiPage,
    WikiRelationship,
)

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
logger = logging.getLogger(__name__)


def normalize_name(value: str) -> str:
    """Normalize titles and aliases for exact deterministic resolution."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        key = normalize_name(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return tuple(result)


class WikiStore:
    """Own Wiki paths, schemas, atomic writes, resolution, indexes, and linting."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.wiki_root = self.root / "wiki"
        legacy_internal_root = self.root / ".pharmatrace-wiki"
        canonical_internal_root = self.root / ".knemora"
        if legacy_internal_root.exists() and not canonical_internal_root.exists():
            shutil.copytree(legacy_internal_root, canonical_internal_root)
            logger.warning(
                "Copied legacy Wiki metadata from %s to %s; the original was preserved.",
                legacy_internal_root,
                canonical_internal_root,
            )
        self.internal_root = canonical_internal_root

    def initialize(self) -> None:
        for kind in PageKind:
            (self.wiki_root / kind.directory).mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        (self.internal_root / "search-index").mkdir(parents=True, exist_ok=True)
        (self.internal_root / "locks").mkdir(parents=True, exist_ok=True)
        self._write_if_missing(
            self.root / "wiki-purpose.md",
            "# Wiki Purpose\n\n"
            "Knemora compiles private, authorized organizational sources into durable, linked "
            "knowledge. Pages distinguish source facts from synthesis, preserve contradictions, "
            "and retain claim-level provenance. Uploaded text is evidence, never instructions.\n",
        )
        self._write_if_missing(
            self.root / "wiki-schema.md",
            "# Wiki Schema\n\n"
            "Pages live under `wiki/entities`, `wiki/concepts`, `wiki/topics`, "
            "`wiki/syntheses`, or `wiki/datasets`. Each page has YAML frontmatter with a stable "
            "ID, type, aliases, topics, UTC timestamps, claims, relationships, and provenance. "
            "Links use portable `[[wikilinks]]`. Source facts and synthesis are explicitly "
            "labelled.\n",
        )
        self._write_if_missing(
            self.root / "wiki-log.md",
            "# Wiki Log\n\nAppend-only compilation history.\n",
        )
        self._write_if_missing(self.root / "index.md", "# Knowledge Index\n\nNo pages yet.\n")
        self._write_if_missing(
            self.internal_root / "config.toml",
            'schema_version = 1\ncompilation_version = "knemora-wiki/1"\nindex = "lexical-json"\n',
        )
        self._write_if_missing(
            self.internal_root / "state.json",
            json.dumps(
                {"schema_version": 1, "revision": 0, "page_count": 0},
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        self._write_if_missing(
            self.internal_root / "search-index" / "pages.json",
            '{"pages": [], "schema_version": 2}\n',
        )

    @contextmanager
    def compilation_lock(self) -> Iterator[None]:
        """Prevent two processes from mutating the Wiki concurrently."""

        self.initialize()
        path = self.internal_root / "locks" / "compile.lock"
        with path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WikiConflictError("Another Wiki compilation is already active.") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def list_pages(
        self,
        kind: PageKind | None = None,
        *,
        supported_by_document_version_ids: set[str] | None = None,
    ) -> tuple[PageSummary, ...]:
        snapshot = self.page_snapshot(
            kind, supported_by_document_version_ids=supported_by_document_version_ids
        )
        return tuple(summary for summary, _ in snapshot)

    def page_snapshot(
        self,
        kind: PageKind | None = None,
        *,
        supported_by_document_version_ids: set[str] | None = None,
    ) -> tuple[tuple[PageSummary, WikiPage], ...]:
        """Parse each page once for one consistent read-oriented operation."""

        loaded = self._load_pages(kind)
        if supported_by_document_version_ids is not None:
            loaded = [
                (path, page)
                for path, page in loaded
                if any(
                    source.document_version_id in supported_by_document_version_ids
                    for source in page.provenance
                )
            ]
        records = ((self._summary(page, path), page) for path, page in loaded)
        return tuple(
            sorted(records, key=lambda item: (item[0].type, normalize_name(item[0].title)))
        )

    def read_page(self, identifier: str) -> WikiPage:
        matches = self._resolve_matches(identifier)
        if not matches:
            raise WikiPageNotFoundError(identifier)
        if len(matches) > 1:
            raise WikiConflictError(f"Ambiguous Wiki identifier: {identifier}")
        return matches[0][1]

    def resolve_page(self, identifier: str) -> PageSummary | None:
        matches = self._resolve_matches(identifier)
        if not matches:
            return None
        if len(matches) > 1:
            raise WikiConflictError(f"Ambiguous Wiki identifier: {identifier}")
        path, page = matches[0]
        return self._summary(page, path)

    def create_page(self, page: WikiPage) -> PageSummary:
        self.initialize()
        self.validate_page(page)
        for name in (page.title, *page.aliases):
            if self._resolve_matches(name):
                raise WikiConflictError(f"A page already uses the title or alias {name!r}.")
        path = self._path_for(page)
        if path.exists():
            raise WikiConflictError(f"Wiki path already exists: {path.relative_to(self.root)}")
        self._write_page(path, page)
        return self._summary(page, path)

    def update_page(self, page: WikiPage) -> PageSummary:
        self.initialize()
        self.validate_page(page)
        existing = [(path, item) for path, item in self._load_pages() if item.id == page.id]
        if not existing:
            raise WikiPageNotFoundError(page.id)
        if len(existing) > 1:
            raise WikiConflictError(f"Stable page ID {page.id} appears more than once.")
        old_path, _ = existing[0]
        for name in (page.title, *page.aliases):
            collisions = [item for _, item in self._resolve_matches(name) if item.id != page.id]
            if collisions:
                raise WikiConflictError(f"Another page already uses the title or alias {name!r}.")
        path = self._path_for(page)
        self._write_page(path, page)
        if old_path != path:
            old_path.unlink()
        return self._summary(page, path)

    def link_pages(
        self,
        source_identifier: str,
        target_identifier: str,
        relation: str,
        provenance: tuple[ProvenanceRef, ...] | None = None,
    ) -> WikiPage:
        source = self.read_page(source_identifier)
        target = self.read_page(target_identifier)
        link = WikiRelationship(
            relation=relation,
            target_id=target.id,
            target_title=target.title,
            provenance=provenance or source.provenance,
        )
        links = {(item.relation, item.target_id): item for item in (*source.relationships, link)}
        updated = source.model_copy(
            update={"relationships": tuple(links.values()), "updated_at": datetime.now(UTC)}
        )
        self.update_page(updated)
        return updated

    def backlinks(self, identifier: str) -> tuple[PageSummary, ...]:
        target = self.read_page(identifier)
        matches = [
            self._summary(page, path)
            for path, page in self._load_pages()
            if any(link.target_id == target.id for link in page.relationships)
        ]
        return tuple(sorted(matches, key=lambda item: normalize_name(item.title)))

    def validate_page(self, page: WikiPage) -> None:
        if not page.title.strip():
            raise WikiValidationError("A Wiki page title cannot be blank.")
        if normalize_name(page.title) in {normalize_name(alias) for alias in page.aliases}:
            raise WikiValidationError("A page title cannot also be its own alias.")
        if any(not topic.strip() for topic in page.topics):
            raise WikiValidationError("Wiki page topics cannot be blank.")
        if not page.claims:
            raise WikiValidationError("A Wiki page must contain at least one claim.")
        if not page.provenance:
            raise WikiValidationError("A Wiki page must contain provenance.")
        claim_ids = [claim.id for claim in page.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise WikiValidationError("Claim IDs must be unique within a page.")
        if any(not claim.provenance for claim in page.claims):
            raise WikiValidationError("Every claim must contain provenance.")
        if any(not link.provenance for link in page.relationships):
            raise WikiValidationError("Every relationship must contain provenance.")

    def rebuild_index(self) -> tuple[PageSummary, ...]:
        self.initialize()
        loaded = self._load_pages()
        summaries = tuple(
            sorted(
                (self._summary(page, path) for path, page in loaded),
                key=lambda item: (item.type, normalize_name(item.title)),
            )
        )
        entries: list[dict[str, Any]] = []
        for path, page in loaded:
            fields = {
                "title": self._tokens(page.title),
                "aliases": self._tokens(" ".join(page.aliases)),
                "type": self._tokens(page.type.value),
                "topics": self._tokens(" ".join(page.topics)),
                "summary": self._tokens(page.summary),
                "claims": self._tokens(" ".join(claim.text for claim in page.claims)),
                "relationships": self._tokens(
                    " ".join(f"{link.relation} {link.target_title}" for link in page.relationships)
                ),
            }
            text = " ".join(token for tokens in fields.values() for token in tokens)
            entries.append(
                {
                    "id": page.id,
                    "type": page.type,
                    "title": page.title,
                    "aliases": list(page.aliases),
                    "normalized_names": [
                        normalize_name(name) for name in (page.title, *page.aliases)
                    ],
                    "topics": list(page.topics),
                    "path": path.relative_to(self.root).as_posix(),
                    "summary": page.summary,
                    "fields": fields,
                    "terms": sorted(set(text.split())),
                    "links": [link.target_id for link in page.relationships],
                }
            )
        payload = {"schema_version": 2, "pages": entries}
        self._atomic_write(
            self.internal_root / "search-index" / "pages.json",
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        lines = ["# Knowledge Index", ""]
        for kind in PageKind:
            lines.extend([f"## {kind.directory.title()}", ""])
            matches = [item for item in summaries if item.type == kind]
            lines.extend(
                f"- [[{item.title}]]"
                + (f" — topics: {', '.join(item.topics)}" if item.topics else "")
                for item in matches
            )
            if not matches:
                lines.append("_No pages._")
            lines.append("")
        self._atomic_write(self.root / "index.md", "\n".join(lines).rstrip() + "\n")
        state_path = self.internal_root / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            {
                "revision": int(state.get("revision", 0)) + 1,
                "page_count": len(summaries),
                "indexed_at": datetime.now(UTC).isoformat(),
            }
        )
        self._atomic_write(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")
        return summaries

    def lint(self) -> WikiLintReport:
        self.initialize()
        issues: list[WikiIssue] = []
        loaded: list[tuple[Path, WikiPage]] = []
        for path in self._page_files():
            try:
                page = self._parse_page(path)
                self.validate_page(page)
                loaded.append((path, page))
            except Exception as exc:
                issues.append(
                    WikiIssue(
                        severity="error",
                        code="invalid-page",
                        path=path.relative_to(self.root).as_posix(),
                        message=str(exc),
                    )
                )
        ids: dict[str, list[Path]] = {}
        names: dict[str, list[tuple[Path, str]]] = {}
        for path, page in loaded:
            ids.setdefault(page.id, []).append(path)
            for name in (page.title, *page.aliases):
                names.setdefault(normalize_name(name), []).append((path, name))
        for page_id, paths in ids.items():
            if len(paths) > 1:
                issues.append(
                    WikiIssue(
                        severity="error",
                        code="duplicate-page-id",
                        path=paths[0].relative_to(self.root).as_posix(),
                        message=f"Stable page ID {page_id} appears {len(paths)} times.",
                    )
                )
        for key, matches in names.items():
            distinct_ids = {
                page.id for path, page in loaded if any(path == match[0] for match in matches)
            }
            if len(distinct_ids) > 1:
                issues.append(
                    WikiIssue(
                        severity="error",
                        code="ambiguous-title-or-alias",
                        path=matches[0][0].relative_to(self.root).as_posix(),
                        message=f"Normalized name {key!r} resolves to multiple pages.",
                    )
                )
        title_targets = {
            normalize_name(name) for _, page in loaded for name in (page.title, *page.aliases)
        }
        known_ids = {page.id for _, page in loaded}
        incoming: dict[str, int] = {page.id: 0 for _, page in loaded}
        for path, page in loaded:
            relative_path = path.relative_to(self.root).as_posix()
            if not page.provenance:
                issues.append(
                    WikiIssue(
                        severity="error",
                        code="missing-provenance",
                        path=relative_path,
                        message=f"{page.title!r} has no page-level source provenance.",
                    )
                )
            claim_ids = {claim.id for claim in page.claims}
            for claim in page.claims:
                if not claim.provenance:
                    issues.append(
                        WikiIssue(
                            severity="error",
                            code="missing-provenance",
                            path=relative_path,
                            message=f"Claim {claim.id!r} has no source provenance.",
                        )
                    )
                if claim.status.value == "disputed" and (
                    not claim.conflicts_with
                    or any(conflict not in claim_ids for conflict in claim.conflicts_with)
                ):
                    issues.append(
                        WikiIssue(
                            severity="error",
                            code="invalid-contradiction",
                            path=relative_path,
                            message=f"Disputed claim {claim.id!r} has invalid conflict links.",
                        )
                    )
            raw = path.read_text(encoding="utf-8")
            for target in WIKILINK.findall(raw):
                if normalize_name(target) not in title_targets:
                    issues.append(
                        WikiIssue(
                            severity="error",
                            code="broken-wikilink",
                            path=path.relative_to(self.root).as_posix(),
                            message=f"Wikilink target {target!r} does not resolve.",
                        )
                    )
            for link in page.relationships:
                if not link.provenance:
                    issues.append(
                        WikiIssue(
                            severity="error",
                            code="missing-provenance",
                            path=relative_path,
                            message=(
                                f"Relationship {link.relation!r} to {link.target_id!r} "
                                "has no source provenance."
                            ),
                        )
                    )
                if link.target_id not in known_ids:
                    issues.append(
                        WikiIssue(
                            severity="error",
                            code="broken-relationship",
                            path=path.relative_to(self.root).as_posix(),
                            message=f"Relationship target ID {link.target_id} does not resolve.",
                        )
                    )
                else:
                    incoming[link.target_id] += 1
        for path, page in loaded:
            if not page.relationships and incoming[page.id] == 0:
                issues.append(
                    WikiIssue(
                        severity="warning",
                        code="orphan-page",
                        path=path.relative_to(self.root).as_posix(),
                        message=f"{page.title!r} has no incoming or outgoing Wiki relationships.",
                    )
                )
        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        return WikiLintReport(
            page_count=len(loaded), errors=errors, warnings=warnings, issues=tuple(issues)
        )

    def apply_pages_transactionally(self, pages: Sequence[WikiPage]) -> WikiLintReport:
        """Apply a batch and roll the filesystem back if validation or indexing fails."""

        self.initialize()
        loaded = self._load_pages()
        existing_by_id = {page.id: (path, page) for path, page in loaded}
        if len(existing_by_id) != len(loaded):
            raise WikiConflictError("A stable page ID appears more than once in the Wiki.")
        batch_ids = [page.id for page in pages]
        if len(batch_ids) != len(set(batch_ids)):
            raise WikiConflictError("A stable page ID appears more than once in the update batch.")
        names: dict[str, str] = {
            normalize_name(name): page.id
            for _, page in loaded
            for name in (page.title, *page.aliases)
        }
        for page in pages:
            self.validate_page(page)
            for name in (page.title, *page.aliases):
                key = normalize_name(name)
                owner = names.get(key)
                if owner is not None and owner != page.id:
                    raise WikiConflictError(
                        f"Another page already uses the title or alias {name!r}."
                    )
                names[key] = page.id
        managed = [*self._page_files(), self.root / "index.md"]
        managed.extend((self.internal_root / "search-index").glob("*.json"))
        managed.append(self.internal_root / "state.json")
        before = {path: path.read_bytes() for path in managed if path.exists()}
        before_page_paths = set(self._page_files())
        try:
            for page in pages:
                target = self._path_for(page)
                self._write_page(target, page)
                existing = existing_by_id.get(page.id)
                if existing is not None and existing[0] != target:
                    existing[0].unlink()
            self.rebuild_index()
            report = self.lint()
            if report.errors:
                raise WikiValidationError(
                    f"Wiki lint reported {report.errors} error(s); changes were rolled back."
                )
            return report
        except Exception:
            for path in set(self._page_files()) - before_page_paths:
                path.unlink(missing_ok=True)
            for path, data in before.items():
                self._atomic_write_bytes(path, data)
            raise

    def reconcile_deleted_versions(self, version_ids: set[str]) -> dict[str, int]:
        """Subtract source lineage and rebuild every active Wiki projection atomically."""

        self.initialize()
        loaded = self._load_pages()
        before = {
            path: path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and path.name != "compile.lock"
        }
        before_paths = set(before)
        removed_claims = 0
        removed_relationships = 0
        removed_pages = 0
        try:
            survivors: dict[str, tuple[Path, WikiPage]] = {}
            for path, page in loaded:
                claims = []
                for claim in page.claims:
                    provenance = tuple(
                        item
                        for item in claim.provenance
                        if item.document_version_id not in version_ids
                    )
                    if not provenance:
                        removed_claims += 1
                        continue
                    claims.append(claim.model_copy(update={"provenance": provenance}))
                if not claims:
                    path.unlink(missing_ok=True)
                    removed_pages += 1
                    continue
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
                claims = reconciled_claims
                page_provenance = tuple(
                    item for item in page.provenance if item.document_version_id not in version_ids
                )
                if not page_provenance:
                    page_provenance = tuple(
                        {
                            (item.source_record_id, item.compilation_version): item
                            for claim in claims
                            for item in claim.provenance
                        }.values()
                    )
                survivors[page.id] = (
                    path,
                    page.model_copy(
                        update={
                            "claims": tuple(claims),
                            "provenance": page_provenance,
                            "summary": " ".join(claim.text for claim in claims[:3])[:4000],
                            "updated_at": datetime.now(UTC),
                        }
                    ),
                )

            surviving_ids = set(survivors)
            for page_id, (path, page) in survivors.items():
                relationships = []
                for relationship in page.relationships:
                    provenance = tuple(
                        item
                        for item in relationship.provenance
                        if item.document_version_id not in version_ids
                    )
                    if not provenance or relationship.target_id not in surviving_ids:
                        removed_relationships += 1
                        continue
                    relationships.append(relationship.model_copy(update={"provenance": provenance}))
                updated = page.model_copy(update={"relationships": tuple(relationships)})
                self.validate_page(updated)
                self._write_page(path, updated)
                survivors[page_id] = (path, updated)

            for version_id in version_ids:
                (self.root / "sources" / f"{version_id}.md").unlink(missing_ok=True)
            self.rebuild_index()
            lint = self.lint()
            if lint.errors:
                raise WikiValidationError(
                    f"Wiki deletion reconciliation produced {lint.errors} lint error(s)."
                )
            return {
                "pages_removed": removed_pages,
                "claims_removed": removed_claims,
                "relationships_removed": removed_relationships,
            }
        except Exception:
            for path in [item for item in self.root.rglob("*") if item.is_file()]:
                if path.name != "compile.lock" and path not in before_paths:
                    path.unlink(missing_ok=True)
            for path, content in before.items():
                self._atomic_write_bytes(path, content)
            raise

    def write_source_manifest(
        self,
        *,
        document_id: str,
        document_version_id: str,
        original_filename: str,
        sha256: str,
        storage_uri: str,
        page_titles: Sequence[str],
    ) -> Path:
        self.initialize()
        path = self.root / "sources" / f"{document_version_id}.md"
        metadata = {
            "document_id": document_id,
            "document_version_id": document_version_id,
            "original_filename": original_filename,
            "sha256": sha256,
            "immutable_source_uri": storage_uri,
        }
        body = [f"# Source: {original_filename}", "", "## Compiled pages", ""]
        body.extend(f"- [[{title}]]" for title in sorted(set(page_titles)))
        text = (
            "---\n"
            + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
            + "\n---\n\n"
            + "\n".join(body).rstrip()
            + "\n"
        )
        self._atomic_write(path, text)
        return path

    def append_log(self, compilation_id: str, lines: Sequence[str]) -> None:
        self.initialize()
        path = self.root / "wiki-log.md"
        current = path.read_text(encoding="utf-8")
        marker = f"<!-- compilation:{compilation_id} -->"
        if marker in current:
            return
        entry = ["", marker, f"## {datetime.now(UTC).isoformat()} — compilation", "", *lines, ""]
        self._atomic_write(path, current.rstrip() + "\n" + "\n".join(entry))

    def _resolve_matches(self, identifier: str) -> list[tuple[Path, WikiPage]]:
        key = normalize_name(identifier)
        return [
            (path, page)
            for path, page in self._load_pages()
            if identifier == page.id
            or key in {normalize_name(page.title), *(normalize_name(a) for a in page.aliases)}
        ]

    def _load_pages(self, kind: PageKind | None = None) -> list[tuple[Path, WikiPage]]:
        paths = (
            sorted((self.wiki_root / kind.directory).glob("*.md"))
            if kind is not None
            else self._page_files()
        )
        return [(path, self._parse_page(path)) for path in paths]

    def _page_files(self) -> list[Path]:
        if not self.wiki_root.exists():
            return []
        return sorted(self.wiki_root.glob("*/*.md"))

    def _parse_page(self, path: Path) -> WikiPage:
        match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
        if match is None:
            raise WikiValidationError("Missing YAML frontmatter.")
        payload = yaml.safe_load(match.group(1))
        if not isinstance(payload, dict):
            raise WikiValidationError("YAML frontmatter must be a mapping.")
        return WikiPage.model_validate(payload)

    def _write_page(self, path: Path, page: WikiPage) -> None:
        payload = page.model_dump(mode="json")
        frontmatter = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).strip()
        body = [f"# {page.title}", "", page.summary.strip()]
        if page.topics:
            body.extend(["", "Topics: " + ", ".join(page.topics)])
        body.extend(["", "## Claims", ""])
        for claim in page.claims:
            label = "Source fact" if claim.classification == "source_fact" else "Synthesis"
            body.append(f"- **{label} · {claim.status}** — {claim.text} ^{claim.id}")
            for source in claim.provenance:
                locator = json.dumps(source.locator, ensure_ascii=False, sort_keys=True)
                body.append(
                    f"  - Source: `{source.original_filename}` · version "
                    f"`{source.document_version_id}` · record `{source.source_record_id}` · "
                    f"locator `{locator}`"
                )
            if claim.conflicts_with:
                body.append(
                    "  - Conflicts with: "
                    + ", ".join(f"`{claim_id}`" for claim_id in claim.conflicts_with)
                )
        body.extend(["", "## Relationships", ""])
        if page.relationships:
            body.extend(
                f"- **{link.relation}** → [[{link.target_title}]]" for link in page.relationships
            )
        else:
            body.append("_No relationships recorded._")
        text = "---\n" + frontmatter + "\n---\n\n" + "\n".join(body).rstrip() + "\n"
        self._atomic_write(path, text)

    def _path_for(self, page: WikiPage) -> Path:
        return self.wiki_root / page.type.directory / f"{self._slug(page.title)}.md"

    def _summary(self, page: WikiPage, path: Path) -> PageSummary:
        return PageSummary(
            id=page.id,
            type=page.type,
            title=page.title,
            aliases=page.aliases,
            topics=page.topics,
            path=path.relative_to(self.root).as_posix(),
        )

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return re.findall(r"[^\W_]+(?:-[^\W_]+)*", normalize_name(value), flags=re.UNICODE)

    @staticmethod
    def _slug(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
        return slug or "page"

    def _write_if_missing(self, path: Path, content: str) -> None:
        if not path.exists():
            self._atomic_write(path, content)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        WikiStore._atomic_write_bytes(path, content.encode("utf-8"))

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["WikiStore", "normalize_name", "_dedupe"]
