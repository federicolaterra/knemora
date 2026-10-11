#!/usr/bin/env bash
set -euo pipefail

: "${LLAMA_CPP_DIR:?Set LLAMA_CPP_DIR to an existing llama.cpp checkout}"

cmake -S "$LLAMA_CPP_DIR" -B "$LLAMA_CPP_DIR/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_METAL=ON
cmake --build "$LLAMA_CPP_DIR/build" --config Release -j 6 \
  --target llama-server llama-bench

"$LLAMA_CPP_DIR/build/bin/llama-server" --version
