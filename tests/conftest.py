"""Shared fixtures.

Every test here runs against the fake providers and a temp-file SQLite store —
no network, no credentials, no cost.
"""
# ruff: noqa: E402 - the colour guard below has to run before any import that
# builds a rich Console, so imports cannot all sit at the top of this file.

from __future__ import annotations

import os

# Before any ledgerkb import, because `cli/main.py` builds its `Console` at
# import time and rich reads these variables when a Console is constructed, not
# when it prints. A fixture would run far too late.
#
# The human-readable output is meant to be coloured; the CLI tests just assert
# on plain substrings. Without this, six of them fail for anyone whose shell
# exports FORCE_COLOR, and pass in CI, which is the worst way round: the failure
# appears only on the contributor's machine and looks like their fault.
for _forced in ("FORCE_COLOR", "CLICOLOR_FORCE"):
    os.environ.pop(_forced, None)

from collections.abc import Iterator
from pathlib import Path

import pytest

from ledgerkb.core.config import Config
from ledgerkb.core.models import (
    Chunk,
    Document,
    DocumentVersion,
    Source,
    Workspace,
    new_id,
)
from ledgerkb.providers.fake import FakeChatModel, FakeEmbedder
from ledgerkb.storage.sqlite.store import SqliteStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteStore]:
    s = SqliteStore(tmp_path / "store.db")
    s.migrate()
    yield s
    s.close()


@pytest.fixture
def workspace(store: SqliteStore) -> Workspace:
    ws = Workspace(name="test")
    store.add_workspace(ws)
    return ws


@pytest.fixture
def source(store: SqliteStore, workspace: Workspace) -> Source:
    s = Source(workspace_id=workspace.id, kind="upload", label="fixtures")
    store.add_source(s)
    return s


@pytest.fixture
def version(store: SqliteStore, workspace: Workspace, source: Source) -> DocumentVersion:
    doc = Document(
        workspace_id=workspace.id,
        source_id=source.id,
        external_id="minutes-2026-03-11.pdf",
        title="Cabinet minutes, 11 March 2026",
        doc_type="minutes",
    )
    doc_id = store.upsert_document(doc)
    v = DocumentVersion(
        document_id=doc_id,
        version_no=1,
        content_hash="a" * 64,
        text_hash="b" * 64,
        mime="application/pdf",
        parser="pypdfium2",
        parse_quality=0.94,
    )
    store.add_version(v)
    return v


@pytest.fixture
def chunk_factory(workspace: Workspace, version: DocumentVersion):
    def make(text: str, ordinal: int = 0, **kw) -> Chunk:
        return Chunk(
            id=kw.pop("id", new_id()),
            workspace_id=workspace.id,
            version_id=version.id,
            ordinal=ordinal,
            char_start=kw.pop("char_start", 0),
            char_end=kw.pop("char_end", len(text)),
            text=text,
            **kw,
        )

    return make


@pytest.fixture(scope="session")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 20-document fixture corpus, plus injection and archive fixtures.

    Built once per session rather than committed, so the content stays
    reviewable source instead of an opaque binary nobody diffs.
    """
    from tests.fixtures.build_corpus import build, build_injections, build_malicious_archives

    root = tmp_path_factory.mktemp("corpus")
    build(root / "corpus")
    build_injections(root / "injections")
    build_malicious_archives(root / "archives")
    return root


@pytest.fixture(scope="session")
def corpus(corpus_root: Path) -> Path:
    return corpus_root / "corpus"


@pytest.fixture(scope="session")
def injections(corpus_root: Path) -> Path:
    return corpus_root / "injections"


@pytest.fixture(scope="session")
def archives(corpus_root: Path) -> Path:
    return corpus_root / "archives"


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def chat() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimensions=64)
