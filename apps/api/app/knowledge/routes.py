"""FastAPI routes for compilation jobs and read-oriented Wiki operations."""

import uuid
from collections.abc import Iterator
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import KnowledgeCompilationJob
from app.knowledge.access import KnowledgeAccessService, SourceReference
from app.knowledge.analysis import (
    DatasetAnalysisRequest,
    DatasetAnalysisResult,
    DatasetAnalysisService,
)
from app.knowledge.compiler import KnowledgeCompiler
from app.knowledge.graph import WikiGraph, WikiMarkdownPage
from app.knowledge.search import RelatedPage, SearchHit
from app.knowledge.store import WikiStore
from app.knowledge.types import (
    CompilationReport,
    PageKind,
    PageSummary,
    WikiLintReport,
    WikiPage,
)
from app.security import Principal, ensure_workspace_writable, require_permission


class CompilationJobResponse(BaseModel):
    id: uuid.UUID
    document_version_id: uuid.UUID
    status: str
    compilation_version: str
    attempt_count: int
    last_completed_stage: str | None
    error: str | None
    report: CompilationReport | None


class WikiPageIndexResponse(BaseModel):
    items: list[PageSummary]
    page: int
    page_limit: int
    total: int
    total_pages: int


def _job_response(job: KnowledgeCompilationJob) -> CompilationJobResponse:
    return CompilationJobResponse(
        id=job.id,
        document_version_id=job.document_version_id,
        status=job.status,
        compilation_version=job.compilation_version,
        attempt_count=job.attempt_count,
        last_completed_stage=job.last_completed_stage,
        error=job.error,
        report=CompilationReport.model_validate(job.report) if job.report else None,
    )


