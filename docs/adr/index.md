# Decision records

From 2026-08-19 onward, a decision significant enough to be re-litigated gets its
own file here: numbered, dated, and saying what was decided, what the alternative
was, and why.

| # | Decision | Status |
|---|---|---|
| [0001](0001-keep-the-l2-gate-metrics.md) | Keep the L2 gate metrics as written | accepted |
| [0002](0002-grow-the-corpus.md) | Grow the corpus rather than lower the retrieval defaults | accepted |
| [0003](0003-vary-the-phrasing.md) | Vary the phrasing of generated facts | accepted |
| [0004](0004-record-the-embedding-space.md) | Record the embedding space and refuse a model swap | accepted |
| [0005](0005-outside-contributions.md) | Request changes rather than merging with a maintainer fix | accepted |
| [0006](0006-measurement-provenance.md) | Every committed measurement carries its provenance | accepted |
| [0007](0007-defer-ooxml-reproducibility.md) | Defer the OOXML byte-reproducibility fix | accepted |
| [0008](0008-provider-for-the-contextual-header-ab.md) | Provider for the contextual-header A/B | proposed |

0001 through 0007 were written on 2026-08-21, after the decisions rather than
with them. That is worth knowing when reading them: they are accurate about what
was decided and why, and they were not what the decision was made from. The
practice from here is to write the record with the decision.

Everything decided before 2026-08-19 lives in the design records, where it was
written at the time:

- **Technology choices**, with the evidence and a verdict, in
  [`design/00-research-log.md`](../design/00-research-log.md).
- **Decisions that constrain later work**, in
  [`design/02-architecture.md` section 12](../design/02-architecture.md) and the
  locked list in [`design/04-build-handoff.md` section 2](../design/04-build-handoff.md).

## The format

`NNNN-short-title.md`, with these headings:

```markdown
# NNNN. Title

**Date:** YYYY-MM-DD · **Status:** proposed | accepted | superseded by NNNN

## Context
What was true that made this a decision rather than an obvious call.

## Decision
What was decided, stated in one or two sentences.

## Alternatives
What else was considered, and what would have made each of them right.

## Consequences
What this costs, and what it makes harder later.
```

## Superseding

Write a new record that says which one it replaces, and set the old one's status
to `superseded by NNNN`. Do not edit the old record's argument. The point of
keeping it is that the next person can see the reasoning rather than having to
re-derive it, and an edited record teaches nothing.

That rule is the reason the design documents in
[`design/`](../design/00-research-log.md) survive with their superseded sections marked in place
rather than tidied away.
