from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import KnowledgeCompilationJob, SourceRecord, WikiChange
from app.ingestion.service import IngestionService
from app.knowledge.compiler import SYSTEM_PROMPT, KnowledgeCompiler
from app.knowledge.store import WikiStore
from app.knowledge.types import (
    ClaimClassification,
    ClaimStatus,
    PageKind,
    ProvenanceRef,
    WikiClaim,
    WikiPage,
    WikiRelationship,
)
from app.llm import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
)
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"


class ProposalProvider:
    def __init__(self, *outputs: dict[str, object] | str) -> None:
        self.outputs = [
            output if isinstance(output, str) else json.dumps(output) for output in outputs
        ]
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=True,
            structured_output=True,
            cancellation=True,
            max_context_tokens=4096,
        )

    async def health(self) -> LLMHealth:
        return LLMHealth(healthy=True, provider="fake", model="fake-knowledge")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("The compiler made an unexpected model call.")
        return ChatResponse(
            message=ChatMessage(role="assistant", content=self.outputs.pop(0)),
            model="fake-knowledge",
            finish_reason="stop",
            usage=ChatUsage(),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        del request
        if False:
            yield ChatChunk(model="fake-knowledge")


class TruncatingProposalProvider(ProposalProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("The compiler made an unexpected model call.")
        truncated = len(self.requests) == 1
        completion_tokens = request.max_tokens if truncated else 400
        return ChatResponse(
            message=ChatMessage(role="assistant", content=self.outputs.pop(0)),
            model="fake-knowledge",
            finish_reason="length" if truncated else "stop",
            usage=ChatUsage(
                prompt_tokens=512,
                completion_tokens=completion_tokens,
                total_tokens=512 + completion_tokens,
            ),
        )


def build_app(tmp_path: Path, provider: ProposalProvider) -> FastAPI:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        llm_model="fake-knowledge",
        authentication_required=False,
        source_store_path=tmp_path / "sources",
        knowledge_path=tmp_path / "knowledge",
        knowledge_compilation_batch_chars=2_000,
    )
    return create_app(settings=settings, provider=provider, engine=engine)


async def upload_and_compile(
    client: AsyncClient, filename: str, content: bytes
) -> tuple[dict[str, Any], dict[str, Any]]:
    uploaded = await client.post(
        "/api/v1/documents",
        files={"file": (filename, content, "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    compiled = await client.post(
        f"/api/v1/document-versions/{uploaded.json()['document_version_id']}/compile"
    )
    assert compiled.status_code == 200, compiled.text
    return uploaded.json(), compiled.json()


def acme_proposal(*, headquarters: str = "Valletta") -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "entity",
                "title": "Acme Corporation",
                "aliases": ["ACME"],
                "summary": "A medicine distribution company.",
                "claims": [
                    {
                        "key": "headquarters",
                        "text": f"Acme Corporation is headquartered in {headquarters}.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [
                    {
                        "relation": "uses",
                        "target_title": "Cold Chain",
                        "source_record_ordinals": [1],
                    }
                ],
            },
            {
                "type": "concept",
                "title": "Cold Chain",
                "aliases": ["Temperature-controlled distribution"],
                "summary": "Controls for temperature-sensitive distribution.",
                "claims": [
                    {
                        "key": "purpose",
                        "text": "Cold-chain controls protect temperature-sensitive medicine.",
                        "classification": "synthesis",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [
                    {
                        "relation": "used_by",
                        "target_title": "Acme Corporation",
                        "source_record_ordinals": [1],
                    }
                ],
            },
        ],
        "warnings": [],
    }


def standard_proposal() -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "entity",
                "title": "ACME",
                "aliases": ["Acme Corporation"],
                "summary": "A medicine distribution company.",
                "claims": [
                    {
                        "key": "quality_review",
                        "text": "ACME completed a Good Distribution Practice review.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [
                    {
                        "relation": "uses",
                        "target_title": "Cold Chain",
                        "source_record_ordinals": [1],
                    }
                ],
            },
            {
                "type": "topic",
                "title": "Good Distribution Practice",
                "aliases": ["GDP"],
                "summary": "Quality requirements for medicine distribution.",
                "claims": [
                    {
                        "key": "scope",
                        "text": "GDP review covers temperature monitoring and excursions.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [
                    {
                        "relation": "applies_to",
                        "target_title": "ACME",
                        "source_record_ordinals": [1],
                    }
                ],
            },
        ],
        "warnings": [],
    }


def conflict_proposal() -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "entity",
                "title": "ACME",
                "aliases": ["Acme Corporation"],
                "summary": "A medicine distribution company.",
                "claims": [
                    {
                        "key": "headquarters",
                        "text": "Acme Corporation is headquartered in Milan.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [],
            }
        ],
        "warnings": ["Source conflicts with an existing headquarters claim."],
    }


def project_aurora_proposal() -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "topic",
                "title": "Project Aurora",
                "aliases": [],
                "topics": [],
                "summary": "A governed release project.",
                "claims": [
                    {
                        "key": "release_window",
                        "text": "Project Aurora releases on Friday at 14:00 UTC.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [],
            }
        ],
        "warnings": [],
    }


