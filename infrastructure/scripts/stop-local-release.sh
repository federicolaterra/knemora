#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
runtime_dir="${KNEMORA_RUNTIME_DIR:-${repo_root}/.runtime}"

for service in web api llm; do
  pid_file="${runtime_dir}/${service}.pid"
  if [[ -f "${pid_file}" ]]; then
    pid="$(<"${pid_file}")"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}"
      for _ in {1..50}; do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "${pid}" 2>/dev/null; then
        kill -KILL "${pid}"
      fi
    fi
    rm "${pid_file}"
  fi
done

echo "Knemora services stopped; the embedded SQLite database was preserved."
