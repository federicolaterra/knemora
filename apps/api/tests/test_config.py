import logging

from pytest import LogCaptureFixture, MonkeyPatch

from app.config import REPOSITORY_ROOT, Settings


def test_storage_paths_resolve_from_repository_root() -> None:
    settings = Settings(_env_file=None)

    assert settings.source_store_path == REPOSITORY_ROOT / "data/sources"
    assert settings.knowledge_path == REPOSITORY_ROOT / "knowledge"
    assert settings.llm_max_output_tokens == 1024
    assert settings.knowledge_compilation_max_output_tokens == 2048


def test_knemora_environment_takes_precedence_over_legacy_name(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PHARMATRACE_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("KNEMORA_LLM_MODEL", "canonical-model")

    assert Settings(_env_file=None).llm_model == "canonical-model"


def test_small_graph_threshold_is_runtime_configurable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("KNEMORA_WIKI_GRAPH_SMALL_GRAPH_THRESHOLD", "24")

    assert Settings(_env_file=None).wiki_graph_small_graph_threshold == 24


def test_legacy_environment_remains_supported_with_warning(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.setenv("PHARMATRACE_LLM_MODEL", "legacy-model")
    monkeypatch.delenv("KNEMORA_LLM_MODEL", raising=False)

    with caplog.at_level(logging.WARNING):
        settings = Settings(_env_file=None)

    assert settings.llm_model == "legacy-model"
    assert "KNEMORA_LLM_MODEL" in caplog.text
