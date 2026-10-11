# Upgrading

Users should be able to upgrade Knemora without destroying their knowledge. Never delete the
SQLite database, source store, or Wiki as a normal upgrade step.

## Managed updates from the stable channel

The supported stable channel is the official repository's `master` branch, identified by
`infrastructure/update-source.json`. After an installation has the managed updater, check or install
an update with:

```bash
./knemora update --check
./knemora update
./knemora --non-interactive --yes update
```

The check exits `0` when the checkout is verified current, `10` when an update is available, and `2`
when the check is unavailable or installation is blocked. Automatic installation is limited to a
clean native macOS Apple Silicon `master` checkout that is strictly behind the official branch and
whose running commit matches checkout `HEAD`. Development, custom, detached, dirty, ahead, diverged,
and running/checkout-mismatch states remain check-only; Knemora never discards edits, switches a
development branch, force-checks out, or silently stashes changes.

Update checks may contact GitHub and update Git fetch metadata plus the namespaced
`refs/knemora/updates/master` ref. They do not change application files, install dependencies,
migrate data, stop services, or send documents, prompts, Wiki content, conversations, credentials,
model data, or private knowledge. Login-triggered checks are limited to one successful attempt per
24 hours and can be disabled with `KNEMORA_UPDATE_CHECK_ENABLED=false`.

For an approved update, the independent worker pins the selected commit, prepares a sibling
checkout, stops managed writers, creates and validates a portable recovery backup, activates the
prepared checkout, runs the existing setup/home/Alembic authorities, restarts the previous mode,
and verifies service readiness at the pinned commit. Status is stored under
`KNEMORA_HOME/runtime/updates/`; use `./knemora status` and `./knemora logs` to inspect failures.
Before activation, Knemora attempts to restore the prior service state automatically. After
activation or migration begins, keep services stopped and recover from the recorded portable
archive with `./knemora restore /absolute/path/to/recovery-backup.zip`, followed by
`./knemora setup` and `./knemora start`; do not run retained older code against migrated data.

## Manual upgrade and data preservation

Before upgrading, run `./knemora backup` and confirm it appears as valid in `./knemora backups`.
The portable archive covers the database, sources, Wiki, datasets, and safe model metadata. It
deliberately excludes `.env` secrets and GGUF files; preserve credentials separately in an
appropriate secret store. Stop Knemora, pull the new source, review the changelog and configuration,
then run `./knemora setup` followed by `./knemora start`. Setup validates/registers the durable home,
repairs managed components, and applies Alembic. Developers should additionally run `make check`.

`config/home.json` owns durable-home compatibility independently from product,
Alembic, backup/component-format, and native-runtime versions. A recognized older installation is
registered or migrated under the shared home-operation lock. Unknown, corrupt, or newer state stops
before writes. Migration steps must prepare required recovery snapshots, journal progress, verify
affected resources, and advance the descriptor only after success. Do not delete/recreate a home or
downgrade its metadata to force compatibility; follow the reported setup and recovery guidance.

Managed-runtime upgrades do not move existing data. They preserve explicit external overrides,
`.env`, model registry/weights, SQLite, Wiki, immutable sources, datasets, sessions, backup settings,
and backups, and they do not uninstall or modify unrelated system tools.

Pre-Knemora environment variables are accepted as deprecated fallbacks; `KNEMORA_*` wins when both
forms are set. Existing legacy Wiki metadata is copied once to `.knemora` while the original is
preserved. The legacy browser token is migrated locally, and the former Python package remains an
import-only shim. Older installations using PostgreSQL must use the explicit
`./knemora migrate-postgresql --source-url ...` workflow; the source remains a rollback surface
until acceptance is complete.
Fresh state uses Knemora identifiers and `~/.knemora/data/knemora.db`. Compatibility removals
require warning, documentation, and a future major release.

The readable-source-name maintenance transition keeps home schema 1 because top-level home roles do
not change. Alembic adds durable deletion jobs, then API startup migrates legacy `original.<ext>`
leaves through per-version journals and checksum verification. Do not rename originals manually;
restart after resolving the reported filesystem problem and the idempotent migration will resume.

The current alpha intentionally defers persistent workspaces. Existing records remain installation/user
scoped. A future workspace migration should create one `default` workspace transactionally,
backfill all owned records, verify counts and constraints, and only then make workspace references
non-null.
