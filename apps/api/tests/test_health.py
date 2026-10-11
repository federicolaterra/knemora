import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import app


async def get(path: str) -> Response:
    transport = ASGITransport(app=app)
    # The repository .env created by first-run setup allows only loopback hosts.
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.get(path)


def test_health_endpoint() -> None:
    response = asyncio.run(get("/api/v1/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "knemora-api"}


def test_openapi_identifies_service() -> None:
    response = asyncio.run(get("/openapi.json"))

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Knemora API"


def test_backend_root_and_documentation_use_the_knemora_favicon() -> None:
    root = asyncio.run(get("/"))
    favicon = asyncio.run(get("/favicon.svg"))
    fallback = asyncio.run(get("/favicon.ico"))
    docs = asyncio.run(get("/docs"))
    redoc = asyncio.run(get("/redoc"))

    assert root.status_code == 307
    assert root.headers["location"] == "/docs"
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert favicon.content.startswith(b"<svg")
    assert b"#33d133" in favicon.content
    assert fallback.content == favicon.content
    assert 'href="/favicon.svg"' in docs.text
    assert 'href="/favicon.svg"' in redoc.text


def test_swagger_ui_has_the_assets_and_scoped_browser_policy_it_needs() -> None:
    response = asyncio.run(get("/docs"))

    assert response.status_code == 200
    assert "SwaggerUIBundle" in response.text
    policy = response.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in policy
    assert "script-src 'self' 'unsafe-inline'" in policy
    assert "connect-src 'self'" in policy

    health = asyncio.run(get("/api/v1/health"))
    assert health.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )


def test_system_metadata_identifies_community_product() -> None:
    response = asyncio.run(get("/api/v1/system"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["product"]["name"] == "Knemora"
    assert payload["product"]["edition"] == "community"
    assert payload["versions"] == {
        "app_version": "0.1.0-alpha",
        "schema_version": 11,
        "knowledge_schema_version": 1,
    }
    assert "document_ingestion" in payload["capabilities"]
    assert payload["telemetry_enabled"] is False
    assert payload["authentication"] == {"default_email": "admin@knemora.local"}


def test_capabilities_endpoint_fails_unknown_capabilities_closed() -> None:
    response = asyncio.run(get("/api/v1/system/capabilities"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["edition"] == "community"
    assert "enterprise_sso" not in payload["capabilities"]
