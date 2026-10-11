"""Local operational health and privacy-safe observability endpoints."""

from collections.abc import Iterator, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import AuditEvent, IngestionJob, KnowledgeCompilationJob
from app.knowledge.store import WikiStore
from app.observability import metrics_registry
from app.security import Principal, require_permission


def _duration_average(rows: Sequence[IngestionJob | KnowledgeCompilationJob]) -> float | None:
    durations = [
        (row.finished_at - row.started_at).total_seconds() * 1_000
        for row in rows
        if row.started_at is not None and row.finished_at is not None
    ]
    return round(sum(durations) / len(durations), 3) if durations else None


def create_operations_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["operations"])

    def get_session(request: Request) -> Iterator[Session]:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as session:
            yield session

    @router.get("/api/v1/metrics", response_model=dict[str, Any])
    def read_metrics(
        _: Annotated[Principal, Depends(require_permission("audit.read"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        ingestion = list(session.scalars(select(IngestionJob)))
        compilation = list(session.scalars(select(KnowledgeCompilationJob)))
        lint = WikiStore(settings.knowledge_path).lint()
        reports = [job.report for job in compilation if job.report]
        coverage = [
            float(report["provenance_coverage"])
            for report in reports
            if isinstance(report.get("provenance_coverage"), int | float)
        ]
        issue_counts = {
            code: sum(issue.code == code for issue in lint.issues)
            for code in (
                "broken-wikilink",
                "broken-relationship",
                "orphan-page",
                "duplicate-page-id",
                "ambiguous-title-or-alias",
                "missing-provenance",
                "invalid-contradiction",
            )
        }
        duplicate_uploads = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "source.duplicate_detected")
        )
        return {
            "runtime": metrics_registry.snapshot(),
            "ingestion": {
                "jobs": len(ingestion),
                "failures": sum(job.status == "FAILED" for job in ingestion),
                "average_duration_ms": _duration_average(ingestion),
            },
            "compilation": {
                "jobs": len(compilation),
                "failures": sum(job.status == "FAILED" for job in compilation),
                "average_duration_ms": _duration_average(compilation),
            },
            "knowledge": {
                "pages": lint.page_count,
                "lint_errors": lint.errors,
                "lint_warnings": lint.warnings,
                "issues": issue_counts,
                "average_provenance_coverage": (
                    round(sum(coverage) / len(coverage), 4) if coverage else None
                ),
                "duplicate_uploads": duplicate_uploads or 0,
            },
            "evaluation_only": {
                "citation_coverage": "tracked by the behavioral evaluation suite",
                "unsupported_answer_rate": "tracked by the behavioral evaluation suite",
            },
            "privacy": {
                "message_content_recorded": False,
                "hidden_reasoning_recorded": False,
            },
        }

    return router


__all__ = ["create_operations_router"]
