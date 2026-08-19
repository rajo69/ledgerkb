-- 003_fts_and_versions — two invariants moved out of Python and into the schema.
--
-- 1. The sparse index is *derived* from the chunk, so the database maintains it.
--    Before this, `add_chunks` inserted the FTS row by hand from `embed_text`,
--    which meant a context header written later (L2) reached the dense index and
--    never reached the sparse one. `Chunk.embed_text` promised the two indexes
--    "cannot disagree"; application code could quietly break that promise. Now
--    nothing can: `body` is a generated column and FTS5 follows it by trigger.
--
-- 2. Retrieval must not return superseded versions. `superseded_by` existed as a
--    column that nothing ever wrote, so re-ingesting a changed document left both
--    generations of its chunks live in the index — and a citation could point at
--    text no longer in the document.

-- --- 1. the sparse index, maintained by the database --------------------------

DROP TABLE chunk_fts;

-- Exactly `Chunk.embed_text`: the header situates the chunk, the text is the
-- chunk. Virtual, so it costs no storage and cannot drift from its inputs.
ALTER TABLE chunk ADD COLUMN body TEXT
  GENERATED ALWAYS AS (COALESCE(context_header, '') || char(10) || char(10) || text) VIRTUAL;

CREATE VIRTUAL TABLE chunk_fts USING fts5(
  body, content='chunk', tokenize='porter unicode61');

INSERT INTO chunk_fts (chunk_fts) VALUES ('rebuild');

CREATE TRIGGER chunk_fts_ai AFTER INSERT ON chunk BEGIN
  INSERT INTO chunk_fts (rowid, body) VALUES (NEW.rowid, NEW.body);
END;

CREATE TRIGGER chunk_fts_ad AFTER DELETE ON chunk BEGIN
  INSERT INTO chunk_fts (chunk_fts, rowid, body) VALUES ('delete', OLD.rowid, OLD.body);
END;

-- Writing a context header is an UPDATE, and this is the trigger that makes the
-- two indexes stay in step without anybody remembering to reindex.
CREATE TRIGGER chunk_fts_au AFTER UPDATE OF context_header, text ON chunk BEGIN
  INSERT INTO chunk_fts (chunk_fts, rowid, body) VALUES ('delete', OLD.rowid, OLD.body);
  INSERT INTO chunk_fts (rowid, body) VALUES (NEW.rowid, NEW.body);
END;

-- --- 2. current versions ------------------------------------------------------

-- Backfill: every version except the newest per document is superseded by the
-- one that follows it.
UPDATE document_version AS v
SET superseded_by = (
  SELECT n.id FROM document_version n
  WHERE n.document_id = v.document_id AND n.version_no > v.version_no
  ORDER BY n.version_no LIMIT 1
)
WHERE superseded_by IS NULL
  AND EXISTS (
    SELECT 1 FROM document_version n
    WHERE n.document_id = v.document_id AND n.version_no > v.version_no
  );

CREATE INDEX idx_version_current ON document_version(id) WHERE superseded_by IS NULL;
