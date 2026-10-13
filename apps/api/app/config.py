"""Application configuration with canonical KNEMORA_* environment variables."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def _default_database_url() -> str:
    data_root = Path(os.environ.get("KNEMORA_HOME", Path.home() / ".knemora")).expanduser()
    return f"sqlite+pysqlite:///{data_root / 'data' / 'knemora.db'}"


def _environment_alias(name: str) -> AliasChoices:
    """Prefer Knemora variables while accepting legacy names during migration."""

    return AliasChoices(f"KNEMORA_{name}", f"PHARMATRACE_{name}")


def _setting(default: Any, name: str, **constraints: Any) -> Any:
    return Field(default=default, validation_alias=_environment_alias(name), **constraints)


def _configured_environment_names() -> set[str]:
    """Return variable names from the process and root .env without reading their values."""

    names = set(os.environ)
    env_file = REPOSITORY_ROOT / ".env"
    if not env_file.is_file():
        return names
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].removeprefix("export ").strip()
        if name:
            names.add(name)
    return names


class Settings(BaseSettings):
    """Runtime settings with safe local-development defaults."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    product_name: str = _setting("Knemora", "PRODUCT_NAME", min_length=1, max_length=100)
    product_edition: Literal["community"] = _setting("community", "PRODUCT_EDITION")
    product_description: str = _setting(
        "Open-source, local-first knowledge and agent platform with a native Second Brain graph, "
        "a portable Markdown wiki, and local AI inference.",
        "PRODUCT_DESCRIPTION",
        min_length=1,
        max_length=300,
    )
    product_website: str | None = _setting(None, "PRODUCT_WEBSITE")
    product_support_url: str | None = _setting(None, "PRODUCT_SUPPORT_URL")
    demo_mode: bool = _setting(False, "DEMO_MODE")
    demo_preset: str | None = _setting(None, "DEMO_PRESET")

    app_env: str = _setting("development", "APP_ENV")
    api_host: str = _setting("127.0.0.1", "API_HOST")
    api_port: int = _setting(8000, "API_PORT")
    web_origin: str = _setting("http://localhost:5173", "WEB_ORIGIN")
    database_url: str = Field(
        default_factory=_default_database_url,
        validation_alias=_environment_alias("DATABASE_URL"),
    )
    log_level: str = _setting("INFO", "LOG_LEVEL")
    request_id_header: str = _setting("X-Request-ID", "REQUEST_ID_HEADER")
    default_user_email: str = _setting("local@knemora.invalid", "DEFAULT_USER_EMAIL")
    default_user_name: str = _setting("Local User", "DEFAULT_USER_NAME")
    authentication_required: bool = _setting(True, "AUTHENTICATION_REQUIRED")
    bootstrap_admin_email: str = _setting("admin@knemora.local", "BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_name: str = _setting("Knemora Administrator", "BOOTSTRAP_ADMIN_NAME")
    bootstrap_admin_password: SecretStr | None = _setting(None, "BOOTSTRAP_ADMIN_PASSWORD")
    auth_session_ttl_minutes: int = _setting(480, "AUTH_SESSION_TTL_MINUTES", ge=5, le=10_080)
    auth_max_failed_attempts: int = _setting(5, "AUTH_MAX_FAILED_ATTEMPTS", ge=1, le=20)
    auth_lockout_minutes: int = _setting(15, "AUTH_LOCKOUT_MINUTES", ge=1, le=1_440)
    login_rate_limit_per_minute: int = _setting(10, "LOGIN_RATE_LIMIT_PER_MINUTE", ge=1, le=1_000)
    mutation_rate_limit_per_minute: int = _setting(
        120, "MUTATION_RATE_LIMIT_PER_MINUTE", ge=1, le=10_000
    )
    trusted_hosts: str = _setting("127.0.0.1,localhost,testserver,test", "TRUSTED_HOSTS")

    llm_base_url: str = _setting("http://localhost:8080", "LLM_BASE_URL")
    llm_model: str = _setting("qwen3-8b-q3-k-m", "LLM_MODEL")
    llm_quantization: str = _setting("Q3_K_M (GSQ-refined K-Quant)", "LLM_QUANTIZATION")
    llm_api_key: SecretStr | None = _setting(None, "LLM_API_KEY")
    llm_timeout_seconds: float = _setting(180.0, "LLM_TIMEOUT_SECONDS", gt=0)
    llm_context_tokens: int = _setting(8192, "LLM_CONTEXT_TOKENS", ge=512)
    llm_max_output_tokens: int = _setting(1024, "LLM_MAX_OUTPUT_TOKENS", ge=1)
    llm_enable_thinking: bool = _setting(False, "LLM_ENABLE_THINKING")
    max_user_message_chars: int = _setting(20_000, "MAX_USER_MESSAGE_CHARS", ge=1)
    source_store_path: Path = _setting(Path("data/sources"), "SOURCE_STORE_PATH")
    knowledge_path: Path = _setting(Path("knowledge"), "KNOWLEDGE_PATH")
    knowledge_compilation_version: str = _setting("knemora-wiki/1", "KNOWLEDGE_COMPILATION_VERSION")
    knowledge_compilation_max_output_tokens: int = _setting(
        2_048, "KNOWLEDGE_COMPILATION_MAX_OUTPUT_TOKENS", ge=1
    )
    knowledge_compilation_timeout_seconds: float = _setting(
        300.0, "KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS", gt=0
    )
    knowledge_compilation_batch_chars: int = _setting(
        12_000, "KNOWLEDGE_COMPILATION_BATCH_CHARS", ge=1_000
    )
    wiki_search_max_results: int = _setting(20, "WIKI_SEARCH_MAX_RESULTS", ge=1, le=100)
    wiki_graph_max_depth: int = _setting(2, "WIKI_GRAPH_MAX_DEPTH", ge=1, le=5)
    wiki_graph_max_nodes: int = _setting(2_000, "WIKI_GRAPH_MAX_NODES", ge=1, le=20_000)
    wiki_graph_max_edges: int = _setting(8_000, "WIKI_GRAPH_MAX_EDGES", ge=1, le=80_000)
    wiki_graph_small_graph_threshold: int = _setting(
        50, "WIKI_GRAPH_SMALL_GRAPH_THRESHOLD", ge=0, le=20_000
    )
    wiki_evidence_max_chars: int = _setting(12_000, "WIKI_EVIDENCE_MAX_CHARS", ge=1_000)
    source_reference_max_chars: int = _setting(8_000, "SOURCE_REFERENCE_MAX_CHARS", ge=500)
    web_search_enabled: bool = _setting(False, "WEB_SEARCH_ENABLED")
    web_search_timeout_seconds: int = _setting(8, "WEB_SEARCH_TIMEOUT_SECONDS", ge=1, le=30)
    web_search_max_results: int = _setting(5, "WEB_SEARCH_MAX_RESULTS", ge=1, le=10)
    update_check_enabled: bool = _setting(True, "UPDATE_CHECK_ENABLED")
    dataset_analysis_max_rows: int = _setting(250_000, "DATASET_ANALYSIS_MAX_ROWS", ge=1)
    dataset_analysis_max_result_rows: int = _setting(
        500, "DATASET_ANALYSIS_MAX_RESULT_ROWS", ge=1, le=5_000
    )
    max_upload_bytes: int = _setting(25 * 1024 * 1024, "MAX_UPLOAD_BYTES", ge=1)
    max_archive_entries: int = _setting(10_000, "MAX_ARCHIVE_ENTRIES", ge=1)
    max_archive_uncompressed_bytes: int = _setting(
        100 * 1024 * 1024, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", ge=1
    )
    max_archive_compression_ratio: float = _setting(100.0, "MAX_ARCHIVE_COMPRESSION_RATIO", gt=1)

    def model_post_init(self, __context: Any) -> None:
        """Warn when a process still relies on a legacy environment variable."""

        configured_names = _configured_environment_names()
        for name in type(self).model_fields:
            legacy = f"PHARMATRACE_{name.upper()}"
            canonical = f"KNEMORA_{name.upper()}"
            if legacy in configured_names and canonical not in configured_names:
                logger.warning(
                    "Deprecated environment variable %s; use %s instead.",
                    legacy,
                    canonical,
                )

    @field_validator("source_store_path", "knowledge_path", mode="after")
    @classmethod
    def resolve_repository_path(cls, value: Path) -> Path:
        """Resolve configured relative storage paths from the repository root."""

        return value if value.is_absolute() else REPOSITORY_ROOT / value

    @field_validator("llm_base_url", mode="after")
    @classmethod
    def normalize_llm_base_url(cls, value: str) -> str:
        """Store the provider endpoint without a trailing slash."""

        return value.rstrip("/")

    @field_validator("bootstrap_admin_password", mode="after")
    @classmethod
    def validate_bootstrap_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        password = value.get_secret_value()
        if password == "replace-with-a-unique-local-password":
            raise ValueError("Replace the example bootstrap administrator password before startup.")
        if len(password) < 12:
            raise ValueError("The bootstrap administrator password must have 12+ characters.")
        return value

    @property
    def trusted_host_list(self) -> list[str]:
        """Return the configured explicit host allow-list."""

        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance per process."""

    return Settings()
