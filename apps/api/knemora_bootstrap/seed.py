"""Seed and validate the isolated Development preset through Knemora's real pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Document, DocumentVersion, KnowledgeCompilationJob, User
from app.db.session import create_database_engine
from app.ingestion.service import IngestionService
from app.knowledge.compiler import KnowledgeCompiler
from app.knowledge.search import BM25WikiSearch
from app.knowledge.store import WikiStore
from app.knowledge.types import CompilationStatus
from app.llm import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
)
from knemora_bootstrap.development_preset import (
    EXPECTED_FACTS,
    EXPECTED_MIN_PAGES,
    PRESET_VERSION,
    build_catalog,
    manifest,
    render_source,
)


class PresetError(RuntimeError):
    """The deterministic preset could not be seeded or validated."""


class DevelopmentPresetProvider:
    """Translate known versioned demo records into compiler proposals without an LLM call."""

    def __init__(self) -> None:
        self.catalog = {page.key: page for page in build_catalog()}

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=False,
            structured_output=True,
            cancellation=False,
            max_context_tokens=128_000,
        )

    async def health(self) -> LLMHealth:
        return LLMHealth(healthy=True, provider="deterministic-preset", model="development-v1")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raw = request.messages[-1].content.removeprefix("UNTRUSTED_SOURCE_JSON\n")
        payload = json.loads(raw)
        pages: list[dict[str, Any]] = []
        for record in payload["untrusted_source_records"]:
            match = next(
                (
                    line.removeprefix("Preset key: ").strip()
                    for line in str(record["content"]).splitlines()
                    if line.startswith("Preset key: ")
                ),
                None,
            )
            if match is None:
                continue
            definition = self.catalog.get(match)
            if definition is None:
                raise PresetError(f"Unknown Development preset record key: {match}")
            ordinal = int(record["ordinal"])
            pages.append(
                {
                    "type": definition.kind,
                    "title": definition.title,
                    "aliases": [],
                    "topics": [
                        "Development",
                        definition.category,
                        "Synthetic Demo",
                        "Non-Production",
                    ],
                    "summary": definition.summary,
                    "claims": [
                        {
                            "key": "development_preset_fact",
                            "text": definition.claim,
                            "classification": "source_fact",
                            "source_record_ordinals": [ordinal],
                        }
                    ],
                    "relationships": [
                        {
                            "relation": relation,
                            "target_title": target,
                            "source_record_ordinals": [ordinal],
                        }
                        for relation, target in definition.relationships
                    ],
                }
            )
        if not pages:
            raise PresetError("A compiler batch contained no recognized demo records.")
        return ChatResponse(
            message=ChatMessage(
                role="assistant", content=json.dumps({"pages": pages, "warnings": []})
            ),
            model="development-v1",
            finish_reason="stop",
            usage=ChatUsage(),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        del request
        if False:
            yield ChatChunk(model="development-v1")


def _existing_preset_result(
    session: Session, settings: Settings, preset_root: Path
) -> dict[str, Any] | None:
    """Return a validated owner-linked preset without rebuilding it."""

    source = preset_root / f"northstar-development-v{PRESET_VERSION}.md"
    manifest_path = preset_root / "manifest.json"
    if not source.is_file() or not manifest_path.is_file() or not settings.knowledge_path.is_dir():
        return None
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    owner = session.scalar(select(User).where(User.email == settings.default_user_email))
    if owner is None:
        return None
    version_ids = {
        str(version_id)
        for version_id in session.scalars(
            select(DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(
                KnowledgeCompilationJob,
                KnowledgeCompilationJob.document_version_id == DocumentVersion.id,
            )
            .where(
                Document.owner_id == owner.id,
                Document.deleted_at.is_(None),
                DocumentVersion.sha256 == checksum,
                KnowledgeCompilationJob.status == CompilationStatus.COMPLETED,
            )
        )
    }
    if not version_ids:
        return None
    try:
        result = validate_development_preset(
            settings.knowledge_path,
            supported_by_document_version_ids=version_ids,
        )
    except (OSError, PresetError):
        return None
    return {**result, "created": False}


def prepare_preset_files(preset_root: Path) -> Path:
    """Write inspectable deterministic inputs for the native Development workspace."""

    preset_root.mkdir(parents=True, exist_ok=True)
    source = preset_root / f"northstar-development-v{PRESET_VERSION}.md"
    expected = preset_root / "manifest.json"
    source.write_bytes(render_source())
    expected.write_text(json.dumps(manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return source


async def seed_development_preset(
    settings: Settings, *, engine: Engine | None = None, preset_root: Path
) -> dict[str, Any]:
    """Ingest one immutable synthetic handbook and compile its 120 connected pages."""

    owned_engine = engine is None
    active_engine = engine or create_database_engine(settings.database_url)
    try:
        with Session(active_engine) as session:
            existing = _existing_preset_result(session, settings, preset_root)
            if existing is not None:
                return existing
            source = prepare_preset_files(preset_root)
            ingestion = IngestionService(session=session, settings=settings)
            owner = ingestion.get_or_create_local_user()
            result = ingestion.ingest(
                owner=owner,
                filename=source.name,
                declared_content_type="text/markdown",
                data=source.read_bytes(),
            )
            if result.job.status != "READY_FOR_COMPILATION":
                raise PresetError(result.job.error or "Synthetic source ingestion failed.")
            compiler = KnowledgeCompiler(
                session=session,
                settings=settings,
                provider=DevelopmentPresetProvider(),
            )
            job = await compiler.compile(
                owner_id=owner.id,
                document_version_id=result.version.id,
            )
            if job.status != CompilationStatus.COMPLETED:
                raise PresetError(job.error or "Synthetic knowledge compilation failed.")
        return {**validate_development_preset(settings.knowledge_path), "created": True}
    finally:
        if owned_engine:
            active_engine.dispose()


def validate_development_preset(
    knowledge_path: Path,
    *,
    supported_by_document_version_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate page count, schema markers, graph quality, retrieval, and provenance."""

    store = WikiStore(knowledge_path)
    pages = [
        page
        for _, page in store.page_snapshot(
            supported_by_document_version_ids=supported_by_document_version_ids
        )
    ]
    demo_pages = [page for page in pages if "Synthetic Demo" in page.topics]
    if len(demo_pages) < EXPECTED_MIN_PAGES:
        raise PresetError(
            f"Expected at least {EXPECTED_MIN_PAGES} demo pages, found {len(demo_pages)}."
        )
    if any(
        "Development" not in page.topics or "Non-Production" not in page.topics
        for page in demo_pages
    ):
        raise PresetError("One or more demo pages are missing synthetic isolation markers.")
    if any(
        not page.provenance or any(not claim.provenance for claim in page.claims)
        for page in demo_pages
    ):
        raise PresetError("One or more demo pages are missing source provenance.")

    ids = {page.id for page in demo_pages}
    degrees = {
        page.title: len({link.target_id for link in page.relationships if link.target_id in ids})
        for page in demo_pages
    }
    incoming = {page.id: 0 for page in demo_pages}
    for page in demo_pages:
        for link in page.relationships:
            if link.target_id in incoming:
                incoming[link.target_id] += 1
    connected = sum(bool(page.relationships) or incoming[page.id] > 0 for page in demo_pages)
    orphans = len(demo_pages) - connected
    categories = {
        topic
        for page in demo_pages
        for topic in page.topics
        if topic not in {"Development", "Synthetic Demo", "Non-Production"}
    }
    if connected / len(demo_pages) < 0.95 or orphans > 5:
        raise PresetError(
            f"Demo graph quality failed: {connected} connected pages and {orphans} orphans."
        )
    required_hubs = (
        "Development",
        "Architecture",
        "Services",
        "Teams",
        "ADRs",
        "Runbooks",
        "Projects",
    )
    if any(
        degrees.get(title, 0)
        + incoming[next(page.id for page in demo_pages if page.title == title)]
        < 5
        for title in required_hubs
    ):
        raise PresetError("One or more expected demo graph hubs has insufficient degree.")
    if len(categories) < 15:
        raise PresetError("The demo graph does not contain enough topical clusters.")

    all_text = " ".join(claim.text for page in demo_pages for claim in page.claims)
    missing_facts = [value for value in EXPECTED_FACTS.values() if value not in all_text]
    if missing_facts:
        raise PresetError(f"Anchor facts are missing from compiled knowledge: {missing_facts}")
    search = BM25WikiSearch(store)
    hits = search.search(
        query="ORBIT-LANTERN Cedar Gate DEV-POL-017 Wednesday",
        page_types=(),
        topics=("Development",),
        limit=10,
        allowed_document_version_ids=None,
    )
    if not hits:
        raise PresetError("The demo lexical index did not retrieve anchor knowledge.")
    lint = store.lint()
    if lint.errors:
        raise PresetError(f"The Development Wiki has {lint.errors} lint errors.")
    return {
        "preset": "development",
        "version": PRESET_VERSION,
        "pages": len(demo_pages),
        "connected_pages": connected,
        "orphans": orphans,
        "clusters": len(categories),
        "lint_errors": lint.errors,
        "lint_warnings": lint.warnings,
        "retrieval_hits": len(hits),
    }


def seed_sync(
    settings: Settings, *, engine: Engine | None = None, preset_root: Path
) -> dict[str, Any]:
    return asyncio.run(seed_development_preset(settings, engine=engine, preset_root=preset_root))
