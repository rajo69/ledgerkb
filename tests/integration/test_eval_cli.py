"""Integration tests for the 'lkb eval' CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ledgerkb.cli.main import app

runner = CliRunner()


@pytest.fixture
def eval_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "."])

    # Create and ingest test document
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "cabinet-minutes.md").write_text(
        "# Cabinet Minutes\n\n"
        "## Item 1: Attercliffe Regeneration\n\n"
        "The capital budget was confirmed at £2.4m.\n",
        encoding="utf-8",
    )
    runner.invoke(app, ["ingest", str(papers)])

    # Create golden set
    golden = tmp_path / "golden.toml"
    golden.write_text(
        """
corpus_scale = 0

[[question]]
id = "attercliffe-budget"
question = "What capital budget was confirmed for Attercliffe?"
answerable = true
shape = "figure-across-quarters"

[[question.relevant]]
document = "cabinet-minutes.md"
quote = "capital budget was confirmed at £2.4m"

[[question]]
id = "unanswerable-test"
question = "What is the budget for the skybridge?"
answerable = false
shape = "unanswerable"
""",
        encoding="utf-8",
    )

    return tmp_path


class TestEvalCLI:
    def test_eval_help(self) -> None:
        res = runner.invoke(app, ["eval", "--help"])
        assert res.exit_code == 0
        assert "retrieval" in res.output

    def test_eval_retrieval_runs_and_prints_summary(self, eval_workdir: Path) -> None:
        res = runner.invoke(
            app,
            ["eval", "retrieval", "golden.toml", "--arms", "sparse,headings"],
        )
        assert res.exit_code == 0, res.output
        assert "Retrieval Evaluation" in res.output
        assert "recall@20" in res.output
        assert "Gate Verdict" in res.output

    def test_eval_retrieval_json_output(self, eval_workdir: Path) -> None:
        res = runner.invoke(
            app,
            ["eval", "retrieval", "golden.toml", "--arms", "sparse,headings", "--json"],
        )
        assert res.exit_code == 0, res.output
        data = json.loads(res.output)
        assert "summary" in data
        assert "recall@20" in data["summary"]
        assert len(data["questions"]) == 1

    def test_eval_retrieval_save(self, eval_workdir: Path) -> None:
        out_dir = eval_workdir / "results"
        res = runner.invoke(
            app,
            [
                "eval",
                "retrieval",
                "golden.toml",
                "--arms",
                "sparse,headings",
                "--save",
                "--out-dir",
                str(out_dir),
            ],
        )
        assert res.exit_code == 0, res.output
        assert out_dir.exists()
        json_files = list(out_dir.glob("*.json"))
        md_files = list(out_dir.glob("*.md"))
        assert len(json_files) == 1
        assert len(md_files) == 1
