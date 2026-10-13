from __future__ import annotations

import hashlib
import http.client
import json
import struct
import subprocess
from pathlib import Path

import pytest

from knemora_bootstrap.cli import (
    SetupManager,
    _parser,
    _print_models,
    _remove_model,
    _remove_registry_definition,
    main,
)
from knemora_bootstrap.configuration import AppPaths
from knemora_bootstrap.model_import import (
    ExternalModelReference,
    HuggingFaceArtifact,
    HuggingFaceClient,
    ModelImporter,
    generate_model_id,
    resolve_artifact,
)
from knemora_bootstrap.models import (
    DEFAULT_MODEL_ID,
    MODEL_REGISTRY,
    ModelError,
    ModelManager,
    ModelRegistry,
    ModelSpec,
    enrich_model_from_local_gguf,
)
from knemora_bootstrap.native_runtime import RuntimeSelection
from knemora_bootstrap.platforms import Hardware


def gguf_payload(suffix: bytes = b"") -> bytes:
    return b"GGUF" + struct.pack("<IQQ", 3, 0, 0) + suffix


def gguf_metadata_payload(entries: dict[str, str | int]) -> bytes:
    payload = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 0, len(entries)))
    for key, value in entries.items():
        encoded_key = key.encode()
        payload.extend(struct.pack("<Q", len(encoded_key)))
        payload.extend(encoded_key)
        if isinstance(value, str):
            encoded_value = value.encode()
            payload.extend(struct.pack("<I", 8))
            payload.extend(struct.pack("<Q", len(encoded_value)))
            payload.extend(encoded_value)
        else:
            payload.extend(struct.pack("<I", 4))
            payload.extend(struct.pack("<I", value))
    return bytes(payload)


class FakeHuggingFaceClient(HuggingFaceClient):
    def __init__(self, artifact: HuggingFaceArtifact, payload: bytes) -> None:
        self.artifact = artifact
        self.payload = payload
        self.downloads = 0

    def resolve(self, reference: ExternalModelReference) -> HuggingFaceArtifact:
        assert reference.repository == self.artifact.repository
        return self.artifact

    def download(self, artifact: HuggingFaceArtifact, partial: Path) -> None:
        assert artifact == self.artifact
        self.downloads += 1
        partial.write_bytes(self.payload)


def artifact_for(payload: bytes, *, repository: str = "owner/Example-GGUF") -> HuggingFaceArtifact:
    return HuggingFaceArtifact(
        repository=repository,
        filename="models/example-Q3_K_M.gguf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        license_reference=f"https://huggingface.co/{repository}",
    )


def import_fixture(paths: AppPaths, *, repository: str = "owner/Example-GGUF") -> ModelSpec:
    payload = gguf_payload(b"fixture")
    client = FakeHuggingFaceClient(artifact_for(payload, repository=repository), payload)
    return ModelImporter(paths.models, ModelRegistry(paths.model_registry), client).import_model(
        f"hf:{repository}:Q3_K_M"
    )


def test_external_reference_parser_accepts_only_explicit_hugging_face_grammar() -> None:
    reference = ExternalModelReference.parse("hf:owner/repository:Q3_K_M")
    assert reference.repository == "owner/repository"
    assert reference.variant == "Q3_K_M"

    for invalid in (
        "owner/repository:Q3_K_M",
        "hf:owner:Q3_K_M",
        "github:owner/repository:Q3_K_M",
        "hf:../repository:Q3_K_M",
        "hf:owner/repository:../../model",
    ):
        with pytest.raises(ModelError, match="Expected hf"):
            ExternalModelReference.parse(invalid)


def test_model_id_generation_is_deterministic_and_cli_safe() -> None:
    assert generate_model_id("ISTA-DASLab/Qwen3-8B-GGUF-GSQ", "Q3_K_M") == "qwen3-8b-q3-k-m"
    assert generate_model_id("owner/My.Model-GGUF", "IQ2_S") == "my-model-iq2-s"


def test_import_persists_trustworthy_gguf_context_and_architecture_metadata(
    tmp_path: Path,
) -> None:
    payload = gguf_metadata_payload(
        {
            "general.architecture": "spark2_5",
            "spark2_5.context_length": 32_768,
            "spark2_5.embedding_length": 2560,
            "spark2_5.block_count": 36,
            "spark2_5.attention.head_count": 20,
            "spark2_5.attention.head_count_kv": 4,
        }
    )
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    client = FakeHuggingFaceClient(artifact_for(payload), payload)
    model = ModelImporter(
        paths.models,
        ModelRegistry(paths.model_registry),
        client,
    ).import_model("hf:owner/Example-GGUF:Q3_K_M")

    assert model.metadata_architecture == "spark2_5"
    assert model.advertised_context_tokens == 32_768
    assert model.context_tokens == 8192
    assert model.block_count == 36
    assert model.attention_head_count_kv == 4


