from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, SourceRecord
from app.knowledge.graph import WikiGraphService
from app.knowledge.store import WikiStore
from app.knowledge.types import ClaimStatus, PageSummary
from tests.test_knowledge import ProposalProvider, build_app


def office_proposal(city: str) -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "entity",
                "title": "Acme Corporation",
                "aliases": ["ACME"],
                "topics": [],
                "summary": f"Acme Corporation has an office in {city}.",
                "claims": [
                    {
                        "key": "office_city",
                        "text": f"Acme Corporation has an office in {city}.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [],
            }
        ],
        "warnings": [],
    }


def profile_without_office_proposal() -> dict[str, object]:
    return {
        "pages": [
            {
                "type": "entity",
                "title": "Acme Corporation",
                "aliases": ["ACME"],
                "topics": [],
                "summary": "Acme Corporation published a general company profile.",
                "claims": [
                    {
                        "key": "profile_status",
                        "text": "Acme Corporation published a general company profile.",
                        "classification": "source_fact",
                        "source_record_ordinals": [1],
                    }
                ],
                "relationships": [],
            }
        ],
        "warnings": [],
    }


async def upload_version(
    client: AsyncClient,
    *,
    filename: str,
    content: bytes,
    document_id: str | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/documents",
        data={"document_id": document_id} if document_id is not None else None,
        files={"file": (filename, content, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def compile_version(client: AsyncClient, version_id: str) -> dict[str, Any]:
    response = await client.post(f"/api/v1/document-versions/{version_id}/compile")
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def knowledge_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "compile.lock"
    }


def test_linked_versions_add_corrections_but_do_not_retire_removed_facts(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(
            office_proposal("Rome"),
            office_proposal("Milan"),
            profile_without_office_proposal(),
        )
        app = build_app(tmp_path, provider)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await upload_version(
                client,
                filename="acme-profile-v1.txt",
                content=b"Acme Corporation has an office in Rome.",
            )
            first_compilation = await compile_version(client, first["document_version_id"])
            second = await upload_version(
                client,
                filename="acme-profile-v2.txt",
                content=b"Acme Corporation has an office in Milan.",
                document_id=first["document_id"],
            )
            second_compilation = await compile_version(client, second["document_version_id"])

            store = WikiStore(app.state.settings.knowledge_path)
            corrected = store.read_page("Acme Corporation")
            third = await upload_version(
                client,
                filename="acme-profile-v3.txt",
                content=b"Acme Corporation published a profile without an office location.",
                document_id=first["document_id"],
            )
            third_compilation = await compile_version(client, third["document_version_id"])
            rome_search = await client.get("/api/v1/wiki/search", params={"q": "Rome"})

        retained = store.read_page("Acme Corporation")

        assert first_compilation["status"] == "COMPLETED"
        assert second_compilation["status"] == "COMPLETED"
        assert third_compilation["status"] == "COMPLETED"
        assert second["document_id"] == first["document_id"]
        assert third["document_id"] == first["document_id"]
        assert [first["version_number"], second["version_number"], third["version_number"]] == [
            1,
            2,
            3,
        ]
        assert {claim.text for claim in corrected.claims} == {
            "Acme Corporation has an office in Rome.",
            "Acme Corporation has an office in Milan.",
        }
        assert all(claim.status == ClaimStatus.DISPUTED for claim in corrected.claims)
        assert third_compilation["report"]["pages_created"] == []
        assert [page["title"] for page in third_compilation["report"]["pages_updated"]] == [
            "Acme Corporation"
        ]
        assert {claim.text for claim in retained.claims} == {
            "Acme Corporation has an office in Rome.",
            "Acme Corporation has an office in Milan.",
            "Acme Corporation published a general company profile.",
        }
        assert [hit["title"] for hit in rome_search.json()] == ["Acme Corporation"]
        assert (
            app.state.settings.knowledge_path / "sources" / f"{third['document_version_id']}.md"
        ).exists()
        assert len(provider.requests) == 3

        with Session(app.state.engine) as session:
            versions = tuple(
                session.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == uuid.UUID(first["document_id"]))
                    .order_by(DocumentVersion.version_number)
                )
            )
            assert [version.id for version in versions] == [
                uuid.UUID(first["document_version_id"]),
                uuid.UUID(second["document_version_id"]),
                uuid.UUID(third["document_version_id"]),
            ]

    asyncio.run(exercise())


def test_overlapping_sources_merge_provenance_and_preserve_other_source_on_update(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(
            office_proposal("Rome"),
            office_proposal("Rome"),
            office_proposal("Milan"),
        )
        app = build_app(tmp_path, provider)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await upload_version(
                client,
                filename="acme-operations.txt",
                content=b"Acme Corporation has an office in Rome.",
            )
            await compile_version(client, first["document_version_id"])
            second = await upload_version(
                client,
                filename="acme-directory.txt",
                content=b"Acme Corporation has an office in Rome. Independent directory source.",
            )
            await compile_version(client, second["document_version_id"])

            shared = WikiStore(app.state.settings.knowledge_path).read_page("ACME")

            revised = await upload_version(
                client,
                filename="acme-operations-v2.txt",
                content=b"Acme Corporation has an office in Milan.",
                document_id=first["document_id"],
            )
            await compile_version(client, revised["document_version_id"])

        updated = WikiStore(app.state.settings.knowledge_path).read_page("ACME")
        assert len(shared.claims) == 1
        assert {source.document_version_id for source in shared.claims[0].provenance} == {
            first["document_version_id"],
            second["document_version_id"],
        }

        by_text = {claim.text: claim for claim in updated.claims}
        assert set(by_text) == {
            "Acme Corporation has an office in Rome.",
            "Acme Corporation has an office in Milan.",
        }
        assert {
            source.document_version_id
            for source in by_text["Acme Corporation has an office in Rome."].provenance
        } == {first["document_version_id"], second["document_version_id"]}
        assert {
            source.document_version_id
            for source in by_text["Acme Corporation has an office in Milan."].provenance
        } == {revised["document_version_id"]}
        assert all(claim.status == ClaimStatus.DISPUTED for claim in updated.claims)

    asyncio.run(exercise())


def test_completed_compile_is_cached_while_reprocess_reanalyzes_without_rebuilding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(office_proposal("Rome"), office_proposal("Rome"))
        app = build_app(tmp_path, provider)
        rebuild_calls = 0
        graph_build_calls = 0
        original_rebuild = WikiStore.rebuild_index
        original_graph_build = WikiGraphService._build

        def counted_rebuild(store: WikiStore) -> tuple[PageSummary, ...]:
            nonlocal rebuild_calls
            rebuild_calls += 1
            return original_rebuild(store)

        def counted_graph_build(
            service: WikiGraphService,
            files: list[Path],
            *,
            signature: str,
            wiki_revision: int,
        ) -> Any:
            nonlocal graph_build_calls
            graph_build_calls += 1
            return original_graph_build(
                service,
                files,
                signature=signature,
                wiki_revision=wiki_revision,
            )

        monkeypatch.setattr(WikiStore, "rebuild_index", counted_rebuild)
        monkeypatch.setattr(WikiGraphService, "_build", counted_graph_build)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await upload_version(
                client,
                filename="acme-profile.txt",
                content=b"Acme Corporation has an office in Rome.",
            )
            compiled = await compile_version(client, uploaded["document_version_id"])
            first_graph = await client.get("/api/v1/wiki/graph")
            repeated = await compile_version(client, uploaded["document_version_id"])
            before = knowledge_snapshot(app.state.settings.knowledge_path)

            reprocessed = await client.post(
                f"/api/v1/ingestion-jobs/{uploaded['ingestion_job_id']}/reprocess"
            )
            recompiled = await compile_version(client, uploaded["document_version_id"])
            second_graph = await client.get("/api/v1/wiki/graph")
            after = knowledge_snapshot(app.state.settings.knowledge_path)

        assert compiled["status"] == "COMPLETED"
        assert compiled["attempt_count"] == 1
        assert repeated["id"] == compiled["id"]
        assert repeated["attempt_count"] == 1
        assert reprocessed.json()["status"] == "READY_FOR_COMPILATION"
        assert recompiled["id"] == compiled["id"]
        assert recompiled["attempt_count"] == 2
        assert recompiled["report"]["pages_created"] == []
        assert recompiled["report"]["pages_updated"] == []
        assert first_graph.json() == second_graph.json()
        assert before == after
        assert rebuild_calls == 1
        assert graph_build_calls == 1
        assert len(provider.requests) == 2

        with Session(app.state.engine) as session:
            record_ids = tuple(
                session.scalars(
                    select(SourceRecord.id).where(
                        SourceRecord.document_version_id
                        == uuid.UUID(uploaded["document_version_id"])
                    )
                )
            )
            assert len(record_ids) == 1

    asyncio.run(exercise())


def test_index_failure_rolls_back_page_search_index_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        provider = ProposalProvider(office_proposal("Rome"))
        app = build_app(tmp_path, provider)
        store = WikiStore(app.state.settings.knowledge_path)
        store.initialize()
        before = knowledge_snapshot(app.state.settings.knowledge_path)

        def fail_rebuild(_store: WikiStore) -> tuple[PageSummary, ...]:
            raise RuntimeError("simulated index failure")

        monkeypatch.setattr(WikiStore, "rebuild_index", fail_rebuild)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await upload_version(
                client,
                filename="acme-profile.txt",
                content=b"Acme Corporation has an office in Rome.",
            )
            failed = await compile_version(client, uploaded["document_version_id"])

        after = knowledge_snapshot(app.state.settings.knowledge_path)
        assert failed["status"] == "FAILED"
        assert failed["report"]["pages_created"] == []
        assert failed["report"]["pages_updated"] == []
        assert before == after
        assert store.list_pages() == ()
        assert not (
            app.state.settings.knowledge_path / "sources" / f"{uploaded['document_version_id']}.md"
        ).exists()

    asyncio.run(exercise())
