"""The L1 exit gate, as tests.

Each class here corresponds to one checkbox in `03-IMPLEMENTATION-PLAN.md §L1`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerkb.core.config import Config
from ledgerkb.core.models import Source, Workspace
from ledgerkb.ingest.metadata import REQUIRED_FIELDS, coverage_report
from ledgerkb.ingest.pipeline import IngestPipeline
from ledgerkb.storage.sqlite.store import SqliteStore


@pytest.fixture
def pipeline(store: SqliteStore, config: Config) -> IngestPipeline:
    return IngestPipeline(store, config)


@pytest.fixture
def report(pipeline: IngestPipeline, store: SqliteStore, workspace: Workspace, corpus: Path):
    source = Source(workspace_id=workspace.id, kind="upload", label="fixtures")
    store.add_source(source)
    return pipeline.ingest_path(corpus, workspace.id, source)


class TestCorpusIngests:
    """20-document fixture corpus ingests with zero unhandled exceptions."""

    def test_every_document_is_accounted_for(self, report, corpus: Path) -> None:
        assert len(report.outcomes) == len(list(corpus.iterdir())) == 20

    def test_nothing_failed(self, report) -> None:
        assert report.failed == [], [
            f"{o.external_id}: {o.error}" for o in report.failed
        ]

    def test_every_format_produced_chunks(self, report) -> None:
        assert all(o.chunks > 0 for o in report.ingested)

    def test_all_tier_zero_parsers_were_exercised(self, report) -> None:
        used = {o.parser for o in report.ingested}
        assert used == {
            "text", "csv", "json", "email", "selectolax",
            "pypdfium2", "python-docx", "openpyxl", "python-pptx",
        }


class TestOffsetInvariant:
    """Every chunk's char_start:char_end slices back byte-identical.

    The property test in tests/property covers arbitrary input; this one covers
    the real corpus, through the real store.
    """

    def test_every_chunk_slices_back_from_stored_text(
        self, report, store: SqliteStore
    ) -> None:
        checked = 0
        for outcome in report.ingested:
            version = store.get_version(outcome.version_id)
            assert version is not None and version.text is not None
            for chunk in store.chunks_for_version(version.id):
                assert version.text[chunk.char_start : chunk.char_end] == chunk.text, (
                    f"{outcome.external_id} ordinal {chunk.ordinal} does not slice back"
                )
                checked += 1
        assert checked == report.total_chunks > 0

    def test_chunks_carry_no_leading_or_trailing_whitespace(
        self, report, store: SqliteStore
    ) -> None:
        for outcome in report.ingested:
            for chunk in store.chunks_for_version(outcome.version_id):
                assert chunk.text == chunk.text.strip()

    def test_ordinals_are_dense_and_ordered(self, report, store: SqliteStore) -> None:
        for outcome in report.ingested:
            ordinals = [c.ordinal for c in store.chunks_for_version(outcome.version_id)]
            assert ordinals == list(range(len(ordinals)))


class TestMetadataCoverage:
    """All five required fields on >= 90% of fixtures; misses reported."""

    def test_each_field_clears_ninety_percent(self, report) -> None:
        coverage = coverage_report([o.metadata for o in report.ingested if o.metadata])
        below = {k: v for k, v in coverage.items() if v < 0.9}
        assert not below, f"below the 90% gate: {below}"

    def test_misses_are_recorded_never_silently_null(
        self, report, store: SqliteStore
    ) -> None:
        for outcome in report.ingested:
            version = store.get_version(outcome.version_id)
            assert version is not None
            meta = outcome.metadata
            assert meta is not None
            # Whatever is missing is named on the version, not left to be
            # discovered later as a hole in the corpus.
            assert set(version.metadata_misses) == set(meta.misses)
            assert set(meta.misses) <= set(REQUIRED_FIELDS)

    def test_metadata_reaches_the_document_row(self, report, store: SqliteStore) -> None:
        titled = [
            d for d in store.list_documents(report.run.workspace_id) if d.title
        ]
        assert len(titled) == len(report.ingested)


class TestDedupe:
    """Stage 3's early exit is what makes refresh nearly free."""

    def test_reingesting_changes_nothing(
        self, report, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, corpus: Path
    ) -> None:
        source = Source(id=report.run.source_id, workspace_id=workspace.id,
                        kind="upload", label="fixtures")
        second = pipeline.ingest_path(corpus, workspace.id, source)

        assert len(second.unchanged) == 20
        assert second.ingested == []
        assert second.total_chunks == 0

    def test_no_duplicate_versions_are_created(
        self, report, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, corpus: Path
    ) -> None:
        before = store.counts()["document_version"]
        source = Source(id=report.run.source_id, workspace_id=workspace.id,
                        kind="upload", label="fixtures")
        pipeline.ingest_path(corpus, workspace.id, source)
        assert store.counts()["document_version"] == before

    def test_a_changed_document_produces_a_new_version(
        self, report, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, corpus: Path, tmp_path: Path
    ) -> None:
        edited = tmp_path / "edit"
        edited.mkdir()
        name = "cabinet-minutes-2026-04-08.md"
        original = (corpus / name).read_text(encoding="utf-8")
        (edited / name).write_text(original + "\n## Item 3: New\n\nAdded later.\n",
                                   encoding="utf-8")

        source = Source(id=report.run.source_id, workspace_id=workspace.id,
                        kind="upload", label="fixtures")
        second = pipeline.ingest_path(edited, workspace.id, source)

        assert len(second.ingested) == 1
        doc_id = second.ingested[0].document_id
        assert store.next_version_no(doc_id) == 3, "version 1 and 2 both retained"


