# Decision records

From 2026-08-19 onward, a decision significant enough to be re-litigated gets its
own file here: numbered, dated, and saying what was decided, what the alternative
was, and why.

Nothing is here yet. Everything decided before that date lives in the design
records, where it was written at the time:

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
