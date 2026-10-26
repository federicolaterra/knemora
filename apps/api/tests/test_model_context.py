from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

import pytest

from app.llm.budget import fit_request_to_context
from app.llm.contracts import ChatMessage, ChatRequest, ChatToolDefinition
from app.llm.errors import LLMContextOverflowError
from knemora_bootstrap.cli import SetupManager, _print_model_info
from knemora_bootstrap.configuration import (
    AppPaths,
    resolve_context_preference,
    runtime_environment,
    write_model_selection,
)
from knemora_bootstrap.model_context import (
    ModelContextError,
    describe_context_admission,
    plan_context,
)
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
    assert "Automatic full-context admission" in describe_context_admission(plan)


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
    assert "Automatic reduced-context admission" in describe_context_admission(plan)
    assert "may truncate sooner" in describe_context_admission(plan)


def test_automatic_profile_rejects_without_mutation_when_minimum_is_unsafe(
    tmp_path: Path,
) -> None:
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    selection = tmp_path / "model.json"
    selection.write_text('{"preserve": true}\n', encoding="utf-8")

    with pytest.raises(ModelContextError) as raised:
        plan_context(
            model,
            _hardware(16, available=5.5),
            configured_context_tokens=8192,
            source="curated model profile",
            explicit=False,
        )

    assert "automatic profile was also unsafe" in str(raised.value)
    assert "Explicit context" not in str(raised.value)
    assert selection.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_explicit_context_admission_and_rejection_never_fall_back() -> None:
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    admitted = plan_context(
        model,
        _hardware(16, available=6.5),
        configured_context_tokens=4096,
        source="persisted per-model user override",
        explicit=True,
    )
    assert admitted.effective_context_tokens == 4096
    assert "Explicit-context admission" in describe_context_admission(admitted)

    with pytest.raises(ModelContextError, match="will not be lowered automatically"):
        plan_context(
            model,
            _hardware(16, available=6.2),
            configured_context_tokens=8192,
            source="explicit setup --context-tokens override",
            explicit=True,
        )
    with pytest.raises(ModelContextError, match="already at Knemora's 4,096-token minimum"):
        plan_context(
            model,
            _hardware(16, available=5.5),
            configured_context_tokens=4096,
            source="KNEMORA_LLM_CONTEXT_TOKENS environment override",
            explicit=True,
        )


