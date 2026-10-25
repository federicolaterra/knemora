"""Persisted chat orchestration through the root ADK agent."""

from __future__ import annotations

import re
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
from app.repositories.chat import ChatRepository
from knowledge_agent.agent import APP_NAME, create_adk_app, strip_hidden_reasoning
from knowledge_agent.tools import create_agent_tools

ResponseMode = Literal["wiki", "direct"]
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
        self._tools = create_agent_tools(settings=settings, session_factory=session_factory)
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
        conversation = self._repository.get_conversation(conversation_id, user_id=user_id)
        history = self._repository.list_messages(conversation_id)
        prior = [(message.role, message.content) for message in history]
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
            yield arithmetic_answer
            return

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
        runner = Runner(
            app=create_adk_app(
                self._provider,
                model_name=self._model_name,
                max_output_tokens=self._max_output_tokens,
                tools=self._tools if response_mode == "wiki" else (),
                response_mode=response_mode,
            ),
            session_service=session_service,
        )
        prompt = types.Content(
            role="user",
            parts=[types.Part.from_text(text=content)],
        )
        response_parts: list[str] = []
        async for event in runner.run_async(
            user_id=str(user_id),
            session_id=adk_session_id,
            new_message=prompt,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
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
                    response_parts.append(visible)
                    yield visible

        final_text = "".join(response_parts).strip()
        self._repository.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_text,
            provider_model=self._model_name,
        )
        self._repository.commit()

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
