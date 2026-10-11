"""Prepare an isolated, repeatable Wiki/database fixture for Milestone 05 evals."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import SourceRecord
from app.db.session import create_database_engine
from app.ingestion.service import IngestionResult, IngestionService
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

FIXTURES = Path(__file__).parent / "fixtures"
NAMESPACE = uuid.UUID("d182dd65-8060-5202-b8c0-c8870bdd9156")


def stable_id(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def ingest(
    session: Session, settings: Settings, filename: str
) -> tuple[IngestionResult, SourceRecord]:
    service = IngestionService(session=session, settings=settings)
    owner = service.get_or_create_local_user()
    result = service.ingest(
        owner=owner,
        filename=filename,
        declared_content_type="text/csv" if filename.endswith(".csv") else "text/markdown",
        data=(FIXTURES / filename).read_bytes(),
    )
    record = session.scalar(
        select(SourceRecord)
        .where(SourceRecord.document_version_id == result.version.id)
        .order_by(SourceRecord.ordinal)
    )
    if record is None:
        raise RuntimeError(f"Fixture {filename} produced no source record.")
    return result, record


def source(result: IngestionResult, record: SourceRecord) -> ProvenanceRef:
    return ProvenanceRef(
        source_record_id=str(record.id),
        document_id=str(result.document.id),
        document_version_id=str(result.version.id),
        original_filename=result.document.original_filename,
        sha256=result.version.sha256,
        locator=record.locator,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        compilation_version="knemora-eval/1",
        compiled_at=datetime.now(UTC),
    )


def claim(
    page_id: str,
    key: str,
    text: str,
    provenance: tuple[ProvenanceRef, ...],
    *,
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    conflicts_with: tuple[str, ...] = (),
    classification: ClaimClassification = ClaimClassification.SOURCE_FACT,
) -> WikiClaim:
    return WikiClaim(
        id=stable_id(f"{page_id}:{key}:{text}"),
        key=key,
        text=text,
        classification=classification,
        status=status,
        provenance=provenance,
        conflicts_with=conflicts_with,
    )


def prepare() -> dict[str, object]:
    settings = Settings()
    allowed_marker = "artifacts/eval-fixture"
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Eval fixture setup requires an isolated SQLite database URL.")
    if allowed_marker not in settings.database_url:
        raise RuntimeError("Eval database path must be under artifacts/eval-fixture.")
    if allowed_marker not in settings.source_store_path.as_posix():
        raise RuntimeError("Eval source path must be under artifacts/eval-fixture.")
    if allowed_marker not in settings.knowledge_path.as_posix():
        raise RuntimeError("Eval knowledge path must be under artifacts/eval-fixture.")

    database_path = Path(settings.database_url.removeprefix("sqlite+pysqlite:///"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        profile_result, profile_record = ingest(session, settings, "company-profile.md")
        audit_result, audit_record = ingest(session, settings, "company-audit.md")
        standard_result, standard_record = ingest(session, settings, "distribution-standard.md")
        sales_result, sales_record = ingest(session, settings, "sales.csv")

    profile = (source(profile_result, profile_record),)
    audit = (source(audit_result, audit_record),)
    standard = (source(standard_result, standard_record),)
    sales = (source(sales_result, sales_record),)
    acme_id = stable_id("page:acme")
    cold_id = stable_id("page:cold-chain")
    gdp_id = stable_id("page:gdp")
    nova_id = stable_id("page:nova")
    dataset_id = stable_id("page:sales")
    valletta_id = stable_id(f"{acme_id}:headquarters:valletta")
    milan_id = stable_id(f"{acme_id}:headquarters:milan")
    now = datetime.now(UTC)

    pages = (
        WikiPage(
            id=acme_id,
            type=PageKind.ENTITY,
            title="Acme Corporation",
            aliases=("ACME",),
            topics=("medicine distribution", "supply chain"),
            summary="A medicine distributor with conflicting recorded headquarters.",
            created_at=now,
            updated_at=now,
            compilation_version="knemora-eval/1",
            provenance=(*profile, *audit, *standard),
            claims=(
                WikiClaim(
                    id=valletta_id,
                    key="headquarters",
                    text="The company profile records Valletta as Acme's headquarters.",
                    classification=ClaimClassification.SOURCE_FACT,
                    status=ClaimStatus.DISPUTED,
                    provenance=profile,
                    conflicts_with=(milan_id,),
                ),
                WikiClaim(
                    id=milan_id,
                    key="headquarters",
                    text="The 2026 audit records Milan as Acme's headquarters.",
                    classification=ClaimClassification.SOURCE_FACT,
                    status=ClaimStatus.DISPUTED,
                    provenance=audit,
                    conflicts_with=(valletta_id,),
                ),
                claim(
                    acme_id,
                    "distribution_controls",
                    "Acme uses cold-chain controls governed by GDP.",
                    (*audit, *standard),
                    classification=ClaimClassification.SYNTHESIS,
                ),
            ),
            relationships=(
                WikiRelationship(
                    relation="uses", target_id=cold_id, target_title="Cold Chain", provenance=audit
                ),
                WikiRelationship(
                    relation="markets", target_id=nova_id, target_title="Nova", provenance=profile
                ),
            ),
        ),
        WikiPage(
            id=cold_id,
            type=PageKind.CONCEPT,
            title="Cold Chain",
            aliases=("Temperature-controlled distribution",),
            topics=("logistics", "temperature monitoring"),
            summary="Temperature-controlled medicine distribution.",
            created_at=now,
            updated_at=now,
            compilation_version="knemora-eval/1",
            provenance=standard,
            claims=(
                claim(
                    cold_id,
                    "definition",
                    "Cold Chain is a temperature-controlled distribution process.",
                    standard,
                ),
            ),
            relationships=(
                WikiRelationship(
                    relation="governed_by",
                    target_id=gdp_id,
                    target_title="Good Distribution Practice",
                    provenance=standard,
                ),
            ),
        ),
        WikiPage(
            id=gdp_id,
            type=PageKind.TOPIC,
            title="Good Distribution Practice",
            aliases=("GDP",),
            topics=("quality", "medicine distribution"),
            summary="Quality requirements for medicine distribution.",
            created_at=now,
            updated_at=now,
            compilation_version="knemora-eval/1",
            provenance=standard,
            claims=(
                claim(
                    gdp_id,
                    "temperature_monitoring",
                    "GDP requires temperature monitoring for medicine distribution.",
                    standard,
                ),
            ),
            relationships=(),
        ),
        WikiPage(
            id=nova_id,
            type=PageKind.ENTITY,
            title="Nova",
            aliases=("Nova temperature-monitoring product",),
            topics=("temperature monitoring",),
            summary="A temperature-monitoring product marketed by Acme.",
            created_at=now,
            updated_at=now,
            compilation_version="knemora-eval/1",
            provenance=profile,
            claims=(
                claim(
                    nova_id,
                    "owner",
                    "Acme markets the Nova temperature-monitoring product.",
                    profile,
                ),
            ),
            relationships=(),
        ),
        WikiPage(
            id=dataset_id,
            type=PageKind.DATASET,
            title="sales.csv",
            aliases=("sales",),
            topics=("structured data", "sales", "revenue"),
            summary="Regional and monthly Nova revenue data.",
            created_at=now,
            updated_at=now,
            compilation_version="knemora-eval/1",
            provenance=sales,
            claims=(
                claim(
                    dataset_id,
                    "schema",
                    "sales.csv has month, region, product, and revenue columns.",
                    sales,
                ),
            ),
            relationships=(),
        ),
    )
    lint = WikiStore(settings.knowledge_path).apply_pages_transactionally(pages)
    engine.dispose()
    return {
        "pages": len(pages),
        "lint_errors": lint.errors,
        "dataset_version_id": str(sales_result.version.id),
        "knowledge_path": str(settings.knowledge_path),
    }


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2, sort_keys=True))