def test_legacy_user_model_uses_installed_gguf_metadata_without_reimport(
    tmp_path: Path,
) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    paths.models.mkdir(parents=True)
    payload = gguf_metadata_payload(
        {
            "general.architecture": "spark2_5",
            "spark2_5.context_length": 32_768,
            "spark2_5.embedding_length": 2560,
            "spark2_5.block_count": 36,
            "spark2_5.attention.head_count": 20,
            "spark2_5.attention.head_count_kv": 4,
        }
    )
    artifact = paths.models / "legacy.gguf"
    artifact.write_bytes(payload)
    legacy = ModelSpec(
        id="legacy",
        display_name="Legacy custom model",
        provider="llama_cpp",
        repository="owner/legacy",
        filename=artifact.name,
        quantization="Q4_K_M",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        required_free_bytes=len(payload),
        recommended_memory_gb=4,
        context_tokens=4096,
        license_url="https://example.invalid",
        origin="user",
        local_path=str(artifact),
    )

    enriched = enrich_model_from_local_gguf(legacy, paths.models)

    assert enriched.metadata_architecture == "spark2_5"
    assert enriched.advertised_context_tokens == 32_768
    assert enriched.context_tokens == 8192


def test_artifact_resolution_prefers_exact_then_requires_unique_normalized_match() -> None:
    exact_reference = ExternalModelReference.parse("hf:owner/repository:exact.gguf")
    exact = resolve_artifact(
        exact_reference,
        [
            {"rfilename": "nested/exact.gguf", "size": 25},
            {"rfilename": "other-exact.gguf", "size": 26},
        ],
    )
    assert exact.filename == "nested/exact.gguf"

    reference = ExternalModelReference.parse("hf:owner/repository:Q3_K_M")
    siblings: list[dict[str, object]] = [
        {"rfilename": "Q3_K_M", "size": 25},
        {"rfilename": "model-Q3_K_M.gguf", "size": 26},
        {"rfilename": "README.md", "size": 10},
    ]
    assert resolve_artifact(reference, siblings).filename == "model-Q3_K_M.gguf"

    with pytest.raises(ModelError, match="No GGUF artifact matches"):
        resolve_artifact(ExternalModelReference.parse("hf:owner/repository:Q4_K_M"), siblings)

    with pytest.raises(ModelError, match="ambiguous"):
        resolve_artifact(
            reference,
            [
                {"rfilename": "part-a-Q3_K_M.gguf", "size": 25},
                {"rfilename": "part-b-Q3_K_M.gguf", "size": 25},
            ],
        )


def test_user_registry_persists_and_cannot_shadow_curated_ids(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    model = import_fixture(paths)
    reloaded = ModelRegistry(paths.model_registry)

    assert reloaded.get(model.id) == model
    assert reloaded.get(DEFAULT_MODEL_ID) == MODEL_REGISTRY[DEFAULT_MODEL_ID]
    assert set(reloaded.effective()) == {*MODEL_REGISTRY, model.id}

    payload = json.loads(paths.model_registry.read_text(encoding="utf-8"))
    payload["models"][0]["id"] = DEFAULT_MODEL_ID
    paths.model_registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelError, match="conflicts with a curated"):
        reloaded.effective()


