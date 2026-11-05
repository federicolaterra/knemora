# Installation

This guide covers installing, starting, stopping, troubleshooting, and uninstalling Knemora. For
model selection and custom GGUF imports, see [Models](models.md). For runtime internals, see
[Local inference](local-inference.md).

## Supported platform and prerequisites

The managed installation path currently supports **native macOS on Apple Silicon with Metal**.
Windows, Linux, and Intel macOS adapters are future work and are not supported in this release.

Install:

- Node.js 24 or newer with npm from [nodejs.org](https://nodejs.org/) or another trusted source;
- Git, when using the clone command below; and
- at least 7 GB of free disk space for the default model, staged downloads, runtimes, packages, and
  working data.

Homebrew, global Python, global uv, a global llama.cpp installation, Docker, and PostgreSQL are not
required for the managed path. Knemora does not install Node or perform privileged setup.

## Acquire and set up Knemora

![Knemora setup and startup](../assets/knemora-setup-github.png)

```bash
git clone https://github.com/federicolaterra/knemora.git
cd knemora
./knemora setup
```

The shell entrypoint checks Node/npm and delegates to a small JavaScript bootstrap before Python is
available. Setup then:

1. verifies the host, available memory, and disk space;
2. installs pinned uv, managed CPython, and the complete managed llama.cpp runtime in
   application-owned locations;
3. installs locked Python and frontend dependencies;
4. downloads and validates the selected model;
5. creates minimum local configuration, initializes SQLite, and applies migrations.

Initial setup requires network access for packages, runtimes, and model assets. Re-running setup is
idempotent: valid work is reused, existing configuration is preserved, and active data is not
replaced. A failed setup reports the phase that failed without replacing a verified runtime or
deleting user data.

Fresh setup generates a strong local administrator password in the repository `.env` file with
mode `0600` and does not print it. Use the stored administrator email and password to sign in.

For automation:

```bash
./knemora --non-interactive --yes --no-open setup
```

## First launch and normal operation

```bash
./knemora start
```

Start launches managed llama.cpp, FastAPI, and Vue services. Readiness requires the database,
inference server, API, and UI to report the expected mode. When the launcher prints `READY`, open
<http://localhost:5173>.

Running `./knemora` interactively on a new installation shows the welcome screen and offers either
normal start or the isolated Quick Demo. The explicit `setup` and `start` commands remain the
canonical normal path.

Useful lifecycle and diagnostic commands:

```bash
./knemora stop
./knemora restart
./knemora status
./knemora logs
./knemora logs --follow
./knemora doctor
```

`stop` verifies that Knemora-managed llama.cpp, FastAPI, and Vue processes have stopped. It does not
remove the database, Wiki, sources, datasets, models, or configuration.

To explore with fictional knowledge before uploading personal documents:

```bash
./knemora start --with-presets
```

The demo uses isolated data and is read-only for uploads, compilation changes, and dataset
analysis. See [Quick Demo — Synthetic Data](../demo/development-preset.md).

## Application data

Knemora stores durable application state under `~/.knemora/` by default, including SQLite, models,
the Wiki, immutable sources, datasets, logs, protected configuration, and demo assets. Managed uv
and llama.cpp live under `bin/`, managed Python under `python/`, and package/download caches under
`cache/`.

Override the root with `KNEMORA_HOME` or configure an explicit file-backed
`KNEMORA_DATABASE_URL`. Do not move or delete the data directory as an installation shortcut.
`config/home.json` describes the durable layout; unknown, corrupt, or newer layouts stop before
mutation. Review [Upgrading](upgrading.md) before changing an existing installation and
[Backup & Restore](backup-and-restore.md) before moving computers.

### Move or rename the checkout

Create an independent backup, confirm the destination does not exist, and stop services first:

```bash
./knemora stop
cd ..
mv OLD_DIRECTORY knemora
cd knemora
./knemora setup
```

Setup rebuilds location-bound console scripts against the managed interpreter. It preserves the
repository `.env` and all data under `KNEMORA_HOME`.

## Troubleshooting setup and startup

Start with:

```bash
./knemora doctor
./knemora logs
```

- A failed or checksum-mismatched download never replaces the active managed runtime or model.
- The first macOS validation of a newly staged signed runtime may take tens of seconds.
- Port conflicts, exited managed processes, a wrong runtime mode, or incompatible home metadata
  prevent `READY` and are reported explicitly.
- Model admission depends on current safe memory. Inspect and change models with the
  [Models guide](models.md); do not delete model or selection files manually.
- Prepared private Wiki, dataset, and local chat operation needs no hosted service. Optional Direct
  web search is the documented exception and requires network access.

For runtime process behavior and lower-level diagnostics, see [Local inference](local-inference.md).

## Safe uninstall

Use the guarded uninstall command rather than manually deleting paths:

```bash
./knemora uninstall
./knemora uninstall --preserve-data
```

Both forms print the absolute repository and application-data paths, include uncommitted and
untracked repository files in their warning, and require an explicit `y` or `yes` in an interactive
terminal. Empty input, `n`/`no`, EOF, interruption, non-interactive execution, and the global
`--yes` flag cannot authorize uninstall. The command stops only Knemora PID-managed services and
aborts before deletion if shutdown fails.

`uninstall` removes the repository and the complete configured Knemora data directory, normally
`~/.knemora`, including the database, configuration, models, Wiki, immutable sources, datasets,
logs, and demo data. `uninstall --preserve-data` removes only the repository. It refuses when the
data directory is inside the repository because preservation would be impossible.

Backups outside the repository and application-data directory, shared dependencies, independent
user files, and external symlink targets are not removed. Before uninstalling, create and validate
a portable archive:

```bash
./knemora backup
./knemora backups
```

After `--preserve-data`, clone Knemora again, keep `KNEMORA_HOME` pointed at the retained directory,
then run `./knemora setup` and `./knemora start`.

## Manual development fallback

The manual path is for contributors, not a claim of general Linux or Windows support. Install
Python 3.12–3.13, uv, Node.js 24, and npm, then run:

```bash
cp .env.example .env
# Set a unique KNEMORA_BOOTSTRAP_ADMIN_PASSWORD in .env.
make setup
make db-migrate
make api-dev
```

Run `make web-dev` in another terminal and open <http://localhost:5173>. Local inference is required
for real chat; follow [Local inference](local-inference.md). Development workflow and the optional
Google ADK playground live in [Development](development.md).

## Existing PostgreSQL installations

SQLite is the current local store. Existing PostgreSQL users must use the explicit, source-preserving
import command; Knemora never assumes, changes, or deletes the source database:

```bash
./knemora migrate-postgresql \
  --source-url 'postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE'
```

Import creates a logical backup, copies into a temporary SQLite database, validates table counts,
referential integrity, and database integrity, then atomically promotes the result. Keep the source
and backup until sign-in, documents, Knowledge, chat history, datasets, and audit records have been
verified. See [Upgrading](upgrading.md#manual-upgrade-and-data-preservation) for lifecycle details.
