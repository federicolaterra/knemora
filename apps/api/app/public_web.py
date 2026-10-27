"""Direct-only, bounded public web search boundary."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from urllib.parse import urlparse

from ddgs import DDGS
from pydantic import BaseModel, ConfigDict

from app.config import Settings

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_URL = re.compile(r"\b(?:https?://|file://|www\.)\S+", re.IGNORECASE)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|password|secret|bearer)\b\s*[:=]",
    re.IGNORECASE,
)
_PRIVATE_CONTEXT = re.compile(
    r"\b(?:our|internal|private|confidential|wiki|source\s+record|uploaded\s+document|"
    r"uploaded\s+file|attached\s+file|attachment|(?:my|this|the)\s+document|"
    r"previous\s+answer|earlier\s+answer|above\s+answer|conversation\s+history)\b",
    re.IGNORECASE,
)
_QUERY_PREFIX = re.compile(
    r"^(?:please\s+)?(?:search|browse|look\s+up|find)(?:\s+the)?\s+"
    r"(?:public\s+)?(?:web|internet|online)(?:\s+for)?\s*[:,-]?\s*",
    re.IGNORECASE,
)


class UnsafePublicQueryError(ValueError):
    """Raised before networking when a current message is unsafe as a public query."""


class PublicWebResult(BaseModel):
    """One bounded untrusted search result."""

    model_config = ConfigDict(frozen=True)

    title: str
    snippet: str
    url: str


class PublicWebOutcome(BaseModel):
    """Truthful outcome of one authorized public search attempt."""

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "no_results", "error"]
    attempted: bool = True
    succeeded: bool
    results: tuple[PublicWebResult, ...] = ()
    user_message: str


def derive_public_query(current_message: str) -> str:
    """Derive a query only from the explicit current message or fail closed."""

    query = " ".join(current_message.split())
    query = _QUERY_PREFIX.sub("", query).strip()
    if not query:
        raise UnsafePublicQueryError("Enter public search terms in the current message.")
    if len(query) > 300:
        raise UnsafePublicQueryError("Public search terms must be 300 characters or fewer.")
    if any(pattern.search(query) for pattern in (_EMAIL, _URL, _UUID, _SECRET, _PRIVATE_CONTEXT)):
        raise UnsafePublicQueryError(
            "Public search cannot use private context, prior answers, documents, URLs, "
            "identifiers, credentials, or contact details. Rephrase with public-only terms."
        )
    return query


def _bounded_result(item: dict[str, Any]) -> PublicWebResult | None:
    url = str(item.get("href") or item.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return PublicWebResult(
        title=" ".join(str(item.get("title") or "Untitled result").split())[:300],
        snippet=" ".join(str(item.get("body") or item.get("description") or "").split())[:1_000],
        url=url[:2_000],
    )


class PublicWebSearchService:
    """Application-owned DDGS adapter with one bounded attempt per call."""

    def __init__(self, settings: Settings) -> None:
        self._timeout_seconds = settings.web_search_timeout_seconds
        self._max_results = settings.web_search_max_results

    def search(self, query: str) -> PublicWebOutcome:
        try:
            raw_results = DDGS(timeout=self._timeout_seconds).text(
                query,
                max_results=self._max_results,
                backend="duckduckgo",
            )
            results = tuple(
                bounded
                for item in raw_results
                if isinstance(item, dict) and (bounded := _bounded_result(item)) is not None
            )[: self._max_results]
        except Exception as exc:  # Third-party failures do not share one stable exception type.
            logger.warning("public_web_search_failed error_type=%s", type(exc).__name__)
            return PublicWebOutcome(
                status="error",
                succeeded=False,
                user_message="Public web search was attempted but is temporarily unavailable.",
            )
        if not results:
            return PublicWebOutcome(
                status="no_results",
                succeeded=False,
                user_message="Public web search was attempted but returned no usable results.",
            )
        return PublicWebOutcome(
            status="success",
            succeeded=True,
            results=results,
            user_message=f"Public web search returned {len(results)} untrusted result(s).",
        )


__all__ = [
    "PublicWebOutcome",
    "PublicWebResult",
    "PublicWebSearchService",
    "UnsafePublicQueryError",
    "derive_public_query",
]
