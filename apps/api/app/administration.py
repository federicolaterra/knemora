"""Authentication and minimal local administration API."""

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import AuditEvent, Permission, Role, RolePermission, User, UserRole
from app.security import (
    PERMISSIONS,
    AuthService,
    Principal,
    SecurityError,
    get_principal,
    hash_password,
    require_permission,
    verify_password,
)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    first_name: str | None
    last_name: str | None
    company: str | None
    visualization_name: str | None
    is_active: bool
    roles: list[str]
    permissions: list[str]
    last_login_at: datetime | None


class UpdateProfileRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company: str | None = Field(default=None, max_length=200)
    visualization_name: str | None = Field(default=None, max_length=200)


class UpdatePasswordRequest(BaseModel):
    current_password: SecretStr
    new_password: SecretStr
    confirm_password: SecretStr


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: SecretStr
    role_names: list[str] = Field(default_factory=list, max_length=20)


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]


class UpsertRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=1_000)
    permissions: list[str] = Field(default_factory=list, max_length=len(PERMISSIONS))


class AssignRolesRequest(BaseModel):
    role_names: list[str] = Field(max_length=20)


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime


class AuditEventPageResponse(BaseModel):
    items: list[AuditEventResponse]
    page: int
    page_limit: int
    total: int
    total_pages: int


class SettingsResponse(BaseModel):
    app_env: str
    authentication_required: bool
    session_ttl_minutes: int
    max_upload_bytes: int
    llm_model: str
    llm_base_url: str
    knowledge_path: str
    source_store_path: str


def _roles_for_user(session: Session, user_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name)
        )
    )


def _user_response(
    session: Session,
    user: User,
    settings: Settings,
    *,
    session_id: uuid.UUID | None = None,
) -> UserResponse:
    principal = AuthService(session=session, settings=settings).principal_for_user(
        user, session_id=session_id
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        company=user.company,
        visualization_name=user.visualization_name,
        is_active=user.is_active,
        roles=_roles_for_user(session, user.id),
        permissions=sorted(principal.permissions),
        last_login_at=user.last_login_at,
    )


def _audit(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )


