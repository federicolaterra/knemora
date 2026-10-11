# Ingestion and provenance

Knemora accepts PDF, TXT, Markdown, DOCX, CSV, and XLSX. It validates size, extension, signatures,
archive paths, and filenames; assigns stable document/version identities; stores originals at
generated content-addressed paths; and marks original bytes read-only. Uploaded content is
untrusted evidence and cannot change application policy.

Normalized records retain parser identity and the strongest available page, section, paragraph,
sheet, row, or range locator. Every compiled claim links back to its immutable source version and
checksum. Product renaming never rewrites source bytes or checksum identity.

Generated date/document/version directories remain the storage identity boundary. The original leaf
uses a readable, portable normalization of the uploaded name while the exact name remains separate
metadata. Legacy `original.<ext>` leaves migrate idempotently with a checksum-backed journal.

Deleting a document immediately tombstones all its versions and queues durable local cleanup. Active
source, dataset, Wiki, search, graph, and answer tools exclude tombstoned lineage even if cleanup
fails. Cleanup preserves shared facts backed by other sources and removes deleted-only evidence,
derived pages, source directories, and operational source metadata. Retry resumes the persisted
stage; it does not reactivate the source.
