from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import SourceRecord
from app.ingestion.service import IngestionResult, IngestionService
from app.knowledge.access import KnowledgeAccessService
from app.knowledge.analysis import DatasetAnalysisRequest, DatasetAnalysisService
from app.knowledge.compiler import KnowledgeCompiler
from app.knowledge.errors import InvalidDatasetAnalysisError
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
    ChatToolCall,
    ChatToolDefinition,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
)
from app.main import create_app
from knowledge_agent.agent import _conflict_evidence_answer, _forced_retrieval_call


def build_app(tmp_path: Path, provider: object | None = None) -> FastAPI:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        llm_model="fake-local",
        authentication_required=False,
        source_store_path=tmp_path / "sources",
        knowledge_path=tmp_path / "knowledge",
    )
    return create_app(settings=settings, provider=provider, engine=engine)  # type: ignore[arg-type]


def ingest_text(
    app: FastAPI, content: bytes = b"Acme source evidence"
) -> tuple[uuid.UUID, SourceRecord]:
    with Session(app.state.engine) as session:
        service = IngestionService(session=session, settings=app.state.settings)
        owner = service.get_or_create_local_user()
        result = service.ingest(
            owner=owner,
            filename="company.txt",
            declared_content_type="text/plain",
            data=content,
        )
        record = session.scalar(
            select(SourceRecord).where(SourceRecord.document_version_id == result.version.id)
        )
        assert record is not None
        return owner.id, record


def provenance(record: SourceRecord) -> ProvenanceRef:
    return ProvenanceRef(
        source_record_id=str(record.id),
        document_id=str(record.document_version_id),
        document_version_id=str(record.document_version_id),
        original_filename="company.txt",
        sha256="a" * 64,
        locator=record.locator,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        compilation_version="test/1",
        compiled_at=datetime.now(UTC),
    )


def seed_wiki(app: FastAPI, record: SourceRecord) -> dict[str, WikiPage]:
    source = (provenance(record),)
    acme_id = str(uuid.uuid4())
    cold_id = str(uuid.uuid4())
    gdp_id = str(uuid.uuid4())
    valletta_claim_id = str(uuid.uuid4())
    milan_claim_id = str(uuid.uuid4())
    acme = WikiPage(
        id=acme_id,
        type=PageKind.ENTITY,
        title="Acme Corporation",
        aliases=("ACME",),
        topics=("medicine distribution", "supply chain"),
        summary="A medicine distribution company based in Valletta.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="test/1",
        provenance=source,
        claims=(
            WikiClaim(
                id=valletta_claim_id,
                key="headquarters",
                text="Acme Corporation is headquartered in Valletta.",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=source,
                conflicts_with=(milan_claim_id,),
            ),
            WikiClaim(
                id=milan_claim_id,
                key="headquarters",
                text="A later source places Acme Corporation in Milan.",
                classification=ClaimClassification.SOURCE_FACT,
                status=ClaimStatus.DISPUTED,
                provenance=source,
                conflicts_with=(valletta_claim_id,),
            ),
        ),
        relationships=(
            WikiRelationship(
                relation="uses",
                target_id=cold_id,
                target_title="Cold Chain",
                provenance=source,
            ),
        ),
    )
    cold = WikiPage(
        id=cold_id,
        type=PageKind.CONCEPT,
        title="Cold Chain",
        aliases=("Temperature-controlled distribution",),
        topics=("logistics",),
        summary="Controls for temperature-sensitive medicines.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="test/1",
        provenance=source,
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="purpose",
                text="Cold-chain controls protect temperature-sensitive medicines.",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=source,
            ),
        ),
        relationships=(
            WikiRelationship(
                relation="used_by",
                target_id=acme_id,
                target_title="Acme Corporation",
                provenance=source,
            ),
        ),
    )
    gdp = WikiPage(
        id=gdp_id,
        type=PageKind.TOPIC,
        title="Good Distribution Practice",
        aliases=("GDP",),
        topics=("quality",),
        summary="Quality requirements for medicine distribution.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        compilation_version="test/1",
        provenance=source,
        claims=(
            WikiClaim(
                id=str(uuid.uuid4()),
                key="scope",
                text="GDP covers temperature monitoring and excursions.",
                classification=ClaimClassification.SOURCE_FACT,
                provenance=source,
            ),
        ),
        relationships=(
            WikiRelationship(
                relation="applies_to",
                target_id=acme_id,
                target_title="Acme Corporation",
                provenance=source,
            ),
        ),
    )
    store = WikiStore(app.state.settings.knowledge_path)
    store.apply_pages_transactionally((acme, cold, gdp))
    return {"acme": acme, "cold": cold, "gdp": gdp}


