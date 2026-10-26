# Knemora API

The API is the application boundary for Knemora. It provides local LLM/ADK chat with explicitly
opted-in bounded public search,
provenance-preserving ingestion/compilation, Milestone 05 Wiki retrieval, and deterministic
CSV/XLSX analysis.

```bash
cd apps/api
uv sync --frozen --dev
uv run --frozen alembic upgrade head
uv run uvicorn app.main:app --reload
uv run pytest
```

`apps/api` is the Python project and required working directory for migrations. Alembic is a
direct locked runtime dependency; launcher setup verifies its executable before database startup.

Primary endpoints:

- `GET /api/v1/health` — process liveness;
- `GET /api/v1/ready` — SQLite and llama.cpp readiness;
- `GET /api/v1/system` — product identity, versions, capabilities, and telemetry state;
- `GET /api/v1/system/capabilities` — frontend feature-discovery contract;
- `POST /api/v1/conversations` — create a local conversation;
- `GET /api/v1/conversations` — latest eight summaries, or a server-paginated/searchable page when
  `page` is supplied (15 per page by default);
- `GET /api/v1/conversations/{id}` — owner-scoped conversation detail;
- `PATCH /api/v1/conversations/{id}` — validate and persist an owner-scoped title rename;
- `DELETE /api/v1/conversations/{id}` — delete one owner-scoped conversation and its messages;
- `POST /api/v1/conversations/{id}/messages` — persisted ADK chat;
- `POST /api/v1/conversations/{id}/messages/stream` — structured SSE events.
- `POST /api/v1/documents` — multipart upload and synchronous ingestion;
- `GET /api/v1/documents` — active owner-scoped source list; paginated requests default to 10 and
  support filename, source-kind, effective processing-status, and canonical file-type filters;
- `GET /api/v1/ingestion-jobs/{id}` — observe persisted job state;
- `POST /api/v1/ingestion-jobs/{id}/retry` — retry failed or interrupted processing.
- `POST /api/v1/document-versions/{id}/compile` — compile a normalized version into the Wiki;
- `GET /api/v1/knowledge-compilation-jobs/{id}` — observe the report and retry state;
- `GET /api/v1/wiki/pages` — list typed Wiki pages;
- `GET /api/v1/wiki/page-index` — server-paginated Wiki index with query and page-kind filters;
- `GET /api/v1/wiki/pages/{id-or-name}` — read by stable ID, title, or alias;
- `GET /api/v1/wiki/pages/{id-or-name}/backlinks` — list incoming links;
- `GET /api/v1/wiki/pages/{id-or-name}/related` — bounded Wiki graph traversal;
- `GET /api/v1/wiki/search` — identity, structured-filter, and weighted BM25 search;
- `GET /api/v1/wiki/graph` — revision-aware global graph or a one-to-three-hop local graph;
- `GET /api/v1/wiki/files/{path}` — safe native read-only detail for Markdown pages without a
  generated Wiki record;
- `GET /api/v1/source-records/{id}` — owner-scoped bounded source evidence;
- `POST /api/v1/datasets/{document-version-id}/analyze` — deterministic Polars analysis and
  chart-ready series;
- `GET /api/v1/datasets` — authorized dataset identities, defaulting to 5 per page;
- `GET /api/v1/datasets/{document-version-id}` — owner-scoped dataset list detail;
- `POST /api/v1/wiki/rebuild-index` — rebuild deterministic lexical/index files;
- `GET /api/v1/wiki/lint` — report schema, link, and orphan health.

Agent behavior lives in `knowledge_agent/`. Wiki executions have exactly the bounded local tools
and never receive public-search authority. Public search is a Direct-only application step whose
request-level `web_search` value may override the `.env` startup default. Every enabled turn derives
a restricted query only from the current message, makes one bounded DDGS/DuckDuckGo attempt, and
returns untrusted snippets and safe URLs to that invocation. `GET /api/v1/chat/capabilities`
reports the runtime identity, safe startup defaults, and selected-model control support without
private paths or secrets. The optional
repository-root `./knemora --dev adk-web` command starts the official ADK developer UI with this
same package and environment. Tests inject fake LLM/search providers and never require the real
model or internet. Implementation and contributor guidance is in the public
[development guide](../../docs/open-source/development.md).

SQLite remains authoritative for chat history. Each request reconstructs the fresh ADK session
from owner-scoped persisted messages with native user/assistant roles, then appends the current
user message once. Context budgeting removes the oldest complete turns first and retains the
current turn, system policy, and recent continuity. Ordinary conversation uses automatic tool
selection; organization-specific questions and co-referential follow-ups enter bounded Wiki
retrieval. Replies follow the current user's language by default, explicit language requests win,
and language-neutral follow-ups inherit the established conversation language when possible.
Simple two-operand expressions and operator-led arithmetic follow-ups are evaluated with bounded
decimal operations. Follow-ups accept a bare or uniquely emphasized preceding numeric answer; they
do not execute model-generated code or `eval`.

The message endpoints also accept optional `thinking_mode: fast | deep` and
`web_search: boolean`. Unsupported thinking modes and Wiki+Web combinations fail with HTTP 422.
Assistant rows persist actual execution metadata in the existing JSON metadata column, including
model, response mode, thinking capability/mode, and distinct Web request/attempt/success/outcome
fields. No migration or separate chat store is required; legacy rows serialize execution metadata
as null.
