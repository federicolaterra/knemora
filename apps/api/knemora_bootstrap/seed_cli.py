"""Internal command run inside the API virtual environment to seed demo knowledge."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import Settings
from knemora_bootstrap.seed import seed_sync


def main() -> int:
    preset_root = Path(os.environ["KNEMORA_DEMO_ROOT"])
    result = seed_sync(Settings(), preset_root=preset_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