class TestFailuresAreIsolated:
    """A parse failure names its document and the run continues."""

    def test_one_bad_file_does_not_stop_the_others(
        self, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, tmp_path: Path
    ) -> None:
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "good.md").write_text("# Fine\n\nBody text.\n", encoding="utf-8")
        (d / "broken.json").write_text("{not valid json", encoding="utf-8")
        (d / "also-good.txt").write_text("Plain text.\n", encoding="utf-8")

        source = Source(workspace_id=workspace.id, kind="upload", label="mixed")
        store.add_source(source)
        report = pipeline.ingest_path(d, workspace.id, source)

        assert len(report.ingested) == 2
        assert len(report.failed) == 1
        assert report.failed[0].external_id == "broken.json"
        assert "invalid JSON" in (report.failed[0].error or "")

    def test_an_unsupported_format_is_named_not_guessed(
        self, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, tmp_path: Path
    ) -> None:
        d = tmp_path / "legacy"
        d.mkdir()
        (d / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0legacy word")

        source = Source(workspace_id=workspace.id, kind="upload", label="legacy")
        store.add_source(source)
        report = pipeline.ingest_path(d, workspace.id, source)

        assert len(report.failed) == 1
        assert "legacy Word" in (report.failed[0].error or "")


class TestZipIngest:
    def test_a_zip_expands_into_its_members(
        self, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, tmp_path: Path
    ) -> None:
        import zipfile

        d = tmp_path / "zipped"
        d.mkdir()
        with zipfile.ZipFile(d / "papers.zip", "w") as z:
            z.writestr("minutes.md", "# Minutes\n\nItem 1 agreed.\n")
            z.writestr("notes/site.txt", "Site visit note.\n")

        source = Source(workspace_id=workspace.id, kind="upload", label="zip")
        store.add_source(source)
        report = pipeline.ingest_path(d, workspace.id, source)

        assert len(report.ingested) == 2
        assert {o.external_id for o in report.ingested} == {
            "papers.zip!minutes.md", "papers.zip!notes/site.txt"
        }


class TestQuarantineIsStored:
    def test_injection_fixtures_land_in_the_quarantine_table(
        self, pipeline: IngestPipeline, store: SqliteStore,
        workspace: Workspace, injections: Path
    ) -> None:
        source = Source(workspace_id=workspace.id, kind="upload", label="injections")
        store.add_source(source)
        report = pipeline.ingest_path(injections, workspace.id, source)

        assert report.failed == []
        flagged = [o for o in report.ingested if o.quarantined]
        assert len(flagged) == 9, "nine of ten fixtures carry an attack"

        benign = next(o for o in report.ingested if "09-benign" in o.external_id)
        assert benign.quarantined == 0

        for outcome in flagged:
            rows = store.quarantine_for_version(outcome.version_id)
            assert rows, f"{outcome.external_id} was counted but not stored"


class TestBudgetGuard:
    def test_the_document_ceiling_aborts_the_run(
        self, store: SqliteStore, workspace: Workspace, corpus: Path
    ) -> None:
        from ledgerkb.core.errors import BudgetExceededError

        cfg = Config()
        cfg.budget.max_docs_per_run = 3
        source = Source(workspace_id=workspace.id, kind="upload", label="capped")
        store.add_source(source)

        with pytest.raises(BudgetExceededError, match="max_docs_per_run"):
            IngestPipeline(store, cfg).ingest_path(corpus, workspace.id, source)
