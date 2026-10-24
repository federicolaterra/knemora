# Knowledge Engine

The Knowledge Engine analyzes normalized records through `LLMProvider`, validates structured
proposals, resolves stable page identities, preserves conflicts, writes pages atomically, rebuilds
indexes, and lints the resulting Wiki. Failed compilation cannot partially replace valid knowledge.

Search combines structured identity, weighted BM25, backlinks, and bounded graph traversal. It does
not require a vector database. Dataset calculations remain allow-listed and deterministic in
Polars; the model may select or explain an operation but does not execute arbitrary code or SQL.

## Relationship safelist

The existing structured proposal call receives Knemora's bounded relationship taxonomy. Version 1
covers family (including `sibling_of`, `parent_of`, `child_of`, `spouse_of`, and close kinship),
professional (`works_at`, `employed_by`, `colleague_of`, `founder_of`, and `owner_of`), education,
organization, project/technology, and geography relations. Known aliases are normalized to the
canonical label. Existing Wiki files and legacy relationship labels remain readable and are not
rewritten.

A safelisted edge requires an exact source-record locator, two uniquely resolved page identities,
and an explicit matching statement in the same source sentence. Knemora rejects or skips negated,
hypothetical, quoted, ambiguous, self-referential, unresolved, or unsupported proposals and records
a compilation warning instead. A bounded deterministic check can recover a relation omitted by the
model only when the same explicit evidence and identity checks pass. Within one source record, a
unique full-name introduction may support a later unambiguous first-name reference, and a nearby
singular `he` or `she` may resolve only when the preceding person reference is unique. Ambiguous
short names and pronouns produce content-free rejection diagnostics rather than guessed edges.
Headings and special author markup are never required.

Historical `colleague_of` evidence is retained as a relationship because it records that the
professional connection existed; the source claim and provenance retain the past or former wording,
and the edge does not assert that the people are current colleagues. The recovery pass never derives
an edge from a filename, metadata topic, label, keyword alone, or simple co-occurrence. Friendship,
acquaintance, and shared preferences are not mandatory structural relations. Symmetric relations are
stored once in a stable direction; the graph remains a rebuildable projection of the Markdown Wiki.

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

Structured knowledge compilation uses a 2,048-token first attempt and at most one context-safe
retry. Each attempt has a 300-second response-read timeout by default, separate from ordinary chat.
If a healthy model is demonstrably slower, increase only the compilation timeout in the repository
`.env`, then restart Knemora:

```dotenv
KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS=500
```

This setting changes waiting time only. It does not increase the output-token limit, model context,
or retry count, and it does not make truncated or schema-invalid output acceptable. Prefer the
300-second default unless logs show the model is still generating valid bounded output when the
deadline is reached.

Check the default model's context state with:

```bash
./knemora model info qwen3-8b-q3-k-m
```

Use the reported **last effective context** to distinguish the full 8,192-token runtime from the
automatic 4,096-token fallback. The configured preference and current memory assessment are
separate: a later start recalculates automatic admission from memory available at that time.
