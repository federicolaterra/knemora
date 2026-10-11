# Contributing to Knemora

Thank you for helping improve Knemora. Open an issue before a large architectural change so scope,
data compatibility, and security implications can be agreed first.

## Development workflow

1. Read the public [architecture](../docs/open-source/architecture.md),
   [development](../docs/open-source/development.md), and
   [security](../docs/open-source/security.md) guides.
2. Create a focused branch and keep changes within one concern.
3. Preserve immutable sources, provenance, authorization, and local-first operation.
4. Add deterministic tests for changed contracts; use agent evaluations for model behavior.
5. Run `make check`, `make public-audit`, and any affected integration/e2e checks.
6. Explain migrations, compatibility, documentation changes, and unverified checks in the PR.

Do not commit user data, source documents, model files, credentials, generated secrets, or private
URLs. Schema changes require a versioned Alembic migration; knowledge-format changes require a
documented, non-destructive migration path.

Contributions are submitted under the repository's MIT License unless a file clearly states a
different license. Preserve third-party headers and attribution.
