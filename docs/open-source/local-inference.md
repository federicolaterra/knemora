# Local inference

Knemora uses `LocalLlamaCppProvider` through the application-owned `LLMProvider` contract. On
supported macOS Apple Silicon, `./knemora setup` installs the complete official llama.cpp b11146
arm64/Metal payload beneath `KNEMORA_HOME`, verifies its provenance/capabilities/dependencies, and
uses the centralized model registry. Homebrew and an arbitrary PATH executable are never implicit
runtime choices. The default stable ID `qwen3-8b-q3-k-m` resolves to
`ISTA-DASLab/Qwen3-8B-GGUF-GSQ/qwen3-8b-Q3_K_M.gguf` with its published full SHA-256. The
8,192-token, single-slot runtime profile is the full-context target on the primary 16 GB
unified-memory host. Admission remains dependent on current safe memory. Each start tries that
automatic profile first and, when necessary, may admit the supported 4,096-token fallback; if even
the fallback is unsafe, startup is refused. Reduced context can truncate broad or multi-step answers
sooner and is not an equivalent-quality mode. Explicit per-model or environment overrides are never
silently lowered. The former 27B model remains selectable as `qwen3.8-27b-iq2-s`; it is no longer the
default.

Both Wiki and Direct chat modes use this same active model and provider path. Direct is not a
second client or model: it is an ADK invocation with retrieval tools withheld. It therefore makes
no Wiki, document, dataset, graph, source, or public-search calls, but it does not imply a universal
latency improvement.

Resolution precedence is a validated absolute `LLAMA_SERVER_BIN` operator override, the verified
active managed installation, then a validated explicitly configured legacy `LLAMA_CPP_DIR` source
checkout. Manual developers may still build a separate checkout with `make llm-build`, but normal
setup/start use `NativeRuntimeManager` and do not discover `llama-server` from PATH.

The effective Model Registry merges source-controlled curated entries with user imports stored at
`~/.knemora/config/models.json`. The lifecycle contract is:

```text
load   = import + validate + register
setup  = select/configure a registered model
models = inspect the effective local registry
```

`./knemora load --model hf:<owner>/<repository>:<variant>` resolves exactly one GGUF through the
Hugging Face HTTPS API, supports rerun-based partial resume, validates advertised size and SHA-256
when available, checks the GGUF header, and atomically promotes the artifact before registry
commit. It does not run model repository code or enable `trust_remote_code`. Custom entries report
runtime compatibility as `not-checked` until exercised with the installed llama.cpp and remain
`custom-unverified-by-knemora` regardless of successful container/checksum validation.

Removal is deliberately two-stage for both curated and imported models:

```bash
./knemora model remove <id>
./knemora model remove <id> registry
```

The first command removes only managed local artifact data. The second is rejected while any final,
partial, or invalid artifact remains, and its error prints both commands in the required order.
For a user import, the second command removes its user registry entry. For a curated model, it adds
a persistent local suppression to the user registry so the source-controlled definition is omitted
from the effective registry. The required default definition cannot be suppressed, and active
models must be deselected first.

Metal offload, direct llama.cpp throughput, memory pressure, ADK call count, Wiki latency, and
end-to-end SSE timing were verified on the primary M1 Pro host. The Qwen3-8B profile replaced the
earlier 27B default to retain memory headroom and improve agent latency on the 16 GB target.
Configuration alone is never evidence that GPU offload is active; confirm assigned layers and the
Metal device in the running server log.

No model weights are included. Review the exact model's license and terms before use. Model files
should remain outside Git and protected as operational assets. Future providers can implement the
same capability-aware contract without changing knowledge-domain code.
