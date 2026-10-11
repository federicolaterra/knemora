#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
eval_root="${repo_root}/apps/api/artifacts/eval-fixture"
if [[ -d "${eval_root}" ]]; then
  mv "${eval_root}" "${eval_root}.previous-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "${eval_root}"

export KNEMORA_APP_ENV=evaluation
export KNEMORA_AUTHENTICATION_REQUIRED=false
export KNEMORA_DATABASE_URL="sqlite+pysqlite:///${eval_root}/knemora.db"
export KNEMORA_SOURCE_STORE_PATH="${eval_root}/sources"
export KNEMORA_KNOWLEDGE_PATH="${eval_root}/knowledge"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/knemora-uv-cache}"

cd "${repo_root}/apps/api"
uv run python -m tests.eval.prepare_retrieval_fixture
uv run python -m tests.eval.run_local_eval \
  --dataset tests/eval/datasets/retrieval-and-analysis.json \
  --output artifacts/local-eval/retrieval-and-analysis.json
