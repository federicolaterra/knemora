from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.knowledge.errors import WikiPageNotFoundError
from app.knowledge.graph import WikiGraphService
from app.knowledge.store import WikiStore
from app.knowledge.types import (
    ClaimClassification,
    PageKind,
    ProvenanceRef,
    WikiClaim,
    WikiPage,
    WikiRelationship,
)


def _page(title: str, *, version_id: str, target: WikiPage | None = None) -> WikiPage:
    provenance = (
        ProvenanceRef(
            source_record_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            document_version_id=version_id,
            original_filename="source.md",
            sha256="a" * 64,
            locator={"heading_path": [title]},
            parser_name="markdown",
            parser_version="1",
            compilation_version="test/1",
            compiled_at=datetime.now(UTC),
        ),
    )
    return WikiPage(
        id=str(uuid.uuid4()),
        type=PageKind.CONCEPT,
        title=title,
        aliases=(f"{title} alias",),
        topics=("testing",),
        summary=f"Summary for {title}.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="test/1",
        provenance=provenance,
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="definition",
                text=f"{title} is a test page.",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=provenance,
            ),
        ),
        relationships=(
            (
                WikiRelationship(
                    relation="references",
                    target_id=target.id,
                    target_title=target.title,
                    provenance=provenance,
                ),
            )
            if target
            else ()
        ),
    )


def test_graph_resolves_real_links_and_reports_ambiguous_or_unresolved_targets(
    tmp_path: Path,
) -> None:
    store = WikiStore(tmp_path / "knowledge")
    store.initialize()
    version_id = str(uuid.uuid4())
    beta = _page("Beta", version_id=version_id)
    alpha = _page("Alpha", version_id=version_id, target=beta)
    store.create_page(alpha)
    store.create_page(beta)
    store.rebuild_index()

    notes = store.wiki_root / "notes"
    guides = store.wiki_root / "guides"
    (store.wiki_root / "duplicates-a").mkdir()
    (store.wiki_root / "duplicates-b").mkdir()
    notes.mkdir()
    guides.mkdir()
    (guides / "Guide.md").write_text("---\naliases: [Handbook]\ntags: [manual]\n---\n# Guide\n")
    (store.wiki_root / "duplicates-a" / "Dupe.md").write_text("# First duplicate\n")
    (store.wiki_root / "duplicates-b" / "Dupe.md").write_text("# Second duplicate\n")
    (notes / "Home.md").write_text(
        "# Home\n\n"
        "[[Beta alias#Details|Beta label]]\n"
        "[Guide](../guides/Guide.md#intro)\n"
        "[[Dupe]]\n"
        "[[Missing page]]\n"
        "`[[Inline code]]`\n"
        "```md\n[[Fenced code]]\n```\n"
        "![[diagram.png]]\n"
        "![image](asset.png)\n"
        "[external](https://example.com)\n"
    )
    (notes / "Isolated.md").write_text("# Isolated\n")

    graph = WikiGraphService(store, small_graph_threshold=37).graph(
        allowed_document_version_ids={version_id}, force_refresh=True
    )

    by_title = {node.title: node for node in graph.nodes}
    assert set(by_title) >= {
        "Alpha",
        "Beta",
        "Guide",
        "Home",
        "First duplicate",
        "Second duplicate",
        "Isolated",
    }
    pairs = {(edge.source, edge.target): edge for edge in graph.edges}
    assert (by_title["Alpha"].id, by_title["Beta"].id) in pairs
    assert pairs[(by_title["Alpha"].id, by_title["Beta"].id)].provenance == (
        "relationship",
        "wikilink",
    )
    assert (by_title["Home"].id, by_title["Beta"].id) in pairs
    assert (by_title["Home"].id, by_title["Guide"].id) in pairs
    assert by_title["Isolated"].isolated is True
    assert graph.ambiguous_count == 1
    assert graph.unresolved_count == 1
    assert graph.small_graph_threshold == 37
    assert {item.target for item in graph.diagnostics} == {"Dupe", "Missing page"}

    restricted = WikiGraphService(store).graph(allowed_document_version_ids={str(uuid.uuid4())})
    assert "Alpha" not in {node.title for node in restricted.nodes}
    assert "Beta" not in {node.title for node in restricted.nodes}
    with pytest.raises(WikiPageNotFoundError):
        WikiGraphService(store).read_markdown_page(
            by_title["Alpha"].path,
            allowed_document_version_ids={str(uuid.uuid4())},
        )


