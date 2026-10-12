"""Model-aware context selection and conservative unified-memory preflight."""

from __future__ import annotations

import math
from dataclasses import dataclass

from knemora_bootstrap.models import ModelSpec
from knemora_bootstrap.platforms import Hardware

GIB = 1024**3
MIN_AGENT_CONTEXT_TOKENS = 4096
KV_Q8_BYTES_PER_VALUE = 1.0625


class ModelContextError(RuntimeError):
    """A requested context is invalid or cannot fit the current safe memory budget."""


@dataclass(frozen=True)
class MemoryEstimate:
    weights_bytes: int
    kv_cache_bytes: int
    runtime_overhead_bytes: int
    working_memory_bytes: int
    total_bytes: int
    safety_reserve_bytes: int
    safe_budget_bytes: int | None
    uncertainty: str


@dataclass(frozen=True)
class ContextPlan:
    advertised_context_tokens: int | None
    configured_context_tokens: int
    effective_context_tokens: int
    source: str
    reason: str
    memory: MemoryEstimate


def _kv_bytes(model: ModelSpec, context_tokens: int) -> tuple[int, str]:
    if (
        model.block_count
        and model.attention_head_count_kv
        and (model.attention_key_length or model.embedding_length)
    ):
        key_length = model.attention_key_length
        if key_length is None and model.embedding_length and model.attention_head_count:
            key_length = math.ceil(model.embedding_length / model.attention_head_count)
        value_length = model.attention_value_length or key_length
        if key_length and value_length:
            values = (
                context_tokens
                * model.block_count
                * model.attention_head_count_kv
                * (key_length + value_length)
            )
            return math.ceil(values * KV_Q8_BYTES_PER_VALUE), "architecture metadata"

    # This fallback deliberately overweights large artifacts. It is a guardrail when the
    # architecture does not publish enough dimensions for an exact KV estimate.
    bytes_per_token = max(64 * 1024, min(256 * 1024, model.size_bytes // 50_000))
    return context_tokens * bytes_per_token, "conservative fallback"


def estimate_memory(model: ModelSpec, context_tokens: int, hardware: Hardware) -> MemoryEstimate:
    """Estimate resident weights, Q8 KV cache, runtime workspace, and an OS safety reserve."""

    weights = math.ceil(model.size_bytes * 1.05)
    kv_cache, kv_basis = _kv_bytes(model, context_tokens)
    runtime_overhead = max(768 * 1024**2, math.ceil(model.size_bytes * 0.15))
    working_memory = 512 * 1024**2
    total = weights + kv_cache + runtime_overhead + working_memory

    physical_gb = hardware.unified_memory_gb or hardware.memory_gb
    physical = math.floor(physical_gb * GIB) if physical_gb else None
    reserve = max(2 * GIB, math.ceil(physical * 0.15)) if physical else 2 * GIB
    safe_budget = physical - reserve if physical else None
    if hardware.available_memory_gb is not None:
        available_budget = max(0, math.floor(hardware.available_memory_gb * GIB) - 512 * 1024**2)
        safe_budget = (
            min(safe_budget, available_budget) if safe_budget is not None else available_budget
        )

    complete = all(
        value is not None
        for value in (
            model.block_count,
            model.attention_head_count_kv,
            model.embedding_length,
        )
    )
    uncertainty = (
        f"medium ({kv_basis}; runtime allocation can still vary)"
        if complete
        else f"high ({kv_basis}; incomplete GGUF architecture metadata)"
    )
    return MemoryEstimate(
        weights_bytes=weights,
        kv_cache_bytes=kv_cache,
        runtime_overhead_bytes=runtime_overhead,
        working_memory_bytes=working_memory,
        total_bytes=total,
        safety_reserve_bytes=reserve,
        safe_budget_bytes=safe_budget,
        uncertainty=uncertainty,
    )


def _validate_capability(model: ModelSpec, context_tokens: int) -> None:
    if context_tokens < MIN_AGENT_CONTEXT_TOKENS:
        raise ModelContextError(
            f"Context {context_tokens:,} is below Knemora's usable agent minimum of "
            f"{MIN_AGENT_CONTEXT_TOKENS:,} tokens."
        )
    advertised = model.advertised_context_tokens
    trustworthy_maximum = advertised or model.context_tokens
    if context_tokens > trustworthy_maximum:
        basis = "GGUF advertised maximum" if advertised else "validated model profile"
        raise ModelContextError(
            f"Context {context_tokens:,} exceeds the {basis} of {trustworthy_maximum:,} tokens "
            f"for {model.id}."
        )


def plan_context(
    model: ModelSpec,
    hardware: Hardware,
    *,
    configured_context_tokens: int,
    source: str,
    explicit: bool,
) -> ContextPlan:
    """Validate an explicit context or auto-reduce a profile within safe, usable bounds."""

    _validate_capability(model, configured_context_tokens)
    candidates = [configured_context_tokens]
    if not explicit:
        candidate = configured_context_tokens
        while candidate // 2 >= MIN_AGENT_CONTEXT_TOKENS:
            candidate //= 2
            candidates.append(candidate)

    last = estimate_memory(model, candidates[-1], hardware)
    for candidate in candidates:
        estimate = estimate_memory(model, candidate, hardware)
        last = estimate
        if estimate.safe_budget_bytes is None or estimate.total_bytes <= estimate.safe_budget_bytes:
            if candidate == configured_context_tokens:
                reason = f"selected from {source}; estimated memory fits the safe host budget"
            else:
                reason = (
                    f"reduced from {configured_context_tokens:,} to {candidate:,} tokens because "
                    "the larger profile exceeded the safe host memory budget"
                )
            return ContextPlan(
                advertised_context_tokens=model.advertised_context_tokens,
                configured_context_tokens=configured_context_tokens,
                effective_context_tokens=candidate,
                source=source,
                reason=reason,
                memory=estimate,
            )

    budget = last.safe_budget_bytes
    required = last.total_bytes
    detail = (
        f"estimated {required / GIB:.2f} GiB required versus {budget / GIB:.2f} GiB safe budget"
        if budget is not None
        else f"estimated {required / GIB:.2f} GiB required"
    )
    qualifier = "Explicit context cannot be reduced automatically. " if explicit else ""
    raise ModelContextError(
        f"{model.display_name} cannot start safely at a usable context: {detail}. "
        f"{qualifier}Stop other memory-intensive applications, select a smaller model, or choose a "
        f"validated context of at least {MIN_AGENT_CONTEXT_TOKENS:,} tokens."
    )


__all__ = [
    "ContextPlan",
    "MemoryEstimate",
    "MIN_AGENT_CONTEXT_TOKENS",
    "ModelContextError",
    "estimate_memory",
    "plan_context",
]
