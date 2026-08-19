"""Hybrid retrieval end to end, against the real store and the fake embedder."""

from __future__ import annotations

import pytest

from ledgerkb.core.config import Config
from ledgerkb.core.models import DocumentVersion
from ledgerkb.index.embed import embed_workspace
from ledgerkb.index.hybrid import explain, search
from ledgerkb.providers.fake import FakeEmbedder, FakeReranker
from ledgerkb.storage.sqlite.store import SqliteStore

PAPERS = [
    "The Attercliffe regeneration budget was set at £2.4m for the coming year.",
    "Refuse collection moves to fortnightly from April, subject to consultation.",
    "Reference SCC/2026/114 records the footbridge decision in full.",
    "Members discussed accountability for the river crossing at length.",
    "The risk register lists five open items against the transport programme.",
]


@pytest.fixture
def indexed(store: SqliteStore, workspace, chunk_factory, config: Config):
    for ordinal, text in enumerate(PAPERS):
        store.add_chunks([
            chunk_factory(text, ordinal, heading_path=["Cabinet", f"Item {ordinal}"])
        ])
    embed_workspace(store, config, FakeEmbedder(dimensions=config.embeddings.dimensions),
                    workspace.id)
    return store


class TestEmbedPass:
    def test_it_embeds_every_current_chunk(
        self, store: SqliteStore, workspace, chunk_factory, config: Config
    ) -> None:
        store.add_chunks([chunk_factory(t, i) for i, t in enumerate(PAPERS)])
        report = embed_workspace(
            store, config, FakeEmbedder(dimensions=config.embeddings.dimensions), workspace.id
        )
        assert report.embedded == len(PAPERS)
        assert store.chunks_missing_embeddings(workspace.id) == []

    def test_it_is_resumable(
        self, store: SqliteStore, workspace, chunk_factory, config: Config
    ) -> None:
        """A long run that cannot be interrupted is a run nobody dares start."""
        embedder = FakeEmbedder(dimensions=config.embeddings.dimensions)
        store.add_chunks([chunk_factory(t, i) for i, t in enumerate(PAPERS)])
        embed_workspace(store, config, embedder, workspace.id)

        store.add_chunks([chunk_factory("A late arrival.", len(PAPERS))])
        second = embed_workspace(store, config, embedder, workspace.id)
        assert second.embedded == 1, "already-embedded chunks are not paid for twice"

    def test_it_refuses_a_dimension_the_store_is_not_configured_for(
        self, store: SqliteStore, workspace, chunk_factory, config: Config
    ) -> None:
        from ledgerkb.core.errors import InvariantError

        store.add_chunks([chunk_factory("anything", 0)])
        with pytest.raises(InvariantError, match="locked after the first index build"):
            embed_workspace(store, config, FakeEmbedder(dimensions=384), workspace.id)

    def test_superseded_chunks_are_not_embedded(
        self, store: SqliteStore, workspace, version, chunk_factory, config: Config
    ) -> None:
        """Retrieval hides them, so paying to vectorise them buys nothing."""
        store.add_chunks([chunk_factory(t, i) for i, t in enumerate(PAPERS)])
        store.add_version(
            DocumentVersion(
                document_id=version.document_id, version_no=2,
                content_hash="c" * 64, text_hash="d" * 64,
            )
        )
        report = embed_workspace(
            store, config, FakeEmbedder(dimensions=config.embeddings.dimensions), workspace.id
        )
        assert report.embedded == 0


class TestHybridSearch:
    def test_it_runs_every_arm(self, indexed: SqliteStore, workspace, config: Config) -> None:
        result = search(
            indexed, config, "Attercliffe budget",
            embedder=FakeEmbedder(dimensions=config.embeddings.dimensions),
            workspace_id=workspace.id,
        )
        assert set(result.arms) == {"dense", "sparse", "headings"}
        assert result.hits

    def test_sparse_finds_an_identifier_that_dense_smooths_away(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """The reason both halves exist: BM25 owns reference numbers."""
        result = search(
            indexed, config, "SCC/2026/114", workspace_id=workspace.id, arms=("sparse",)
        )
        assert "SCC/2026/114" in result.hits[0].text

    def test_the_heading_arm_matches_structure_not_body(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        result = search(
            indexed, config, "Cabinet", workspace_id=workspace.id, arms=("headings",)
        )
        assert result.hits
        assert all("Cabinet" in h.heading_path for h in result.hits)

    def test_search_degrades_to_sparse_without_an_embedder(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """A store with no vectors should still search, and say what it did."""
        result = search(indexed, config, "refuse collection", workspace_id=workspace.id)
        assert "dense" not in result.arms
        assert result.hits

    def test_reranking_reorders_and_marks_the_hits(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        result = search(
            indexed, config, "footbridge decision record",
            workspace_id=workspace.id, reranker=FakeReranker(), k=3,
        )
        assert result.reranked
        assert len(result.hits) <= 3
        assert all(h.method == "rerank" for h in result.hits)

    def test_explain_shows_each_arm_and_the_fused_score(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """The L2 gate asks for this by name."""
        result = search(
            indexed, config, "Attercliffe budget",
            embedder=FakeEmbedder(dimensions=config.embeddings.dimensions),
            workspace_id=workspace.id,
        )
        rows = explain(result)
        assert rows
        assert {"chunk_id", "score", "method", "ranks", "preview"} <= set(rows[0])
        assert any(row["ranks"] for row in rows)

    def test_search_is_deterministic(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        embedder = FakeEmbedder(dimensions=config.embeddings.dimensions)
        runs = [
            [h.chunk_id for h in search(
                indexed, config, "budget consultation",
                embedder=embedder, workspace_id=workspace.id).hits]
            for _ in range(3)
        ]
        assert runs[0] == runs[1] == runs[2]
