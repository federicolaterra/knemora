# Knowledge Engine

The Knowledge Engine analyzes normalized records through `LLMProvider`, validates structured
proposals, resolves stable page identities, preserves conflicts, writes pages atomically, rebuilds
indexes, and lints the resulting Wiki. Failed compilation cannot partially replace valid knowledge.

Search combines structured identity, weighted BM25, backlinks, and bounded graph traversal. It does
not require a vector database. Dataset calculations remain allow-listed and deterministic in
Polars; the model may select or explain an operation but does not execute arbitrary code or SQL.

## Model-facing proposal contract

The default model-facing request uses the proven version-1 `KnowledgeProposal` schema through the
provider-neutral `LLMProvider`. A valid short batch therefore makes one generation request. The
only automatic retry is the existing bounded, context-safe retry when the provider explicitly
reports output truncation with `finish_reason=length`; invalid JSON, schema errors, and provider
response-contract failures fail without a second generation or a compatibility loop.

Every accepted proposal still passes the same grounding, relationship, authorization, conflict,
provenance, stable-ID, and transactional validators. A `WikiConflictError` invalidates the cached
proposal before a later user retry and records only its content-free error category; non-conflict
filesystem interruptions may still resume from the validated proposal without another model call.
Durable Markdown/frontmatter, API, database, page, claim, relationship, search, and graph contracts
are unchanged, so no data or schema migration is required.

The compact version-2 DTO and deterministic expansion adapter remain available for isolated
experiments and compatibility validation, but normal compilation does not request v2. The failed
2026-10-25 Qwen acceptance showed that v2-first behavior generated invalid TXT/PDF responses and a
terminal DOCX failure, so it must not be re-enabled without a separate controlled investigation and
matched real-model acceptance. Existing version-1 and expanded cached/in-flight proposals remain
valid; the adapter also remains able to read a version-2 payload without changing durable Wiki
formats.

The contract is independent of model name, parameter count, inference provider, and hardware. The
configured 2,048-token limit remains the conservative bootstrap ceiling and is also bounded by the
provider's effective context. A later batch may use a smaller ceiling only after a successful batch
in the same compilation supplies an observed completion size and source-character requirement. A
length result retains the existing single context-safe retry. This does not assume that a larger
model is faster or that a smaller model is less capable, and it creates no model-size-specific
pipeline.

Historical deterministic fixture measurement found that the compact-serialized relationship
fixture fell from 890 to 413 characters (53.6%), the validating response schema from 2,162 to 1,719
characters (20.5%), and the system prompt from 2,869 to 2,500 characters (12.9%). Those character
measurements did not translate into valid real-model output and are not performance claims.

## Relationship safelist

The existing structured proposal call receives Knemora's bounded relationship taxonomy. Version 1
covers family (including `sibling_of`, `parent_of`, `child_of`, `spouse_of`, and close kinship),
professional (`works_at`, `employed_by`, `colleague_of`, `founder_of`, and `owner_of`), education,
organization, project/technology, and geography relations. Known aliases are normalized to the
canonical label. Existing Wiki files and legacy relationship labels remain readable and are not
rewritten.

A safelisted edge requires exact source-record locators, two uniquely resolved page identities,
and an explicit matching statement in the source evidence. Knemora rejects or skips negated,
hypothetical, quoted, ambiguous, self-referential, unresolved, or unsupported proposals and records
a compilation warning instead. A bounded deterministic check can recover a relation omitted by the
model only when the same explicit evidence and identity checks pass. A unique full-name introduction
may support a later unambiguous first-name or singular `he`/`she` reference within the same record,
or across at most three contiguous DOCX paragraph records, two ordinal steps, and 2,000 source
characters. Cross-record windows never cross document versions, tables, non-contiguous records, or
section boundaries; an unrelated intervening paragraph breaks carryover. Relationships that need
the introduction and relation paragraphs retain both original locators in provenance. Ambiguous
short names and pronouns produce content-free rejection diagnostics rather than guessed edges.
Headings and special author markup are never required.

Historical `colleague_of` evidence is retained as a relationship because it records that the
professional connection existed; the source claim and provenance retain the past or former wording,
and the edge does not assert that the people are current colleagues. The recovery pass never derives
an edge from a filename, metadata topic, label, keyword alone, or simple co-occurrence. Friendship,
acquaintance, and shared preferences are not mandatory structural relations. Symmetric relations are
stored once in a stable direction; the graph remains a rebuildable projection of the Markdown Wiki.

## Identity-neutral analysis and stage measurement

The model-visible source JSON contains normalized evidence ordinals, locators, content, and any
deterministic dataset metadata needed for analysis. Original filenames, document/version UUIDs, and
checksums remain application-owned provenance and job metadata; they are not sent to the model.
Equivalent normalized evidence therefore produces the same model-visible request even after a
rename, new generated identity, or byte-level line-ending/BOM change that does not change the
normalized records.

Ingestion processing metadata records content-free monotonic durations for upload read, validation,
checksum, duplicate lookup, immutable storage, parsing, normalization, and total work, together with
the source-record count. Compilation reports record lock wait, batch preparation, provider attempts
and token usage, accepted proposal-contract version, response character count, output-budget basis,
validation/grounding/relationship work, merge, transactional write, index, lint, manifest/log, and
database-commit durations. Telemetry contains counts, reason codes, timings, and generated IDs
only—not source text, prompts, filenames, page titles, claims, or model output.

Changed-page transactions rebuild the lexical index and lint exactly once inside the rollback-safe
Wiki transaction. The compiler's visible `INDEXING` and `LINTING` stages reflect those authoritative
results without rerunning either whole-Wiki operation. Semantic no-op compilation still avoids page,
index, and source-manifest writes.

## Page classification

The model proposes `ENTITY` for a distinct person, organization, place, product, or project;
`CONCEPT` for an abstract principle, practice, method, or idea; `TOPIC` for a broader thematic
subject; and `SYNTHESIS` only for supported cross-fact or cross-source synthesis. `DATASET` remains
an application-created page for structured data. The backend validates the page-kind enum, retains
the established kind of a resolved page, and preserves deterministic dataset creation. A page's
`topics` metadata does not create a topic page or relationship, and the compiler does not create
pages merely to fill kind categories. If evidence does not warrant a durable page, none should be
proposed.

## Compilation timeout and model context

Structured knowledge compilation uses the configured 2,048-token maximum as its bootstrap ceiling,
bounded by effective model context, and at most one context-safe retry. Later batches can adapt from
successful measured output as described above. Each attempt has a 300-second response-read timeout
by default, separate from ordinary chat.
If a healthy model is demonstrably slower, increase only the compilation timeout in the repository
`.env`, then restart Knemora:

```dotenv
KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS=500
```

This setting changes waiting time only. It does not increase the output-token limit, model context,
or retry count, and it does not make schema-invalid output acceptable. Prefer the 300-second default
unless logs show the model is still generating valid bounded output when the deadline is reached.

Check the default model's context state with:

```bash
./knemora model info qwen3-8b-q3-k-m
```

Use the reported **last effective context** to distinguish the full 8,192-token runtime from the
automatic 4,096-token fallback. The configured preference and current memory assessment are
separate: a later start recalculates automatic admission from memory available at that time.