def create_administration_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["authentication", "administration"])

    def get_session(request: Request) -> Iterator[Session]:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as session:
            yield session

    @router.post("/api/v1/auth/login", response_model=SessionResponse)
    def login(
        body: LoginRequest,
        request: Request,
        background_tasks: BackgroundTasks,
        session: Annotated[Session, Depends(get_session)],
    ) -> SessionResponse:
        metadata = {
            "client": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("User-Agent", "")[:300],
        }
        token, principal, expires_at = AuthService(session=session, settings=settings).login(
            email=body.email, password=body.password.get_secret_value(), client_metadata=metadata
        )
        user = session.get(User, principal.user_id)
        if user is None:
            raise RuntimeError("Authenticated user disappeared.")
        update_service = getattr(request.app.state, "update_service", None)
        if update_service is not None and request.app.state.update_checks_on_login:
            background_tasks.add_task(update_service.schedule_check_if_due)
        return SessionResponse(
            access_token=token,
            expires_at=expires_at,
            user=_user_response(session, user, settings, session_id=principal.session_id),
        )

    @router.get("/api/v1/auth/me", response_model=UserResponse)
    def me(
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserResponse:
        user = session.get(User, principal.user_id)
        if user is None:
            raise RuntimeError("Authenticated user disappeared.")
        return _user_response(session, user, settings, session_id=principal.session_id)

    @router.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        if principal.session_id is not None:
            AuthService(session=session, settings=settings).revoke(
                principal.session_id, actor_user_id=principal.user_id
            )

    @router.put("/api/v1/auth/profile", response_model=UserResponse)
    def update_profile(
        body: UpdateProfileRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserResponse:
        user = session.get(User, principal.user_id)
        if user is None:
            raise RuntimeError("Authenticated user disappeared.")
        email = body.email.strip().lower()
        conflicting_user_id = session.scalar(
            select(User.id).where(User.email == email, User.id != user.id)
        )
        if conflicting_user_id is not None:
            raise SecurityError(
                "A user with that email already exists.",
                status_code=status.HTTP_409_CONFLICT,
                error_type="urn:knemora:error:user-conflict",
            )

        def optional_text(value: str | None) -> str | None:
            cleaned = value.strip() if value is not None else ""
            return cleaned or None

        changed_fields: list[str] = []
        updates = {
            "email": email,
            "first_name": optional_text(body.first_name),
            "last_name": optional_text(body.last_name),
            "company": optional_text(body.company),
            "visualization_name": optional_text(body.visualization_name),
        }
        for field, value in updates.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)
        if changed_fields:
            _audit(
                session,
                actor_user_id=principal.user_id,
                event_type="profile.updated",
                entity_type="user",
                entity_id=str(user.id),
                payload={"fields": sorted(changed_fields)},
            )
            session.commit()
        return _user_response(session, user, settings, session_id=principal.session_id)

    @router.put("/api/v1/auth/password", status_code=status.HTTP_204_NO_CONTENT)
    def update_password(
        body: UpdatePasswordRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        user = session.get(User, principal.user_id)
        if user is None or user.password_hash is None:
            raise RuntimeError("Authenticated user disappeared.")
        current_password = body.current_password.get_secret_value()
        new_password = body.new_password.get_secret_value()
        confirm_password = body.confirm_password.get_secret_value()
        if not verify_password(current_password, user.password_hash):
            raise SecurityError(
                "The current password is incorrect.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_type="urn:knemora:error:invalid-current-password",
            )
        if new_password != confirm_password:
            raise SecurityError(
                "The new passwords do not match.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_type="urn:knemora:error:password-mismatch",
            )
        try:
            user.password_hash = hash_password(new_password)
        except ValueError as error:
            raise SecurityError(
                str(error),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_type="urn:knemora:error:invalid-password",
            ) from error
        _audit(
            session,
            actor_user_id=principal.user_id,
            event_type="password.updated",
            entity_type="user",
            entity_id=str(user.id),
        )
        session.commit()

    @router.get("/api/v1/users", response_model=list[UserResponse])
    def list_users(
        _: Annotated[Principal, Depends(require_permission("user.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[UserResponse]:
        return [
            _user_response(session, user, settings)
            for user in session.scalars(select(User).order_by(User.email))
        ]

    @router.post("/api/v1/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    def create_user(
        body: CreateUserRequest,
        principal: Annotated[Principal, Depends(require_permission("user.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserResponse:
        email = body.email.strip().lower()
        if session.scalar(select(User.id).where(User.email == email)) is not None:
            raise SecurityError(
                "A user with that email already exists.",
                status_code=status.HTTP_409_CONFLICT,
                error_type="urn:knemora:error:user-conflict",
            )
        roles = list(session.scalars(select(Role).where(Role.name.in_(body.role_names))))
        if len(roles) != len(set(body.role_names)):
            raise SecurityError(
                "One or more requested roles do not exist.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_type="urn:knemora:error:invalid-role",
            )
        user = User(
            email=email,
            display_name=body.display_name.strip(),
            password_hash=hash_password(body.password.get_secret_value()),
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.add_all(UserRole(user_id=user.id, role_id=role.id) for role in roles)
        _audit(
            session,
            actor_user_id=principal.user_id,
            event_type="user.created",
            entity_type="user",
            entity_id=str(user.id),
            payload={"roles": sorted(body.role_names)},
        )
        session.commit()
        return _user_response(session, user, settings)

    @router.put("/api/v1/users/{user_id}/roles", response_model=UserResponse)
    def assign_user_roles(
        user_id: uuid.UUID,
        body: AssignRolesRequest,
        principal: Annotated[Principal, Depends(require_permission("user.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserResponse:
        user = session.get(User, user_id)
        if user is None:
            raise SecurityError(
                "User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
                error_type="urn:knemora:error:user-not-found",
            )
        current_roles = set(_roles_for_user(session, user_id))
        requested_roles = set(body.role_names)
        if (
            user_id == principal.user_id
            and "administrator" in current_roles
            and "administrator" not in requested_roles
        ):
            raise SecurityError(
                "You cannot remove your own administrator role.",
                status_code=status.HTTP_409_CONFLICT,
                error_type="urn:knemora:error:self-lockout",
            )
        roles = list(session.scalars(select(Role).where(Role.name.in_(body.role_names))))
        if len(roles) != len(set(body.role_names)):
            raise SecurityError(
                "One or more requested roles do not exist.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_type="urn:knemora:error:invalid-role",
            )
        for assignment in session.scalars(select(UserRole).where(UserRole.user_id == user_id)):
            session.delete(assignment)
        session.flush()
        session.add_all(UserRole(user_id=user.id, role_id=role.id) for role in roles)
        _audit(
            session,
            actor_user_id=principal.user_id,
            event_type="user.roles_updated",
            entity_type="user",
            entity_id=str(user.id),
            payload={"roles": sorted(body.role_names)},
        )
        session.commit()
        return _user_response(session, user, settings)

    @router.get("/api/v1/roles", response_model=list[RoleResponse])
    def list_roles(
        _: Annotated[Principal, Depends(require_permission("role.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[RoleResponse]:
        roles = list(session.scalars(select(Role).order_by(Role.name)))
        return [
            RoleResponse(
                id=role.id,
                name=role.name,
                description=role.description,
                permissions=list(
                    session.scalars(
                        select(Permission.name)
                        .join(RolePermission, RolePermission.permission_id == Permission.id)
                        .where(RolePermission.role_id == role.id)
                        .order_by(Permission.name)
                    )
                ),
            )
            for role in roles
        ]

    @router.post("/api/v1/roles", response_model=RoleResponse)
    def upsert_role(
        body: UpsertRoleRequest,
        principal: Annotated[Principal, Depends(require_permission("role.manage"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> RoleResponse:
        if body.name == "administrator":
            raise SecurityError(
                "The built-in administrator role cannot be modified.",
                status_code=status.HTTP_409_CONFLICT,
                error_type="urn:knemora:error:protected-role",
            )
        unknown = sorted(set(body.permissions) - set(PERMISSIONS))
        if unknown:
            raise SecurityError(
                f"Unknown permissions: {', '.join(unknown)}",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_type="urn:knemora:error:invalid-permission",
            )
        AuthService(session=session, settings=settings)._seed_permissions()
        role = session.scalar(select(Role).where(Role.name == body.name))
        if role is None:
            role = Role(name=body.name, description=body.description)
            session.add(role)
            session.flush()
        else:
            role.description = body.description
            for assignment in session.scalars(
                select(RolePermission).where(RolePermission.role_id == role.id)
            ):
                session.delete(assignment)
            session.flush()
        permission_rows = list(
            session.scalars(select(Permission).where(Permission.name.in_(body.permissions)))
        )
        session.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permission_rows
        )
        _audit(
            session,
            actor_user_id=principal.user_id,
            event_type="role.updated",
            entity_type="role",
            entity_id=str(role.id),
            payload={"permissions": sorted(body.permissions)},
        )
        session.commit()
        return RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=sorted(body.permissions),
        )

    @router.get(
        "/api/v1/audit-events",
        response_model=list[AuditEventResponse] | AuditEventPageResponse,
    )
    def list_audit_events(
        _: Annotated[Principal, Depends(require_permission("audit.read"))],
        session: Annotated[Session, Depends(get_session)],
        event_type: Annotated[str | None, Query(max_length=150)] = None,
        q: Annotated[str, Query(max_length=200)] = "",
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        page: Annotated[int | None, Query(ge=1)] = None,
        page_limit: Annotated[int, Query(ge=1, le=100)] = 15,
    ) -> list[AuditEventResponse] | AuditEventPageResponse:
        query = select(AuditEvent)
        if event_type:
            query = query.where(AuditEvent.event_type == event_type)
        search = q.strip()
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    AuditEvent.event_type.ilike(pattern),
                    AuditEvent.entity_type.ilike(pattern),
                    AuditEvent.entity_id.ilike(pattern),
                    cast(AuditEvent.payload, String).ilike(pattern),
                )
            )
        total = int(
            session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        )
        query = query.order_by(AuditEvent.created_at.desc())
        if page is None:
            query = query.limit(limit)
        else:
            query = query.offset((page - 1) * page_limit).limit(page_limit)
        items = [
            AuditEventResponse.model_validate(event, from_attributes=True)
            for event in session.scalars(query)
        ]
        if page is None:
            return items
        return AuditEventPageResponse(
            items=items,
            page=page,
            page_limit=page_limit,
            total=total,
            total_pages=max(1, (total + page_limit - 1) // page_limit),
        )

    @router.get("/api/v1/settings", response_model=SettingsResponse)
    def read_settings(
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
    ) -> SettingsResponse:
        return SettingsResponse(
            app_env=settings.app_env,
            authentication_required=settings.authentication_required,
            session_ttl_minutes=settings.auth_session_ttl_minutes,
            max_upload_bytes=settings.max_upload_bytes,
            llm_model=settings.llm_model,
            llm_base_url=settings.llm_base_url,
            knowledge_path=str(settings.knowledge_path),
            source_store_path=str(settings.source_store_path),
        )

    return router


__all__ = ["create_administration_router"]
