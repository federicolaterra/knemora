import asyncio

from httpx import ASGITransport, AsyncClient

from tests.test_chat_api import build_test_app


def test_product_lists_conversations_and_documents() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=build_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/conversations", json={"title": "Quality review"})
            assert created.status_code == 201

            conversations = await client.get("/api/v1/conversations")
            assert conversations.status_code == 200
            assert conversations.json()[0]["title"] == "Quality review"
            assert conversations.json()[0]["message_count"] == 0

            documents = await client.get("/api/v1/documents")
            assert documents.status_code == 200
            assert documents.json() == []

    asyncio.run(exercise())
