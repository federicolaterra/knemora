# Changelog

Knemora follows [Semantic Versioning](https://semver.org/). During `0.x`, minor releases may include
documented breaking changes; migrations and deprecation windows remain required for persisted data
and established interfaces.

## [Unreleased]

### Added

- Request-scoped Fast / Deep chat controls with selected-model capability reporting, immutable
  per-turn propagation through ADK and `LLMProvider`, and server-confirmed assistant execution
  metadata for model, response mode, thinking, and Web outcomes.
- Strict Direct-only public search with one deterministic bounded DDGS/DuckDuckGo attempt per
  enabled turn, current-message-only privacy checks, and truthful failure/no-result reporting. Wiki
  has no public-search authority under any runtime configuration.
- Timezone-aware UTC message creation and browser-local rendering, with assistant-response-day
  separators that avoid optimistic, duplicate, invalid, and midnight-crossover banners.
- Optional Knemora-tested `gemma-4-e4b-q4-k-m` curated model with immutable Hugging Face revision,
  exact size/SHA-256, real TXT/PDF/DOCX compilation acceptance, managed Qwen → Gemma → Qwen
  preservation/readiness/rollback acceptance, and unchanged Qwen default.
- Content-free Direct latency telemetry spanning llama.cpp prefill/decode and TTFT, provider and ADK
  stages, history/session/persistence work, and browser stream/render timing.
- Per-turn Wiki / Direct chat modes. Wiki remains the backwards-compatible default; Direct uses
  the selected local model through the existing ADK/provider path with all retrieval tools and
  schemas withheld.
- Role-aware reconstruction of persisted chat history for multi-turn follow-ups, bounded recent-
  turn retention at both supported context sizes, and automatic response-language matching with
  explicit-language overrides.
- GGUF-derived model context profiles, unified-memory startup preflight, per-model context
  overrides, and CLI diagnostics for advertised, configured, and effective context.
- Provider-neutral prompt budgeting with bounded history/tool evidence and actionable context or
  truncation errors.

### Changed

- Fast/Deep and Direct Web controls now behave as temporary browser-session overrides. Environment
  values are startup defaults, ordinary `./knemora start` is sufficient, Wiki stays no-Web, and a
  new backend runtime identity resets stale UI overrides to freshly read defaults.

### Fixed

- Curated Gemma 4 E4B now advertises its verified request-scoped thinking capability, allowing the
  same Fast/Deep controls as curated Qwen in Wiki and Direct instead of incorrectly disabling Deep.
- Removed the obsolete managed-start Web-search flag completely; standard startup plus the
  Direct-only session control is now the sole supported workflow.
- Reprocessing no longer duplicates an otherwise identical fact when a model changes only the
  proposal's claim key; exact text/classification matches retain the established claim identity and
  byte-stable Wiki page.
- Direct avoids constructing unused retrieval tools and uses a shorter equivalent policy prompt
  with an explicit concise-answer rule, reducing matched Gemma prompt and completion work without
  bypassing ADK, changing global generation settings, or weakening retrieval isolation.
- Ordinary chat no longer enters compulsory Wiki retrieval, while organization-specific questions
  and co-referential follow-ups retain bounded owner-authorized grounding and citation handling.
- Simple two-operand decimal expressions and terse arithmetic continuations now use a bounded
  grammar. Follow-ups can consume a bare or uniquely emphasized preceding numeric answer without
  `eval` or an unnecessary model/tool round trip.
- Knowledge compilation now uses a bounded 300-second deadline per structured-output attempt,
  preserving its single context-safe truncation retry without inheriting ordinary chat's shorter
  deadline. Slower healthy systems can override this response-read timeout through `.env` without
  changing context, token limits, or retry count. Timeout and transport failures are reported
  accurately and emit content-free timing, token-count, retry-cause, and correlation telemetry.
- Automatic model profiles are re-evaluated at every start and can safely fall back from the full
  8,192-token Qwen profile to 4,096 tokens without being mistaken for explicit user overrides.
- Context diagnostics now distinguish automatic full/reduced admission from explicit rejection,
  describe reduced-context quality limits, and label memory assessments as time-dependent.
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
