# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). `core/` gets a
stability commitment at v1.0.0.

## [Unreleased]

### Added — L0 scaffolding

- `core/models.py` — the domain models, with the two invariants encoded as
  validators: an assertion cannot be constructed without evidence, and an
  inferred assertion cannot claim full confidence.
- `core/ports.py` — Protocol ports for `ChatModel`, `Embedder`, `Reranker`,
  `Reader`, `Parser`, `Chunker` and `Store`. The extension surface.
- `core/config.py` — config and profile loading, with tunability as an attribute
  of each field so validation enforces the tier rather than documentation asking
  nicely. Incoherent combinations fail at startup.
- `storage/sqlite/` — the default store: migration `001_init`, FTS5 for true
  BM25, float32 vector columns, and database triggers that refuse any delete on
  the ledger.
- `providers/fake.py` — deterministic stub chat, embedder and reranker. Every
  test runs against these: no network, no credentials, no cost.
- `cli/main.py` — `lkb init`, `lkb version`, `lkb doctor`, all working with zero
  API keys.
- `profiles/default.toml` and `profiles/council.toml`.
- CI: lint, strict typing on `core`, import contracts, a three-OS test matrix,
  and an offline workflow that runs the suite with egress blocked.
