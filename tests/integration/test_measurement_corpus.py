"""The generated corpus that L2's measurement runs on.

The anchor corpus is checked by ``test_ingest_pipeline.py``. This file checks
the generated half, and it checks the two properties the measurement depends
on rather than every property a corpus could have.

The first is size. L2's gate could not go red at 59 chunks, because ``dense_k``
and ``sparse_k`` both default to 50 and each arm was therefore asked for most
of the corpus. A test that only asserted "the corpus builds" would let that
regress silently, so the size assertion is written against the retrieval
defaults rather than against a number somebody typed.

The second is the decoy structure. A large corpus of unrelated documents is as
easy to retrieve from as a small one. What makes a retrieval measurement
discriminate is several documents that share almost all of their vocabulary and
differ in the one figure the question asks about.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ledgerkb.core.config import ChunkingConfig, RetrievalConfig
from ledgerkb.core.ports import ParseHint
from ledgerkb.ingest.chunk import chunk_document
from ledgerkb.ingest.metadata import REQUIRED_FIELDS, extract_metadata
from ledgerkb.ingest.parsers.registry import registry
from tests.fixtures.build_corpus import MEASUREMENT_SCALE, build
from tests.fixtures.corpus_world import (
    ALLOCATION_PHRASINGS,
    PROGRAMMES,
    generated_documents,
)


def _longest_literal(template: str) -> str:
    """The longest run of fixed words in a phrasing, which identifies it."""
    return max(re.split(r"\{[a-z]+\}", template), key=len).strip()


@pytest.fixture(scope="module")
def measurement_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("measurement")
    build(root / "corpus", scale=MEASUREMENT_SCALE)
    return root / "corpus"


@pytest.fixture(scope="module")
def parsed(measurement_corpus: Path) -> list[tuple[Path, object]]:
    out = []
    for path in sorted(measurement_corpus.iterdir()):
        doc = registry.parse(path.read_bytes(), ParseHint(filename=path.name))
        out.append((path, doc))
    return out


class TestSize:
    def test_the_corpus_is_large_enough_for_dense_k_to_discriminate(self, parsed) -> None:
        """The condition L2's gate needs, stated against the config, not a number.

        At 59 chunks, dense_k = 50 covered 85% of the corpus and every strategy
        scored about the same. Ten times the candidate pool is the point at
        which asking for 50 candidates is a choice rather than a formality.
        """
        cfg = RetrievalConfig()
        total = sum(len(chunk_document(d, "ws", "v")) for _, d in parsed)
        assert total >= cfg.dense_k * 10, (
            f"{total} chunks against dense_k={cfg.dense_k}: too small to measure on"
        )

    def test_recall_at_20_asks_for_a_small_fraction_of_the_corpus(self, parsed) -> None:
        """recall@20 over 55 chunks asked the retriever for 36% of everything."""
        total = sum(len(chunk_document(d, "ws", "v")) for _, d in parsed)
        assert 20 / total < 0.02

    def test_every_document_parsed(self, parsed, measurement_corpus: Path) -> None:
        assert len(parsed) == len(list(measurement_corpus.iterdir()))
        assert all(d.text.strip() for _, d in parsed)


class TestTheInvariantHoldsAtScale:
    def test_every_chunk_slices_back_byte_identical(self, parsed) -> None:
        """The L1 invariant, over 4000-odd chunks rather than 55.

        The property test in ``tests/property/test_offsets.py`` runs over
        synthetic documents and never sees parser output. The anchor corpus
        runs over 20 documents. This is the same invariant over the corpus the
        retrieval numbers will actually be computed from.
        """
        for path, doc in parsed:
            for c in chunk_document(doc, "ws", "v", ChunkingConfig()):
                assert doc.text[c.char_start : c.char_end] == c.text, path.name

    def test_metadata_coverage_clears_the_l1_gate(self, parsed) -> None:
        found = 0
        for path, doc in parsed:
            meta = extract_metadata(doc, filename=path.name, uri=f"file://{path.name}")
            found += sum(
                1 for f in REQUIRED_FIELDS if getattr(meta, f) not in (None, "", [])
            )
        coverage = found / (len(parsed) * len(REQUIRED_FIELDS))
        assert coverage >= 0.90, f"metadata coverage {coverage:.0%}"


class TestDecoys:
    """The property that makes the measurement worth running."""

    def test_a_programme_is_described_with_four_different_figures(self) -> None:
        """One question, one right answer, three near-identical wrong ones.

        Without this a large corpus is no harder to retrieve from than a small
        one: BM25 finds the single document containing the rare term and every
        arm agrees with it.
        """
        for prog in PROGRAMMES:
            assert len(set(prog.budgets)) == 4, prog.name

    def test_the_same_figure_appears_in_several_documents(self) -> None:
        """The decoys have to be spread across documents, not stacked in one."""
        docs = generated_documents(MEASUREMENT_SCALE)
        prog = PROGRAMMES[0]
        holding = [
            d for d in docs
            if isinstance(d.payload, str) and prog.name in d.payload
        ]
        assert len(holding) >= 10, f"only {len(holding)} documents mention {prog.name}"

    def test_the_same_fact_is_not_always_stated_the_same_way(self) -> None:
        """Templated decoys measure the fixtures rather than the retriever.

        Four sentences differing by one number sit almost on top of each other
        under an embedding model, so the dense arm cannot separate them, while
        BM25 has exact tokens for the year and the amount. A corpus shaped that
        way answers "BM25 was enough" before the retriever gets a say, and the
        gate asks precisely whether hybrid beats BM25-only.
        """
        body = "\n".join(
            d.payload for d in generated_documents(MEASUREMENT_SCALE)
            if isinstance(d.payload, str)
        )
        used = [t for t in ALLOCATION_PHRASINGS if _longest_literal(t) in body]
        assert len(used) >= 5, (
            f"only {len(used)} of {len(ALLOCATION_PHRASINGS)} phrasings reach "
            "the corpus, so the decoys are closer to copies than to duplicates"
        )

    def test_every_phrasing_keeps_the_amount_and_the_year(self) -> None:
        """The wording varies; the facts do not.

        BM25 is entitled to the handle it is good at. Varying the phrasing to
        help the dense arm must not quietly remove the exact tokens that make
        the sparse arm a fair comparison.
        """
        for template in ALLOCATION_PHRASINGS:
            assert "{amount}" in template, template
            assert "{fy}" in template, template

    def test_generation_is_a_pure_function_of_the_scale(self) -> None:
        """No clock, no seed, no filesystem order. Same input, same corpus."""
        first = generated_documents(4)
        second = generated_documents(4)
        assert [(d.name, d.kind) for d in first] == [(d.name, d.kind) for d in second]
        assert [repr(d.payload) for d in first] == [repr(d.payload) for d in second]


class TestScaleZeroIsUnchanged:
    def test_the_anchor_corpus_is_still_exactly_the_anchor_corpus(
        self, tmp_path: Path
    ) -> None:
        """The tutorial and the README quote figures from scale 0.

        Growing the corpus for L2 must not silently rewrite the numbers on
        every page that documents the anchor set.
        """
        written = build(tmp_path / "anchors")
        assert len(written) == 20
        assert generated_documents(0) == []
