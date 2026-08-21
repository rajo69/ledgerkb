"""Retrieval metrics. Pure: no store, no config, no corpus, no golden set.

Everything here takes a ranked list of chunk ids and the set that should have
been in it, and returns a number. That is deliberate. These functions can be
checked against worked examples by hand, which is what makes them usable as
evidence rather than as another thing that has to be trusted.

``recall@20`` is L2's headline because ``docs/stages.toml`` says so.
[ADR 0001](../../../docs/adr/0001-keep-the-l2-gate-metrics.md) records that this
is a coarse choice, keeps it anyway for a reason about process rather than
statistics, and asks for ``recall@5``, ``nDCG@10`` and MRR to be recorded
alongside it. They cost nothing once the golden set exists and they let a later
reader apply a better metric to the same run without re-running anything.

**Unanswerable questions are not scored here, and that is not an oversight.**
L2's gate says recall is measured "on the answerable questions". A question with
no correct chunk has no recall: returning 1.0 would inflate the average for
retrieving nothing, and returning 0.0 would punish a retriever for a question
that has no right answer. Both are lies about the same run. The seven
unanswerable questions earn their place at L3, where the system has to decline
to answer, and the honest thing to do at L2 is count them and say they were not
scored. Passing one of them to these functions raises.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import log2

# L2's headline, from `docs/stages.toml`. A test asserts the two agree.
GATE_K = 20

# Recorded alongside it on ADR 0001's instruction, so a later reader can apply a
# better metric to the same run without re-running it.
RECALL_KS = (5, GATE_K)
NDCG_K = 10


@dataclass(frozen=True)
class QuestionScores:
    """One answerable question, scored.

    ``relevant_found`` and ``relevant_total`` are kept because an aggregate of
    ratios hides how many chunks each question was asking for, and a question
    needing two documents is a different thing from one needing a single chunk.

    ``relevant_found`` counts within the gate's ``k``, not over the whole ranked
    list, so that it always explains ``recall[GATE_K]``. Counted over the full
    list it could read "1 of 1 found" beside a recall of 0.0, which is true of a
    hit at rank 400 and useless to the person reading the table.
    """

    question_id: str
    recall: dict[int, float]
    ndcg: float
    reciprocal_rank: float
    relevant_found: int
    relevant_total: int


@dataclass(frozen=True)
class RunScores:
    """The aggregate over a golden set, and the counts behind it.

    Averaged per question rather than pooled over all relevant chunks, so a
    question needing four chunks does not outweigh four questions needing one.
    That is the usual convention, and it is the one the gate's "0.90" is read
    against.
    """

    recall: dict[int, float]
    ndcg: float
    mrr: float
    questions_scored: int
    questions_unanswerable: int

    def meets_gate(self, threshold: float = 0.90) -> bool:
        """Whether ``recall@20`` clears L2's bar."""
        return self.recall[GATE_K] >= threshold


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the relevant chunks that appear in the top ``k``."""
    wanted = frozenset(relevant)
    _require_relevant(wanted)
    _require_k(k)
    top = _top(ranked, k)
    return len(wanted & set(top)) / len(wanted)


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Normalised discounted cumulative gain, binary relevance.

    Relevance is binary because the golden set has no graded judgements: a chunk
    either contains the quote that answers the question or it does not. Inventing
    a grade would be inventing data.
    """
    wanted = frozenset(relevant)
    _require_relevant(wanted)
    _require_k(k)

    gain = sum(
        1.0 / log2(position + 1)
        for position, chunk_id in enumerate(_top(ranked, k), start=1)
        if chunk_id in wanted
    )
    # The best achievable ordering: every relevant chunk packed into the top
    # positions, capped at k because nothing below k can contribute.
    ideal = sum(1.0 / log2(position + 1) for position in range(1, min(len(wanted), k) + 1))
    return gain / ideal


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """``1 / rank`` of the first relevant chunk, or 0.0 if none was retrieved.

    Not truncated at k. MRR answers "how far down did the user have to read",
    and cutting the list off turns every deep hit into the same miss.
    """
    wanted = frozenset(relevant)
    _require_relevant(wanted)
    for position, chunk_id in enumerate(_dedupe(ranked), start=1):
        if chunk_id in wanted:
            return 1.0 / position
    return 0.0


def score_question(
    question_id: str, ranked: Sequence[str], relevant: Iterable[str]
) -> QuestionScores:
    """Every figure L2 records for one answerable question."""
    wanted = frozenset(relevant)
    _require_relevant(wanted)
    return QuestionScores(
        question_id=question_id,
        recall={k: recall_at_k(ranked, wanted, k) for k in RECALL_KS},
        ndcg=ndcg_at_k(ranked, wanted, NDCG_K),
        reciprocal_rank=reciprocal_rank(ranked, wanted),
        relevant_found=len(wanted & set(_top(ranked, GATE_K))),
        relevant_total=len(wanted),
    )


def aggregate(scores: Sequence[QuestionScores], *, unanswerable: int = 0) -> RunScores:
    """Mean the per-question figures, and carry the counts they came from.

    ``unanswerable`` is passed in rather than derived, because these scores hold
    only the answerable questions by construction and a run that silently
    forgot the other seven should not be able to look complete.
    """
    if not scores:
        raise ValueError(
            "no answerable questions to score. A run with nothing in it is not a "
            "result of zero, it is a run that did not happen."
        )
    count = len(scores)
    return RunScores(
        recall={k: sum(s.recall[k] for s in scores) / count for k in RECALL_KS},
        ndcg=sum(s.ndcg for s in scores) / count,
        mrr=sum(s.reciprocal_rank for s in scores) / count,
        questions_scored=count,
        questions_unanswerable=unanswerable,
    )


def _require_relevant(relevant: frozenset[str]) -> None:
    if not relevant:
        raise ValueError(
            "a question with no relevant chunks cannot be scored for retrieval. "
            "Unanswerable questions are counted, not scored: see the module "
            "docstring, and filter to the answerable ones before calling this."
        )


def _require_k(k: int) -> None:
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")


def _top(ranked: Sequence[str], k: int) -> list[str]:
    return _dedupe(ranked)[:k]


def _dedupe(ranked: Sequence[str]) -> list[str]:
    """First occurrence wins.

    A chunk returned twice must not count twice. Fusion should not produce
    duplicates, but a metric that silently rewards one would turn a bug in the
    retriever into a better score, which is the wrong direction for a number
    that exists to catch bugs.
    """
    seen: set[str] = set()
    out: list[str] = []
    for chunk_id in ranked:
        if chunk_id not in seen:
            seen.add(chunk_id)
            out.append(chunk_id)
    return out


__all__ = [
    "GATE_K",
    "NDCG_K",
    "RECALL_KS",
    "QuestionScores",
    "RunScores",
    "aggregate",
    "ndcg_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "score_question",
]
