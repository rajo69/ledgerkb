# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). `core/` gets a
stability commitment at v1.0.0.

## [Unreleased]

### Added: RTF at tier 0

- `ingest/parsers/rtf.py`: RTF joins the tier-0 formats, with no new
  dependency. The format is a plain-text container, so the parser is a scanner
  over groups, control words and escapes. Headings come from the stylesheet and
  from `\outlinelevel`, which is the pair Word writes. That is also why no
  existing library was used: the ones that flatten RTF to a string discard the
  paragraph styles, and a parser that returns no headings returns no heading
  path for a citation to name.
- Hidden text (`\v`) and tracked-change deletions are kept out of the text and
  reported as `hidden:<offset>:<text>`, the shape `parsers/html.py` already
  uses, so the sanitiser turns them into quarantine records. Word will hide a
  run on request, which makes it the one injection channel the format offers.
- `.rtf` leaves `KNOWN_UNSUPPORTED`, so the error message and the parser list
  agree again.
- `tests/fixtures/build_corpus.py` generates a 21st document, an RTF board
  note. It puts the new parser under the corpus offset invariant in
  `tests/integration/test_ingest_pipeline.py` rather than only under its own
  unit tests.

### Decided: Cerebras for the contextual-header measurement

- L2's fourth criterion needs one model call per chunk, about 2.4M tokens, and
  it is the only part of L2 that needs a model at all. ADR 0008 is now accepted:
  the Cerebras free tier, `gpt-oss-120b`, through the existing
  OpenAI-compatible adapter. No new dependency and no new code path.
- The reasoning is that the useful outcome is a negative one, deleting the
  highest-volume model call in the system, and a negative result from a small
  local model could not be distinguished from a bad model.
- `docs/how-to/use-a-hosted-provider.md` carries the configuration.
- Generating the headers waits on the corpus freezing, not on the key. Chunk ids
  are minted at ingest, so headers generated against a corpus that is then
  rebuilt are lost with the ids they were attached to.
- `golden/` and `results/` now carry a README each, so the directories exist in
  a fresh clone and say what belongs in them.

### Added: the retrieval metrics

- `ledgerkb.evals.metrics` computes `recall@k`, `nDCG@k` and reciprocal rank
  over a ranked list of chunk ids. Pure: no store, no config, no corpus, no
  golden set, so every figure can be checked against a worked example by hand.
- `recall@20` is the gate metric. `recall@5`, `nDCG@10` and MRR are recorded
  alongside it on ADR 0001's instruction, so a later reader can apply a better
  metric to the same run without re-running it.
- Unanswerable questions raise rather than score. Returning 1.0 would credit the
  retriever for finding everything it was asked for when it was asked for
  nothing; returning 0.0 would blame it for a question with no answer. The gate
  says recall is measured on the answerable questions.
- Aggregation is per question, not pooled over chunks, so one question wanting
  four chunks cannot outweigh four questions wanting one.
- A chunk returned twice counts once, and deduplication happens before the top-k
  cut, so a duplicate cannot raise the score or push a real hit past the cutoff.

### Added: a format for the golden set

- `ledgerkb.evals.golden` defines what an eval question is and loads a TOML
  file of them. It contains no questions: L2's gate requires those to be written
  from the documents before retrieval is run, and nobody can write them until
  there is a format to write them in.
- Relevance is a document and a verbatim quote, not a chunk id. Chunk ids are
  minted at ingest and change on every rebuild, so a golden set keyed on them
  would rot the first time the pipeline was re-run.
- `resolve()` locates each quote in the store and raises if no chunk contains
  it. Scoring an unfindable quote as a miss would report a wrong question as a
  retrieval failure, and the two are indistinguishable in a recall number.
- `answerable` is stated, never inferred from whether spans are present, so a
  half-written question cannot silently become one of the seven unanswerable
  ones and meet the gate by accident.
- Structural problems are reported together on load. The gate counts are
  reported by `gate_problems()` rather than raised, because a file with 12
  questions in it is what writing a golden set looks like on the way to 40.
- The format is documented in
  [docs/how-to/build-the-measurement-corpus.md](docs/how-to/build-the-measurement-corpus.md).

### Added: measurements carry their provenance

- `ledgerkb.evals.provenance` collects the header ADR 0006 specifies, and
  renders the Markdown and JSON halves a committed result is made of. Every
  value is gathered from the environment, the store or git. There is no argument
  through which a human can hand-write one.
- The header records fact over intent, following the same rule as
  `embedding_space`: the embedding model and the corpus counts come from the
  store, so a result describes the run rather than what was asked for.
- `Provenance.admissible` applies ADR 0006's rule that a result from a dirty
  tree is not gate evidence, and `inadmissible_because` says which reason
  applied. ADR 0009 settles what "dirty" counts and what a run with no commit
  counts as.
- `SqliteStore.counts_for_workspace()`: document and chunk counts for one
  workspace, so a store holding a second workspace cannot inflate the corpus
  size a measurement reports.