def test_v1_registry_migrates_and_hidden_curated_ids_remain_reserved(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    paths.config.mkdir(parents=True)
    paths.model_registry.write_text(json.dumps({"version": 1, "models": []}), encoding="utf-8")
    registry = ModelRegistry(paths.model_registry)
    curated_id = "qwen3.8-27b-iq2-s"

    registry.hide_curated(curated_id)

    persisted = json.loads(paths.model_registry.read_text(encoding="utf-8"))
    assert persisted["version"] == 2
    assert persisted["hidden_curated_ids"] == [curated_id]
    assert curated_id not in registry.effective()
    assert registry.reserved_model(curated_id) == MODEL_REGISTRY[curated_id]

    payload = gguf_payload(b"collision")
    client = FakeHuggingFaceClient(artifact_for(payload, repository="owner/Another-GGUF"), payload)
    with pytest.raises(ModelError, match="already belongs"):
        ModelImporter(paths.models, registry, client).import_model(
            "hf:owner/Another-GGUF:Q3_K_M", alias=curated_id
        )
    assert client.downloads == 0


def test_import_is_atomic_idempotent_and_detects_id_collisions(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    payload = gguf_payload(b"valid")
    client = FakeHuggingFaceClient(artifact_for(payload), payload)
    importer = ModelImporter(paths.models, ModelRegistry(paths.model_registry), client)

    first = importer.import_model("hf:owner/Example-GGUF:Q3_K_M")
    second = importer.import_model("hf:owner/Example-GGUF:Q3_K_M")

    assert first == second
    assert client.downloads == 1
    assert ModelManager(paths.models).is_valid(first)
    assert len(ModelRegistry(paths.model_registry).user_models()) == 1

    other_payload = gguf_payload(b"other")
    other_client = FakeHuggingFaceClient(
        artifact_for(other_payload, repository="another/Example-GGUF"), other_payload
    )
    with pytest.raises(ModelError, match="already belongs"):
        ModelImporter(paths.models, ModelRegistry(paths.model_registry), other_client).import_model(
            "hf:another/Example-GGUF:Q3_K_M"
        )


def test_partial_or_invalid_download_never_registers(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    valid = gguf_payload(b"complete")

    partial_client = FakeHuggingFaceClient(artifact_for(valid), valid[:-1])
    with pytest.raises(ModelError, match="incomplete"):
        ModelImporter(
            paths.models, ModelRegistry(paths.model_registry), partial_client
        ).import_model("hf:owner/Example-GGUF:Q3_K_M")
    assert ModelRegistry(paths.model_registry).user_models() == {}
    assert len(list(paths.models.glob(".example-q3-k-m.*.gguf.partial"))) == 1

    invalid = b"not-a-gguf-container-data"
    invalid_client = FakeHuggingFaceClient(artifact_for(invalid), invalid)
    with pytest.raises(ModelError, match="not a valid GGUF"):
        ModelImporter(
            paths.models,
            ModelRegistry(paths.model_registry),
            invalid_client,
        ).import_model("hf:owner/Example-GGUF:Q3_K_M")
    assert ModelRegistry(paths.model_registry).user_models() == {}


def test_interrupted_http_download_remains_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = gguf_payload(b"network")
    artifact = artifact_for(payload)
    partial = tmp_path / "model.gguf.partial"

    class InterruptedResponse:
        status = 200

        def __init__(self) -> None:
            self.reads = 0

        def __enter__(self) -> InterruptedResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            self.reads += 1
            if self.reads == 1:
                return payload[:8]
            raise http.client.IncompleteRead(payload[:8], len(payload))

    monkeypatch.setattr(
        "knemora_bootstrap.model_import.urllib.request.urlopen",
        lambda *args, **kwargs: InterruptedResponse(),
    )

    with pytest.raises(ModelError, match="rerun the same command to resume"):
        HuggingFaceClient().download(artifact, partial)
    assert partial.read_bytes() == payload[:8]


def test_imported_model_lists_offline_and_reports_missing_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    model = import_fixture(paths)

    _print_models(paths)
    listed = capsys.readouterr().out
    assert model.id in listed
    assert "User" in listed
    assert "Custom" in listed
    assert "installed" in listed

    ModelManager(paths.models).path_for(model).unlink()
    _print_models(paths)
    assert "missing" in capsys.readouterr().out


def test_registered_import_can_be_selected_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    paths = AppPaths(repository=repository, data=tmp_path / "data")
    model = import_fixture(paths)
    paths.wiki.mkdir(parents=True)
    wiki_page = paths.wiki / "unrelated.md"
    wiki_page.write_text("unchanged knowledge\n", encoding="utf-8")
    wiki_digest = hashlib.sha256(wiki_page.read_bytes()).hexdigest()
    graph_state = paths.wiki / ".knemora" / "graph-index.json"
    graph_state.parent.mkdir(parents=True)
    graph_state.write_text('{"nodes": ["stable"]}\n', encoding="utf-8")
    dataset = paths.data / "datasets" / "stable.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("name,value\nstable,1\n", encoding="utf-8")
    source = paths.sources / "stable" / "original.md"
    source.parent.mkdir(parents=True)
    source.write_text("immutable source\n", encoding="utf-8")
    preserved = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (graph_state, dataset, source)
    }
    server = tmp_path / "llama-server"
    server.write_text("binary", encoding="utf-8")

    class FakePlatform:
        def check_prerequisites(self) -> list[str]:
            return []

        def hardware(self) -> Hardware:
            return Hardware("macOS", "arm64", 16.0, "Apple Metal", 16.0)

        def prepare_dependencies(self) -> None:
            return None

        def llama_server(self) -> Path:
            return server

    manager = SetupManager(paths, FakePlatform())  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "_prepare_application", lambda: None)
    monkeypatch.setattr(manager, "_prepare_database", lambda: None)

    class FakeNativeRuntimeManager:
        def __init__(self, _: AppPaths) -> None:
            pass

        def ensure_llama(self) -> RuntimeSelection:
            return RuntimeSelection(
                source="test",
                executable=server,
                component="llama.cpp",
                version="test",
                platform="darwin",
                architecture="arm64",
                backend="metal",
                compatible=True,
                integrity="test",
            )

    monkeypatch.setattr("knemora_bootstrap.cli.NativeRuntimeManager", FakeNativeRuntimeManager)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    manager.run(model_id=model.id)

    selection = json.loads((paths.config / "model.json").read_text(encoding="utf-8"))
    assert selection["model_id"] == model.id
    assert selection["path"] == str(ModelManager(paths.models).path_for(model))
    assert selection["context_tokens"] == 4096
    assert ModelRegistry(paths.model_registry).get(model.id) == model
    assert hashlib.sha256(wiki_page.read_bytes()).hexdigest() == wiki_digest
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in preserved} == preserved