def test_bm25_identity_graph_and_source_retrieval_are_bounded_and_provenanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(tmp_path)
    owner_id, record = ingest_text(app)
    pages = seed_wiki(app, record)

    with Session(app.state.engine) as session:
        access = KnowledgeAccessService(
            session=session, settings=app.state.settings, owner_id=owner_id
        )
        retrieval = access.retrieval()
        with monkeypatch.context() as patch:
            patch.setattr(
                retrieval.store,
                "read_page",
                lambda _identifier: pytest.fail(
                    "search authorization must not resolve every indexed page separately"
                ),
            )
            alias_hits = retrieval.search(query="ACME")
        lexical_hits = retrieval.search(query="temperature medicines")
        topic_hits = retrieval.search(query="", page_types=(PageKind.TOPIC,), topics=("quality",))
        evidence = retrieval.read_page("ACME", max_claims=10)
        evidence_by_search_path = retrieval.read_page(alias_hits[0].path, max_claims=10)
        related = retrieval.related_pages("GDP", max_depth=2, limit=10)
        backlinks = retrieval.backlinks("Acme Corporation", limit=10)
        source = access.read_source_reference(str(record.id), max_chars=8)

    assert alias_hits[0].id == pages["acme"].id
    assert alias_hits[0].retrieval_mode == "identity"
    assert lexical_hits[0].id == pages["cold"].id
    assert [item.id for item in topic_hits] == [pages["gdp"].id]
    assert topic_hits[0].retrieval_mode == "structured_index"
    assert {claim.status for claim in evidence.claims} == {"supported", "disputed"}
    assert evidence_by_search_path.id == evidence.id
    assert all(claim.citations for claim in evidence.claims)
    assert {item.id for item in related} >= {pages["acme"].id, pages["cold"].id}
    assert {item.id for item in backlinks} == {pages["cold"].id, pages["gdp"].id}
    assert source.content == "Acme sou"
    assert source.truncated is True

    index = json.loads(
        (app.state.settings.knowledge_path / ".knemora/search-index/pages.json").read_text()
    )
    assert index["schema_version"] == 2
    assert index["pages"][0]["fields"]


def test_related_page_traversal_parses_each_vault_page_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(tmp_path)
    owner_id, record = ingest_text(app)
    pages = seed_wiki(app, record)
    store = WikiStore(app.state.settings.knowledge_path)
    parsed: list[Path] = []
    original = store._parse_page

    def counted(path: Path) -> WikiPage:
        parsed.append(path)
        return original(path)

    monkeypatch.setattr(store, "_parse_page", counted)
    with Session(app.state.engine) as session:
        retrieval = KnowledgeAccessService(
            session=session, settings=app.state.settings, owner_id=owner_id
        ).retrieval()
        retrieval.store = store
        related = retrieval.related_pages(pages["gdp"].id, max_depth=2, limit=10)

    assert {item.id for item in related} >= {pages["acme"].id, pages["cold"].id}
    assert len(parsed) == 3


def ingest_dataset(
    app: FastAPI, *, filename: str, content_type: str, data: bytes
) -> IngestionResult:
    with Session(app.state.engine) as session:
        service = IngestionService(session=session, settings=app.state.settings)
        owner = service.get_or_create_local_user()
        return service.ingest(
            owner=owner,
            filename=filename,
            declared_content_type=content_type,
            data=data,
        )


