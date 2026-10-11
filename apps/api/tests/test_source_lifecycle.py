from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, SourceDeletionJob, SourceRecord
from app.ingestion.deletion import SourceDeletionService
from app.ingestion.errors import IngestionRequestError
from app.ingestion.migration import SourceFilenameMigrator
from app.ingestion.storage import MAX_STORAGE_FILENAME_LENGTH, readable_storage_filename
from app.ingestion.validation import sanitize_filename
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
from tests.test_ingestion import build_test_app, upload


@pytest.mark.parametrize(
    ("filename", "extension", "expected"),
    [
        ("Relazione tecnica 2026.pdf", ".pdf", "Relazione_tecnica_2026.pdf"),
        ("Résumé Federico.docx", ".docx", "Resume_Federico.docx"),
        ("Mini PC – AI 2026.csv", ".csv", "Mini_PC_AI_2026.csv"),
        ("例.txt", ".txt", "source.txt"),
        (".hidden.txt", ".txt", "hidden.txt"),
    ],
)
def test_readable_storage_filename_policy(filename: str, extension: str, expected: str) -> None:
    assert (
        readable_storage_filename(filename, extension=extension, identity=uuid.UUID(int=1))
        == expected
    )


def test_storage_filename_reserves_artifacts_devices_collisions_and_length() -> None:
    identity = uuid.UUID("12345678-0000-0000-0000-000000000000")
    assert readable_storage_filename("extracted.md", extension=".md", identity=identity) == (
        "extracted_12345678.md"
    )
    assert readable_storage_filename("CON.txt", extension=".txt", identity=identity) == (
        "CON_12345678.txt"
    )
    assert (
        readable_storage_filename(
            "Report.txt", extension=".txt", identity=identity, existing_names={"report.txt"}
        )
        == "Report_12345678.txt"
    )
    long_name = readable_storage_filename(f"{'a' * 500}.pdf", extension=".pdf", identity=identity)
    assert len(long_name) == MAX_STORAGE_FILENAME_LENGTH
    assert long_name.endswith(".pdf")
    with pytest.raises(IngestionRequestError):
        sanitize_filename("../escape.txt")
    with pytest.raises(IngestionRequestError):
        sanitize_filename("control\x00.txt")


