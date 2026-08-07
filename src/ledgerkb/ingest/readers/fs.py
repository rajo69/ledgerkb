"""Filesystem reader — a path, a directory, or a zip.

The only reader L1 needs, and the only one that requires no network. It walks a
tree, expands archives through the guards in :mod:`~ledgerkb.ingest.readers.archive`,
and yields ``(Document, bytes)`` pairs for the pipeline to hash and parse.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ledgerkb.core.models import Document
from ledgerkb.ingest.parsers.registry import KNOWN_UNSUPPORTED, guess_mime
from ledgerkb.ingest.readers.archive import expand, is_archive

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".lkb", ".idea", ".vscode"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin", ".lock"}


@dataclass(frozen=True)
class FetchedDocument:
    document: Document
    data: bytes

    @property
    def content_hash(self) -> str:
        return sha256(self.data)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FilesystemReader:
    """Implements the reading half of :class:`ledgerkb.core.ports.Reader`."""

    kind = "upload"

    def __init__(self, workspace_id: str, source_id: str) -> None:
        self.workspace_id = workspace_id
        self.source_id = source_id

    def read(self, target: str | Path) -> Iterator[FetchedDocument]:
        """Yield every readable document under ``target``.

        A directory is walked in sorted order so two runs over the same tree
        produce the same sequence — which is what makes an ingest run
        reproducible and a change report meaningful.

        The target is resolved to an absolute path first: ``external_id`` stays
        relative to it, but ``uri`` is a ``file://`` URI, and a relative path
        has no URI form.
        """
        path = Path(target).resolve()
        if not path.exists():
            raise FileNotFoundError(f"No such path: {target}")

        if path.is_file():
            yield from self._read_file(path, external_id=path.name)
            return

        for child in sorted(path.rglob("*")):
            if any(part in SKIP_DIRS for part in child.parts):
                continue
            if not child.is_file():
                continue
            if child.suffix.lower() in SKIP_SUFFIXES:
                continue
            external_id = str(child.relative_to(path)).replace("\\", "/")
            yield from self._read_file(child, external_id=external_id)

    def _read_file(self, path: Path, external_id: str) -> Iterator[FetchedDocument]:
        data = path.read_bytes()

        if is_archive(path.name):
            for member in expand(data, archive_name=path.name):
                if Path(member.path).suffix.lower() in SKIP_SUFFIXES:
                    continue
                yield self._document(
                    external_id=f"{external_id}!{member.path}",
                    uri=f"{path.as_uri()}!{member.path}",
                    filename=Path(member.path).name,
                    data=member.data,
                )
            return

        yield self._document(
            external_id=external_id,
            uri=path.as_uri(),
            filename=path.name,
            data=data,
        )

    def _document(self, external_id: str, uri: str, filename: str, data: bytes) -> FetchedDocument:
        return FetchedDocument(
            document=Document(
                workspace_id=self.workspace_id,
                source_id=self.source_id,
                external_id=external_id,
                uri=uri,
                title=filename,
            ),
            data=data,
        )


def is_probably_readable(name: str) -> bool:
    """Cheap pre-filter for reporting, not a gate. The registry decides."""
    suffix = Path(name).suffix.lower()
    return suffix not in SKIP_SUFFIXES and suffix not in KNOWN_UNSUPPORTED and bool(
        guess_mime(name)
    )


__all__ = ["FetchedDocument", "FilesystemReader", "is_probably_readable", "sha256"]
