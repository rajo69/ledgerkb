"""The header every committed measurement carries.

ADR 0006 fixed this format before any measurement existed, on the grounds that
provenance rules written after the first number are rules the first number was
never held to. These tests are what keeps that true: the field list is read out
of the decision record rather than restated here, so the code and the record
cannot drift apart quietly.

The rest check the property the record cares about most, which is that a header
describes the run rather than the intent. A config can ask for one embedding
model and a store can hold vectors from another, and the header has to say what
the vectors were.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from dataclasses import fields
from pathlib import Path

import pytest

from ledgerkb.core.config import Config
from ledgerkb.evals.provenance import Provenance, collect
from ledgerkb.evals.provenance import _canonical as canonical
from ledgerkb.index.embed import embed_workspace
from ledgerkb.providers.fake import FakeEmbedder
from ledgerkb.storage.sqlite.store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]

PAPERS = [
    "The Committee approved the capital allocation of GBP 2.4m.",
    "The footbridge option appraisal recommends Option B.",
    "Housing delivery fell short of target in the year to March.",
]


def adr_fields() -> list[str]:
    """The field names ADR 0006 lists, read from the record itself."""
    text = (ROOT / "docs" / "adr" / "0006-measurement-provenance.md").read_text(
        encoding="utf-8"
    )
    block = re.search(r"^```\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    assert block is not None, "ADR 0006 no longer contains a fenced field list"
    return [line.split()[0] for line in block.group(1).splitlines() if line.strip()]


def docs_linter():
    """The repository's own Markdown linter, imported from ``scripts/``.

    Reused rather than reimplemented: results are committed Markdown, so they
    are linted by exactly this, and a second copy of the rules here would be a
    second copy to get wrong.
    """
    spec = importlib.util.spec_from_file_location(
        "check_docs", ROOT / "scripts" / "check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def indexed(store: SqliteStore, workspace, chunk_factory, config: Config) -> SqliteStore:
    store.add_chunks([chunk_factory(t, i) for i, t in enumerate(PAPERS)])
    embed_workspace(
        store,
        config,
        FakeEmbedder(name="fixture/embedder", dimensions=config.embeddings.dimensions),
        workspace.id,
    )
    return store


@pytest.fixture
def header(indexed: SqliteStore, workspace, config: Config) -> Provenance:
    return collect(
        store=indexed,
        cfg=config,
        workspace_id=workspace.id,
        corpus_scale=11,
        command="lkb evals run --scale 11",
    )


class TestTheRecordAndTheCodeAgree:
    def test_every_field_the_decision_record_lists_is_collected(self) -> None:
        collected = {f.name for f in fields(Provenance)}
        missing = set(adr_fields()) - collected
        assert not missing, f"ADR 0006 asks for fields the header does not carry: {missing}"

    def test_the_only_addition_is_the_dirty_flag(self) -> None:
        """ADR 0006 asks for the commit "with a dirty flag".

        It is carried as its own field rather than glued onto the SHA, because a
        machine reading the JSON should not have to parse a suffix to apply the
        admissibility rule. Anything else appearing here is drift.
        """
        extra = {f.name for f in fields(Provenance)} - set(adr_fields())
        assert extra == {"dirty"}


class TestFactRatherThanIntent:
    def test_the_embedding_model_is_the_one_that_made_the_vectors(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """The config names a model. The store knows what was actually run.

        ADR 0004's whole point, and the reason ADR 0006 says to read this field
        from ``embedding_space`` rather than from the config.
        """
        assert config.embeddings.model != "fixture/embedder"
        header = collect(
            store=indexed, cfg=config, workspace_id=workspace.id, corpus_scale=11
        )
        assert header.embedding_model == "fixture/embedder"
        assert header.embedding_dims == config.embeddings.dimensions

    def test_an_unindexed_workspace_claims_no_model(
        self, store: SqliteStore, workspace, config: Config
    ) -> None:
        header = collect(
            store=store, cfg=config, workspace_id=workspace.id, corpus_scale=0
        )
        assert header.embedding_model is None
        assert header.embedding_dims is None

    def test_the_counts_describe_the_workspace_that_was_measured(
        self, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """A second workspace in the same store must not inflate the corpus size.

        This is the failure the scoped count exists to prevent: the header would
        report a larger corpus than the run ever saw, and nothing would look
        wrong.
        """
        header = collect(
            store=indexed, cfg=config, workspace_id=workspace.id, corpus_scale=11
        )
        assert header.corpus_chunks == len(PAPERS)
        assert header.corpus_documents == 1

        from ledgerkb.core.models import Workspace

        other = Workspace(name="unrelated")
        indexed.add_workspace(other)
        again = collect(
            store=indexed, cfg=config, workspace_id=workspace.id, corpus_scale=11
        )
        assert again.corpus_chunks == header.corpus_chunks
        assert again.corpus_documents == header.corpus_documents


class TestAdmissibility:
    def test_a_dirty_tree_is_not_gate_evidence(self, header: Provenance) -> None:
        dirty = replace_field(header, dirty=True, ledgerkb_commit="a" * 40)
        assert not dirty.admissible
        assert "uncommitted" in (dirty.inadmissible_because or "")

    def test_a_run_with_no_commit_is_not_gate_evidence(self, header: Provenance) -> None:
        """Weaker than a dirty tree, not stronger. It names no starting point."""
        detached = replace_field(header, dirty=False, ledgerkb_commit=None)
        assert not detached.admissible
        assert "git checkout" in (detached.inadmissible_because or "")

    def test_a_clean_checkout_is_gate_evidence(self, header: Provenance) -> None:
        clean = replace_field(header, dirty=False, ledgerkb_commit="a" * 40)
        assert clean.admissible
        assert clean.inadmissible_because is None


class TestGitReading:
    """Against a real repository, because the git plumbing is the part most
    likely to be subtly wrong and the least likely to be noticed."""

    @pytest.fixture
    def repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from ledgerkb.evals import provenance

        root = tmp_path / "repo"
        root.mkdir()
        (root / "uv.lock").write_bytes(b"version = 1\n")
        (root / "tracked.txt").write_bytes(b"one\n")
        git(root, "init", "--quiet")
        git(root, "add", ".")
        git(
            root,
            "-c", "user.email=t@example.com",
            "-c", "user.name=Test",
            "commit", "--quiet", "-m", "initial",
        )
        monkeypatch.setattr(provenance, "_PACKAGE_DIR", root)
        return root

    def test_a_clean_checkout_reports_its_commit(
        self, repo: Path, store: SqliteStore, workspace, config: Config
    ) -> None:
        header = collect(
            store=store, cfg=config, workspace_id=workspace.id, corpus_scale=0
        )
        assert header.ledgerkb_commit is not None
        assert len(header.ledgerkb_commit) == 40
        assert not header.dirty
        assert header.admissible

    def test_a_modified_tracked_file_makes_the_run_inadmissible(
        self, repo: Path, store: SqliteStore, workspace, config: Config
    ) -> None:
        (repo / "tracked.txt").write_bytes(b"two\n")
        header = collect(
            store=store, cfg=config, workspace_id=workspace.id, corpus_scale=0
        )
        assert header.dirty
        assert not header.admissible

    def test_an_untracked_file_does_not(
        self, repo: Path, store: SqliteStore, workspace, config: Config
    ) -> None:
        """A scratch file beside the checkout does not change what the commit
        reproduces. Counting it would make almost every local run inadmissible
        and buy nothing."""
        (repo / "notes.txt").write_bytes(b"scratch\n")
        header = collect(
            store=store, cfg=config, workspace_id=workspace.id, corpus_scale=0
        )
        assert not header.dirty
        assert header.admissible

    def test_the_lockfile_is_hashed_from_that_checkout(
        self, repo: Path, store: SqliteStore, workspace, config: Config
    ) -> None:
        import hashlib

        header = collect(
            store=store, cfg=config, workspace_id=workspace.id, corpus_scale=0
        )
        expected = hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest()
        assert header.lockfile_sha256 == expected


class TestHashes:
    def test_the_config_hash_moves_when_the_config_does(
        self, indexed: SqliteStore, workspace
    ) -> None:
        a = collect(
            store=indexed, cfg=Config(), workspace_id=workspace.id, corpus_scale=11
        )
        b = collect(
            store=indexed,
            cfg=Config(retrieval={"dense_k": 17}),
            workspace_id=workspace.id,
            corpus_scale=11,
        )
        assert a.config_hash != b.config_hash

    def test_the_config_hash_does_not_depend_on_key_order(self) -> None:
        """Otherwise reordering a field in the config model would change the
        hash of a config nobody edited, and two runs would disagree about
        having used the same settings."""
        assert canonical({"a": 1, "b": {"c": 2, "d": 3}}) == canonical(
            {"b": {"d": 3, "c": 2}, "a": 1}
        )

    def test_the_golden_set_is_hashed_by_content(
        self, tmp_path: Path, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        import hashlib

        golden = tmp_path / "golden.jsonl"
        golden.write_bytes(b'{"q": "who approved it?"}\n')
        header = collect(
            store=indexed,
            cfg=config,
            workspace_id=workspace.id,
            corpus_scale=11,
            golden_set=golden,
        )
        assert header.golden_set_sha256 == hashlib.sha256(golden.read_bytes()).hexdigest()

    def test_no_golden_set_is_recorded_as_absent(self, header: Provenance) -> None:
        assert header.golden_set_sha256 is None

    def test_a_golden_set_path_that_does_not_exist_stops_the_run(
        self, tmp_path: Path, indexed: SqliteStore, workspace, config: Config
    ) -> None:
        """A mistyped path must not quietly produce a result with no golden set
        recorded, which would look like a run that never had one."""
        with pytest.raises(OSError):
            collect(
                store=indexed,
                cfg=config,
                workspace_id=workspace.id,
                corpus_scale=11,
                golden_set=tmp_path / "absent.jsonl",
            )


class TestBothHalvesCarryTheSameHeader:
    def test_the_json_half_holds_every_field(self, header: Provenance) -> None:
        data = header.as_dict()
        for name in adr_fields():
            assert name in data
        assert data["admissible"] is header.admissible
        json.dumps(data)  # it has to survive the trip it exists for

    def test_the_markdown_half_holds_every_field(self, header: Provenance) -> None:
        rendered = header.as_markdown()
        for name in adr_fields():
            assert f"| {name} |" in rendered

    def test_the_markdown_obeys_the_documentation_rules(
        self, header: Provenance, tmp_path: Path
    ) -> None:
        """Results are committed Markdown, so ``check_docs.py`` lints them like
        anything else. A generated file that fails the repository's own lint is
        a generator that has to be fixed, not a file to exempt."""
        linter = docs_linter()
        path = tmp_path / "result.md"
        path.write_text(header.as_markdown(), encoding="utf-8")
        assert linter.check(path, linter.load_banned()) == []

    def test_an_absent_value_reads_as_absent(self, header: Provenance) -> None:
        assert "| golden_set_sha256 | none |" in header.as_markdown()

    def test_a_boolean_is_spelled_the_way_the_json_half_spells_it(
        self, header: Provenance
    ) -> None:
        """So the two files can be read against each other without translating
        Python's capitalisation in your head."""
        assert "| dirty | true |" in replace_field(header, dirty=True).as_markdown()
        assert "| dirty | false |" in replace_field(header, dirty=False).as_markdown()

    def test_a_pipe_in_a_value_cannot_break_the_table(self, header: Provenance) -> None:
        piped = replace_field(header, command="lkb evals run | tee out.txt")
        row = [
            line
            for line in piped.as_markdown().splitlines()
            if line.startswith("| command |")
        ]
        assert len(row) == 1
        assert row[0].count("|") == 3 + 1  # three cell borders, one escaped pipe
        assert r"\|" in row[0]


class TestTheCommandIsRecorded:
    def test_a_caller_that_is_not_a_command_line_can_say_so(
        self, header: Provenance
    ) -> None:
        assert header.command == "lkb evals run --scale 11"

    def test_the_default_does_not_carry_the_path_it_was_run_from(
        self, indexed: SqliteStore, workspace, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A committed result should not name somebody's home directory."""
        monkeypatch.setattr(
            "sys.argv", [r"C:\Users\someone\.venv\Scripts\lkb", "evals", "run"]
        )
        header = collect(
            store=indexed, cfg=config, workspace_id=workspace.id, corpus_scale=11
        )
        assert "someone" not in header.command
        assert header.command.startswith("lkb evals run")


def replace_field(header: Provenance, **kw: object) -> Provenance:
    import dataclasses

    return dataclasses.replace(header, **kw)  # type: ignore[arg-type]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )
