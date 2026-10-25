"""Conservative provider-neutral prompt budgeting for local model requests."""

from __future__ import annotations

import json
import math
from typing import Any

from app.llm.contracts import ChatMessage, ChatRequest, ChatToolDefinition
from app.llm.errors import LLMContextOverflowError

TOKEN_CHARACTER_RATIO = 3
REQUEST_RESERVE_TOKENS = 256
MINIMUM_OUTPUT_TOKENS = 256


def _text_tokens(value: str) -> int:
    return math.ceil(len(value) / TOKEN_CHARACTER_RATIO)


def estimate_request_tokens(request: ChatRequest) -> int:
    """Estimate tokenizer-independent request size conservatively."""

    message_tokens = sum(
        12
        + _text_tokens(message.content)
        + _text_tokens(
            json.dumps(
                [call.model_dump(mode="json") for call in message.tool_calls],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for message in request.messages
    )
    tools = _text_tokens(
        json.dumps(
            [tool.model_dump(mode="json") for tool in request.tools],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    schema = _text_tokens(
        json.dumps(request.response_schema or {}, ensure_ascii=False, sort_keys=True)
    )
    return message_tokens + tools + schema + request.max_tokens + REQUEST_RESERVE_TOKENS


def _drop_oldest_history_turn(messages: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]:
    """Drop one oldest pre-current conversational turn without touching privileged/current data."""

    latest_user = max(
        (index for index, message in enumerate(messages) if message.role == "user"),
        default=-1,
    )
    candidates = [
        index
        for index, message in enumerate(messages[:latest_user])
        if message.role in {"user", "assistant"}
    ]
    if not candidates:
        return messages
    first = candidates[0]
    remove = {first}
    if messages[first].role == "user":
        for index in candidates[1:]:
            if messages[index].role == "assistant":
                remove.add(index)
                break
            if messages[index].role == "user":
                break
    return tuple(message for index, message in enumerate(messages) if index not in remove)


def _compact_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _compact_schema(item)
            for key, item in value.items()
            if key not in {"default", "description", "examples", "title"}
        }
    return value


def _compact_tool_definition(tool: ChatToolDefinition) -> ChatToolDefinition:
    summary = tool.description.strip().split("\n", maxsplit=1)[0][:240]
    return tool.model_copy(
        update={"description": summary, "parameters": _compact_schema(tool.parameters)}
    )


def _compact_value(value: Any, *, string_limit: int, list_limit: int) -> Any:
    if isinstance(value, str):
        if len(value) <= string_limit:
            return value
        return value[:string_limit] + "… [truncated to fit model context]"
    if isinstance(value, list):
        return [
            _compact_value(item, string_limit=string_limit, list_limit=list_limit)
            for item in value[:list_limit]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, string_limit=string_limit, list_limit=list_limit)
            for key, item in value.items()
        }
    return value


def _compact_tool_message(message: ChatMessage, maximum_chars: int) -> ChatMessage:
    try:
        payload = json.loads(message.content)
    except (TypeError, ValueError):
        content = message.content[:maximum_chars] + "… [truncated to fit model context]"
        return message.model_copy(update={"content": content})
    for string_limit, list_limit in ((2000, 12), (1000, 8), (500, 4), (250, 2), (120, 1)):
        compact = _compact_value(payload, string_limit=string_limit, list_limit=list_limit)
        content = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        if len(content) <= maximum_chars:
            return message.model_copy(update={"content": content})
    return message.model_copy(
        update={
            "content": json.dumps(
                {
                    "status": "truncated",
                    "error": (
                        "Tool evidence exceeded the selected model context. Narrow the question "
                        "or select a validated larger context."
                    ),
                },
                sort_keys=True,
            )
        }
    )


def fit_request_to_context(request: ChatRequest, context_tokens: int | None) -> ChatRequest:
    """Trim old transcript data and bound tool payloads before a llama.cpp request."""

    if context_tokens is None:
        return request
    fitted = request
    if estimate_request_tokens(fitted) <= context_tokens:
        return fitted

    while True:
        messages = _drop_oldest_history_turn(fitted.messages)
        if messages == fitted.messages:
            break
        fitted = fitted.model_copy(update={"messages": messages})
        if estimate_request_tokens(fitted) <= context_tokens:
            return fitted

    if fitted.tools:
        fitted = fitted.model_copy(
            update={"tools": tuple(_compact_tool_definition(tool) for tool in fitted.tools)}
        )
        if estimate_request_tokens(fitted) <= context_tokens:
            return fitted

    excess_tokens = estimate_request_tokens(fitted) - context_tokens
    reduced_max_tokens = max(MINIMUM_OUTPUT_TOKENS, fitted.max_tokens - excess_tokens)
    if reduced_max_tokens < fitted.max_tokens:
        fitted = fitted.model_copy(update={"max_tokens": reduced_max_tokens})
        if estimate_request_tokens(fitted) <= context_tokens:
            return fitted

    tool_indexes = [
        index for index, message in enumerate(fitted.messages) if message.role == "tool"
    ]
    for index in sorted(
        tool_indexes, key=lambda item: len(fitted.messages[item].content), reverse=True
    ):
        mutable_messages = list(fitted.messages)
        available_chars = max(
            800,
            len(mutable_messages[index].content)
            - (estimate_request_tokens(fitted) - context_tokens) * TOKEN_CHARACTER_RATIO
            - 256,
        )
        mutable_messages[index] = _compact_tool_message(mutable_messages[index], available_chars)
        fitted = fitted.model_copy(update={"messages": tuple(mutable_messages)})
        if estimate_request_tokens(fitted) <= context_tokens:
            return fitted

    estimated = estimate_request_tokens(fitted)
    raise LLMContextOverflowError(
        f"This turn needs about {estimated:,} tokens including output and tool reserves, but the "
        f"selected model has an effective {context_tokens:,}-token context. Older conversation "
        "turns were already removed. Narrow the question, request less evidence, or select a "
        "validated larger context with "
        "'./knemora setup --model MODEL_ID --context-tokens N'."
    )


__all__ = ["estimate_request_tokens", "fit_request_to_context"]
