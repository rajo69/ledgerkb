# Golden sets

Evaluation questions, written by hand against a known corpus, live here.

`l2-retrieval.toml` is the one L2 is waiting on: 40 questions, at least 7 of
them unanswerable. It does not exist yet, and the order in which it gets written
is itself the criterion.

**Write the questions from the documents, before retrieval is run even once.**
Questions written after looking at what the retriever returned measure the
retriever against itself, and no amount of care afterwards repairs that. This is
not a style preference, it is what L2's first gate criterion says.

The format, the question shapes that discriminate, and the reasoning behind both
are in
[docs/how-to/build-the-measurement-corpus.md](../docs/how-to/build-the-measurement-corpus.md).
`ledgerkb.evals.golden.load` reads the file and reports every structural problem
at once; `gate_problems()` reports the counts without refusing a file that is
still being written.

Relevance is a document and a verbatim quote, never a chunk id. Chunk ids are
minted at ingest and change on every rebuild, so a file keyed on them would rot
the first time anybody re-ran the pipeline.

Do not start writing until the corpus is frozen. See
[docs/design/06-l2-completion-handoff.md](../docs/design/06-l2-completion-handoff.md).
