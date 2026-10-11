from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.main import create_app
from app.security import hash_password, verify_password
from tests.fakes import FakeLLMProvider

ADMIN_EMAIL = "admin@example.test"
ADMIN_PASSWORD = "correct horse battery staple"


def build_app(tmp_path: Path, **overrides: object) -> FastAPI:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    values: dict[str, object] = {
        "database_url": "sqlite+pysqlite://",
        "llm_model": "fake-local",
        "source_store_path": tmp_path / "sources",
        "knowledge_path": tmp_path / "knowledge",
        "authentication_required": True,
        "bootstrap_admin_email": ADMIN_EMAIL,
        "bootstrap_admin_password": ADMIN_PASSWORD,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    return create_app(settings=settings, provider=FakeLLMProvider(), engine=engine)


async def login(
    client: AsyncClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD
) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_password_hashes_are_salted_and_verified() -> None:
    first = hash_password(ADMIN_PASSWORD)
    second = hash_password(ADMIN_PASSWORD)

    assert first != second
    assert verify_password(ADMIN_PASSWORD, first)
    assert not verify_password("incorrect password value", first)


def test_profile_and_password_updates_preserve_the_bootstrap_account(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await login(client)
            headers = {"Authorization": f"Bearer {token}"}
            profile = await client.put(
                "/api/v1/auth/profile",
                headers=headers,
                json={
                    "email": "federico@example.test",
                    "first_name": "Federico",
                    "last_name": "La Terra",
                    "company": "Knemora Labs",
                    "visualization_name": "Fede",
                },
            )
            mismatch = await client.put(
                "/api/v1/auth/password",
                headers=headers,
                json={
                    "current_password": ADMIN_PASSWORD,
                    "new_password": "a new secure password",
                    "confirm_password": "a different secure password",
                },
            )
            password = await client.put(
                "/api/v1/auth/password",
                headers=headers,
                json={
                    "current_password": ADMIN_PASSWORD,
                    "new_password": "a new secure password",
                    "confirm_password": "a new secure password",
                },
            )
            new_token = await login(client, "federico@example.test", "a new secure password")
            users = await client.get(
                "/api/v1/users", headers={"Authorization": f"Bearer {new_token}"}
            )
            old_login = await client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )

        assert profile.status_code == 200
        assert profile.json()["first_name"] == "Federico"
        assert profile.json()["last_name"] == "La Terra"
        assert profile.json()["company"] == "Knemora Labs"
        assert profile.json()["visualization_name"] == "Fede"
        assert mismatch.status_code == 422
        assert password.status_code == 204
        assert users.status_code == 200
        assert len(users.json()) == 1
        assert users.json()[0]["email"] == "federico@example.test"
        assert old_login.status_code == 401

    asyncio.run(exercise())


def test_example_bootstrap_password_must_be_replaced() -> None:
    with pytest.raises(ValueError, match="Replace the example bootstrap"):
        Settings(
            _env_file=None,
            bootstrap_admin_password="replace-with-a-unique-local-password",
        )


def test_cors_preflight_allows_conversation_title_patches(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/v1/conversations/00000000-0000-0000-0000-000000000000",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "PATCH",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "PATCH" in response.headers["access-control-allow-methods"]

    asyncio.run(exercise())


def test_authentication_rbac_logout_and_security_headers(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            public = await client.get("/api/v1/health")
            denied = await client.get("/api/v1/documents")
            token = await login(client)
            admin_headers = {"Authorization": f"Bearer {token}"}
            me = await client.get("/api/v1/auth/me", headers=admin_headers)
            metrics = await client.get("/api/v1/metrics", headers=admin_headers)
            protected_role = await client.post(
                "/api/v1/roles",
                headers=admin_headers,
                json={
                    "name": "administrator",
                    "description": "Accidental replacement",
                    "permissions": [],
                },
            )
            self_lockout = await client.put(
                f"/api/v1/users/{me.json()['id']}/roles",
                headers=admin_headers,
                json={"role_names": []},
            )
            role = await client.post(
                "/api/v1/roles",
                headers=admin_headers,
                json={
                    "name": "reader",
                    "description": "Read-only knowledge user",
                    "permissions": ["document.read", "knowledge.read"],
                },
            )
            created_user = await client.post(
                "/api/v1/users",
                headers=admin_headers,
                json={
                    "email": "reader@example.test",
                    "display_name": "Reader",
                    "password": "reader password long enough",
                    "role_names": ["reader"],
                },
            )
            reader_token = await login(client, "reader@example.test", "reader password long enough")
            reader_headers = {"Authorization": f"Bearer {reader_token}"}
            allowed = await client.get("/api/v1/documents", headers=reader_headers)
            forbidden = await client.get("/api/v1/audit-events", headers=reader_headers)
            logged_out = await client.post("/api/v1/auth/logout", headers=reader_headers)
            expired = await client.get("/api/v1/auth/me", headers=reader_headers)

        assert public.status_code == 200
        assert public.headers["x-content-type-options"] == "nosniff"
        assert public.headers["x-frame-options"] == "DENY"
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"
        assert me.status_code == 200
        assert "role.manage" in me.json()["permissions"]
        assert metrics.status_code == 200
        assert metrics.json()["privacy"] == {
            "message_content_recorded": False,
            "hidden_reasoning_recorded": False,
        }
        assert protected_role.status_code == 409
        assert self_lockout.status_code == 409
        assert role.status_code == 200
        assert created_user.status_code == 201
        assert allowed.status_code == 200
        assert forbidden.status_code == 403
        assert logged_out.status_code == 204
        assert expired.status_code == 401

    asyncio.run(exercise())


def test_source_deletion_purges_bytes_and_reupload_creates_fresh_source(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await login(client)
            headers = {"Authorization": f"Bearer {token}"}
            uploaded = await client.post(
                "/api/v1/documents",
                headers=headers,
                files={"file": ("evidence.txt", b"immutable evidence", "text/plain")},
            )
            body = uploaded.json()
            source_path = tmp_path / "sources" / body["original_uri"]
            source_path.chmod(0o644)
            source_path.write_bytes(b"tampered evidence")
            integrity_failure = await client.get(
                f"/api/v1/document-versions/{body['document_version_id']}/original",
                headers=headers,
            )
            source_path.write_bytes(b"immutable evidence")
            source_path.chmod(0o444)
            retired = await client.delete(
                f"/api/v1/documents/{body['document_id']}", headers=headers
            )
            library = await client.get("/api/v1/documents", headers=headers)
            hidden = await client.get(
                f"/api/v1/document-versions/{body['document_version_id']}/original",
                headers=headers,
            )
            restored = await client.post(
                "/api/v1/documents",
                headers=headers,
                files={"file": ("evidence.txt", b"immutable evidence", "text/plain")},
            )

        assert uploaded.status_code == 201
        assert integrity_failure.status_code == 409
        assert retired.status_code == 202
        assert retired.json()["status"] == "PENDING"
        assert not source_path.exists()
        assert library.json() == []
        assert hidden.status_code == 404
        assert restored.status_code == 201
        assert restored.json()["duplicate"] is False
        assert restored.json()["document_version_id"] != body["document_version_id"]

    asyncio.run(exercise())


def test_login_rate_limit_and_account_lockout(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = build_app(
            tmp_path,
            login_rate_limit_per_minute=3,
            auth_max_failed_attempts=2,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": "wrong password value"},
            )
            second = await client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": "wrong password value"},
            )
            locked = await client.post(
                "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
            )
            limited = await client.post(
                "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
            )
        assert first.status_code == 401
        assert second.status_code == 401
        assert locked.status_code == 423
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert limited.headers["x-content-type-options"] == "nosniff"
        assert limited.headers["x-frame-options"] == "DENY"

    asyncio.run(exercise())
