# Portable backup and restore

Knemora writes versioned ZIP archives to `~/Documents/Knemora/Backups/` by default. This location
is deliberately outside `~/.knemora`; Knemora never silently redirects a failed backup into the
application-data directory. Inspect or change the persistent destination with:

```bash
./knemora config backup-path
./knemora config backup-path ~/Dropbox/Knemora
```

An unavailable `/Volumes/...` destination or a permission failure is reported without creating an
archive elsewhere.

## Create and inspect backups

```bash
./knemora backup                 # full backup (default)
./knemora backup --full
./knemora backup --db-only
./knemora backup --path ~/Dropbox/Knemora
./knemora backups
```

`--path` applies to that backup and becomes the default for subsequent commands. A full backup
briefly pauses managed Knemora writers, snapshots SQLite with its online backup API, archives the
Wiki, immutable source files and attachments, dataset artifacts, and portable model configuration,
then resumes the previous runtime profile. Database-only backup can run while SQLite is in WAL mode.

Archives use the ID `knemora-backup-YYYY-MM-DD-HHMMSS-TYPE` and this layout:

```text
database/knemora.db
knowledge/...
sources/...
datasets/...
config/model-selection.json
config/models.json
manifest.json
```

The manifest records backup-format, Knemora, application-home, SQLite schema, Alembic, and Knowledge
schema versions; UTC creation time; type; selected model metadata; and a size/SHA-256 inventory for
every archived file. Legacy format-1 archives without home fields are recognized as the schema-1
baseline; a newer unsupported home fails validation before live replacement. Archives are built
under a temporary name, fully validated, and atomically promoted. GGUF files, `.env`, credentials,
logs, `bin/`, managed Python, caches/runtime provenance, Development demo data, and rebuildable Wiki
search and graph indexes are excluded. Keep backup media encrypted because source documents and
SQLite remain sensitive.

`--db-only` protects relational records only. It does not include Wiki notes, original documents,
attachments, dataset files, or portable model configuration.

## Restore

Stop untracked writers before restoring. The product CLI stops managed services automatically:

```bash
./knemora restore knemora-backup-2026-10-05-120000-full
./knemora restore /path/copied-from-another-computer.zip
```

Restore validates entry paths, rejects links/traversal, verifies the complete checksum inventory,
checks home/component/SQLite compatibility and SQLite integrity, stages all files, and
validates/rebuilds the Wiki before replacing active data. Migration, restore, and runtime activation
share the application-home operation lock. Restore first creates a full recovery archive in the configured backup
directory. Activation uses same-filesystem staging and rolls back the current database and file
trees if replacement fails. The source archive is never deleted and services remain stopped for
review.

A database-only restore deliberately leaves current Wiki/source files in place and may therefore
create a historical mismatch. It is refused when those files exist unless explicitly acknowledged:

```bash
./knemora --yes restore DATABASE_BACKUP_ID --allow-db-only
```

On another supported computer, run `./knemora setup`, copy the archive, and restore it by explicit
path. Model binaries are not portable-backup contents: the completion report names the archived
model ID, and `./knemora setup --model MODEL_ID` can select/download a registered model when
available. Machine-specific model paths are removed from the archive; the destination's active
model selection is not overwritten with an unusable path.

After restore, run `./knemora start` and verify sign-in, documents, original downloads, Knowledge
links/search, a cited answer, datasets, conversations, settings, and audit history.
The restored database replaces local account records and password hashes, so credentials from the
backup are authoritative. The destination setup password is no longer valid unless it happens to
match a restored account; keep source credentials available or reset a restored account after
sign-in.

Backups are independent historical archives. Source deletion never edits an existing archive; a new
full backup made after completed cleanup omits the deleted source and its active knowledge. Explicitly
restoring an older archive intentionally restores that archive's earlier state. Legacy archives with
`original.<ext>` remain supported and migrate normally after restore.

## Delete a backup

```bash
./knemora backup delete BACKUP_ID
./knemora --yes backup delete BACKUP_ID  # automation
```

Deletion requires confirmation and accepts only an ID inside the configured backup directory; it
does not accept an arbitrary archive path.

The compatibility Make targets call this same implementation: `make backup`, `make backup-db`, and
`make restore BACKUP_ARCHIVE=/path/or/id`. There is no separate component/tar backup system.
