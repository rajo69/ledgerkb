-- 002_version_text — keep the canonical text alongside the version.
--
-- Chunk offsets index into this text, so storing it is what lets the offset
-- invariant be checked against the store rather than only in memory, and lets
-- re-chunking happen without re-parsing (re-parsing costs money once tier 1 is
-- involved). It is the sanitised text: sanitisation runs once, before any
-- offset is taken, so there is exactly one coordinate system.

ALTER TABLE document_version ADD COLUMN text TEXT;

-- Which parser tier actually ran, and what the density probe said. Recorded so
-- a later reader can see why a document went the way it did.
ALTER TABLE document_version ADD COLUMN parse_warnings TEXT NOT NULL DEFAULT '[]';

-- Metadata coverage, so the "reported, never silently null" rule has somewhere
-- to report to.
ALTER TABLE document_version ADD COLUMN metadata_misses TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_quarantine_version ON quarantine(version_id);
