"""Deterministic test doubles; no real model is required."""

from collections.abc import AsyncIterator

from app.llm import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
)


class FakeLLMProvider:
    """Fake provider with a stable visible answer and hidden-reasoning fixture."""

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=True,
            structured_output=True,
            cancellation=True,
            max_context_tokens=8192,
        )

    async def health(self) -> LLMHealth:
        return LLMHealth(healthy=True, provider="fake", model="fake-local")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        assert request.messages
        return ChatResponse(
            message=ChatMessage(
                role="assistant", content="<think>private scratchpad</think>Hello from fake."
            ),
            model="fake-local",
            finish_reason="stop",
            usage=ChatUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        assert request.messages
        for delta in ("<think>private ", "scratchpad</think>Hello ", "from fake."):
            yield ChatChunk(delta=delta, model="fake-local")
        yield ChatChunk(delta="", done=True, model="fake-local", finish_reason="stop")
