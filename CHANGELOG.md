# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). `core/` gets a
stability commitment at v1.0.0.

## [Unreleased]

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
