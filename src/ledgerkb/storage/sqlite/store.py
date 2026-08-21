"""SQLite store — the default backend.

SQLite is not the fallback here; it is the default, and Postgres is the scale
backend behind the same ``Store`` protocol. FTS5 gives true BM25 in-process,
which is why the sparse half of hybrid retrieval needs no external service.

Dense search is an exact scan at this stage. That is deliberate: correct before
fast, and `sqlite-vec` is an optional accelerator that is still alpha.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ledgerkb.core.errors import InvariantError, StorageError
from ledgerkb.core.models import (
    Assertion,
    ChangeEvent,
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    Evidence,
    Hit,
    IngestRun,
    InvalidationReason,
    MergeMethod,
    RunRecord,
    Source,
    Workspace,
    new_id,
    utcnow,
)
from ledgerkb.storage.base import (
    discover_migrations,
    dt,
    dumps,
    fts_query,
    loads,
    pack_vector,
    unpack_vector,
)


def _as_date(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _as_dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


class SqliteStore:
    """Implements :class:`ledgerkb.core.ports.Store`."""

    def __init__(self, path: str | Path = ".lkb/store.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")

    # --- lifecycle -----------------------------------------------------------

    def migrate(self) -> int:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        current = self.schema_version()
        for mig in discover_migrations():
            if mig.version <= current:
                continue
            try:
                self.db.executescript(mig.sql)
                self.db.execute(
                    "INSERT INTO schema_version (version, name, applied_at) VALUES (?,?,?)",
                    (mig.version, mig.name, utcnow().isoformat()),
                )
                self.db.commit()
            except sqlite3.Error as exc:
                self.db.rollback()
                raise StorageError(
                    f"Migration {mig.version:03d}_{mig.name} failed: {exc}"
                ) from exc
            current = mig.version
        return current

    def schema_version(self) -> int:
        """0 on a store that has never been migrated."""
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if not exists:
            return 0
        row = self.db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0

    def stamp_config(self, receipt: dict[str, Any]) -> None:
        """Record the fully-resolved config so exports are auditable and tier
        transitions are detectable on the next run."""
        self.db.execute(
            "INSERT INTO config_stamp (id, receipt, stamped_at) VALUES (1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET receipt = excluded.receipt, "
            "stamped_at = excluded.stamped_at",
            (dumps(receipt), utcnow().isoformat()),
        )
        self.db.commit()

    def stamped_config(self) -> dict[str, Any] | None:
        row = self.db.execute("SELECT receipt FROM config_stamp WHERE id = 1").fetchone()
        return json.loads(row["receipt"]) if row else None

    def record_embedding_space(
        self, workspace_id: str, model: str, dimensions: int
    ) -> None:
        """Record which model produced this workspace's vectors.

        Fact, not intent: the model the embedder reported, which is what the
        vectors were made with. ``stamp_config`` covers intent.
        """
        self.db.execute(
            "INSERT INTO embedding_space (workspace_id, model, dimensions, recorded_at) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(workspace_id) DO UPDATE SET model = excluded.model, "
            "dimensions = excluded.dimensions, recorded_at = excluded.recorded_at",
            (workspace_id, model, dimensions, utcnow().isoformat()),
        )
        self.db.commit()

    def embedding_space(self, workspace_id: str) -> tuple[str, int] | None:
        """``(model, dimensions)``, or None if nothing has been embedded here."""
        row = self.db.execute(
            "SELECT model, dimensions FROM embedding_space WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return (row["model"], int(row["dimensions"])) if row else None

    def embedding_spaces(self) -> list[tuple[str, str, int]]:
        """``(workspace_id, model, dimensions)`` for every indexed workspace.

        Read-only, for ``lkb doctor``. It must not create a workspace to answer
        the question, which is why it does not go through the default-workspace
        helper.
        """
        rows = self.db.execute(
            "SELECT workspace_id, model, dimensions FROM embedding_space "
            "ORDER BY recorded_at"
        ).fetchall()
        return [(r["workspace_id"], r["model"], int(r["dimensions"])) for r in rows]

    def embedded_chunk_count(self, workspace_id: str) -> int:
        """How many vectors exist, which is what makes a recorded space binding.

        A space recorded by a run that then failed before writing anything must
        not refuse the next run: there is nothing for a new model to be
        inconsistent with.
        """
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM chunk "
            "WHERE workspace_id = ? AND embedding IS NOT NULL",
            (workspace_id,),
        ).fetchone()
        return int(row["n"])

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- workspaces and sources ---------------------------------------------

    def add_workspace(self, ws: Workspace) -> str:
        self.db.execute(
            "INSERT INTO workspace (id,name,profile,created_at) VALUES (?,?,?,?)",
            (ws.id, ws.name, ws.profile, ws.created_at.isoformat()),
        )
        self.db.commit()
        return ws.id

    def get_workspace(self, id: str) -> Workspace | None:
        row = self.db.execute("SELECT * FROM workspace WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return Workspace(
            id=row["id"],
            name=row["name"],
            profile=row["profile"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def add_source(self, s: Source) -> str:
        self.db.execute(
            "INSERT INTO source (id,workspace_id,kind,label,config,connector_state,"
            "last_refreshed_at,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                s.id, s.workspace_id, s.kind, s.label, dumps(s.config),
                dumps(s.connector_state), dt(s.last_refreshed_at), s.status,
                s.created_at.isoformat(),
            ),
        )
        self.db.commit()
        return s.id

    # --- documents -----------------------------------------------------------

    def upsert_document(self, doc: Document) -> str:
        row = self.db.execute(
            "SELECT id FROM document WHERE source_id = ? AND external_id = ?",
            (doc.source_id, doc.external_id),
        ).fetchone()
        doc_id = row["id"] if row else doc.id
        self.db.execute(
            "INSERT INTO document (id,workspace_id,source_id,external_id,uri,title,doc_type,"
            "meeting_or_project,published_at,authors,status,current_version_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source_id, external_id) DO UPDATE SET "
            "uri=excluded.uri, title=excluded.title, doc_type=excluded.doc_type, "
            "meeting_or_project=excluded.meeting_or_project, "
            "published_at=excluded.published_at, authors=excluded.authors, "
            "status=excluded.status, current_version_id=excluded.current_version_id",
            (
                doc_id, doc.workspace_id, doc.source_id, doc.external_id, doc.uri,
                doc.title, doc.doc_type, doc.meeting_or_project, dt(doc.published_at),
                dumps(doc.authors), doc.status, doc.current_version_id,
            ),
        )
        self.db.commit()
        return doc_id

    def get_document(self, id: str) -> Document | None:
        row = self.db.execute("SELECT * FROM document WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return Document(
            id=row["id"],
            workspace_id=row["workspace_id"],
            source_id=row["source_id"],
            external_id=row["external_id"],
            uri=row["uri"],
            title=row["title"],
            doc_type=row["doc_type"],
            meeting_or_project=row["meeting_or_project"],
            published_at=_as_date(row["published_at"]),
            authors=loads(row["authors"], []),
            status=row["status"],
            current_version_id=row["current_version_id"],
        )

    def add_version(self, v: DocumentVersion) -> str:
        """A new version supersedes the one it replaces.

        Marking it is what keeps retrieval out of stale text: without it both
        generations of a re-ingested document stay in the index, and a citation
        can point at wording the document no longer contains.
        """
        previous = self.db.execute(
            "SELECT id FROM document_version WHERE document_id = ? AND superseded_by IS NULL",
            (v.document_id,),
        ).fetchall()
        self.db.execute(
            "INSERT INTO document_version (id,document_id,version_no,content_hash,text_hash,"
            "blob_uri,mime,bytes,page_count,parser,parse_quality,ingested_at,superseded_by,"
            "text,parse_warnings,metadata_misses) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                v.id, v.document_id, v.version_no, v.content_hash, v.text_hash, v.blob_uri,
                v.mime, v.bytes, v.page_count, v.parser, v.parse_quality,
                v.ingested_at.isoformat(), v.superseded_by,
                v.text, dumps(v.parse_warnings), dumps(v.metadata_misses),
            ),
        )
        for row in previous:
            if row["id"] != v.id:
                self.db.execute(
                    "UPDATE document_version SET superseded_by = ? WHERE id = ?",
                    (v.id, row["id"]),
                )
        self.db.execute(
            "UPDATE document SET current_version_id = ? WHERE id = ?", (v.id, v.document_id)
        )
        self.db.commit()
        return v.id

    def _version(self, row: sqlite3.Row) -> DocumentVersion:
        return DocumentVersion(
            id=row["id"],
            document_id=row["document_id"],
            version_no=row["version_no"],
            content_hash=row["content_hash"],
            text_hash=row["text_hash"],
            blob_uri=row["blob_uri"],
            mime=row["mime"],
            bytes=row["bytes"],
            page_count=row["page_count"],
            parser=row["parser"],
            parse_quality=row["parse_quality"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            superseded_by=row["superseded_by"],
            text=row["text"],
            parse_warnings=loads(row["parse_warnings"], []),
            metadata_misses=loads(row["metadata_misses"], []),
        )

    def get_version(self, id: str) -> DocumentVersion | None:
        row = self.db.execute("SELECT * FROM document_version WHERE id = ?", (id,)).fetchone()
        return self._version(row) if row else None

    def find_version_by_hash(self, document_id: str, content_hash: str) -> DocumentVersion | None:
        row = self.db.execute(
            "SELECT * FROM document_version WHERE document_id = ? AND content_hash = ?",
            (document_id, content_hash),
        ).fetchone()
        return self._version(row) if row else None

    # --- chunks --------------------------------------------------------------

    def add_chunks(self, chunks: Iterable[Chunk]) -> None:
        rows = list(chunks)
        if not rows:
            return
        self.db.executemany(
            "INSERT INTO chunk (id,workspace_id,version_id,ordinal,heading_path,page_from,"
            "page_to,char_start,char_end,text,context_header,token_count,embedding) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    c.id, c.workspace_id, c.version_id, c.ordinal, dumps(c.heading_path),
                    c.page_from, c.page_to, c.char_start, c.char_end, c.text,
                    c.context_header, c.token_count, pack_vector(c.embedding),
                )
                for c in rows
            ],
        )
        # No FTS insert here on purpose: migration 003 makes `chunk.body` a
        # generated column and keeps chunk_fts in step by trigger, so the dense
        # and sparse indexes derive from one string and cannot disagree even if
        # a context header is written long after ingest.
        self.db.commit()

    def _chunk(self, row: sqlite3.Row) -> Chunk:
        return Chunk(
            id=row["id"],
            workspace_id=row["workspace_id"],
            version_id=row["version_id"],
            ordinal=row["ordinal"],
            heading_path=loads(row["heading_path"], []),
            page_from=row["page_from"],
            page_to=row["page_to"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            text=row["text"],
            context_header=row["context_header"],
            token_count=row["token_count"],
            embedding=unpack_vector(row["embedding"]),
        )

    def get_chunk(self, id: str) -> Chunk | None:
        row = self.db.execute("SELECT * FROM chunk WHERE id = ?", (id,)).fetchone()
        return self._chunk(row) if row else None

    def set_embeddings(self, pairs: Iterable[tuple[str, list[float]]]) -> None:
        self.db.executemany(
            "UPDATE chunk SET embedding = ? WHERE id = ?",
            [(pack_vector(v), cid) for cid, v in pairs],
        )
        self.db.commit()

    def set_context_headers(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Write the situating headers. The sparse index follows by trigger."""
        self.db.executemany(
            "UPDATE chunk SET context_header = ? WHERE id = ?",
            [(header, cid) for cid, header in pairs],
        )
        self.db.commit()

    def chunks_missing_embeddings(self, workspace_id: str) -> list[Chunk]:
        rows = self.db.execute(
            "SELECT c.* FROM chunk c "
            "JOIN document_version v ON v.id = c.version_id "
            "WHERE c.workspace_id = ? AND c.embedding IS NULL AND v.superseded_by IS NULL "
            "ORDER BY c.version_id, c.ordinal",
            (workspace_id,),
        ).fetchall()
        return [self._chunk(r) for r in rows]

    def _scope(self, f: dict[str, Any], alias: str = "c") -> tuple[str, list[Any]]:
        """The filter every search shares.

        Superseded versions are excluded by default. Retrieval answers questions
        about what a document says *now*; the ledger is where "what did it say in
        March" lives, and conflating the two is how a citation ends up quoting
        text that was edited out.
        """
        sql, params = "", []
        if ws := f.get("workspace_id"):
            sql += f" AND {alias}.workspace_id = ?"
            params.append(ws)
        if not f.get("include_superseded"):
            sql += " AND v.superseded_by IS NULL"
        return sql, params

    def clear_embeddings(self, workspace_id: str) -> int:
        """Drop every vector in a workspace, for a deliberate re-index.

        The recorded embedding space goes with them. It describes vectors that
        no longer exist, and keeping it would make ``--rebuild`` refuse the
        model change that is the usual reason for running it.
        """
        cur = self.db.execute(
            "UPDATE chunk SET embedding = NULL WHERE workspace_id = ?", (workspace_id,)
        )
        self.db.execute(
            "DELETE FROM embedding_space WHERE workspace_id = ?", (workspace_id,)
        )
        self.db.commit()
        return int(cur.rowcount)

    def search_dense(self, vec: list[float], k: int, **f: Any) -> list[Hit]:
        where, params = self._scope(f)
        rows = self.db.execute(
            "SELECT c.id, c.version_id, v.document_id, c.text, c.heading_path, c.page_from, "
            "       c.embedding "
            "FROM chunk c JOIN document_version v ON v.id = c.version_id "
            "WHERE c.embedding IS NOT NULL" + where,
            params,
        ).fetchall()
        if not rows:
            return []

        q = np.asarray(vec, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0.0:
            return []
        mat = np.vstack([np.frombuffer(r["embedding"], dtype="<f4") for r in rows])
        if mat.shape[1] != q.shape[0]:
            raise InvariantError(
                f"Stored vectors are {mat.shape[1]}-dimensional but the query is "
                f"{q.shape[0]}-dimensional. The embedding model changed under an "
                "existing index; run: lkb reindex --confirm"
            )
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0.0] = np.inf          # zero vectors score 0, never NaN
        scores = (mat @ q) / (norms * qn)
        # Stable, so a tie breaks the same way on every platform and numpy
        # version. Ties are common on boilerplate and a wobbling order would
        # make the eval numbers wobble with it.
        top = np.argsort(-scores, kind="stable")[:k]
        return [
            Hit(
                chunk_id=rows[i]["id"],
                score=float(scores[i]),
                text=rows[i]["text"],
                method="dense",
                document_id=rows[i]["document_id"],
                version_id=rows[i]["version_id"],
                heading_path=loads(rows[i]["heading_path"], []),
                page_from=rows[i]["page_from"],
            )
            for i in top
        ]

    def search_sparse(self, query: str, k: int, **f: Any) -> list[Hit]:
        where, params = self._scope(f)
        sql = (
            "SELECT c.id, c.version_id, v.document_id, c.text, c.heading_path, c.page_from, "
            "       bm25(chunk_fts) AS rank "
            "FROM chunk_fts "
            "JOIN chunk c ON c.rowid = chunk_fts.rowid "
            "JOIN document_version v ON v.id = c.version_id "
            "WHERE chunk_fts MATCH ?" + where + " ORDER BY rank, c.id LIMIT ?"
        )
        rows = self.db.execute(sql, [fts_query(query), *params, k]).fetchall()
        return [
            Hit(
                chunk_id=r["id"],
                # bm25() returns a negative score, better = more negative
                score=-float(r["rank"]),
                text=r["text"],
                method="sparse",
                document_id=r["document_id"],
                version_id=r["version_id"],
                heading_path=loads(r["heading_path"], []),
                page_from=r["page_from"],
            )
            for r in rows
        ]

    def search_headings(self, query: str, k: int, **f: Any) -> list[Hit]:
        """BM25 over the heading path alone.

        Deterministic, free, and it answers a shape of question the body index
        is bad at: "what did Planning Committee decide about the footbridge" is
        a heading query wearing a sentence's clothes.
        """
        where, params = self._scope(f)
        sql = (
            "SELECT c.id, c.version_id, v.document_id, c.text, c.heading_path, c.page_from, "
            "       bm25(chunk_headings) AS rank "
            "FROM chunk_headings "
            "JOIN chunk c ON c.rowid = chunk_headings.rowid "
            "JOIN document_version v ON v.id = c.version_id "
            "WHERE chunk_headings MATCH ?" + where + " ORDER BY rank, c.id LIMIT ?"
        )
        rows = self.db.execute(sql, [fts_query(query), *params, k]).fetchall()
        return [
            Hit(
                chunk_id=r["id"],
                score=-float(r["rank"]),
                text=r["text"],
                method="sparse",
                document_id=r["document_id"],
                version_id=r["version_id"],
                heading_path=loads(r["heading_path"], []),
                page_from=r["page_from"],
            )
            for r in rows
        ]

    # --- entities ------------------------------------------------------------

    def upsert_entity(self, e: Entity) -> str:
        self.db.execute(
            "INSERT INTO entity (id,workspace_id,type,canonical_name,normalised_name,aliases,"
            "attrs,embedding,first_seen,last_seen,merged_into,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name, "
            "aliases=excluded.aliases, attrs=excluded.attrs, embedding=excluded.embedding, "
            "last_seen=excluded.last_seen, status=excluded.status",
            (
                e.id, e.workspace_id, e.type, e.canonical_name, e.normalised_name,
                dumps(e.aliases), dumps(e.attrs), pack_vector(e.embedding),
                dt(e.first_seen), dt(e.last_seen), e.merged_into, e.status,
            ),
        )
        self.db.commit()
        return e.id

    def _entity(self, row: sqlite3.Row) -> Entity:
        return Entity(
            id=row["id"],
            workspace_id=row["workspace_id"],
            type=row["type"],
            canonical_name=row["canonical_name"],
            normalised_name=row["normalised_name"],
            aliases=loads(row["aliases"], []),
            attrs=loads(row["attrs"], {}),
            embedding=unpack_vector(row["embedding"]),
            first_seen=_as_date(row["first_seen"]),
            last_seen=_as_date(row["last_seen"]),
            merged_into=row["merged_into"],
            status=row["status"],
        )

    def get_entity(self, id: str) -> Entity | None:
        row = self.db.execute("SELECT * FROM entity WHERE id = ?", (id,)).fetchone()
        return self._entity(row) if row else None

    def find_entities(self, workspace_id: str, normalised_name: str) -> list[Entity]:
        rows = self.db.execute(
            "SELECT * FROM entity WHERE workspace_id = ? AND normalised_name = ? "
            "AND merged_into IS NULL",
            (workspace_id, normalised_name),
        ).fetchall()
        return [self._entity(r) for r in rows]

    def merge_entities(
        self, winner_id: str, loser_id: str, method: MergeMethod, decided_by: str, **kw: Any
    ) -> None:
        """Soft merge. Reversible by construction — over-merging is the failure
        that matters, so every merge is undoable and carries its evidence."""
        if winner_id == loser_id:
            raise StorageError("An entity cannot be merged into itself")
        self.db.execute("UPDATE entity SET merged_into = ?, status = 'merged' WHERE id = ?",
                        (winner_id, loser_id))
        self.db.execute(
            "INSERT INTO entity_merge_log (id,winner_id,loser_id,method,score,evidence,"
            "decided_by,decided_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_id(), winner_id, loser_id, method, kw.get("score"),
                dumps(kw.get("evidence", {})), decided_by, utcnow().isoformat(),
            ),
        )
        self.db.commit()

    def unmerge_entity(self, loser_id: str, decided_by: str) -> None:
        self.db.execute(
            "UPDATE entity SET merged_into = NULL, status = 'active' WHERE id = ?", (loser_id,)
        )
        self.db.execute(
            "UPDATE entity_merge_log SET reverted_at = ? "
            "WHERE loser_id = ? AND reverted_at IS NULL",
            (utcnow().isoformat(), loser_id),
        )
        self.db.commit()

    # --- the ledger ----------------------------------------------------------

    def add_assertion(self, a: Assertion, ev: list[Evidence] | None = None) -> str:
        """Assertion and evidence land in one transaction.

        Evidence is not optional and is not a second step that might be skipped:
        an assertion with no evidence is rejected here as well as being
        unconstructable in the model layer.
        """
        evidence = ev if ev is not None else a.evidence
        if not evidence:
            raise InvariantError(
                f"Assertion {a.id} has no evidence. Every claim carries its source."
            )
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO assertion (id,workspace_id,subject_id,predicate,object_id,"
                    "object_literal,claim_text,modality,confidence,valid_from,valid_to,"
                    "asserted_at,invalid_at,invalidated_by,invalidation_reason,status,"
                    "stale_after,verified_by,verified_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        a.id, a.workspace_id, a.subject_id, a.predicate, a.object_id,
                        a.object_literal, a.claim_text, a.modality, a.confidence,
                        dt(a.valid_from), dt(a.valid_to), a.asserted_at.isoformat(),
                        dt(a.invalid_at), a.invalidated_by, a.invalidation_reason,
                        a.status, dt(a.stale_after), a.verified_by, dt(a.verified_at),
                    ),
                )
                self.db.executemany(
                    "INSERT INTO assertion_evidence (assertion_id,chunk_id,quote,char_start,"
                    "char_end) VALUES (?,?,?,?,?)",
                    [(a.id, e.chunk_id, e.quote, e.char_start, e.char_end) for e in evidence],
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Could not store assertion {a.id}: {exc}") from exc
        return a.id

    def _assertion(self, row: sqlite3.Row) -> Assertion:
        ev = self.db.execute(
            "SELECT chunk_id, quote, char_start, char_end FROM assertion_evidence "
            "WHERE assertion_id = ?",
            (row["id"],),
        ).fetchall()
        return Assertion(
            id=row["id"],
            workspace_id=row["workspace_id"],
            subject_id=row["subject_id"],
            predicate=row["predicate"],
            object_id=row["object_id"],
            object_literal=row["object_literal"],
            claim_text=row["claim_text"],
            modality=row["modality"],
            confidence=row["confidence"],
            evidence=[
                Evidence(
                    chunk_id=e["chunk_id"],
                    quote=e["quote"],
                    char_start=e["char_start"],
                    char_end=e["char_end"],
                )
                for e in ev
            ],
            valid_from=_as_date(row["valid_from"]),
            valid_to=_as_date(row["valid_to"]),
            asserted_at=datetime.fromisoformat(row["asserted_at"]),
            invalid_at=_as_dt(row["invalid_at"]),
            invalidated_by=row["invalidated_by"],
            invalidation_reason=row["invalidation_reason"],
            status=row["status"],
            stale_after=_as_date(row["stale_after"]),
            verified_by=row["verified_by"],
            verified_at=_as_dt(row["verified_at"]),
        )

    def get_assertion(self, id: str) -> Assertion | None:
        row = self.db.execute("SELECT * FROM assertion WHERE id = ?", (id,)).fetchone()
        return self._assertion(row) if row else None

    def invalidate(self, id: str, by: str, reason: InvalidationReason) -> None:
        """The only mutation the ledger permits. Never a delete.

        ``by`` is the id of the assertion that supersedes this one, or an actor
        string when nothing replaces it.
        """
        row = self.db.execute("SELECT invalid_at FROM assertion WHERE id = ?", (id,)).fetchone()
        if not row:
            raise StorageError(f"No such assertion: {id}")
        if row["invalid_at"] is not None:
            raise InvariantError(
                f"Assertion {id} was already invalidated at {row['invalid_at']}; "
                "belief revision is recorded once, not rewritten"
            )
        replaces = self.db.execute("SELECT 1 FROM assertion WHERE id = ?", (by,)).fetchone()
        with self.db:
            self.db.execute(
                "UPDATE assertion SET invalid_at = ?, invalidated_by = ?, "
                "invalidation_reason = ?, status = 'invalidated' WHERE id = ?",
                (utcnow().isoformat(), by if replaces else None, reason, id),
            )

    def dispute(self, a_id: str, b_id: str) -> None:
        """Mark two assertions as contradicting each other.

        Contradictions are never merged and the store never picks a winner —
        both stay active and visible.
        """
        with self.db:
            self.db.executemany(
                "UPDATE assertion SET status = 'disputed' WHERE id = ? AND invalid_at IS NULL",
                [(a_id,), (b_id,)],
            )

    def active_assertions(self, workspace_id: str, **f: Any) -> list[Assertion]:
        sql = "SELECT * FROM assertion WHERE workspace_id = ? AND invalid_at IS NULL"
        params: list[Any] = [workspace_id]
        if predicate := f.get("predicate"):
            sql += " AND predicate = ?"
            params.append(predicate)
        if subject_id := f.get("subject_id"):
            sql += " AND subject_id = ?"
            params.append(subject_id)
        sql += " ORDER BY asserted_at"
        return [self._assertion(r) for r in self.db.execute(sql, params).fetchall()]

    def assertions_as_of(self, workspace_id: str, when: datetime, **f: Any) -> list[Assertion]:
        """What did we believe on this date?

        System time, not world time — this is the query a latest-state snapshot
        structurally cannot answer.
        """
        stamp = when.isoformat()
        sql = (
            "SELECT * FROM assertion WHERE workspace_id = ? AND asserted_at <= ? "
            "AND (invalid_at IS NULL OR invalid_at > ?)"
        )
        params: list[Any] = [workspace_id, stamp, stamp]
        if predicate := f.get("predicate"):
            sql += " AND predicate = ?"
            params.append(predicate)
        sql += " ORDER BY asserted_at"
        return [self._assertion(r) for r in self.db.execute(sql, params).fetchall()]

    # --- quarantine ----------------------------------------------------------

    def add_quarantine(self, version_id: str, spans: Iterable[Any]) -> None:
        """Record what the sanitiser found. Stored, not deleted - the operator
        gets to see what was in the file."""
        rows = list(spans)
        if not rows:
            return
        self.db.executemany(
            "INSERT INTO quarantine (id,version_id,char_start,char_end,text,reason,"
            "detected_at) VALUES (?,?,?,?,?,?,?)",
            [
                (new_id(), version_id, s.char_start, s.char_end, s.text, s.reason,
                 utcnow().isoformat())
                for s in rows
            ],
        )
        self.db.commit()

    def quarantine_for_version(self, version_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT char_start, char_end, text, reason FROM quarantine "
            "WHERE version_id = ? ORDER BY char_start",
            (version_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- listing -------------------------------------------------------------

    def list_documents(self, workspace_id: str, limit: int = 200) -> list[Document]:
        rows = self.db.execute(
            "SELECT id FROM document WHERE workspace_id = ? ORDER BY external_id LIMIT ?",
            (workspace_id, limit),
        ).fetchall()
        return [d for d in (self.get_document(r["id"]) for r in rows) if d is not None]

    def chunks_for_version(self, version_id: str) -> list[Chunk]:
        rows = self.db.execute(
            "SELECT * FROM chunk WHERE version_id = ? ORDER BY ordinal", (version_id,)
        ).fetchall()
        return [self._chunk(r) for r in rows]

    def latest_version_for(self, document_id: str) -> DocumentVersion | None:
        row = self.db.execute(
            "SELECT * FROM document_version WHERE document_id = ? "
            "ORDER BY version_no DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        return self._version(row) if row else None

    def next_version_no(self, document_id: str) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS n FROM document_version WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["n"]) + 1

    # --- runs and change events ---------------------------------------------

    def start_run(self, run: IngestRun) -> str:
        self.db.execute(
            "INSERT INTO ingest_run (id,workspace_id,source_id,trigger,started_at,stats) "
            "VALUES (?,?,?,?,?,?)",
            (run.id, run.workspace_id, run.source_id, run.trigger,
             run.started_at.isoformat(), dumps(run.stats)),
        )
        self.db.commit()
        return run.id

    def finish_run(self, run: IngestRun) -> None:
        self.db.execute(
            "UPDATE ingest_run SET finished_at=?, docs_seen=?, docs_changed=?, docs_new=?, "
            "docs_gone=?, stats=? WHERE id = ?",
            (
                dt(run.finished_at or utcnow()), run.docs_seen, run.docs_changed,
                run.docs_new, run.docs_gone, dumps(run.stats), run.id,
            ),
        )
        self.db.commit()

    def add_change_event(self, ev: ChangeEvent) -> None:
        self.db.execute(
            "INSERT INTO change_event (id,run_id,kind,assertion_id,prior_assertion_id,summary,"
            "detail) VALUES (?,?,?,?,?,?,?)",
            (ev.id, ev.run_id, ev.kind, ev.assertion_id, ev.prior_assertion_id,
             ev.summary, dumps(ev.detail)),
        )
        self.db.commit()

    def changes_for_run(self, run_id: str) -> list[ChangeEvent]:
        """The change report is a select, not a recomputation — which is what
        makes a report identical every time it is opened."""
        rows = self.db.execute(
            "SELECT * FROM change_event WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [
            ChangeEvent(
                id=r["id"],
                run_id=r["run_id"],
                kind=r["kind"],
                assertion_id=r["assertion_id"],
                prior_assertion_id=r["prior_assertion_id"],
                summary=r["summary"],
                detail=loads(r["detail"], {}),
            )
            for r in rows
        ]

    def record(self, r: RunRecord) -> None:
        self.db.execute(
            "INSERT INTO run_record (id,run_id,stage,model,input_tokens,output_tokens,cost_usd,"
            "duration_ms,error,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r.id, r.run_id, r.stage, r.model, r.input_tokens, r.output_tokens,
                r.cost_usd, r.duration_ms, r.error, r.created_at.isoformat(),
            ),
        )
        self.db.commit()

    def run_cost(self, run_id: str) -> float:
        row = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM run_record WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return float(row["total"])

    def counts(self) -> dict[str, int]:
        """Row counts for ``lkb doctor``."""
        tables = ("workspace", "source", "document", "document_version", "chunk",
                  "entity", "assertion", "change_event")
        out: dict[str, int] = {}
        for t in tables:
            row = self.db.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()  # noqa: S608
            out[t] = int(row["n"])
        return out

    def counts_for_workspace(self, workspace_id: str) -> dict[str, int]:
        """Row counts for one workspace, for a measurement header.

        Separate from ``counts`` because a measurement has to state the size of
        the corpus it ran against, and a store with a second workspace in it
        would otherwise inflate that figure without anything looking wrong.
        """
        tables = ("document", "chunk")
        out: dict[str, int] = {}
        for t in tables:
            row = self.db.execute(
                f"SELECT COUNT(*) AS n FROM {t} WHERE workspace_id = ?",  # noqa: S608
                (workspace_id,),
            ).fetchone()
            out[t] = int(row["n"])
        return out


__all__ = ["SqliteStore"]
