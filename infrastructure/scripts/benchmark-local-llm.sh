#!/usr/bin/env bash
set -euo pipefail

: "${LLAMA_CPP_DIR:?Set LLAMA_CPP_DIR to the llama.cpp checkout}"
model_path="${KNEMORA_MODEL_PATH:-${PHARMATRACE_MODEL_PATH:-}}"
: "${model_path:?Set KNEMORA_MODEL_PATH to the GGUF file}"

benchmark="$LLAMA_CPP_DIR/build/bin/llama-bench"
if [[ ! -x "$benchmark" ]]; then
  echo "llama-bench not found at $benchmark; run make llm-build first" >&2
  exit 1
fi

exec "$benchmark" \
  --model "$model_path" \
  --n-gpu-layers 99 \
  --prompt 256 \
  --generation 64 \
  --repetitions 3
