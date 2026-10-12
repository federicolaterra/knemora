from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.llm.budget import fit_request_to_context
from app.llm.contracts import ChatMessage, ChatRequest, ChatToolDefinition
from app.llm.errors import LLMContextOverflowError
from knemora_bootstrap.cli import SetupManager
from knemora_bootstrap.configuration import AppPaths, write_model_selection
from knemora_bootstrap.model_context import ModelContextError, plan_context
from knemora_bootstrap.models import DEFAULT_MODEL_ID, MODEL_REGISTRY, ModelSpec
from knemora_bootstrap.platforms import Hardware
from knemora_bootstrap.runtime import RuntimeFailure, RuntimeManager


def _hardware(total: float, available: float | None = None) -> Hardware:
    return Hardware(
        "macOS",
        "arm64",
        total,
        "Apple Metal",
        total,
        total if available is None else available,
    )


def _wiki_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_context_plan_distinguishes_advertised_configured_and_effective() -> None:
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=8192,
        source="curated model profile",
        explicit=False,
    )

    assert plan.advertised_context_tokens == 40_960
    assert plan.configured_context_tokens == 8192
    assert plan.effective_context_tokens == 8192
    assert plan.memory.kv_cache_bytes > 0
    assert plan.memory.total_bytes < plan.memory.safe_budget_bytes  # type: ignore[operator]


def test_invalid_or_unsafe_explicit_context_fails_actionably() -> None:
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    with pytest.raises(ModelContextError, match="advertised maximum"):
        plan_context(
            model,
            _hardware(16),
            configured_context_tokens=65_536,
            source="test override",
            explicit=True,
        )
    with pytest.raises(ModelContextError, match="cannot start safely"):
        plan_context(
            model,
            _hardware(6, available=3),
            configured_context_tokens=8192,
            source="test override",
            explicit=True,
        )


def test_automatic_profile_can_reduce_context_but_never_below_usable_minimum() -> None:
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    plan = plan_context(
        model,
        _hardware(7.7),
        configured_context_tokens=8192,
        source="curated model profile",
        explicit=False,
    )
    assert plan.effective_context_tokens == 4096
    assert "reduced from 8,192" in plan.reason


def test_history_is_removed_before_request_and_current_turn_overflow_is_explained() -> None:
    tools = (
        ChatToolDefinition(
            name="search_wiki",
            description="Search bounded local evidence.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
    )
    request = ChatRequest(
        messages=(
            ChatMessage(role="system", content="system"),
            ChatMessage(
                role="user",
                content=(
                    "The following is prior conversation data.\n"
                    + ("old transcript " * 1000)
                    + "\n[CURRENT USER] current question"
                ),
            ),
        ),
        tools=tools,
        max_tokens=512,
    )
    fitted = fit_request_to_context(request, 4096)
    assert "old transcript" not in fitted.messages[1].content
    assert "current question" in fitted.messages[1].content

    oversized = request.model_copy(
        update={
            "messages": (
                ChatMessage(role="system", content="system"),
                ChatMessage(role="user", content="x" * 20_000),
            )
        }
    )
    with pytest.raises(LLMContextOverflowError, match="effective 4,096-token context"):
        fit_request_to_context(oversized, 4096)


def test_same_model_context_change_keeps_prior_selection_for_runtime_rollback(
    tmp_path: Path,
) -> None:
    paths = AppPaths(repository=tmp_path / "repository", data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    model_path = paths.models / model.filename
    previous_plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=4096,
        source="test profile",
        explicit=True,
    )
    updated_plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=8192,
        source="test override",
        explicit=True,
    )
    write_model_selection(paths, model, model_path, plan=previous_plan)
    write_model_selection(paths, model, model_path, plan=updated_plan)

    selection = json.loads((paths.config / "model.json").read_text())
    assert selection["context_tokens"] == 8192
    assert selection["previous_selection"]["model_id"] == DEFAULT_MODEL_ID
    assert selection["previous_selection"]["context_tokens"] == 4096


