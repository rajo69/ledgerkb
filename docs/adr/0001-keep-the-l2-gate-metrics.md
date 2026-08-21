# 0001. Keep the L2 gate metrics as written

**Date:** 2026-08-21 · **Status:** accepted

## Context

`docs/design/04-build-handoff.md` section 10 recommends replacing L2's headline
metric. Its argument: `recall@20` over 40 questions is coarse, a 5 point
difference is two questions, and a bare positive number is not evidence that
hybrid retrieval beats either half.

That recommendation was made while the corpus was 55 chunks, when no metric
could have discriminated. The corpus is now 4,433 chunks, so the question of
which metric to use became live rather than academic.

The gate in `docs/stages.toml` still says: a golden set of 40 questions with at
least 7 unanswerable, `recall@20` at or above 0.90, hybrid beating dense-only
and BM25-only, and contextual headers adding at least 5 points.

## Decision

The L2 gate keeps the criteria it already has. The measurement runs against
`recall@20` on 40 questions.

## Alternatives

**Adopt the handoff's revision.** `recall@5` and `nDCG@10` as headline, plus
MRR, plus a hard-negatives subset, plus a bootstrap confidence interval on the
hybrid delta. Better statistics, and the criticism of `recall@20` is correct on
its own terms.

It was declined for a reason about process rather than about statistics. This
gate was written before the measurement, which is what makes passing it mean
anything. Editing the criteria while working against them, in the same week the
work is being done, removes that property. The person changing the metric is the
person who will be judged by it, and no amount of good faith fixes that.

The revision remains recorded in 04-build-handoff.md. If L8's eval work wants
it, it should be adopted there, prospectively, before any number exists.

## Consequences

The L2 result will be weaker evidence than it could have been. A 5 point hybrid
delta on 40 questions is two questions, and it will have to be reported with
that caveat rather than as a clean win.

Whoever writes the results file should record `recall@5`, `nDCG@10` and MRR
alongside the gate metric even though the gate does not ask for them. Computing
them costs nothing once the golden set exists, and it lets a later reader apply
the better metric to the same run without re-running anything.

The gate can now go red, which it could not before. See [0002](0002-grow-the-corpus.md).