def contaminated_skills_proposal() -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "topic",
                "title": "Project Aurora",
                "aliases": [],
                "topics": [],
                "summary": "A governed release project.",
                "claims": [
                    {
                        "key": "launch_review",
                        "text": "Project Aurora assigns its launch review to Mira Chen.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [],
            }
        ],
        "warnings": [],
    }


def federico_skills_proposal() -> dict[str, object]:
    pages: list[dict[str, object]] = [
        {
            "type": "entity",
            "title": "Avery Morgan",
            "aliases": ["Federico"],
            "topics": ["software development"],
            "summary": "A designer and fullstack developer.",
            "claims": [
                {
                    "key": "technical_context",
                    "text": "Avery Morgan works with TypeScript, JavaScript, and SQL.",
                    "classification": "source_fact",
                    "source_record_ordinals": [1],
                }
            ],
            "relationships": [
                {
                    "relation": "uses",
                    "target_title": title,
                    "source_record_ordinals": [1],
                }
                for title in ("TypeScript", "JavaScript", "SQL")
            ],
        }
    ]
    pages.extend(
        {
            "type": "concept",
            "title": title,
            "aliases": [],
            "topics": ["programming"],
            "summary": f"{title} in Avery Morgan's technical context.",
            "claims": [
                {
                    "key": "used_by",
                    "text": f"Avery Morgan uses {title} in their work context.",
                    "classification": "source_fact",
                    "source_record_ordinals": [1],
                }
            ],
            "relationships": [],
        }
        for title in ("TypeScript", "JavaScript", "SQL")
    )
    return {"pages": pages, "warnings": []}


