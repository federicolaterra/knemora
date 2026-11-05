# Knowledge Updates & Recompilation

Knemora separates source processing, AI (SI) analysis, Wiki updates, and derived-index work. These
steps are related, but they are not the same operation. Reprocessing one source does **not** send
the entire Wiki to the model or rewrite every Wiki page. It reparses that source's immutable bytes,
runs knowledge analysis for its normalized records again, and merges the accepted proposal into
only the pages it names. If any page changes, Knemora then rebuilds the whole lexical search index;
the native graph projection is rebuilt lazily on a later graph request.

> [!NOTE]
> Knemora's Knowledge Engine is actively evolving. Upcoming releases will focus on strengthening knowledge updates and recompilation, improving consistency and reliability, and introducing more advanced document versioning and fact lifecycle management.

## Compile, reprocess, and upload are different

| Action | Source bytes | AI (SI) analysis | Wiki effect |
| --- | --- | --- | --- |
| Compile an already completed version | Unchanged | Reuses the completed compilation job; no new model call | No write |
| **Reprocess source** in Documents | Verifies and reparses the same immutable version | Runs again after invalidating the cached proposal | Additive merge into named pages; an equivalent proposal is a semantic no-op |
| Upload a changed file | Creates a new immutable source identity in the current UI | Runs for the new source | Merges new claims and provenance with existing pages |
| Delete a source | Tombstones the whole document immediately | No model call | Asynchronous reconciliation removes that document's lineage and rebuilds derived state |

Reprocessing is useful after parser or compiler improvements, or when a previous compilation needs
another model attempt. It is not in-place source editing and cannot change the stored original.
There is no separate public `force=true` compilation option. The product's force-like workflow is
**Reprocess source**, followed by compilation.

## Source versions and changed documents

Original files are immutable. The normal Documents upload creates a new document when the bytes are
new and returns the existing version when the owner uploads identical bytes again. The HTTP upload
API also accepts a multipart `document_id` field to create version 2, 3, and later under an existing
document. The current UI does not expose that version-linking field.

Linked versions preserve their relationship for audit and storage, but they are all active evidence.
A newer version does not automatically supersede, deactivate, or retract claims from an older
version. Whole-document deletion removes every linked version; there is no per-version withdrawal
action in the product today.

For a changed file in the current UI:

1. Open **Documents** and upload the revised file. Knemora stores and compiles it as a new immutable
   source.
2. Review the resulting page claims and source references in **Knowledge**. A correction may appear
   beside the previous claim as a dispute.
3. If the older source should no longer contribute, use **Delete source and update knowledge** for
   that older document. Deletion is whole-document and asynchronous, so confirm that you selected
   the intended source.

Do not use **Reprocess source** when the bytes themselves changed: reprocess always reads the
existing immutable original.

## What Knemora recalculates

### Model analysis

New sources and reprocessed sources are analyzed in bounded normalized-record batches. A completed
compilation request is cached by document-version job and returns without invoking the model. A
reprocess clears that cached proposal, so the next compilation invokes the model again. A failed
non-conflict filesystem write may reuse its already validated proposal on retry, while invalid
model output and Wiki conflicts require fresh analysis.

### Wiki pages and provenance

The compiler resolves stable page identities, validates cited record ordinals, and merges claims and
relationships. It writes only pages whose serialized semantic content changed; an exact no-op keeps
page IDs, claim IDs, timestamps, and bytes stable. The same normalized fact and classification from
another source becomes one claim with additional provenance. A different fact with the same claim
key is retained alongside the earlier claim and both are marked disputed.

Merging is additive during compilation. A later proposal that omits an older claim does not retract
that claim or remove its provenance. Source deletion is the supported operation that subtracts
lineage.

### Search index, source manifest, and graph

- If one or more pages change, Knemora writes those pages transactionally, scans the full Wiki to
  rebuild the lexical search index and Markdown index, increments the Wiki revision, and lints the
  full Wiki once.
- If the merge is an exact no-op, it does not rewrite pages, the search index, Wiki revision, or that
  source's manifest.
- A changed compilation writes the manifest for that source version and records the compilation.
- The native graph is a rebuildable cache. Compilation does not eagerly rebuild it; the next graph
  request detects the Wiki revision or file signature and rebuilds when needed. **Refresh** in the
  Second Brain forces that graph reindex.

This means page selection is incremental, but the lexical index and lint pass are whole-Wiki work.
Knemora is not fully incremental end to end.

## Corrections, removed facts, and conflicting sources

Suppose an original source says, “Acme Corporation has an office in Rome,” and a revised source says
the office is in Milan.

- If both sources or linked versions remain active, Knemora retains both claims with their respective
  provenance and marks the same-key claims disputed. It does not choose a winner.
- If a later version simply omits the office statement, the Rome or Milan claims remain searchable
  and citable because omission is not a retraction signal.
- If an independent source repeats the exact Rome fact, its provenance is added to the existing Rome
  claim rather than creating a duplicate.
- Deleting one contributing document removes only that document's provenance. A shared claim remains
  when another active source still supports it; claims and pages with no surviving support are
  removed.

AI (SI) Chat receives the active, authorized claims and their conflict state. It can expose competing
evidence, but the provenance system does not certify that a source or model conclusion is factually
correct.

## Safeguards and limits

For an existing page, every source-record ordinal cited by a proposed claim or relationship must
independently name the page title or an established alias. Relationship proposals also pass bounded
identity and evidence checks. These controls prevent one record in a batch from authorizing writes
to an unrelated page and preserve unrelated contributions during ordinary merges.

They do not establish truth, infer which conflicting source is newer or authoritative, or convert a
missing statement into a retraction. Fact retirement, version supersession, and dependency-aware
incremental recompilation are not supported today.

Page, search-index, and revision writes are rollback-safe as one Wiki transaction. Compilation job,
source-manifest, and log persistence occur afterward, so the complete filesystem/database workflow
is not one cross-store transaction. Retry a failed job and review its Wiki state; do not assume every
failure happened before all Wiki files were touched.

## Troubleshooting

- **Reprocess did not change a page:** the new proposal may have been semantically equivalent. Check
  the compilation attempt count and page source references.
- **An old fact still appears after a revised upload:** uploads and linked versions are additive. The
  older active source must be deleted to subtract its lineage.
- **A page shows two disputed claims:** Knemora preserved conflicting source-backed statements. Review
  their source links rather than treating page order as authority.
- **Search changed but the graph looks stale:** reopen the Second Brain or use **Refresh** so the lazy
  graph cache is rebuilt.
- **Deletion is still running:** Documents shows the durable deletion operation. Failed cleanup stays
  tombstoned and can be retried without reactivating the source.

See [Ingestion & Provenance](ingestion.md) for immutable sources and deletion,
[Knowledge Engine](knowledge-engine.md) for proposal validation and merging,
[Second Brain & Wiki](wiki.md) for the Markdown and graph projections, and
[AI (SI) Chat modes](chat.md) for how active Wiki evidence reaches answers.
