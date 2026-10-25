import asyncio
import json

import httpx
import pytest

from app.llm import (
    ChatMessage,
    ChatRequest,
    ChatToolDefinition,
    LocalLlamaCppProvider,
)
from app.llm.errors import LLMTimeoutError, LLMTransportError


def test_local_provider_health_and_chat_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        payload = json.loads(request.content)
        assert payload["model"] == "configured-model"
        assert payload["messages"] == [{"role": "user", "content": "Hello"}]
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert request.extensions["timeout"]["read"] == 300.0
        assert request.extensions["timeout"]["connect"] == 120.0
        assert request.extensions["timeout"]["write"] == 120.0
        assert request.extensions["timeout"]["pool"] == 120.0
        return httpx.Response(
            200,
            json={
                "model": "configured-model",
                "choices": [
                    {"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "timings": {"prompt_ms": 12.5, "predicted_ms": 34.25},
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = LocalLlamaCppProvider(
                base_url="http://llama.test", model="configured-model", client=client
            )
            health = await provider.health()
            response = await provider.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="Hello"),), timeout_seconds=300
                )
            )
        assert health.healthy is True
        assert response.message.content == "Hi"
        assert response.usage.total_tokens == 2
        assert response.performance.prefill_ms == 12.5
        assert response.performance.decode_ms == 34.25

    import asyncio

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (httpx.ReadTimeout("generation exceeded deadline"), LLMTimeoutError),
        (httpx.ConnectError("runtime connection failed"), LLMTransportError),
    ],
)
async def test_local_provider_types_timeout_and_transport_failures(
    provider_error: httpx.HTTPError, expected_error: type[Exception]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        provider_error.request = request
        raise provider_error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LocalLlamaCppProvider(
            base_url="http://llama.test", model="configured-model", client=client
        )
        with pytest.raises(expected_error) as raised:
            await provider.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="Hello"),), timeout_seconds=300
                )
            )
        if expected_error is LLMTimeoutError:
            assert str(raised.value) == "llama.cpp read exceeded its 300-second deadline"


async def test_local_provider_preserves_caller_cancellation() -> None:
    started = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("The cancelled request unexpectedly resumed.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LocalLlamaCppProvider(
            base_url="http://llama.test", model="configured-model", client=client
        )
        task = asyncio.create_task(
            provider.chat(ChatRequest(messages=(ChatMessage(role="user", content="Hello"),)))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_local_provider_stream_contract() -> None:
    body = (
        'data: {"model":"configured-model","choices":[{"delta":{"content":"Hello"},'
        '"finish_reason":null}]}\n\n'
        'data: {"model":"configured-model","choices":[{"delta":{"content":""},'
        '"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,'
        '"total_tokens":3},"timings":{"prompt_ms":4.5,"predicted_ms":8.5}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LocalLlamaCppProvider(
            base_url="http://llama.test", model="configured-model", client=client
        )
        chunks = [
            chunk
            async for chunk in provider.stream(
                ChatRequest(messages=(ChatMessage(role="user", content="Hello"),))
            )
        ]

    assert "".join(chunk.delta for chunk in chunks) == "Hello"
    assert any(chunk.done for chunk in chunks)
    completed = next(chunk for chunk in chunks if chunk.finish_reason == "stop")
    assert completed.usage is not None
    assert completed.usage.total_tokens == 3
    assert completed.performance is not None
    assert completed.performance.prefill_ms == 4.5
    assert completed.performance.decode_ms == 8.5


def test_local_provider_sends_tools_and_parses_function_calls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tool_choice"] == "auto"
        assert payload["tools"][0]["function"]["name"] == "search_wiki"
        return httpx.Response(
            200,
            json={
                "model": "configured-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_wiki",
                                        "arguments": '{"query":"ACME"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = LocalLlamaCppProvider(
                base_url="http://llama.test", model="configured-model", client=client
            )
            response = await provider.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="Find ACME"),),
                    tools=(
                        ChatToolDefinition(
                            name="search_wiki",
                            description="Search the Wiki.",
                            parameters={
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                            },
                        ),
                    ),
                )
            )
        assert response.message.content == ""
        assert response.message.tool_calls[0].name == "search_wiki"
        assert response.message.tool_calls[0].arguments == {"query": "ACME"}

    import asyncio

    asyncio.run(exercise())


def test_local_provider_forwards_required_named_tool_choice() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tool_choice"] == {
            "type": "function",
            "function": {"name": "read_wiki_page"},
        }
        return httpx.Response(
            200,
            json={
                "model": "configured-model",
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = LocalLlamaCppProvider(
                base_url="http://llama.test", model="configured-model", client=client
            )
            await provider.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="Read ACME"),),
                    tools=(
                        ChatToolDefinition(
                            name="read_wiki_page",
                            description="Read a Wiki page.",
                            parameters={"type": "object", "properties": {}},
                        ),
                    ),
                    tool_choice={
                        "type": "function",
                        "function": {"name": "read_wiki_page"},
                    },
                )
            )

    import asyncio

    asyncio.run(exercise())