- Nothing here runs retrieval. The golden set does not exist yet, and L2's
  ordering requires it to be written before retrieval is run even once.

### Added: the store records which model made its vectors

- Migration `005_embedding_space.sql` adds `embedding_space`, one row per
  workspace holding the model and dimension its vectors were made with.
- `lkb index` refuses to add vectors from a different embedder to an existing
  index. Two models of the same width produce vectors in different geometries,
  and cosine distance between them is still a number, so the failure was silent:
  search returned a confidently ranked list of noise, and L3 would have cited it.
- The refusal fires even when there is nothing left to embed. A model swapped on
  a fully embedded workspace has no pending chunks, and previously the command
  reported success, changed nothing, and left every later query vectorised by a
  model the index knew nothing about.
- It records what the embedder reported rather than what the config asked for.
  `config_stamp` is the record of intent; this is the record of fact.
- `lkb index --rebuild` clears the record with the vectors, so changing model
  stays a one-command operation. `lkb doctor` shows the recorded model, and says
  nothing when a workspace has never been indexed.
- This meets the last L2 criterion that was not waiting on a measurement, taking
  the gate to 3 of 7.

### Added: the L2 measurement corpus

- `tests/fixtures/corpus_world.py`: a small invented world (12 capital
  programmes, 9 committees, 11 months of meetings) that the large fixture
  corpus is generated from. Nothing in it is random and nothing is seeded, so
  a diff of that file is a diff of the corpus.
- `build_corpus.build()` takes a `scale`. Scale 0 is the 20 anchor documents
  and is the default, so the tutorial, the README and every existing test keep
  the figures they already quote. `MEASUREMENT_SCALE` is 196 documents and
  4,437 chunks.
- This unblocks the four L2 gate criteria that are measurements. At 55 chunks
  a `dense_k` of 50 covered most of the corpus and no retrieval strategy could
  score differently from any other, so the gate could not go red. It now can.
- Every programme in the world carries four different budget figures across
  four quarters, so a question about an allocation has one correct chunk and
  three decoys that share nearly all of its vocabulary. Size alone would not
  have made the measurement discriminate.
- The facts are the decoys; the wording is not. Stating every budget in one
  sentence template would have handicapped the dense arm, because templated
  text collapses under an embedding model, while giving BM25 exact tokens for
  the year and the amount. The gate asks whether hybrid beats BM25-only, so
  that shape would have answered the question before the retriever got a say.
  Each fact is now stated several ways, chosen by document index, and every
  phrasing keeps the amount and the financial year as literal tokens.
- `tests/integration/test_measurement_corpus.py` asserts the size condition
  against `RetrievalConfig` rather than against a fixed number, so raising
  `dense_k` without growing the corpus fails the build. It also runs the L1
  offset invariant over all 4,437 chunks.
- The L1 gate criterion no longer pins a document count. Growing the corpus is
  the work that unblocks L2, and a number inside a criterion that is already
  met turned every corpus contribution into a question about editing history.

### Added: L2 index and retrieve (half)

The retrieval machinery. What is outstanding is the measurement, which is
blocked on a fixture corpus too small to measure on: 55 chunks against a
default `dense_k` of 50 means every strategy scores about 1.0.

- `providers/openai_compat.py`: one adapter speaking `/chat/completions` and
  `/embeddings`, which covers most hosted providers and every local server that
  imitates them.
- `providers/local.py`: fastembed in-process, no API key and no network. Known
  model widths are checked against the configured dimensions at construction, so
  a mismatch is refused before a corpus is embedded rather than surfacing as a
  shape error on the first search.
- `providers/factory.py`: the one place a provider name in config becomes a
  class.
- `index/rrf.py`: reciprocal rank fusion over any number of named ranked lists.
  Pure: no store, no provider, no I/O. Fusing on rank rather than score is what
  makes hybrid retrieval work at all, because a cosine similarity and a BM25
  score are not on the same scale.
- `index/embed.py`: batch embedding for chunks, and query embedding.
- `index/hybrid.py`: three arms fused by rank. Dense finds the passage that never
  uses your words; BM25 finds the reference numbers an embedding smooths away;
  and a third arm matches the heading path, which costs one FTS query and no
  model at all. Each arm's own ranked list is kept, because an eval that has to
  show hybrid beating either half needs to tell "ran and found nothing" from
  "was not run".
- `lkb index`, and `lkb search` with `--k`, `--explain`, `--arms` and `--json`.
- Migration `003_fts_and_versions`: the full-text index is now a generated column
  maintained by trigger, so a context header written later cannot reach the dense
  index without reaching the sparse one. Retrieval is scoped to current document
  versions, so re-ingesting a changed document no longer leaves two generations
  of its chunks live in the index.
- Migration `004_heading_index`: the heading path gets its own FTS table, which
  is what makes the third arm free.

### Changed

