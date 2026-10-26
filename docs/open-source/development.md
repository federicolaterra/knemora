# Development

For product-like macOS setup, use `./knemora setup`; it manages uv/Python/llama.cpp locally. For
manual development, install Python 3.12–3.13, uv, Node.js 24, and npm, run `make setup`, then use
`make api-dev` and `make web-dev`. The primary quality gate is `make check`; `make public-audit`
checks product branding and high-confidence secret signatures.
SQLite is the default development and local-product store; PostgreSQL is used only as an explicit
source for migration tests or future adapters. Backend tests use isolated SQLite files and fake
model providers where deterministic behavior is required. Agent
language quality belongs in local evaluation datasets, not brittle string assertions. Public-search
tests must mock DDGS; CI must not depend on live internet access.

Database changes require ordered Alembic revisions. API/config changes require compatibility and
deprecation decisions. Wiki changes require a knowledge-schema strategy. Preserve local-first
operation, immutable originals, mandatory provenance, deterministic dataset computation, and
server-side authorization.
Durable data/path/configuration changes must preserve the version, migration, recovery, and test
contract summarized in [Upgrading](upgrading.md#manual-upgrade-and-data-preservation).
Acceptance checkouts must exclude the maintainer's ignored `.env` and use an isolated temporary
home; setting `KNEMORA_HOME` alone does not override explicit database/source/Wiki paths in `.env`.
Changes to the public-search boundary must preserve Wiki's absolute exclusion, Direct-only double
consent, one bounded current-message-only attempt, untrusted-result handling, and the default-
disabled launch profile. ADK Web acceptance
must use `./knemora --dev adk-web`, verify the printed loopback URL and `/list-apps`, and confirm a
repeated launch does not replace another listener.

Second Brain changes must keep graph packages lazy-loaded, preserve safe Wiki-relative path
resolution, and stop/kill Sigma instances and ForceAtlas2 workers on refresh and unmount. Use
`npm run build` to verify worker chunking. Backend graph tests cover aliases, duplicate basenames,
relative links, headings, code/image/external-link exclusion, diagnostics, cycles, local depth,
external edit/rename/delete refresh, authorization filtering, and traversal/symlink boundaries.
Browser interaction checks should cover click-to-detail versus drag, hover fading, filters, camera
controls, repeated route entry, responsive layout, and the WebGL fallback.

## Starting development work

Begin with the public architecture, installation, upgrading, security, and contribution guides.
Establish local state with `git status --short`, `./knemora status`, and `./knemora models`; never
reset user changes or delete `~/.knemora`, databases, presets, or downloaded models as a shortcut.
Keep pull requests focused, document compatibility effects, and report every check that was not run.
