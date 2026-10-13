# 0010. Freeze the measurement corpus

**Date:** 2026-08-27 · **Status:** accepted

## Context

L2's three met criteria are the code ones. The four that remain are all
measurements, and none of them has been taken. They need a corpus that has
stopped changing.

The two changes that were going to move it have landed. [#1](https://github.com/rajo69/ledgerkb/pull/1)
added the RTF anchor and [#3](https://github.com/rajo69/ledgerkb/pull/3) grew the
generated world, both on 2026-08-21. `MEASUREMENT_SCALE` is 11, which builds 196
documents and 4,437 chunks.

The obvious argument for freezing is that chunk ids are minted at ingest and a
rebuild invalidates anything keyed to them. That argument is weaker than it
looks, and it is worth saying so here rather than leaving a future reader to
notice. `evals/golden.py` already anticipated it: relevance is a document plus a
verbatim quote, never a chunk id, precisely so the file survives a rebuild.
Re-running `build_corpus.py` with the same inputs is not what a freeze protects
against.

Three things are what it protects against, and they are about content rather
than identifiers.

A change to what the documents **say** can invalidate an individual question.
`resolve()` refuses a quote no chunk contains rather than scoring it zero, which
is the right behaviour, but it means an edited budget figure turns a written
question into a load error rather than a measurement.

The decoys are the measurement. Every capital programme carries four budget
figures across four quarters, phrased several ways, so that a question about one
allocation has three near-neighbours competing with it. That structure is what
lets one retrieval strategy score differently from another, and
[0002](0002-grow-the-corpus.md) and [0003](0003-vary-the-phrasing.md) exist
because the earlier corpus did not have it. Change the generator and the number
still computes, but it is measuring a different thing than the one the gate
asks about.

Contextual headers are the exception that really is keyed to chunk ids.
`context_header` is a column on `chunk`, and [0008](0008-provider-for-the-contextual-header-ab.md)
prices the generation at roughly 2.4M tokens across 4,437 requests, which is
days of wall clock against a 1M per day cap. A rebuild during or after that run
discards it.

Three outside pull requests are open while this is being decided, two of them
touching parsers.

## Decision

The corpus is frozen. Three things may not change until L2's measurements are
recorded in `results/`:

- `tests/fixtures/corpus_world.py`, the generated world
- the anchor documents in `tests/fixtures/build_corpus.py`
- anything that alters the **extracted text** of a document already in the
  corpus, which includes a parser change to a format the corpus contains

Frozen means extracted text and chunk boundaries, not bytes. Bytes are already
not reproducible, for the reasons in [0007](0007-defer-ooxml-reproducibility.md),
so a byte-level freeze would be a claim this repository cannot currently make.

Everything else is unaffected: parsers for formats the corpus does not contain,
documentation, the CLI, the eval harness, and all L3 and later work.

The freeze lifts when the four measurements are committed. It was announced in
[issue #7](https://github.com/rajo69/ledgerkb/issues/7) and
[discussion #8](https://github.com/rajo69/ledgerkb/discussions/8) with a one-week
window for contributors to flag work in flight, so that it lands on people
before it lands on their branches.

## Alternatives

**Do not freeze. Re-resolve the golden set after each corpus change.** Cheap for
the questions, because quotes survive a rebuild by design. Rejected because it
does nothing for the other two problems. The decoy structure would drift under
the measurement, and the contextual-header run would have to be repeated at 2.4M
tokens each time. It also quietly moves the burden onto whoever notices that a
committed number no longer describes the corpus in the repository.

**Freeze the anchors, leave `corpus_world.py` open.** Tempting, because the
generator is where contributors would most naturally improve the corpus.
Rejected because the generator is the part that decides whether the measurement
discriminates at all. The anchors are 21 documents of texture; the generator
produces the other 175 and every decoy in them.

**Freeze after the golden set is written rather than before.** Rejected on the
ordering rule that L2's third criterion already states. A question written
against a corpus that then changes has to be edited to survive, and editing a
question after seeing that it broke is the point at which the author starts
shaping questions around the corpus rather than from it.

**Commit a built snapshot of the corpus instead of freezing the generator.**
This is the strongest alternative and it was rejected on two grounds rather than
one. The corpus is not byte-reproducible, so the snapshot would be one arbitrary
build of 196 files including binary OOXML, which is heavy in git and impossible
to diff usefully. More importantly it would not work: a parser change alters
extracted text from identical bytes, so a snapshot freezes the input and leaves
the thing actually being measured free to move.

## Consequences

Parser contributions for formats already in the corpus are queued rather than
merged until the freeze lifts. That cost falls on outside contributors at the
moment contributor interest is highest, which is the worst possible timing, and
it is accepted because the alternative is a measurement nobody should believe.

The three open pull requests were checked rather than assumed, and none of them
invalidates the corpus. #5 changes the RTF parser only for input the generator
cannot produce, since `_rtf_escape` emits `\u` only through
`f"\\u{ord(ch)}?"` and `ord()` is always positive and never above `0x10FFFF`.
#4's ODT parser adds a format the corpus does not contain. #6 is documentation.

Two pieces of work are unblocked by this record and by nothing else: the golden
set can be written, and contextual-header generation can start. [0008](0008-provider-for-the-contextual-header-ab.md)
said the key was never what that criterion was waiting for, and this is the
thing it was waiting for instead.

**The freeze is a policy and not a mechanism, and nothing enforces it.** The
sharpest version of that gap is Renovate. It is configured to group minor and
patch bumps into one pull request, `lockFileMaintenance` runs weekly, and the
parser dependencies are range-pinned rather than exact: `pypdfium2>=4.30,<6`,
`python-docx>=1.1,<2`, `openpyxl>=3.1,<4`, `python-pptx>=1.0,<2`,
`selectolax>=0.3.21,<1`. A grouped `chore` bump can therefore change what any of
those extract from an unchanged file, breaking the freeze without a single
corpus file appearing in the diff. Until the measurements are recorded, a
dependency bump touching a parser needs reading as a corpus change.

What would turn this into a mechanism is a committed hash per document of its
extracted text, checked in CI. That is the planned next step, and building it
now would delay the measurement it protects. It is written down here so the next person
does not have to rediscover that the freeze rests on nobody forgetting.
