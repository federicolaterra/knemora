"""Idempotent ingestion orchestration and persisted job state transitions."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    AuditEvent,
    DatasetRecord,
    Document,
    DocumentVersion,
    IngestionJob,
    KnowledgeCompilationJob,
    SourceRecord,
    User,
)
from app.ingestion.errors import (
    DocumentNotFoundError,
    IngestionJobNotFoundError,
    IngestionRetryConflictError,
    ParserFailure,
)
from app.ingestion.normalization import render_extracted_markdown
from app.ingestion.parsers import ParserRegistry
from app.ingestion.storage import SourceStorage
from app.ingestion.types import IngestionStatus, ParsedDocument, ValidatedUpload
from app.ingestion.validation import validate_upload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    document: Document
    version: DocumentVersion
    job: IngestionJob
    duplicate: bool
    sanitized_filename: str


class IngestionService:
    """Own the upload-to-normalized-source transaction boundary."""

    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        parsers: ParserRegistry | None = None,
        storage: SourceStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.parsers = parsers or ParserRegistry()
        self.storage = storage or SourceStorage(settings.source_store_path)

    def get_or_create_local_user(self) -> User:
        user = self.session.scalar(
            select(User).where(User.email == self.settings.default_user_email)
        )
        if user is None:
            user = User(
                email=self.settings.default_user_email,
                display_name=self.settings.default_user_name,
            )
            self.session.add(user)
            self.session.commit()
        return user

    def ingest(
        self,
        *,
        owner: User,
        filename: str,
        declared_content_type: str | None,
        data: bytes,
        document_id: uuid.UUID | None = None,
    ) -> IngestionResult:
        upload = validate_upload(
            filename=filename,
            declared_content_type=declared_content_type,
            data=data,
            settings=self.settings,
        )
        checksum = hashlib.sha256(data).hexdigest()
        duplicate = self._find_duplicate(owner.id, checksum)
        if duplicate is not None:
            version, job, document = duplicate
            self._audit(
                owner.id,
                "source.duplicate_detected",
                "document_version",
                version.id,
                {"sha256": checksum},
            )
            self.session.commit()
            return IngestionResult(
                document=document,
                version=version,
                job=job,
                duplicate=True,
                sanitized_filename=str(
                    version.provenance.get("sanitized_filename", upload.sanitized_filename)
                ),
            )

        document = self._resolve_document(
            owner=owner, document_id=document_id, original_filename=filename
        )
        version_number = (
            self.session.scalar(
                select(func.max(DocumentVersion.version_number)).where(
                    DocumentVersion.document_id == document.id
                )
            )
            or 0
        ) + 1
        now = datetime.now(UTC)
        version_id = uuid.uuid4()
        paths = self.storage.artifact_paths(
            stored_on=now.date(),
            document_id=document.id,
            version_id=version_id,
            extension=upload.extension,
            uploaded_filename=filename,
        )
        provenance = {
            "original_filename": filename,
            "sanitized_filename": upload.sanitized_filename,
            "extension": upload.extension,
            "stored_on": now.date().isoformat(),
            "storage_filename": paths["original"].name,
        }
        version = DocumentVersion(
            id=version_id,
            owner_id=owner.id,
            document_id=document.id,
            version_number=version_number,
            sha256=checksum,
            content_type=upload.content_type,
            byte_size=len(data),
            storage_uri=self.storage.relative_path(paths["original"]),
            extracted_uri=None,
            metadata_uri=None,
            provenance=provenance,
        )
        job = IngestionJob(
            document_version_id=version.id,
            status=IngestionStatus.UPLOADED,
            error=None,
            attempt_count=1,
            last_completed_stage=None,
            processing_uri=self.storage.relative_path(paths["processing"]),
            processing_metadata={
                "history": [self._history_entry(IngestionStatus.UPLOADED)],
            },
        )
        self.session.add_all([version, job])
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            concurrent_duplicate = self._find_duplicate(owner.id, checksum)
            if concurrent_duplicate is None:
                raise
            existing_version, existing_job, existing_document = concurrent_duplicate
            return IngestionResult(
                document=existing_document,
                version=existing_version,
                job=existing_job,
                duplicate=True,
                sanitized_filename=str(
                    existing_version.provenance.get("sanitized_filename", upload.sanitized_filename)
                ),
            )
        self._audit(
            owner.id, "source.uploaded", "document_version", version.id, {"sha256": checksum}
        )
        self.session.commit()

        try:
            self._transition(job, IngestionStatus.VALIDATING)
            self._transition(job, IngestionStatus.STORING)
            self.storage.store_original(
                path=paths["original"],
                data=data,
                processing=self._processing_payload(job, version),
            )
            job.last_completed_stage = IngestionStatus.STORING
            self.session.commit()
            self._process(owner=owner, document=document, version=version, job=job, upload=upload)
        except Exception as exc:
            self._mark_failed(owner.id, job.id, version.id, exc)
            job = self.session.get(IngestionJob, job.id) or job
        return IngestionResult(
            document=document,
            version=version,
            job=job,
            duplicate=False,
            sanitized_filename=upload.sanitized_filename,
        )

    def get_job(
        self, *, owner_id: uuid.UUID, job_id: uuid.UUID
    ) -> tuple[IngestionJob, DocumentVersion]:
        row = self.session.execute(
            select(IngestionJob, DocumentVersion)
            .join(DocumentVersion, IngestionJob.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(IngestionJob.id == job_id, Document.owner_id == owner_id)
            .where(Document.deleted_at.is_(None))
        ).one_or_none()
        if row is None:
            raise IngestionJobNotFoundError(str(job_id))
        return row

    def retry(self, *, owner: User, job_id: uuid.UUID) -> IngestionResult:
        return self._reprocess(owner=owner, job_id=job_id, allow_completed=False)

    def reprocess(self, *, owner: User, job_id: uuid.UUID) -> IngestionResult:
        """Re-run parsing and normalization from checksum-verified immutable bytes."""

        return self._reprocess(owner=owner, job_id=job_id, allow_completed=True)

    def _reprocess(
        self, *, owner: User, job_id: uuid.UUID, allow_completed: bool
    ) -> IngestionResult:
        job, version = self.get_job(owner_id=owner.id, job_id=job_id)
        if job.status == IngestionStatus.READY_FOR_COMPILATION and not allow_completed:
            raise IngestionRetryConflictError("A completed ingestion job cannot be retried.")
        document = self.session.get(Document, version.document_id)
        if document is None or document.owner_id != owner.id:
            raise IngestionJobNotFoundError(str(job_id))
        try:
            original_path = self.storage.resolve_relative(version.storage_uri)
            data = self.storage.read_original(original_path)
            if hashlib.sha256(data).hexdigest() != version.sha256:
                raise ParserFailure("The immutable original failed checksum verification.")
            upload = validate_upload(
                filename=str(version.provenance["original_filename"]),
                declared_content_type=version.content_type,
                data=data,
                settings=self.settings,
            )
            job.attempt_count += 1
            job.error = None
            job.finished_at = None
            self._append_history(job, IngestionStatus.VALIDATING)
            job.status = IngestionStatus.VALIDATING
            self._audit(owner.id, "ingestion.retried", "ingestion_job", job.id, {})
            self.session.commit()
            self._process(owner=owner, document=document, version=version, job=job, upload=upload)
            self._invalidate_compilation(owner_id=owner.id, version_id=version.id)
        except Exception as exc:
            self._mark_failed(owner.id, job.id, version.id, exc)
            job = self.session.get(IngestionJob, job.id) or job
        return IngestionResult(
            document=document,
            version=version,
            job=job,
            duplicate=False,
            sanitized_filename=str(version.provenance["sanitized_filename"]),
        )

    def _process(
        self,
        *,
        owner: User,
        document: Document,
        version: DocumentVersion,
        job: IngestionJob,
        upload: ValidatedUpload,
    ) -> None:
        self._transition(job, IngestionStatus.PARSING)
        parsed = self.parsers.parse(upload)
        job.last_completed_stage = IngestionStatus.PARSING
        self.session.commit()
        self._transition(job, IngestionStatus.NORMALIZING)
        markdown = render_extracted_markdown(parsed)
        existing_records = {
            record.ordinal: record
            for record in self.session.scalars(
                select(SourceRecord).where(SourceRecord.document_version_id == version.id)
            )
        }
        records: list[SourceRecord] = []
        for ordinal, block in enumerate(parsed.blocks, start=1):
            record = existing_records.get(ordinal)
            if record is None:
                record = SourceRecord(
                    id=uuid.uuid4(),
                    document_version_id=version.id,
                    ordinal=ordinal,
                    content=block.content,
                    locator=block.locator,
                    parser_name=parsed.parser_name,
                    parser_version=parsed.parser_version,
                )
                self.session.add(record)
            else:
                record.content = block.content
                record.locator = block.locator
                record.parser_name = parsed.parser_name
                record.parser_version = parsed.parser_version
            records.append(record)
        metadata = self._metadata_payload(document, version, upload, parsed, records)
        original_path = self.storage.resolve_relative(version.storage_uri)
        extracted_path = original_path.parent / "extracted.md"
        metadata_path = original_path.parent / "metadata.json"
        self.storage.write_derived(
            extracted_path=extracted_path,
            metadata_path=metadata_path,
            markdown=markdown,
            metadata=metadata,
        )
        version.extracted_uri = self.storage.relative_path(extracted_path)
        version.metadata_uri = self.storage.relative_path(metadata_path)
        self.session.execute(
            delete(DatasetRecord).where(DatasetRecord.document_version_id == version.id)
        )
        if parsed.dataset_metadata is not None:
            self.session.add(
                DatasetRecord(
                    document_version_id=version.id,
                    schema_metadata=parsed.dataset_metadata,
                )
            )
        version.provenance = {
            **version.provenance,
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
        }
        processing_metadata = dict(job.processing_metadata or {})
        processing_metadata["active_source_record_ids"] = [str(record.id) for record in records]
        job.processing_metadata = processing_metadata
        job.last_completed_stage = IngestionStatus.NORMALIZING
        self.session.commit()
        self._transition(job, IngestionStatus.READY_FOR_COMPILATION)
        self._audit(
            owner.id,
            "ingestion.completed",
            "ingestion_job",
            job.id,
            {"source_record_count": len(records)},
        )
        self.session.commit()
        self.storage.write_processing(
            self.storage.resolve_relative(job.processing_uri),
            self._processing_payload(job, version),
        )

    def _invalidate_compilation(self, *, owner_id: uuid.UUID, version_id: uuid.UUID) -> None:
        compilation = self.session.scalar(
            select(KnowledgeCompilationJob).where(
                KnowledgeCompilationJob.document_version_id == version_id
            )
        )
        if compilation is None:
            return
        compilation.status = "QUEUED"
        compilation.compilation_version = self.settings.knowledge_compilation_version
        compilation.last_completed_stage = None
        compilation.proposal = None
        compilation.report = None
        compilation.error = None
        compilation.started_at = None
        compilation.finished_at = None
        self._audit(
            owner_id,
            "knowledge.compilation.invalidated",
            "knowledge_compilation_job",
            compilation.id,
            {"document_version_id": str(version_id)},
        )
        self.session.commit()

    def _transition(self, job: IngestionJob, status: IngestionStatus) -> None:
        job.status = status
        job.error = None
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        if status == IngestionStatus.READY_FOR_COMPILATION:
            job.last_completed_stage = IngestionStatus.NORMALIZING
            job.finished_at = datetime.now(UTC)
        self._append_history(job, status)
        self.session.commit()
        self.storage.write_processing(
            self.storage.resolve_relative(job.processing_uri),
            self._processing_payload(job, self._version_for_job(job)),
        )

    def _mark_failed(
        self,
        owner_id: uuid.UUID,
        job_id: uuid.UUID,
        version_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        logger.exception("ingestion_failed", extra={"job_id": str(job_id)})
        self.session.rollback()
        job = self.session.get(IngestionJob, job_id)
        version = self.session.get(DocumentVersion, version_id)
        if job is None or version is None:
            raise exc
        detail = (
            str(exc)
            if isinstance(exc, ParserFailure)
            else f"Processing failed: {type(exc).__name__}."
        )
        job.status = IngestionStatus.FAILED
        job.error = detail[:2000]
        job.finished_at = datetime.now(UTC)
        self._append_history(job, IngestionStatus.FAILED, error=job.error)
        self._audit(owner_id, "ingestion.failed", "ingestion_job", job.id, {"error": job.error})
        self.session.commit()
        self.storage.write_processing(
            self.storage.resolve_relative(job.processing_uri),
            self._processing_payload(job, version),
        )

    def _resolve_document(
        self, *, owner: User, document_id: uuid.UUID | None, original_filename: str
    ) -> Document:
        if document_id is None:
            document = Document(owner_id=owner.id, original_filename=original_filename)
            self.session.add(document)
            self.session.flush()
            return document
        existing_document = self.session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == owner.id,
                Document.deleted_at.is_(None),
            )
        )
        if existing_document is None:
            raise DocumentNotFoundError(str(document_id))
        return existing_document

    def _find_duplicate(
        self, owner_id: uuid.UUID, checksum: str
    ) -> tuple[DocumentVersion, IngestionJob, Document] | None:
        row = self.session.execute(
            select(DocumentVersion, IngestionJob, Document)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
            .where(DocumentVersion.sha256 == checksum, Document.owner_id == owner_id)
        ).one_or_none()
        if row is not None and row[2].deleted_at is not None:
            raise IngestionRetryConflictError(
                "Matching source bytes are being deleted. Retry as a fresh upload after cleanup."
            )
        return row

    def _version_for_job(self, job: IngestionJob) -> DocumentVersion:
        version = self.session.get(DocumentVersion, job.document_version_id)
        if version is None:
            raise RuntimeError("Ingestion job references a missing document version.")
        return version

    @staticmethod
    def _history_entry(status: IngestionStatus, *, error: str | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {"status": status, "at": datetime.now(UTC).isoformat()}
        if error is not None:
            entry["error"] = error
        return entry

    def _append_history(
        self, job: IngestionJob, status: IngestionStatus, *, error: str | None = None
    ) -> None:
        metadata = dict(job.processing_metadata or {})
        history = list(metadata.get("history", []))
        history.append(self._history_entry(status, error=error))
        metadata["history"] = history
        job.processing_metadata = metadata

    @staticmethod
    def _processing_payload(job: IngestionJob, version: DocumentVersion) -> dict[str, Any]:
        return {
            "job_id": str(job.id),
            "document_version_id": str(version.id),
            "status": job.status,
            "attempt_count": job.attempt_count,
            "last_completed_stage": job.last_completed_stage,
            "error": job.error,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "history": job.processing_metadata.get("history", []),
        }

    @staticmethod
    def _metadata_payload(
        document: Document,
        version: DocumentVersion,
        upload: ValidatedUpload,
        parsed: ParsedDocument,
        records: list[SourceRecord],
    ) -> dict[str, Any]:
        return {
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "version_number": version.version_number,
            "original_filename": upload.original_filename,
            "sanitized_filename": upload.sanitized_filename,
            "content_type": upload.content_type,
            "byte_size": version.byte_size,
            "sha256": version.sha256,
            "storage_uri": version.storage_uri,
            "parser": {"name": parsed.parser_name, "version": parsed.parser_version},
            "document_metadata": parsed.document_metadata,
            "dataset_metadata": parsed.dataset_metadata,
            "source_records": [
                {
                    "id": str(record.id),
                    "ordinal": record.ordinal,
                    "locator": record.locator,
                }
                for record in records
            ],
        }

    def _audit(
        self,
        actor_user_id: uuid.UUID,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=str(entity_id),
                payload=payload,
            )
        )
