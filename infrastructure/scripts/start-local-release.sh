#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
runtime_dir="${KNEMORA_RUNTIME_DIR:-${repo_root}/.runtime}"
log_dir="${KNEMORA_LOG_DIR:-${runtime_dir}}"
mkdir -p "${runtime_dir}" "${log_dir}"

skip_llm="${KNEMORA_SKIP_LLM:-${PHARMATRACE_SKIP_LLM:-0}}"
model_path="${KNEMORA_MODEL_PATH:-${PHARMATRACE_MODEL_PATH:-}}"

if [[ "${skip_llm}" != "1" ]]; then
  if [[ -z "${model_path}" ]]; then
    echo "Set KNEMORA_MODEL_PATH, or set KNEMORA_SKIP_LLM=1." >&2
    exit 2
  fi
fi

is_running() {
  local pid_file="$1"
  [[ -f "${pid_file}" ]] || return 1
  local pid
  pid="$(<"${pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null
}

cd "${repo_root}"
if command -v git >/dev/null 2>&1; then
  KNEMORA_RUNNING_COMMIT="$(git rev-parse HEAD)"
  export KNEMORA_RUNNING_COMMIT
fi
(cd "${repo_root}/apps/api" && .venv/bin/alembic upgrade head)

if [[ "${skip_llm}" != "1" ]]; then
  if ! is_running "${runtime_dir}/llm.pid"; then
    nohup "${repo_root}/infrastructure/scripts/run-llama-server.sh" >"${log_dir}/llm.log" 2>&1 &
    echo "$!" >"${runtime_dir}/llm.pid"
  fi
fi
if ! is_running "${runtime_dir}/api.pid"; then
  nohup bash -c '
    cd "$1"
    exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
  ' knemora-api "${repo_root}/apps/api" >"${log_dir}/api.log" 2>&1 &
  echo "$!" >"${runtime_dir}/api.pid"
fi
if ! is_running "${runtime_dir}/web.pid"; then
  if [[ ! -f "${repo_root}/apps/web/dist/index.html" ]]; then
    (cd "${repo_root}/apps/web" && npm run build)
  fi
  nohup bash -c '
    cd "$1"
    exec node_modules/.bin/vite preview --host 127.0.0.1 --port 5173 --strictPort
  ' knemora-web "${repo_root}/apps/web" >"${log_dir}/web.log" 2>&1 &
  echo "$!" >"${runtime_dir}/web.pid"
fi

echo "Knemora services launched. Logs: ${log_dir}; PID files: ${runtime_dir}."
