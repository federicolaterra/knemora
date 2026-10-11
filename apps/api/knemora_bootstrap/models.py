"""Curated and user model registries plus safe local artifact management."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, cast

DEFAULT_MODEL_ID = "qwen3-8b-q3-k-m"
USER_REGISTRY_VERSION = 2
SUPPORTED_USER_REGISTRY_VERSIONS = {1, USER_REGISTRY_VERSION}


class ModelError(RuntimeError):
    """A selected model is unknown, invalid, or could not be acquired safely."""


@dataclass(frozen=True)
class ModelSpec:
    """One local llama.cpp GGUF artifact known to Knemora."""

    id: str
    display_name: str
    provider: str
    repository: str
    filename: str
    quantization: str
    sha256: str
    size_bytes: int
    required_free_bytes: int
    recommended_memory_gb: int
    context_tokens: int
    license_url: str
    enabled: bool = True
    origin: str = "curated"
    source_provider: str = "huggingface"
    artifact: str = ""
    variant: str = ""
    format: str = "gguf"
    runtime: str = "llama.cpp"
    local_path: str = ""
    imported_at: str = ""
    verification_status: str = "knemora-tested"
    compatibility_status: str = "knemora-tested"

    @property
    def download_url(self) -> str:
        artifact = self.artifact or self.filename
        return f"https://huggingface.co/{self.repository}/resolve/main/{artifact}?download=true"

    @property
    def is_user_import(self) -> bool:
        return self.origin == "user"


MODEL_REGISTRY: dict[str, ModelSpec] = {
    DEFAULT_MODEL_ID: ModelSpec(
        id=DEFAULT_MODEL_ID,
        display_name="Qwen3 8B GSQ Q3_K_M",
        provider="llama_cpp",
        repository="ISTA-DASLab/Qwen3-8B-GGUF-GSQ",
        filename="qwen3-8b-Q3_K_M.gguf",
        artifact="qwen3-8b-Q3_K_M.gguf",
        variant="Q3_K_M",
        quantization="Q3_K_M (GSQ-refined K-Quant)",
        sha256="81894ed9b0e0245af542019a941e0aac21f3ec8b5a2386b82486db19c0170e77",
        size_bytes=4_124_161_376,
        required_free_bytes=5_500_000_000,
        recommended_memory_gb=8,
        context_tokens=8192,
        license_url="https://huggingface.co/ISTA-DASLab/Qwen3-8B-GGUF-GSQ",
    ),
    "qwen3.8-27b-iq2-s": ModelSpec(
        id="qwen3.8-27b-iq2-s",
        display_name="Qwen3.8 27B GSQ-RCO IQ2_S",
        provider="llama_cpp",
        repository="ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF",
        filename="Qwen3.8-27B-GSQ-RCO-IQ2_S.gguf",
        artifact="Qwen3.8-27B-GSQ-RCO-IQ2_S.gguf",
        variant="IQ2_S",
        quantization="IQ2_S (GSQ/RCO, 2.75 bpw)",
        sha256="16c9802111aa9ef3acde465188d6d601f8db128ee3d828ad983a5caca4135ecb",
        size_bytes=9_260_000_000,
        required_free_bytes=11_000_000_000,
        recommended_memory_gb=16,
        context_tokens=4096,
        license_url="https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF",
    ),
}


class ModelRegistry:
    """Merge immutable curated models with an atomic local user registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path

    def _read_state(self) -> tuple[dict[str, ModelSpec], set[str]]:
        if self.registry_path is None or not self.registry_path.is_file():
            return {}, set()
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("registry root must be an object")
            if payload.get("version") not in SUPPORTED_USER_REGISTRY_VERSIONS:
                raise ValueError("unsupported registry version")
            raw_entries = payload.get("models")
            if not isinstance(raw_entries, list):
                raise ValueError("models must be a list")
            entries = [ModelSpec(**entry) for entry in raw_entries]
            raw_hidden = payload.get("hidden_curated_ids", [])
            if not isinstance(raw_hidden, list) or not all(
                isinstance(model_id, str) for model_id in raw_hidden
            ):
                raise ValueError("hidden_curated_ids must be a list of strings")
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise ModelError(
                f"User model registry is invalid: {self.registry_path}: {exc}"
            ) from exc
        models: dict[str, ModelSpec] = {}
        for model in entries:
            if model.origin != "user":
                raise ModelError(f"User registry entry {model.id!r} has invalid origin.")
            if model.id in MODEL_REGISTRY:
                raise ModelError(
                    f"User registry entry {model.id!r} conflicts with a curated model ID."
                )
            if model.id in models:
                raise ModelError(f"Duplicate user model ID {model.id!r} in registry.")
            models[model.id] = model
        hidden = set(raw_hidden)
        for model_id in hidden:
            if model_id not in MODEL_REGISTRY:
                raise ModelError(f"Hidden curated model ID {model_id!r} is unknown.")
            if model_id == DEFAULT_MODEL_ID:
                raise ModelError("The required default model definition cannot be hidden.")
        return models, hidden

    def user_models(self) -> dict[str, ModelSpec]:
        return self._read_state()[0]

    def hidden_curated_ids(self) -> set[str]:
        return self._read_state()[1]

    def effective(self) -> dict[str, ModelSpec]:
        users, hidden = self._read_state()
        curated = {
            model_id: model for model_id, model in MODEL_REGISTRY.items() if model_id not in hidden
        }
        return {**curated, **users}

    def reserved_model(self, model_id: str) -> ModelSpec | None:
        """Return an ID owner even when a curated entry is locally suppressed."""

        return MODEL_REGISTRY.get(model_id) or self.user_models().get(model_id)

    def get(self, model_id: str) -> ModelSpec:
        resolved = DEFAULT_MODEL_ID if model_id == "default" else model_id
        model = self.effective().get(resolved)
        if model is None or not model.enabled:
            raise ModelError(
                f"Model {model_id!r} is not registered.\n\n"
                "Run:\n  ./knemora models\n\n"
                "To import a custom Hugging Face GGUF:\n"
                "  ./knemora load --model hf:<owner>/<repository>:<variant>"
            )
        return model

    def register(self, model: ModelSpec) -> ModelSpec:
        if self.registry_path is None:
            raise ModelError("A persistent user registry path is required for registration.")
        if model.origin != "user":
            raise ModelError("Only user-imported models can be written to the user registry.")
        users, hidden = self._read_state()
        if model.id in MODEL_REGISTRY:
            raise ModelError(
                f"Model ID {model.id!r} is reserved by the curated registry; "
                "rerun load with --id <unique-alias>."
            )
        existing = users.get(model.id)
        if existing is not None:
            if (
                existing.origin == "user"
                and existing.repository == model.repository
                and (existing.artifact or existing.filename) == (model.artifact or model.filename)
                and existing.size_bytes == model.size_bytes
                and existing.sha256 == model.sha256
            ):
                return existing
            raise ModelError(
                f"Model ID {model.id!r} is already used by a different model; "
                "rerun load with --id <unique-alias>."
            )
        users[model.id] = model
        self._write(users, hidden)
        return model

    def remove(self, model_id: str) -> ModelSpec:
        users, hidden = self._read_state()
        model = users.pop(model_id, None)
        if model is None:
            if model_id in MODEL_REGISTRY:
                raise ModelError("Curated model definitions cannot be removed.")
            raise ModelError(f"User model {model_id!r} is not registered.")
        self._write(users, hidden)
        return model

    def hide_curated(self, model_id: str) -> ModelSpec:
        if self.registry_path is None:
            raise ModelError("A persistent user registry path is required for registry removal.")
        if model_id == DEFAULT_MODEL_ID:
            raise ModelError(
                f"The required default model definition {DEFAULT_MODEL_ID!r} cannot be removed."
            )
        model = MODEL_REGISTRY.get(model_id)
        if model is None:
            raise ModelError(f"Curated model {model_id!r} is not registered.")
        users, hidden = self._read_state()
        hidden.add(model_id)
        self._write(users, hidden)
        return model

    def find_source(self, repository: str, artifact: str) -> ModelSpec | None:
        for model in self.user_models().values():
            if model.repository == repository and (model.artifact or model.filename) == artifact:
                return model
        return None

    def _write(self, models: dict[str, ModelSpec], hidden_curated_ids: set[str]) -> None:
        assert self.registry_path is not None
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        payload = {
            "version": USER_REGISTRY_VERSION,
            "models": [
                asdict(model) for model in sorted(models.values(), key=lambda item: item.id)
            ],
            "hidden_curated_ids": sorted(hidden_curated_ids),
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            temporary.chmod(0o600)
            temporary.replace(self.registry_path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ModelError(f"Could not persist user model registry: {exc}") from exc


def get_model(model_id: str, registry_path: Path | None = None) -> ModelSpec:
    """Resolve ``default`` or a registered identifier."""

    return ModelRegistry(registry_path).get(model_id)


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Hash a file without loading a multi-gigabyte artifact into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_gguf(path: Path) -> None:
    """Reject truncated or implausible GGUF containers without executing model code."""

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise ModelError(f"Could not inspect GGUF artifact {path}: {exc}") from exc
    if size < 24 or len(header) != 24 or header[:4] != b"GGUF":
        raise ModelError("Downloaded artifact is not a valid GGUF file (missing GGUF header).")
    version, tensor_count, metadata_count = struct.unpack("<IQQ", header[4:])
    if version not in {2, 3}:
        raise ModelError(f"Unsupported GGUF container version {version}; expected version 2 or 3.")
    if tensor_count > 10_000_000 or metadata_count > 10_000_000:
        raise ModelError("GGUF header contains implausible tensor or metadata counts.")


class ModelManager:
    """Validate, download, resume, and atomically promote registered models."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir

    def path_for(self, model: ModelSpec) -> Path:
        if model.local_path:
            candidate = Path(model.local_path).expanduser().resolve()
            root = self.model_dir.resolve()
            if not candidate.is_relative_to(root):
                raise ModelError(
                    f"Registered model path escapes the managed directory: {candidate}"
                )
            return candidate
        if Path(model.filename).name != model.filename:
            raise ModelError(f"Unsafe managed model filename: {model.filename!r}")
        return self.model_dir / model.filename

    def is_valid(self, model: ModelSpec) -> bool:
        path = self.path_for(model)
        if not path.is_file() or path.stat().st_size != model.size_bytes:
            return False
        try:
            validate_gguf(path)
        except ModelError:
            return False
        return sha256_file(path) == model.sha256

    def artifact_status(self, model: ModelSpec) -> str:
        path = self.path_for(model)
        if not path.is_file():
            return "missing" if model.is_user_import else "not-downloaded"
        if path.stat().st_size != model.size_bytes:
            return "corrupt"
        try:
            validate_gguf(path)
        except ModelError:
            return "corrupt"
        return "installed"

    def ensure(self, model: ModelSpec) -> Path:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(model)
        if self.is_valid(model):
            return destination
        if model.is_user_import:
            raise ModelError(
                f"Imported model artifact is missing or corrupt: {destination}. "
                "Re-run the original load command to recover it safely."
            )
        if destination.exists():
            invalid = destination.with_suffix(destination.suffix + ".invalid")
            destination.replace(invalid)

        free = shutil.disk_usage(self.model_dir).free
        partial = destination.with_suffix(destination.suffix + ".partial")
        remaining = max(0, model.size_bytes - (partial.stat().st_size if partial.exists() else 0))
        safety_margin = max(0, model.required_free_bytes - model.size_bytes)
        if free < remaining + safety_margin:
            raise ModelError(
                f"Insufficient free disk space for {model.display_name}: "
                f"need approximately {model.required_free_bytes / 1_000_000_000:.1f} GB."
            )

        self._download(model, partial)
        actual = sha256_file(partial)
        if actual != model.sha256:
            raise ModelError(
                "Downloaded model checksum did not match the registry; the partial file was "
                f"retained for inspection at {partial}."
            )
        validate_gguf(partial)
        partial.replace(destination)
        return destination

    def _download(self, model: ModelSpec, partial: Path) -> None:
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "Knemora/0.8.2"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(model.download_url, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=60)  # noqa: S310
        except urllib.error.URLError as exc:
            raise ModelError(f"Model download failed: {exc.reason}") from exc
        status = getattr(response, "status", 200)
        mode = "ab" if offset and status == 206 else "wb"
        if mode == "wb":
            offset = 0
        total = response.headers.get("Content-Length")
        expected = offset + int(total) if total and total.isdigit() else model.size_bytes
        with response, partial.open(mode) as output:
            self._copy_with_progress(
                cast(BinaryIO, response),
                cast(BinaryIO, output),
                offset=offset,
                expected=expected,
            )

    @staticmethod
    def _copy_with_progress(
        source: BinaryIO, destination: BinaryIO, *, offset: int, expected: int
    ) -> None:
        downloaded = offset
        last_percent = -1
        while chunk := source.read(4 * 1024 * 1024):
            destination.write(chunk)
            downloaded += len(chunk)
            percent = min(100, int(downloaded * 100 / expected)) if expected else 0
            if percent // 5 != last_percent // 5:
                print(f"Model download: {downloaded / 1_000_000_000:.2f} GB ({percent}%)")
                last_percent = percent
        destination.flush()
