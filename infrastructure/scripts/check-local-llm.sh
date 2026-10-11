#!/usr/bin/env bash
set -euo pipefail

base_url="${KNEMORA_LLM_BASE_URL:-${PHARMATRACE_LLM_BASE_URL:-http://localhost:8080}}"
model="${KNEMORA_LLM_MODEL:-${PHARMATRACE_LLM_MODEL:-qwen3-8b-q3-k-m}}"

curl --fail --silent --show-error "$base_url/health"
echo
curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: ready\"}],\"temperature\":0,\"max_tokens\":16}" \
  "$base_url/v1/chat/completions"
echo