def test_local_graph_uses_incoming_and_outgoing_edges_and_preserves_direction(
    tmp_path: Path,
) -> None:
    store = WikiStore(tmp_path / "knowledge")
    store.initialize()
    notes = store.wiki_root / "notes"
    notes.mkdir()
    (notes / "A.md").write_text("# A\n\n[[B]]\n")
    (notes / "B.md").write_text("# B\n\n[[C]]\n")
    (notes / "C.md").write_text("# C\n\n[[A]]\n")
    (notes / "D.md").write_text("# D\n\n[[C]]\n")
    service = WikiGraphService(store)

    depth_one = service.graph(
        allowed_document_version_ids=set(), root="C", depth=1, force_refresh=True
    )
    assert {node.title for node in depth_one.nodes} == {"A", "B", "C", "D"}
    assert {(edge.source, edge.target) for edge in depth_one.edges} == {
        (
            next(node.id for node in depth_one.nodes if node.title == "A"),
            next(node.id for node in depth_one.nodes if node.title == "B"),
        ),
        (
            next(node.id for node in depth_one.nodes if node.title == "B"),
            next(node.id for node in depth_one.nodes if node.title == "C"),
        ),
        (
            next(node.id for node in depth_one.nodes if node.title == "C"),
            next(node.id for node in depth_one.nodes if node.title == "A"),
        ),
        (
            next(node.id for node in depth_one.nodes if node.title == "D"),
            next(node.id for node in depth_one.nodes if node.title == "C"),
        ),
    }


def test_graph_cache_refreshes_after_external_edit_rename_and_delete(tmp_path: Path) -> None:
    store = WikiStore(tmp_path / "knowledge")
    store.initialize()
    notes = store.wiki_root / "notes"
    notes.mkdir()
    first = notes / "First.md"
    second = notes / "Second.md"
    first.write_text("# First\n\n[[Second]]\n")
    second.write_text("# Second\n")
    service = WikiGraphService(store)
    initial = service.graph(allowed_document_version_ids=set())
    assert initial.total_nodes == 2
    assert initial.total_edges == 1

    second.rename(notes / "Renamed.md")
    (notes / "Renamed.md").write_text("# Renamed\n")
    first.write_text("# First\n\n[[Renamed]]\n")
    renamed = service.graph(allowed_document_version_ids=set())
    assert renamed.freshness.revision != initial.freshness.revision
    assert {node.title for node in renamed.nodes} == {"First", "Renamed"}
    assert renamed.total_edges == 1

    (notes / "Renamed.md").unlink()
    deleted = service.graph(allowed_document_version_ids=set())
    assert deleted.total_nodes == 1
    assert deleted.total_edges == 0
    assert deleted.unresolved_count == 1


def test_markdown_detail_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    store = WikiStore(tmp_path / "knowledge")
    store.initialize()
    notes = store.wiki_root / "notes"
    notes.mkdir()
    page = notes / "Portable.md"
    page.write_text("# Portable\n\nSafe **Markdown** body.\n")
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (notes / "escape.md").symlink_to(outside)
    service = WikiGraphService(store)

    detail = service.read_markdown_page(
        "wiki/notes/Portable.md", allowed_document_version_ids=set()
    )
    assert detail.title == "Portable"
    assert "Safe **Markdown** body." in detail.content
    for unsafe in ("../outside.md", "wiki/notes/escape.md"):
        try:
            service.read_markdown_page(unsafe, allowed_document_version_ids=set())
        except WikiPageNotFoundError:
            pass
        else:
            raise AssertionError(f"unsafe Wiki path was readable: {unsafe}")
