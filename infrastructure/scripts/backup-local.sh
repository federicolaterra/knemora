#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ( "$2" != "full" && "$2" != "database" ) ]]; then
  echo "Usage: $0 [BACKUP_DIR] {full|database}" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command=("${repo_root}/knemora" --non-interactive backup)
if [[ "$2" == "database" ]]; then
  command+=(--db-only)
else
  command+=(--full)
fi
if [[ -n "$1" ]]; then
  command+=(--path "$1")
fi
exec "${command[@]}"
