# Development demo preset

The version 1 Development preset is entirely fictional, synthetic, demo-only, and non-production.
It contains no customer, private, or externally sourced content.

## Start

```bash
./knemora start --with-presets
```

The command uses a dedicated SQLite database, immutable source store, and Wiki
under `~/.knemora/demo/development`. Normal `./knemora start` does not load or inject demo data.
On every start a stage progress bar reports cache inspection, database readiness, preset loading,
and service readiness. The launcher validates the preset files, database ownership/provenance
links, Wiki, graph, lint result, and retrieval index in a single vault snapshot. A valid existing
preset is reused without recompilation;
missing source/database assets are created through the real ingestion/compiler flow. A corrupt or
inconsistently linked preset fails with a diagnostic instead of being reported as `READY`.

The synthetic source is owned by the configured bootstrap administrator, so after signing in the
Knowledge screen shows all 120 pages. FastAPI, the database connection, immutable source root, and
Wiki root all use the same selected mode. Switching between normal and Development mode restarts
managed services instead of reusing a process configured for the other mode. `READY` is printed
only when the managed processes are alive and the API reports the requested mode.

Development mode is intentionally read-only. The API rejects source upload/delete/retry/reprocess,
knowledge compilation/index rebuild, and dataset analysis with a clear `403` response. The Vue UI
hides those mutation workflows while keeping the synthetic Wiki and grounded chat available.

The repository-owned generator creates one deterministic Northstar Labs handbook, ingests it through
the normal immutable-source/parser pipeline, and compiles it with the real Knowledge Compiler using
a deterministic preset provider. The result is 120 schema-valid pages with claim-level provenance,
source manifests, BM25 index entries, and graph relationships. Direct final-Wiki fixtures are not
used by the product demo.

## Knowledge and graph

The `Development` topic spans Architecture, Backend, Frontend, APIs, Database, Infrastructure,
CI-CD, Security, Standards, ADRs, Runbooks, Services, Incidents, Releases, Teams, Glossary, and
Projects. Validation requires at least 100 nodes, 95% connected pages, no more than five orphans,
15 topical clusters, high-degree hubs, connected anchor pages, successful anchor retrieval, zero
Wiki lint errors, and provenance on every page and claim. The generated version currently has 120
connected nodes and zero intended orphans.

After startup, open **Second Brain** and select **Global Graph**. The page renders the same portable
Markdown links that Knemora searches and reasons over. Select any hub as a Local Graph root and
compare one-, two-, and three-hop neighborhoods. The preset does not create or require external
viewer configuration.

## Anchor facts and canonical prompt

- Project: `ORBIT-LANTERN`
- Internal gateway: `Cedar Gate`
- Owner: `Atlas Platform Team`
- Production deployment policy: `DEV-POL-017`
- Development freeze: `Wednesday`
- Staging label: `Harbor-3`

> Which gateway, owner, policy, and freeze day apply to ORBIT-LANTERN? Cite sources.

Expected factual coverage is Cedar Gate, Atlas Platform Team, DEV-POL-017, and Wednesday, with
source/provenance references. Evaluation checks fact coverage rather than exact prose and never
inspects hidden chain-of-thought.

For a fair comparison, ask the exact prompt in a general-purpose chatbot that has not received this
corpus. It cannot authoritatively know these private fictional facts and may ask for context, admit
that it lacks context, or hallucinate. Then ask Knemora. The comparison demonstrates access to
private grounded knowledge, not a smarter base model. No external chatbot is an automated demo
dependency.

## Delete the preset and limitations

```bash
./knemora delete --presets
# non-interactive confirmation:
./knemora --yes delete --presets
```

This stops an active Development environment, drops only `knemora_demo`, and removes only
`~/.knemora/demo/development`. The downloaded model, normal Wiki, normal immutable sources, normal
database, and configuration remain intact. The next `start --with-presets` recreates the preset.

Live answer quality still depends on the selected local model and available hardware. Opening the
local web interface may require normal macOS browser confirmation. The demo remains usable offline
after required packages and model assets are present. Public web search stays disabled unless the
operator starts it with `./knemora start --with-presets --yes-web-search`, and each eligible turn must
still request external results explicitly.
