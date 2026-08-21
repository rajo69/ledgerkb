# 0005. Request changes on outside contributions rather than merging with a fix

**Date:** 2026-08-21 · **Status:** accepted

## Context

The project received its first outside contribution, [#1](https://github.com/rajo69/ledgerkb/pull/1),
a tier-0 RTF parser. It was good work: no new dependency, a reasoned rejection
of `striprtf`, offsets recorded at append time, and a test file longer than the
parser.

Review found one defect. The raw byte buffer was not flushed when the hidden
text state changed, so a pending `\'hh` escape landed in the wrong buffer. On a
document Word actually wrote, a tracked change to a budget figure caused the
pound sign to be dropped from the visible text and filed as deleted text. The
fix is two lines.

The project has one maintainer, and `GOVERNANCE.md` says so. Merging the change
and fixing it afterwards would have been faster, and the corpus work behind it
was waiting.

## Decision

Post the review with a reproduction and the fix, request changes, and let the
contributor push it.

## Alternatives

**Merge and fix in a follow-up commit, crediting the contributor.** Faster, and
common practice. Rejected because it lands a known text-loss defect on `main`,
in a repository whose central claim is that a citation quotes the document
exactly. The defect is precisely a citation that quotes the document as saying
something it does not.

**Push the fix to the contributor's branch.** Fastest clean path, and permitted
when maintainer edits are enabled. Rejected as a matter of courtesy: editing
somebody's work without asking teaches them nothing and signals that review is a
formality.

**Close it and write the parser in house.** Rejected. The work is good and the
defect is two lines.

## Consequences

The critical path now runs through somebody outside the project. The golden set
cannot begin until #1 lands, because it changes the corpus by one anchor
document, and questions written against a corpus that then changes are questions
written against a corpus that no longer exists.

That is an accepted cost with no timeout attached. If the contributor goes
quiet, the decision to take the fix in house is a new decision and should be
recorded as one.

Two mechanics worth keeping for the next contribution. Fork pull requests arrive
with CI held at `action_required` until a maintainer approves the workflow runs,
so a contributor's "all green locally" is the only signal until somebody acts.
Check the workflows carry no secrets and that any deploy job is gated on `main`
before approving. And reproduce a defect before claiming it publicly: the review
here was posted under the maintainer's name, and a wrong one is expensive.
