"""Central product identity, version, and capability contracts."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from app.config import Settings

APP_VERSION = "0.1.0-alpha"
SCHEMA_VERSION = 11
KNOWLEDGE_SCHEMA_VERSION = 1

COMMUNITY_CAPABILITIES = frozenset(
    {
        "audit",
        "authentication",
        "dataset_analysis",
        "document_ingestion",
        "knowledge_compilation",
        "local_inference",
        "native_second_brain",
        "rbac",
        "source_provenance",
        "wiki_graph",
        "wiki_search",
    }
)
DEMO_DISABLED_CAPABILITIES = frozenset(
    {"dataset_analysis", "document_ingestion", "knowledge_compilation"}
)


class CapabilityRegistry:
    """Small immutable registry used by core code and distribution extensions."""

    def __init__(self, capabilities: Iterable[str] = ()) -> None:
        self._capabilities = frozenset(capabilities)

    def has(self, capability: str) -> bool:
        return capability in self._capabilities

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))


class ProductIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    edition: str
    description: str
    website: str | None
    support_url: str | None


class VersionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_version: str
    schema_version: int
    knowledge_schema_version: int


class AuthenticationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    default_email: str


class SystemMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: ProductIdentity
    versions: VersionMetadata
    capabilities: tuple[str, ...]
    telemetry_enabled: bool = False
    demo: DemoMetadata
    authentication: AuthenticationMetadata


class DemoMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    active: bool
    preset: str | None
    topic: str | None
    synthetic: bool


def create_capability_registry(settings: Settings) -> CapabilityRegistry:
    """Build capabilities for the configured distribution."""

    if settings.product_edition == "community":
        capabilities = COMMUNITY_CAPABILITIES
        if settings.demo_mode:
            capabilities = capabilities - DEMO_DISABLED_CAPABILITIES
        return CapabilityRegistry(capabilities)
    return CapabilityRegistry()


def create_system_metadata(settings: Settings) -> SystemMetadata:
    registry = create_capability_registry(settings)
    return SystemMetadata(
        product=ProductIdentity(
            name=settings.product_name,
            edition=settings.product_edition,
            description=settings.product_description,
            website=settings.product_website,
            support_url=settings.product_support_url,
        ),
        versions=VersionMetadata(
            app_version=APP_VERSION,
            schema_version=SCHEMA_VERSION,
            knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        ),
        capabilities=registry.list(),
        authentication=AuthenticationMetadata(default_email=settings.bootstrap_admin_email),
        demo=DemoMetadata(
            active=settings.demo_mode,
            preset=settings.demo_preset if settings.demo_mode else None,
            topic="Development" if settings.demo_mode else None,
            synthetic=settings.demo_mode,
        ),
    )
