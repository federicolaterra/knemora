"""FastAPI application boundary for health, readiness, and persisted ADK chat."""

import json
import logging
import unicodedata
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.administration import create_administration_router
from app.config import Settings, get_settings
from app.db.models import AuditEvent
from app.db.session import create_database_engine, create_session_factory, database_is_ready
from app.home import HomeCompatibilityService
from app.ingestion.deletion import SourceDeletionWorker
from app.ingestion.errors import IngestionRequestError
from app.ingestion.migration import SourceFilenameMigrator
from app.ingestion.routes import create_ingestion_router
from app.knowledge.errors import (
    CompilationNotFoundError,
    CompilationNotReadyError,
    DatasetNotFoundError,
    InvalidDatasetAnalysisError,
    KnowledgeError,
    SourceReferenceNotFoundError,
    WikiConflictError,
    WikiPageNotFoundError,
    WikiValidationError,
)
from app.knowledge.routes import create_knowledge_router
from app.llm import LLMProvider, LocalLlamaCppProvider
from app.llm.errors import LLMProviderError
from app.observability import RequestMetricsMiddleware, configure_logging, request_id_context
from app.operations import create_operations_router
from app.product import APP_VERSION, SystemMetadata, create_system_metadata
from app.repositories.chat import ChatRepository, ConversationNotFoundError
from app.security import (
    Principal,
    RateLimitMiddleware,
    SecurityError,
    SecurityHeadersMiddleware,
    require_permission,
)
from app.services.chat import ChatService
from app.updates import create_update_router
from knemora_bootstrap.configuration import AppPaths, configured_data_path
from knemora_bootstrap.update import UpdateService

logger = logging.getLogger(__name__)
FAVICON_PATH = Path(__file__).with_name("static") / "favicon.svg"


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """Reject new mutations while the independent updater replaces services."""

    def __init__(self, app: Any, *, marker: Path) -> None:
        super().__init__(app)
        self.marker = marker

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.marker.is_file() and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "title": "Update in progress",
                    "detail": "Knemora is in maintenance mode while an update is installed.",
                    "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                },
                headers={"Retry-After": "5"},
            )
        return await call_next(request)


class HealthResponse(BaseModel):
    """Stable liveness response contract."""

    status: Literal["ok"]
    service: Literal["knemora-api"]


class CapabilitiesResponse(BaseModel):
    """Stable frontend feature-discovery contract."""

    edition: str
    capabilities: tuple[str, ...]


class ReadinessResponse(BaseModel):
    """Dependency readiness without leaking credentials or stack traces."""

    status: Literal["ready", "not_ready"]
    database: bool
    llm: bool
    model: str


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: str | None = None
    last_activity_at: str | None = None


class ConversationListResponse(ConversationResponse):
    message_count: int
    updated_at: str


class ConversationPageResponse(BaseModel):
    items: list[ConversationListResponse]
    page: int
    page_limit: int
    total: int
    total_pages: int


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Conversation titles cannot be empty.")
        if any(unicodedata.category(character).startswith("C") for character in title):
            raise ValueError("Conversation titles cannot contain control characters.")
        return title


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class MessageResponse(BaseModel):
    conversation_id: uuid.UUID
    role: Literal["assistant"] = "assistant"
    content: str
    model: str


