"""Retrieval metrics.

These are pure functions, so they are checked against worked examples rather
than against themselves. Every non-obvious expected value below is written as
the arithmetic that produces it, so a reader can confirm the number without
running anything. That is the whole reason the metrics were kept free of the
store, the config and the corpus.

The cases that matter are the boundaries and the refusals. An off-by-one at the
`k` cutoff moves `recall@20` by a whole question out of forty, and a metric that
quietly scored an unanswerable question would put a number in the results file
that means nothing.
"""

from __future__ import annotations

import re
from math import log2
from pathlib import Path

import pytest

from ledgerkb.evals import metrics

ROOT = Path(__file__).resolve().parents[2]


def ids(*positions: int, length: int = 30) -> list[str]:
    """A ranked list of `length` chunk ids, with `positions` (1-based) marked.

    Returns the list; the marked ids are `c1`, `c2` and so on at those ranks.
    """
    out = [f"filler{i}" for i in range(1, length + 1)]
    for position in positions:
        out[position - 1] = f"c{position}"
    return out


class TestTheGateNumberComesFromTheRoadmap:
    def test_gate_k_matches_stages_toml(self) -> None:
        """Otherwise the harness could report a metric the gate does not ask for."""
        text = (ROOT / "docs" / "stages.toml").read_text(encoding="utf-8")
        criterion = next(line for line in text.splitlines() if "recall@" in line)
        assert f"recall@{metrics.GATE_K}" in criterion
        assert "0.90" in criterion


class TestRecall:
    def test_everything_relevant_in_the_top_k(self) -> None:
        assert metrics.recall_at_k(ids(1, 2), {"c1", "c2"}, 20) == 1.0

    def test_nothing_relevant_retrieved(self) -> None:
        assert metrics.recall_at_k(ids(), {"missing"}, 20) == 0.0

    def test_half_of_them(self) -> None:
        assert metrics.recall_at_k(ids(1), {"c1", "elsewhere"}, 20) == 0.5

    def test_the_cutoff_is_inclusive_at_k(self) -> None:
        """A hit at rank 20 counts and a hit at rank 21 does not.

        One question out of forty is 2.5 recall points, so an off-by-one here
        would move the gate result on its own.
        """
        assert metrics.recall_at_k(ids(20), {"c20"}, 20) == 1.0
        assert metrics.recall_at_k(ids(21), {"c21"}, 20) == 0.0

    def test_a_shorter_list_than_k_is_fine(self) -> None:
        assert metrics.recall_at_k(["c1"], {"c1"}, 20) == 1.0

    def test_a_chunk_returned_twice_does_not_count_twice(self) -> None:
        """Fusion should not emit duplicates. If it ever does, the metric must
        not reward it: a bug in the retriever would otherwise raise the score."""
        ranked = ["c1", "c1", "c1"]
        assert metrics.recall_at_k(ranked, {"c1", "other"}, 20) == 0.5

    def test_duplicates_do_not_push_a_real_hit_past_the_cutoff(self) -> None:
        """Deduplication happens before truncation, so a repeated chunk cannot
        shove a genuine hit out of the top k."""
        ranked = ["dup"] * 5 + ["dup"] * 15 + ["c1"]
        assert metrics.recall_at_k(ranked, {"c1"}, 20) == 1.0


class TestNdcg:
    def test_a_perfect_ranking_scores_one(self) -> None:
        assert metrics.ndcg_at_k(ids(1, 2), {"c1", "c2"}, 10) == 1.0

    def test_one_relevant_chunk_at_rank_two(self) -> None:
        """DCG = 1/log2(3), IDCG = 1/log2(2) = 1, so nDCG = 1/log2(3)."""
        expected = 1 / log2(3)
        assert metrics.ndcg_at_k(ids(2), {"c2"}, 10) == pytest.approx(expected)
        assert expected == pytest.approx(0.63093, abs=1e-5)

    def test_two_relevant_chunks_at_ranks_one_and_three(self) -> None:
        """DCG = 1/log2(2) + 1/log2(4) = 1 + 0.5 = 1.5.

        IDCG packs both into the top two: 1/log2(2) + 1/log2(3) = 1.63093.
        nDCG = 1.5 / 1.63093 = 0.91972.
        """
        got = metrics.ndcg_at_k(ids(1, 3), {"c1", "c3"}, 10)
        assert got == pytest.approx(1.5 / (1 + 1 / log2(3)))
        assert got == pytest.approx(0.91972, abs=1e-5)

    def test_a_hit_below_k_contributes_nothing(self) -> None:
        assert metrics.ndcg_at_k(ids(11), {"c11"}, 10) == 0.0

    def test_the_ideal_is_capped_at_k(self) -> None:
        """With more relevant chunks than k, a run that fills the top k with
        relevant chunks has done everything possible and scores 1.0."""
        ranked = ["c1", "c2", "c3"]
        assert metrics.ndcg_at_k(ranked, {"c1", "c2", "c3", "unreachable"}, 3) == 1.0


class TestReciprocalRank:
    def test_first_hit_at_rank_one(self) -> None:
        assert metrics.reciprocal_rank(ids(1), {"c1"}) == 1.0

    def test_first_hit_at_rank_four(self) -> None:
        assert metrics.reciprocal_rank(ids(4), {"c4"}) == 0.25

    def test_nothing_relevant_scores_zero(self) -> None:
        assert metrics.reciprocal_rank(ids(), {"missing"}) == 0.0

    def test_it_is_not_truncated_at_k(self) -> None:
        """MRR answers how far the reader had to go. Cutting the list at k would
        flatten every deep hit into the same miss as never finding it at all."""
        assert metrics.reciprocal_rank(ids(50, length=60), {"c50"}) == pytest.approx(0.02)

    def test_the_earliest_hit_wins(self) -> None:
        assert metrics.reciprocal_rank(ids(2, 5), {"c2", "c5"}) == 0.5


