# L2 completion handoff

Written 2026-08-21, for a session starting cold. Read this before touching
retrieval. [04-build-handoff.md](04-build-handoff.md) is still the wider
reference; its "corpus problem" section is superseded by this one.

## Verify you are where this document thinks you are

```bash
git log --oneline -3
gh pr list --state open
uv run pytest --no-cov -q
python tests/fixtures/build_corpus.py /tmp/c 11   # 195 documents
```

Stage status is generated from `docs/stages.toml`. Do not state it anywhere
else, and do not edit the generated regions by hand.

## Where L2 actually is

Gate 2 of 7. The machinery has been merged since `76d010c`: an OpenAI-compatible
embedder, a local in-process one, RRF, three arms (dense, BM25, heading path),
version-scoped search, and `--explain`. Two criteria are met and stay met.

The five open criteria, and what each needs:

| Criterion | Blocked on | Exists today |
|---|---|---|
| Golden set, 40 questions, 7+ unanswerable | somebody writing them | `golden/` is empty |
| recall@20 >= 0.90 | a measurement harness | `src/ledgerkb/eval/` is an empty package |
| Hybrid beats dense-only and BM25-only | the same harness | nothing |
| Contextual headers +5 points | `index/contextualise.py` **and an LLM** | neither |
| Embedding model and dimension in the store | a migration | no such columns in `storage/migrations/` |

The last one is unblocked, self-contained, and the obvious first commit.

## What changed this session, and why

**The corpus stopped being the blocker.** It was 20 documents and 55 chunks
against a default `dense_k` of 50, so each arm was asked for most of the corpus
and no strategy could score differently from any other. The gate could not go
red, so passing it would have proved nothing.

`tests/fixtures/corpus_world.py` now generates a world and
`build_corpus.build(target, scale)` takes a scale. Scale 0 is the 20 anchor
documents and remains the default, so every figure quoted in the tutorial and
the README stays true. `MEASUREMENT_SCALE` is 11: **195 documents, 4,433
chunks**.

Size alone was not the point. Every capital programme carries four different
budget figures across four quarters, so a question about an allocation has one
correct chunk and three decoys sharing nearly all of its vocabulary. Without
that, 200 unrelated documents retrieve as easily as 20.

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
   lists the question shapes that discriminate.
5. **Build the eval harness**, then run recall@20 and the hybrid-versus-arms
   comparison. Commit the numbers as a file. A figure that lives only in
   terminal scrollback is not a met criterion.
6. **Contextual headers**, or a written descope. See the open decision below.
7. **Update `docs/stages.toml`** and run `scripts/render_docs.py`. Then update
   this document to say what the numbers were.

## The open decision

Criterion 4 needs an LLM, one call per chunk, about 2.4M tokens across 4,433
requests. Nothing else in L2 needs one: embeddings run locally through
fastembed with no key.

There is no key in the environment and no local model server. The options, with
the numbers as of 2026-08-21:

- **Cerebras free tier.** 1M tokens/day, so about 2.5 days unattended.
  OpenAI-compatible at `api.cerebras.ai/v1`, `gpt-oss-120b`, 8K context cap
  which is ample for a chunk.
- **Local Ollama.** Faster in elapsed time on this hardware, roughly 15 to 20
  hours, but CPU-only on an i5-1235U with no discrete GPU, and a 4B model. A
  negative result from a small model cannot be distinguished from a bad model,
  which defeats the purpose of the criterion.
- **Paid, about $0.33** on Gemini 2.5 Flash Lite, which removes the constraint
  entirely.
- **Descope it in writing.** Permitted by the roadmap. The argument is real: the
  knob defaults to off, the baseline to beat is the heading arm rather than "no
  context", and this corpus is structured enough that the heading arm may
  already carry the whole gain.

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
  PR ref to test a real Word file. Delete it once RTF has landed.
