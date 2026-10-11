"""Deterministic Northstar Labs Development demo preset.

The generated Markdown source is intentionally human-readable. It is ingested by the normal
immutable-source pipeline and compiled through ``KnowledgeCompiler`` with a deterministic provider,
so the public demo is repeatable without asking the local model to invent seed content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PRESET_NAME = "development"
PRESET_VERSION = 1
TOPIC = "Development"
ORGANIZATION = "Northstar Labs"
EXPECTED_MIN_PAGES = 100
CANONICAL_PROMPT = (
    "Which gateway, owner, policy, and freeze day apply to ORBIT-LANTERN? Cite sources."
)
EXPECTED_FACTS = {
    "project": "ORBIT-LANTERN",
    "gateway": "Cedar Gate",
    "owner": "Atlas Platform Team",
    "policy": "DEV-POL-017",
    "freeze_day": "Wednesday",
}


@dataclass(frozen=True)
class PageDefinition:
    key: str
    title: str
    kind: str
    category: str
    summary: str
    claim: str
    relationships: tuple[tuple[str, str], ...]


CATEGORY_CONTENT: dict[str, tuple[tuple[str, str], ...]] = {
    "Architecture": (
        (
            "Architecture Overview",
            "Northstar uses a modular monolith for product APIs and independently managed local inference.",
        ),
        (
            "Trust Boundary Map",
            "Uploaded text is evidence, never executable policy, and all tool authorization remains server-side.",
        ),
        (
            "Event Flow",
            "Domain events are recorded after committed state changes and carry correlation identifiers.",
        ),
        (
            "Local Inference Boundary",
            "Model traffic stays on loopback and domain code depends only on the provider contract.",
        ),
        (
            "Knowledge Compilation Flow",
            "Immutable sources become normalized records, provenanced claims, Wiki pages, and lexical indexes.",
        ),
        (
            "Deployment Topology",
            "The development topology uses SQLite, FastAPI, Vue, and llama.cpp on one trusted workstation.",
        ),
    ),
    "Backend": (
        (
            "FastAPI Service Conventions",
            "Routers validate typed inputs while services own transactions and repositories own persistence queries.",
        ),
        (
            "Error Contract",
            "Public API failures use problem details with a stable type, safe detail, HTTP status, and request ID.",
        ),
        (
            "Background Work Policy",
            "Long-running work records durable job state before processing and exposes retry without duplicating effects.",
        ),
        (
            "Configuration Precedence",
            "Process environment values override local dotenv values and canonical KNEMORA variables override compatibility aliases.",
        ),
        (
            "Python Type Discipline",
            "Backend changes pass strict static typing and do not use untyped dictionaries at domain boundaries.",
        ),
        (
            "Request Correlation",
            "Every API response echoes a bounded request identifier used to connect audit and operational events.",
        ),
    ),
    "Frontend": (
        (
            "Vue Application Shell",
            "The Vue shell derives product identity and capabilities from the backend before rendering navigation.",
        ),
        (
            "Client Error Handling",
            "The client renders safe problem details and never displays server stack traces or hidden model reasoning.",
        ),
        (
            "Accessible Interaction Standard",
            "Interactive controls require keyboard operation, visible focus, labels, and live status where appropriate.",
        ),
        (
            "State Store Boundaries",
            "Authentication, system metadata, and workspace data live in separate Pinia stores with explicit refresh behavior.",
        ),
        (
            "Knowledge Page Experience",
            "The Knowledge view exposes search, page claims, backlinks, graph relationships, and source citations.",
        ),
        (
            "Demo Mode Presentation",
            "Demo mode is visibly labeled Synthetic Data and Development without changing normal workspace presentation.",
        ),
    ),
    "APIs": (
        (
            "API Versioning",
            "Breaking HTTP contract changes require a new API version; additive response fields remain backward compatible.",
        ),
        (
            "Pagination Contract",
            "List endpoints use stable ordering and bounded page sizes before datasets become operationally large.",
        ),
        (
            "Idempotency Rules",
            "Retryable mutation endpoints use stable resource identity or checksums to avoid duplicate work.",
        ),
        (
            "Health Endpoint Contract",
            "Liveness checks process availability while readiness checks SQLite and local inference separately.",
        ),
        (
            "Cedar Gate",
            "Cedar Gate is Northstar Labs' internal API gateway nickname and is owned by the Atlas Platform Team.",
        ),
        (
            "API Deprecation Window",
            "Deprecated API fields remain readable for one major release and emit operator-visible migration guidance.",
        ),
    ),
    "Database": (
        (
            "SQLite Ownership",
            "SQLite stores operational metadata, while immutable bytes and the Markdown Wiki remain separate assets.",
        ),
        (
            "Migration Safety",
            "Migrations are ordered, additive by default, data-preserving, and tested against a prior-schema fixture.",
        ),
        (
            "Transaction Boundary",
            "A service commits one business operation atomically and records its audit event in the same transaction.",
        ),
        (
            "Index Review Standard",
            "New indexes require a measured query pattern and an explain-plan review before release.",
        ),
        (
            "Backup Retention",
            "Development backups retain seven daily database snapshots and never replace immutable source backups.",
        ),
        (
            "Demo Database Isolation",
            "The Development preset uses the dedicated knemora_demo database and never writes normal workspace metadata.",
        ),
    ),
    "Infrastructure": (
        (
            "Apple Silicon Workstation",
            "The primary local profile targets macOS Apple Silicon with Metal acceleration and 16 GB unified memory.",
        ),
        (
            "Container Boundary",
            "SQLite is embedded; local application and inference processes bind only to loopback by default.",
        ),
        (
            "Harbor-3",
            "Harbor-3 is the fictional label for Northstar Labs' staging region used by Project ORBIT-LANTERN.",
        ),
        (
            "Runtime Logs",
            "Managed services write separate content-safe logs beneath the Knemora application-data directory.",
        ),
        (
            "Disk Capacity Runbook",
            "Operators keep model size plus two gigabytes free before model acquisition and preserve partial downloads for retry.",
        ),
        (
            "Service Port Registry",
            "Development uses an embedded database and reserves 8080 for llama.cpp, 8000 for FastAPI, and 5173 for Vue.",
        ),
    ),
    "CI-CD": (
        (
            "Continuous Integration Gates",
            "Every change passes formatting, lint, strict type checks, backend tests, frontend tests, build, and release audit.",
        ),
        (
            "Release Branch Policy",
            "Release branches are cut only from a green main branch and receive fixes through reviewed cherry-picks.",
        ),
        (
            "Artifact Promotion",
            "The same verified artifact is promoted between environments; rebuilding during promotion is prohibited.",
        ),
        (
            "Rollback Decision",
            "A failed readiness check or provenance regression triggers rollback before additional deployment attempts.",
        ),
        (
            "Deployment Evidence",
            "Each production deployment records revision, migration head, operator, approval, and verification results.",
        ),
        (
            "Wednesday Pipeline Hold",
            "Routine production pipelines pause during the Wednesday development freeze unless an incident commander approves an exception.",
        ),
    ),
    "Security": (
        (
            "Uploaded Content Threat Model",
            "Documents may contain prompt injection and are treated as untrusted evidence without tool authority.",
        ),
        (
            "Local Port Exposure",
            "API, web, and inference listeners bind to 127.0.0.1 unless an operator explicitly configures a protected network.",
        ),
        (
            "Secret Handling",
            "Secrets come from protected environment configuration and are redacted from status, logs, and diagnostic output.",
        ),
        (
            "Role Review",
            "Administrators review role assignments quarterly and immediately after any security incident.",
        ),
        (
            "Dependency Review",
            "Runtime dependency updates require provenance, license, vulnerability, and reproducibility review.",
        ),
        (
            "Browser Consent Boundary",
            "Optional external tools retain their own confirmation boundaries and setup never bypasses platform security controls.",
        ),
    ),
    "Standards": (
        (
            "Engineering Standards",
            "Northstar changes must be reviewable, observable, reversible, and backed by proportionate automated tests.",
        ),
        (
            "Definition of Done",
            "Work is done only when behavior, tests, operator documentation, and recovery implications agree.",
        ),
        (
            "Code Review Standard",
            "At least one reviewer validates correctness, security boundaries, data preservation, and operational impact.",
        ),
        (
            "Documentation Standard",
            "Documentation states actual behavior, distinguishes limitations, and avoids promises for unimplemented features.",
        ),
        (
            "Naming Standard",
            "Stable public identifiers use lowercase kebab-case while user-facing titles use readable natural language.",
        ),
        (
            "DEV-POL-017",
            "DEV-POL-017 governs production deployment for Project ORBIT-LANTERN and requires evidence plus Atlas Platform Team approval.",
        ),
    ),
    "ADRs": (
        (
            "ADR Index",
            "Architecture decisions are immutable historical records; superseding decisions link back rather than rewriting history.",
        ),
        (
            "ADR 021 Modular Monolith",
            "Northstar retains a modular monolith until measured scaling needs justify an independently deployed service.",
        ),
        (
            "ADR 022 Lexical Retrieval First",
            "Search uses structured identity, BM25, and graph navigation before any vector infrastructure is considered.",
        ),
        (
            "ADR 023 Local Model Provider",
            "All model calls cross a provider-neutral boundary with explicit health, timeout, and capability contracts.",
        ),
        (
            "ADR 024 Markdown Knowledge",
            "Organizational knowledge remains human-readable Markdown with YAML and standard wikilinks.",
        ),
        (
            "ADR 025 Demo Isolation",
            "Synthetic demonstrations use an isolated Wiki, source store, and database rather than tagging real user content.",
        ),
    ),
    "Runbooks": (
        (
            "Runbook Index",
            "Runbooks are symptom-led, list safe checks first, and identify escalation and rollback conditions.",
        ),
        (
            "API Unavailable Runbook",
            "Check FastAPI process state, database readiness, port ownership, and redacted logs before restarting.",
        ),
        (
            "Local Model Unavailable Runbook",
            "Verify loopback health, model checksum, memory pressure, and llama.cpp logs before changing configuration.",
        ),
        (
            "Database Recovery Runbook",
            "Restore into an isolated database, verify migrations and row counts, then schedule a controlled cutover.",
        ),
        (
            "Wiki Rebuild Runbook",
            "Back up the Wiki, validate immutable sources, rebuild indexes, lint links, and compare provenance coverage.",
        ),
        (
            "Cedar Gate Degradation Runbook",
            "During Cedar Gate degradation, Atlas Platform Team disables promotion and uses request IDs to isolate failures.",
        ),
    ),
    "Services": (
        (
            "Service Catalog",
            "The service catalog records ownership, dependencies, data classification, health checks, and recovery objectives.",
        ),
        (
            "Knowledge API",
            "Knowledge API serves lexical search, page evidence, backlinks, and bounded graph traversal with authorization.",
        ),
        (
            "Ingestion Service",
            "Ingestion validates uploads, stores immutable bytes, normalizes locator-aware records, and records audit events.",
        ),
        (
            "Compilation Service",
            "Compilation validates structured proposals, preserves conflicts, applies pages atomically, and rebuilds indexes.",
        ),
        (
            "Dataset Analysis Service",
            "Dataset analysis uses allow-listed deterministic Polars operations rather than model arithmetic.",
        ),
        (
            "Identity Service",
            "Identity Service manages local sessions, lockout, roles, permissions, and bootstrap administrator creation.",
        ),
    ),
    "Incidents": (
        (
            "Incident Index",
            "Incident records connect affected services, owners, mitigations, follow-ups, and relevant architecture decisions.",
        ),
        (
            "INC-042 Cedar Timeout",
            "INC-042 traced intermittent Cedar Gate timeouts to an unbounded upstream retry and added a strict retry budget.",
        ),
        (
            "INC-043 Wiki Lock Contention",
            "INC-043 added non-blocking compilation locks after simultaneous jobs attempted Wiki mutation.",
        ),
        (
            "INC-044 Stale Search Index",
            "INC-044 made index rebuild part of the atomic compilation workflow after stale results survived a write.",
        ),
        (
            "INC-045 Model Memory Pressure",
            "INC-045 set the default context to 8192 tokens for the 16 GB Apple Silicon profile.",
        ),
        (
            "INC-046 Demo Data Leak Drill",
            "INC-046 verified that the isolated demo database and vault can be removed without touching normal data.",
        ),
    ),
    "Releases": (
        (
            "Release Index",
            "Release records connect shipped behavior to decisions, migrations, validation evidence, and rollback notes.",
        ),
        (
            "Release 0.8 Community",
            "Release 0.8 established Knemora Community identity, capabilities, upgrade compatibility, and public release checks.",
        ),
        (
            "Release 0.8.1 Onboarding",
            "Release 0.8.1 adds the root launcher, model registry, lifecycle diagnostics, and Development demo preset.",
        ),
        (
            "Release Verification",
            "A release candidate must pass fresh install, upgrade, backup, restore, normal start, and demo acceptance.",
        ),
        (
            "Change Log Policy",
            "User-visible changes and migrations are recorded under the release that first ships them.",
        ),
        (
            "Model Compatibility Matrix",
            "Each supported model records artifact hash, runtime provider, memory guidance, context profile, and license link.",
        ),
    ),
    "Teams": (
        (
            "Team Directory",
            "Team pages identify owned services, escalation boundaries, review duties, and active projects.",
        ),
        (
            "Atlas Platform Team",
            "Atlas Platform Team owns Cedar Gate and approves production deployment under DEV-POL-017.",
        ),
        (
            "Aurora Knowledge Team",
            "Aurora Knowledge Team owns ingestion, compilation, Wiki integrity, and provenance quality.",
        ),
        (
            "Compass Experience Team",
            "Compass Experience Team owns the Vue product shell, accessibility, and guided demo experience.",
        ),
        (
            "Keel Reliability Team",
            "Keel Reliability Team owns runtime health, backups, recovery drills, and incident facilitation.",
        ),
        (
            "Sentinel Security Team",
            "Sentinel Security Team owns threat models, role reviews, dependency policy, and disclosure response.",
        ),
    ),
    "Glossary": (
        (
            "Glossary Index",
            "The glossary defines Northstar-specific terms and links each term to the systems and decisions that use it.",
        ),
        (
            "Cedar Gate Definition",
            "Cedar Gate means the internal API gateway, not an external product or public network service.",
        ),
        (
            "Harbor-3 Definition",
            "Harbor-3 means the staging region label used in synthetic Northstar deployment records.",
        ),
        (
            "Evidence Packet",
            "An evidence packet is the deployment revision, test results, migration status, approvals, and recovery plan.",
        ),
        (
            "Knowledge Claim",
            "A knowledge claim is a supported source fact or synthesis carrying claim-level provenance.",
        ),
        (
            "Development Freeze",
            "The recurring Northstar development freeze is Wednesday; emergency exceptions require incident commander approval.",
        ),
    ),
    "Projects": (
        (
            "Project Portfolio",
            "Project pages connect goals, teams, services, policies, releases, incidents, and operational constraints.",
        ),
        (
            "Project ORBIT-LANTERN",
            "Project ORBIT-LANTERN uses Cedar Gate, is owned by Atlas Platform Team, follows DEV-POL-017, and observes the Wednesday freeze.",
        ),
        (
            "Project PAPER-COMPASS",
            "PAPER-COMPASS improves provenance navigation between Wiki claims and immutable source locators.",
        ),
        (
            "Project TIDAL-MAP",
            "TIDAL-MAP improves bounded graph traversal and connected-topic exploration without embeddings.",
        ),
        (
            "Project QUIET-HARBOR",
            "QUIET-HARBOR automates local backup verification and isolated restore rehearsals.",
        ),
        (
            "Project GLASS-FINCH",
            "GLASS-FINCH strengthens accessible evidence rendering and copyable citation workflows.",
        ),
    ),
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def build_catalog() -> tuple[PageDefinition, ...]:
    """Return 120 deterministic, connected, semantically meaningful pages."""

    pages: list[PageDefinition] = [
        PageDefinition(
            key="development",
            title="Development",
            kind="topic",
            category="Development",
            summary="Synthetic Development knowledge for the fictional Northstar Labs organization.",
            claim=(
                "This isolated preset is synthetic, demo-only, non-production knowledge for "
                "Northstar Labs."
            ),
            relationships=tuple(("contains", category) for category in CATEGORY_CONTENT),
        )
    ]
    entity_categories = {"Services", "Teams", "Projects"}
    synthesis_categories = {"Incidents", "Releases", "Runbooks", "ADRs"}
    for category, entries in CATEGORY_CONTENT.items():
        hub_title = category
        first_title = entries[0][0]
        pages.append(
            PageDefinition(
                key=f"hub-{_key(category)}",
                title=hub_title,
                kind="topic",
                category=category,
                summary=f"Navigation hub for Northstar Labs {category} knowledge.",
                claim=f"This hub organizes synthetic {category} records for the Development demo.",
                relationships=(
                    ("part_of", "Development"),
                    ("indexes", first_title),
                ),
            )
        )
        for title, detail in entries:
            kind = (
                "entity"
                if category in entity_categories
                else "synthesis"
                if category in synthesis_categories
                else "concept"
            )
            links: list[tuple[str, str]] = [
                ("part_of", hub_title),
                ("belongs_to", "Development"),
            ]
            anchor_links = {
                "Project ORBIT-LANTERN": (
                    ("uses", "Cedar Gate"),
                    ("owned_by", "Atlas Platform Team"),
                    ("governed_by", "DEV-POL-017"),
                    ("observes", "Development Freeze"),
                ),
                "Cedar Gate": (
                    ("owned_by", "Atlas Platform Team"),
                    ("governs_traffic_for", "Project ORBIT-LANTERN"),
                ),
                "Atlas Platform Team": (
                    ("owns", "Cedar Gate"),
                    ("delivers", "Project ORBIT-LANTERN"),
                ),
                "DEV-POL-017": (
                    ("governs", "Project ORBIT-LANTERN"),
                    ("approved_by", "Atlas Platform Team"),
                ),
                "Development Freeze": (
                    ("constrains", "Project ORBIT-LANTERN"),
                    ("implemented_by", "Wednesday Pipeline Hold"),
                ),
                "Harbor-3": (("stages", "Project ORBIT-LANTERN"),),
            }
            links.extend(anchor_links.get(title, ()))
            pages.append(
                PageDefinition(
                    key=f"{_key(category)}-{_key(title)}",
                    title=title,
                    kind=kind,
                    category=category,
                    summary=f"{title} in the fictional Northstar Labs Development environment.",
                    claim=detail,
                    relationships=tuple(links),
                )
            )
    if len(pages) != 120:
        raise AssertionError(
            f"Development catalog must contain exactly 120 pages, got {len(pages)}"
        )
    return tuple(pages)


def manifest() -> dict[str, object]:
    return {
        "preset": PRESET_NAME,
        "version": PRESET_VERSION,
        "organization": ORGANIZATION,
        "synthetic": True,
        "demo": True,
        "non_production": True,
        "topic": TOPIC,
        "expected_min_wiki_pages": EXPECTED_MIN_PAGES,
        "generated_wiki_pages": len(build_catalog()),
        "expected_facts": EXPECTED_FACTS,
        "canonical_prompt": CANONICAL_PROMPT,
    }


def render_source() -> bytes:
    """Render the versioned synthetic source consumed by normal ingestion."""

    lines = [
        "# Northstar Labs Development Handbook",
        "",
        "Synthetic: true",
        "Demo: true",
        "Non-production: true",
        f"Preset version: {PRESET_VERSION}",
        "",
        "This fictional handbook exists only to demonstrate private organizational knowledge.",
    ]
    for page in build_catalog():
        lines.extend(
            [
                "",
                f"## {page.title}",
                "",
                f"Preset key: {page.key}",
                f"Category: {page.category}",
                "Record classification: synthetic demo non-production",
                "",
                page.claim,
                "",
                "Related records: " + ", ".join(title for _, title in page.relationships),
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode()


def write_manifest(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
