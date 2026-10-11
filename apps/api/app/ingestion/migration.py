"""Recoverable migration from legacy ``original.<ext>`` source leaf names."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Document, DocumentVersion
from app.ingestion.storage import SourceStorage, readable_storage_filename


class SourceFilenameMigrator:
    """Rename legacy originals while preserving bytes, identity, and authoritative URIs."""

    def __init__(self, *, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self.session_factory = session_factory
        self.storage = SourceStorage(settings.source_store_path)
        self.knowledge_path = settings.knowledge_path.resolve()

    def run(self) -> int:
        migrated = 0
        with self.session_factory() as session:
            rows = session.execute(
                select(DocumentVersion, Document).join(
                    Document, DocumentVersion.document_id == Document.id
                )
            ).all()
            for version, document in rows:
                old_path = self.storage.resolve_relative(version.storage_uri)
                if not old_path.name.casefold().startswith("original."):
                    continue
                journal = old_path.parent / "source-name-migration.json"
                journal_payload: dict[str, object] | None = None
                if journal.is_file():
                    loaded = json.loads(journal.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        journal_payload = loaded
                extension = str(version.provenance.get("extension") or old_path.suffix).lower()
                display_name = str(
                    version.provenance.get("original_filename") or document.original_filename
                )
                recorded_new_uri = (
                    str(journal_payload.get("new_uri"))
                    if journal_payload is not None
                    and journal_payload.get("old_uri") == version.storage_uri
                    and journal_payload.get("status") in {"prepared", "completed"}
                    else None
                )
                if recorded_new_uri is not None:
                    new_path = self.storage.resolve_relative(recorded_new_uri)
                    if new_path.parent != old_path.parent:
                        raise ValueError(
                            "Source-name migration journal changed identity directory."
                        )
                    new_name = new_path.name
                    new_uri = recorded_new_uri
                else:
                    new_name = readable_storage_filename(
                        display_name,
                        extension=extension,
                        identity=version.id,
                        existing_names={child.name for child in old_path.parent.iterdir()},
                    )
                    new_path = old_path.with_name(new_name)
                    new_uri = self.storage.relative_path(new_path)
                payload = {
                    "version": 1,
                    "document_version_id": str(version.id),
                    "old_uri": version.storage_uri,
                    "new_uri": new_uri,
                    "sha256": version.sha256,
                    "status": "prepared",
                }
                self._write_json(journal, payload)
                if old_path.exists() and not new_path.exists():
                    os.replace(old_path, new_path)
                if not new_path.is_file():
                    raise FileNotFoundError(f"Legacy original is unavailable for {version.id}.")
                if hashlib.sha256(new_path.read_bytes()).hexdigest() != version.sha256:
                    raise ValueError(f"Legacy original checksum mismatch for {version.id}.")

                old_uri = version.storage_uri
                version.storage_uri = new_uri
                version.provenance = {
                    **version.provenance,
                    "storage_filename": new_name,
                    "legacy_storage_uri": old_uri,
                }
                self._replace_reference(old_path.parent / "metadata.json", old_uri, new_uri)
                self._replace_reference(
                    self.knowledge_path / "sources" / f"{version.id}.md", old_uri, new_uri
                )
                session.commit()
                self._write_json(journal, {**payload, "status": "completed"})
                migrated += 1
        return migrated

    @staticmethod
    def _replace_reference(path: Path, old_uri: str, new_uri: str) -> None:
        if not path.is_file():
            return
        content = path.read_text(encoding="utf-8")
        if old_uri in content:
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(content.replace(old_uri, new_uri), encoding="utf-8")
            os.replace(temporary, path)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)


__all__ = ["SourceFilenameMigrator"]
