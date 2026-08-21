# 0006. Every committed measurement carries its provenance

**Date:** 2026-08-21 · **Status:** accepted

## Context

L2's gate says numbers must be "measured, printed and committed". Several later
gates say the same. Nothing specifies what a committed measurement looks like,
and no measurement has been taken yet, so there is nothing to retrofit.

This is the last moment at which the format can be decided honestly. Once a
number exists, any provenance rule written afterwards is a rule the first result
was not held to.

The repository already has most of the inputs. `uv.lock` pins the environment
exactly, `Config.build_receipt()` produces the resolved config, the corpus is a
deterministic function of its scale, and `embedding_space` now records which
model made the vectors.

## Decision

A committed measurement lives in `results/` as a pair: a Markdown file for
reading and a JSON file with the same stem for machines. Both carry the same
header, and the header is written by the eval runner, never by hand.

```
run_at              ISO 8601, UTC
ledgerkb_commit     git SHA, with a dirty flag if the tree was not clean
lockfile_sha256     hash of uv.lock
config_hash         hash of Config.build_receipt()
corpus_scale        the scale argument
corpus_documents    count
corpus_chunks       count
golden_set_sha256   hash of the golden set file
embedding_model     from embedding_space, not from config
embedding_dims      from embedding_space
python              version
platform            OS and CPU
command             the exact command that produced this file
```

A result whose tree was dirty at run time is marked and is not admissible as
gate evidence.

## Alternatives

**Print to the terminal and quote the numbers in prose.** What the gate text
literally permits. Rejected: a figure in a document with no artifact behind it
cannot be re-derived, and the repository's own writing rule says any figure
should be reproducible by running something.

**JSON only.** Rejected because nobody reads it, and the point of committing a
result is that a human can see what changed between two runs in a diff.

**Markdown only.** Rejected because a later stage will want to compare runs
programmatically, and parsing prose is how numbers get misquoted.

## Consequences

The eval runner cannot be written as a script that prints. It has to collect the
header, which means it needs the store, the config and the git state, and that
shapes its interface before the first line is written.

Recording `embedding_model` from `embedding_space` rather than from config is
deliberate, and follows [0004](0004-record-the-embedding-space.md): the config
says what was asked for and the store says what the vectors were made with. A
result should describe the run, not the intent.

`results/` is not `.gitignore`d and should not become large. If a stage starts
producing results per commit, that is a signal to keep the last one per gate and
let git history hold the rest.

[0001](0001-keep-the-l2-gate-metrics.md) asks for `recall@5`, `nDCG@10` and MRR
to be recorded alongside the gate metric even though the gate does not require
them. They cost nothing once the golden set exists and they let a later reader
apply a better metric without re-running anything.
