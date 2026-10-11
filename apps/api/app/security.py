"""Authentication, RBAC, audit, security headers, and local rate limits."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import Settings
from app.db.models import (
    AuditEvent,
    AuthSession,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)

PERMISSIONS: tuple[str, ...] = (
    "chat.use",
    "document.upload",
    "document.read",
    "document.delete",
    "document.reprocess",
    "knowledge.read",
    "knowledge.manage",
    "ingestion.read",
    "ingestion.retry",
    "dataset.analyze",
    "audit.read",
    "user.manage",
    "role.manage",
    "settings.manage",
)

PBKDF2_ITERATIONS = 600_000
bearer_scheme = HTTPBearer(auto_error=False)


class SecurityError(Exception):
    """Safe authentication/authorization failure for the HTTP boundary."""

    def __init__(self, detail: str, *, status_code: int, error_type: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_type = error_type


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    display_name: str
    permissions: frozenset[str]
    session_id: uuid.UUID | None


def ensure_workspace_writable(settings: Settings) -> None:
    """Keep the synthetic Development preset immutable through public APIs."""

    if settings.demo_mode:
        raise SecurityError(
            "The Development demo is read-only. Start normal Knemora to modify sources or data.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_type="urn:knemora:error:demo-read-only",
        )


def hash_password(password: str) -> str:
    """Hash a password with a unique salt and deliberately expensive PBKDF2."""

    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "$".join(
        (
            "pbkdf2-sha256",
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time validation for the stored password representation."""

    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2-sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