def test_removal_is_two_stage_for_user_and_curated_models(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    model = import_fixture(paths)

    _remove_model(paths, model.id)

    assert ModelRegistry(paths.model_registry).get(model.id) == model
    assert not (paths.models / f"{model.id}.gguf").exists()
    _remove_registry_definition(paths, model.id)
    assert model.id not in ModelRegistry(paths.model_registry).effective()

    curated_id = "qwen3.8-27b-iq2-s"
    curated = ModelRegistry(paths.model_registry).get(curated_id)
    curated_path = ModelManager(paths.models).path_for(curated)
    curated_path.write_bytes(b"downloaded curated artifact")
    curated_path.with_suffix(curated_path.suffix + ".partial").write_bytes(b"partial")

    _remove_model(paths, curated_id)

    assert not curated_path.exists()
    assert not curated_path.with_suffix(curated_path.suffix + ".partial").exists()
    assert ModelRegistry(paths.model_registry).get(curated_id) == curated
    _remove_registry_definition(paths, curated_id)
    assert curated_id not in ModelRegistry(paths.model_registry).effective()
    assert curated_id in ModelRegistry(paths.model_registry).hidden_curated_ids()

    with pytest.raises(ModelError, match="required default"):
        ModelRegistry(paths.model_registry).hide_curated(DEFAULT_MODEL_ID)


def test_registry_removal_requires_artifact_removal_first(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    model = import_fixture(paths)

    with pytest.raises(RuntimeError) as raised:
        _remove_registry_definition(paths, model.id)

    message = str(raised.value)
    assert f"./knemora model remove {model.id}" in message
    assert f"./knemora model remove {model.id} registry" in message
    assert ModelRegistry(paths.model_registry).get(model.id) == model
    assert ModelManager(paths.models).path_for(model).exists()


def test_active_model_cannot_be_removed(tmp_path: Path) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    model = import_fixture(paths)
    paths.config.mkdir(parents=True, exist_ok=True)
    (paths.config / "model.json").write_text(json.dumps({"model_id": model.id}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="is active"):
        _remove_model(paths, model.id)

    assert ModelRegistry(paths.model_registry).get(model.id) == model
    assert ModelManager(paths.models).path_for(model).exists()


def test_unknown_setup_id_is_registry_only_and_noninteractive_import_requires_yes() -> None:
    with pytest.raises(ModelError, match="is not registered"):
        ModelRegistry().get("owner/arbitrary-hugging-face-repository")

    args = _parser().parse_args(
        ["--non-interactive", "--yes", "load", "--model", "hf:owner/repo:Q3_K_M"]
    )
    assert args.command == "load"
    assert args.yes is True
    assert args.non_interactive is True
    remove = _parser().parse_args(
        ["--non-interactive", "--yes", "model", "remove", "custom-id", "registry"]
    )
    assert remove.scope == "registry"


def test_noninteractive_import_without_yes_fails_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = AppPaths(repository=tmp_path / "repo", data=tmp_path / "data")
    monkeypatch.setattr(AppPaths, "discover", classmethod(lambda cls: paths))

    result = main(["--non-interactive", "load", "--model", "hf:owner/Example-GGUF:Q3_K_M"])

    assert result == 2
    assert "requires --yes" in capsys.readouterr().err
    assert not paths.model_registry.exists()
