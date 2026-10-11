"""Independent update worker entry point that survives API shutdown."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from knemora_bootstrap.configuration import AppPaths, configured_data_path
from knemora_bootstrap.update import UpdateService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--repository", type=Path, required=True)
    arguments = parser.parse_args()
    home = configured_data_path().resolve()
    os.chdir(home)
    service = UpdateService(AppPaths(repository=arguments.repository.resolve(), data=home))
    try:
        service.mark_worker_started(arguments.job_id)
        service.execute_job(arguments.job_id)
    except Exception:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