def test_csv_analysis_computes_filters_statistics_rankings_and_chart_data(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    content = (
        b"month,region,product,revenue,units\n"
        b"2026-01,North,A,10,1\n"
        b"2026-01,South,A,20,2\n"
        b"2026-02,North,B,30,3\n"
        b"2026-02,South,B,5,1\n"
    )
    ingested = ingest_dataset(app, filename="sales.csv", content_type="text/csv", data=content)
    with Session(app.state.engine) as session:
        owner = IngestionService(
            session=session, settings=app.state.settings
        ).get_or_create_local_user()
        service = DatasetAnalysisService(
            session=session, settings=app.state.settings, owner_id=owner.id
        )
        grouped = service.analyze(
            ingested.version.id,
            DatasetAnalysisRequest(
                operation="comparison",
                group_by=("region",),
                value_column="revenue",
                metrics=("sum", "average", "count"),
                chart_type="bar",
            ),
        )
        described = service.analyze(
            ingested.version.id,
            DatasetAnalysisRequest(operation="describe", value_column="revenue"),
        )
        top = service.analyze(
            ingested.version.id,
            DatasetAnalysisRequest(
                operation="top",
                group_by=("product",),
                value_column="revenue",
                metrics=("sum",),
                limit=1,
            ),
        )
        second_grouped_row = service.analyze(
            ingested.version.id,
            DatasetAnalysisRequest(
                operation="comparison",
                group_by=("region",),
                value_column="revenue",
                metrics=("sum", "average", "count"),
                limit=1,
                offset=1,
            ),
        )
        filtered = service.analyze(
            ingested.version.id,
            DatasetAnalysisRequest.model_validate(
                {
                    "operation": "aggregate",
                    "filters": [{"column": "product", "operator": "eq", "value": "A"}],
                    "metrics": ["count"],
                }
            ),
        )

        assert grouped.rows == (
            {"region": "North", "revenue_sum": 40, "revenue_average": 20.0, "count": 2},
            {"region": "South", "revenue_sum": 25, "revenue_average": 12.5, "count": 2},
        )
        assert grouped.chart is not None
        assert grouped.chart.x == ("North", "South")
        assert grouped.provenance.source_columns == ("region", "revenue")
        assert described.rows[0]["median"] == 15.0
        assert top.rows == ({"product": "B", "revenue_sum": 35},)
        assert top.truncated is True
        assert len(second_grouped_row.rows) == 1
        assert second_grouped_row.rows[0] == grouped.rows[1]
        assert filtered.rows == ({"count": 2},)
        with pytest.raises(InvalidDatasetAnalysisError, match="Unknown dataset column"):
            service.analyze(
                ingested.version.id,
                DatasetAnalysisRequest(
                    operation="aggregate", group_by=("missing",), metrics=("count",)
                ),
            )


def test_xlsx_analysis_preserves_sheet_and_column_provenance(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Batches"
    sheet.append(["status", "yield"])
    sheet.append(["released", 98.4])
    sheet.append(["review", 96.1])
    content = io.BytesIO()
    workbook.save(content)
    workbook.close()

    app = build_app(tmp_path)
    ingested = ingest_dataset(
        app,
        filename="batches.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data=content.getvalue(),
    )
    with Session(app.state.engine) as session:
        owner = IngestionService(
            session=session, settings=app.state.settings
        ).get_or_create_local_user()
        result = DatasetAnalysisService(
            session=session, settings=app.state.settings, owner_id=owner.id
        ).analyze(
            ingested.version.id,
            DatasetAnalysisRequest(
                operation="aggregate",
                sheet="Batches",
                value_column="yield",
                metrics=("average", "median"),
            ),
        )

    assert result.rows == ({"yield_average": 97.25, "yield_median": 97.25},)
    assert result.provenance.sheet == "Batches"
    assert result.provenance.source_columns == ("yield",)


def test_search_source_and_dataset_analysis_api_contracts(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    _, record = ingest_text(app)
    pages = seed_wiki(app, record)
    ingested = ingest_dataset(
        app,
        filename="sales.csv",
        content_type="text/csv",
        data=b"region,revenue\nNorth,10\nNorth,30\nSouth,20\n",
    )

    async def exercise() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            search = await client.get("/api/v1/wiki/search", params={"q": "ACME"})
            related = await client.get(
                f"/api/v1/wiki/pages/{pages['gdp'].id}/related",
                params={"max_depth": 2},
            )
            source = await client.get(f"/api/v1/source-records/{record.id}")
            analysis = await client.post(
                f"/api/v1/datasets/{ingested.version.id}/analyze",
                json={
                    "operation": "comparison",
                    "group_by": ["region"],
                    "value_column": "revenue",
                    "metrics": ["sum"],
                    "chart_type": "bar",
                },
            )
            invalid = await client.post(
                f"/api/v1/datasets/{ingested.version.id}/analyze",
                json={"operation": "aggregate", "group_by": ["missing"]},
            )

        assert search.status_code == 200
        assert search.json()[0]["id"] == pages["acme"].id
        assert related.status_code == 200
        assert {item["id"] for item in related.json()} >= {
            pages["acme"].id,
            pages["cold"].id,
        }
        assert source.status_code == 200
        assert source.json()["locator"] == {"line_start": 1, "line_end": 1}
        assert analysis.status_code == 200, analysis.text
        assert analysis.json()["rows"][0]["revenue_sum"] == 40
        assert analysis.json()["chart"]["type"] == "bar"
        assert invalid.status_code == 422

    asyncio.run(exercise())


class DatasetProposalProvider:
    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=True,
            structured_output=True,
            cancellation=True,
            max_context_tokens=4096,
        )

    async def health(self) -> LLMHealth:
        return LLMHealth(healthy=True, provider="fake", model="fake-local")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        del request
        proposal = {
            "pages": [
                {
                    "type": "topic",
                    "title": "Commercial Performance",
                    "aliases": [],
                    "topics": ["sales"],
                    "summary": "Commercial performance information.",
                    "claims": [
                        {
                            "key": "source",
                            "text": "The source contains commercial performance data.",
                            "classification": "source_fact",
                            "source_record_ordinals": [1],
                        }
                    ],
                    "relationships": [],
                }
            ],
            "warnings": [],
        }
        return ChatResponse(
            message=ChatMessage(role="assistant", content=json.dumps(proposal)),
            model="fake-local",
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        del request
        if False:
            yield ChatChunk(model="fake-local")


def test_dataset_compilation_adds_deterministic_wiki_metadata(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(tmp_path, DatasetProposalProvider())
        ingested = ingest_dataset(
            app,
            filename="sales.csv",
            content_type="text/csv",
            data=b"region,revenue\nNorth,10\nSouth,20\n",
        )
        with Session(app.state.engine) as session:
            owner = IngestionService(
                session=session, settings=app.state.settings
            ).get_or_create_local_user()
            job = await KnowledgeCompiler(
                session=session,
                settings=app.state.settings,
                provider=app.state.llm_provider,
            ).compile(owner_id=owner.id, document_version_id=ingested.version.id)
            status = job.status
        assert status == "COMPLETED"
        dataset_page = WikiStore(app.state.settings.knowledge_path).read_page("sales")
        assert dataset_page.type == PageKind.DATASET
        assert {"structured data", "csv", "region", "revenue"} <= set(dataset_page.topics)
        assert "dataset_schema" in {claim.key for claim in dataset_page.claims}

    asyncio.run(exercise())


def test_forced_retrieval_uses_meaningful_query_terms() -> None:
    call = _forced_retrieval_call(
        ChatRequest(
            messages=(
                ChatMessage(role="user", content="Summarize Project LUMEN-QUAY."),
                ChatMessage(role="assistant", content="It is an Atlas project."),
                ChatMessage(role="user", content="Who owns it?"),
            ),
            tools=(
                ChatToolDefinition(
                    name="search_wiki",
                    description="Search the Wiki.",
                    parameters={"type": "object", "properties": {}},
                ),
            ),
        )
    )

    assert call is not None
    assert call.name == "search_wiki"
    assert call.arguments["query"] == "Project LUMEN-QUAY Who owns"

    later_call = _forced_retrieval_call(
        ChatRequest(
            messages=(
                ChatMessage(role="user", content="Summarize Project LUMEN-QUAY."),
                ChatMessage(role="assistant", content="It is an Atlas project."),
                ChatMessage(role="user", content="Who owns it?"),
                ChatMessage(role="assistant", content="The platform team owns it."),
                ChatMessage(role="user", content="What are its main risks?"),
            ),
            tools=(
                ChatToolDefinition(
                    name="search_wiki",
                    description="Search the Wiki.",
                    parameters={"type": "object", "properties": {}},
                ),
            ),
        )
    )
    assert later_call is not None
    assert later_call.arguments["query"] == "Project LUMEN-QUAY are main risks"


def test_natural_relationship_question_forces_wiki_retrieval_without_user_prompting() -> None:
    tools = (
        ChatToolDefinition(
            name="search_wiki",
            description="Search the Wiki.",
            parameters={"type": "object", "properties": {}},
        ),
    )

    italian = _forced_retrieval_call(
        ChatRequest(
            messages=(
                ChatMessage(
                    role="user",
                    content="Che relazione c'è tra Aldo Riva e Bruno Riva?",
                ),
            ),
            tools=tools,
        )
    )
    english = _forced_retrieval_call(
        ChatRequest(
            messages=(
                ChatMessage(
                    role="user",
                    content="What is the relationship between Aldo Riva and Bruno Riva?",
                ),
            ),
            tools=tools,
        )
    )

    assert italian is not None
    assert italian.name == "search_wiki"
    assert italian.arguments["query"] == "Aldo Riva Bruno Riva"
    assert english is not None
    assert english.name == "search_wiki"
    assert english.arguments["query"] == "relationship between Aldo Riva Bruno Riva"


def test_general_chat_and_translation_do_not_force_wiki_retrieval() -> None:
    tools = (
        ChatToolDefinition(
            name="search_wiki",
            description="Search the Wiki.",
            parameters={"type": "object", "properties": {}},
        ),
    )
    general = _forced_retrieval_call(
        ChatRequest(
            messages=(ChatMessage(role="user", content="What is the capital of Italy?"),),
            tools=tools,
        )
    )
    general_risk = _forced_retrieval_call(
        ChatRequest(
            messages=(ChatMessage(role="user", content="What are the risks of skiing?"),),
            tools=tools,
        )
    )
    translation = _forced_retrieval_call(
        ChatRequest(
            messages=(
                ChatMessage(role="user", content="Summarize Project LUMEN-QUAY."),
                ChatMessage(role="assistant", content="Grounded prior answer."),
                ChatMessage(role="user", content="Translate your previous answer into Italian."),
            ),
            tools=tools,
        )
    )

    assert general is None
    assert general_risk is None
    assert translation is None


def test_conflict_answer_does_not_invent_source_precedence() -> None:
    page_result = {
        "page": {
            "claims": [
                {
                    "text": "The Atlas Platform Team owns Project LUMEN-QUAY.",
                    "citations": [
                        {
                            "wiki_path": "wiki/concepts/atlas-operations.md",
                            "original_filename": "atlas-operations.md",
                            "locator": {"line_start": 1, "line_end": 8},
                        }
                    ],
                },
                {
                    "text": "The Atlas Platform Team does not own Project LUMEN-QUAY.",
                    "citations": [
                        {
                            "wiki_path": "wiki/concepts/atlas-platform-team.md",
                            "original_filename": "atlas-conflict.txt",
                            "locator": {"line_start": 1, "line_end": 3},
                        }
                    ],
                },
            ]
        }
    }
    answer = _conflict_evidence_answer(
        (
            ChatMessage(role="user", content="Resolve any conflict in the local Atlas material."),
            ChatMessage(
                role="tool",
                name="read_wiki_page",
                tool_call_id="read-1",
                content=json.dumps(page_result),
            ),
        )
    )

    assert answer is not None
    assert "conflict remains unresolved" in answer
    assert "atlas-operations.md" in answer
    assert "atlas-conflict.txt" in answer
    assert "more authoritative" not in answer


class AgentToolProvider:
    def __init__(self, page_id: str, source_record_id: str) -> None:
        self.page_id = page_id
        self.source_record_id = source_record_id
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
        return LLMHealth(healthy=True, provider="fake", model="fake-local")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        tool_messages = [message for message in request.messages if message.role == "tool"]
        if not tool_messages:
            message = ChatMessage(
                role="assistant",
                tool_calls=(
                    ChatToolCall(
                        id="search-1",
                        name="search_wiki",
                        arguments={
                            "query": "ACME",
                            "page_types": [],
                            "topics": [],
                            "limit": 5,
                        },
                    ),
                ),
            )
        elif len(tool_messages) == 1:
            assert self.page_id in tool_messages[-1].content
            message = ChatMessage(
                role="assistant",
                tool_calls=(
                    ChatToolCall(
                        id="read-1",
                        name="read_wiki_page",
                        arguments={"identifier": self.page_id, "max_claims": 10},
                    ),
                ),
            )
        elif len(tool_messages) == 2:
            page_payload = json.loads(tool_messages[-1].content)["page"]
            citation = page_payload["claims"][0]["citations"][0]
            assert citation["source_record_id"] == self.source_record_id
            assert citation["wiki_path"] == page_payload["path"]
            message = ChatMessage(
                role="assistant",
                tool_calls=(
                    ChatToolCall(
                        id="source-1",
                        name="read_source_reference",
                        arguments={
                            "source_record_id": self.source_record_id,
                            "max_chars": 1_000,
                        },
                    ),
                ),
            )
        else:
            assert "company.txt" in tool_messages[-1].content
            assert "headquartered in Valletta" in tool_messages[-1].content
            message = ChatMessage(
                role="assistant",
                content=(
                    "Acme is headquartered in Valletta "
                    "[Wiki: Acme Corporation](wiki/entities/acme-corporation.md) "
                    "[Source: company.txt, lines 1-1].\n\n"
                    "### **Citations:**\n- Original filename: invented.md"
                ),
            )
        return ChatResponse(
            message=message,
            model="fake-local",
            finish_reason="tool_calls" if message.tool_calls else "stop",
            usage=ChatUsage(),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise AssertionError(f"Tool-enabled ADK calls must use complete responses: {request}")
        yield ChatChunk(model="fake-local")


class GroundedFollowupProvider:
    """Answer after deterministic retrieval while exposing role-aware follow-up context."""

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=True,
            structured_output=True,
            cancellation=True,
            max_context_tokens=8192,
        )

    async def health(self) -> LLMHealth:
        return LLMHealth(healthy=True, provider="fake", model="fake-local")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        assert any(
            message.role == "tool" and message.name == "read_wiki_page"
            for message in request.messages
        )
        current = [message.content for message in request.messages if message.role == "user"][-1]
        answer = (
            "No authorized Wiki evidence identifies an owner."
            if current == "Who owns it?"
            else "Acme Corporation is a medicine distribution company."
        )
        return ChatResponse(
            message=ChatMessage(role="assistant", content=answer),
            model="fake-local",
            finish_reason="stop",
            usage=ChatUsage(),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise AssertionError(f"Tool-enabled ADK calls must use complete responses: {request}")
        yield ChatChunk(model="fake-local")


def test_adk_executes_search_then_page_read_before_grounded_answer(tmp_path: Path) -> None:
    seed_app = build_app(tmp_path)
    _, record = ingest_text(seed_app, b"Acme Corporation is headquartered in Valletta.")
    pages = seed_wiki(seed_app, record)
    provider = AgentToolProvider(pages["acme"].id, str(record.id))
    app = create_app(
        settings=seed_app.state.settings,
        provider=provider,
        engine=seed_app.state.engine,
    )

    async def exercise() -> str:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            conversation = await client.post("/api/v1/conversations", json={})
            response = await client.post(
                f"/api/v1/conversations/{conversation.json()['id']}/messages",
                json={"content": "Where is ACME headquartered?"},
            )
        assert response.status_code == 200, response.text
        assert "Valletta" in response.json()["content"]
        return str(response.json()["content"])

    content = asyncio.run(exercise())
    assert len(provider.requests) == 2
    assert all(request.tool_choice == "auto" for request in provider.requests)
    assert 'original filename: "company.txt"' in content
    assert 'locator: {"line_end": 1, "line_start": 1}' in content
    assert "invented.md" not in content
    assert {tool.name for tool in provider.requests[0].tools} == {
        "search_wiki",
        "read_wiki_page",
        "list_related_pages",
        "get_backlinks",
        "read_source_reference",
        "analyze_dataset",
    }


def test_grounded_followup_retrieves_same_subject_and_reports_missing_owner(
    tmp_path: Path,
) -> None:
    seed_app = build_app(tmp_path)
    _, record = ingest_text(seed_app, b"Acme Corporation distributes medicines from Valletta.")
    seed_wiki(seed_app, record)
    provider = GroundedFollowupProvider()
    app = create_app(
        settings=seed_app.state.settings,
        provider=provider,
        engine=seed_app.state.engine,
    )

    async def exercise() -> tuple[str, str]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            conversation = await client.post("/api/v1/conversations", json={})
            conversation_id = conversation.json()["id"]
            summary = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "Summarize company ACME."},
            )
            owner = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "Who owns it?"},
            )
        assert summary.status_code == 200, summary.text
        assert owner.status_code == 200, owner.text
        return str(summary.json()["content"]), str(owner.json()["content"])

    summary, owner = asyncio.run(exercise())

    assert "medicine distribution company" in summary
    assert 'original filename: "company.txt"' in summary
    assert "No authorized Wiki evidence identifies an owner." in owner
    assert [message.role for message in provider.requests[-1].messages[:4]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


class DatasetAgentProvider:
    def __init__(self, version_id: uuid.UUID) -> None:
        self.version_id = version_id
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
        return LLMHealth(healthy=True, provider="fake", model="fake-local")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        tool_messages = [message for message in request.messages if message.role == "tool"]
        if not tool_messages:
            message = ChatMessage(
                role="assistant",
                tool_calls=(
                    ChatToolCall(
                        id="analysis-1",
                        name="analyze_dataset",
                        arguments={
                            "document_version_id": str(self.version_id),
                            "request": {
                                "operation": "comparison",
                                "group_by": ["region"],
                                "value_column": "revenue",
                                "metrics": ["sum"],
                                "chart_type": "bar",
                            },
                        },
                    ),
                ),
            )
        else:
            assert '"revenue_sum": 40' in tool_messages[-1].content
            assert '"source_columns": ["region", "revenue"]' in tool_messages[-1].content
            message = ChatMessage(
                role="assistant",
                content=(
                    "North revenue is 40 and South revenue is 20 "
                    f"[Source: sales.csv, version {self.version_id}, columns region/revenue]."
                ),
            )
        return ChatResponse(message=message, model="fake-local")

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise AssertionError(f"Tool-enabled ADK calls must use complete responses: {request}")
        yield ChatChunk(model="fake-local")


def test_adk_executes_deterministic_dataset_analysis_with_provenance(tmp_path: Path) -> None:
    seed_app = build_app(tmp_path)
    ingested = ingest_dataset(
        seed_app,
        filename="sales.csv",
        content_type="text/csv",
        data=b"region,revenue\nNorth,10\nNorth,30\nSouth,20\n",
    )
    provider = DatasetAgentProvider(ingested.version.id)
    app = create_app(
        settings=seed_app.state.settings,
        provider=provider,
        engine=seed_app.state.engine,
    )

    async def exercise() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            conversation = await client.post("/api/v1/conversations", json={})
            response = await client.post(
                f"/api/v1/conversations/{conversation.json()['id']}/messages",
                json={"content": "Compare revenue by region and prepare a bar chart."},
            )
        assert response.status_code == 200, response.text
        assert "North revenue is 40" in response.json()["content"]

    asyncio.run(exercise())
    assert len(provider.requests) == 2
