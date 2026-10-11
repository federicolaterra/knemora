from app.config import Settings
from app.product import create_capability_registry


def test_community_registry_has_real_features_and_rejects_unknown_names() -> None:
    registry = create_capability_registry(Settings(_env_file=None))

    assert registry.has("wiki_search")
    assert registry.has("dataset_analysis")
    assert not registry.has("enterprise_sso")
    assert not registry.has("billing")


def test_development_demo_advertises_only_read_only_capabilities() -> None:
    registry = create_capability_registry(Settings(_env_file=None, demo_mode=True))

    assert registry.has("wiki_search")
    assert registry.has("local_inference")
    assert not registry.has("dataset_analysis")
    assert not registry.has("document_ingestion")
    assert not registry.has("knowledge_compilation")
