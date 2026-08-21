# Build the measurement corpus

The fixture corpus comes in two sizes. This page is about the larger one, what
it is for, and why it is generated rather than written.

## The two sizes

```bash
# the anchor corpus: 21 documents, 59 chunks
python tests/fixtures/build_corpus.py ./demo

# the measurement corpus: 196 documents, 4,437 chunks
python tests/fixtures/build_corpus.py ./demo 11
```

The second argument is the scale. Scale 0 is the anchor set, which is what the
tutorial uses and what every ingest and offset test runs against: 21 documents
prove that each format parses as well as 200 do, and they keep the suite fast.
Scale 11 is `MEASUREMENT_SCALE`, the corpus the L2 retrieval numbers are
computed on.

Both are written by the same code and share the same 21 anchor documents, so a
question written against the anchor set is still valid against the larger one.

## Why the larger one exists

`retrieval.dense_k` and `retrieval.sparse_k` both default to 50. Against 55
chunks that asks each arm for most of the corpus, reciprocal rank fusion then
combines two lists that both contain nearly everything, and every retrieval
strategy scores about the same. `recall@20` asks for 36% of the corpus.

L2's gate has four criteria that are measurements, including "hybrid beats
dense-only and BM25-only". None of them can fail at that size, and a gate that
cannot fail proves nothing. At 4,437 chunks, `dense_k = 50` is about 1% of the
corpus and `recall@20` asks for less than half of one percent.

There is a test for this, in `tests/integration/test_measurement_corpus.py`,
and it is written against `RetrievalConfig` rather than against a fixed number,
so raising `dense_k` without growing the corpus fails the build.

## Why it is generated

Size is not the only thing that makes a retrieval measurement discriminate. A
corpus of 200 documents about 200 unrelated subjects is as easy as a corpus of
20: BM25 finds the one document containing the rare term, the dense arm agrees,
and fusion has nothing to do.

What discriminates is near-identical documents that differ in the one fact the
question asks about. So `tests/fixtures/corpus_world.py` holds a small world,
and every capital programme in it carries four different budget figures across
four quarters. The document dated in a given quarter states that quarter's
figure. Ask what a programme's allocation was for a given year and there is
exactly one correct chunk and three decoys that share almost all of their
vocabulary with it.

The facts are the decoys; the wording is not. An earlier version stated every
budget in one byte-identical sentence, varying only the programme, the date and
the amount. That is a corpus of copies rather than near duplicates, and it
biases the measurement it exists to support: templated text collapses under an
embedding model, so the dense arm cannot separate four sentences differing by
one number, while BM25 has exact tokens for the year and the amount. A corpus
shaped that way answers "BM25 was enough" before the retriever gets a say.

So each fact is stated several ways, chosen by document index. Every phrasing
keeps the amount and the financial year as literal tokens, so BM25 keeps the
handle it is entitled to, and the dense arm has real semantic variation to work
against. Both properties have tests.

The world is the reviewable source. Nothing in it is random and nothing is
seeded: every document is a function of its index, so a diff of that file is a
diff of the corpus, and two builds on two machines produce the same text.

## Writing questions against it

The L2 gate asks for the golden set to be written from the documents **before**
retrieval is run. That ordering is the whole point: questions written after
looking at what the retriever returned measure the retriever against itself.

Read the documents first:

```bash
python tests/fixtures/build_corpus.py ./demo 11
ls ./demo/corpus | head -40
```

The shapes worth writing questions about, in rough order of how much they
discriminate:

- **A figure that changes across quarters.** "What capital allocation was
  approved for the Darnall Regeneration Programme in 2026/27?" One right
  answer, three decoys.
- **A fact that appears in one format only.** Risk owners live in the XLSX risk
  registers and nowhere else.
- **A fact that spans two documents.** A programme's contractor is named in the
  progress report, its completion date in the slides.
- **Something the corpus does not contain.** At least 7 of the 40 must be
  unanswerable, and they have to be plausible: a programme that does not exist
  in a ward that does, or a figure for a quarter outside the window.

## The file format

One TOML file, loaded by `ledgerkb.evals.golden.load`. It records the corpus
scale it was written against, because a golden set is only meaningful against
one corpus, and the results header records which.

```toml
corpus_scale = 11

[[question]]
id = "attercliffe-allocation-2026-27"
question = "What capital allocation was approved for Attercliffe in 2026/27?"
answerable = true
shape = "figure-across-quarters"

[[question.relevant]]
document = "planning-committee-minutes-2026-03-11.md"
quote = "capital allocation of GBP 2.4m"

[[question]]
id = "hillsborough-skyway"
question = "What was allocated to the Hillsborough Skyway Programme?"
answerable = false
shape = "unanswerable"
note = "No such programme. The ward is real, which is what makes it plausible."
```

**Relevance is a quote, not a chunk id.** Chunk ids are minted at ingest, so
they change every time the corpus is rebuilt and a golden set keyed on them
would rot the first time anybody re-ran the pipeline. Naming the document and a
span of its text survives a rebuild, and it gives the file a self-check: `resolve`
locates each quote in the store and refuses if no chunk contains it. That refusal
matters more than it looks. Scoring an unfindable quote as a miss would report a
wrong question as a retrieval failure, and the two are indistinguishable in a
recall number.

Keep the quote to the shortest span that actually carries the answer. A long
quote spanning a heading boundary becomes a test of where the chunker split
rather than of what the retriever found.

`answerable` is stated rather than inferred from whether spans are present, so
a question somebody left half written cannot silently become one of the seven
unanswerable ones and meet the gate by accident. `shape` is checked against the
list above, because a typo would otherwise invent a category of one.

Structural mistakes are all reported together on load. The counts the gate asks
for, 40 questions and at least 7 unanswerable, are reported by `gate_problems()`
rather than raised, because a file with 12 questions in it is what writing a
golden set looks like on the way to 40.

## Known limitation

The corpus is synthetic, and the same process wrote the documents and the code
that reads them. That was already recorded as a caveat for metadata coverage in
the build handoff, and it applies harder here, where the questions would also be
written against documents that were generated rather than found. Treat the
resulting numbers as a floor on a friendly corpus, not as a measured property of
retrieval in general. Bringing forward a second corpus, from any public document
set unlike council minutes, is what would fix that, and it is recorded as Q5 in
[the build handoff](../design/04-build-handoff.md).
