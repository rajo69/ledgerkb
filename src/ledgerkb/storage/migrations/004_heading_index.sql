-- 004_heading_index — a third retrieval arm that costs nothing to run.
--
-- `heading_path` is already on every chunk and is already a structural summary
-- of where the chunk sits: "Planning Committee Minutes > Item 4 > Decision".
-- Matching a query against it is one more FTS query and no model at all, which
-- makes it the deterministic counterpart to an LLM-written context header --
-- and the baseline any contextual-header A/B has to beat before it is worth
-- paying for.
--
-- unicode61 treats the JSON brackets and quotes as separators, so the stored
-- array tokenises into its words without any unpacking.

CREATE VIRTUAL TABLE chunk_headings USING fts5(
  heading_path, content='chunk', tokenize='porter unicode61');

INSERT INTO chunk_headings (chunk_headings) VALUES ('rebuild');

CREATE TRIGGER chunk_headings_ai AFTER INSERT ON chunk BEGIN
  INSERT INTO chunk_headings (rowid, heading_path) VALUES (NEW.rowid, NEW.heading_path);
END;

CREATE TRIGGER chunk_headings_ad AFTER DELETE ON chunk BEGIN
  INSERT INTO chunk_headings (chunk_headings, rowid, heading_path)
  VALUES ('delete', OLD.rowid, OLD.heading_path);
END;

CREATE TRIGGER chunk_headings_au AFTER UPDATE OF heading_path ON chunk BEGIN
  INSERT INTO chunk_headings (chunk_headings, rowid, heading_path)
  VALUES ('delete', OLD.rowid, OLD.heading_path);
  INSERT INTO chunk_headings (rowid, heading_path) VALUES (NEW.rowid, NEW.heading_path);
END;
