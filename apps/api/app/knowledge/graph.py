"""Revision-aware graph projection over the portable Markdown Wiki."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import quote, unquote, urlparse

import yaml  # type: ignore[import-untyped]
from pydantic import Field

from app.knowledge.errors import WikiConflictError, WikiPageNotFoundError
from app.knowledge.store import FRONTMATTER, WikiStore, normalize_name
from app.knowledge.types import PageKind, StrictModel

FENCED_CODE = re.compile(r"(?ms)^[ \t]*(```+|~~~+).*?^[ \t]*\1[ \t]*$")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)*\1")
WIKILINK = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"(?m)^#\s+(.+?)\s*$")
EXTERNAL_SCHEMES = {"data", "file", "ftp", "http", "https", "mailto", "tel"}


class GraphNode(StrictModel):
    id: str
    page_id: str | None
    title: str
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    document_type: str
    folder: str
    path: str
    detail_reference: str
    modified_at: datetime
    generated: bool
    degree: int = Field(default=0, ge=0)
    isolated: bool = False


class GraphEdge(StrictModel):
    id: str
    source: str
    target: str
    relations: tuple[str, ...]
    provenance: tuple[Literal["relationship", "wikilink", "markdown_link"], ...]


class GraphDiagnostic(StrictModel):
    source_id: str
    source_path: str
    target: str
    reason: Literal["ambiguous", "unresolved"]


class GraphFreshness(StrictModel):
    revision: str
    wiki_revision: int
    indexed_at: datetime
    file_count: int


class WikiGraph(StrictModel):
    mode: Literal["global", "local"]
    root_id: str | None
    depth: int | None
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    diagnostics: tuple[GraphDiagnostic, ...]
    unresolved_count: int
    ambiguous_count: int
    total_nodes: int
    total_edges: int
    isolated_nodes: int
    returned_nodes: int
    returned_edges: int
    truncated: bool
    small_graph_threshold: int
    freshness: GraphFreshness


class WikiMarkdownPage(StrictModel):
    id: str
    path: str
    title: str
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    document_type: str
    modified_at: datetime
    content: str


class _IndexedNode(StrictModel):
    node: GraphNode
    document_version_ids: tuple[str, ...] = ()


class _GraphIndex(StrictModel):
    nodes: tuple[_IndexedNode, ...]
    edges: tuple[GraphEdge, ...]
    diagnostics: tuple[GraphDiagnostic, ...]
    freshness: GraphFreshness


class WikiGraphService:
    """Build and serve a rebuildable graph without changing Wiki documents."""

    CACHE_SCHEMA_VERSION = 1

    def __init__(
        self,
        store: WikiStore,
        *,
        max_nodes: int = 2_000,
        max_edges: int = 8_000,
        small_graph_threshold: int = 50,
    ) -> None:
        self.store = store
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self.small_graph_threshold = small_graph_threshold
        self.cache_path = store.internal_root / "graph-index.json"

    def graph(
        self,
        *,
        allowed_document_version_ids: set[str] | None,
        root: str | None = None,
        depth: int = 1,
        force_refresh: bool = False,
    ) -> WikiGraph:
        index = self._load_or_build(force_refresh=force_refresh)
        allowed_nodes = {
            record.node.id: record.node
            for record in index.nodes
            if not record.document_version_ids
            or allowed_document_version_ids is None
            or bool(set(record.document_version_ids).intersection(allowed_document_version_ids))
        }
        authorized_relationships: set[tuple[str, str]] | None = None
        if allowed_document_version_ids is not None:
            generated_snapshot = (
                item
                for kind in PageKind
                for item in self.store.page_snapshot(
                    kind, supported_by_document_version_ids=allowed_document_version_ids
                )
            )
            authorized_relationships = {
                (page.id, relationship.target_id)
                for _, page in generated_snapshot
                for relationship in page.relationships
                if any(
                    source.document_version_id in allowed_document_version_ids
                    for source in relationship.provenance
                )
            }
        allowed_edges = tuple(
            edge
            for edge in index.edges
            if edge.source in allowed_nodes
            and edge.target in allowed_nodes
            and (
                authorized_relationships is None
                or "relationship" not in edge.provenance
                or (edge.source, edge.target) in authorized_relationships
                or "markdown_link" in edge.provenance
            )
        )
        diagnostics = tuple(item for item in index.diagnostics if item.source_id in allowed_nodes)
        mode: Literal["global", "local"] = "global"
        root_id: str | None = None
        selected_ids = set(allowed_nodes)
        if root:
            mode = "local"
            root_id = self._resolve_root(root, allowed_nodes)
            selected_ids = self._neighborhood(root_id, allowed_edges, max(1, min(depth, 3)))

        selected_edges = [
            edge
            for edge in allowed_edges
            if edge.source in selected_ids and edge.target in selected_ids
        ]
        degree: dict[str, int] = defaultdict(int)
        for edge in selected_edges:
            degree[edge.source] += 1
            degree[edge.target] += 1
        selected_nodes = [
            allowed_nodes[node_id].model_copy(
                update={"degree": degree[node_id], "isolated": degree[node_id] == 0}
            )
            for node_id in selected_ids
        ]
        selected_nodes.sort(key=lambda node: (-node.degree, normalize_name(node.title), node.id))
        selected_edges.sort(key=lambda edge: (edge.source, edge.target, edge.id))
        total_nodes = len(selected_nodes)
        total_edges = len(selected_edges)
        returned_nodes = selected_nodes[: self.max_nodes]
        returned_ids = {node.id for node in returned_nodes}
        returned_edges = [
            edge
            for edge in selected_edges
            if edge.source in returned_ids and edge.target in returned_ids
        ][: self.max_edges]
        return WikiGraph(
            mode=mode,
            root_id=root_id,
            depth=max(1, min(depth, 3)) if root else None,
            nodes=tuple(returned_nodes),
            edges=tuple(returned_edges),
            diagnostics=diagnostics[:100],
            unresolved_count=sum(item.reason == "unresolved" for item in diagnostics),
            ambiguous_count=sum(item.reason == "ambiguous" for item in diagnostics),
            total_nodes=total_nodes,
            total_edges=total_edges,
            isolated_nodes=sum(node.isolated for node in selected_nodes),
            returned_nodes=len(returned_nodes),
            returned_edges=len(returned_edges),
            truncated=total_nodes > len(returned_nodes) or total_edges > len(returned_edges),
            small_graph_threshold=self.small_graph_threshold,
            freshness=index.freshness,
        )

    def read_markdown_page(
        self, path: str, *, allowed_document_version_ids: set[str] | None
    ) -> WikiMarkdownPage:
        relative = self._safe_relative_path(path)
        candidate = (self.store.root / relative).resolve()
        wiki_root = self.store.wiki_root.resolve()
        if (
            not candidate.is_relative_to(wiki_root)
            or not candidate.is_file()
            or candidate.suffix.casefold() != ".md"
        ):
            raise WikiPageNotFoundError(path)
        raw = candidate.read_text(encoding="utf-8")
        metadata, body = self._metadata_and_body(raw)
        record = self._node_for_file(candidate, metadata, body)
        version_ids = self._document_version_ids(metadata)
        if (
            version_ids
            and allowed_document_version_ids is not None
            and not set(version_ids).intersection(allowed_document_version_ids)
        ):
            raise WikiPageNotFoundError(path)
        return WikiMarkdownPage(
            id=record.node.id,
            path=record.node.path,
            title=record.node.title,
            aliases=record.node.aliases,
            tags=record.node.tags,
            document_type=record.node.document_type,
            modified_at=record.node.modified_at,
            content=body.strip(),
        )

    def _load_or_build(self, *, force_refresh: bool) -> _GraphIndex:
        self.store.initialize()
        files = self._markdown_files()
        signature = self._signature(files)
        wiki_revision = self._wiki_revision()
        if not force_refresh:
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if (
                    payload.get("schema_version") == self.CACHE_SCHEMA_VERSION
                    and payload.get("signature") == signature
                    and payload.get("wiki_revision") == wiki_revision
                ):
                    return _GraphIndex.model_validate(payload["graph"])
            except (OSError, ValueError, TypeError, KeyError):
                pass
        graph = self._build(files, signature=signature, wiki_revision=wiki_revision)
        payload = {
            "schema_version": self.CACHE_SCHEMA_VERSION,
            "signature": signature,
            "wiki_revision": wiki_revision,
            "graph": graph.model_dump(mode="json"),
        }
        self.store._atomic_write(
            self.cache_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return graph

    def _build(self, files: list[Path], *, signature: str, wiki_revision: int) -> _GraphIndex:
        indexed: list[_IndexedNode] = []
        raw_by_id: dict[str, tuple[Path, dict[str, Any], str]] = {}
        for path in files:
            raw = path.read_text(encoding="utf-8")
            metadata, body = self._metadata_and_body(raw)
            record = self._node_for_file(path, metadata, body)
            indexed.append(record)
            raw_by_id[record.node.id] = (path, metadata, body)

        nodes = {record.node.id: record.node for record in indexed}
        path_index: dict[str, list[str]] = defaultdict(list)
        name_index: dict[str, list[str]] = defaultdict(list)
        basename_index: dict[str, list[str]] = defaultdict(list)
        page_id_index: dict[str, str] = {}
        for node in nodes.values():
            normalized_path = self._normalized_link_path(node.path)
            for key in {normalized_path, normalized_path.removesuffix(".md")}:
                path_index[key].append(node.id)
            basename_index[normalize_name(PurePosixPath(node.path).stem)].append(node.id)
            for name in (node.title, *node.aliases):
                name_index[normalize_name(name)].append(node.id)
            if node.page_id:
                page_id_index[node.page_id] = node.id

        edge_values: dict[tuple[str, str], dict[str, set[str]]] = {}
        diagnostics: dict[tuple[str, str, str], GraphDiagnostic] = {}
        for source_id, (path, metadata, body) in raw_by_id.items():
            references: list[tuple[str, str, str]] = []
            for relationship in metadata.get("relationships", ()):
                if not isinstance(relationship, dict):
                    continue
                relation = str(relationship.get("relation") or "relationship").strip()
                target_id = str(relationship.get("target_id") or "").strip()
                target_title = str(relationship.get("target_title") or "").strip()
                if target_id and target_id in page_id_index:
                    self._add_edge(
                        edge_values,
                        source_id,
                        page_id_index[target_id],
                        relation,
                        "relationship",
                    )
                elif target_title:
                    references.append((target_title, relation, "relationship"))

            link_text = INLINE_CODE.sub("", FENCED_CODE.sub("", body))
            for match in WIKILINK.finditer(link_text):
                target = match.group(1).split("|", 1)[0].strip()
                references.append((target, "link", "wikilink"))
            for match in MARKDOWN_LINK.finditer(link_text):
                target = self._markdown_target(match.group(1))
                if target:
                    references.append((target, "link", "markdown_link"))

            source_path = path.relative_to(self.store.root).as_posix()
            for target, relation, provenance in references:
                resolution, reason = self._resolve_link(
                    source_path,
                    target,
                    path_index=path_index,
                    name_index=name_index,
                    basename_index=basename_index,
                )
                if resolution:
                    self._add_edge(edge_values, source_id, resolution, relation, provenance)
                elif reason:
                    diagnostic = GraphDiagnostic(
                        source_id=source_id,
                        source_path=source_path,
                        target=target,
                        reason=reason,
                    )
                    diagnostics[(source_id, target, reason)] = diagnostic

        edges = tuple(
            GraphEdge(
                id=hashlib.sha256(f"{source}\0{target}".encode()).hexdigest()[:24],
                source=source,
                target=target,
                relations=tuple(sorted(values["relations"])),
                provenance=cast(
                    tuple[Literal["relationship", "wikilink", "markdown_link"], ...],
                    tuple(sorted(values["provenance"])),
                ),
            )
            for (source, target), values in sorted(edge_values.items())
        )
        now = datetime.now(UTC)
        return _GraphIndex(
            nodes=tuple(indexed),
            edges=edges,
            diagnostics=tuple(diagnostics.values()),
            freshness=GraphFreshness(
                revision=signature,
                wiki_revision=wiki_revision,
                indexed_at=now,
                file_count=len(files),
            ),
        )

    def _node_for_file(self, path: Path, metadata: dict[str, Any], body: str) -> _IndexedNode:
        relative = path.relative_to(self.store.root).as_posix()
        page_id_value = metadata.get("id")
        page_id = str(page_id_value).strip() if page_id_value else None
        stable_id = page_id or "file:" + hashlib.sha256(relative.encode()).hexdigest()[:24]
        heading = HEADING.search(body)
        title = str(metadata.get("title") or (heading.group(1) if heading else path.stem)).strip()
        aliases = self._string_tuple(metadata.get("aliases"))
        tags = self._string_tuple(metadata.get("topics") or metadata.get("tags"))
        raw_type = str(metadata.get("type") or "markdown").strip().casefold()
        generated = bool(page_id and raw_type in {kind.value for kind in PageKind})
        detail_reference = (
            f"/knowledge/{quote(page_id, safe='')}"
            if generated and page_id
            else f"/knowledge/file/{quote(relative, safe='/')}"
        )
        return _IndexedNode(
            node=GraphNode(
                id=stable_id,
                page_id=page_id if generated else None,
                title=title or path.stem,
                aliases=aliases,
                tags=tags,
                document_type=raw_type,
                folder=PurePosixPath(relative).parent.as_posix(),
                path=relative,
                detail_reference=detail_reference,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                generated=generated,
            ),
            document_version_ids=self._document_version_ids(metadata),
        )

    @staticmethod
    def _metadata_and_body(raw: str) -> tuple[dict[str, Any], str]:
        match = FRONTMATTER.match(raw)
        if match is None:
            return {}, raw
        payload = yaml.safe_load(match.group(1))
        return (payload if isinstance(payload, dict) else {}), raw[match.end() :]

    @staticmethod
    def _document_version_ids(metadata: dict[str, Any]) -> tuple[str, ...]:
        ids = {
            str(item.get("document_version_id"))
            for item in metadata.get("provenance", ())
            if isinstance(item, dict) and item.get("document_version_id")
        }
        return tuple(sorted(ids))

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        values: list[Any] | tuple[Any, ...]
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = value
        else:
            return ()
        return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

    @staticmethod
    def _markdown_target(raw: str) -> str | None:
        target = raw.strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]
        parsed = urlparse(target)
        if parsed.scheme.casefold() in EXTERNAL_SCHEMES or target.startswith("//"):
            return None
        path = unquote(parsed.path)
        if not path or Path(path).suffix.casefold() not in {"", ".md", ".markdown"}:
            return None
        return path + (f"#{parsed.fragment}" if parsed.fragment else "")

    def _resolve_link(
        self,
        source_path: str,
        raw_target: str,
        *,
        path_index: dict[str, list[str]],
        name_index: dict[str, list[str]],
        basename_index: dict[str, list[str]],
    ) -> tuple[str | None, Literal["ambiguous", "unresolved"] | None]:
        target = unquote(raw_target.strip()).split("#", 1)[0].strip()
        if not target:
            return None, None
        parsed = urlparse(target)
        if parsed.scheme.casefold() in EXTERNAL_SCHEMES or target.startswith("//"):
            return None, None
        normalized_name = normalize_name(PurePosixPath(target).stem)
        candidate_lists: list[list[str]] = []
        if "/" in target or target.startswith(".") or target.casefold().endswith(".md"):
            base = PurePosixPath(source_path).parent
            relative_candidate = self._normalized_link_path(
                posixpath.normpath((base / target).as_posix())
            )
            root_candidate = self._normalized_link_path(posixpath.normpath(target.lstrip("/")))
            for candidate in (relative_candidate, root_candidate):
                if not candidate.startswith("../"):
                    candidate_lists.append(path_index.get(candidate, []))
                    candidate_lists.append(path_index.get(candidate.removesuffix(".md"), []))
        candidate_lists.append(name_index.get(normalize_name(target), []))
        candidate_lists.append(basename_index.get(normalized_name, []))
        for matches in candidate_lists:
            unique = tuple(dict.fromkeys(matches))
            if len(unique) == 1:
                return unique[0], None
            if len(unique) > 1:
                return None, "ambiguous"
        return None, "unresolved"

    @staticmethod
    def _add_edge(
        values: dict[tuple[str, str], dict[str, set[str]]],
        source: str,
        target: str,
        relation: str,
        provenance: str,
    ) -> None:
        edge = values.setdefault((source, target), {"relations": set(), "provenance": set()})
        edge["relations"].add(relation or "link")
        edge["provenance"].add(provenance)

    @staticmethod
    def _neighborhood(root: str, edges: tuple[GraphEdge, ...], depth: int) -> set[str]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
        visited = {root}
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        while queue:
            node, distance = queue.popleft()
            if distance >= depth:
                continue
            for neighbor in sorted(adjacency[node]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))
        return visited

    @staticmethod
    def _resolve_root(root: str, nodes: dict[str, GraphNode]) -> str:
        if root in nodes:
            return root
        key = normalize_name(root)
        matches = [
            node.id
            for node in nodes.values()
            if key in {normalize_name(node.title), *(normalize_name(a) for a in node.aliases)}
        ]
        if not matches:
            raise WikiPageNotFoundError(root)
        if len(matches) > 1:
            raise WikiConflictError(f"Ambiguous Wiki graph root: {root}")
        return matches[0]

    def _markdown_files(self) -> list[Path]:
        if not self.store.wiki_root.is_dir():
            return []
        root = self.store.wiki_root.resolve()
        return sorted(
            path
            for path in self.store.wiki_root.rglob("*.md")
            if path.is_file() and path.resolve().is_relative_to(root)
        )

    @staticmethod
    def _signature(files: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in files:
            stat = path.stat()
            digest.update(str(path).encode())
            digest.update(f"\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
        return digest.hexdigest()

    def _wiki_revision(self) -> int:
        try:
            payload = json.loads((self.store.internal_root / "state.json").read_text())
            return int(payload.get("revision", 0))
        except (OSError, ValueError, TypeError):
            return 0

    @staticmethod
    def _normalized_link_path(path: str) -> str:
        return unicase_path(path.removeprefix("./"))

    @staticmethod
    def _safe_relative_path(path: str) -> PurePosixPath:
        decoded = unquote(path).strip().lstrip("/")
        relative = PurePosixPath(decoded)
        if not decoded or relative.is_absolute() or ".." in relative.parts:
            raise WikiPageNotFoundError(path)
        return relative


def unicase_path(path: str) -> str:
    """Normalize a portable Wiki-relative path without resolving the host filesystem."""

    return "/".join(normalize_name(part) for part in PurePosixPath(path).parts)


__all__ = [
    "GraphDiagnostic",
    "GraphEdge",
    "GraphFreshness",
    "GraphNode",
    "WikiGraph",
    "WikiGraphService",
    "WikiMarkdownPage",
]