- `chunking.contextual_headers` defaults to `False`. The plan gates contextual
  headers on a 5-point recall improvement, and a knob that is on before the
  measurement makes the gate decorative. The baseline to beat is the heading arm,
  which carries the same structural information deterministically and offline.
- Dependency floors are now claims rather than guesses. The floors job resolves
  to the lowest direct version every `>=` allows and runs the suite there. It
  found typer 0.12 silently mis-parsing an `Annotated` option against click
  8.2, which made `lkb init --force` default to true and overwrite a config it
  should have refused to touch. The floor is 0.16.
- The extras are split so that L1 does not drag a 40MB onnxruntime onto the
  critical path of every test run. `local` remains the union.

### Fixed

- `lkb search --json` writes to stdout instead of through the styling console.
  It went through `print_json`, which syntax-highlights whenever colour is on,
  so anyone whose shell exports `FORCE_COLOR` had escape codes inside the
  document they were about to parse and `lkb search --json | jq` failed for
  them and for nobody else. A pipe is precisely the case with no terminal to
  style for.
- `lkb` escapes document-controlled text before printing it. Console output is
  styled with rich markup, and a document is untrusted input, so a crafted title
  could otherwise forge a heading or a status in the output.
- A local provider endpoint is matched on its hostname rather than as a
  substring, so a hosted endpoint whose URL happens to contain `localhost` is no
  longer treated as local.
- `lkb ingest` accepts a relative path.

### Documentation

- `docs/stages.toml` is the one source of truth for stage status, rendered into
  `README.md` and `ROADMAP.md` by `scripts/render_docs.py` and checked in CI.
- `ARCHITECTURE.md`, `ROADMAP.md`, `GOVERNANCE.md`, `SUPPORT.md`, `AGENTS.md`
  and `CITATION.cff` added. `README.md` and `CONTRIBUTING.md` rewritten.
- The design documents move to `docs/design/`, each with a banner saying what it
  is and when it was written. Three superseded sections are marked in place.
- A documentation site under `docs/`, organised by Diátaxis, published to GitHub
  Pages.
- `scripts/check_docs.py` fails the build on an em dash, a banned word, a broken
  relative link, or a stage status stated in prose outside a generated region.
- Code examples in the README, the tutorial and the how-to guides are executed
  as tests, so a quickstart cannot rot.

### Added: L1 ingest, parse, chunk

Documents to chunks with correct metadata and offsets, entirely offline.

- `ingest/readers/`: a filesystem reader, and ZIP expansion guarded against
  path traversal, compression bombs, nesting and sheer volume. None of the
  guards is configurable.
- `ingest/parsers/`: tier-0 parsers for PDF (`pypdfium2`), DOCX, XLSX, PPTX,
  HTML, EML, CSV, JSON, TXT and MD, behind a registry that names an unsupported
  format rather than guessing at it.
- `ingest/sanitise.py`: invisible text removed, instruction-shaped spans
  quarantined but kept. Detection requires an instruction verb *and* a token
  addressing a model, so "the committee resolved to ignore the previous
  recommendation" is not a finding.
- `ingest/chunk.py`: structure-first chunking. A whole decision stays whole;
  only oversized sections are split further. Chunk text is sliced, never
  constructed.
- `ingest/metadata.py`: the five fields the brief names, deterministically,
  with every miss reported rather than left null.
- `ingest/pipeline.py`: dedupe by content hash before parsing; a failure names
  its document and the run continues.
- `lkb ingest`, `lkb docs`, `lkb chunks --verify`.
- A generated 20-document fixture corpus, 10 injection fixtures (nine attacks
  and one benign decoy) and 5 malicious archives, built from reviewable source
  rather than committed as binaries.
- Migration `002_version_text`: the canonical text is stored on the version, so
  the offset invariant is checkable against the store and re-chunking does not
  require re-parsing.

### Added: L0 scaffolding

- `core/models.py`: the domain models, with the two invariants encoded as
  validators: an assertion cannot be constructed without evidence, and an
  inferred assertion cannot claim full confidence.
- `core/ports.py`: Protocol ports for `ChatModel`, `Embedder`, `Reranker`,
  `Reader`, `Parser`, `Chunker` and `Store`. The extension surface.
- `core/config.py`: config and profile loading, with tunability as an attribute
  of each field so validation enforces the tier rather than documentation asking
  nicely. Incoherent combinations fail at startup.
- `storage/sqlite/`: the default store: migration `001_init`, FTS5 for true
  BM25, float32 vector columns, and database triggers that refuse any delete on
  the ledger.
- `providers/fake.py`: deterministic stub chat, embedder and reranker. Every
  test runs against these: no network, no credentials, no cost.
- `cli/main.py`: `lkb init`, `lkb version`, `lkb doctor`, all working with zero
  API keys.
- `profiles/default.toml` and `profiles/council.toml`.
- CI: lint, strict typing on `core`, import contracts, a three-OS test matrix,
  and an offline workflow that runs the suite with egress blocked.
