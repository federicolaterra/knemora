"""Keep every pytest process isolated from the user's real Knemora installation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_HOME = tempfile.TemporaryDirectory(prefix="knemora-pytest-")
_TEST_ROOT = Path(_TEST_HOME.name).resolve()

# Test modules import the production application during collection. Establish all mutable storage
# paths before those imports so plain `pytest` and `make check` cannot resolve to ~/.knemora or the
# repository's tracked Wiki, even when the invoking shell exports live Knemora configuration.
os.environ["KNEMORA_HOME"] = str(_TEST_ROOT)
os.environ["KNEMORA_DATABASE_URL"] = f"sqlite+pysqlite:///{_TEST_ROOT / 'data' / 'knemora.db'}"
os.environ["KNEMORA_SOURCE_STORE_PATH"] = str(_TEST_ROOT / "sources")
os.environ["KNEMORA_KNOWLEDGE_PATH"] = str(_TEST_ROOT / "wiki")
