# Evaluation Datasets

This directory contains evaluation datasets for testing agent behavior.

## Running Evaluations

### Default Dataset
```bash
# Generate traces using the default dataset
agents-cli eval generate
agents-cli eval grade
```

### Custom Dataset
```bash
# Generate traces for a custom dataset
agents-cli eval generate --dataset tests/eval/datasets/custom-dataset.json --output custom_traces/
agents-cli eval grade --metrics general_quality --traces custom_traces/
```

## Dataset Format

Each dataset file follows the Gemini Enterprise Agent Platform Evaluation
dataset format. An eval case may use **either** of two shapes — both are
valid input to `agents-cli eval generate`:

**Shape A — single-prompt case:**

```json
{
  "eval_cases": [
    {
      "eval_case_id": "unique_case_id",
      "prompt": {
        "role": "user",
        "parts": [{"text": "User message"}]
      }
    }
  ]
}
```

**Shape B — continued-conversation case (the "N+1" pattern):**
The case carries prior turns in `agent_data` and the last turn ends with a
user message; `eval generate` appends the next agent response.

```json
{
  "eval_cases": [
    {
      "eval_case_id": "unique_case_id",
      "agent_data": {
        "turns": [
          {
            "turn_index": 0,
            "events": [
              {"author": "user",  "content": {"role": "user",  "parts": [{"text": "First user message"}]}},
              {"author": "agent", "content": {"role": "model", "parts": [{"text": "First agent reply"}]}},
              {"author": "user",  "content": {"role": "user",  "parts": [{"text": "Follow-up user message"}]}}
            ]
          }
        ]
      }
    }
  ]
}
```

## Key Fields

- `eval_cases`: Array of evaluation cases.
- `eval_case_id`: Unique identifier for the evaluation case (optional).
- `prompt`: A single user message — Shape A.
- `agent_data.turns`: Prior conversation turns ending with a user message — Shape B.

## Creating Custom Datasets

You can create custom datasets in two ways:

1. **By Hand**: Copy `basic-dataset.json` as a template and manually add evaluation cases.
2. **Synthesize**: Use the synthetic dataset generation command to generate conversation scenarios:
   ```bash
   agents-cli eval dataset synthesize --count 10
   ```

## Discovering Metrics

You can discover available out-of-the-box evaluation metrics by running:

```bash
agents-cli eval metric list
```

## Beyond Generate and Grade

Once you have a baseline, the eval surface has a few more commands worth knowing about:

- `agents-cli eval compare BASE CAND` — diff two grade-results files (regression check).
- `agents-cli eval analyze RESULTS` — cluster failure modes from a grade-results file.
- `agents-cli eval optimize` — auto-tune your agent's prompts using eval data.

See the [Evaluation Guide](https://google.github.io/agents-cli/guide/evaluation/) for the full surface and metric reference.

## Milestone 05 retrieval and analysis fixture

The Milestone 05 suite covers exact identity, aliases, single- and multi-source QA,
relationships, conflicts, unknown questions, provenance, lexical mismatch, bounded graph
traversal, deterministic dataset comparison, and chart-ready trends. Run it only against its
isolated local fixture:

```bash
mkdir -p artifacts/eval-fixture
export KNEMORA_DATABASE_URL=sqlite+pysqlite:///artifacts/eval-fixture/knemora.db
export KNEMORA_SOURCE_STORE_PATH=./apps/api/artifacts/eval-fixture/sources
export KNEMORA_KNOWLEDGE_PATH=./apps/api/artifacts/eval-fixture/knowledge
export KNEMORA_APP_ENV=evaluation
export KNEMORA_AUTHENTICATION_REQUIRED=false
uv run python -m tests.eval.prepare_retrieval_fixture
uv run python -m tests.eval.run_local_eval \
  --dataset tests/eval/datasets/retrieval-and-analysis.json \
  --output artifacts/local-eval/retrieval-and-analysis.json
```

The fixture loader refuses PostgreSQL and paths outside `artifacts/eval-fixture`, so evaluation
cannot mutate the normal development database, source store, or Wiki.

`make eval-enterprise` wraps the complete sequence. The local runner executes the same Google ADK
application and narrow tools but does not initialize Vertex evaluation storage or require Google
ADC. The agents-cli-compatible datasets and YAML metrics remain available for a future CLI release
that supports fully local generation and grading.
