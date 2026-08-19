# One ledger, and why everything else is a projection

The obvious way to build this system is to write three things from the same
documents: a vector index for retrieval, a graph for structure, and a wiki for
reading. Three pipelines, three outputs, run them in parallel.

That gives you three sources of truth. The vector store says one thing, the graph
says another, the wiki a third, and nothing reconciles them. Worse, they drift
apart silently: nobody notices until a user asks the same question of two surfaces
and gets two answers.

The design here is one append-only ledger of evidence-bearing assertions, and
everything a user sees is a projection of it. The retrieval index, the knowledge
graph, the wiki bundle, the briefing document and the change report are five views
over one table.

## What that buys, for free

**Belief revision becomes a write, not a rewrite.** When a new document
contradicts an old claim, the old assertion gets an `invalid_at`, an
`invalidated_by` pointing at what replaced it, and a reason. Nothing is deleted.
History is therefore queryable rather than reconstructible.

**The change report becomes a diff.** Two ingest runs, two ledger states, and the
difference between them is the report. No separate machinery, no summarisation
pass over the documents, and no risk of the report disagreeing with the data it
describes.

**Governance becomes a query.** "What is ageing fastest" is `stale_after`
ascending. "What rests on a single source" is a count over evidence rows. "What
has no owner" is a null check. A governance guide generated this way cannot
contain generic filler, because every line traces to a row.

**Citations cannot drift.** Every projection carries the same `chunk_id`, and
every `chunk_id` resolves to a character span in an immutable document version.
The wiki, the briefing and the graph all cite the same thing because they are all
reading the same column.

## The bitemporal part

An assertion carries two pairs of dates:

- **World time**: `valid_from` and `valid_to`. When the claim was true out there.
- **System time**: `asserted_at` and `invalid_at`. When this system believed it.

Keeping both is what makes the interesting question answerable: as of 12 June,
what did we believe was true about Q3? A latest-state snapshot cannot answer that,
at any price, because the information was overwritten.

It is also what distinguishes two things that look identical in a snapshot: a fact
that changed in the world, and a fact we were wrong about. The first is a
`superseded` invalidation with a later `valid_from`. The second is `corrected`.
For records work, that distinction is often the whole finding.

## Contradictions are not resolved

When two sources disagree and neither is clearly later, both assertions stay
active and both are marked `disputed`. The store never picks a winner.

The instinct is to pick one, or to blend them into a hedged sentence. Both are
wrong here. An unexplained figure changing between two documents is not noise to
be smoothed away, it is the thing somebody needs to know about. A system that
quietly resolves it has destroyed the finding and replaced it with false
confidence.

Display may vary: a reader can show the more recent one first, or collapse the
pair behind a marker. The store may not. That is a tier-4 rule with no
configuration key, which is the subject of [Tunability tiers](tunability-tiers.md).

## The cost

One rebuild step. Projections are derived, so changing how the graph is shaped or
how the wiki is laid out means regenerating them from the ledger rather than
migrating them in place. That is a real cost, and it is worth paying, because the
alternative is three write paths that will disagree with no way to tell which one
is right.

## What exists today

The ledger tables exist, with their constraints and their triggers. Nothing writes
to them: extraction is L4. Of the five projections, retrieval is built and the
other four are not. [ROADMAP.md](https://github.com/rajo69/ledgerkb/blob/main/ROADMAP.md) has the detail.

This page describes the organising idea the code is being built towards, and the
schema it already commits to.
