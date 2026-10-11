from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from google.adk.agents.context import Context
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from knowledge_agent.agent import external_search_requested, guard_user_input
from knowledge_agent.tools import ToolCallable, create_agent_tools


def _web_tool(tmp_path: Path) -> ToolCallable:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        authentication_required=False,
        web_search_enabled=True,
        source_store_path=tmp_path / "sources",
        knowledge_path=tmp_path / "knowledge",
    )
    factory = sessionmaker(bind=engine, class_=Session)
    return next(
        tool
        for tool in create_agent_tools(settings=settings, session_factory=factory)
        if tool.__name__ == "search_web"
    )


def _context(*, allowed: bool) -> ToolContext:
    return cast(ToolContext, SimpleNamespace(state={"external_search_allowed": allowed}))


def test_external_search_request_requires_explicit_turn_language() -> None:
    assert external_search_requested(
        "Tell me about Northstar Labs Malta; search results outside my wiki knowledge."
    )
    assert external_search_requested("Look this up on the public web.")
    assert not external_search_requested("What does my Wiki say about Northstar Labs Malta?")


def test_model_guard_sets_per_turn_external_search_consent() -> None:
    context = cast(Context, SimpleNamespace(state={}))

    async def exercise() -> None:
        allowed = LlmRequest(
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Search the public web for Northstar Labs.")],
                )
            ]
        )
        assert await guard_user_input(context, allowed) is None
        assert context.state["external_search_allowed"] is True

        private_only = LlmRequest(
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Search only my Wiki for Northstar Labs.")],
                )
            ]
        )
        assert await guard_user_input(context, private_only) is None
        assert context.state["external_search_allowed"] is False

    asyncio.run(exercise())


def test_web_search_is_opt_in_bounded_and_returns_only_safe_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    monkeypatch.setattr("knowledge_agent.tools.DDGS", FakeDDGS)
    tool = _web_tool(tmp_path)

    blocked = tool("Northstar Labs Malta", 10, _context(allowed=False))
    allowed = tool("  Northstar   Labs Malta  ", 10, _context(allowed=True))

    assert blocked["status"] == "error"
    assert calls == [("Northstar Labs Malta", 5, "duckduckgo")]
    assert allowed == {
        "status": "success",
        "source": "external_web",
        "query": "Northstar Labs Malta",
        "untrusted": True,
        "results": [
            {
                "title": "Public company result",
                "snippet": "A public search snippet.",
                "url": "https://example.test/company",
            }
        ],
    }
