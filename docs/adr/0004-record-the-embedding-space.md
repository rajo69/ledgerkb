# 0004. Record the embedding space and refuse a model swap on the index path

**Date:** 2026-08-21 · **Status:** accepted

## Context

The store knew what dimension its vectors had to be and nothing about which
model produced them. `embed_workspace` compared `embedder.dimensions` against
`embeddings.dimensions` and refused a mismatch, which catches a 384-wide model
in a 1024-wide store.

It does not catch the case that matters: two models of the same width. Their
vectors sit in different geometries, and cosine distance between them is still a
number. An index holding both returns a confidently ranked list in which every
ranking is noise. Nothing raises, nothing looks empty, and no later stage can
detect it, because L3 cites whatever L2 retrieved. The first visible symptom
would be a citation pointing at the wrong chunk.

`config_stamp` already recorded the config a store was built with, and
`lkb doctor` already reported drift from it.

## Decision

Migration 005 adds `embedding_space`, one row per workspace holding the model
and dimension its vectors were made with. `guard_embedding_space` runs on the
index path and refuses to add vectors from a different embedder.

It records what the embedder reported, not what the config asked for.
`config_stamp` is the record of intent; this is the record of fact.

## Alternatives

**Leave it to `lkb doctor`.** The drift was already reported. Rejected because
reporting is not a mechanism: the damage is done by a command the report does
not stop, and the L2 criterion says so explicitly, "not only by lkb doctor".

**Store the model per vector rather than per workspace.** Would allow a mixed
index to be queried correctly by filtering to one model. Rejected as solving a
problem nobody has: there is no use for a deliberately mixed index, and the
column would cost a row-width increase across every chunk.

**Refuse at search time instead.** Search is where the damage shows, so this is
tempting. Rejected because `hybrid.search` deliberately degrades rather than
fails, dropping the dense arm when no embedder is available. A hard refusal
there would contradict a decision already taken. The gap is real and is recorded
in the consequences below.

## Consequences

`lkb index --rebuild` clears the record with the vectors, so changing model
stays one command.

Three details are load-bearing rather than incidental, and each has a test. The
refusal fires even when nothing is left to embed, because a model swapped on a
fully embedded workspace has no pending chunks and the CLI used to return before
reaching the check. The vector count is part of the condition, so a record left
by a run that died before writing anything binds nothing. Nothing is recorded
when there are no vectors and none coming, so `lkb doctor` does not report the
embedding space of a store that has never been indexed.

**Still open:** the search path does not check. A store indexed with model A and
then queried through a config naming model B will embed the query with B and
compare it against A's vectors, silently. The index path now makes that state
hard to reach, but it is reachable by editing config and running only `lkb
search`. Closing it means deciding whether search refuses or degrades, which is
a separate decision.