def test_context_precedence_and_managed_child_effective_value_is_not_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    automatic_plan = plan_context(
        model,
        _hardware(7.7),
        configured_context_tokens=8192,
        source="curated model profile",
        explicit=False,
    )
    write_model_selection(paths, model, paths.models / model.filename, plan=automatic_plan)

    monkeypatch.setenv("KNEMORA_LLM_CONTEXT_TOKENS", "6144")
    preference = resolve_context_preference(paths, model, cli_context_tokens=7168)
    assert (preference.tokens, preference.source, preference.explicit) == (
        7168,
        "explicit setup --context-tokens override",
        True,
    )

    selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    selection["context_overrides"] = {model.id: 4096}
    (paths.config / "model.json").write_text(json.dumps(selection), encoding="utf-8")
    preference = resolve_context_preference(paths, model)
    assert (preference.tokens, preference.source, preference.explicit) == (
        4096,
        "persisted per-model user override",
        True,
    )

    selection["context_overrides"] = {}
    (paths.config / "model.json").write_text(json.dumps(selection), encoding="utf-8")
    (repository / ".env").write_text("KNEMORA_LLM_CONTEXT_TOKENS=5120\n", encoding="utf-8")
    preference = resolve_context_preference(paths, model)
    assert (preference.tokens, preference.source, preference.explicit) == (
        5120,
        "KNEMORA_LLM_CONTEXT_TOKENS environment override",
        True,
    )
    environment_plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=preference.tokens,
        source=preference.source,
        explicit=preference.explicit,
    )
    write_model_selection(paths, model, paths.models / model.filename, plan=environment_plan)
    selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    assert selection["context_overrides"] == {}

    (repository / ".env").unlink()
    managed_child = runtime_environment(paths)
    assert managed_child["KNEMORA_LLM_DISPLAY_NAME"] == model.display_name
    assert managed_child["KNEMORA_LLM_REVISION"] == model.revision
    assert managed_child["KNEMORA_LLM_THINKING_CONTROL"] == model.thinking_control
    monkeypatch.setattr("knemora_bootstrap.configuration.os.environ", managed_child)
    preference = resolve_context_preference(paths, model)
    assert (preference.tokens, preference.source, preference.explicit) == (
        8192,
        "curated model profile",
        False,
    )


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
            ChatMessage(role="user", content="old question " * 700),
            ChatMessage(role="assistant", content="old answer " * 700),
            ChatMessage(role="user", content="recent subject"),
            ChatMessage(role="assistant", content="recent answer"),
            ChatMessage(role="user", content="current question"),
        ),
        tools=tools,
        max_tokens=512,
    )
    fitted = fit_request_to_context(request, 4096)
    assert all("old question" not in message.content for message in fitted.messages)
    assert all("old answer" not in message.content for message in fitted.messages)
    assert [message.role for message in fitted.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert fitted.messages[-1].content == "current question"

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


def test_context_budgets_preserve_current_and_most_recent_turns() -> None:
    messages: list[ChatMessage] = [ChatMessage(role="system", content="policy" * 100)]
    for index in range(4):
        messages.extend(
            (
                ChatMessage(role="user", content=f"question-{index} " * 120),
                ChatMessage(role="assistant", content=f"answer-{index} " * 120),
            )
        )
    messages.append(ChatMessage(role="user", content="current follow-up"))
    request = ChatRequest(messages=tuple(messages), max_tokens=1024)

    at_8192 = fit_request_to_context(request, 8192)
    at_4096 = fit_request_to_context(request, 4096)

    assert at_8192.messages == request.messages
    assert at_4096.messages[-1].content == "current follow-up"
    assert [message.content for message in at_4096.messages].count("current follow-up") == 1
    assert any("question-3" in message.content for message in at_4096.messages)
    assert not any("question-0" in message.content for message in at_4096.messages)
    assert at_4096.messages[0].role == "system"


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


def test_runtime_reevaluates_automatic_profile_and_records_reduced_effective_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "repository"
    start_script = repository / "infrastructure" / "scripts" / "start-local-release.sh"
    start_script.parent.mkdir(parents=True)
    start_script.write_text("#!/bin/sh\n", encoding="utf-8")
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    full_plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=8192,
        source="curated model profile",
        explicit=False,
    )
    write_model_selection(paths, model, paths.models / model.filename, plan=full_plan)

    class ChangedMemoryPlatform:
        @staticmethod
        def hardware() -> Hardware:
            return _hardware(7.7)

        @staticmethod
        def open_url(_url: str) -> None:
            return None

    runtime = RuntimeManager(paths, ChangedMemoryPlatform())  # type: ignore[arg-type]
    runtime._native_runtime = type(
        "Native",
        (),
        {
            "resolve_llama": staticmethod(
                lambda: type("Selection", (), {"executable": tmp_path / "llama-server"})()
            )
        },
    )()
    launched_environment: dict[str, str] = {}

    def successful_start(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "start-local-release.sh" in command[0]:
            launched_environment.update(cast(dict[str, str], kwargs["env"]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", successful_start)
    monkeypatch.setattr(runtime, "wait_until_ready", lambda: [])
    monkeypatch.setattr(
        runtime,
        "status",
        lambda: (
            type("Status", (), {"name": "database", "running": True})(),
            type("Status", (), {"name": "llm", "running": True})(),
            type("Status", (), {"name": "api", "running": True})(),
            type("Status", (), {"name": "web", "running": True})(),
        ),
    )
    monkeypatch.setattr(runtime, "_api_mode_matches", lambda *, demo: True)

    runtime.start(open_apps=False)

    selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    assert selection["configured_context_tokens"] == 8192
    assert selection["context_tokens"] == 4096
    assert selection["context_mode"] == "automatic"
    assert "previous_selection" not in selection
    assert launched_environment["KNEMORA_LLM_CONTEXT_TOKENS"] == "4096"
    assert launched_environment["KNEMORA_LLM_CONTEXT_ORIGIN"] == "managed-effective"
    output = capsys.readouterr().out
    assert "Automatic reduced-context admission" in output
    assert "may truncate sooner" in output


def test_runtime_explicit_rejection_is_clear_and_preserves_selection(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    paths.wiki.mkdir(parents=True)
    (paths.wiki / "preserve.md").write_text("preserve\n", encoding="utf-8")
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=8192,
        source="persisted per-model user override",
        explicit=True,
    )
    write_model_selection(
        paths,
        model,
        paths.models / model.filename,
        plan=plan,
        explicit_context_tokens=8192,
    )
    before_selection = (paths.config / "model.json").read_bytes()
    before_wiki = _wiki_hashes(paths.wiki)

    class LowMemoryPlatform:
        @staticmethod
        def hardware() -> Hardware:
            return _hardware(16, available=6.2)

    runtime = RuntimeManager(paths, LowMemoryPlatform())  # type: ignore[arg-type]
    with pytest.raises(RuntimeFailure) as raised:
        runtime.start(open_apps=False)

    message = str(raised.value)
    assert "explicit request will not be lowered automatically" in message
    assert ".." not in message
    assert (paths.config / "model.json").read_bytes() == before_selection
    assert _wiki_hashes(paths.wiki) == before_wiki


def test_model_info_labels_preflight_as_time_dependent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "home")
    paths.config.mkdir(parents=True)
    model = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    plan = plan_context(
        model,
        _hardware(16),
        configured_context_tokens=8192,
        source="curated model profile",
        explicit=False,
    )
    write_model_selection(paths, model, paths.models / model.filename, plan=plan)

    _print_model_info(paths, model.id)

    output = capsys.readouterr().out
    assert "Profile context: 8,192 tokens" in output
    assert "Configured preference: 8,192 tokens" in output
    assert "Configuration mode: automatic" in output
    assert "Effective context (last preflight): 8,192 tokens" in output
    assert "time-dependent and not a launch guarantee" in output


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
