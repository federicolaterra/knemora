"""Explicit Hugging Face GGUF import without executing repository code."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

from knemora_bootstrap.models import (
    ModelError,
    ModelManager,
    ModelRegistry,
    ModelSpec,
    model_metadata_fields,
    read_gguf_metadata,
    sha256_file,
    validate_gguf,
)

REFERENCE_PATTERN = re.compile(
    r"^hf:(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"(?P<repository>[A-Za-z0-9][A-Za-z0-9._-]*):"
    r"(?P<variant>[A-Za-z0-9][A-Za-z0-9._+-]*)$"
)
MODEL_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
PACKAGING_SUFFIXES = {"gguf", "gsq", "rco"}


@dataclass(frozen=True)
class ExternalModelReference:
    provider: str
    repository: str
    variant: str

    @classmethod
    def parse(cls, value: str) -> ExternalModelReference:
        match = REFERENCE_PATTERN.fullmatch(value)
        if match is None:
            raise ModelError(
                "Invalid external model reference. Expected "
                "hf:<owner>/<repository>:<variant>, for example "
                "hf:ISTA-DASLab/Qwen3-8B-GGUF-GSQ:Q3_K_M."
            )
        return cls(
            provider="huggingface",
            repository=f"{match['owner']}/{match['repository']}",
            variant=match["variant"],
        )


@dataclass(frozen=True)
class HuggingFaceArtifact:
    repository: str
    filename: str
    size_bytes: int
    sha256: str | None
    license_reference: str

    @property
    def download_url(self) -> str:
        repository = urllib.parse.quote(self.repository, safe="/")
        filename = urllib.parse.quote(self.filename, safe="/")
        return f"https://huggingface.co/{repository}/resolve/main/{filename}?download=true"


def _normalize(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.casefold())).strip("-")


def generate_model_id(repository: str, variant: str) -> str:
    """Create a stable CLI-safe ID from repository basename and requested variant."""

    parts = [part for part in _normalize(repository.rsplit("/", 1)[-1]).split("-") if part]
    while parts and parts[-1] in PACKAGING_SUFFIXES:
        parts.pop()
    base = "-".join(parts)
    normalized_variant = _normalize(variant.removesuffix(".gguf"))
    if not base or not normalized_variant:
        raise ModelError("Could not derive a safe model ID; supply --id <unique-alias>.")
    return f"{base}-{normalized_variant}"


def validate_model_id(model_id: str) -> str:
    if len(model_id) > 96 or MODEL_ID_PATTERN.fullmatch(model_id) is None:
        raise ModelError(
            "Model ID must be 1-96 lowercase letters, digits, dots, or hyphens, "
            "and must start and end with a letter or digit."
        )
    return model_id


def partial_path_for(model_dir: Path, model_id: str, repository: str, artifact: str) -> Path:
    """Bind resumable bytes to one exact upstream source without exposing source text in paths."""

    source_key = hashlib.sha256(f"{repository}\0{artifact}".encode()).hexdigest()[:12]
    return model_dir / f".{model_id}.{source_key}.gguf.partial"


def resolve_artifact(
    reference: ExternalModelReference, siblings: list[dict[str, object]]
) -> HuggingFaceArtifact:
    """Resolve exactly one GGUF using exact matching before deterministic normalization."""

    ggufs: list[dict[str, object]] = []
    for sibling in siblings:
        filename = sibling.get("rfilename")
        if isinstance(filename, str) and filename.casefold().endswith(".gguf"):
            ggufs.append(sibling)
    if not ggufs:
        raise ModelError(f"Repository {reference.repository!r} contains no GGUF artifacts.")

    def names(item: dict[str, object]) -> tuple[str, str, str]:
        filename = str(item["rfilename"])
        basename = filename.rsplit("/", 1)[-1]
        stem = basename[:-5] if basename.casefold().endswith(".gguf") else basename
        return filename, basename, stem

    exact = [item for item in ggufs if reference.variant in names(item)]
    candidates = exact
    if not candidates:
        casefolded = reference.variant.casefold()
        candidates = [
            item for item in ggufs if casefolded in {name.casefold() for name in names(item)}
        ]
    if not candidates:
        normalized_variant = _normalize(reference.variant.removesuffix(".gguf"))
        candidates = [
            item
            for item in ggufs
            if _normalize(names(item)[2]) == normalized_variant
            or _normalize(names(item)[2]).endswith(f"-{normalized_variant}")
        ]
    if not candidates:
        available = ", ".join(sorted(str(item["rfilename"]) for item in ggufs))
        raise ModelError(
            f"No GGUF artifact matches variant {reference.variant!r}. Available: {available}"
        )
    if len(candidates) != 1:
        matches = ", ".join(sorted(str(item["rfilename"]) for item in candidates))
        raise ModelError(
            f"Variant {reference.variant!r} is ambiguous. Matching GGUF artifacts: {matches}. "
            "Use a more specific variant."
        )

    selected = candidates[0]
    lfs = selected.get("lfs")
    lfs_data = lfs if isinstance(lfs, dict) else {}
    size = lfs_data.get("size", selected.get("size"))
    if not isinstance(size, int) or size <= 0:
        raise ModelError(
            f"Hugging Face did not provide a valid size for {selected['rfilename']!r}."
        )
    oid = lfs_data.get("oid")
    checksum = (
        oid.casefold() if isinstance(oid, str) and re.fullmatch(r"[0-9a-fA-F]{64}", oid) else None
    )
    return HuggingFaceArtifact(
        repository=reference.repository,
        filename=str(selected["rfilename"]),
        size_bytes=size,
        sha256=checksum,
        license_reference=f"https://huggingface.co/{reference.repository}",
    )


class HuggingFaceClient:
    """Small HTTPS-only boundary around the public Hugging Face model API and artifacts."""

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "Knemora/0.8.2"}
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def resolve(self, reference: ExternalModelReference) -> HuggingFaceArtifact:
        repository = urllib.parse.quote(reference.repository, safe="/")
        url = f"https://huggingface.co/api/models/{repository}?blobs=true"
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                detail = "authorization is required; authenticate with HF_TOKEN"
            elif exc.code == 404:
                detail = "repository was not found"
            else:
                detail = f"Hugging Face returned HTTP {exc.code}"
            raise ModelError(f"Could not inspect {reference.repository}: {detail}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError(
                f"Could not inspect {reference.repository}: network error: {exc}."
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ModelError("Hugging Face returned invalid model metadata.") from exc
        siblings = payload.get("siblings") if isinstance(payload, dict) else None
        if not isinstance(siblings, list):
            raise ModelError("Hugging Face response did not include an artifact listing.")
        typed_siblings = [item for item in siblings if isinstance(item, dict)]
        return resolve_artifact(reference, typed_siblings)

    def download(self, artifact: HuggingFaceArtifact, partial: Path) -> None:
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > artifact.size_bytes:
            raise ModelError(f"Partial download is larger than expected: {partial}")
        headers = self._headers()
        headers.pop("Accept", None)
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(artifact.download_url, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=60)  # noqa: S310
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                detail = "authorization is required; authenticate with HF_TOKEN"
            else:
                detail = f"HTTP {exc.code}"
            raise ModelError(f"Model download failed: {detail}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError(f"Model download failed; rerun to resume: {exc}.") from exc
        status = getattr(response, "status", 200)
        mode = "ab" if offset and status == 206 else "wb"
        if mode == "wb":
            offset = 0
        try:
            with response, partial.open(mode) as output:
                self._copy_with_progress(
                    cast(BinaryIO, response),
                    cast(BinaryIO, output),
                    offset=offset,
                    expected=artifact.size_bytes,
                )
        except (OSError, http.client.HTTPException) as exc:
            raise ModelError(
                f"Model download was interrupted; rerun the same command to resume: {exc}."
            ) from exc

    @staticmethod
    def _copy_with_progress(
        source: BinaryIO, destination: BinaryIO, *, offset: int, expected: int
    ) -> None:
        ModelManager._copy_with_progress(source, destination, offset=offset, expected=expected)


class ModelImporter:
    """Resolve, download, validate, promote, and register one explicit external model."""

    def __init__(
        self,
        model_dir: Path,
        registry: ModelRegistry,
        client: HuggingFaceClient | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.registry = registry
        self.client = client or HuggingFaceClient()

    def import_model(
        self,
        reference_value: str,
        *,
        alias: str | None = None,
        confirm: Callable[[HuggingFaceArtifact, str], bool] | None = None,
    ) -> ModelSpec:
        reference = ExternalModelReference.parse(reference_value)
        artifact = self.client.resolve(reference)
        existing_source = self.registry.find_source(reference.repository, artifact.filename)
        model_id = (
            validate_model_id(alias)
            if alias
            else generate_model_id(reference.repository, reference.variant)
        )
        if existing_source is not None:
            if alias is not None and alias != existing_source.id:
                raise ModelError(
                    f"This artifact is already registered as {existing_source.id!r}; "
                    "a second alias was not created."
                )
            if existing_source.size_bytes != artifact.size_bytes or (
                artifact.sha256 is not None and existing_source.sha256 != artifact.sha256
            ):
                raise ModelError(
                    "Upstream artifact metadata changed since import. Refusing to replace known "
                    "local bytes silently. Remove and reimport explicitly after review."
                )
            if ModelManager(self.model_dir).is_valid(existing_source):
                return existing_source
            model_id = existing_source.id
        else:
            collision = self.registry.reserved_model(model_id)
            if collision is not None:
                raise ModelError(
                    f"Generated model ID {model_id!r} already belongs to a different model; "
                    "rerun load with --id <unique-alias>."
                )

        if confirm is not None and not confirm(artifact, model_id):
            raise ModelError("Model import cancelled; no registry entry was created.")

        self.model_dir.mkdir(parents=True, exist_ok=True)
        destination = self.model_dir / f"{model_id}.gguf"
        if existing_source is None and destination.exists():
            raise ModelError(
                f"Refusing to overwrite unregistered managed artifact {destination}; "
                "move it aside or choose another --id after reviewing it."
            )
        partial = partial_path_for(self.model_dir, model_id, artifact.repository, artifact.filename)
        remaining = max(
            0, artifact.size_bytes - (partial.stat().st_size if partial.exists() else 0)
        )
        margin = max(512_000_000, math.ceil(artifact.size_bytes * 0.05))
        if shutil.disk_usage(self.model_dir).free < remaining + margin:
            raise ModelError(
                "Insufficient free disk space: need the remaining download plus approximately "
                f"{margin / 1_000_000_000:.1f} GB safety margin."
            )
        self.client.download(artifact, partial)
        actual_size = partial.stat().st_size
        if actual_size != artifact.size_bytes:
            raise ModelError(
                f"Download is incomplete ({actual_size} of {artifact.size_bytes} bytes); "
                f"the partial file remains resumable at {partial}."
            )
        validate_gguf(partial)
        metadata_fields = model_metadata_fields(read_gguf_metadata(partial))
        actual_checksum = sha256_file(partial)
        if artifact.sha256 is not None and actual_checksum != artifact.sha256:
            raise ModelError(
                "Downloaded model checksum did not match Hugging Face metadata; "
                f"the partial file was retained at {partial}."
            )
        partial.replace(destination)

        if existing_source is not None:
            return existing_source
        recommended_memory = max(1, math.ceil(artifact.size_bytes * 1.25 / 1024**3))
        advertised_context = metadata_fields.get("advertised_context_tokens")
        preferred_context = min(
            8192,
            advertised_context if isinstance(advertised_context, int) else 4096,
        )
        model = ModelSpec(
            id=model_id,
            display_name=f"{reference.repository.rsplit('/', 1)[-1]} {reference.variant}",
            provider="llama_cpp",
            repository=reference.repository,
            filename=destination.name,
            artifact=artifact.filename,
            variant=reference.variant,
            quantization=reference.variant,
            sha256=actual_checksum,
            size_bytes=actual_size,
            required_free_bytes=actual_size + margin,
            recommended_memory_gb=recommended_memory,
            context_tokens=preferred_context,
            license_url=artifact.license_reference,
            origin="user",
            local_path=str(destination.resolve()),
            imported_at=datetime.now(UTC).isoformat(),
            verification_status="custom-unverified-by-knemora",
            compatibility_status="not-checked",
            metadata_architecture=(
                str(metadata_fields.get("metadata_architecture"))
                if metadata_fields.get("metadata_architecture")
                else ""
            ),
            advertised_context_tokens=(
                value
                if isinstance((value := metadata_fields.get("advertised_context_tokens")), int)
                else None
            ),
            embedding_length=(
                value
                if isinstance((value := metadata_fields.get("embedding_length")), int)
                else None
            ),
            block_count=(
                value if isinstance((value := metadata_fields.get("block_count")), int) else None
            ),
            attention_head_count=(
                value
                if isinstance((value := metadata_fields.get("attention_head_count")), int)
                else None
            ),
            attention_head_count_kv=(
                value
                if isinstance((value := metadata_fields.get("attention_head_count_kv")), int)
                else None
            ),
            attention_key_length=(
                value
                if isinstance((value := metadata_fields.get("attention_key_length")), int)
                else None
            ),
            attention_value_length=(
                value
                if isinstance((value := metadata_fields.get("attention_value_length")), int)
                else None
            ),
        )
        return self.registry.register(model)
