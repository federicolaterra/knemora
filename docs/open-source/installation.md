# Installation

## Supported zero-configuration path

The current automated bootstrap supports native macOS on Apple Silicon with Metal. Install Node.js
24+ with npm from [nodejs.org](https://nodejs.org/) or another trusted distribution. Git is needed
only for the `git clone` acquisition route. Homebrew, global Python/uv/llama.cpp, Docker, and
PostgreSQL are not required. Knemora does not install Node or perform privileged setup. Keep at
least 7 GB free for the default model, downloads/staging, runtime components, and application data.

```bash
./knemora
```

On a first interactive run, the monochrome welcome screen offers normal start or the Development
demo and asks for confirmation. Non-interactive automation never prompts:

```bash
./knemora --non-interactive --yes --no-open setup
./knemora --non-interactive --no-open start
```

The shell entrypoint checks Node/npm and delegates to a thin ordinary-JavaScript bootstrap before
Python is available. It downloads the pinned uv binary without executing a remote installer,
verifies size/SHA-256, provisions managed CPython, and performs a frozen dependency sync. Setup
then checks the platform, RAM, and disk; installs the pinned complete llama.cpp payload; installs
locked frontend dependencies; safely downloads and
checksum-validates the selected GGUF; creates minimum local configuration; initializes embedded
SQLite; applies migrations; and records completion. Re-running setup skips valid work and preserves
existing configuration and data. Fresh setup generates a strong local administrator password in
the repository `.env` (mode `0600`) and never prints it; use the stored administrator email/password
for browser sign-in.

Python dependencies are installed from committed `apps/api/uv.lock`; compatible macOS arm64 wheels
were verified without a compiler. Managed uv/Python live below `KNEMORA_HOME/bin` and
`KNEMORA_HOME/python`; the checkout-local `apps/api/.venv` is recreated when its managed interpreter
or lock fingerprint changes. Models and durable data are not part of that rebuild. A failed setup
reports its phase without replacing an active verified runtime or user data.

To rename an existing checkout safely, first create an independent repository backup, confirm the
destination does not exist, and stop managed services. Move the directory from its parent and then
run setup from the new path:

```bash
./knemora stop
cd ..
mv OLD_DIRECTORY knemora
cd knemora
./knemora setup
```

Do not move or delete `~/.knemora`; it contains the database, Wiki, immutable sources, models, and
other persistent local state. Existing `.env` and ignored local files move with the checkout.

The default registry entry is `qwen3-8b-q3-k-m`: the 4.12 GB
`qwen3-8b-Q3_K_M.gguf` from `ISTA-DASLab/Qwen3-8B-GGUF-GSQ`.
Its published SHA-256 is pinned in the registry. Downloads use a `.partial` path, resume where the
server permits, and are promoted only after full checksum validation. Model licenses remain
separate from Knemora's MIT license.

```bash
./knemora models
./knemora setup --model qwen3-8b-q3-k-m
```

Model hardware guidance is advisory. Explicit supported selections are respected and update only
Knemora-owned runtime selection metadata.

To use an external Hugging Face GGUF, import it before setup. The reference is intentionally
explicit and resolves one artifact; it never causes repository code to execute:

```bash
# Syntax example; confirm the upstream repository, artifact, and license yourself.
./knemora load --model hf:owner/Example-GGUF:Q3_K_M
./knemora models
./knemora setup --model example-q3-k-m
```

Imported metadata persists in `~/.knemora/config/models.json`, while managed weights live under
`~/.knemora/models`. Custom entries are unverified by Knemora even after their checksum and GGUF
container validate. Listing and selection use local state and do not contact Hugging Face. Private
or gated repositories may use the standard `HF_TOKEN` environment variable; Knemora uses it only
as an HTTPS authorization header and never writes it to the registry. For non-interactive import,
use `./knemora --non-interactive --yes load --model hf:...`.

To reclaim model storage and optionally remove its registry entry, use the two-stage lifecycle:

```bash
./knemora model remove <id>
./knemora model remove <id> registry
```

Running the registry command while artifact data remains fails with these ordered instructions.
Curated registry removal is a local suppression in `models.json`, not an edit to application code;
the required default model definition remains protected.

## Application data and lifecycle

Knemora stores application state under `~/.knemora/` by default: SQLite at
`data/knemora.db`, models, Wiki, immutable sources, datasets, logs, protected configuration, runtime
PID files, and isolated demo assets. Managed uv/llama.cpp are under `bin/`, managed Python under
`python/`, and downloads/package caches under `cache/`. Override the root with `KNEMORA_HOME` or set
an explicit file-backed `KNEMORA_DATABASE_URL`. Paths with spaces are supported.

`config/home.json` is the durable descriptor (format 1/home schema 1). Existing recognized homes
receive a metadata-only baseline registration that preserves all content. A newer, corrupt, or
unknown layout is never treated as empty; setup stops before mutation. `config/runtime.json` records
replaceable component provenance and is deliberately separate from durable-home compatibility.
See [Upgrading and data preservation](upgrading.md#manual-upgrade-and-data-preservation).

```bash
./knemora start
./knemora start --with-presets
./knemora start --yes-web-search
./knemora start --with-presets --yes-web-search
./knemora stop
./knemora restart
./knemora status
./knemora logs --follow
./knemora doctor
```

Readiness requires SQLite, llama.cpp, FastAPI, and Vue health. Managed HTTP services and
inference bind to loopback by default. Process IDs refer to the actual long-running services, and
mode changes restart them with the requested normal or Development configuration. Port conflicts,
exited managed processes, or an API serving the wrong mode prevent `READY`. `stop` stops processes
without removing the database, Wiki pages, sources, datasets, models, or configuration. Before
returning, `stop` verifies the managed llama.cpp, FastAPI, and Vue services are no longer running.
A failure names any service that remained available.

Normal mode uses the normal database, source store, and Wiki. Development mode uses a dedicated
SQLite database and `~/.knemora/demo/development` source/Wiki roots all the way through the
API and Vue UI. Valid existing presets are reused and missing assets are created; inconsistent
existing assets fail validation before `READY`. Startup prints a stage progress bar, and cached
preset validation parses the vault once instead of recompiling it. The Development API/UI is read-only for upload,
ingestion changes, compilation, and dataset analysis.

Use `./knemora delete --presets` (or `./knemora --yes delete --presets`) to remove only the isolated
preset files and `knemora_demo` database. It preserves the model and all normal user data.

Setup and startup open only Knemora's local web interface. They do not install, detect, configure,
or launch a separate knowledge application. The native **Second Brain** provides global and local
graphs over the portable Wiki. See [optional external viewers](external-viewers.md) when manually
opening the Markdown files elsewhere.

After software and model assets are installed, private Wiki, dataset, and local chat operation
require no hosted service. Public web search is disabled by default. Starting with
`--yes-web-search` enables the optional DDGS-backed integration for that runtime profile, but a
chat turn must still explicitly request public web results before only that public query is sent to
the external provider. Starting again without the flag restores the offline default.

## Optional ADK developer playground

With the configured local model server running, developers may start the official Google ADK Web
interface without changing the normal product runtime:

```bash
./knemora --dev adk-web
```

It imports Knemora's existing `knowledge_agent` through `apps/api/.venv`, binds to `127.0.0.1`,
and prints its actual URL. The launcher prefers a free, unreserved port 8080, otherwise scans
through 8090; it reports an existing Knemora ADK Web URL on repeated launch and never stops another
listener. Use its own chat for Events and Trace, because normal Knemora UI requests do not
automatically enter this separate development server. Stop it with Ctrl+C. Do not expose it to an
untrusted network; normal `./knemora start` never launches it.

## Manual fallback

Linux and Windows zero-config adapters are future extension points and are not claimed as supported
in this release. Install Python 3.12+, `uv`, Node.js 24, and npm. From the
repository root:

```bash
cp .env.example .env
# Set a unique KNEMORA_BOOTSTRAP_ADMIN_PASSWORD in .env.
make setup
make db-migrate
make api-dev
```

Run `make web-dev` in another terminal and open `http://localhost:5173`. Fresh installs use the
Knemora database settings in `.env.example`. `make check` verifies formatting, lint, types, tests,
and the production frontend build.

Local inference is optional for installation verification but required for real chat. Configure it
using `local-inference.md`. No AWS, hosted model API, object store, vector database, Stripe account,
or telemetry service is required.

## Failure, recovery, and uninstall

Run `./knemora doctor` and `./knemora logs` first. Runtime downloads use installer-owned partial
files and a failed or checksum-mismatched artifact never replaces the active installation. The
first macOS validation of a newly staged signed runtime may take tens of seconds; later prepared
starts are much faster. A failed service start does not print `READY`. Correct the exact Node,
home-compatibility, runtime-integrity, port, model, or configuration error and rerun setup/start.

Use the guarded uninstall command rather than manually deleting paths:

```bash
./knemora uninstall
./knemora uninstall --preserve-data
```

Both forms print the absolute repository and configured application-data paths, warn that
uncommitted and untracked repository files are included, and require an explicit `y` or `yes` in
an interactive terminal. Empty input, `n`/`no`, EOF, interruption, non-interactive execution, and
the global `--yes` flag cannot authorize uninstall. The launcher stops only its PID-managed
services and aborts before deletion if safe shutdown fails.

Plain `uninstall` removes the repository and the complete configured runtime directory, normally
`~/.knemora`, including its database, configuration, models, Wiki, immutable sources, datasets,
logs, and demo data. `uninstall --preserve-data` removes only the repository. It refuses when the
data directory is inside the repository because preservation would be impossible; first move the
data through `KNEMORA_HOME`. Shared dependencies, independently located backups and user files,
and external symlink targets are never uninstalled.

After `--preserve-data`, clone Knemora again, keep `KNEMORA_HOME` pointed at the retained directory,
and run `./knemora setup` followed by `./knemora start`. Setup rebuilds checkout-bound dependencies
and reuses the existing application data.

Before uninstalling or moving computers, create and validate a portable archive:

```bash
./knemora backup
./knemora backups
```

The default is `~/Documents/Knemora/Backups/`; use `./knemora backup --path /other/location` to
persist another destination. On the new computer, run setup and then restore by explicit archive
path. GGUF files are excluded and may need to be downloaded or selected again. See
[Backup and restore](backup-and-restore.md).

## Migrating an existing PostgreSQL installation

Stop application writers and provide the source URL explicitly; the command never assumes a local
container and never changes or deletes the PostgreSQL database:

```bash
./knemora migrate-postgresql \
  --source-url 'postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE'
```

By default, a portable logical source backup is written under `./backups`, outside
`~/.knemora`. Use `--backup-dir /independent/path` to choose another parent. Import happens in a
temporary database. Knemora validates every table count, `PRAGMA foreign_key_check`, and
`PRAGMA integrity_check` before atomically promoting the file and changing the repository `.env`.
If any step fails, the active URL is unchanged and the backup directory is retained with a
`.failed` suffix. Correct the problem and retry the same command. A completed import has a receipt
beside the SQLite file, so an identical retry validates and exits without duplicating rows.

After migration, run `./knemora start` and verify sign-in, documents, Knowledge, chat history,
datasets, and audit records. Keep PostgreSQL and the logical backup until that acceptance is done.
Rollback is explicit: stop Knemora, restore the pre-migration `.env` database URL, and restart;
the migration command did not modify the source.