def test_related_sources_build_one_evolving_wiki_with_conflict_provenance(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(acme_proposal(), standard_proposal(), conflict_proposal())
        app = build_app(tmp_path, provider)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first_upload, first = await upload_and_compile(
                client,
                "acme-profile.md",
                (FIXTURES / "acme-profile.md").read_bytes(),
            )
            _, second = await upload_and_compile(
                client,
                "cold-chain-standard.md",
                (FIXTURES / "cold-chain-standard.md").read_bytes(),
            )
            _, third = await upload_and_compile(
                client,
                "acme-audit.md",
                (FIXTURES / "acme-audit.md").read_bytes(),
            )
            pages_response = await client.get("/api/v1/wiki/pages")
            page_index_response = await client.get(
                "/api/v1/wiki/page-index?page=1&page_limit=2&q=acme&kind=entity"
            )
            acme_response = await client.get("/api/v1/wiki/pages/ACME")
            backlink_response = await client.get("/api/v1/wiki/pages/ACME/backlinks")
            graph_response = await client.get("/api/v1/wiki/graph")
            local_graph_response = await client.get("/api/v1/wiki/graph?root=ACME&depth=1")
            lint_response = await client.get("/api/v1/wiki/lint")
            repeated = await client.post(
                f"/api/v1/document-versions/{first_upload['document_version_id']}/compile"
            )
            observed = await client.get(f"/api/v1/knowledge-compilation-jobs/{first['id']}")

        assert first["status"] == "COMPLETED"
        assert len(first["report"]["pages_created"]) == 2
        assert second["status"] == "COMPLETED"
        assert len(second["report"]["pages_created"]) == 1
        assert len(second["report"]["pages_updated"]) == 1
        assert third["status"] == "COMPLETED"
        assert len(third["report"]["conflicts"]) == 1
        assert repeated.json()["id"] == first["id"]
        assert observed.json()["status"] == "COMPLETED"
        assert len(provider.requests) == 3

        pages = pages_response.json()
        assert len(pages) == 3
        assert {page["title"] for page in pages} == {
            "Acme Corporation",
            "Cold Chain",
            "Good Distribution Practice",
        }
        page_index = page_index_response.json()
        assert page_index["page"] == 1
        assert page_index["page_limit"] == 2
        assert page_index["total"] == 1
        assert page_index["total_pages"] == 1
        assert [page["title"] for page in page_index["items"]] == ["Acme Corporation"]
        assert acme_response.json()["title"] == "Acme Corporation"
        assert {page["title"] for page in backlink_response.json()} == {
            "Cold Chain",
            "Good Distribution Practice",
        }
        graph = graph_response.json()
        assert graph["mode"] == "global"
        assert graph["total_nodes"] == 3
        assert graph["total_edges"] == 3
        assert graph["truncated"] is False
        assert graph["small_graph_threshold"] == 50
        assert {node["title"] for node in graph["nodes"]} == {
            "Acme Corporation",
            "Cold Chain",
            "Good Distribution Practice",
        }
        assert all(node["detail_reference"].startswith("/knowledge/") for node in graph["nodes"])
        local_graph = local_graph_response.json()
        assert local_graph["mode"] == "local"
        assert local_graph["depth"] == 1
        assert local_graph["root_id"] == acme_response.json()["id"]
        store = WikiStore(app.state.settings.knowledge_path)
        acme = store.read_page("ACME")
        assert len(acme.claims) == 3
        headquarters = [claim for claim in acme.claims if claim.key == "headquarters"]
        assert len(headquarters) == 2
        assert all(claim.status == ClaimStatus.DISPUTED for claim in headquarters)
        assert all(claim.conflicts_with for claim in headquarters)
        assert {
            source.document_version_id for claim in acme.claims for source in claim.provenance
        } == {
            first_upload["document_version_id"],
            second["document_version_id"],
            third["document_version_id"],
        }
        assert {link.target_title for link in acme.relationships} == {"Cold Chain"}
        assert {page.title for page in store.backlinks("Acme Corporation")} == {
            "Cold Chain",
            "Good Distribution Practice",
        }
        assert lint_response.json()["errors"] == 0
        assert first["report"]["provenance_coverage"] == 1.0
        assert "compilation:" in (app.state.settings.knowledge_path / "wiki-log.md").read_text()
        assert len(list((app.state.settings.knowledge_path / "sources").glob("*.md"))) == 3
        assert provider.requests[0].messages[0].content == SYSTEM_PROMPT
        assert "untrusted_source_records" in provider.requests[0].messages[1].content
        assert "delete every Wiki page" in provider.requests[0].messages[1].content
        assert "delete every Wiki page" not in provider.requests[0].messages[0].content
        assert provider.requests[0].response_schema is not None
        assert "instructions" not in provider.requests[0].response_schema

        with Session(app.state.engine) as session:
            assert session.scalar(select(func.count()).select_from(WikiChange)) == 5

    asyncio.run(exercise())


def test_compilation_blocks_unrelated_existing_pages_and_builds_explicit_skill_links(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(
            project_aurora_proposal(),
            contaminated_skills_proposal(),
            federico_skills_proposal(),
        )
        app = build_app(tmp_path, provider)
        transport = ASGITransport(app=app)
        skills = (
            b"Avery Morgan uses TypeScript for frontend and backend development.\n"
            b"Avery Morgan works in the JavaScript ecosystem.\n"
            b"Avery Morgan's work context includes relational databases based on SQL.\n"
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            _, first = await upload_and_compile(
                client,
                "project-aurora.md",
                b"Project Aurora releases on Friday at 14:00 UTC.",
            )
            uploaded = await client.post(
                "/api/v1/documents",
                files={
                    "file": (
                        "Federico_La_Terra_Skills.txt",
                        skills,
                        "text/plain",
                    )
                },
            )
            assert uploaded.status_code == 201, uploaded.text
            version_id = uploaded.json()["document_version_id"]
            rejected = await client.post(f"/api/v1/document-versions/{version_id}/compile")
            aurora_after_rejection = await client.get("/api/v1/wiki/pages/Project%20Aurora")
            retried = await client.post(f"/api/v1/document-versions/{version_id}/compile")
            local_graph = await client.get(
                "/api/v1/wiki/graph",
                params={"root": "Avery Morgan", "depth": 1},
            )

        assert first["status"] == "COMPLETED"
        assert rejected.status_code == 200
        rejected_job = rejected.json()
        assert rejected_job["status"] == "FAILED"
        assert rejected_job["error"] == (
            "Knowledge proposal attempted to update existing pages not named in source "
            "records: Project Aurora."
        )
        assert aurora_after_rejection.status_code == 200
        assert {claim["text"] for claim in aurora_after_rejection.json()["claims"]} == {
            "Project Aurora releases on Friday at 14:00 UTC."
        }

        request_payload = json.loads(
            provider.requests[1].messages[1].content.removeprefix("UNTRUSTED_SOURCE_JSON\n")
        )
        assert "existing_wiki_pages" not in request_payload
        assert request_payload["existing_page_identities"] == []

        retried_job = retried.json()
        assert retried_job["status"] == "COMPLETED"
        assert retried_job["attempt_count"] == 2
        assert retried_job["report"]["links_created"] == 3
        graph = local_graph.json()
        assert graph["mode"] == "local"
        assert {node["title"] for node in graph["nodes"]} == {
            "Avery Morgan",
            "JavaScript",
            "SQL",
            "TypeScript",
        }
        assert len(graph["edges"]) == 3
        assert all("uses" in edge["relations"] for edge in graph["edges"])

    asyncio.run(exercise())


def test_reprocess_preserves_source_record_identity_and_forces_a_new_compilation_attempt(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(acme_proposal(), acme_proposal())
        app = build_app(tmp_path, provider)
        transport = ASGITransport(app=app)
        source = b"Acme Corporation is headquartered in Valletta and uses Cold Chain."
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/v1/documents",
                files={"file": ("acme.md", source, "text/markdown")},
            )
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            version_id = uuid.UUID(body["document_version_id"])
            first = await client.post(f"/api/v1/document-versions/{version_id}/compile")
            assert first.status_code == 200, first.text
            assert first.json()["status"] == "COMPLETED"

            with Session(app.state.engine) as session:
                before_ids = tuple(
                    session.scalars(
                        select(SourceRecord.id)
                        .where(SourceRecord.document_version_id == version_id)
                        .order_by(SourceRecord.ordinal)
                    )
                )

            reprocessed = await client.post(
                f"/api/v1/ingestion-jobs/{body['ingestion_job_id']}/reprocess"
            )
            original = await client.get(f"/api/v1/document-versions/{version_id}/original")
            second = await client.post(f"/api/v1/document-versions/{version_id}/compile")

        assert reprocessed.status_code == 200, reprocessed.text
        assert reprocessed.json()["status"] == "READY_FOR_COMPILATION"
        assert original.content == source
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "COMPLETED"
        assert second.json()["attempt_count"] == 2
        assert len(provider.requests) == 2
        with Session(app.state.engine) as session:
            after_ids = tuple(
                session.scalars(
                    select(SourceRecord.id)
                    .where(SourceRecord.document_version_id == version_id)
                    .order_by(SourceRecord.ordinal)
                )
            )
            compilation = session.scalar(
                select(KnowledgeCompilationJob).where(
                    KnowledgeCompilationJob.document_version_id == version_id
                )
            )
            assert compilation is not None
            assert compilation.status == "COMPLETED"
        assert after_ids == before_ids

    asyncio.run(exercise())


class FailOnceStore(WikiStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.fail_next_page_write = True

    def _write_page(self, path: Path, page: WikiPage) -> None:
        super()._write_page(path, page)
        if self.fail_next_page_write:
            self.fail_next_page_write = False
            raise OSError("simulated interruption")


def test_interrupted_compilation_rolls_back_and_reuses_validated_proposal(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(acme_proposal())
        app = build_app(tmp_path, provider)
        settings = app.state.settings
        store = FailOnceStore(settings.knowledge_path)
        with Session(app.state.engine) as session:
            ingestion = IngestionService(session=session, settings=settings)
            owner = ingestion.get_or_create_local_user()
            source = ingestion.ingest(
                owner=owner,
                filename="acme-profile.md",
                declared_content_type="text/markdown",
                data=(FIXTURES / "acme-profile.md").read_bytes(),
            )
            compiler = KnowledgeCompiler(
                session=session,
                settings=settings,
                provider=provider,
                store=store,
            )
            failed = await compiler.compile(
                owner_id=owner.id, document_version_id=source.version.id
            )
            assert failed.status == "FAILED"
            assert store.list_pages() == ()
            recovered = await compiler.compile(
                owner_id=owner.id, document_version_id=source.version.id
            )
            assert recovered.status == "COMPLETED"
            assert recovered.attempt_count == 2
            assert len(store.list_pages()) == 2
            assert len(provider.requests) == 1

    asyncio.run(exercise())


def test_invalid_structured_model_output_is_failed_and_retryable(tmp_path: Path) -> None:
    async def exercise() -> None:
        provider = ProposalProvider("not valid JSON", acme_proposal())
        app = build_app(tmp_path, provider)
        settings = app.state.settings
        with Session(app.state.engine) as session:
            ingestion = IngestionService(session=session, settings=settings)
            owner = ingestion.get_or_create_local_user()
            source = ingestion.ingest(
                owner=owner,
                filename="acme-profile.md",
                declared_content_type="text/markdown",
                data=(FIXTURES / "acme-profile.md").read_bytes(),
            )
            compiler = KnowledgeCompiler(session=session, settings=settings, provider=provider)
            failed = await compiler.compile(
                owner_id=owner.id, document_version_id=source.version.id
            )
            assert failed.status == "FAILED"
            assert failed.proposal is None
            assert failed.error == (
                "Local model output did not match the structured knowledge proposal schema."
            )
            assert WikiStore(settings.knowledge_path).list_pages() == ()
            retried = await compiler.compile(
                owner_id=owner.id, document_version_id=source.version.id
            )
            assert retried.status == "COMPLETED"
            assert retried.attempt_count == 2
            assert len(provider.requests) == 2

    asyncio.run(exercise())


def test_truncated_structured_output_retries_with_larger_budget(tmp_path: Path) -> None:
    async def exercise() -> None:
        provider = TruncatingProposalProvider('{"pages":[', acme_proposal())
        app = build_app(tmp_path, provider)
        settings = app.state.settings
        with Session(app.state.engine) as session:
            ingestion = IngestionService(session=session, settings=settings)
            owner = ingestion.get_or_create_local_user()
            source = ingestion.ingest(
                owner=owner,
                filename="acme-profile.md",
                declared_content_type="text/markdown",
                data=(FIXTURES / "acme-profile.md").read_bytes(),
            )
            compiler = KnowledgeCompiler(
                session=session,
                settings=settings,
                provider=provider,
            )
            compiled = await compiler.compile(
                owner_id=owner.id, document_version_id=source.version.id
            )
            status = compiled.status

        assert status == "COMPLETED"
        assert [request.max_tokens for request in provider.requests] == [2048, 3328]

    asyncio.run(exercise())


def test_single_record_compilation_normalizes_model_ordinals(tmp_path: Path) -> None:
    async def exercise() -> None:
        proposal = json.loads(
            json.dumps(acme_proposal()).replace(
                '"source_record_ordinals": [1]', '"source_record_ordinals": [2]'
            )
        )
        provider = ProposalProvider(proposal)
        app = build_app(tmp_path, provider)
        settings = app.state.settings
        with Session(app.state.engine) as session:
            ingestion = IngestionService(session=session, settings=settings)
            owner = ingestion.get_or_create_local_user()
            source = ingestion.ingest(
                owner=owner,
                filename="acme-profile.md",
                declared_content_type="text/markdown",
                data=(FIXTURES / "acme-profile.md").read_bytes(),
            )
            compiled = await KnowledgeCompiler(
                session=session,
                settings=settings,
                provider=provider,
            ).compile(owner_id=owner.id, document_version_id=source.version.id)
            status = compiled.status
            report = compiled.report

        assert status == "COMPLETED"
        assert report is not None
        assert report["warnings"] == [
            "Model source ordinals were normalized to the only source record in this batch."
        ]

    asyncio.run(exercise())


def fake_provenance() -> ProvenanceRef:
    return ProvenanceRef(
        source_record_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        original_filename="source.md",
        sha256="a" * 64,
        locator={"heading_path": ["Source"]},
        parser_name="markdown",
        parser_version="1",
        compilation_version="test/1",
        compiled_at=datetime.now(UTC),
    )


def fake_page(title: str, kind: PageKind = PageKind.CONCEPT) -> WikiPage:
    page_id = str(uuid.uuid4())
    provenance = (fake_provenance(),)
    return WikiPage(
        id=page_id,
        type=kind,
        title=title,
        aliases=(),
        summary=f"Summary for {title}.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="test/1",
        provenance=provenance,
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="definition",
                text=f"{title} is a test concept.",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=provenance,
            ),
        ),
    )


def test_typed_wiki_operations_and_lint_detect_broken_links_and_orphans(
    tmp_path: Path,
) -> None:
    store = WikiStore(tmp_path / "knowledge")
    alpha = fake_page("Alpha")
    beta = fake_page("Beta")
    store.create_page(alpha)
    store.create_page(beta)
    assert {page.title for page in store.list_pages()} == {"Alpha", "Beta"}
    assert store.read_page(alpha.id).title == "Alpha"

    alpha = alpha.model_copy(update={"aliases": ("First",), "updated_at": datetime.now(UTC)})
    store.update_page(alpha)
    assert store.resolve_page("first").id == alpha.id  # type: ignore[union-attr]
    store.link_pages("Alpha", "Beta", "relates_to")
    assert [page.title for page in store.backlinks("Beta")] == ["Alpha"]
    store.rebuild_index()
    assert store.lint().errors == 0

    orphan = fake_page("Orphan")
    store.create_page(orphan)
    lint = store.lint()
    assert any(issue.code == "orphan-page" and "Orphan" in issue.message for issue in lint.issues)

    broken = WikiRelationship(
        relation="references",
        target_id=str(uuid.uuid4()),
        target_title="Missing Page",
        provenance=alpha.provenance,
    )
    alpha = store.read_page("Alpha").model_copy(update={"relationships": (broken,)})
    store.update_page(alpha)
    lint = store.lint()
    assert {issue.code for issue in lint.issues} >= {
        "broken-wikilink",
        "broken-relationship",
    }


def test_compilation_job_table_is_registered() -> None:
    assert KnowledgeCompilationJob.__tablename__ in Base.metadata.tables


def test_legacy_wiki_metadata_is_copied_without_deleting_original(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    legacy = root / ".pharmatrace-wiki"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text('{"schema_version": 1, "revision": 7}\n')

    store = WikiStore(root)

    assert store.internal_root == root / ".knemora"
    assert (store.internal_root / "state.json").read_text() == (legacy / "state.json").read_text()
    assert legacy.exists()
