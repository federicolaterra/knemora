"""Persisted chat orchestration through the root ADK agent."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Literal

from google.adk.agents._streaming_mode import StreamingMode
from google.adk.agents.run_config import RunConfig
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.session import Session as AdkSession
from google.genai import types
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.llm import LLMProvider
from app.observability import metrics_registry
from app.repositories.chat import ChatRepository
from knowledge_agent.agent import APP_NAME, create_adk_app, strip_hidden_reasoning
from knowledge_agent.tools import create_agent_tools

ResponseMode = Literal["wiki", "direct"]
logger = logging.getLogger(__name__)
_DECIMAL_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_NUMERIC_ANSWER = re.compile(rf"^\s*({_DECIMAL_PATTERN})\s*[.!]?\s*$")
_EMPHASIZED_NUMERIC_ANSWER = re.compile(rf"(?:\*\*|__)\s*({_DECIMAL_PATTERN})\s*(?:\*\*|__)")
_BINARY_EXPRESSION = re.compile(
    rf"^\s*({_DECIMAL_PATTERN})\s*([+\-*/×÷])\s*({_DECIMAL_PATTERN})\s*$"
)
_ACKNOWLEDGEMENT = r"(?:(?:yes|yeah|yep|ok(?:ay)?|si|sì)\s*(?:[,;:]\s*|\s+))?"
_OPERATOR_FOLLOW_UP = re.compile(
    rf"^\s*{_ACKNOWLEDGEMENT}([+\-*/×÷])\s*({_DECIMAL_PATTERN})\s*$", re.I
)
_WORD_FOLLOW_UPS = (
    (re.compile(rf"^\s*(?:and\s+)?(?:add|plus)\s+({_DECIMAL_PATTERN})\s*$", re.I), "+"),
    (
        re.compile(rf"^\s*(?:and\s+)?(?:subtract|minus)\s+({_DECIMAL_PATTERN})\s*$", re.I),
        "-",
    ),
    (
        re.compile(
            rf"^\s*(?:and\s+)?(?:multiply(?:\s+(?:it|that|the\s+result))?\s+by|times)"
            rf"\s+({_DECIMAL_PATTERN})\s*$",
            re.I,
        ),
        "*",
    ),
    (
        re.compile(
            rf"^\s*(?:and\s+)?divide(?:\s+(?:it|that|the\s+result))?\s+by"
            rf"\s+({_DECIMAL_PATTERN})\s*$",
            re.I,
        ),
        "/",
    ),
)


def _follow_up_operation(content: str) -> tuple[str, str] | None:
    symbolic = _OPERATOR_FOLLOW_UP.fullmatch(content)
    if symbolic is not None:
        return symbolic.group(1), symbolic.group(2)
    for pattern, operator in _WORD_FOLLOW_UPS:
        if match := pattern.fullmatch(content):
            return operator, match.group(1)
    return None


def _calculate_decimal(left: str, operator: str, right: str) -> str | None:
    """Evaluate one bounded decimal operation without executing user-provided code."""

    try:
        left_value = Decimal(left)
        right_value = Decimal(right)
        if operator == "+":
            result = left_value + right_value
        elif operator == "-":
            result = left_value - right_value
        elif operator in {"*", "×"}:
            result = left_value * right_value
        else:
            result = left_value / right_value
    except (DivisionByZero, InvalidOperation):
        return None
    if result == 0:
        return "0"
    return format(result.normalize(), "f")


def _numeric_answer(content: str) -> str | None:
    direct = _NUMERIC_ANSWER.fullmatch(content)
    if direct is not None:
        return direct.group(1)
    emphasized = [match.group(1) for match in _EMPHASIZED_NUMERIC_ANSWER.finditer(content)]
    if len(emphasized) == 1:
        return emphasized[0]
    return None


def _arithmetic_answer(messages: list[tuple[str, str]], content: str) -> str | None:
    """Resolve a bounded expression or continuation without general code evaluation."""

    expression = _BINARY_EXPRESSION.fullmatch(content)
    if expression is not None:
        return _calculate_decimal(expression.group(1), expression.group(2), expression.group(3))
    operation = _follow_up_operation(content)
    if operation is None or not messages or messages[-1][0] != "assistant":
        return None
    prior = _numeric_answer(messages[-1][1])
    if prior is None:
        return None
    operator, operand = operation
    return _calculate_decimal(prior, operator, operand)


async def _replay_history(
    session_service: InMemorySessionService,
    session: AdkSession,
    messages: list[tuple[str, str]],
) -> None:
    """Reconstruct persisted turns with native roles in an isolated ADK session."""

    for role, content in messages:
        await session_service.append_event(
            session,
            Event(
                invocation_id=f"persisted-{uuid.uuid4()}",
                author="user" if role == "user" else APP_NAME,
                content=types.Content(
                    role="user" if role == "user" else "model",
                    parts=[types.Part.from_text(text=content)],
                ),
            ),
        )


class ChatService:
    """Coordinates persistence and one isolated ADK invocation."""

    def __init__(
        self,
        *,
        repository: ChatRepository,
        provider: LLMProvider,
        settings: Settings,
        session_factory: sessionmaker[Session],
        model_name: str,
        max_output_tokens: int,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._settings = settings
        self._session_factory = session_factory
        self._model_name = model_name
        self._max_output_tokens = max_output_tokens

    async def stream_reply(
        self,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str,
        response_mode: ResponseMode = "wiki",
    ) -> AsyncIterator[str]:
        total_started = time.monotonic()
        history_started = total_started
        conversation = self._repository.get_conversation(conversation_id, user_id=user_id)
        history = self._repository.list_messages(conversation_id)
        prior = [(message.role, message.content) for message in history]
        history_ms = (time.monotonic() - history_started) * 1_000
        self._repository.assign_initial_title(conversation, content)
        self._repository.add_message(conversation_id=conversation_id, role="user", content=content)

        arithmetic_answer = _arithmetic_answer(prior, content)
        if arithmetic_answer is not None:
            self._repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=arithmetic_answer,
                provider_model=self._model_name,
            )
            self._repository.commit()
            elapsed_ms = (time.monotonic() - total_started) * 1_000
            metrics_registry.observe("chat.request.duration", elapsed_ms)
            logger.info(
                "chat_request_completed",
                extra={
                    "knemora_fields": {
                        "model": self._model_name,
                        "response_mode": response_mode,
                        "duration_ms": round(elapsed_ms, 3),
                        "history_preparation_ms": round(history_ms, 3),
                        "history_length": len(prior),
                        "stream": True,
                        "tools_count": 0,
                        "model_calls": 0,
                        "deterministic_arithmetic": True,
                    }
                },
            )
            yield arithmetic_answer
            return

        session_started = time.monotonic()
        adk_session_id = str(uuid.uuid4())
        self._repository.ensure_agent_session(
            conversation_id=conversation_id, adk_session_id=adk_session_id
        )
        self._repository.commit()

        session_service = InMemorySessionService()
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=str(user_id),
            session_id=adk_session_id,
            state={
                "conversation_id": str(conversation_id),
                "response_mode": response_mode,
            },
        )
        await _replay_history(session_service, session, prior)
        tools_started = time.monotonic()
        tools = (
            create_agent_tools(settings=self._settings, session_factory=self._session_factory)
            if response_mode == "wiki"
            else ()
        )
        tools_ms = (time.monotonic() - tools_started) * 1_000
        runner = Runner(
            app=create_adk_app(
                self._provider,
                model_name=self._model_name,
                max_output_tokens=self._max_output_tokens,
                tools=tools,
                response_mode=response_mode,
            ),
            session_service=session_service,
        )
        prompt = types.Content(
            role="user",
            parts=[types.Part.from_text(text=content)],
        )
        session_ms = (time.monotonic() - session_started) * 1_000
        response_parts: list[str] = []
        first_visible_ms: float | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for event in runner.run_async(
            user_id=str(user_id),
            session_id=adk_session_id,
            new_message=prompt,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_token_count", None) or prompt_tokens
                completion_tokens = (
                    getattr(usage, "candidates_token_count", None) or completion_tokens
                )
            if event.content is None:
                continue
            text = "".join(
                part.text or ""
                for part in (event.content.parts or [])
                if not getattr(part, "thought", False)
            )
            if not text:
                continue
            if event.partial or not response_parts:
                visible = strip_hidden_reasoning(text)
                if visible:
                    if first_visible_ms is None:
                        first_visible_ms = (time.monotonic() - total_started) * 1_000
                    response_parts.append(visible)
                    yield visible

        final_text = "".join(response_parts).strip()
        persistence_started = time.monotonic()
        self._repository.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_text,
            provider_model=self._model_name,
        )
        self._repository.commit()
        persistence_ms = (time.monotonic() - persistence_started) * 1_000
        elapsed_ms = (time.monotonic() - total_started) * 1_000
        metrics_registry.observe("chat.request.duration", elapsed_ms)
        metrics_registry.observe("chat.history.duration", history_ms)
        metrics_registry.observe("chat.session.duration", session_ms)
        metrics_registry.observe("chat.persistence.duration", persistence_ms)
        if first_visible_ms is not None:
            metrics_registry.observe("chat.time_to_first_visible_delta", first_visible_ms)
        logger.info(
            "chat_request_completed",
            extra={
                "knemora_fields": {
                    "model": self._model_name,
                    "response_mode": response_mode,
                    "duration_ms": round(elapsed_ms, 3),
                    "history_preparation_ms": round(history_ms, 3),
                    "session_setup_and_replay_ms": round(session_ms, 3),
                    "tool_construction_ms": round(tools_ms, 3),
                    "persistence_ms": round(persistence_ms, 3),
                    "time_to_first_visible_delta_ms": (
                        round(first_visible_ms, 3) if first_visible_ms is not None else None
                    ),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "effective_context_tokens": self._provider.capabilities.max_context_tokens,
                    "history_length": len(prior),
                    "stream": True,
                    "tools_count": len(tools),
                    "deterministic_arithmetic": False,
                }
            },
        )

    async def reply(
        self,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str,
        response_mode: ResponseMode = "wiki",
    ) -> str:
        chunks = [
            chunk
            async for chunk in self.stream_reply(
                conversation_id=conversation_id,
                user_id=user_id,
                content=content,
                response_mode=response_mode,
            )
        ]
        return "".join(chunks)