def test_upload_uses_readable_leaf_but_preserves_exact_display_name(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await upload(client, "Résumé Federico.txt", "text/plain", b"evidence")
            library = await client.get("/api/v1/documents")
        assert response.status_code == 201
        assert Path(response.json()["original_uri"]).name == "Resume_Federico.txt"
        assert library.json()[0]["original_filename"] == "Résumé Federico.txt"
        assert (tmp_path / "sources" / response.json()["original_uri"]).read_bytes() == b"evidence"

    asyncio.run(exercise())


def test_legacy_original_migration_is_repeatable_and_updates_references(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await upload(client, "Résumé Federico.txt", "text/plain", b"legacy bytes")
        body = response.json()
        readable = tmp_path / "sources" / body["original_uri"]
        legacy = readable.with_name("original.txt")
        readable.rename(legacy)
        legacy_uri = legacy.relative_to(tmp_path / "sources").as_posix()
        manifest = tmp_path / "knowledge" / "sources" / f"{body['document_version_id']}.md"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(f"immutable_source_uri: {legacy_uri}\n", encoding="utf-8")
        with Session(app.state.engine) as session:
            version = session.get(DocumentVersion, uuid.UUID(body["document_version_id"]))
            assert version is not None
            version.storage_uri = legacy_uri
            session.commit()

        migrator = SourceFilenameMigrator(
            session_factory=app.state.session_factory, settings=app.state.settings
        )
        assert migrator.run() == 1
        assert migrator.run() == 0
        with Session(app.state.engine) as session:
            version = session.get(DocumentVersion, uuid.UUID(body["document_version_id"]))
            assert version is not None
            assert Path(version.storage_uri).name == "Resume_Federico.txt"
            migrated = tmp_path / "sources" / version.storage_uri
            assert migrated.read_bytes() == b"legacy bytes"
            journal = json.loads(
                (migrated.parent / "source-name-migration.json").read_text(encoding="utf-8")
            )
            assert journal["status"] == "completed"
            assert version.storage_uri in manifest.read_text(encoding="utf-8")

    asyncio.run(exercise())


def test_legacy_migration_resumes_after_filesystem_rename(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await upload(client, "Interrupted name.txt", "text/plain", b"same bytes")
        body = response.json()
        readable = tmp_path / "sources" / body["original_uri"]
        legacy = readable.with_name("original.txt")
        readable.rename(legacy)
        legacy_uri = legacy.relative_to(tmp_path / "sources").as_posix()
        new_uri = readable.relative_to(tmp_path / "sources").as_posix()
        with Session(app.state.engine) as session:
            version = session.get(DocumentVersion, uuid.UUID(body["document_version_id"]))
            assert version is not None
            version.storage_uri = legacy_uri
            session.commit()
        legacy.rename(readable)
        (readable.parent / "source-name-migration.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "document_version_id": body["document_version_id"],
                    "old_uri": legacy_uri,
                    "new_uri": new_uri,
                    "sha256": body["checksum"],
                    "status": "prepared",
                }
            ),
            encoding="utf-8",
        )

        migrator = SourceFilenameMigrator(
            session_factory=app.state.session_factory, settings=app.state.settings
        )
        assert migrator.run() == 1
        with Session(app.state.engine) as session:
            version = session.get(DocumentVersion, uuid.UUID(body["document_version_id"]))
            assert version is not None
            assert version.storage_uri == new_uri
        assert readable.read_bytes() == b"same bytes"

    asyncio.run(exercise())


def _provenance(record: SourceRecord, document_id: str, filename: str) -> ProvenanceRef:
    return ProvenanceRef(
        source_record_id=str(record.id),
        document_id=document_id,
        document_version_id=str(record.document_version_id),
        original_filename=filename,
        sha256="0" * 64,
        locator=record.locator,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        compilation_version="test/1",
        compiled_at=datetime.now(UTC),
    )


def test_whole_document_deletion_reconciles_shared_knowledge_and_purges_all_versions(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await upload(client, "alpha.txt", "text/plain", b"alpha evidence")
            second_version = await upload(
                client,
                "alpha v2.txt",
                "text/plain",
                b"alpha revised",
                document_id=first.json()["document_id"],
            )
            surviving = await upload(client, "beta.txt", "text/plain", b"beta evidence")
            original_paths = [
                tmp_path / "sources" / first.json()["original_uri"],
                tmp_path / "sources" / second_version.json()["original_uri"],
            ]

            with Session(app.state.engine) as session:
                alpha_record = session.scalar(
                    select(SourceRecord).where(
                        SourceRecord.document_version_id
                        == uuid.UUID(first.json()["document_version_id"])
                    )
                )
                beta_record = session.scalar(
                    select(SourceRecord).where(
                        SourceRecord.document_version_id
                        == uuid.UUID(surviving.json()["document_version_id"])
                    )
                )
                assert alpha_record is not None and beta_record is not None
                alpha = _provenance(alpha_record, first.json()["document_id"], "alpha.txt")
                beta = _provenance(beta_record, surviving.json()["document_id"], "beta.txt")

            now = datetime.now(UTC)
            removed_page = WikiPage(
                id="removed-page",
                type=PageKind.CONCEPT,
                title="Deleted only",
                summary="Deleted-only summary",
                created_at=now,
                updated_at=now,
                compilation_version="test/1",
                provenance=(alpha,),
                claims=(
                    WikiClaim(
                        id="deleted-page-claim",
                        key="deleted-key",
                        text="Deleted-only fact",
                        classification=ClaimClassification.SOURCE_FACT,
                        status=ClaimStatus.SUPPORTED,
                        provenance=(alpha,),
                    ),
                ),
            )
            shared_page = WikiPage(
                id="shared-page",
                type=PageKind.ENTITY,
                title="Shared subject",
                summary="Deleted-only fact. Surviving fact.",
                created_at=now,
                updated_at=now,
                compilation_version="test/1",
                provenance=(alpha, beta),
                claims=(
                    WikiClaim(
                        id="alpha-claim",
                        key="shared-key",
                        text="Deleted-only fact",
                        classification=ClaimClassification.SOURCE_FACT,
                        status=ClaimStatus.DISPUTED,
                        provenance=(alpha,),
                        conflicts_with=("beta-claim",),
                    ),
                    WikiClaim(
                        id="beta-claim",
                        key="shared-key",
                        text="Surviving fact",
                        classification=ClaimClassification.SOURCE_FACT,
                        status=ClaimStatus.DISPUTED,
                        provenance=(beta,),
                        conflicts_with=("alpha-claim",),
                    ),
                ),
                relationships=(
                    WikiRelationship(
                        relation="references",
                        target_id="surviving-page",
                        target_title="Surviving target",
                        provenance=(alpha,),
                    ),
                ),
            )
            surviving_page = WikiPage(
                id="surviving-page",
                type=PageKind.CONCEPT,
                title="Surviving target",
                summary="Independent target",
                created_at=now,
                updated_at=now,
                compilation_version="test/1",
                provenance=(beta,),
                claims=(
                    WikiClaim(
                        id="target-claim",
                        key="target-key",
                        text="Independent target",
                        classification=ClaimClassification.SOURCE_FACT,
                        provenance=(beta,),
                    ),
                ),
            )
            store = WikiStore(tmp_path / "knowledge")
            store.apply_pages_transactionally((removed_page, shared_page, surviving_page))

            with Session(app.state.engine) as session:
                owner_id = session.scalar(
                    select(DocumentVersion.owner_id).where(
                        DocumentVersion.id == uuid.UUID(first.json()["document_version_id"])
                    )
                )
                assert owner_id is not None
                accepted = SourceDeletionService(session).accept(
                    owner_id=owner_id, document_id=uuid.UUID(first.json()["document_id"])
                )
                accepted_id = str(accepted.id)
            pending_search = await client.get("/api/v1/wiki/search?q=Deleted-only")
            pending_page = await client.get("/api/v1/wiki/pages/shared-page")
            pending_graph = await client.get("/api/v1/wiki/graph")
            deleted = await client.delete(f"/api/v1/documents/{first.json()['document_id']}")
            operation = await client.get(f"/api/v1/source-deletion-operations/{accepted_id}")
            hidden_download = await client.get(
                f"/api/v1/document-versions/{first.json()['document_version_id']}/original"
            )
            pages = await client.get("/api/v1/wiki/pages")

        assert deleted.status_code == 202
        assert deleted.json()["status"] == "PENDING"
        assert deleted.json()["id"] == accepted_id
        assert pending_search.json() == []
        assert "Deleted-only fact" not in pending_page.json()["summary"]
        assert [item["text"] for item in pending_page.json()["claims"]] == ["Surviving fact"]
        assert pending_page.json()["claims"][0]["status"] == "supported"
        assert pending_page.json()["claims"][0]["conflicts_with"] == []
        assert pending_graph.json()["edges"] == []
        assert operation.json()["status"] == "COMPLETED"
        assert hidden_download.status_code == 404
        assert {item["title"] for item in pages.json()} == {
            "Shared subject",
            "Surviving target",
        }
        reconciled = store.read_page("shared-page")
        assert [claim.text for claim in reconciled.claims] == ["Surviving fact"]
        assert reconciled.claims[0].status == ClaimStatus.SUPPORTED
        assert reconciled.claims[0].conflicts_with == ()
        assert reconciled.relationships == ()
        assert "Deleted-only fact" not in reconciled.summary
        assert all(not path.parent.exists() for path in original_paths)
        with Session(app.state.engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentVersion)
                    .where(DocumentVersion.document_id == uuid.UUID(first.json()["document_id"]))
                )
                == 0
            )
            job = session.get(SourceDeletionJob, uuid.UUID(operation.json()["id"]))
            assert job is not None and job.artifact_uris == []

    asyncio.run(exercise())


