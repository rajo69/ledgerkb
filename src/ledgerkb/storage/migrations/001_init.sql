-- 001_init — SQLite counterpart of the Postgres DDL in 02-ARCHITECTURE.md §3.
-- Migrations are plain numbered SQL with a schema_version table. No Alembic:
-- the schema is small and additive.

CREATE TABLE workspace (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  profile TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL
);

CREATE TABLE source (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('gdrive','link','upload')),
  label TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}',
  connector_state TEXT NOT NULL DEFAULT '{}',
  last_refreshed_at TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TEXT NOT NULL
);

CREATE TABLE document (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  external_id TEXT NOT NULL,
  uri TEXT,
  title TEXT,
  doc_type TEXT,
  meeting_or_project TEXT,
  published_at TEXT,
  authors TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  current_version_id TEXT,
  UNIQUE (source_id, external_id)
);

-- immutable. a new content hash is a new row, never an update.
CREATE TABLE document_version (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  blob_uri TEXT,
  mime TEXT,
  bytes INTEGER,
  page_count INTEGER,
  parser TEXT,
  parse_quality REAL,
  ingested_at TEXT NOT NULL,
  superseded_by TEXT REFERENCES document_version(id),
  UNIQUE (document_id, content_hash)
);

CREATE TABLE chunk (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  version_id TEXT NOT NULL REFERENCES document_version(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '[]',
  page_from INTEGER,
  page_to INTEGER,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  text TEXT NOT NULL,            -- verbatim source span. NEVER rewritten.
  context_header TEXT,
  token_count INTEGER,
  embedding BLOB                 -- float32 little-endian
);

-- true BM25, built into SQLite
CREATE VIRTUAL TABLE chunk_fts USING fts5(
  body, chunk_id UNINDEXED, tokenize='porter unicode61');

CREATE TABLE entity (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  normalised_name TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '[]',
  attrs TEXT NOT NULL DEFAULT '{}',
  embedding BLOB,
  first_seen TEXT,
  last_seen TEXT,
  merged_into TEXT REFERENCES entity(id),
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE assertion (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  subject_id TEXT REFERENCES entity(id),
  predicate TEXT NOT NULL,
  object_id TEXT REFERENCES entity(id),
  object_literal TEXT,
  claim_text TEXT NOT NULL,
  modality TEXT NOT NULL CHECK (modality IN ('explicit','inferred')),
  confidence REAL NOT NULL DEFAULT 1.0,
  valid_from TEXT,
  valid_to TEXT,
  asserted_at TEXT NOT NULL,
  invalid_at TEXT,
  invalidated_by TEXT REFERENCES assertion(id),
  invalidation_reason TEXT CHECK (invalidation_reason IN
    ('superseded','contradicted','corrected','source_withdrawn')),
  status TEXT NOT NULL DEFAULT 'active',
  stale_after TEXT,
  verified_by TEXT,
  verified_at TEXT,
  -- inference is never certain: enforced in the schema, not just in code
  CHECK (modality <> 'inferred' OR confidence < 1.0)
);

-- an assertion with zero rows here is invalid by construction
CREATE TABLE assertion_evidence (
  assertion_id TEXT NOT NULL REFERENCES assertion(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES chunk(id),
  quote TEXT NOT NULL,
  char_start INTEGER,
  char_end INTEGER,
  PRIMARY KEY (assertion_id, chunk_id)
);

CREATE TABLE entity_merge_log (
  id TEXT PRIMARY KEY,
  winner_id TEXT NOT NULL,
  loser_id TEXT NOT NULL,
  method TEXT NOT NULL,
  score REAL,
  evidence TEXT NOT NULL DEFAULT '{}',
  decided_by TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  reverted_at TEXT
);

CREATE TABLE quarantine (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL,
  char_start INTEGER,
  char_end INTEGER,
  text TEXT NOT NULL,
  reason TEXT NOT NULL,
  detected_at TEXT NOT NULL
);

CREATE TABLE ingest_run (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  source_id TEXT,
  trigger TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  docs_seen INTEGER,
  docs_changed INTEGER,
  docs_new INTEGER,
  docs_gone INTEGER,
  stats TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE change_event (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES ingest_run(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  assertion_id TEXT,
  prior_assertion_id TEXT,
  summary TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE run_record (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  stage TEXT NOT NULL,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  duration_ms INTEGER,
  error TEXT,
  created_at TEXT NOT NULL
);

-- the resolved config, stamped so any artifact can be audited for how it was
-- produced, and so tier-2/3 transitions can be detected on the next run
CREATE TABLE config_stamp (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  receipt TEXT NOT NULL,
  stamped_at TEXT NOT NULL
);

CREATE INDEX idx_chunk_ws ON chunk(workspace_id, version_id);
CREATE INDEX idx_assert_active ON assertion(workspace_id, status) WHERE invalid_at IS NULL;
CREATE INDEX idx_assert_stale ON assertion(workspace_id, stale_after) WHERE status = 'active';
CREATE INDEX idx_entity_norm ON entity(workspace_id, normalised_name);
CREATE INDEX idx_version_hash ON document_version(document_id, content_hash);
CREATE INDEX idx_change_run ON change_event(run_id);

-- The append-only invariant, enforced by the database rather than by convention.
-- There is no config key that turns these off (tier 4).
CREATE TRIGGER assertion_no_delete BEFORE DELETE ON assertion
BEGIN
  SELECT RAISE(ABORT, 'assertion is append-only: never delete, set invalid_at instead');
END;

CREATE TRIGGER assertion_invalidate_once BEFORE UPDATE OF invalid_at ON assertion
WHEN OLD.invalid_at IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'invalid_at is set once and never revised');
END;

CREATE TRIGGER assertion_evidence_no_delete BEFORE DELETE ON assertion_evidence
BEGIN
  SELECT RAISE(ABORT, 'evidence is append-only: an assertion may never lose its evidence');
END;

CREATE TRIGGER document_version_immutable BEFORE UPDATE OF content_hash, text_hash, ingested_at
ON document_version
BEGIN
  SELECT RAISE(ABORT, 'document_version is immutable: a new content hash is a new row');
END;
