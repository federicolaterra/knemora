# Local inference

Local inference means Knemora sends model requests to a llama.cpp server running on the same
machine instead of requiring a hosted LLM API. Domain services call the application-owned
`LLMProvider` boundary, so knowledge and chat code do not depend directly on llama.cpp types.

For available models, selection, custom imports, licenses, and removal, see [Models](models.md).

## Managed llama.cpp runtime

On supported macOS Apple Silicon, `./knemora setup` installs the complete pinned llama.cpp
arm64/Metal payload beneath `KNEMORA_HOME`. Knemora verifies its provenance, architecture,
capabilities, dependent libraries, and inventory before activation. A staged or invalid runtime
never replaces the last verified installation.

Normal setup and start do not discover an arbitrary `llama-server` from `PATH`. Runtime resolution
uses this precedence:

1. a validated absolute executable supplied through `LLAMA_SERVER_BIN`;
2. the active verified managed installation; then
3. an explicitly configured legacy `LLAMA_CPP_DIR` checkout.

Manual developers may build a separate llama.cpp checkout with `make llm-build`, but the managed
path uses the centralized runtime manager.

## Startup and request flow

`./knemora start` performs a memory and context preflight, launches one managed llama-server on a
loopback address, waits for readiness, then starts FastAPI and Vue. The selected GGUF is loaded once
and shared by AI (SI) Chat and knowledge compilation through provider-neutral requests.

```text
Vue → FastAPI → Google ADK or Knowledge Engine → LLMProvider → loopback llama-server
```

The runtime uses one model slot with Metal layer offload on the supported platform. Knemora passes
bounded context, batch, cache, timeout, cancellation, streaming, structured-output, and
chat-template options through the provider boundary. The server remains a separate operating-system
process with its own PID, log, readiness endpoint, and shutdown handling.

Private prompts, Wiki evidence, and model responses remain on the machine during ordinary local
inference. Optional Direct-mode web search is a separate explicit network step before model
synthesis; it is not a llama.cpp feature and is never available to Wiki mode.

## Context and memory behavior

Before startup, Knemora estimates model weights, Q8 KV cache, runtime/workspace overhead, current
available unified memory, and a safety reserve. Automatic profiles try their preferred context and
may use the supported 4,096-token fallback only when that fallback also passes admission. If no safe
profile exists, startup is refused before the model is launched.

Reduced context gives the agent less room for system policy, conversation history, tools, evidence,
and output. Knemora preserves the current turn and required policy first, then drops older complete
conversation turns and bounds tool evidence. Explicit context overrides are never silently lowered.
See [Models](models.md#memory-context-and-compatibility) for selection and context commands.

Fast/Deep is a request-scoped chat-template capability. It does not reload the model, change the
global context, reveal hidden reasoning, or alter the independent knowledge compiler. Knemora only
offers labelled control for model templates whose behavior has been verified. See
[AI (SI) Chat modes](chat.md#fast-deep-and-response-metadata).

## Operational diagnostics

Use the managed lifecycle commands first:

```bash
./knemora status
./knemora logs
./knemora logs --follow
./knemora doctor
```

When diagnosing inference:

- confirm `status` reports the intended normal or demo mode and one ready llama.cpp process;
- inspect the server log for the selected model, context, assigned Metal layers, Metal device, and
  readiness result—configuration alone is not proof that GPU offload is active;
- inspect the selected model with `./knemora model info MODEL_ID` to compare configured preference
  with the last effective context and memory assessment;
- check available unified memory before retrying an admission failure;
- treat context overflow, output truncation, timeout, allocation failure, and runtime exit as
  different problems rather than increasing every limit at once.

Content-free telemetry records provider duration, llama.cpp prefill/decode timing, time to first
visible token, token counts, finish reason, model identity, effective context, history size, and
tool count. It excludes prompts, responses, source contents, and hidden reasoning.

## Common failures

### The model is refused before startup

The current model/context profile did not fit the safe memory budget. Close memory-heavy work and
retry, choose a more suitable registered model, or remove an unsafe explicit context override. Do
not bypass the guard by editing selection metadata.

### llama-server starts but never becomes ready

Inspect `./knemora logs` for runtime integrity, architecture, library, port, model, and allocation
errors. Run `./knemora setup` to repair managed components; do not replace the managed binary with an
unverified executable from `PATH`.

### Responses truncate or broad tasks lose context

Check the last effective context. An automatic 4,096-token fallback is safe but provides less
working room than the preferred profile. Reduce the conversation/evidence scope or, only when the
host can admit it, select a validated larger context through the [Models guide](models.md).

### Knowledge compilation reaches its timeout

Compilation uses a separate bounded response-read timeout because structured output can take longer
than ordinary chat. Increase it only when logs show a healthy request is still generating valid
bounded output at the deadline:

```dotenv
KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS=500
```

Restart after editing `.env`. A longer timeout does not add context, output tokens, or retries, and
does not repair invalid structured output.

## Architecture and future providers

The local provider implements capability, timeout, cancellation, streaming, structured-output, and
usage contracts without leaking llama.cpp-specific objects into domain code. A future provider can
implement the same boundary, but no hosted provider is required or currently part of the supported
local product path. See [Architecture](architecture.md) for the broader component and trust model.
