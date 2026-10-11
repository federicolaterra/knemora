#!/usr/bin/env bash
set -euo pipefail

model_path="${KNEMORA_MODEL_PATH:-${PHARMATRACE_MODEL_PATH:-}}"
: "${model_path:?Set KNEMORA_MODEL_PATH to the GGUF file}"

: "${LLAMA_SERVER_BIN:?Managed runtime resolver did not provide LLAMA_SERVER_BIN}"
server="${LLAMA_SERVER_BIN}"
port="${KNEMORA_LLM_PORT:-${PHARMATRACE_LLM_PORT:-8080}}"
context="${KNEMORA_LLM_CONTEXT_TOKENS:-${PHARMATRACE_LLM_CONTEXT_TOKENS:-8192}}"

if [[ ! -x "${server}" ]]; then
  echo "llama-server not found; run ./knemora setup or set LLAMA_SERVER_BIN" >&2
  exit 1
fi
if [[ ! -f "$model_path" ]]; then
  echo "GGUF model not found: $model_path" >&2
  exit 1
fi

exec "$server" \
  --model "$model_path" \
  --host 127.0.0.1 \
  --port "$port" \
  --ctx-size "$context" \
  --parallel 1 \
  --threads 6 \
  --n-gpu-layers 99 \
  --batch-size 128 \
  --ubatch-size 64 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --load-mode mmap \
  --no-reasoning-preserve \
  --metrics