class AuthService:
    """Database-backed opaque sessions and role/permission evaluation."""

    def __init__(self, *, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def ensure_bootstrap_admin(self) -> User | None:
        password = self.settings.bootstrap_admin_password
        if password is None:
            return None
        self._seed_permissions()
        user = self.session.scalar(
            select(User).where(User.email == self.settings.bootstrap_admin_email.lower())
        )
        role = self.session.scalar(select(Role).where(Role.name == "administrator"))
        if user is None and role is not None:
            user = self.session.scalar(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(UserRole.role_id == role.id, User.is_active.is_(True))
                .order_by(User.created_at)
            )
        if user is None:
            user = User(
                email=self.settings.bootstrap_admin_email.lower(),
                display_name=self.settings.bootstrap_admin_name,
                password_hash=hash_password(password.get_secret_value()),
                is_active=True,
            )
            self.session.add(user)
            self.session.flush()
        elif user.password_hash is None:
            user.password_hash = hash_password(password.get_secret_value())

        if role is None:
            role = Role(name="administrator", description="Full local release administrator")
            self.session.add(role)
            self.session.flush()
        permission_ids = set(
            self.session.scalars(select(Permission.id).where(Permission.name.in_(PERMISSIONS)))
        )
        existing_permission_ids = set(
            self.session.scalars(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
            )
        )
        self.session.add_all(
            RolePermission(role_id=role.id, permission_id=permission_id)
            for permission_id in permission_ids - existing_permission_ids
        )
        assigned = self.session.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if assigned is None:
            self.session.add(UserRole(user_id=user.id, role_id=role.id))
        self.session.commit()
        return user

    def login(
        self, *, email: str, password: str, client_metadata: dict[str, Any]
    ) -> tuple[str, Principal, datetime]:
        self.ensure_bootstrap_admin()
        now = datetime.now(UTC)
        user = self.session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or user.password_hash is None or not user.is_active:
            self._audit(
                None, "auth.login_failed", "user", "unknown", {"reason": "invalid_credentials"}
            )
            self.session.commit()
            raise SecurityError(
                "Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_type="urn:knemora:error:invalid-credentials",
            )
        locked_until = user.locked_until
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        if locked_until is not None and locked_until > now:
            raise SecurityError(
                "Account is temporarily locked.",
                status_code=status.HTTP_423_LOCKED,
                error_type="urn:knemora:error:account-locked",
            )
        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= self.settings.auth_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=self.settings.auth_lockout_minutes)
                user.failed_login_count = 0
            self._audit(
                user.id,
                "auth.login_failed",
                "user",
                str(user.id),
                {"reason": "invalid_credentials"},
            )
            self.session.commit()
            raise SecurityError(
                "Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_type="urn:knemora:error:invalid-credentials",
            )

        raw_token = secrets.token_urlsafe(48)
        expires_at = now + timedelta(minutes=self.settings.auth_session_ttl_minutes)
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=self._token_hash(raw_token),
            expires_at=expires_at,
            last_seen_at=now,
            client_metadata=client_metadata,
        )
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        self.session.add(auth_session)
        self.session.flush()
        self._audit(user.id, "auth.login_succeeded", "auth_session", str(auth_session.id), {})
        self.session.commit()
        return raw_token, self.principal_for_user(user, session_id=auth_session.id), expires_at

    def authenticate_token(self, raw_token: str) -> Principal:
        now = datetime.now(UTC)
        row = self.session.execute(
            select(AuthSession, User)
            .join(User, AuthSession.user_id == User.id)
            .where(AuthSession.token_hash == self._token_hash(raw_token))
        ).one_or_none()
        if row is None:
            raise self._unauthenticated()
        auth_session, user = row
        expires_at = auth_session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if auth_session.revoked_at is not None or expires_at <= now or not user.is_active:
            raise self._unauthenticated()
        auth_session.last_seen_at = now
        self.session.commit()
        return self.principal_for_user(user, session_id=auth_session.id)

    def revoke(self, session_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> None:
        auth_session = self.session.get(AuthSession, session_id)
        if auth_session is None or auth_session.user_id != actor_user_id:
            raise self._unauthenticated()
        auth_session.revoked_at = datetime.now(UTC)
        self._audit(actor_user_id, "auth.logout", "auth_session", str(session_id), {})
        self.session.commit()

    def principal_for_user(self, user: User, *, session_id: uuid.UUID | None) -> Principal:
        permissions = frozenset(
            self.session.scalars(
                select(Permission.name)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(UserRole, UserRole.role_id == RolePermission.role_id)
                .where(UserRole.user_id == user.id)
            )
        )
        return Principal(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            permissions=permissions,
            session_id=session_id,
        )

    def development_principal(self) -> Principal:
        user = self.session.scalar(
            select(User).where(User.email == self.settings.default_user_email)
        )
        if user is None:
            user = User(
                email=self.settings.default_user_email,
                display_name=self.settings.default_user_name,
                is_active=True,
            )
            self.session.add(user)
            self.session.commit()
        return Principal(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            permissions=frozenset(PERMISSIONS),
            session_id=None,
        )

    def _seed_permissions(self) -> None:
        existing = set(self.session.scalars(select(Permission.name)))
        self.session.add_all(
            Permission(name=name, description=f"Allows {name} operations")
            for name in PERMISSIONS
            if name not in existing
        )
        self.session.flush()

    def _audit(
        self,
        actor_user_id: uuid.UUID | None,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )
        )

    @staticmethod
    def _token_hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @staticmethod
    def _unauthenticated() -> SecurityError:
        return SecurityError(
            "Authentication is required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_type="urn:knemora:error:authentication-required",
        )


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    settings: Settings = request.app.state.settings
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        service = AuthService(session=session, settings=settings)
        if not settings.authentication_required:
            principal = service.development_principal()
        else:
            if credentials is None or credentials.scheme.lower() != "bearer":
                raise service._unauthenticated()
            principal = service.authenticate_token(credentials.credentials)
    request.state.principal = principal
    return principal


def require_permission(permission: str) -> Callable[[Principal], Principal]:
    """Create an explicit backend authorization dependency."""

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if permission not in principal.permissions:
            raise SecurityError(
                f"Permission {permission} is required.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_type="urn:knemora:error:permission-denied",
            )
        return principal

    return dependency


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply browser hardening headers to every API response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path in {"/docs", "/redoc"}:
            content_security_policy = (
                "default-src 'none'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; frame-ancestors 'none'"
            )
        else:
            content_security_policy = "default-src 'none'; frame-ancestors 'none'"
        response.headers.setdefault("Content-Security-Policy", content_security_policy)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith("/api/v1/auth"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small local-process limiter for login and mutation abuse containment."""

    def __init__(self, app: Any, *, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        login = request.url.path == "/api/v1/auth/login"
        limit = (
            self.settings.login_rate_limit_per_minute
            if login
            else self.settings.mutation_rate_limit_per_minute
        )
        key = f"{client}:{'login' if login else 'mutation'}"
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= limit:
                return Response(
                    content='{"detail":"Rate limit exceeded."}',
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )
            events.append(now)
        return await call_next(request)


__all__ = [
    "AuthService",
    "PERMISSIONS",
    "Principal",
    "RateLimitMiddleware",
    "SecurityError",
    "SecurityHeadersMiddleware",
    "get_principal",
    "hash_password",
    "require_permission",
    "verify_password",
]
