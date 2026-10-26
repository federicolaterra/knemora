from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from google.adk.agents.context import Context
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from app.config import Settings
from app.public_web import (
    PublicWebSearchService,
    UnsafePublicQueryError,
    derive_public_query,
)
from knowledge_agent.agent import external_search_requested, guard_user_input


def test_external_search_language_is_not_backend_authority() -> None:
    assert external_search_requested("Look this up on the public web.")
    assert not external_search_requested("What does my Wiki say about Northstar Labs Malta?")

    context = cast(Context, SimpleNamespace(state={"response_mode": "wiki"}))

    async def exercise() -> None:
        request = LlmRequest(
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Search the public web for Northstar Labs.")],
                )
            ]
        )
        assert await guard_user_input(context, request) is None
        assert context.state["external_search_allowed"] is False

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "message",
    [
        "Search the web for our private Wiki project",
        "Search the web using my document",
        "Search the web using the attached file",
        "Look online for previous answer details",
        "Search for person@example.test",
        "Search for api_key=secret-value",
        "Search for 123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_public_query_fails_closed_for_private_or_sensitive_shapes(message: str) -> None:
    with pytest.raises(UnsafePublicQueryError):
        derive_public_query(message)


def test_public_query_uses_only_normalized_current_message() -> None:
    assert derive_public_query("  Search the public web for   Malta weather tomorrow ") == (
        "Malta weather tomorrow"
    )


def test_web_search_is_one_attempt_bounded_and_keeps_only_safe_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, str]] = []

    class FakeDDGS:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 8.0

        def text(self, query: str, *, max_results: int, backend: str) -> list[dict[str, str]]:
            calls.append((query, max_results, backend))
            return [
                {
                    "title": "  Public company result  ",
                    "body": "A public search snippet.",
                    "href": "https://example.test/company",
                },
                {
                    "title": "Unsafe result",
                    "body": "Must be discarded.",
                    "href": "javascript:alert(1)",
                },
            ]

    monkeypatch.setattr("app.public_web.DDGS", FakeDDGS)
    service = PublicWebSearchService(Settings(_env_file=None, web_search_max_results=5))
    outcome = service.search("Northstar Labs Malta")

    assert calls == [("Northstar Labs Malta", 5, "duckduckgo")]
    assert outcome.status == "success"
    assert outcome.succeeded is True
    assert [item.model_dump() for item in outcome.results] == [
        {
            "title": "Public company result",
            "snippet": "A public search snippet.",
            "url": "https://example.test/company",
        }
    ]


@pytest.mark.parametrize("results", [[], RuntimeError("network down")])
def test_web_search_discloses_empty_and_failure_outcomes(
    results: list[dict[str, str]] | RuntimeError,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDDGS:
        def __init__(self, *, timeout: float) -> None:
            pass

        def text(self, query: str, *, max_results: int, backend: str) -> list[dict[str, str]]:
            if isinstance(results, RuntimeError):
                raise results
            return results

    monkeypatch.setattr("app.public_web.DDGS", FakeDDGS)
    outcome = PublicWebSearchService(Settings(_env_file=None)).search("Malta weather")
    assert outcome.attempted is True
    assert outcome.succeeded is False
    assert outcome.status == ("error" if isinstance(results, RuntimeError) else "no_results")
    assert "attempted" in outcome.user_message
