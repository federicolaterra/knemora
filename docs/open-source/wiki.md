# Second Brain and Wiki schema

The Wiki is plain Markdown with YAML frontmatter, wikilinks, and relative Markdown links. It
contains entities, concepts, topics, syntheses, datasets, source manifests, an append-only
compilation log, and rebuildable lexical and graph indexes. Knemora's native **Second Brain** is the
supported graph viewer; see [optional external viewers](external-viewers.md) for portability.

New pages include `schema_version: 1`. The internal metadata config and state also track their
schema versions independently from the application and database. Existing pages without the field
load as version 1.

Future Wiki migrations must be versioned, deterministic, backup-aware, idempotent, and tested on a
copy before modifying a live vault. They must preserve stable page IDs, source identities,
provenance, wikilinks, human edits where supported, and an auditable migration record. Deleting and
rebuilding a user's Second Brain is not an upgrade strategy.

## Native graph behavior

`GET /api/v1/wiki/graph` serves every eligible page, resolved explicit edges, unresolved and
ambiguous counts, totals, truncation, and revision freshness. With `root` and `depth=1|2|3`, it
returns an undirected neighborhood traversal while retaining each edge's original direction.

The resolver supports page titles, aliases, unique basenames, relative `.md` links, wikilink
labels, and heading references. It ignores fenced/inline code, images, attachments, and external
URLs. Duplicate basenames or aliases are diagnostics and never resolve arbitrarily. Generated
pages open Wiki Detail by stable ID; other Markdown pages under `knowledge/wiki/` use a traversal-
protected read-only native view.

Compilation's existing index rebuild increments the Wiki revision. The graph cache also compares a
safe Markdown path/mtime/size signature, so supported external renames, edits, and deletions are
picked up on a later graph request. **Refresh** forces reindexing and displays the resulting time
and revision. Defaults bound responses to 2,000 nodes and 8,000 edges; configure
`KNEMORA_WIKI_GRAPH_MAX_NODES` and `KNEMORA_WIKI_GRAPH_MAX_EDGES` when local hardware measurements
justify different limits.

## Troubleshooting

- If the canvas cannot create WebGL contexts, use the page-list fallback; detail navigation and
  local root selection remain available outside the canvas.
- If an external edit is not visible, choose **Refresh** and inspect the indexed timestamp and Wiki
  revision shown below the graph.
- Unresolved links usually name missing pages; ambiguous links usually mean duplicate basenames,
  titles, or aliases. Knemora deliberately does not guess.
- Layout runs in a worker for a bounded interval (at most 2.5 seconds in the current UI). **Reset
  layout** starts a new bounded run; dragging a node stops the active run so it does not fight the
  user.
