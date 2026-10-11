"""FastAPI routes for source upload, job observation, and retry."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import (
    AuditEvent,
    DatasetRecord,
    Document,
    DocumentVersion,
    IngestionJob,
    KnowledgeCompilationJob,
    SourceDeletionJob,
    User,
)
from app.ingestion.deletion import SourceDeletionService, SourceDeletionWorker
from app.ingestion.errors import (
    DocumentNotFoundError,
    IngestionRequestError,
    SourceIntegrityError,
    UploadTooLargeError,
)
from app.ingestion.service import IngestionResult, IngestionService
from app.ingestion.storage import SourceStorage
from app.security import Principal, ensure_workspace_writable, require_permission


class IngestionResponse(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    version_number: int
    ingestion_job_id: uuid.UUID
    status: str
    checksum: str
    content_type: str
    byte_size: int
    sanitized_filename: str
    duplicate: bool
    error: str | None
    original_uri: str
    extracted_uri: str | None
    metadata_uri: str | None
    processing_uri: str


class DocumentListResponse(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    original_filename: str
    version_number: int
    content_type: str
    byte_size: int
    checksum: str
    created_at: datetime
    ingestion_job_id: uuid.UUID
    ingestion_status: str
    ingestion_error: str | None
    ingestion_attempt_count: int
    last_completed_stage: str | None
    compilation_job_id: uuid.UUID | None
    compilation_status: str | None
    compilation_error: str | None
    compilation_attempt_count: int | None
    compilation_report: dict[str, object] | None
    is_dataset: bool
    original_url: str


class DocumentPageResponse(BaseModel):
    items: list[DocumentListResponse]
    page: int
    page_limit: int
    total: int
    total_pages: int


class SourceDeletionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    display_filename: str
    status: str
    stage: str
    attempt_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


def _deletion_response(job: SourceDeletionJob) -> SourceDeletionResponse:
    return SourceDeletionResponse(
        id=job.id,
        document_id=job.document_id,
        display_filename=job.display_filename,
        status=job.status,
        stage=job.stage,
        attempt_count=job.attempt_count,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
    )


def _response(
    *,
    version: DocumentVersion,
    job: IngestionJob,
    sanitized_filename: str,
    duplicate: bool,
) -> IngestionResponse:
    return IngestionResponse(
        document_id=version.document_id,
        document_version_id=version.id,
        version_number=version.version_number,
        ingestion_job_id=job.id,
        status=job.status,
        checksum=version.sha256,
        content_type=version.content_type,
        byte_size=version.byte_size,
        sanitized_filename=sanitized_filename,
        duplicate=duplicate,
        error=job.error,
        original_uri=version.storage_uri,
        extracted_uri=version.extracted_uri,
        metadata_uri=version.metadata_uri,
        processing_uri=job.processing_uri,
    )


def _document_list_response(
    row: tuple[
        Document,
        DocumentVersion,
        IngestionJob,
        KnowledgeCompilationJob | None,
        bool,
    ],
) -> DocumentListResponse:
    document, version, job, compilation, is_dataset = row
    return DocumentListResponse(
        document_id=document.id,
        document_version_id=version.id,
        original_filename=document.original_filename,
        version_number=version.version_number,
        content_type=version.content_type,
        byte_size=version.byte_size,
        checksum=version.sha256,
        created_at=version.created_at,
        ingestion_job_id=job.id,
        ingestion_status=job.status,
        ingestion_error=job.error,
        ingestion_attempt_count=job.attempt_count,
        last_completed_stage=job.last_completed_stage,
        compilation_job_id=compilation.id if compilation else None,
        compilation_status=compilation.status if compilation else None,
        compilation_error=compilation.error if compilation else None,
        compilation_attempt_count=compilation.attempt_count if compilation else None,
        compilation_report=compilation.report if compilation else None,
        is_dataset=is_dataset,
        original_url=f"/api/v1/document-versions/{version.id}/original",
    )


async def _read_bounded(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise UploadTooLargeError(f"Uploads may not exceed {max_bytes} bytes.")
            chunks.append(chunk)
    finally:
        await upload.close()
    return b"".join(chunks)


def create_ingestion_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["ingestion"])

    def get_session(request: Request) -> Iterator[Session]:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as session:
            yield session

    @router.post(
        "/api/v1/documents",
        response_model=IngestionResponse,
        status_code=status.HTTP_201_CREATED,
        responses={200: {"model": IngestionResponse}},
    )
    async def upload_document(
        request: Request,
        http_response: Response,
        file: Annotated[UploadFile, File()],
        principal: Annotated[Principal, Depends(require_permission("document.upload"))],
        session: Annotated[Session, Depends(get_session)],
        document_id: Annotated[uuid.UUID | None, Form()] = None,
    ) -> IngestionResponse:
        del request
        ensure_workspace_writable(settings)
        if file.filename is None:
            raise IngestionRequestError("A filename is required.")
        data = await _read_bounded(file, settings.max_upload_bytes)
        service = IngestionService(session=session, settings=settings)
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        result = service.ingest(
            owner=owner,
            filename=file.filename,
            declared_content_type=file.content_type,
            data=data,
            document_id=document_id,
        )
        result_response = _response(
            version=result.version,
            job=result.job,
            sanitized_filename=result.sanitized_filename,
            duplicate=result.duplicate,
        )
        if result.duplicate:
            http_response.status_code = status.HTTP_200_OK
            return result_response
        return result_response

    @router.get(
        "/api/v1/documents",
        response_model=list[DocumentListResponse] | DocumentPageResponse,
    )
    def list_documents(
        principal: Annotated[Principal, Depends(require_permission("document.read"))],
        session: Annotated[Session, Depends(get_session)],
        page: Annotated[int | None, Query(ge=1)] = None,
        page_limit: Annotated[int, Query(ge=1, le=100)] = 10,
        query: Annotated[str, Query(alias="q", max_length=300)] = "",
        document_filter: Annotated[
            Literal["all", "dataset", "attention"], Query(alias="filter")
        ] = "all",
        processing_status: Annotated[
            Literal["all", "processing", "completed", "failed"], Query(alias="status")
        ] = "all",
        file_type: Annotated[
            Literal["all", "pdf", "txt", "md", "docx", "csv", "xlsx"], Query()
        ] = "all",
    ) -> list[DocumentListResponse] | DocumentPageResponse:
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        dataset_exists = exists().where(DatasetRecord.document_version_id == DocumentVersion.id)
        statement = (
            select(
                Document,
                DocumentVersion,
                IngestionJob,
                KnowledgeCompilationJob,
                dataset_exists.label("is_dataset"),
            )
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
            .outerjoin(
                KnowledgeCompilationJob,
                KnowledgeCompilationJob.document_version_id == DocumentVersion.id,
            )
            .where(Document.owner_id == owner.id, Document.deleted_at.is_(None))
        )
        if query.strip():
            statement = statement.where(Document.original_filename.ilike(f"%{query.strip()}%"))
        if document_filter == "dataset":
            statement = statement.where(dataset_exists)
        elif document_filter == "attention":
            statement = statement.where(
                or_(IngestionJob.error.is_not(None), KnowledgeCompilationJob.error.is_not(None))
            )

        if processing_status == "failed":
            statement = statement.where(
                or_(IngestionJob.status == "FAILED", KnowledgeCompilationJob.status == "FAILED")
            )
        elif processing_status == "completed":
            statement = statement.where(KnowledgeCompilationJob.status == "COMPLETED")
        elif processing_status == "processing":
            statement = statement.where(
                IngestionJob.status != "FAILED",
                or_(
                    KnowledgeCompilationJob.id.is_(None),
                    KnowledgeCompilationJob.status.not_in(("COMPLETED", "FAILED")),
                ),
            )

        content_types = {
            "pdf": "application/pdf",
            "txt": "text/plain",
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if file_type != "all":
            statement = statement.where(DocumentVersion.content_type == content_types[file_type])

        total = int(
            session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
            or 0
        )
        statement = statement.order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
        if page is not None:
            statement = statement.offset((page - 1) * page_limit).limit(page_limit)
        items = [_document_list_response(row) for row in session.execute(statement).all()]
        if page is None:
            return items
        return DocumentPageResponse(
            items=items,
            page=page,
            page_limit=page_limit,
            total=total,
            total_pages=max(1, (total + page_limit - 1) // page_limit),
        )

    @router.get("/api/v1/datasets", response_model=DocumentPageResponse)
    def list_datasets(
        principal: Annotated[Principal, Depends(require_permission("dataset.analyze"))],
        session: Annotated[Session, Depends(get_session)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_limit: Annotated[int, Query(ge=1, le=100)] = 5,
        query: Annotated[str, Query(alias="q", max_length=300)] = "",
    ) -> DocumentPageResponse:
        result = list_documents(
            principal=principal,
            session=session,
            page=page,
            page_limit=page_limit,
            query=query,
            document_filter="dataset",
            processing_status="all",
            file_type="all",
        )
        assert isinstance(result, DocumentPageResponse)
        return result

    @router.get("/api/v1/datasets/{document_version_id}", response_model=DocumentListResponse)
    def get_dataset(
        document_version_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("dataset.analyze"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> DocumentListResponse:
        dataset_exists = exists().where(DatasetRecord.document_version_id == DocumentVersion.id)
        row = session.execute(
            select(
                Document,
                DocumentVersion,
                IngestionJob,
                KnowledgeCompilationJob,
                dataset_exists.label("is_dataset"),
            )
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
            .outerjoin(
                KnowledgeCompilationJob,
                KnowledgeCompilationJob.document_version_id == DocumentVersion.id,
            )
            .where(
                Document.owner_id == principal.user_id,
                Document.deleted_at.is_(None),
                DocumentVersion.id == document_version_id,
                dataset_exists,
            )
        ).one_or_none()
        if row is None:
            raise DocumentNotFoundError(str(document_version_id))
        return _document_list_response(row)

    @router.get("/api/v1/document-versions/{version_id}/original")
    def get_original_document(
        version_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("document.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> FileResponse:
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        row = session.execute(
            select(DocumentVersion, Document)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                DocumentVersion.id == version_id,
                Document.owner_id == owner.id,
                Document.deleted_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            raise DocumentNotFoundError(str(version_id))
        version, document = row
        path = SourceStorage(settings.source_store_path).resolve_relative(version.storage_uri)
        if not path.is_file():
            raise DocumentNotFoundError(str(version_id))
        if hashlib.sha256(path.read_bytes()).hexdigest() != version.sha256:
            raise SourceIntegrityError("The immutable source checksum no longer matches metadata.")
        session.add(
            AuditEvent(
                actor_user_id=owner.id,
                event_type="source.downloaded",
                entity_type="document_version",
                entity_id=str(version.id),
                payload={"sha256": version.sha256},
            )
        )
        session.commit()
        return FileResponse(
            path,
            media_type=version.content_type,
            filename=document.original_filename,
            content_disposition_type="attachment",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )

    @router.get(
        "/api/v1/ingestion-jobs/{job_id}",
        response_model=IngestionResponse,
    )
    def get_ingestion_job(
        job_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("ingestion.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> IngestionResponse:
        service = IngestionService(session=session, settings=settings)
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        job, version = service.get_job(owner_id=owner.id, job_id=job_id)
        return _response(
            version=version,
            job=job,
            sanitized_filename=str(version.provenance.get("sanitized_filename", "source")),
            duplicate=False,
        )

    @router.post(
        "/api/v1/ingestion-jobs/{job_id}/retry",
        response_model=IngestionResponse,
    )
    def retry_ingestion_job(
        job_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("ingestion.retry"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> IngestionResponse:
        ensure_workspace_writable(settings)
        service = IngestionService(session=session, settings=settings)
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        result: IngestionResult = service.retry(owner=owner, job_id=job_id)
        return _response(
            version=result.version,
            job=result.job,
            sanitized_filename=result.sanitized_filename,
            duplicate=False,
        )

    @router.post(
        "/api/v1/ingestion-jobs/{job_id}/reprocess",
        response_model=IngestionResponse,
    )
    def reprocess_ingestion_job(
        job_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("document.reprocess"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> IngestionResponse:
        ensure_workspace_writable(settings)
        service = IngestionService(session=session, settings=settings)
        owner = session.get(User, principal.user_id)
        if owner is None:
            raise DocumentNotFoundError(str(principal.user_id))
        result = service.reprocess(owner=owner, job_id=job_id)
        return _response(
            version=result.version,
            job=result.job,
            sanitized_filename=result.sanitized_filename,
            duplicate=False,
        )

    @router.delete(
        "/api/v1/documents/{document_id}",
        response_model=SourceDeletionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def delete_document(
        document_id: uuid.UUID,
        request: Request,
        background_tasks: BackgroundTasks,
        principal: Annotated[Principal, Depends(require_permission("document.delete"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> SourceDeletionResponse:
        """Tombstone a whole document and durably queue all-version cleanup."""

        ensure_workspace_writable(settings)
        operation = SourceDeletionService(session).accept(
            owner_id=principal.user_id, document_id=document_id
        )
        worker: SourceDeletionWorker = request.app.state.source_deletion_worker
        background_tasks.add_task(worker.run_operation, operation.id)
        return _deletion_response(operation)

    @router.get("/api/v1/source-deletion-operations", response_model=list[SourceDeletionResponse])
    def list_source_deletions(
        principal: Annotated[Principal, Depends(require_permission("document.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[SourceDeletionResponse]:
        return [
            _deletion_response(job)
            for job in SourceDeletionService(session).list(owner_id=principal.user_id)
        ]

    @router.get(
        "/api/v1/source-deletion-operations/{operation_id}",
        response_model=SourceDeletionResponse,
    )
    def get_source_deletion(
        operation_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("document.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> SourceDeletionResponse:
        return _deletion_response(
            SourceDeletionService(session).get(
                owner_id=principal.user_id, operation_id=operation_id
            )
        )

    @router.post(
        "/api/v1/source-deletion-operations/{operation_id}/retry",
        response_model=SourceDeletionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_source_deletion(
        operation_id: uuid.UUID,
        request: Request,
        background_tasks: BackgroundTasks,
        principal: Annotated[Principal, Depends(require_permission("document.delete"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> SourceDeletionResponse:
        ensure_workspace_writable(settings)
        operation = SourceDeletionService(session).retry(
            owner_id=principal.user_id, operation_id=operation_id
        )
        worker: SourceDeletionWorker = request.app.state.source_deletion_worker
        background_tasks.add_task(worker.run_operation, operation.id)
        return _deletion_response(operation)

    return router