class PersistedMessageResponse(BaseModel):
    id: uuid.UUID
    sequence: int
    role: str
    content: str
    model: str | None
    created_at: str | None


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Validate or create a correlation ID and return it to the caller."""

    def __init__(self, app: Any, *, header_name: str) -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(self._header_name)
        request_id = supplied[:200] if supplied else str(uuid.uuid4())
        token = request_id_context.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers[self._header_name] = request_id
            return response
        finally:
            request_id_context.reset(token)


def _create_provider(settings: Settings) -> LocalLlamaCppProvider:
    return LocalLlamaCppProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        context_tokens=settings.llm_context_tokens,
        enable_thinking=settings.llm_enable_thinking,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
    )


def _problem(
    request: Request, *, http_status: int, title: str, detail: str, error_type: str
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "type": error_type,
            "title": title,
            "status": http_status,
            "detail": detail,
            "request_id": getattr(request.state, "request_id", "-"),
        },
        media_type="application/problem+json",
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(
    *,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    engine: Engine | None = None,
    update_service: UpdateService | None = None,
) -> FastAPI:
    """Application factory with injectable infrastructure for deterministic tests."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    owns_engine = engine is None
    database_engine = engine or create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(database_engine)
    llm_provider = provider or _create_provider(app_settings)
    source_deletion_worker = SourceDeletionWorker(
        session_factory=session_factory, settings=app_settings
    )
    repository = Path(__file__).resolve().parents[3]
    updates = update_service or UpdateService(
        AppPaths(repository=repository, data=configured_data_path().resolve())
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_engine:
            HomeCompatibilityService(
                configured_data_path(), repository=Path(__file__).resolve().parents[3]
            ).validate_ready()
        migrated = SourceFilenameMigrator(
            session_factory=session_factory, settings=app_settings
        ).run()
        if migrated:
            logger.info("readable_source_filename_migration_completed", extra={"count": migrated})
        source_deletion_worker.start()
        logger.info("api_started")
        try:
            yield
        finally:
            source_deletion_worker.stop()
            database_engine.dispose()
            logger.info("api_stopped")

    application = FastAPI(
        title=f"{app_settings.product_name} API",
        summary="Local-first organizational knowledge application boundary",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    application.state.settings = app_settings
    application.state.engine = database_engine
    application.state.session_factory = session_factory
    application.state.llm_provider = llm_provider
    application.state.source_deletion_worker = source_deletion_worker
    application.state.update_service = updates
    application.state.update_checks_on_login = owns_engine
    application.add_middleware(MaintenanceModeMiddleware, marker=updates.maintenance_path)
    application.add_middleware(RequestMetricsMiddleware)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=app_settings.trusted_host_list)
    application.add_middleware(RateLimitMiddleware, settings=app_settings)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestIdMiddleware, header_name=app_settings.request_id_header)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", app_settings.request_id_header],
    )

    def get_session(request: Request) -> Iterator[Session]:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as session:
            yield session

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Open the branded local API documentation from the service root."""

        return RedirectResponse(url="/docs", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @application.get("/favicon.svg", include_in_schema=False)
    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        """Serve the shared Knemora browser icon for backend surfaces."""

        return FileResponse(FAVICON_PATH, media_type="image/svg+xml")

    @application.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        """Render Swagger UI with the Knemora favicon."""

        return get_swagger_ui_html(
            openapi_url=application.openapi_url or "/openapi.json",
            title=f"{app_settings.product_name} API docs",
            swagger_favicon_url="/favicon.svg",
        )

    @application.get("/redoc", include_in_schema=False)
    def redoc_ui() -> HTMLResponse:
        """Render ReDoc with the Knemora favicon."""

        return get_redoc_html(
            openapi_url=application.openapi_url or "/openapi.json",
            title=f"{app_settings.product_name} API docs",
            redoc_favicon_url="/favicon.svg",
        )

    @application.exception_handler(ConversationNotFoundError)
    async def conversation_not_found(
        request: Request, exc: ConversationNotFoundError
    ) -> JSONResponse:
        return _problem(
            request,
            http_status=status.HTTP_404_NOT_FOUND,
            title="Conversation not found",
            detail=f"Conversation {exc} does not exist.",
            error_type="urn:knemora:error:conversation-not-found",
        )

    @application.exception_handler(LLMProviderError)
    async def provider_failure(request: Request, exc: LLMProviderError) -> JSONResponse:
        logger.warning("llm_provider_failure", exc_info=exc)
        return _problem(
            request,
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Local model unavailable",
            detail="The configured local model could not complete the request.",
            error_type="urn:knemora:error:llm-unavailable",
        )

    @application.exception_handler(RequestValidationError)
    async def validation_failure(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            request,
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Request validation failed",
            detail="The request did not match the required schema.",
            error_type="urn:knemora:error:validation",
        )

    @application.exception_handler(SecurityError)
    async def security_failure(request: Request, exc: SecurityError) -> JSONResponse:
        titles = {
            status.HTTP_401_UNAUTHORIZED: "Authentication required",
            status.HTTP_403_FORBIDDEN: "Access denied",
            status.HTTP_404_NOT_FOUND: "Security resource not found",
            status.HTTP_409_CONFLICT: "Security resource conflict",
            status.HTTP_422_UNPROCESSABLE_CONTENT: "Invalid security request",
            status.HTTP_423_LOCKED: "Account locked",
        }
        response = _problem(
            request,
            http_status=exc.status_code,
            title=titles.get(exc.status_code, "Security request failed"),
            detail=str(exc),
            error_type=exc.error_type,
        )
        if exc.status_code == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @application.exception_handler(IngestionRequestError)
    async def ingestion_request_failure(
        request: Request, exc: IngestionRequestError
    ) -> JSONResponse:
        return _problem(
            request,
            http_status=exc.status_code,
            title=exc.title,
            detail=str(exc),
            error_type=exc.error_type,
        )

    @application.exception_handler(KnowledgeError)
    async def knowledge_failure(request: Request, exc: KnowledgeError) -> JSONResponse:
        if isinstance(
            exc,
            (
                WikiPageNotFoundError,
                CompilationNotFoundError,
                DatasetNotFoundError,
                SourceReferenceNotFoundError,
            ),
        ):
            http_status = status.HTTP_404_NOT_FOUND
            title = "Knowledge resource not found"
        elif isinstance(exc, (WikiConflictError, CompilationNotReadyError)):
            http_status = status.HTTP_409_CONFLICT
            title = "Knowledge operation conflict"
        elif isinstance(exc, (WikiValidationError, InvalidDatasetAnalysisError)):
            http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
            title = "Wiki validation failed"
        else:
            http_status = status.HTTP_400_BAD_REQUEST
            title = "Knowledge operation failed"
        return _problem(
            request,
            http_status=http_status,
            title=title,
            detail=str(exc),
            error_type="urn:knemora:error:knowledge",
        )

    @application.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        """Report process liveness without touching dependencies."""

        return HealthResponse(status="ok", service="knemora-api")

    @application.get("/api/v1/system", response_model=SystemMetadata, tags=["system"])
    def system_metadata() -> SystemMetadata:
        """Expose centralized product identity and non-sensitive runtime metadata."""

        return create_system_metadata(app_settings)

    @application.get(
        "/api/v1/system/capabilities", response_model=CapabilitiesResponse, tags=["system"]
    )
    def system_capabilities() -> CapabilitiesResponse:
        """Expose edition-neutral feature discovery for current and future clients."""

        metadata = create_system_metadata(app_settings)
        return CapabilitiesResponse(
            edition=metadata.product.edition,
            capabilities=metadata.capabilities,
        )

    @application.get(
        "/api/v1/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
        tags=["system"],
    )
    async def ready(request: Request) -> ReadinessResponse | JSONResponse:
        """Report database and local-model readiness independently."""

        database_ready = database_is_ready(request.app.state.engine)
        llm_health = await request.app.state.llm_provider.health()
        payload = ReadinessResponse(
            status="ready" if database_ready and llm_health.healthy else "not_ready",
            database=database_ready,
            llm=llm_health.healthy,
            model=llm_health.model,
        )
        if payload.status == "not_ready":
            return JSONResponse(status_code=503, content=payload.model_dump())
        return payload

    @application.post(
        "/api/v1/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["chat"],
    )
    def create_conversation(
        body: CreateConversationRequest,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> ConversationResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        conversation = repository.create_conversation(user=user, title=body.title)
        repository.commit()
        return ConversationResponse(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=_timestamp(conversation.created_at),
            last_activity_at=_timestamp(conversation.created_at),
        )

    @application.get(
        "/api/v1/conversations",
        response_model=list[ConversationListResponse] | ConversationPageResponse,
        tags=["chat"],
    )
    def list_conversations(
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
        page: Annotated[int | None, Query(ge=1)] = None,
        page_limit: Annotated[int | None, Query(ge=1, le=100)] = None,
        query: Annotated[str, Query(alias="q", max_length=300)] = "",
    ) -> list[ConversationListResponse] | ConversationPageResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        effective_limit = page_limit or (15 if page is not None else 8)
        rows, total = repository.list_conversations(
            user.id,
            query=query,
            offset=((page or 1) - 1) * effective_limit,
            limit=effective_limit,
        )
        items = [
            ConversationListResponse(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                message_count=message_count,
                created_at=_timestamp(conversation.created_at),
                last_activity_at=_timestamp(last_activity),
                updated_at=_timestamp(last_activity) or "",
            )
            for conversation, message_count, last_activity in rows
        ]
        if page is None:
            return items
        return ConversationPageResponse(
            items=items,
            page=page,
            page_limit=effective_limit,
            total=total,
            total_pages=(total + effective_limit - 1) // effective_limit if total else 0,
        )

    @application.get(
        "/api/v1/conversations/{conversation_id}",
        response_model=ConversationResponse,
        tags=["chat"],
    )
    def get_conversation(
        conversation_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> ConversationResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        conversation = repository.get_conversation(conversation_id, user_id=user.id)
        return ConversationResponse(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=_timestamp(conversation.created_at),
            last_activity_at=_timestamp(conversation.created_at),
        )

    @application.patch(
        "/api/v1/conversations/{conversation_id}",
        response_model=ConversationResponse,
        tags=["chat"],
    )
    def rename_conversation(
        conversation_id: uuid.UUID,
        body: RenameConversationRequest,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> ConversationResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        conversation = repository.rename_conversation(
            conversation_id, user_id=user.id, title=body.title
        )
        session.add(
            AuditEvent(
                actor_user_id=user.id,
                event_type="conversation.renamed",
                entity_type="conversation",
                entity_id=str(conversation.id),
                payload={},
            )
        )
        repository.commit()
        return ConversationResponse(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=_timestamp(conversation.created_at),
            last_activity_at=_timestamp(conversation.created_at),
        )

    @application.get(
        "/api/v1/conversations/{conversation_id}/messages",
        response_model=list[PersistedMessageResponse],
        tags=["chat"],
    )
    def list_messages(
        conversation_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[PersistedMessageResponse]:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        repository.get_conversation(conversation_id, user_id=user.id)
        return [
            PersistedMessageResponse(
                id=message.id,
                sequence=message.sequence,
                role=message.role,
                content=message.content,
                model=message.provider_model,
                created_at=_timestamp(message.created_at),
            )
            for message in repository.list_messages(conversation_id)
        ]

    @application.delete(
        "/api/v1/conversations/{conversation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["chat"],
    )
    def delete_conversation(
        conversation_id: uuid.UUID,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        repository.delete_conversation(conversation_id, user_id=user.id)
        session.add(
            AuditEvent(
                actor_user_id=user.id,
                event_type="conversation.deleted",
                entity_type="conversation",
                entity_id=str(conversation_id),
                payload={},
            )
        )
        repository.commit()

    @application.post(
        "/api/v1/conversations/{conversation_id}/messages",
        response_model=MessageResponse,
        tags=["chat"],
    )
    async def send_message(
        conversation_id: uuid.UUID,
        body: SendMessageRequest,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> MessageResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        conversation = repository.get_conversation(conversation_id, user_id=user.id)
        service = ChatService(
            repository=repository,
            provider=llm_provider,
            settings=app_settings,
            session_factory=session_factory,
            model_name=app_settings.llm_model,
            max_output_tokens=app_settings.llm_max_output_tokens,
        )
        content = await service.reply(
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            content=body.content,
        )
        return MessageResponse(
            conversation_id=conversation.id,
            content=content,
            model=app_settings.llm_model,
        )

    @application.post(
        "/api/v1/conversations/{conversation_id}/messages/stream",
        response_class=StreamingResponse,
        tags=["chat"],
    )
    async def stream_message(
        conversation_id: uuid.UUID,
        body: SendMessageRequest,
        principal: Annotated[Principal, Depends(require_permission("chat.use"))],
        session: Annotated[Session, Depends(get_session)],
    ) -> StreamingResponse:
        repository = ChatRepository(session)
        user = repository.get_user(principal.user_id)
        conversation = repository.get_conversation(conversation_id, user_id=user.id)
        service = ChatService(
            repository=repository,
            provider=llm_provider,
            settings=app_settings,
            session_factory=session_factory,
            model_name=app_settings.llm_model,
            max_output_tokens=app_settings.llm_max_output_tokens,
        )

        async def events() -> AsyncIterator[str]:
            event_id = str(uuid.uuid4())
            yield _sse(
                "message.started",
                {"event_id": event_id, "conversation_id": str(conversation.id)},
            )
            try:
                async for chunk in service.stream_reply(
                    conversation_id=conversation.id,
                    user_id=conversation.user_id,
                    content=body.content,
                ):
                    yield _sse("message.delta", {"event_id": event_id, "delta": chunk})
                yield _sse("message.completed", {"event_id": event_id})
            except Exception as exc:
                logger.exception("chat_stream_failed")
                yield _sse(
                    "error",
                    {"event_id": event_id, "error": type(exc).__name__},
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    application.include_router(create_administration_router(app_settings))
    application.include_router(create_operations_router(app_settings))
    application.include_router(create_ingestion_router(app_settings))
    application.include_router(create_knowledge_router(app_settings))
    application.include_router(create_update_router(app_settings))
    return application


app = create_app()
