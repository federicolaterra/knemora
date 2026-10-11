"""llama.cpp adapter for its OpenAI-compatible HTTP surface."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.contracts import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatToolCall,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
)
from app.llm.errors import LLMResponseError, LLMUnavailableError
from app.observability import metrics_registry


class LocalLlamaCppProvider:
    """Typed adapter around a local llama.cpp OpenAI-compatible server."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        context_tokens: int = 8192,
        enable_thinking: bool = False,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._context_tokens = context_tokens
        self._enable_thinking = enable_thinking
        self._api_key = api_key
        self._client = client

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            streaming=True,
            structured_output=True,
            cancellation=True,
            max_context_tokens=self._context_tokens,
        )

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    def _payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._message_payload(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
            "chat_template_kwargs": {"enable_thinking": self._enable_thinking},
        }
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "knemora_response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _message_payload(message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            payload["tool_call_id"] = message.tool_call_id
        if message.name is not None:
            payload["name"] = message.name
        return payload

    def _usage(self, data: dict[str, Any] | None) -> ChatUsage:
        usage = data or {}
        return ChatUsage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

    def _client_or_new(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def health(self) -> LLMHealth:
        client = self._client_or_new()
        close_client = self._client is None
        try:
            response = await client.get(f"{self._base_url}/health", headers=self._headers())
            response.raise_for_status()
            body = response.json()
            status = body.get("status") if isinstance(body, dict) else None
            healthy = status in {"ok", "ready", None}
            return LLMHealth(
                healthy=healthy,
                provider="llama.cpp",
                model=self._model,
                detail=None if healthy else f"reported status={status!r}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            return LLMHealth(
                healthy=False,
                provider="llama.cpp",
                model=self._model,
                detail=str(exc),
            )
        finally:
            if close_client:
                await client.aclose()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.monotonic()
        client = self._client_or_new()
        close_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers=self._headers(),
                json=self._payload(request, stream=False),
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"llama.cpp request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMResponseError("llama.cpp returned invalid JSON") from exc
        finally:
            if close_client:
                await client.aclose()

        try:
            choice = data["choices"][0]
            message = choice["message"]
            raw_content = message.get("content")
            content = raw_content if isinstance(raw_content, str) else ""
            tool_calls = tuple(self._tool_call(item) for item in message.get("tool_calls") or [])
            if not content and not tool_calls:
                raise TypeError("message has neither text nor tool calls")
            result = ChatResponse(
                message=ChatMessage(role="assistant", content=content, tool_calls=tool_calls),
                model=str(data.get("model") or self._model),
                finish_reason=choice.get("finish_reason"),
                usage=self._usage(data.get("usage")),
            )
            elapsed = (time.monotonic() - started) * 1_000
            metrics_registry.observe("llm.request.duration", elapsed)
            metrics_registry.increment("llm.request.completed")
            if result.usage.completion_tokens:
                metrics_registry.observe(
                    "llm.completion.tokens_per_second",
                    result.usage.completion_tokens / max(elapsed / 1_000, 0.001),
                )
            return result
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseError("llama.cpp response did not match the chat contract") from exc

    @staticmethod
    def _tool_call(payload: dict[str, Any]) -> ChatToolCall:
        function = payload["function"]
        arguments = function.get("arguments") or "{}"
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(parsed, dict):
            raise TypeError("tool arguments must be an object")
        return ChatToolCall(
            id=str(payload["id"]),
            name=str(function["name"]),
            arguments=parsed,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        started = time.monotonic()
        first_token_recorded = False
        completion_tokens: int | None = None
        client = self._client_or_new()
        close_client = self._client is None
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                headers=self._headers(),
                json=self._payload(request, stream=True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        yield ChatChunk(delta="", done=True, model=self._model)
                        return
                    try:
                        data = json.loads(payload)
                        choices = data.get("choices") or []
                        choice = choices[0] if choices else {}
                        delta = choice.get("delta", {}).get("content") or ""
                        finish_reason = choice.get("finish_reason")
                        usage = self._usage(data.get("usage")) if data.get("usage") else None
                        if usage and usage.completion_tokens is not None:
                            completion_tokens = usage.completion_tokens
                    except (AttributeError, IndexError, TypeError, ValueError) as exc:
                        raise LLMResponseError("invalid llama.cpp SSE event") from exc
                    if delta and not first_token_recorded:
                        metrics_registry.observe(
                            "llm.stream.time_to_first_token", (time.monotonic() - started) * 1_000
                        )
                        first_token_recorded = True
                    yield ChatChunk(
                        delta=delta,
                        done=finish_reason is not None,
                        model=str(data.get("model") or self._model),
                        finish_reason=finish_reason,
                        usage=usage,
                    )
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"llama.cpp stream failed: {exc}") from exc
        finally:
            elapsed = (time.monotonic() - started) * 1_000
            metrics_registry.observe("llm.stream.duration", elapsed)
            metrics_registry.increment("llm.stream.completed")
            if completion_tokens:
                metrics_registry.observe(
                    "llm.stream.tokens_per_second",
                    completion_tokens / max(elapsed / 1_000, 0.001),
                )
            if close_client:
                await client.aclose()
