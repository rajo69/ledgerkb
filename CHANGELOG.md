# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). `core/` gets a
stability commitment at v1.0.0.

## [Unreleased]

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
