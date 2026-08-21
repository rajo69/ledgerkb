# 0002. Grow the corpus rather than lower the retrieval defaults

**Date:** 2026-08-21 · **Status:** accepted

## Context

`retrieval.dense_k` and `retrieval.sparse_k` both default to 50. The fixture
corpus was 20 documents and 55 chunks. Each arm was therefore asked for about
91% of the corpus, reciprocal rank fusion combined two lists that both held
nearly everything, and `recall@20` asked the retriever to return 36% of all
chunks.

Every retrieval strategy scores about the same under those conditions. Two of
L2's criteria, "hybrid beats dense-only and BM25-only" and "contextual headers
improve recall@20 by at least 5 points", were not merely hard to satisfy: they
were unfalsifiable. A gate that cannot go red proves nothing when it goes green.

This is why L2 stayed open for weeks with its machinery merged.

## Decision

Grow the fixture corpus to a size where the shipped defaults are a choice rather
than a formality. `tests/fixtures/corpus_world.py` generates a world, and
`build_corpus.build(target, scale)` takes a scale. `MEASUREMENT_SCALE` produces
195 documents and 4,433 chunks, at which `dense_k = 50` is about 1% of the
corpus.

Scale 0 remains the 20 anchor documents and remains the default, so every figure
quoted in the tutorial, the README and the existing tests stays true.

## Alternatives

**Lower `dense_k` and `sparse_k` to fit the corpus.** Setting both to 10 would
have made fusion meaningful at 55 chunks immediately, at no cost. It was
rejected because the gate would then measure a configuration nobody ships. The
defaults are what a user gets, and the numbers L3 onward depend on have to
describe the system as delivered, not a variant tuned to make a small fixture
set behave.

**Write 200 documents by hand.** Rejected: 200 hand-written documents are 200
documents that differ in ways nobody chose, and the content stops being
reviewable at that volume.

**Commit a real corpus.** There is no real corpus. See Q4 in
04-build-handoff.md.

## Consequences

The corpus is synthetic, and one process now wrote the documents, the generator
and possibly the questions. That is a stronger version of the caveat Q4 already
recorded for metadata coverage, and it has to travel with every number L2
produces. Bringing forward Q5's second corpus is what would fix it.

The suite is about 5 seconds slower, because the measurement corpus is built
once per module for its tests.

The L1 criterion no longer pins a document count. Growing the corpus is the work
that unblocks L2, and a number inside an already-met criterion turned every
corpus contribution into an argument about editing history. The criterion now
reads "a mixed-format fixture corpus" and the count lives in the generator.

Size alone turned out not to be sufficient. See [0003](0003-vary-the-phrasing.md).
