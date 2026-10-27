"""Provider-independent language model contracts and adapters."""

from app.llm.contracts import (
    ChatChunk,
    ChatMessage,
    ChatPerformance,
    ChatRequest,
    ChatResponse,
    ChatRole,
    ChatToolCall,
    ChatToolDefinition,
    ChatUsage,
    LLMCapabilities,
    LLMHealth,
    LLMProvider,
)
from app.llm.errors import (
    LLMContextOverflowError,
    LLMResponseTruncatedError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.local_llama_cpp import LocalLlamaCppProvider

__all__ = [
    "ChatChunk",
    "ChatMessage",
    "ChatPerformance",
    "ChatRequest",
    "ChatResponse",
    "ChatRole",
    "ChatToolCall",
    "ChatToolDefinition",
    "ChatUsage",
    "LLMCapabilities",
    "LLMHealth",
    "LLMProvider",
    "LocalLlamaCppProvider",
    "LLMContextOverflowError",
    "LLMResponseTruncatedError",
    "LLMTimeoutError",
    "LLMTransportError",
]