def test_rejected_preflight_and_runtime_rollback_leave_wiki_immutable(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    paths.wiki.mkdir(parents=True)
    (paths.wiki / "unrelated.md").write_text("preserve me\n", encoding="utf-8")
    previous = {
        "model_id": DEFAULT_MODEL_ID,
        "display_name": "Qwen",
        "provider": "llama_cpp",
        "path": str(paths.models / "qwen.gguf"),
        "quantization": "Q3_K_M",
        "context_tokens": 8192,
        "context_source": "curated model profile",
        "sha256": "qwen",
    }
    (paths.config / "model.json").write_text(
        json.dumps(
            {
                "model_id": "qwen3.8-27b-iq2-s",
                "display_name": "Qwen 27B",
                "provider": "llama_cpp",
                "path": str(paths.models / "qwen-27b.gguf"),
                "quantization": "IQ2_S",
                "context_tokens": 8192,
                "context_source": "test switch",
                "sha256": "qwen-27b",
                "previous_selection": previous,
            }
        ),
        encoding="utf-8",
    )
    before = _wiki_hashes(paths.wiki)

    class LowMemoryPlatform:
        @staticmethod
        def check_prerequisites() -> list[str]:
            return []

        @staticmethod
        def hardware() -> Hardware:
            return _hardware(6, available=3)

        @staticmethod
        def open_url(_url: str) -> None:
            return None

    with pytest.raises(ModelContextError, match="cannot start safely"):
        SetupManager(paths, LowMemoryPlatform()).run(  # type: ignore[arg-type]
            model_id=DEFAULT_MODEL_ID
        )
    assert _wiki_hashes(paths.wiki) == before
    assert json.loads((paths.config / "model.json").read_text())["model_id"] == (
        "qwen3.8-27b-iq2-s"
    )

    runtime = RuntimeManager(paths, LowMemoryPlatform())  # type: ignore[arg-type]
    with pytest.raises(RuntimeFailure, match="prior model selection was restored"):
        runtime.start(open_apps=False)
    restored = json.loads((paths.config / "model.json").read_text())
    assert restored["model_id"] == DEFAULT_MODEL_ID
    assert restored["context_tokens"] == 8192
    assert _wiki_hashes(paths.wiki) == before


def test_runtime_launch_failure_rolls_back_to_qwen_without_wiki_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    script = repository / "infrastructure" / "scripts" / "start-local-release.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    stop = repository / "infrastructure" / "scripts" / "stop-local-release.sh"
    stop.write_text("#!/bin/sh\n", encoding="utf-8")
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    paths.wiki.mkdir(parents=True)
    (paths.wiki / "unrelated.md").write_text("preserve me\n", encoding="utf-8")
    previous = {
        "model_id": DEFAULT_MODEL_ID,
        "path": str(paths.models / "qwen.gguf"),
        "quantization": "Q3_K_M",
        "context_tokens": 8192,
        "context_source": "curated model profile",
    }
    (paths.config / "model.json").write_text(
        json.dumps(
            {
                "model_id": "qwen3.8-27b-iq2-s",
                "path": str(paths.models / "candidate.gguf"),
                "quantization": "IQ2_S",
                "context_tokens": 8192,
                "context_source": "test switch",
                "previous_selection": previous,
            }
        ),
        encoding="utf-8",
    )
    before = _wiki_hashes(paths.wiki)

    class HighMemoryPlatform:
        @staticmethod
        def hardware() -> Hardware:
            return _hardware(64)

        @staticmethod
        def open_url(_url: str) -> None:
            return None

    runtime = RuntimeManager(paths, HighMemoryPlatform())  # type: ignore[arg-type]
    runtime._native_runtime = type(
        "Native",
        (),
        {
            "resolve_llama": staticmethod(
                lambda: type("Selection", (), {"executable": tmp_path / "llama-server"})()
            )
        },
    )()

    def fail_start(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0 if "stop-local-release.sh" in command[0] else 1
        )

    monkeypatch.setattr(subprocess, "run", fail_start)
    with pytest.raises(RuntimeFailure, match="prior model selection was restored"):
        runtime.start(open_apps=False)

    restored = json.loads((paths.config / "model.json").read_text())
    assert restored["model_id"] == DEFAULT_MODEL_ID
    assert _wiki_hashes(paths.wiki) == before


def test_missing_metadata_never_allows_context_above_validated_profile() -> None:
    model = ModelSpec(
        id="unknown",
        display_name="Unknown custom model",
        provider="llama_cpp",
        repository="owner/model",
        filename="model.gguf",
        quantization="Q4",
        sha256="0" * 64,
        size_bytes=2_000_000_000,
        required_free_bytes=3_000_000_000,
        recommended_memory_gb=4,
        context_tokens=4096,
        license_url="https://example.test",
        origin="user",
    )
    with pytest.raises(ModelContextError, match="validated model profile"):
        plan_context(
            model,
            _hardware(16),
            configured_context_tokens=8192,
            source="override",
            explicit=True,
        )
