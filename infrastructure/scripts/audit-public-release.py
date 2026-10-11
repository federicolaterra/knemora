"""Fail on leaked secrets or legacy branding outside explicit compatibility paths."""

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "infrastructure/public-release-brand-allowlist.txt"
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".venv",
    "_internal",
    "AGENTS.md",
    "artifacts",
    "backups",
    "dist",
    "node_modules",
}
BRAND_PATTERN = re.compile(r"pharmatrace|pharmaceutical", re.IGNORECASE)
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{36,255}\b"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
}


def allowed_patterns() -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def text_files() -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(ROOT).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files.append((relative, content))
    return files


def main() -> int:
    allowed = allowed_patterns()
    failures: list[str] = []
    for relative, content in text_files():
        brand_allowed = any(fnmatch.fnmatch(relative, pattern) for pattern in allowed)
        if not brand_allowed:
            for line_number, line in enumerate(content.splitlines(), start=1):
                if BRAND_PATTERN.search(line):
                    failures.append(f"legacy brand: {relative}:{line_number}")
        if relative == "infrastructure/scripts/audit-public-release.py":
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"possible {label}: {relative}")

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith(
        "MIT License\n\nCopyright (c) 2026 Federico La Terra\n\nPermission is hereby granted"
    ):
        failures.append("LICENSE is not the expected standard MIT grant and attribution")
    for required in (
        "README.md",
        "docs/open-source/THIRD_PARTY_NOTICES.md",
        ".github/SECURITY.md",
    ):
        if not (ROOT / required).is_file():
            failures.append(f"missing public-release file: {required}")

    if failures:
        print("Public-release audit failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Public-release brand, secret-signature, and license checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
