-- 005_embedding_space — which model actually produced the vectors.
--
-- `config_stamp` already records the config a store was built with, and
-- `lkb doctor` reports drift from it. Neither of those stops `lkb index` from
-- adding vectors from a second model to an index built by a first one, and
-- that is the failure worth preventing rather than reporting.
--
-- It is worth being precise about why it is bad. Cosine distance between two
-- different models' vectors is still a number, so nothing raises, nothing
-- looks empty, and search keeps returning a confidently ranked list. Every
-- ranking in it is meaningless. There is no later stage that can detect it
-- either: L3 cites whatever L2 retrieved, so a silently poisoned index becomes
-- a citation that points at the wrong chunk with full confidence.
--
-- This records fact rather than intent. `config_stamp` says what the config
-- asked for; this says what the embedder reported it was, which is what the
-- vectors were actually made with. A provider that silently resolves a model
-- alias, or falls back, differs from its own config, and the vectors follow
-- the provider.
--
-- Per workspace, because embeddings are written and cleared per workspace and
-- two workspaces are entitled to different models. Deleted when the vectors
-- are, so `lkb index --rebuild` is the sanctioned way to change model.

CREATE TABLE embedding_space (
  workspace_id TEXT PRIMARY KEY REFERENCES workspace(id) ON DELETE CASCADE,
  model        TEXT NOT NULL,
  dimensions   INTEGER NOT NULL CHECK (dimensions > 0),
  recorded_at  TEXT NOT NULL
);
