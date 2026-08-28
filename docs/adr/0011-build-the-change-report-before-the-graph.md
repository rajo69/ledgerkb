# 0011. Build the change report before the graph

**Date:** 2026-08-28 · **Status:** accepted

## Context

The library track was ordered L0 through L8 numerically, which put L6, the
refresh and change report, seventh of nine. L6's own goal line calls it "the
differentiator", and it is the stage that answers the brief's shared final
challenge, the one that "turns a static knowledge collection into a Living
Knowledge System".

Ahead of it sat L5, entity resolution and a graph with ten node types and four
export formats, and behind it L7, five more export formats. Both are things the
tools this project will be compared against already do. GraphRAG and LightRAG
build a richer graph than L5 plans to. Retrieval frameworks export whatever the
application asks for.

Belief revision is the part nothing else does in the same way. Graphiti keeps a
bitemporal graph but invalidates the older fact when two disagree. Mem0 updates
in place. GraphRAG reconciles during summarisation. All of them pick a winner.
L6 is the stage where this project refuses to, and no other stage carries that
claim.

So the order meant building two stages of parity features before finding out
whether the one original idea works. On the observed pace, L2 alone has run from
7 August without closing, that is months of work before the question is answered.

A second thing was wrong and only visible from the file. L0's gate said the PyPI
name "is claimed on first publish at L8" and L8's summary said it "claims the
PyPI name", while L3's gate already required "Published to PyPI". The roadmap
contradicted itself about when the project becomes installable.

## Decision

The library track runs **L0, L1, L2, L3, L4, L6, L5, L7, L8**. L6 is built
immediately after the ledger it depends on.

Stage ids are **not** renumbered. They are identities, not sequence, and
`ROADMAP.md` now says so above the tables.

The stages are grouped into three phases, each of which must leave something
usable behind: L2 and L3 produce a cited answer with honest abstention and the
first PyPI release; L4 and L6 produce belief revision and the change report; L5,
L7 and L8 are breadth, built when something pulls them.

L6 gains a seventh gate criterion: the change report must run end to end on a
second corpus of real public documents, with the result published alongside its
limitations.

The PyPI contradiction is resolved in favour of L3. The name is claimed on the
first publish, at L3. L8 commits to core's stability behind a name already
claimed.

## Alternatives

**Keep the numeric order.** The safe reading, and it has one real argument
behind it: L6 without L5 has no entity resolution, so reconciliation cannot tell
that two documents describing the same programme in different words are talking
about one thing. L6's gate asks for change-report precision at or above 0.90 and
that is harder to reach on string identity alone. Rejected because the cost is
one gate criterion getting harder, and the benefit is learning months earlier
whether the central idea works at all. If the precision criterion cannot be met
without resolution, that is a finding worth having early rather than a reason to
have built the graph first.

**Renumber the stages so the order is numeric.** Rejected. Ten decision records,
the design documents, the README's comparison table and several merged pull
requests refer to stages by number. Renumbering makes every one of those
references quietly wrong, and this repository's whole practice is that the record
survives the decision. An out-of-order table costs one paragraph of explanation.

**Move the graph and the exports out of the roadmap entirely.** Considered,
because neither is differentiating and both are large. Rejected because L5 is a
genuine dependency for L6's precision over time and for L7's entity export, and
descoping in writing is a decision that should be taken when there is evidence,
not pre-emptively. Phase 3 being demand-driven is the softer version of the same
idea.

**Renumber only the two stages being swapped.** Rejected for the same reason as
renumbering everything, with the additional problem that L5 and L6 would then
mean different things in documents written before and after this record.

## Consequences

The change report arrives at v0.3.0 instead of v0.4.0, and the graph and its
exports move behind it. Anyone waiting for graph queries or GraphML waits longer.
That is the Analyst persona from the product spec, which that document already
ranks third of three and describes the Custodian, who L6 serves, as "the
differentiator".

L6's reconciliation must be written against an identity port rather than against
resolved entities. String identity first, with L5's resolution swapped in behind
it. If that port is not designed in from the start, L5 becomes a rewrite of L6
rather than an improvement to it, and this record is the warning.

The two-day exception in
[`design/03-implementation-plan.md`](../design/03-implementation-plan.md)
section 9 loses most of its purpose. It existed as the only route to the change
report without building everything first; the main sequence now takes nearly the
same path, so the exception survives only as the version that also skips L4.

The second-corpus criterion adds work to L6 that the roadmap did not previously
require anywhere. It is on L6 rather than L8 because a change report demonstrated
only on documents this project generated is not evidence about change reports,
and L6 is the stage that makes the claim.

Nothing built so far is invalidated. The reordering changes what comes next and
touches no merged code.