def create_knowledge_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["knowledge"])

    def get_session(request: Request) -> Iterator[Session]:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as session:
            yield session

    @router.post(
        "/api/v1/document-versions/{document_version_id}/compile",
        response_model=CompilationJobResponse,
    )
    async def compile_document_version(
        document_version_id: uuid.UUID,
        request: Request,
        principal: Annotated[Principal, Depends(require_permission("knowledge.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> CompilationJobResponse:
        ensure_workspace_writable(settings)
        compiler = KnowledgeCompiler(
            session=session,
            settings=settings,
            provider=request.app.state.llm_provider,
        )
        job = await compiler.compile(
            owner_id=principal.user_id, document_version_id=document_version_id
        )
        return _job_response(job)

    @router.get(
        "/api/v1/knowledge-compilation-jobs/{job_id}",
        response_model=CompilationJobResponse,
    )
    def get_compilation_job(
        job_id: uuid.UUID,
        request: Request,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> CompilationJobResponse:
        compiler = KnowledgeCompiler(
            session=session,
            settings=settings,
            provider=request.app.state.llm_provider,
        )
        return _job_response(compiler.get_job(owner_id=principal.user_id, job_id=job_id))

    @router.get("/api/v1/wiki/pages", response_model=list[PageSummary])
    def list_wiki_pages(
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        kind: Annotated[PageKind | None, Query()] = None,
    ) -> list[PageSummary]:
        return list(
            KnowledgeAccessService(
                session=session, settings=settings, owner_id=principal.user_id
            ).list_pages(kind)
        )

    @router.get("/api/v1/wiki/page-index", response_model=WikiPageIndexResponse)
    def page_wiki_index(
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_limit: Annotated[int, Query(ge=1, le=100)] = 8,
        query: Annotated[str, Query(alias="q", max_length=500)] = "",
        kind: Annotated[PageKind | None, Query()] = None,
    ) -> WikiPageIndexResponse:
        pages = list(
            KnowledgeAccessService(
                session=session, settings=settings, owner_id=principal.user_id
            ).list_pages(kind)
        )
        normalized_query = query.strip().lower()
        if normalized_query:
            pages = [
                item
                for item in pages
                if normalized_query in " ".join((item.title, *item.aliases, *item.topics)).lower()
            ]
        total = len(pages)
        start = (page - 1) * page_limit
        return WikiPageIndexResponse(
            items=pages[start : start + page_limit],
            page=page,
            page_limit=page_limit,
            total=total,
            total_pages=ceil(total / page_limit) if total else 0,
        )

    @router.get("/api/v1/wiki/search", response_model=list[SearchHit])
    def search_wiki(
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        query: Annotated[str, Query(alias="q", max_length=500)] = "",
        page_type: Annotated[list[PageKind] | None, Query()] = None,
        topic: Annotated[list[str] | None, Query(max_length=300)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> list[SearchHit]:
        retrieval = KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).retrieval()
        return list(
            retrieval.search(
                query=query,
                page_types=tuple(page_type or ()),
                topics=tuple(topic or ()),
                limit=limit,
            )
        )

    @router.get("/api/v1/wiki/graph", response_model=WikiGraph)
    def wiki_graph(
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        root: Annotated[str | None, Query(max_length=500)] = None,
        depth: Annotated[int, Query(ge=1, le=3)] = 1,
        refresh: Annotated[bool, Query()] = False,
    ) -> WikiGraph:
        return KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).graph(root=root, depth=depth, force_refresh=refresh)

    @router.get("/api/v1/wiki/files/{path:path}", response_model=WikiMarkdownPage)
    def read_wiki_markdown_file(
        path: str,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> WikiMarkdownPage:
        return KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).read_markdown_page(path)

    @router.get("/api/v1/wiki/pages/{identifier}", response_model=WikiPage)
    def read_wiki_page(
        identifier: str,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> WikiPage:
        return KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).read_page(identifier)

    @router.get(
        "/api/v1/wiki/pages/{identifier}/backlinks",
        response_model=list[PageSummary],
    )
    def wiki_backlinks(
        identifier: str,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[PageSummary]:
        related = (
            KnowledgeAccessService(session=session, settings=settings, owner_id=principal.user_id)
            .retrieval()
            .backlinks(identifier, limit=settings.wiki_search_max_results)
        )
        return [
            PageSummary(
                id=item.id,
                type=item.type,
                title=item.title,
                aliases=item.aliases,
                topics=item.topics,
                path=item.path,
            )
            for item in related
        ]

    @router.get(
        "/api/v1/wiki/pages/{identifier}/related",
        response_model=list[RelatedPage],
    )
    def wiki_related_pages(
        identifier: str,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        max_depth: Annotated[int, Query(ge=1, le=5)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[RelatedPage]:
        retrieval = KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).retrieval()
        return list(retrieval.related_pages(identifier, max_depth=max_depth, limit=limit))

    @router.get(
        "/api/v1/source-records/{source_record_id}",
        response_model=SourceReference,
    )
    def read_source_reference(
        source_record_id: str,
        principal: Annotated[Principal, Depends(require_permission("knowledge.read"))],
        session: Annotated[Session, Depends(get_session)],
        max_chars: Annotated[int, Query(ge=1)] = 8_000,
    ) -> SourceReference:
        return KnowledgeAccessService(
            session=session, settings=settings, owner_id=principal.user_id
        ).read_source_reference(source_record_id, max_chars=max_chars)

    @router.post(
        "/api/v1/datasets/{document_version_id}/analyze",
        response_model=DatasetAnalysisResult,
    )
    def analyze_dataset(
        document_version_id: uuid.UUID,
        body: DatasetAnalysisRequest,
        principal: Annotated[Principal, Depends(require_permission("dataset.analyze"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> DatasetAnalysisResult:
        ensure_workspace_writable(settings)
        return DatasetAnalysisService(
            session=session, settings=settings, owner_id=principal.user_id
        ).analyze(document_version_id, body)

    @router.post("/api/v1/wiki/rebuild-index", response_model=list[PageSummary])
    def rebuild_wiki_index(
        _: Annotated[Principal, Depends(require_permission("knowledge.manage"))],
    ) -> list[PageSummary]:
        ensure_workspace_writable(settings)
        return list(WikiStore(settings.knowledge_path).rebuild_index())

    @router.get("/api/v1/wiki/lint", response_model=WikiLintReport)
    def lint_wiki(
        _: Annotated[Principal, Depends(require_permission("knowledge.manage"))],
    ) -> WikiLintReport:
        return WikiStore(settings.knowledge_path).lint()

    return router
