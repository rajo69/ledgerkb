# L2 completion handoff

Written 2026-08-21 and updated the same day, for a session starting cold. Read
it before touching retrieval. [04-build-handoff.md](04-build-handoff.md) is
still the wider reference; its "corpus problem" section is superseded by this
one.

## Verify you are where this document thinks you are

```bash
git log --oneline -3
gh pr list --state open
uv run pytest --no-cov -q
python tests/fixtures/build_corpus.py /tmp/c 11   # 196 documents
```

Stage status is generated from `docs/stages.toml`. Do not state it anywhere
else, and do not edit the generated regions by hand.

If the suite fails only in `tests/integration/test_cli.py`, check whether your
shell exports `FORCE_COLOR`. It used to colour the CLI output and break six
substring assertions. `tests/conftest.py` now clears it before anything builds a
rich console, and `lkb search --json` no longer prints through that console at
all, but the shape of the failure is worth recognising.

## If you are starting cold, read this first

**The critical path runs through somebody outside the project.** PR #1 is an
outside contribution with changes requested: a two-line fix, a test for it,
footnotes named or warned about, and four stale counts. A review and a
real-Word-file follow-up are posted, and a check-in offering to push the fix was
posted on top of them. Nothing else in L2 can finish until it lands, because it
changes the corpus by one anchor document and everything downstream is written
against a frozen corpus.

Do not work around that by writing the golden set early. The ordering is the
criterion.

What is safe to build while it is open is anything that does not run retrieval
and does not depend on a chunk id. Three such pieces are already in, and the
list is now close to exhausted.

If the contributor stays quiet, taking the fix in house is a **new decision**
that needs its own record, per
[0005](../adr/0005-outside-contributions.md). It is not a thing to do quietly.

## Where L2 actually is

Gate 3 of 7. The machinery has been merged since `76d010c`: an OpenAI-compatible
embedder, a local in-process one, RRF, three arms (dense, BM25, heading path),
version-scoped search, and `--explain`. Migration 005 added `embedding_space`,
so the store now records which model made its vectors and `lkb index` refuses a
second one.

**Every remaining criterion is a measurement.** There is no code-only work left
in L2, which is a change from how this stage has looked until now.

| Criterion | Blocked on | Exists today |
|---|---|---|
| Golden set, 40 questions, 7+ unanswerable | the corpus freezing, then somebody writing them | the format, in `evals/golden.py`. `golden/` holds no questions |
| recall@20 >= 0.90 | the golden set, then the runner | `evals/metrics.py` and `evals/provenance.py` |
| Hybrid beats dense-only and BM25-only | the same | `hybrid.search` already takes an `arms` subset |
| Contextual headers +5 points | the corpus freezing, then `index/contextualise.py` | the provider is decided, see 0008 |

**Retrieval has still not been run against a golden set, and must not be until
one is written.** Three of the harness's four pieces are built and none of them
runs anything: `provenance.py` collects the header 0006 specifies, `golden.py`
defines what a question is and holds none, and `metrics.py` computes recall,
nDCG and reciprocal rank over a ranked list somebody else produced. They landed
ahead of step 4 on purpose, because PR #1 is blocked on somebody outside the
project and these were the pieces that needed neither the corpus frozen nor a
question written.

That did not spend the ordering constraint that matters. The runner is the one
piece left, and it is the one that cannot be built blind, because its shape
depends on questions existing.

## Read the decision records first

`docs/adr/` holds the decisions this stage rests on, with the alternatives that
were rejected and why. They are short. Reading 0001, 0002, 0003 and 0006 before
starting will save re-deriving arguments that were already had:

- [0001](../adr/0001-keep-the-l2-gate-metrics.md) why the gate metrics were not
  improved, even though the criticism of them is correct
- [0002](../adr/0002-grow-the-corpus.md) why the corpus grew instead of the
  retrieval defaults shrinking
- [0003](../adr/0003-vary-the-phrasing.md) why the generated facts are worded
  several ways, and what flattening them back into a template would cost
- [0006](../adr/0006-measurement-provenance.md) what a committed measurement has
  to carry, decided before any measurement exists
- [0008](../adr/0008-provider-for-the-contextual-header-ab.md) the provider for
  the contextual-header A/B, decided, with the options that were priced against it

## What the harness session added, and why

Second session of 2026-08-21, on `l2-corpus-growth`. Nothing here runs
retrieval, and nothing here is a met criterion.

- `evals/provenance.py`, the header 0006 specifies, gathered from git, the store
  and the environment with no argument a human can hand-write a value through.
  [0009](../adr/0009-what-makes-a-measurement-inadmissible.md) settles the three
  questions 0006 left open about the admissibility rule.
