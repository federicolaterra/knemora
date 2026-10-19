# Architecture

Knemora Open-Source is a local-first modular monolith: Vue calls FastAPI; FastAPI enforces identity
and authorization before domain services; Google ADK coordinates narrow knowledge, analysis, and
explicitly opted-in public-search tools; all model calls cross `LLMProvider`; SQLite stores
operational metadata; immutable bytes and the Markdown Wiki remain in explicit filesystem
boundaries.

Core boundaries are knowledge, ingestion, Wiki, lexical/graph search, deterministic analytics,
agents, providers, authentication, and API contracts. `CapabilityRegistry` reports actual features
without edition conditionals spread through the code. Provider interfaces are extended only when a
real implementation requires them.

The open-source application includes all current core functionality without edition conditionals or
artificial limits. Cloud infrastructure is not a prerequisite for the core.

Public search is optional rather than a core dependency and is disabled for normal launches. The
operator must add `--yes-web-search`, after which a per-turn guard still requires explicit user
language. It sends only a bounded public query through DDGS/DuckDuckGo, treats results as
untrusted, and keeps them separate from private Wiki evidence.

Persisted SQLite messages are the chat source of truth. For each turn, FastAPI creates an isolated
ADK session and replays only that owner-scoped conversation as ordered user/model events before
sending the current user message once. Provider-neutral context budgeting preserves system policy,
the current turn, and the most recent conversation turns while dropping the oldest complete turns
when the active 8,192- or 4,096-token context requires it. Prior conversation text remains
untrusted and cannot become a system instruction. Ordinary chat does not require a Wiki call;
organization-specific questions and referential follow-ups use bounded authorized retrieval.
The root system policy matches the response language to the current message, honors explicit
language requests, and falls back to the established conversation language for ambiguous short
messages without rewriting citations, identifiers, code, locators, or quotations. A narrow decimal
grammar resolves simple two-operand expressions and operator-led fragments against a bare or
uniquely emphasized preceding numeric answer; all other conversation continues through the
existing ADK root agent.

The chat API also accepts a per-turn `response_mode` of `wiki` or `direct`, defaulting to `wiki`.
Wiki preserves the behavior above. Direct constructs an isolated invocation with no retrieval
tools and independently suppresses tool schemas at the provider adapter, while retaining the same
ADK root-agent → `LLMProvider` → llama.cpp path. Persisted history contains only native-role
user/assistant text, not ADK tool responses. The mode is request-scoped and does not add a second
conversation store or database schema.

The current implementation keeps orchestration out of the launcher and makes the
distribution/runtime/home boundaries explicit without moving core behavior into Node:

```text
POSIX entrypoint → thin Node cold bootstrap → existing Python CLI/composition root
├── Distribution bootstrap: pinned uv + managed CPython + locked dependency handoff
├── HomeCompatibilityService: descriptor/version guards + ordered migration/recovery
├── Setup Manager
│   ├── host detection (macOS arm64 implemented; other platforms unsupported)
│   ├── NativeRuntimeManager + source-controlled platform/backend manifest
│   ├── ModelManager and centralized registry
│   └── local configuration and locked web dependencies
├── Runtime Manager
│   ├── embedded SQLite and migrations
│   ├── llama-server
│   ├── FastAPI
│   └── Vue
├── real process/HTTP health checks
├── optional loopback-only ADK Web developer launcher
├── Portable Backup Manager
│   └── SQLite snapshot + Wiki/sources/datasets/config → checksummed ZIP → staged restore
└── Development Preset Manager
    └── cached synthetic source → ingestion → KnowledgeCompiler → Wiki/search/graph
```

Bootstrap acquisition, native artifact lifecycle, durable-home migration, core/application services,
and presentation are separate owners. Node does not implement knowledge, authentication, SQL, model
policy, or migration. The runtime resolver returns validated absolute handles/paths; it does not own
Wiki/source/model-selection policy. Future executable/desktop hosts must reuse the same home and
Python services rather than create another domain stack. See
[Upgrading and data preservation](upgrading.md#manual-upgrade-and-data-preservation).

macOS arm64/Metal is implemented. The manifest separately represents OS, architecture, and compute
backend and returns explicit `not-supported-yet` errors for macOS x64, Windows, and Linux. Those are
future extension boundaries, not support claims or silent CPU fallbacks.

The native Second Brain is lazy-loaded in Vue. FastAPI projects explicit relationships, wikilinks,
and relative Markdown links into a rebuildable graph index. Sigma.js renders it, Graphology owns
the client graph, and a bounded ForceAtlas2 worker performs layout without blocking the UI.

Portable backup is an application-owned boundary rather than a shell composition of component
archives. Full backup coordinates managed writers, excludes secrets and model binaries, and
atomically publishes only a validated archive. Restore never extracts untrusted paths directly
into active data: it validates checksums/schema/integrity, stages content, creates an external
recovery archive, and then activates same-filesystem replacements with rollback.