class TestUnanswerableQuestionsAreRefused:
    """Scoring one would put a meaningless number in a committed result.

    1.0 says the retriever found everything it was asked for, having been asked
    for nothing. 0.0 blames it for a question with no answer. The gate says
    recall is measured on the answerable questions, so these raise instead.
    """

    def test_recall_refuses(self) -> None:
        with pytest.raises(ValueError, match="Unanswerable"):
            metrics.recall_at_k(ids(1), set(), 20)

    def test_ndcg_refuses(self) -> None:
        with pytest.raises(ValueError, match="Unanswerable"):
            metrics.ndcg_at_k(ids(1), set(), 10)

    def test_reciprocal_rank_refuses(self) -> None:
        with pytest.raises(ValueError, match="Unanswerable"):
            metrics.reciprocal_rank(ids(1), set())

    def test_score_question_refuses(self) -> None:
        with pytest.raises(ValueError, match="Unanswerable"):
            metrics.score_question("q1", ids(1), set())

    def test_a_nonsense_k_is_refused(self) -> None:
        with pytest.raises(ValueError, match="k must be at least 1"):
            metrics.recall_at_k(ids(1), {"c1"}, 0)


class TestScoringOneQuestion:
    def test_it_records_everything_adr_0001_asked_for(self) -> None:
        scored = metrics.score_question("attercliffe", ids(3), {"c3"})
        assert set(scored.recall) == set(metrics.RECALL_KS)
        assert scored.recall[5] == 1.0
        assert scored.recall[metrics.GATE_K] == 1.0
        assert scored.reciprocal_rank == pytest.approx(1 / 3)
        assert scored.ndcg == pytest.approx(1 / log2(4))

    def test_it_carries_the_counts_behind_the_ratios(self) -> None:
        """A question needing two documents is a different thing from one
        needing a single chunk, and an average of ratios hides that."""
        scored = metrics.score_question("spans-two", ids(1), {"c1", "elsewhere"})
        assert (scored.relevant_found, scored.relevant_total) == (1, 2)
        assert scored.recall[metrics.GATE_K] == 0.5

    def test_recall_at_five_and_twenty_can_disagree(self) -> None:
        scored = metrics.score_question("deep", ids(9), {"c9"})
        assert scored.recall[5] == 0.0
        assert scored.recall[metrics.GATE_K] == 1.0

    def test_the_counts_agree_with_the_headline_recall(self) -> None:
        """A hit below the gate's cutoff is not "found".

        Counted over the whole ranked list this would say 1 of 1 found next to a
        recall of 0.0, which is true of a hit at rank 400 and no use to anyone
        reading the results table.
        """
        scored = metrics.score_question("too-deep", ids(25, length=40), {"c25"})
        assert scored.recall[metrics.GATE_K] == 0.0
        assert (scored.relevant_found, scored.relevant_total) == (0, 1)
        # MRR is where a deep hit still shows up, on purpose.
        assert scored.reciprocal_rank == pytest.approx(1 / 25)


class TestAggregate:
    def test_it_averages_per_question_not_per_chunk(self) -> None:
        """The distinction the gate's 0.90 is read against.

        One question wanting four chunks and finding all four, plus three
        questions wanting one chunk and finding none. Per question that is
        (1 + 0 + 0 + 0) / 4 = 0.25. Pooled over chunks it would be 4/7 = 0.57,
        and one well-answered question would carry the run.
        """
        scores = [
            metrics.score_question("wide", ["a", "b", "c", "d"], {"a", "b", "c", "d"}),
            *(
                metrics.score_question(f"miss{n}", ["nothing"], {f"want{n}"})
                for n in range(3)
            ),
        ]
        run = metrics.aggregate(scores)
        assert run.recall[metrics.GATE_K] == 0.25
        assert run.questions_scored == 4

    def test_it_carries_the_unanswerable_count(self) -> None:
        """Passed in rather than derived, so a run that dropped the seven
        unanswerable questions cannot look complete."""
        run = metrics.aggregate(
            [metrics.score_question("q", ids(1), {"c1"})], unanswerable=7
        )
        assert run.questions_unanswerable == 7

    def test_an_empty_run_is_refused(self) -> None:
        with pytest.raises(ValueError, match="did not happen"):
            metrics.aggregate([])

    def test_the_gate_check_reads_recall_at_twenty(self) -> None:
        passing = metrics.aggregate(
            [metrics.score_question(f"q{n}", ids(1), {"c1"}) for n in range(10)]
        )
        assert passing.meets_gate()

        mixed = metrics.aggregate(
            [metrics.score_question(f"hit{n}", ids(1), {"c1"}) for n in range(8)]
            + [metrics.score_question(f"miss{n}", ["no"], {"want"}) for n in range(2)]
        )
        assert mixed.recall[metrics.GATE_K] == pytest.approx(0.80)
        assert not mixed.meets_gate()


def test_the_module_names_are_stable() -> None:
    """The runner and the report both import these by name."""
    assert re.fullmatch(r"\d+", str(metrics.GATE_K))
    for name in ("recall_at_k", "ndcg_at_k", "reciprocal_rank", "score_question"):
        assert callable(getattr(metrics, name))