- `evals/golden.py`, the question format. Relevance is a document plus a
  verbatim quote, never a chunk id, because chunk ids are minted at ingest and a
  file keyed on them would rot on the next rebuild. `resolve()` refuses a quote
  no chunk contains rather than scoring it zero, because a zero from a wrong
  question is indistinguishable from a zero from a retriever that missed.
- `evals/metrics.py`, pure and free of the store so each figure is checkable by
  hand. `recall@20` for the gate, with `recall@5`, `nDCG@10` and MRR alongside
  because 0001 asked for them. Unanswerable questions raise rather than score.
- `SqliteStore.counts_for_workspace`, so a measurement states the size of the
  corpus it actually ran against rather than of every workspace in the store.
- A real bug, unrelated to L2 and found while chasing a test failure:
  `lkb search --json` printed through the styling console, so a shell exporting
  `FORCE_COLOR` got escape codes inside the JSON and `--json | jq` failed.

Two tests tie code to the roadmap the way nothing else does: `metrics.GATE_K` is
read back out of `docs/stages.toml`, and `golden.py`'s counts out of the same
criterion. Rewording a gate now fails the suite, which is the intended alarm.

## What the corpus session changed, and why

**The corpus stopped being the blocker.** It was 20 documents and 55 chunks
against a default `dense_k` of 50, so each arm was asked for most of the corpus
and no strategy could score differently from any other. The gate could not go
red, so passing it would have proved nothing.

`tests/fixtures/corpus_world.py` now generates a world and
`build_corpus.build(target, scale)` takes a scale. Scale 0 is the 20 anchor
documents and remains the default, so every figure quoted in the tutorial and
the README stays true. `MEASUREMENT_SCALE` is 11: **196 documents, 4,437
chunks**.

Size alone was not the point. Every capital programme carries four different
budget figures across four quarters, so a question about an allocation has one
correct chunk and three decoys sharing nearly all of its vocabulary. Without
that, 200 unrelated documents retrieve as easily as 20.

Nor was near-duplication enough on its own. The first version stated every
budget in one sentence template, which handicaps the dense arm (templated text
collapses under an embedding model) and flatters BM25 (exact tokens for the year
and the amount). The gate asks whether hybrid beats BM25-only, so that shape
would have answered the question before the retriever got a say. Each fact is
now stated several ways, chosen by document index, with the amount and the
financial year kept as literal tokens in every phrasing.

**The store learned which model made its vectors.** Migration 005 adds
`embedding_space`, and `guard_embedding_space` on the index path refuses to add
vectors from a second model. The case that made it worth doing is two models of
the same width: their vectors sit in different geometries, cosine distance
between them is still a number, and the index returns a confidently ranked list
of noise without raising. `config_stamp` and `lkb doctor` already reported the
drift, and reporting was not enough, because the damage is done by a command the
report does not stop. The refusal fires even when nothing is left to embed,
which is the case the CLI's early return used to walk past.

**Three decisions, so they are not relitigated:**

1. The L2 gate metrics stay as written in `docs/stages.toml`. The build handoff
   recommended switching to recall@5, nDCG@10, MRR and a bootstrap confidence
   interval. That was considered and declined, to avoid editing an open gate
   while working against it. The recommendation is still on the record in
   04-build-handoff.md if a later stage wants it.
2. The L1 criterion no longer pins a document count. A number inside a criterion
   that is already met made every corpus contribution a question about editing
   history.
3. RTF lands before any golden-set work. See below.

## Do these in this order

The order matters more than usual here, because two of the steps are
irreversible in practice.

1. **Land PR #1 (RTF parser).** It changes the corpus by one anchor document.
   Landing it after the golden set is written means questions written against a
   corpus that no longer exists.
2. **Land PR #3 (corpus growth).** Rebase it onto #1 first. They conflict on
   `build_corpus.py` and on the contribution-ask bullet in `CONTRIBUTING.md` and
   `README.md`. Both conflicts are small.
3. **Freeze the corpus.** After this point, changing `corpus_world.py` or the
   anchors invalidates work downstream of it.
4. **Write the golden set.** 40 questions, at least 7 unanswerable, written from
   the documents and **before retrieval is run even once**. That ordering is the
   criterion, not a style preference: questions written after seeing what the
   retriever returned measure the retriever against itself.
   [../how-to/build-the-measurement-corpus.md](../how-to/build-the-measurement-corpus.md)
   lists the question shapes that discriminate and documents the file format.
   The format itself is done, in `evals/golden.py`, and holds no questions:
   relevance is a document plus a verbatim quote rather than a chunk id, so the
   file survives a corpus rebuild, and `resolve()` refuses a quote no chunk
   contains rather than scoring it as a miss. This is the one part of step 4
   that did not have to wait for the corpus to freeze, and writing the questions
   still does.
