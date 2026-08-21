# 0007. Defer the OOXML byte-reproducibility fix

**Date:** 2026-08-21 · **Status:** accepted

## Context

`build_corpus.py` says the corpus "regenerates deterministically on every
machine". At the level that matters today that is true: every Markdown, text,
HTML, email, JSON, CSV and PDF file is byte-identical across two builds, so the
extracted text and every chunk boundary are stable.

It is not true of the bytes. Two builds of the measurement corpus differ in 29
files, all `.docx`, `.xlsx` and `.pptx`, because python-docx, openpyxl and
python-pptx stamp the current time into the OOXML container. This predates the
corpus work: one of the differing files is an anchor document that has been in
the repository since L1.

The consequence is that those files get a new content hash on every rebuild.
Ingest dedupes by content hash, so a rebuilt corpus looks like 29 modified
documents to a store built from the previous one.

## Decision

Leave it. Record it here, in the L2 handoff, and as a known limitation, and fix
it when L6 needs it.

## Alternatives

**Fix it now** by post-processing each archive to normalise the ZIP timestamps
and strip the core-properties dates. Perhaps an hour of work across three
writers. Rejected as scope: it is unrelated to unblocking L2's measurement, it
touches the anchor corpus that every existing test depends on, and doing it
inside a corpus-growth change would hide it.

**Weaken the claim in the docstring** to say the text is deterministic rather
than the corpus. Rejected as the worst option: it makes the sentence true by
lowering the bar, and the honest problem disappears from view.

**Commit the OOXML fixtures as binaries** so they never regenerate. Rejected:
the whole reason the corpus is generated is that a reviewer can diff its
content.

## Consequences

The claim in `build_corpus.py` is currently stronger than what the code
delivers. That is exactly the kind of over-claim this project's documentation
rules exist to prevent, and it is left standing deliberately rather than by
oversight. It should be fixed rather than reworded.

It bites at L6, where content-hash diffing decides what changed between two
ingest runs. A test that rebuilds the corpus and expects "unchanged" will see 29
modified documents, and the L6 criterion "unchanged documents cost zero LLM
calls" will fail for a reason that has nothing to do with L6.

Whoever picks this up should treat the fix as a prerequisite of L6 rather than a
tidy-up, and should assert byte equality across two builds as the regression
test, since that is the property currently claimed.