def test_pending_deletion_immediately_blocks_reads_analysis_and_duplicate_reactivation(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await upload(
                client, "numbers.csv", "text/csv", b"category,value\na,1\nb,2\n"
            )
            body = uploaded.json()
            with Session(app.state.engine) as session:
                owner_id = session.scalar(select(DocumentVersion.owner_id))
                assert owner_id is not None
                operation = SourceDeletionService(session).accept(
                    owner_id=owner_id,
                    document_id=uuid.UUID(body["document_id"]),
                )
                operation_id = operation.id

            download = await client.get(
                f"/api/v1/document-versions/{body['document_version_id']}/original"
            )
            analysis = await client.post(
                f"/api/v1/datasets/{body['document_version_id']}/analyze",
                json={"operation": "describe"},
            )
            duplicate = await upload(
                client, "numbers.csv", "text/csv", b"category,value\na,1\nb,2\n"
            )
            status = await client.get(f"/api/v1/source-deletion-operations/{operation_id}")

        assert download.status_code == 404
        assert analysis.status_code == 404
        assert duplicate.status_code == 409
        assert status.json()["status"] == "PENDING"

        with Session(app.state.engine) as session:
            interrupted = session.get(SourceDeletionJob, operation_id)
            assert interrupted is not None
            interrupted.status = "RUNNING"
            interrupted.lease_owner = "stopped-worker"
            interrupted.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        assert app.state.source_deletion_worker.run_once() is True
        with Session(app.state.engine) as session:
            completed = session.get(SourceDeletionJob, operation_id)
            assert completed is not None and completed.status == "COMPLETED"

    asyncio.run(exercise())


def test_symlink_escape_fails_closed_and_retry_resumes_without_touching_target(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = build_test_app(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await upload(client, "attack.txt", "text/plain", b"isolated")
            body = uploaded.json()
            original = tmp_path / "sources" / body["original_uri"]
            version_directory = original.parent
            for child in version_directory.iterdir():
                child.unlink()
            version_directory.rmdir()
            version_directory.symlink_to(outside, target_is_directory=True)

            accepted = await client.delete(f"/api/v1/documents/{body['document_id']}")
            operation_id = accepted.json()["id"]
            failed = await client.get(f"/api/v1/source-deletion-operations/{operation_id}")
            blocked = await client.get(
                f"/api/v1/document-versions/{body['document_version_id']}/original"
            )
            assert failed.json()["status"] == "FAILED"
            assert failed.json()["stage"] == "KNOWLEDGE_RECONCILED"
            assert blocked.status_code == 404
            assert marker.read_text(encoding="utf-8") == "preserve"

            version_directory.unlink()
            retried = await client.post(f"/api/v1/source-deletion-operations/{operation_id}/retry")
            completed = await client.get(f"/api/v1/source-deletion-operations/{operation_id}")

        assert retried.status_code == 202
        assert completed.json()["status"] == "COMPLETED"
        assert marker.read_text(encoding="utf-8") == "preserve"

    asyncio.run(exercise())
