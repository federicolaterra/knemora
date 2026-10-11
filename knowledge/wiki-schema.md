# Wiki Schema

Pages live under `wiki/entities`, `wiki/concepts`, `wiki/topics`, `wiki/syntheses`, or
`wiki/datasets`. Each page has YAML frontmatter containing `schema_version: 1`, a stable ID, page
type, aliases, topic metadata, UTC timestamps, compilation version, claims, relationships, and
provenance. Pages created before Milestone 08 without `schema_version` are read as version 1.

Claims are labelled `source_fact` or `synthesis`. Conflicting claims share a semantic `key`, use
the `disputed` status, and cross-reference each other's stable claim IDs. Relationships use
portable `[[wikilinks]]` and explicit frontmatter metadata. Generated pages must pass the backend
Wiki lint before a compilation completes.

The deterministic search index contains field-separated tokens for weighted BM25 plus normalized
identity names, topics, paths, and graph links. It is derived data and may be rebuilt from pages.
Knowledge schema changes follow the non-destructive migration policy in
`../docs/open-source/wiki.md`.
