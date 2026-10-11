# Knowledge Engine

The Knowledge Engine analyzes normalized records through `LLMProvider`, validates structured
proposals, resolves stable page identities, preserves conflicts, writes pages atomically, rebuilds
indexes, and lints the resulting Wiki. Failed compilation cannot partially replace valid knowledge.

Search combines structured identity, weighted BM25, backlinks, and bounded graph traversal. It does
not require a vector database. Dataset calculations remain allow-listed and deterministic in
Polars; the model may select or explain an operation but does not execute arbitrary code or SQL.
