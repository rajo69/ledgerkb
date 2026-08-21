"""Stage 7 — embed the chunks.

Batched, resumable and budget-guarded. Only chunks of current versions are
embedded: superseded text is kept for history but is never retrieved, so paying
to vectorise it would be paying for something the search deliberately hides.

Resumability matters more than it looks. Embedding a corpus is the first point
in the pipeline where a run can be genuinely long, and a run that cannot be
interrupted is a run nobody dares start. Vectors are written per batch, so
stopping and re-running picks up exactly where it left off.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ledgerkb.core.config import Config
from ledgerkb.core.errors import BudgetExceededError, InvariantError
from ledgerkb.core.models import Chunk
from ledgerkb.core.ports import Embedder
from ledgerkb.storage.sqlite.store import SqliteStore


@dataclass
class EmbedReport:
    embedded: int = 0
    skipped: int = 0
    batches: int = 0
    model: str = ""
    dimensions: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.embedded + self.skipped


def embed_workspace(
    store: SqliteStore,
    cfg: Config,
    embedder: Embedder,
    workspace_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> EmbedReport:
    """Embed every current chunk that has no vector yet."""
    pending = store.chunks_missing_embeddings(workspace_id)
    report = EmbedReport(model=embedder.name, dimensions=embedder.dimensions)

    if embedder.dimensions != cfg.embeddings.dimensions:
        raise InvariantError(
            f"{embedder.name} produces {embedder.dimensions}-dimensional vectors but "
            f"embeddings.dimensions is {cfg.embeddings.dimensions}. The dimension is "
            "locked after the first index build, so this is refused before anything "
            "is written."
        )

    guard_embedding_space(store, embedder, workspace_id, pending=len(pending))

    if not pending:
        return report

    if len(pending) > cfg.budget.max_docs_per_run * 200:
        # A ceiling you set, and cannot set your way out of.
        raise BudgetExceededError(
            f"{len(pending)} chunks exceed what this run is allowed to embed. "
            "Raise budget.max_docs_per_run deliberately, or narrow the workspace."
        )

    batch_size = max(1, cfg.embeddings.batch_size)
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embedder.embed([c.embed_text for c in batch])
        if len(vectors) != len(batch):
            raise InvariantError(
                f"{embedder.name} returned {len(vectors)} vectors for {len(batch)} "
                "chunks. A silent misalignment here would attach every vector to the "
                "wrong chunk, so it is fatal rather than warned about."
            )
        store.set_embeddings(zip([c.id for c in batch], vectors, strict=True))
        report.embedded += len(batch)
        report.batches += 1
        if progress is not None:
            progress(report.embedded, len(pending))

    return report


def guard_embedding_space(
    store: SqliteStore, embedder: Embedder, workspace_id: str, *, pending: int
) -> None:
    """Refuse to add vectors from one model to an index built by another.

    Two models' vectors share an index but not a geometry. Cosine distance
    between them is still a number, so nothing raises and nothing looks empty:
    search returns a confidently ranked list in which every ranking is noise.
    Nothing downstream can catch it either, because L3 cites whatever L2
    retrieved. It has to be refused here, at the only point where the two facts
    are both in hand.

    ``lkb doctor`` already reports config drift. Reporting is not enough for
    this one, because the damage is done by a command the report does not stop.
    """
    recorded = store.embedding_space(workspace_id)
    current = (embedder.name, embedder.dimensions)
    embedded = store.embedded_chunk_count(workspace_id)

    # The vector count is part of the condition, not an afterthought: a space
    # recorded by a run that died before writing anything binds nothing, because
    # there are no vectors for a new model to be inconsistent with.
    if recorded is not None and recorded != current and embedded > 0:
        model, dims = recorded
        raise InvariantError(
            f"this workspace was indexed with {model} ({dims} dimensions) and "
            f"the configured embedder is {embedder.name} "
            f"({embedder.dimensions} dimensions). Mixing two models in one index "
            "makes every distance meaningless without making anything fail, so "
            "it is refused. Run 'lkb index --rebuild' to drop the existing "
            "vectors and re-embed with the new model."
        )

    if not (pending or embedded):
        # No vectors and none coming. Recording a model here would have
        # `lkb doctor` report the embedding space of a store that has never
        # been indexed, which is a claim about vectors that do not exist.
        return

    # Recorded before the first batch rather than after the last, so an
    # interrupted run still leaves the space it was writing into. A store
    # embedded before this table existed records whatever it is re-indexed
    # with, which is the only claim available and is true from here on.
    store.record_embedding_space(workspace_id, *current)


def embed_query(embedder: Embedder, query: str) -> list[float]:
    """One vector for the query, through the same embedder the corpus used."""
    vectors = embedder.embed([query])
    if not vectors:
        raise InvariantError(f"{embedder.name} returned no vector for the query")
    return vectors[0]


def needs_embedding(chunks: Sequence[Chunk]) -> list[Chunk]:
    return [c for c in chunks if c.embedding is None]


__all__ = [
    "EmbedReport",
    "embed_query",
    "embed_workspace",
    "guard_embedding_space",
    "needs_embedding",
]
