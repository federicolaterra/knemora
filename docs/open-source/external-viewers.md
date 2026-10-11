# Optional external Markdown viewers

Knemora's native **Second Brain** and **Knowledge** pages are the supported graph and detail
experience. No external desktop application, plugin, or browser extension is required for setup,
startup, ingestion, search, graph exploration, or source-grounded chat.

The authoritative Wiki remains portable Markdown under the configured knowledge root:

```text
knowledge/
├── wiki/
│   ├── entities/
│   ├── concepts/
│   ├── topics/
│   ├── syntheses/
│   └── datasets/
├── sources/
├── index.md
├── wiki-purpose.md
├── wiki-schema.md
└── wiki-log.md
```

Generated pages use YAML frontmatter, stable IDs, standard Markdown, `[[Page]]`,
`[[Page|Label]]`, heading references, and relative Markdown links. Attachments and immutable source
files keep their existing locations. `.knemora/` contains rebuildable application indexes and is
not part of the portable content contract.

Users may open a copy or the live Wiki with Obsidian or another compatible Markdown editor/viewer.
Knemora does not install or configure those tools, depend on their plugin APIs, or guarantee how a
third-party graph interprets frontmatter, aliases, duplicate filenames, or link ambiguity. Do not
delete or rewrite generated IDs, provenance, claims, or relationship metadata. External edits are
noticed through the graph signature on the next graph request; use **Refresh** after editing when
immediate confirmation matters, and run Wiki lint before relying on structural changes.

Unprocessed captures should enter through Knemora ingestion so immutable originals and provenance
are preserved. A future Knemora-native clipping extension is planned separately and is not part of
Milestone 08.4.