5. **Build the eval harness** in `src/ledgerkb/evals/`, then run recall@20 and
   the hybrid-versus-arms comparison. The output format is already decided in
   [0006](../adr/0006-measurement-provenance.md): a Markdown and a JSON file in
   `results/`, sharing a provenance header the runner writes rather than a human.
   The header collection is done, in `evals/provenance.py`: `collect()` returns a
   `Provenance` that renders both halves, and `admissible` is where 0006's rule
   about a dirty tree is applied. [0009](../adr/0009-what-makes-a-measurement-inadmissible.md)
   settles the three questions 0006 left open about that rule. The metrics are
   done too, in `evals/metrics.py`, pure and free of the store so each figure can
   be checked against a worked example: `recall@20` for the gate, and
   `recall@5`, `nDCG@10` and MRR alongside it because 0001 asked for them.
   Unanswerable questions raise rather than score there, since the gate measures
   recall on the answerable ones and any number for the rest would be invented.
   What remains is the runner: wiring the golden set through `hybrid.search`
   once per arm combination, and writing the pair into `results/`. A figure that
   lives only in terminal scrollback is not a met criterion.
6. **Contextual headers**, or a written descope. The provider is settled: see
   the decision below, and note that it waits on step 3 rather than on the key.
7. **Update `docs/stages.toml`** and run `scripts/render_docs.py`. Then update
   this document to say what the numbers were, and write an ADR for any decision
   taken along the way. The practice from 0009 onward is to write the record
   with the decision rather than after it.

## The provider decision, taken

Criterion 4 needs an LLM, one call per chunk, about 2.4M tokens across 4,437
requests. Nothing else in L2 needs one: embeddings run locally through
fastembed with no key.

**Cerebras free tier**, `gpt-oss-120b` at `https://api.cerebras.ai/v1`, through
the existing OpenAI-compatible adapter.
[0008](../adr/0008-provider-for-the-contextual-header-ab.md) has the reasoning
and the options that were priced against it. The short version is that the
useful outcome is a negative one, deleting the highest-volume model call in the
system, and a negative result from a small local model could not be told apart
from a bad model.

Two things follow, and the second one is easy to get wrong:

- **Generation must be resumable.** 1M tokens a day is about two and a half days
  of wall clock, and nobody watches a job that long. `context_header` is a column
  on `chunk`, so the work remaining is the chunks without one and the operation
  is idempotent for free. Write it that way from the start.
- **The key does not unblock this.** Chunk ids are minted at ingest, so headers
  generated against a corpus that is then rebuilt die with the ids they were
  attached to. This criterion sits behind the corpus freeze in step 3 exactly as
  the golden set does. Having a key changes nothing about the ordering.

If the A/B runs, the baseline is the **heading arm**, not an unlabelled index.
Beating "no context" would be a meaningless win.

## The limitation to carry into the results

The corpus is synthetic, and the same process wrote the documents, the
generator, and (if nobody else writes them) the questions. Q4 in
04-build-handoff.md already recorded this for metadata coverage, where the
extractor and the fixtures were adjusted together and the coverage figure
stopped meaning much. It applies harder to a retrieval measurement.

Treat whatever comes out as a floor on a friendly corpus, not as a measured
property of retrieval. Q5's second corpus, from any public document set unlike
council minutes, is what would fix it, and bringing it forward from v1.0 is
worth arguing for before L3 depends on these numbers.

## Two things known and not fixed

- **The corpus is not byte-reproducible.** 29 files differ between two builds,
  all `.docx`, `.xlsx` and `.pptx`, because python-docx, openpyxl and
  python-pptx stamp the current time into the OOXML container. This predates the
  corpus work and includes an anchor document. Extracted text and chunk
  boundaries are stable, so nothing today is wrong, but `build_corpus.py` claims
  the corpus "regenerates deterministically" and that claim is currently false
  at the byte level. It will matter at L6, where content-hash diffing decides
  what changed.
- **`scripts/try_real_rtf.py` is scaffolding.** It reads the parser out of the
  PR ref to run a real Word file through it. Delete it once RTF has landed.
  It has already done its job: a Word-written `.rtf` with a tracked change on a
  budget figure showed the parser dropping the pound sign out of the visible
  text, which is reported on #1.
