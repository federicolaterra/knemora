"""Typed inference boundary owned by the application core."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["system", "user", "assistant", "tool"]


class ChatToolDefinition(BaseModel):
    """Provider-neutral function declaration exposed to a model."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class ChatToolCall(BaseModel):
    """One provider-neutral model request to invoke an application tool."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class ChatMessage(BaseModel):
    """One provider-neutral chat message."""

    model_config = ConfigDict(frozen=True)

    role: ChatRole
    content: str = ""
    tool_calls: tuple[ChatToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    """Provider-neutral request including optional structured-output intent."""

    model_config = ConfigDict(frozen=True)

    messages: tuple[ChatMessage, ...]
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1)
    response_schema: dict[str, Any] | None = None
    tools: tuple[ChatToolDefinition, ...] = ()
    tool_choice: str | dict[str, Any] | None = None


class ChatUsage(BaseModel):
    """Normalized token usage when supplied by the runtime."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    """Complete visible model response."""

    model_config = ConfigDict(frozen=True)

    message: ChatMessage
    model: str
    finish_reason: str | None = None
    usage: ChatUsage = Field(default_factory=ChatUsage)


class ChatChunk(BaseModel):
    """One streamed visible-text delta."""

    model_config = ConfigDict(frozen=True)

    delta: str = ""
    done: bool = False
    model: str
    finish_reason: str | None = None
    usage: ChatUsage | None = None


class LLMCapabilities(BaseModel):
    """Runtime capabilities surfaced without leaking provider SDK types."""

    model_config = ConfigDict(frozen=True)

    streaming: bool
    structured_output: bool
    cancellation: bool
    max_context_tokens: int | None = None


class LLMHealth(BaseModel):
    """Health result for readiness and diagnostics."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    provider: str
    model: str
    detail: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Replaceable, async language-model provider boundary."""

    @property
    def capabilities(self) -> LLMCapabilities: ...

    async def health(self) -> LLMHealth: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]: ...
