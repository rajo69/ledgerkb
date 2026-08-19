# Store schema

SQLite is the default and the only implemented backend. A library that requires a
server is not a library, and at this scale SQLite is not a compromise: FTS5 gives
true BM25, and a brute-force cosine scan over 50,000 vectors at 1024 dimensions
is a 200MB matrix multiply that finishes in single-digit milliseconds.

Migrations are plain numbered SQL under `src/ledgerkb/storage/migrations/`, with a
`schema_version` table. No migration framework: the schema is small and additive,
and a numbered file is easier to read than a generated one.

## Migrations

| File | What it does |
|---|---|
| `001_init.sql` | Every table, the indexes, and the triggers that make the ledger append-only |
| `002_version_text.sql` | Stores the canonical text on the version, plus `parse_warnings` and `metadata_misses` |
| `003_fts_and_versions.sql` | Moves the full-text index onto a generated column maintained by trigger, and scopes retrieval to current versions |
| `004_heading_index.sql` | A second FTS table over the heading path, which is the third retrieval arm |

`lkb init` and `lkb doctor` both report the schema version. `store.migrate()`
runs anything outstanding and returns the version it reached.

## Tables

| Table | Holds |
|---|---|
| `workspace` | The top-level grouping |
| `source` | Where documents come from |
| `document` | Stable document identity, unique on `(source_id, external_id)` |
| `document_version` | Immutable versions, unique on `(document_id, content_hash)` |
| `chunk` | Addressable spans, with `embedding` as a float32 blob |
| `chunk_fts` | FTS5 over the chunk body. External-content table over `chunk` |
| `chunk_headings` | FTS5 over `heading_path`. External-content table over `chunk` |
| `entity`, `entity_merge_log` | Resolved entities and every merge decision |
| `assertion`, `assertion_evidence` | The ledger |
| `quarantine` | Instruction-shaped spans found during sanitisation |
| `ingest_run`, `change_event` | What a run saw and what changed |
| `run_record` | Per-stage model, tokens, cost, duration, error |
| `config_stamp` | The resolved config, so a tier transition is detectable on the next run |

## Vectors

`chunk.embedding` is a float32 little-endian blob. `search_dense` decodes the
column and scans, which is exact rather than approximate: there is no recall loss
from an index, and no index to keep in step with the data.

`sqlite-vec` is available behind the `vec` extra as an optional accelerator. It
is not a dependency, because it is still alpha and a library that must install
cleanly everywhere cannot require it.

A width mismatch between a stored vector and a query vector raises a named
`InvariantError` rather than returning nonsense.

## Keyword search

`chunk_fts` is an FTS5 external-content table over `chunk`, indexing a generated
column:

```sql
ALTER TABLE chunk ADD COLUMN body TEXT
  GENERATED ALWAYS AS (COALESCE(context_header, '') || char(10) || char(10) || text) VIRTUAL;
```

That is exactly `Chunk.embed_text`, the same string the dense arm embeds. Three
triggers keep the FTS row in step on insert, delete and update. Before migration
003 the application inserted the FTS row by hand, which meant a context header
written later reached the dense index and never reached the sparse one. The model
promised the two indexes could not disagree; application code could quietly break
that promise. Now nothing can.

`chunk_headings` is the same arrangement over `heading_path`. The `unicode61`
tokeniser treats the stored JSON brackets and quotes as separators, so the array
tokenises into its words with no unpacking.

Both use `porter unicode61`, so `bm25()` is real BM25 with length normalisation
and saturating term frequency.

## Triggers, which are the interesting part

The invariants are in the database rather than in convention, which means they
hold for anything that opens the file, including a `sqlite3` shell.

| Trigger | Refuses |
|---|---|
| `assertion_no_delete` | Any delete on `assertion`. Set `invalid_at` instead |
| `assertion_invalidate_once` | A second write to `invalid_at`. It is set once and never revised |
| `assertion_evidence_no_delete` | Any delete on `assertion_evidence`. An assertion may never lose its evidence |
| `document_version_immutable` | An update to `content_hash`, `text_hash` or `ingested_at`. A new hash is a new row |

Plus a `CHECK` constraint: `modality <> 'inferred' OR confidence < 1.0`. Inference
is never certain, and that is enforced in the schema rather than only in the
pydantic model.

None of these has a configuration key that turns it off. See
[Tunability tiers](../explanation/tunability-tiers.md).

## Current versions

`document_version.superseded_by` points at the version that replaced it, and is
written on ingest. `idx_version_current` is a partial index on
`superseded_by IS NULL`.

Retrieval filters on it. Without that, re-ingesting a changed document leaves both
generations of its chunks live in the index, and a citation can point at text that
is no longer in the document. Migration 003 backfilled it for stores created
before the column was ever written to.

`search_dense` and `search_sparse` take `include_superseded=True` if you
deliberately want the older generations, which is what a historical query will
need at L6.

## Postgres

`storage/postgres/` is an empty package. The DDL is designed and is in
[`docs/design/02-architecture.md` section 3](../design/02-architecture.md).

One asymmetry is worth knowing before anyone builds it: SQLite gets real BM25 via
FTS5, and Postgres gets `ts_rank`, which is not BM25. No document-length
normalisation, no saturating term frequency. Local development would therefore
have better lexical ranking than production until a BM25 extension is added.
Documented rather than hidden, as risk R4 in
[the implementation plan](../design/03-implementation-plan.md).
