"""Which model made the vectors, recorded and enforced.

The failure this prevents is quiet. Two models' vectors sit in one index, cosine
distance between them is still a number, so nothing raises and nothing looks
empty. Search returns a confidently ranked list of noise, and because L3 cites
whatever L2 retrieved, the first visible symptom is a citation pointing at the
wrong chunk.

``lkb doctor`` already reported config drift before this existed. Reporting was
not enough, because the damage is done by a command the report does not stop.
"""

from __future__ import annotations

import pytest

from ledgerkb.core.config import Config
from ledgerkb.core.errors import InvariantError
from ledgerkb.index.embed import embed_workspace, guard_embedding_space
from ledgerkb.providers.fake import FakeEmbedder
from ledgerkb.storage.sqlite.store import SqliteStore

PAPERS = [
    "The Committee approved the capital allocation of GBP 2.4m.",
    "The footbridge option appraisal recommends Option B.",
    "Housing delivery fell short of target in the year to March.",
]


def embedder_named(name: str, config: Config) -> FakeEmbedder:
    return FakeEmbedder(name=name, dimensions=config.embeddings.dimensions)


@pytest.fixture
def chunks(store: SqliteStore, chunk_factory):
    store.add_chunks([chunk_factory(t, i) for i, t in enumerate(PAPERS)])
    return store


class TestRecording:
    def test_indexing_records_the_model_and_the_dimension(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        assert store.embedding_space(workspace.id) == (
            "model/a", config.embeddings.dimensions
        )

    def test_a_store_that_was_never_indexed_records_nothing(
        self, store: SqliteStore, workspace
    ) -> None:
        assert store.embedding_space(workspace.id) is None
        assert store.embedding_spaces() == []

    def test_indexing_an_empty_workspace_still_records_nothing(
        self, store: SqliteStore, workspace, config: Config
    ) -> None:
        """No chunks, no vectors, so no model to claim.

        ``lkb index`` on an empty store runs the guard, and recording there
        would have ``lkb doctor`` report an embedding space for a store that
        has never embedded anything.
        """
        report = embed_workspace(
            store, config, embedder_named("model/a", config), workspace.id
        )
        assert report.embedded == 0
        assert store.embedding_space(workspace.id) is None

    def test_it_records_what_the_embedder_reports_not_what_config_asked_for(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        """Fact, not intent.

        A provider that resolves an alias, or falls back, differs from its own
        config. The vectors follow the provider, so the record has to as well,
        otherwise the stored model name describes something that never ran.
        """
        assert config.embeddings.model != "provider/actually-used"
        embed_workspace(
            store, config, embedder_named("provider/actually-used", config), workspace.id
        )
        model, _ = store.embedding_space(workspace.id)
        assert model == "provider/actually-used"


class TestDetection:
    def test_the_same_model_twice_is_fine(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        assert store.embedded_chunk_count(workspace.id) == len(PAPERS)

    def test_a_different_model_is_refused_once_vectors_exist(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        store.add_chunks([])  # nothing pending changes; the guard is what runs

        with pytest.raises(InvariantError) as exc:
            embed_workspace(
                store, config, embedder_named("model/b", config), workspace.id
            )

        assert "model/a" in str(exc.value)
        assert "model/b" in str(exc.value)
        assert "--rebuild" in str(exc.value), "the message has to name the way out"

    def test_it_is_caught_even_when_there_is_nothing_left_to_embed(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        """The case that matters most, and the one an early return would miss.

        A model swapped on a fully embedded workspace has no pending chunks. If
        the check only ran when there was work to do, this would report success,
        change nothing, and leave every later query vectorised by the wrong
        model.
        """
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        assert store.chunks_missing_embeddings(workspace.id) == []

        with pytest.raises(InvariantError):
            embed_workspace(
                store, config, embedder_named("model/b", config), workspace.id
            )

    def test_the_vectors_are_left_alone_when_it_refuses(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        with pytest.raises(InvariantError):
            embed_workspace(
                store, config, embedder_named("model/b", config), workspace.id
            )
        assert store.embedding_space(workspace.id) == (
            "model/a", config.embeddings.dimensions
        )
        assert store.embedded_chunk_count(workspace.id) == len(PAPERS)


class TestTheWayOut:
    def test_rebuild_clears_the_space_so_a_new_model_is_accepted(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)

        store.clear_embeddings(workspace.id)
        assert store.embedding_space(workspace.id) is None, (
            "a space describing vectors that no longer exist would make "
            "--rebuild refuse the change it exists to perform"
        )

        embed_workspace(store, config, embedder_named("model/b", config), workspace.id)
        assert store.embedding_space(workspace.id) == (
            "model/b", config.embeddings.dimensions
        )
        assert store.embedded_chunk_count(workspace.id) == len(PAPERS)

    def test_a_space_with_no_vectors_behind_it_binds_nothing(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        """A run that died before writing a vector must not poison the next one.

        Recording happens before the first batch so that an interrupted run
        still leaves the space it was writing into. The price of that choice is
        this case, where the record exists and the vectors do not.
        """
        guard_embedding_space(
            store, embedder_named("model/a", config), workspace.id, pending=len(PAPERS)
        )
        assert store.embedding_space(workspace.id) is not None
        assert store.embedded_chunk_count(workspace.id) == 0

        embed_workspace(store, config, embedder_named("model/b", config), workspace.id)
        assert store.embedding_space(workspace.id) == (
            "model/b", config.embeddings.dimensions
        )


class TestScope:
    def test_two_workspaces_may_use_different_models(
        self, store: SqliteStore, workspace, chunks, config: Config
    ) -> None:
        """Per workspace, because embeddings are written and cleared per workspace.

        Both workspaces hold real vectors here. A second workspace with no
        chunks would record nothing and prove nothing.
        """
        other, other_chunk = _second_workspace_with_a_chunk(store)

        embed_workspace(store, config, embedder_named("model/a", config), workspace.id)
        embed_workspace(store, config, embedder_named("model/b", config), other.id)

        assert store.embedded_chunk_count(other.id) == 1, other_chunk
        assert store.embedding_space(workspace.id) == (
            "model/a", config.embeddings.dimensions
        )
        assert store.embedding_space(other.id) == (
            "model/b", config.embeddings.dimensions
        )
        assert len(store.embedding_spaces()) == 2


def _second_workspace_with_a_chunk(store: SqliteStore):
    """A whole second workspace, down to one embeddable chunk."""
    from ledgerkb.core.models import Chunk, Document, DocumentVersion, Source, Workspace

    ws = Workspace(name="other", profile="default")
    store.add_workspace(ws)
    src = Source(workspace_id=ws.id, kind="upload", label="other fixtures")
    store.add_source(src)
    doc_id = store.upsert_document(
        Document(
            workspace_id=ws.id,
            source_id=src.id,
            external_id="other-minutes.md",
            title="Other minutes",
            doc_type="minutes",
        )
    )
    version = DocumentVersion(
        document_id=doc_id,
        version_no=1,
        content_hash="c" * 64,
        text_hash="d" * 64,
        mime="text/markdown",
        parser="text",
        parse_quality=1.0,
    )
    store.add_version(version)
    text = "A separate workspace, entitled to its own embedding model."
    chunk = Chunk(
        workspace_id=ws.id,
        version_id=version.id,
        ordinal=0,
        char_start=0,
        char_end=len(text),
        text=text,
    )
    store.add_chunks([chunk])
    return ws, chunk
