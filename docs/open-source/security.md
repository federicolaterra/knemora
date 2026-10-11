# Security and privacy

The primary trust path is browser → API → authentication/RBAC → ingestion of untrusted documents →
parsers → Knowledge Engine → local model → Wiki. Backend checks, not UI visibility, authorize every
protected operation and agent tool.

Uploads are bounded and checked for traversal, unsafe archives, misleading content types, and
invalid names. Source downloads re-check owner scope, active state, containment, existence, and
checksum. Model prompts treat document and conversation content as untrusted data. The agent has no
arbitrary shell, filesystem, SQL, formula, or code-execution tool. Logs and metrics exclude prompts,
responses, credentials, access tokens, document bodies, and hidden reasoning.

Knemora sends no telemetry. Keep the API bound to trusted interfaces, configure strong unique
credentials, restrict CORS/hosts, patch dependencies, and maintain encrypted backups. See the
[security policy](../../.github/SECURITY.md) for private vulnerability reporting.

The bootstrap invokes package managers with argument arrays, never pipes network scripts to a
privileged shell, never disables Gatekeeper or browser controls, and does not print generated
credentials. Model downloads use a fixed HTTPS origin, resumable partial paths, a pinned SHA-256,
and atomic promotion. Existing dotenv values are not overwritten. Managed inference and HTTP
listeners bind to loopback. Demo assets use a dedicated database, immutable-source root, and Wiki;
normal start never injects them. Optional external tools remain outside Knemora's installation and
authorization boundary.
