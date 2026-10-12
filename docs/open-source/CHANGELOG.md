# Changelog

Knemora follows [Semantic Versioning](https://semver.org/). During `0.x`, minor releases may include
documented breaking changes; migrations and deprecation windows remain required for persisted data
and established interfaces.

## [Unreleased]

### Added

- GGUF-derived model context profiles, unified-memory startup preflight, per-model context
  overrides, and CLI diagnostics for advertised, configured, and effective context.
- Provider-neutral prompt budgeting with bounded history/tool evidence and actionable context or
  truncation errors.

### Fixed

- Failed model startup now restores the prior selection without initiating knowledge work.
- Intentional compilation now requires each existing-page proposal to be grounded in every cited
  source record and skips byte-identical Wiki writes, index rebuilds, and manifest rewrites.

## [0.1.0-alpha] - 2026-10-11

### Added

- Repository-root `./knemora` setup, lifecycle, diagnostics, model registry, and first-run wizard.
- Isolated versioned Development demo with 120 synthetic, interconnected, provenance-bearing pages.
- Demo-mode product metadata, UI labeling, canonical private-knowledge prompt, and graph validation.
- Content-free ADK model/tool stage timing and token/size telemetry for local performance diagnosis.
- Public Community repository policies, MIT license, third-party notices, and release audits.
- Central product identity, edition, capability, and version metadata.
- Versioned application/schema tracking and knowledge schema documentation.
- Explicit Hugging Face GGUF import, persistent user model registry, offline effective model
  listing, model metadata inspection, and safe custom-model removal.
- Explicit per-turn public web search with bounded DDGS results, source URLs, and an offline kill
  switch; private Wiki/source content is excluded from outbound queries.
- Stage progress reporting for Development preset startup.
- Optional `./knemora --dev adk-web` launcher for the existing agent through Google's official
  loopback-only developer UI, with conflict-aware port selection and duplicate detection.
- Launch-time `--yes-web-search` flags for normal and Development preset runtimes.
- Embedded SQLite storage with versioned schema migration, enforced foreign keys, WAL concurrency,
  bounded lock waits, append-only audit triggers, and SQLite-safe online backup/restore.
- Explicit, source-preserving `migrate-postgresql` workflow with a portable logical backup,
  temporary import, row-count/referential/integrity validation, atomic promotion, and retry receipt.
- Versioned portable ZIP backups with a consistent SQLite snapshot, Second Brain files, sanitized
  model metadata, per-file checksums, persistent external destination, listing/deletion, and staged
  rollback-safe restore by ID or explicit archive path.
- Native Second Brain global and local graph views, explicit-link diagnostics, safe Markdown detail
  navigation, revision-aware graph caching, and WebGL fallback navigation.

### Changed

- Local macOS Apple Silicon onboarding now checks Homebrew and prepares llama.cpp, the selected
  checksum-pinned GGUF, application dependencies, and embedded SQLite without Docker or another
  mandatory desktop application.
- The verified ISTA-DASLab Qwen3-8B GSQ Q3_K_M artifact is now the 16 GB Apple Silicon default;
  the former Qwen3.8-27B model remains an optional preserved registry entry.
- Development mode now links its isolated database, source store, and Wiki through the API and Vue
  and exposes a read-only product surface.
- Product identity is now Knemora across normal runtime and public documentation.
- `KNEMORA_*` is the canonical environment namespace.
- The Google ADK root package is now `knowledge_agent`.
- `setup --model` now accepts only effective-registry IDs; arbitrary external downloads require the
  separate `load --model hf:<owner>/<repository>:<variant>` workflow.
- Public web search is now disabled by default and is enabled only for an explicit managed runtime
  profile in addition to the existing per-turn consent guard.
- Fresh local setup, normal runtime, Development presets, diagnostics, and maintenance commands no
  longer require Docker or a PostgreSQL server.
- Setup, startup, diagnostics, and Development presets now use Knemora's native Second Brain and no
  longer install, configure, check, or launch an external Markdown viewer.

### Fixed

- Model removal now identifies curated entries before confirmation and can reclaim their downloaded
  artifact data without deleting the curated registry definition; active models remain protected.
- Registry removal is now an explicit second stage, `model remove <id> registry`, which refuses to
  run until artifact data is removed and persists local curated suppression without editing the
  source-controlled registry.
- First-run migrations now install and verify locked Alembic from the `apps/api` project and report
  the failing phase, command, working directory, and exit status.
- Runtime management tracks long-lived service PIDs, rejects stale/wrong-mode health responders,
  uses a strict Vue port, and verifies every service is down after `knemora stop`.
- Authenticated demo Wiki access now uses bootstrap-admin ownership, and Wiki authorization no
  longer reparses the full corpus once per search candidate.
- Hidden model reasoning and oversized Wiki evidence no longer inflate the default ADK flow.
- Cached Development preset validation now parses its 120-page vault once and avoids duplicate
  demo-database preparation.
- Depth-two related-page traversal now uses one request-scoped Wiki snapshot instead of repeatedly
  reparsing the vault, while the Knowledge reader renders the core page before connections finish.
- FastAPI Swagger UI now receives a documentation-scoped CSP that permits its required assets;
  ordinary API responses retain the restrictive default policy.
- User-facing local URLs now consistently use `localhost`, while services continue binding to the
  explicit loopback address.
- Remaining former-product references were removed from maintained and historical documentation.

### Deprecated

- Pre-Knemora environment variables, imports, session-storage keys, and
  Wiki metadata paths remain compatibility-only and are planned for review before a future major
  release. See `docs/open-source/upgrading.md`.
