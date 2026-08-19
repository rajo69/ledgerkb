"""Hybrid retrieval: dense + sparse + headings, fused by rank, optionally reranked.

The two halves fail in different directions, which is the whole argument for
running both. Dense retrieval finds "who is accountable for the footbridge" in
a passage that never says *accountable*; BM25 finds "SCC/2026/114" and every
other identifier, name and number that an embedding smooths into its
neighbours. Council papers are full of both kinds of query.

A third arm comes free. ``heading_path`` is already stored on every chunk and
is already a structural summary — *"Planning Committee Minutes > Item 4 >
Decision"* — so matching it costs one more FTS query and no model at all. It is
the deterministic version of what a contextual header buys with an LLM call,
and running it as its own ranked list is the cheapest way to find out how much
of that benefit was ever worth paying for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerkb.core.config import Config
from ledgerkb.core.models import Hit
from ledgerkb.core.ports import Embedder, Reranker
from ledgerkb.index.embed import embed_query
from ledgerkb.index.rrf import fuse
from ledgerkb.storage.sqlite.store import SqliteStore


@dataclass
class SearchResult:
    hits: list[Hit]
    arms: dict[str, list[Hit]] = field(default_factory=dict)
    """Each retriever's own ranked list, kept for ``--explain`` and for evals
    that need to show hybrid beating either half."""
    reranked: bool = False
    query: str = ""


def search(
    store: SqliteStore,
    cfg: Config,
    query: str,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    workspace_id: str | None = None,
    k: int | None = None,
    arms: tuple[str, ...] = ("dense", "sparse", "headings"),
    include_superseded: bool = False,
) -> SearchResult:
    """Run the enabled arms, fuse them, and optionally rerank the top of the pool.

    ``embedder=None`` drops the dense arm rather than failing, so search still
    works on a store that has not been embedded yet — degraded, and it says so
    by which arms come back.
    """
    filters = {"workspace_id": workspace_id, "include_superseded": include_superseded}
    lists: dict[str, list[Hit]] = {}

    if "dense" in arms and embedder is not None:
        vector = embed_query(embedder, query)
        lists["dense"] = store.search_dense(vector, cfg.retrieval.dense_k, **filters)

    if "sparse" in arms:
        lists["sparse"] = store.search_sparse(query, cfg.retrieval.sparse_k, **filters)

    if "headings" in arms:
        # Recorded even when empty: "this arm ran and found nothing" is a
        # different fact from "this arm was not run", and the eval that has to
        # show hybrid beating either half needs to tell them apart.
        lists["headings"] = store.search_headings(query, cfg.retrieval.sparse_k, **filters)

    fused = fuse(lists, k=cfg.retrieval.rrf_k, limit=cfg.retrieval.fuse_to)
    result = SearchResult(hits=fused, arms=lists, query=query)

    top = k if k is not None else cfg.retrieval.rerank_to
    if reranker is not None and fused:
        ordered = reranker.rerank(query, [h.text for h in fused], top)
        result.hits = [
            fused[i].model_copy(update={"score": score, "method": "rerank"})
            for i, score in ordered
        ]
        result.reranked = True
    else:
        result.hits = fused[:top]

    return result


def explain(result: SearchResult) -> list[dict[str, object]]:
    """Per-candidate dense rank, sparse rank and fused score.

    The L2 gate asks for this by name, and it is the only way to tell a
    retrieval win from a lucky ordering.
    """
    return [
        {
            "chunk_id": hit.chunk_id,
            "score": round(hit.score, 6),
            "method": hit.method,
            "ranks": hit.ranks,
            "heading_path": " > ".join(hit.heading_path),
            "page_from": hit.page_from,
            "preview": hit.text[:160].replace("\n", " "),
        }
        for hit in result.hits
    ]


__all__ = ["SearchResult", "explain", "search"]
