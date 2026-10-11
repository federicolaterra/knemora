# Infrastructure scripts

Milestone 02 provides small wrappers for a separately checked-out llama.cpp build:

- `build-llama-cpp-macos.sh` builds `llama-server` and `llama-bench` with Metal;
- `run-llama-server.sh` starts the configured GGUF with conservative 16 GB defaults;
- `check-local-llm.sh` verifies health and one OpenAI-compatible prompt;
- `benchmark-local-llm.sh` runs the native benchmark against the configured model.

The scripts never download or copy a model. See the public
[local inference guide](../../docs/open-source/local-inference.md).

The current 16 GB default wrapper uses one slot, an 8192-token context, six CPU threads, Metal
offload, batch 128, micro-batch 64, Q8_0 K/V caches, mmap, metrics, and disabled reasoning
preservation. Confirm actual Metal assignment and the selected device in the running server log.

Milestone 07 added local-release lifecycle and isolated evaluation runners; Milestone 08.3 routes
the compatibility backup wrappers through the product's portable-archive CLI:

- `start-local-release.sh` and `stop-local-release.sh` manage the complete local stack;
- `backup-local.sh` invokes full or database-only versioned ZIP backup;
- `restore-local.sh` invokes validated staged restore for an archive path or configured ID;
- `run-enterprise-eval.sh` creates an isolated fixture, generates traces, and grades them.

See [Backup and restore](../../docs/open-source/backup-and-restore.md) before using restore.

Milestone 08.1 launcher code now wraps these scripts with direct long-running PID tracking,
strict-port Vue startup, requested-mode readiness checks, and verified all-service shutdown.
Milestone 08.2 adds launch-profile selection for default-off public search and an independent
`./knemora --dev adk-web` foreground developer server. Neither changes the production lifecycle
scripts or starts ADK Web as part of the normal stack.

Milestone 08.5 routes ordinary release startup through the Node-managed bootstrap and verified
native-runtime resolver. `run-llama-server.sh` now requires the resolver-selected absolute
`LLAMA_SERVER_BIN`; it does not search `PATH`. `benchmark-managed-runtime.py` performs the
repeatable five-sample prepared-start, short-stream, and long-stream comparison used by the
milestone acceptance report. The older source-build scripts remain explicit developer tools, not
application setup prerequisites.
