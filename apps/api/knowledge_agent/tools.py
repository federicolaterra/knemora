"""Narrow, owner-scoped agent tools for retrieval and deterministic analysis."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from google.adk.tools.tool_context import ToolContext
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Permission, RolePermission, User, UserRole
from app.knowledge.access import KnowledgeAccessService
from app.knowledge.analysis import DatasetAnalysisRequest, DatasetAnalysisService
from app.knowledge.errors import KnowledgeError
from app.knowledge.types import PageKind
from app.observability import metrics_registry

ToolCallable = Callable[..., dict[str, Any]]
logger = logging.getLogger(__name__)


def _instrument_tool(tool: ToolCallable) -> ToolCallable:
    """Record content-free tool latency and result size while preserving ADK introspection."""

    @wraps(tool)
    def measured(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        result = tool(*args, **kwargs)
        elapsed_ms = (time.monotonic() - started) * 1_000
        result_chars = len(json.dumps(result, ensure_ascii=False, default=str))
        metrics_registry.increment(f"adk.tool.{tool.__name__}.calls")
        metrics_registry.observe(f"adk.tool.{tool.__name__}.duration", elapsed_ms)
        logger.info(
            "adk_tool_completed name=%s duration_ms=%.1f result_chars=%d status=%s",
            tool.__name__,
            elapsed_ms,
            result_chars,
            result.get("status", "unknown"),
        )
        return result

    return measured


def _citation_payload(citation: Any) -> dict[str, Any]:
    """Keep the citation fields needed for quotation and authorized source drilldown."""

    return {
        "wiki_path": citation.wiki_path,
        "source_record_id": citation.source_record_id,
        "original_filename": citation.original_filename,
        "locator": citation.locator,
    }


def _agent_page_payload(page: Any) -> dict[str, Any]:
    """Return compact evidence so several page reads fit in the local model context."""

    return {
        "id": page.id,
        "type": page.type.value,
        "title": page.title,
        "path": page.path,
        "summary": page.summary,
        "claims": [
            {
                "id": claim.id,
                "key": claim.key,
                "text": claim.text,
                "classification": claim.classification,
                "status": claim.status,
                "conflicts_with": list(claim.conflicts_with),
                "citations": [_citation_payload(item) for item in claim.citations],
            }
            for claim in page.claims
        ],
        "relationships": [
            {
                "relation": relationship.relation,
                "target_id": relationship.target_id,
                "target_title": relationship.target_title,
            }
            for relationship in page.relationships
        ],
        "truncated": page.truncated,
    }


def _bounded_web_result(item: dict[str, Any]) -> dict[str, str] | None:
    """Keep only short text fields and ordinary public HTTP(S) result URLs."""

    url = str(item.get("href") or item.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return {
        "title": " ".join(str(item.get("title") or "Untitled result").split())[:300],
        "snippet": " ".join(str(item.get("body") or item.get("description") or "").split())[:1_000],
        "url": url[:2_000],
    }


def create_agent_tools(
    *, settings: Settings, session_factory: sessionmaker[Session]
) -> list[ToolCallable]:
    """Create isolated function tools backed by short-lived database sessions."""

    def owner_id(session: Session, tool_context: ToolContext, *, permission: str) -> uuid.UUID:
        if settings.app_env == "evaluation" and not settings.authentication_required:
            evaluation_user = session.scalar(
                select(User).where(User.email == settings.default_user_email, User.is_active)
            )
            if evaluation_user is None:
                raise PermissionError("The isolated evaluation owner is missing.")
            return evaluation_user.id
        try:
            candidate = uuid.UUID(tool_context.user_id)
        except ValueError as exc:
            raise PermissionError("The agent session has no valid authenticated owner.") from exc
        user = session.get(User, candidate)
        if user is None or not user.is_active:
            raise PermissionError("The agent session owner is inactive or missing.")
        if settings.authentication_required:
            authorized = session.scalar(
                select(Permission.id)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(UserRole, UserRole.role_id == RolePermission.role_id)
                .where(UserRole.user_id == candidate, Permission.name == permission)
                .limit(1)
            )
            if authorized is None:
                raise PermissionError(f"Permission {permission} is required.")
        return candidate

    def search_wiki(
        query: str,
        page_types: list[str],
        topics: list[str],
        limit: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Search authorized Wiki metadata and evidence with identity matching and BM25.

        Args:
            query: Words, exact title, alias, stable page ID, or empty text when browsing filters.
            page_types: Optional page type filters: entity, concept, topic, synthesis, or dataset.
            topics: Optional exact topic metadata filters.
            limit: Maximum candidate pages to return, from 1 to 20.

        Returns:
            Candidate Wiki pages with scores, match fields, paths, and retrieval modes.
        """

        try:
            kinds = tuple(PageKind(item) for item in page_types)
            with session_factory() as session:
                service = KnowledgeAccessService(
                    session=session,
                    settings=settings,
                    owner_id=owner_id(session, tool_context, permission="knowledge.read"),
                ).retrieval()
                hits = service.search(
                    query=query, page_types=kinds, topics=tuple(topics), limit=min(limit, 4)
                )
                if not hits and query.strip() and (kinds or topics):
                    hits = service.search(
                        query=query,
                        page_types=(),
                        topics=(),
                        limit=min(limit, 4),
                    )
            return {
                "status": "success",
                "results": [item.model_dump(mode="json") for item in hits],
            }
        except (KnowledgeError, PermissionError, ValueError) as exc:
            return {"status": "error", "error": str(exc)}

    def read_wiki_page(
        identifier: str,
        max_claims: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Read bounded authorized evidence and citations from one Wiki page.

        Args:
            identifier: Stable page ID, exact title, or alias returned by search_wiki.
            max_claims: Maximum claims to return, from 1 to 100.

        Returns:
            Page evidence, relationships, Wiki paths, and original-source citations.
        """

        try:
            with session_factory() as session:
                page = (
                    KnowledgeAccessService(
                        session=session,
                        settings=settings,
                        owner_id=owner_id(session, tool_context, permission="knowledge.read"),
                    )
                    .retrieval()
                    .read_page(
                        identifier,
                        max_claims=min(
                            max_claims,
                            max(4, min(20, settings.llm_context_tokens // 512)),
                        ),
                    )
                )
            return {"status": "success", "page": _agent_page_payload(page)}
        except (KnowledgeError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def list_related_pages(
        identifier: str,
        max_depth: int,
        limit: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Traverse authorized outgoing links and backlinks from a Wiki page.

        Args:
            identifier: Stable page ID, title, or alias from a previous lookup.
            max_depth: Requested graph depth; the server enforces its configured upper bound.
            limit: Maximum related pages to return, from 1 to 20.

        Returns:
            Related pages with direction, relationship, depth, and traversal origin.
        """

        try:
            with session_factory() as session:
                pages = (
                    KnowledgeAccessService(
                        session=session,
                        settings=settings,
                        owner_id=owner_id(session, tool_context, permission="knowledge.read"),
                    )
                    .retrieval()
                    .related_pages(
                        identifier,
                        max_depth=max_depth,
                        limit=min(limit, max(4, settings.llm_context_tokens // 1024)),
                    )
                )
            return {
                "status": "success",
                "results": [item.model_dump(mode="json") for item in pages],
            }
        except (KnowledgeError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def get_backlinks(
        identifier: str,
        limit: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """List authorized Wiki pages that link to a page.

        Args:
            identifier: Stable page ID, exact title, or alias.
            limit: Maximum backlink records to return, from 1 to 20.

        Returns:
            Incoming pages and the relationship by which each references the target.
        """

        try:
            with session_factory() as session:
                pages = (
                    KnowledgeAccessService(
                        session=session,
                        settings=settings,
                        owner_id=owner_id(session, tool_context, permission="knowledge.read"),
                    )
                    .retrieval()
                    .backlinks(
                        identifier,
                        limit=min(limit, max(4, settings.llm_context_tokens // 1024)),
                    )
                )
            return {
                "status": "success",
                "results": [item.model_dump(mode="json") for item in pages],
            }
        except (KnowledgeError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def read_source_reference(
        source_record_id: str,
        max_chars: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Read bounded normalized evidence behind a Wiki citation.

        Args:
            source_record_id: Source record identifier from a Wiki-page citation.
            max_chars: Maximum source characters to return; the server applies a hard limit.

        Returns:
            Source text plus immutable document, checksum, parser, and locator provenance.
        """

        try:
            with session_factory() as session:
                source = KnowledgeAccessService(
                    session=session,
                    settings=settings,
                    owner_id=owner_id(session, tool_context, permission="knowledge.read"),
                ).read_source_reference(
                    source_record_id,
                    max_chars=min(
                        max_chars,
                        settings.source_reference_max_chars,
                        max(1_000, settings.llm_context_tokens),
                    ),
                )
            return {"status": "success", "source": source.model_dump(mode="json")}
        except (KnowledgeError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def analyze_dataset(
        document_version_id: str,
        request: DatasetAnalysisRequest,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Compute an allow-listed deterministic analysis over an authorized CSV or XLSX.

        Args:
            document_version_id: Immutable structured-source version identifier.
            request: Typed filters, grouping, metrics, ranking, trend, statistics, and chart intent.

        Returns:
            Computed rows, optional chart series, and sheet/column/source provenance.
        """

        try:
            version_id = uuid.UUID(document_version_id)
            with session_factory() as session:
                result = DatasetAnalysisService(
                    session=session,
                    settings=settings,
                    owner_id=owner_id(session, tool_context, permission="dataset.analyze"),
                ).analyze(version_id, request)
            return {"status": "success", "analysis": result.model_dump(mode="json")}
        except (KnowledgeError, PermissionError, ValueError) as exc:
            return {"status": "error", "error": str(exc)}

    def search_web(
        query: str,
        limit: int,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Search bounded public web results after the current user explicitly opts in.

        Args:
            query: Public search terms from the user's explicit request. Never include private Wiki
                text, source records, credentials, or opaque internal identifiers.
            limit: Maximum result count from 1 to the configured public-search limit.

        Returns:
            Untrusted external titles, snippets, and source URLs for separately labelled citation.
        """

        if not settings.web_search_enabled:
            return {"status": "error", "error": "Public web search is disabled."}
        if not bool(tool_context.state.get("external_search_allowed", False)):
            return {
                "status": "error",
                "error": (
                    "Public web search requires an explicit request in the current user message."
                ),
            }
        cleaned = " ".join(query.split())
        if not cleaned:
            return {"status": "error", "error": "A public search query is required."}
        if len(cleaned) > 300:
            return {"status": "error", "error": "The public search query is too long."}
        bounded_limit = max(1, min(limit, settings.web_search_max_results))
        try:
            raw_results = DDGS(timeout=settings.web_search_timeout_seconds).text(
                cleaned,
                max_results=bounded_limit,
                backend="duckduckgo",
            )
            results = [
                bounded
                for item in raw_results
                if isinstance(item, dict) and (bounded := _bounded_web_result(item)) is not None
            ][:bounded_limit]
        except Exception as exc:  # The third-party backend exposes provider-specific failures.
            logger.warning("public_web_search_failed error_type=%s", type(exc).__name__)
            return {
                "status": "error",
                "error": "Public web search is temporarily unavailable.",
            }
        return {
            "status": "success",
            "source": "external_web",
            "query": cleaned,
            "untrusted": True,
            "results": results,
        }

    return [
        _instrument_tool(tool)
        for tool in (
            search_wiki,
            read_wiki_page,
            list_related_pages,
            get_backlinks,
            read_source_reference,
            analyze_dataset,
            search_web,
        )
    ]


__all__ = ["ToolCallable", "create_agent_tools"]
