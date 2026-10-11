"""Deterministic Markdown rendering with machine-readable source locators."""

from __future__ import annotations

import json

from app.ingestion.types import ParsedDocument


def render_extracted_markdown(parsed: ParsedDocument) -> str:
    """Render blocks without interpreting source content as application instructions."""

    rendered: list[str] = []
    for ordinal, block in enumerate(parsed.blocks, start=1):
        marker = json.dumps(
            {"ordinal": ordinal, "locator": block.locator},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rendered.append(f"<!-- knemora-source {marker} -->\n\n{block.content}".rstrip())
    return "\n\n".join(rendered).rstrip() + "\n"
