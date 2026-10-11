"""Durable, restart-resumable source deletion pipeline."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
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
    SourceRecord,
    WikiChange,
)
from app.ingestion.errors import DocumentNotFoundError, IngestionRetryConflictError
from app.ingestion.storage import SourceStorage
from app.knowledge.store import WikiStore


class SourceDeletionService:
    """Accept deletions transactionally and expose owner-scoped operation state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def accept(self, *, owner_id: uuid.UUID, document_id: uuid.UUID) -> SourceDeletionJob:
        existing = self.session.scalar(
            select(SourceDeletionJob).where(
                SourceDeletionJob.owner_id == owner_id,
                SourceDeletionJob.document_id == document_id,
            )
        )
        if existing is not None:
            return existing
        document = self.session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == owner_id,
                Document.deleted_at.is_(None),
            )
        )
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        versions = list(
            self.session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version_number)
            )
        )
        operation = SourceDeletionJob(
            id=uuid.uuid4(),
            owner_id=owner_id,
            document_id=document.id,
            display_filename=document.original_filename,
            status="PENDING",
            stage="ACCEPTED",
            attempt_count=0,
            target_version_ids=[str(item.id) for item in versions],
            artifact_uris=[item.storage_uri for item in versions],
            error=None,
        )
        document.deleted_at = datetime.now(UTC)
        self.session.add_all(
            [
                operation,
                AuditEvent(
                    actor_user_id=owner_id,
                    event_type="source.deletion.accepted",
                    entity_type="document",
                    entity_id=str(document.id),
                    payload={"version_count": len(versions), "operation_id": str(operation.id)},
                ),
            ]
        )
        self.session.commit()
        return operation

    def get(self, *, owner_id: uuid.UUID, operation_id: uuid.UUID) -> SourceDeletionJob:
        job = self.session.scalar(
            select(SourceDeletionJob).where(
                SourceDeletionJob.id == operation_id,
                SourceDeletionJob.owner_id == owner_id,
            )
        )
        if job is None:
            raise DocumentNotFoundError(str(operation_id))
        return job

    def list(self, *, owner_id: uuid.UUID) -> list[SourceDeletionJob]:
        return list(
            self.session.scalars(
                select(SourceDeletionJob)
                .where(SourceDeletionJob.owner_id == owner_id)
                .order_by(SourceDeletionJob.created_at.desc())
                .limit(50)
            )
        )

    def retry(self, *, owner_id: uuid.UUID, operation_id: uuid.UUID) -> SourceDeletionJob:
        job = self.get(owner_id=owner_id, operation_id=operation_id)
        if job.status != "FAILED":
            raise IngestionRetryConflictError("Only a failed deletion operation can be retried.")
        job.status = "PENDING"
        job.error = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = None
        self.session.commit()
        return job


class SourceDeletionWorker:
    """Small persisted SQLite worker with leases, retries, and stage resumption."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        poll_seconds: float = 1.0,
    ) -> None:
        self.session_factory = session_factory
        self.storage = SourceStorage(settings.source_store_path)
        self.store = WikiStore(settings.knowledge_path)
        self.poll_seconds = poll_seconds
        self.worker_id = str(uuid.uuid4())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="source-deletion", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            self.run_once()

    def run_once(self) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            job_id = session.scalar(
                select(SourceDeletionJob.id)
                .where(
                    or_(
                        SourceDeletionJob.status == "PENDING",
                        (
                            (SourceDeletionJob.status == "RUNNING")
                            & (SourceDeletionJob.lease_expires_at < now)
                        ),
                    )
                )
                .order_by(SourceDeletionJob.created_at)
                .limit(1)
            )
        if job_id is None:
            return False
        self.run_operation(job_id)
        return True

    def run_operation(self, operation_id: uuid.UUID) -> None:
        with self.session_factory() as session:
            now = datetime.now(UTC)
            claimed = session.execute(
                update(SourceDeletionJob)
                .where(
                    SourceDeletionJob.id == operation_id,
                    or_(
                        SourceDeletionJob.status == "PENDING",
                        (
                            (SourceDeletionJob.status == "RUNNING")
                            & (SourceDeletionJob.lease_expires_at < now)
                        ),
                    ),
                )
                .values(
                    status="RUNNING",
                    attempt_count=SourceDeletionJob.attempt_count + 1,
                    lease_owner=self.worker_id,
                    lease_expires_at=now + timedelta(minutes=5),
                    started_at=func.coalesce(SourceDeletionJob.started_at, now),
                )
            )
            session.commit()
            if getattr(claimed, "rowcount", 0) != 1:
                return
            job = session.get(SourceDeletionJob, operation_id)
            if job is None:
                return
            try:
                self._execute(session, job)
            except Exception as exc:
                session.rollback()
                failed = session.get(SourceDeletionJob, operation_id)
                if failed is None:
                    raise
                failed.status = "FAILED"
                failed.error = f"{type(exc).__name__}: cleanup stage failed"
                failed.lease_owner = None
                failed.lease_expires_at = None
                failed.finished_at = datetime.now(UTC)
                session.commit()

    def _execute(self, session: Session, job: SourceDeletionJob) -> None:
        version_ids = set(job.target_version_ids)
        if job.stage == "ACCEPTED":
            with self.store.compilation_lock():
                report = self.store.reconcile_deleted_versions(version_ids)
            job.stage = "KNOWLEDGE_RECONCILED"
            session.add(
                AuditEvent(
                    actor_user_id=job.owner_id,
                    event_type="source.deletion.knowledge_reconciled",
                    entity_type="source_deletion_job",
                    entity_id=str(job.id),
                    payload=report,
                )
            )
            session.commit()

        if job.stage == "KNOWLEDGE_RECONCILED":
            for uri in job.artifact_uris:
                self.storage.remove_version_directory(uri)
            job.stage = "ARTIFACTS_PURGED"
            session.commit()

        if job.stage == "ARTIFACTS_PURGED":
            ids = [uuid.UUID(item) for item in job.target_version_ids]
            source_ids = list(
                session.scalars(
                    select(SourceRecord.id).where(SourceRecord.document_version_id.in_(ids))
                )
            )
            if source_ids:
                session.execute(
                    delete(WikiChange).where(WikiChange.source_record_id.in_(source_ids))
                )
            session.execute(
                delete(KnowledgeCompilationJob).where(
                    KnowledgeCompilationJob.document_version_id.in_(ids)
                )
            )
            session.execute(delete(DatasetRecord).where(DatasetRecord.document_version_id.in_(ids)))
            session.execute(delete(SourceRecord).where(SourceRecord.document_version_id.in_(ids)))
            session.execute(delete(IngestionJob).where(IngestionJob.document_version_id.in_(ids)))
            session.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(ids)))
            session.execute(
                delete(Document).where(
                    Document.id == job.document_id, Document.owner_id == job.owner_id
                )
            )
            job.stage = "METADATA_CLEANED"
            job.status = "COMPLETED"
            job.error = None
            job.artifact_uris = []
            job.lease_owner = None
            job.lease_expires_at = None
            job.finished_at = datetime.now(UTC)
            session.add(
                AuditEvent(
                    actor_user_id=job.owner_id,
                    event_type="source.deletion.completed",
                    entity_type="source_deletion_job",
                    entity_id=str(job.id),
                    payload={"document_id": str(job.document_id)},
                )
            )
            session.commit()


__all__ = ["SourceDeletionService", "SourceDeletionWorker"]
