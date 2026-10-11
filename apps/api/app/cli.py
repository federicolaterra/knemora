"""Small operational CLI for deterministic Wiki maintenance."""

from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.knowledge.store import WikiStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Knemora local operations")
    parser.add_argument("command", choices=("wiki-lint", "wiki-rebuild"))
    args = parser.parse_args()
    store = WikiStore(get_settings().knowledge_path)
    if args.command == "wiki-rebuild":
        pages = store.rebuild_index()
        print(json.dumps({"status": "rebuilt", "pages": len(pages)}))
        return 0
    report = store.lint()
    print(report.model_dump_json(indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
