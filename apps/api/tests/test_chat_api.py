import asyncio
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import Conversation, User
from app.main import create_app
from tests.fakes import FakeLLMProvider


def build_test_app() -> FastAPI:
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
    )
    return create_app(settings=settings, provider=FakeLLMProvider(), engine=engine)


def test_persisted_chat_and_request_id() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=build_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/v1/conversations",
                json={"title": "Deterministic test"},
                headers={"X-Request-ID": "test-request"},
            )
            assert created.status_code == 201
            assert created.headers["X-Request-ID"] == "test-request"
            conversation_id = created.json()["id"]

            response = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "Hello"},
            )
            assert response.status_code == 200
            assert response.json()["content"] == "Hello from fake."
            assert "private scratchpad" not in response.text

            messages = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
            assert [message["role"] for message in messages.json()] == ["user", "assistant"]
            assert messages.json()[1]["content"] == "Hello from fake."

    asyncio.run(exercise())


def test_sse_stream_uses_structured_events_and_persists() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=build_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/conversations", json={})
            conversation_id = created.json()["id"]
            response = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages/stream",
                json={"content": "Stream this"},
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "event: message.started" in response.text
            assert "event: message.delta" in response.text
            assert "event: message.completed" in response.text
            assert "private scratchpad" not in response.text

            messages = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
            assert len(messages.json()) == 2

    asyncio.run(exercise())


def test_conversation_titles_rename_search_and_pagination() -> None:
    async def exercise() -> None:
        app = build_test_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/conversations", json={})
            conversation_id = created.json()["id"]
            first = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={
                    "content": "  Compare   Vue and React for Knemora's dashboard\nIgnore this line"
                },
            )
            detail = await client.get(f"/api/v1/conversations/{conversation_id}")
            renamed = await client.patch(
                f"/api/v1/conversations/{conversation_id}", json={"title": "  Roadmap 🚀  "}
            )
            second = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "This must not replace the manual title"},
            )
            preserved = await client.get(f"/api/v1/conversations/{conversation_id}")
            invalid_empty = await client.patch(
                f"/api/v1/conversations/{conversation_id}", json={"title": "   "}
            )
            invalid_control = await client.patch(
                f"/api/v1/conversations/{conversation_id}", json={"title": "Bad\u0007title"}
            )
            for index in range(16):
                await client.post("/api/v1/conversations", json={"title": f"History {index:02}"})
            recent = await client.get("/api/v1/conversations")
            page = await client.get("/api/v1/conversations", params={"page": 1})
            searched = await client.get("/api/v1/conversations", params={"page": 1, "q": "roadmap"})
            messages = await client.get(f"/api/v1/conversations/{conversation_id}/messages")

        assert first.status_code == 200
        assert detail.json()["title"] == "Compare Vue and React for Knemora's dashboard"
        assert renamed.json()["title"] == "Roadmap 🚀"
        assert second.status_code == 200
        assert preserved.json()["title"] == "Roadmap 🚀"
        assert invalid_empty.status_code == 422
        assert invalid_control.status_code == 422
        assert len(recent.json()) == 8
        assert page.json()["page_limit"] == 15
        assert page.json()["total"] == 17
        assert len(page.json()["items"]) == 15
        assert searched.json()["total"] == 1
        assert messages.json()[0]["created_at"].endswith("+00:00")

    asyncio.run(exercise())


def test_conversation_counts_and_mutations_are_owner_scoped() -> None:
    async def exercise() -> None:
        app = build_test_app()
        with app.state.session_factory() as session:
            foreign_user = User(
                id=uuid.uuid4(),
                email="foreign@example.test",
                display_name="Foreign User",
                is_active=True,
            )
            foreign_conversation = Conversation(
                id=uuid.uuid4(), user_id=foreign_user.id, title="Foreign secret"
            )
            session.add_all((foreign_user, foreign_conversation))
            session.commit()
            foreign_id = foreign_conversation.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            own = await client.post("/api/v1/conversations", json={"title": "Owned"})
            listing = await client.get("/api/v1/conversations", params={"page": 1})
            rename = await client.patch(
                f"/api/v1/conversations/{foreign_id}", json={"title": "Stolen"}
            )
            delete = await client.delete(f"/api/v1/conversations/{foreign_id}")

        assert own.status_code == 201
        assert listing.json()["total"] == 1
        assert rename.status_code == 404
        assert delete.status_code == 404

    asyncio.run(exercise())


def test_conversation_deletion_removes_owner_scoped_history() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=build_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/conversations", json={"title": "Temporary chat"})
            conversation_id = created.json()["id"]
            sent = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "Delete this history"},
            )
            deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
            missing = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
            conversations = await client.get("/api/v1/conversations")
            audit = await client.get(
                "/api/v1/audit-events", params={"event_type": "conversation.deleted"}
            )

        assert sent.status_code == 200
        assert deleted.status_code == 204
        assert missing.status_code == 404
        assert conversations.json() == []
        assert audit.status_code == 200
        assert audit.json()[0]["entity_id"] == conversation_id

    asyncio.run(exercise())


def test_readiness_reports_database_and_fake_model() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=build_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "database": True,
            "llm": True,
            "model": "fake-local",
        }

    asyncio.run(exercise())
