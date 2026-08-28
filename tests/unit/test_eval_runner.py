"""Unit tests for the retrieval evaluation runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerkb.core.config import Config
from ledgerkb.core.models import Chunk, Document, DocumentVersion, Source, Workspace
from ledgerkb.evals.metrics import GATE_K
from ledgerkb.evals.runner import EvaluationError, run_retrieval_eval
from ledgerkb.providers.fake import FakeEmbedder
from ledgerkb.storage.sqlite.store import SqliteStore


@pytest.fixture
def eval_fixture(tmp_path: Path) -> tuple[SqliteStore, Config, Path, str]:
    db_path = tmp_path / "test.db"
    store = SqliteStore(db_path)
    store.migrate()

    cfg = Config()

    ws = Workspace(name="test")
    store.add_workspace(ws)

    src = Source(workspace_id=ws.id, kind="upload", label="docs")
    store.add_source(src)

    doc = Document(
        workspace_id=ws.id,
        source_id=src.id,
        external_id="doc1.md",
        title="Attercliffe Regeneration Plan",
    )
    doc_id = store.upsert_document(doc)

    content = (
        "# Attercliffe Project\n\n"
        "## Budget\n"
        "The total approved capital budget for Attercliffe was confirmed at £2.4m.\n\n"
        "## Timeline\n"
        "Construction is scheduled to begin in Q3 2026."
    )
    ver = DocumentVersion(
        document_id=doc_id,
        version_no=1,
        content_hash="a" * 64,
        text_hash="b" * 64,
        mime="text/markdown",
        parser="text",
        parse_quality=1.0,
        text=content,
    )
    store.add_version(ver)

    chunks = [
        Chunk(
            workspace_id=ws.id,
            version_id=ver.id,
            ordinal=0,
            text="The total approved capital budget for Attercliffe was confirmed at £2.4m.",
            heading_path=["Attercliffe Project", "Budget"],
            char_start=content.index("The total approved capital budget"),
            char_end=content.index("The total approved capital budget") + 72,
            token_count=15,
        ),
        Chunk(
            workspace_id=ws.id,
            version_id=ver.id,
            ordinal=1,
            text="Construction is scheduled to begin in Q3 2026.",
            heading_path=["Attercliffe Project", "Timeline"],
            char_start=content.index("Construction is scheduled"),
            char_end=content.index("Construction is scheduled") + 46,
            token_count=9,
        ),
    ]

    embedder = FakeEmbedder(dimensions=8)
    for c in chunks:
        c.embedding = embedder.embed([c.embed_text])[0]
    store.add_chunks(chunks)
    store.record_embedding_space(ws.id, embedder.name, embedder.dimensions)

    golden_path = tmp_path / "golden.toml"
    golden_path.write_text(
        """
corpus_scale = 0

[[question]]
id = "q1"
question = "What is the capital budget for Attercliffe?"
answerable = true
shape = "single-format"

[[question.relevant]]
document = "doc1.md"
quote = "total approved capital budget for Attercliffe was confirmed at £2.4m"

[[question]]
id = "q2"
question = "What is the budget for the skybridge?"
answerable = false
shape = "unanswerable"
""",
        encoding="utf-8",
    )

    return store, cfg, golden_path, ws.id


def test_eval_runner_runs_and_scores(
    eval_fixture: tuple[SqliteStore, Config, Path, str],
    tmp_path: Path,
) -> None:
    store, cfg, golden_path, ws_id = eval_fixture
    embedder = FakeEmbedder(dimensions=8)

    result = run_retrieval_eval(
        store=store,
        cfg=cfg,
        golden_set_path=golden_path,
        workspace_id=ws_id,
        arms=("dense", "sparse", "headings"),
        compare_arms=True,
        embedder=embedder,
    )

    assert result.main_scores.questions_scored == 1
    assert result.main_scores.questions_unanswerable == 1
    assert result.main_scores.recall[GATE_K] == 1.0
    assert result.main_scores.recall[5] == 1.0
    assert result.main_scores.ndcg == 1.0
    assert result.main_scores.mrr == 1.0

    assert result.arm_scores is not None
    assert "hybrid" in result.arm_scores
    assert "dense" in result.arm_scores
    assert "sparse (BM25)" in result.arm_scores
    assert "headings" in result.arm_scores

    data = result.as_dict()
    assert data["summary"]["recall@20"] == 1.0
    assert "arm_comparison" in data
    assert "provenance" in data

    md = result.as_markdown()
    assert "Retrieval Evaluation:" in md
    assert "Arm Comparison" in md

    out_dir = tmp_path / "results"
    json_path, md_path = result.save(out_dir)
    assert json_path.exists()
    assert md_path.exists()


def test_eval_runner_refuses_when_requested_arm_did_not_run(
    eval_fixture: tuple[SqliteStore, Config, Path, str],
) -> None:
    store, cfg, golden_path, ws_id = eval_fixture

    # Dense requested without providing an embedder -> must raise EvaluationError
    with pytest.raises(EvaluationError, match="Retrieval arm 'dense' was requested"):
        run_retrieval_eval(
            store=store,
            cfg=cfg,
            golden_set_path=golden_path,
            workspace_id=ws_id,
            arms=("dense", "sparse"),
            embedder=None,
        )


def test_inadmissible_provenance_fails_gate_verdict(
    eval_fixture: tuple[SqliteStore, Config, Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, cfg, golden_path, ws_id = eval_fixture

    import ledgerkb.evals.provenance as prov_mod

    # Force provenance to report dirty tree
    orig_collect = prov_mod.collect

    def fake_collect(*args: object, **kwargs: object) -> prov_mod.Provenance:
        p = orig_collect(*args, **kwargs)
        return prov_mod.Provenance(
            run_at=p.run_at,
            ledgerkb_commit=p.ledgerkb_commit,
            dirty=True,
            lockfile_sha256=p.lockfile_sha256,
            config_hash=p.config_hash,
            corpus_scale=p.corpus_scale,
            corpus_documents=p.corpus_documents,
            corpus_chunks=p.corpus_chunks,
            golden_set_sha256=p.golden_set_sha256,
            embedding_model=p.embedding_model,
            embedding_dims=p.embedding_dims,
            python=p.python,
            platform=p.platform,
            command=p.command,
        )

    monkeypatch.setattr(prov_mod, "collect", fake_collect)

    result = run_retrieval_eval(
        store=store,
        cfg=cfg,
        golden_set_path=golden_path,
        workspace_id=ws_id,
        arms=("sparse", "headings"),
    )

    # Scores may be 100%, but because provenance is dirty (inadmissible), meets_gate is False
    assert not result.provenance.admissible
    assert not result.meets_gate


def golden_set_path(path: Path) -> Path:
    return path
