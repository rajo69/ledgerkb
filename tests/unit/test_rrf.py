"""Reciprocal rank fusion — pure, so it is testable without a store or a model."""

from __future__ import annotations

import pytest

from ledgerkb.core.models import Hit
from ledgerkb.index.rrf import fuse


def hit(chunk_id: str, score: float = 0.0, method: str = "dense") -> Hit:
    return Hit(chunk_id=chunk_id, score=score, text=f"text of {chunk_id}", method=method)


class TestFusion:
    def test_a_candidate_found_by_both_arms_beats_one_found_first_by_one(self) -> None:
        """The whole reason to run two retrievers.

        `b` is second in both lists; `a` is first in one and absent from the
        other. Agreement wins, which is what hybrid retrieval is buying.
        """
        dense = [hit("a"), hit("b")]
        sparse = [hit("c", method="sparse"), hit("b", method="sparse")]
        out = fuse({"dense": dense, "sparse": sparse}, k=60)
        assert out[0].chunk_id == "b"

    def test_scores_are_the_sum_of_reciprocal_ranks(self) -> None:
        out = fuse({"dense": [hit("a")], "sparse": [hit("a", method="sparse")]}, k=60)
        assert out[0].score == pytest.approx(2 / 61)

    def test_incomparable_input_scores_are_ignored(self) -> None:
        """Cosine 0.83 and BM25 -7.2 are not on one scale, so only rank counts."""
        dense = [hit("a", score=0.99), hit("b", score=0.98)]
        sparse = [hit("b", score=-2000.0, method="sparse")]
        by_rank = fuse({"dense": dense, "sparse": sparse}, k=60)
        dense_shuffled = [hit("a", score=0.01), hit("b", score=0.001)]
        assert [h.chunk_id for h in by_rank] == [
            h.chunk_id for h in fuse({"dense": dense_shuffled, "sparse": sparse}, k=60)
        ]

    def test_every_result_is_marked_fused(self) -> None:
        out = fuse({"dense": [hit("a")]}, k=60)
        assert out[0].method == "rrf"

    def test_ranks_are_carried_through_for_explain(self) -> None:
        out = fuse({"dense": [hit("x"), hit("a")], "sparse": [hit("a", method="sparse")]}, k=60)
        found = next(h for h in out if h.chunk_id == "a")
        assert found.ranks == {"dense": 2, "sparse": 1}

    def test_a_third_arm_needs_no_signature_change(self) -> None:
        out = fuse(
            {
                "dense": [hit("a")],
                "sparse": [hit("b", method="sparse")],
                "headings": [hit("a", method="sparse")],
            },
            k=60,
        )
        assert out[0].chunk_id == "a"

    def test_ties_break_deterministically(self) -> None:
        """Same inputs, same order, every run — otherwise eval numbers wobble."""
        lists = {
            "dense": [hit("z"), hit("y")],
            "sparse": [hit("y", method="sparse"), hit("z", method="sparse")],
        }
        assert [h.chunk_id for h in fuse(lists, k=60)] == ["y", "z"]

    def test_limit_truncates_after_fusing_not_before(self) -> None:
        dense = [hit(c) for c in "abcde"]
        sparse = [hit("e", method="sparse")]
        out = fuse({"dense": dense, "sparse": sparse}, k=60, limit=2)
        assert [h.chunk_id for h in out] == ["e", "a"]

    def test_empty_input_is_not_an_error(self) -> None:
        assert fuse({}, k=60) == []
        assert fuse({"dense": []}, k=60) == []

    def test_k_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="rrf k"):
            fuse({"dense": [hit("a")]}, k=0)
