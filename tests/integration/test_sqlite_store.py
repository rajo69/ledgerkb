"""The L0 gate: every core model round-trips through SQLite unchanged, and the
ledger's append-only guarantee holds against direct attack."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ledgerkb.core.errors import InvariantError
from ledgerkb.core.models import (
    Assertion,
    ChangeEvent,
    Entity,
    Evidence,
    IngestRun,
    RunRecord,
    utcnow,
)
from ledgerkb.storage.sqlite.store import SqliteStore


class TestMigrations:
    def test_migrate_is_idempotent(self, store: SqliteStore) -> None:
        from ledgerkb.storage.base import discover_migrations

        latest = discover_migrations()[-1].version
        assert store.schema_version() == latest
        assert store.migrate() == latest, "re-running must be a no-op"

    def test_fresh_store_reports_version_zero(self, tmp_path) -> None:
        s = SqliteStore(tmp_path / "fresh.db")
        assert s.schema_version() == 0
        s.close()


class TestRoundTrip:
    def test_document_round_trips(self, store: SqliteStore, version) -> None:
        doc = store.get_document(version.document_id)
        assert doc is not None
        assert doc.title == "Cabinet minutes, 11 March 2026"
        assert doc.current_version_id == version.id

    def test_version_round_trips(self, store: SqliteStore, version) -> None:
        got = store.get_version(version.id)
        assert got == version

    def test_chunk_round_trips_including_its_vector(
        self, store: SqliteStore, chunk_factory, embedder
    ) -> None:
        c = chunk_factory("The budget was set at £2.4m.", heading_path=["Item 4", "Budget"])
        c.embedding = embedder.embed([c.embed_text])[0]
        store.add_chunks([c])

        got = store.get_chunk(c.id)
        assert got is not None
        assert got.text == c.text
        assert got.heading_path == ["Item 4", "Budget"]
        assert got.embedding is not None
        # float32 storage, so compare at float32 precision rather than exactly
        assert all(abs(a - b) < 1e-6 for a, b in zip(got.embedding, c.embedding, strict=True))

    def test_entity_round_trips(self, store: SqliteStore, workspace) -> None:
        e = Entity(
            workspace_id=workspace.id,
            type="Organisation",
            canonical_name="Sheffield City Council",
            normalised_name="sheffield city council",
            aliases=["SCC"],
            attrs={"region": "South Yorkshire"},
            first_seen=date(2026, 1, 1),
        )
        store.upsert_entity(e)
        assert store.get_entity(e.id) == e

    def test_assertion_round_trips_with_its_evidence(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        c = chunk_factory("The budget was set at £2.4m.")
        store.add_chunks([c])
        a = Assertion(
            workspace_id=workspace.id,
            predicate="owns",
            object_literal="£2.4m",
            claim_text="The Attercliffe budget is £2.4m.",
            modality="explicit",
            evidence=[Evidence(chunk_id=c.id, quote="The budget was set at £2.4m.",
                               char_start=0, char_end=28)],
            valid_from=date(2026, 3, 11),
        )
        store.add_assertion(a)
        got = store.get_assertion(a.id)
        assert got == a


class TestAppendOnly:
    def _stored(self, store: SqliteStore, workspace, chunk_factory, **kw) -> Assertion:
        c = chunk_factory("The site is owned by the council.")
        store.add_chunks([c])
        a = Assertion(
            workspace_id=workspace.id,
            predicate="owns",
            claim_text=kw.pop("claim_text", "The council owns the site."),
            modality="explicit",
            evidence=[Evidence(chunk_id=c.id, quote="The site is owned by the council.")],
            **kw,
        )
        store.add_assertion(a)
        return a

    def test_invalidate_sets_the_flag_and_never_deletes(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory)
        store.invalidate(a.id, by="agent/test", reason="superseded")

        got = store.get_assertion(a.id)
        assert got is not None, "the row must survive invalidation"
        assert got.invalid_at is not None
        assert got.status == "invalidated"
        assert store.active_assertions(workspace.id) == []

    def test_invalidating_twice_is_refused(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory)
        store.invalidate(a.id, by="agent/test", reason="superseded")
        with pytest.raises(InvariantError, match="already invalidated"):
            store.invalidate(a.id, by="agent/test", reason="corrected")

    def test_deleting_an_assertion_is_blocked_by_the_database(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory)
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("DELETE FROM assertion WHERE id = ?", (a.id,))

    def test_deleting_evidence_is_blocked_by_the_database(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory)
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("DELETE FROM assertion_evidence WHERE assertion_id = ?", (a.id,))

    def test_an_assertion_with_no_evidence_is_refused_at_the_store_too(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory)
        with pytest.raises(InvariantError, match="no evidence"):
            store.add_assertion(a, ev=[])

    def test_contradictions_stay_active_and_unmerged(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        a = self._stored(store, workspace, chunk_factory, claim_text="The site is council-owned.")
        b = self._stored(store, workspace, chunk_factory, claim_text="The site is privately owned.")
        store.dispute(a.id, b.id)

        active = store.active_assertions(workspace.id)
        assert len(active) == 2, "the store never picks a winner"
        assert {x.status for x in active} == {"disputed"}


class TestBitemporal:
    def test_as_of_answers_what_we_believed_then(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        c = chunk_factory("Owner: Jane Smith")
        store.add_chunks([c])
        ev = [Evidence(chunk_id=c.id, quote="Owner: Jane Smith")]

        before = utcnow() - timedelta(days=1)
        a = Assertion(workspace_id=workspace.id, predicate="owns",
                      claim_text="Jane Smith owns the action.", modality="explicit", evidence=ev)
        store.add_assertion(a)
        store.invalidate(a.id, by="agent/test", reason="superseded")

        assert store.active_assertions(workspace.id) == []
        assert store.assertions_as_of(workspace.id, before) == []

        mid = a.asserted_at + timedelta(microseconds=1)
        as_of = store.assertions_as_of(workspace.id, mid)
        assert [x.id for x in as_of] == [a.id], "we believed it at that instant"


class TestEntityResolution:
    def test_merge_is_soft_and_reversible(self, store: SqliteStore, workspace) -> None:
        winner = Entity(workspace_id=workspace.id, type="Person",
                        canonical_name="J. Smith", normalised_name="j smith")
        loser = Entity(workspace_id=workspace.id, type="Person",
                       canonical_name="Jane Smith", normalised_name="jane smith")
        store.upsert_entity(winner)
        store.upsert_entity(loser)

        store.merge_entities(winner.id, loser.id, method="trigram",
                             decided_by="agent/test", score=0.91)
        merged = store.get_entity(loser.id)
        assert merged is not None and merged.merged_into == winner.id

        store.unmerge_entity(loser.id, decided_by="human:test")
        restored = store.get_entity(loser.id)
        assert restored is not None
        assert restored.merged_into is None
        assert restored.status == "active"

    def test_merged_entities_drop_out_of_lookup(self, store: SqliteStore, workspace) -> None:
        a = Entity(workspace_id=workspace.id, type="Person",
                   canonical_name="A", normalised_name="dup")
        b = Entity(workspace_id=workspace.id, type="Person",
                   canonical_name="B", normalised_name="dup")
        store.upsert_entity(a)
        store.upsert_entity(b)
        assert len(store.find_entities(workspace.id, "dup")) == 2
        store.merge_entities(a.id, b.id, method="exact", decided_by="agent/test")
        assert [e.id for e in store.find_entities(workspace.id, "dup")] == [a.id]

    def test_self_merge_is_refused(self, store: SqliteStore, workspace) -> None:
        e = Entity(workspace_id=workspace.id, type="Person",
                   canonical_name="A", normalised_name="a")
        store.upsert_entity(e)
        with pytest.raises(Exception, match="itself"):
            store.merge_entities(e.id, e.id, method="exact", decided_by="agent/test")


class TestRetrieval:
    def test_sparse_search_finds_the_right_chunk(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        store.add_chunks([
            chunk_factory("The Attercliffe regeneration budget was set at £2.4m.", 0),
            chunk_factory("Refuse collection moves to fortnightly from April.", 1),
        ])
        hits = store.search_sparse("attercliffe budget", k=5, workspace_id=workspace.id)
        assert hits
        assert "Attercliffe" in hits[0].text

    def test_sparse_search_survives_fts_metacharacters(
        self, store: SqliteStore, workspace, chunk_factory
    ) -> None:
        store.add_chunks([chunk_factory("Budget decisions for 2026.", 0)])
        assert store.search_sparse('budget AND "(', k=5, workspace_id=workspace.id) is not None

    def test_dense_search_ranks_by_cosine(
        self, store: SqliteStore, workspace, chunk_factory, embedder
    ) -> None:
        target = chunk_factory("The Attercliffe regeneration budget was set at £2.4m.", 0)
        other = chunk_factory("Refuse collection moves to fortnightly from April.", 1)
        for c in (target, other):
            c.embedding = embedder.embed([c.embed_text])[0]
        store.add_chunks([target, other])

        q = embedder.embed([target.embed_text])[0]
        hits = store.search_dense(q, k=2, workspace_id=workspace.id)
        assert hits[0].chunk_id == target.id
        assert hits[0].score > 0.99

    def test_dense_search_ignores_chunks_with_no_vector(
        self, store: SqliteStore, workspace, chunk_factory, embedder
    ) -> None:
        store.add_chunks([chunk_factory("no vector here", 0)])
        assert store.search_dense(embedder.embed(["anything"])[0], k=5,
                                  workspace_id=workspace.id) == []


class TestRunsAndChanges:
    def test_change_report_is_a_select_not_a_recomputation(
        self, store: SqliteStore, workspace
    ) -> None:
        run = IngestRun(workspace_id=workspace.id, trigger="manual")
        store.start_run(run)
        store.add_change_event(ChangeEvent(run_id=run.id, kind="new",
                                           summary="3 new decisions recorded"))
        store.add_change_event(ChangeEvent(run_id=run.id, kind="outdated",
                                           summary="1 action superseded"))
        run.docs_seen = 56
        store.finish_run(run)

        first = store.changes_for_run(run.id)
        second = store.changes_for_run(run.id)
        assert [e.summary for e in first] == [
            "3 new decisions recorded", "1 action superseded"
        ]
        assert first == second, "reports are stable artifacts"

    def test_cost_accumulates_per_run(self, store: SqliteStore, workspace) -> None:
        run = IngestRun(workspace_id=workspace.id, trigger="initial")
        store.start_run(run)
        store.record(RunRecord(run_id=run.id, stage="extract", cost_usd=0.4))
        store.record(RunRecord(run_id=run.id, stage="embed", cost_usd=0.1))
        assert store.run_cost(run.id) == pytest.approx(0.5)


class TestConfigStamp:
    def test_receipt_round_trips(self, store: SqliteStore) -> None:
        from ledgerkb.core.config import Config

        cfg = Config()
        store.stamp_config(cfg.build_receipt())
        assert Config.model_validate(store.stamped_config()) == cfg
