# Knowledge Engine

The Knowledge Engine analyzes normalized records through `LLMProvider`, validates structured
proposals, resolves stable page identities, preserves conflicts, writes pages atomically, rebuilds
indexes, and lints the resulting Wiki. Failed compilation cannot partially replace valid knowledge.

Search combines structured identity, weighted BM25, backlinks, and bounded graph traversal. It does
not require a vector database. Dataset calculations remain allow-listed and deterministic in
Polars; the model may select or explain an operation but does not execute arbitrary code or SQL.

## Compilation timeout and model context

Structured knowledge compilation uses a 2,048-token first attempt and at most one context-safe
retry. Each attempt has a 300-second response-read timeout by default, separate from ordinary chat.
If a healthy model is demonstrably slower, increase only the compilation timeout in the repository
`.env`, then restart Knemora:

```dotenv
KNEMORA_KNOWLEDGE_COMPILATION_TIMEOUT_SECONDS=500
```

This setting changes waiting time only. It does not increase the output-token limit, model context,
or retry count, and it does not make truncated or schema-invalid output acceptable. Prefer the
300-second default unless logs show the model is still generating valid bounded output when the
deadline is reached.

Check the default model's context state with:

```bash
./knemora model info qwen3-8b-q3-k-m
```

Use the reported **last effective context** to distinguish the full 8,192-token runtime from the
automatic 4,096-token fallback. The configured preference and current memory assessment are
separate: a later start recalculates automatic admission from memory available at that time.
