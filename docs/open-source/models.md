# Models

Knemora runs GGUF models locally through llama.cpp. The model registry separates Knemora-curated
definitions from user-imported models and keeps import, selection, inspection, and removal as
distinct operations.

## Curated models

The source-controlled registry currently includes:

| Model ID | Role | Notes |
| --- | --- | --- |
| `qwen3-8b-q3-k-m` | Default | Qwen3 8B GSQ Q3_K_M; the recommended default for the supported 16 GB Apple Silicon target. |
| `gemma-4-e4b-q4-k-m` | Optional, Knemora-tested | Gemma 4 E4B Instruct Q4_K_M; downloaded and selected only when explicitly requested. |
| `qwen3.8-27b-iq2-s` | Optional | A larger retained Qwen entry. It is not the default because measured 16 GB hardware lacked comfortable memory headroom and responsive multi-step performance. |

`qwen3-8b-q3-k-m` remains the required default definition and rollback model. A model being curated
does not guarantee that the current machine has enough safe memory to start it.

No model weights are included in the repository. Each model has its own upstream license and terms;
Knemora's MIT License applies to the software, not to model weights.

## List and inspect models

List the effective local registry, including curated entries and user imports:

```bash
./knemora models
```

Inspect one entry and its local state:

```bash
./knemora model info qwen3-8b-q3-k-m
```

The inspection output distinguishes the configured context preference, automatic or explicit
selection, last effective context, and the last time-dependent memory assessment. The last
effective context describes the most recently admitted start; a future start reassesses available
memory and may make a different automatic decision.

## Select or switch a curated model

`setup --model` selects an already registered model and downloads its managed artifact when
needed:

```bash
./knemora setup --model qwen3-8b-q3-k-m
./knemora setup --model gemma-4-e4b-q4-k-m
```

Setup validates the artifact and checks whether the model's context and memory profile can start
safely. Selection is committed only after preparation succeeds. Allocation or readiness failure
restores the previous selection rather than leaving a partial switch.

Automatic profiles may use a supported 4,096-token fallback when the preferred context is unsafe.
Reduced context can truncate broad or multi-step answers sooner and is not equivalent quality. To
request an explicit validated context for a model:

```bash
./knemora setup --model MODEL_ID --context-tokens 8192
```

The value must be at least 4,096, cannot exceed the validated model capability, and must pass the
same memory checks. Explicit unsafe values fail rather than being silently reduced.

## Import a custom model

Custom imports use an explicit Hugging Face GGUF reference:

```bash
# Verify the repository, artifact, and license before importing.
./knemora load --model hf:owner/Example-GGUF:Q3_K_M
./knemora models
./knemora setup --model example-q3-k-m
```

The import resolves exactly one `.gguf` or fails on no match or ambiguity. It uses a resumable
partial download, checks available metadata and the GGUF container, promotes the artifact
atomically, and only then writes the user registry. Repository code is never downloaded or
executed. Use `--id <unique-alias>` when the generated ID would collide with another entry.

For private or gated repositories, provide `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` in the environment.
Knemora sends the token only as an HTTPS authorization header and does not store it in the registry.
For automation, global flags precede the command:

```bash
./knemora --non-interactive --yes load --model hf:owner/Example-GGUF:Q3_K_M
```

Custom entries are labelled `User / Custom`, `custom-unverified-by-knemora`, and runtime
compatibility `not-checked`. Successful checksum and GGUF validation confirms artifact integrity,
not answer quality, chat-template compatibility, memory suitability, or Knemora certification.

## Curated, tested, and custom status

- **Curated** means Knemora ships a source-controlled definition and integrity metadata for a
  specific upstream artifact.
- **Knemora-tested** is scoped to the exact curated artifact and supported managed runtime behavior
  that the project has actually exercised. It is not a claim about every model variant or host.
- **Custom / unverified** means the user supplied the model. Knemora does not silently promote it to
  tested status after download or a successful start.

Model templates also determine whether labelled Fast/Deep chat control is available. The curated
Qwen3 8B and Gemma 4 E4B templates are verified controllable. Custom or otherwise unverified models
do not receive that claim without separate evidence.

## Memory, context, and compatibility

Model size, context length, KV cache, runtime overhead, and currently available Apple unified
memory all affect admission. Memory estimates are conservative safeguards, not guarantees. A model
that fits on disk may still be refused at startup, and a model that loads may still be unsuitable
for a particular workload.

Choose the default unless you have a concrete reason to switch. Before changing models:

1. stop or finish important work;
2. inspect the candidate with `./knemora model info MODEL_ID`;
3. review its upstream license and hardware requirements;
4. run `./knemora setup --model MODEL_ID` and follow any admission error; and
5. verify chat, grounded Wiki answers, and ingestion on representative non-sensitive data.

Model selection never initiates Wiki compilation or document reprocessing. See
[Local inference](local-inference.md) for runtime startup, Metal, process behavior, and diagnostics.

## Remove a model

Removal is deliberately two-stage:

```bash
./knemora model remove <id>
./knemora model remove <id> registry
```

The first command removes local artifact data only. The second removes a user registry entry or
locally suppresses an optional curated definition, and it is accepted only after artifact data is
gone. Active models must first be replaced with `setup --model <other-id>`. The required default
definition cannot be removed.

Removing a model does not change the Wiki, sources, datasets, databases, or other models. Curated
suppression is stored locally; it never edits the source-controlled registry.

