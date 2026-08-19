"""Reciprocal rank fusion.

Pure: no I/O, no provider, no store. Fusing on **rank** rather than score is
what makes hybrid retrieval work at all — a cosine similarity of 0.83 and a
BM25 score of -7.2 are not on the same scale and never will be, so any attempt
to combine the numbers directly is a fudge factor wearing a formula's clothes.
Ranks are comparable by construction.

    score(d) = sum over lists of 1 / (k + rank(d))

``k=60`` is the value from the original TREC work and the one the config
defaults to. Larger ``k`` flattens the contribution of top ranks, so a document
found by both retrievers wins more often than one found first by a single
retriever. That is exactly the behaviour hybrid retrieval exists to buy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ledgerkb.core.models import Hit


def fuse(
    lists: Mapping[str, Sequence[Hit]], *, k: int = 60, limit: int | None = None
) -> list[Hit]:
    """Fuse named ranked lists into one.

    Takes a mapping rather than two arguments so a third arm — headings, a
    graph neighbourhood, a second embedding — drops in without changing the
    signature or any caller.

    Ties break on chunk id, so the same inputs always produce the same order.
    """
    if k < 1:
        raise ValueError(f"rrf k must be >= 1, got {k}")

    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    first_seen: dict[str, Hit] = {}

    for name, hits in lists.items():
        for position, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + position)
            ranks.setdefault(hit.chunk_id, {})[name] = position
            first_seen.setdefault(hit.chunk_id, hit)

    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    if limit is not None:
        order = order[:limit]

    return [
        first_seen[cid].model_copy(
            update={
                "score": scores[cid],
                "method": "rrf",
                # Kept so `--explain` can show why a candidate placed where it
                # did without re-running either retriever.
                "ranks": dict(sorted(ranks[cid].items())),
            }
        )
        for cid in order
    ]


__all__ = ["fuse"]
