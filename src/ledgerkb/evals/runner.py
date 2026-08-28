"""Retrieval evaluation runner.

Orchestrates loading golden question sets, resolving relevant quotes to stored
chunk IDs, executing hybrid retrieval queries against the store, calculating
recall@20, recall@5, nDCG@10, MRR, and writing ADR 0006/0009 compliant artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ledgerkb.core.config import Config
from ledgerkb.core.errors import LedgerKBError
from ledgerkb.core.ports import Embedder, Reranker
from ledgerkb.evals.golden import load as load_golden_set
from ledgerkb.evals.metrics import (
    GATE_K,
    QuestionScores,
    RunScores,
    aggregate,
    score_question,
)
from ledgerkb.evals.provenance import Provenance
from ledgerkb.evals.provenance import collect as collect_provenance
from ledgerkb.index.hybrid import search as hybrid_search
from ledgerkb.storage.sqlite.store import SqliteStore


class EvaluationError(LedgerKBError):
    """Raised when an evaluation run fails or cannot execute requested arms."""


@dataclass(frozen=True)
class EvalRunResult:
    """Complete results from a retrieval evaluation run."""

    provenance: Provenance
    golden_set_path: Path
    main_scores: RunScores
    arm_scores: dict[str, RunScores] | None = None
    gate_problems: list[str] | None = None
    question_details: list[dict[str, object]] | None = None

    @property
    def meets_gate(self) -> bool:
        """Passes if the run meets gate scores, has zero gate structural problems,
        and provenance is admissible (clean git tree per ADR 0006 and ADR 0009).
        """
        return (
            self.provenance.admissible
            and self.main_scores.meets_gate()
            and not self.gate_problems
        )

    def as_dict(self) -> dict[str, object]:
        """Format complete run results as JSON-serializable dictionary."""
        data: dict[str, object] = {
            "provenance": self.provenance.as_dict(),
            "golden_set": str(self.golden_set_path),
            "meets_gate": self.meets_gate,
            "gate_problems": self.gate_problems or [],
            "summary": {
                "recall@20": round(self.main_scores.recall.get(GATE_K, 0.0), 4),
                "recall@5": round(self.main_scores.recall.get(5, 0.0), 4),
                "nDCG@10": round(self.main_scores.ndcg, 4),
                "mrr": round(self.main_scores.mrr, 4),
                "questions_scored": self.main_scores.questions_scored,
                "questions_unanswerable": self.main_scores.questions_unanswerable,
            },
        }

        if self.arm_scores:
            data["arm_comparison"] = {
                arm_name: {
                    "recall@20": round(scores.recall.get(GATE_K, 0.0), 4),
                    "recall@5": round(scores.recall.get(5, 0.0), 4),
                    "nDCG@10": round(scores.ndcg, 4),
                    "mrr": round(scores.mrr, 4),
                }
                for arm_name, scores in self.arm_scores.items()
            }

        if self.question_details:
            data["questions"] = self.question_details

        return data

    def as_markdown(self) -> str:
        """Render results as Markdown report with provenance headers per ADR 0006/0009."""
        lines: list[str] = [
            f"# Retrieval Evaluation: {self.golden_set_path.name}",
            "",
            self.provenance.as_markdown(),
            "",
            "## Summary",
            "",
            "| Metric | Score | Gate Target |",
            "|---|---|---|",
            f"| `recall@{GATE_K}` | **{self.main_scores.recall.get(GATE_K, 0.0):.4f}** "
            f"| >= 0.9000 (gate) |",
            f"| `recall@5` | {self.main_scores.recall.get(5, 0.0):.4f} | - |",
            f"| `nDCG@10` | {self.main_scores.ndcg:.4f} | - |",
            f"| `MRR` | {self.main_scores.mrr:.4f} | - |",
            f"| Questions Scored | {self.main_scores.questions_scored} | - |",
            f"| Unanswerable | {self.main_scores.questions_unanswerable} | >= 7 |",
            "",
        ]

        verdict = "GREEN" if self.meets_gate else "RED"
        lines.extend([f"**Gate Verdict**: {verdict}", ""])

        if self.gate_problems:
            lines.extend(["### Gate Problems", ""])
            for prob in self.gate_problems:
                lines.append(f"* {prob}")
            lines.append("")

        if self.arm_scores:
            lines.extend([
                "## Arm Comparison",
                "",
                "| Arm | recall@20 | recall@5 | nDCG@10 | MRR |",
                "|---|---|---|---|---|",
            ])
            for arm_name, scores in self.arm_scores.items():
                r20 = scores.recall.get(GATE_K, 0.0)
                r5 = scores.recall.get(5, 0.0)
                lines.append(
                    f"| {arm_name} | {r20:.4f} | {r5:.4f} | {scores.ndcg:.4f} | {scores.mrr:.4f} |"
                )
            lines.append("")

        return "\n".join(lines)

    def save(self, out_dir: Path | str = "results") -> tuple[Path, Path]:
        """Save results as JSON and Markdown files under `out_dir`."""
        target_dir = Path(out_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        commit_part = (
            self.provenance.ledgerkb_commit[:8]
            if self.provenance.ledgerkb_commit
            else "no-git"
        )
        stem = f"{self.golden_set_path.stem}-{commit_part}"
        json_path = target_dir / f"{stem}.json"
        md_path = target_dir / f"{stem}.md"

        json_path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        md_path.write_text(self.as_markdown(), encoding="utf-8")

        return json_path, md_path


def run_retrieval_eval(
    store: SqliteStore,
    cfg: Config,
    golden_set_path: Path,
    workspace_id: str,
    *,
    arms: tuple[str, ...] = ("dense", "sparse", "headings"),
    compare_arms: bool = False,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> EvalRunResult:
    """Execute retrieval evaluation on a golden set against an indexed workspace."""
    # 1. Load golden set and validate structure
    golden_set = load_golden_set(golden_set_path)
    gate_problems = golden_set.gate_problems()

    # 2. Collect provenance upfront before querying (ADR 0006 / ADR 0009)
    provenance = collect_provenance(
        store=store,
        cfg=cfg,
        workspace_id=workspace_id,
        corpus_scale=golden_set.corpus_scale,
        golden_set=golden_set_path,
    )

    # 3. Resolve quotes to chunk IDs in the store
    resolved = golden_set.resolve(store, workspace_id)

    # 4. Search and score each answerable question
    # Candidate pool size retrieved before fusion ensures sufficient candidate
    # depth across all enabled arms before ranking down to GATE_K.
    eval_k = cfg.retrieval.dense_k + cfg.retrieval.sparse_k

    question_scores: list[QuestionScores] = []
    question_details: list[dict[str, object]] = []

    for q in golden_set.answerable:
        res = hybrid_search(
            store,
            cfg,
            q.question,
            embedder=embedder if "dense" in arms else None,
            workspace_id=workspace_id,
            k=eval_k,
            arms=arms,
        )

        # Confirm all requested arms actually executed rather than silently skipping
        for arm in arms:
            if arm not in res.arms:
                raise EvaluationError(
                    f"Retrieval arm {arm!r} was requested but did not execute. "
                    f"Check that the required embedder is available."
                )

        ranked_ids = [hit.chunk_id for hit in res.hits]
        scores = score_question(q.id, ranked_ids, resolved[q.id])
        question_scores.append(scores)

        question_details.append({
            "id": q.id,
            "question": q.question,
            "shape": q.shape,
            "relevant_chunks": list(resolved[q.id]),
            "retrieved_chunks": ranked_ids[:GATE_K],
            "recall@20": scores.recall.get(GATE_K, 0.0),
            "recall@5": scores.recall.get(5, 0.0),
            "mrr": scores.reciprocal_rank,
        })

    main_scores = aggregate(
        question_scores,
        unanswerable=len(golden_set.unanswerable),
    )

    # 5. Optional arm comparison mode
    arm_scores: dict[str, RunScores] | None = None
    if compare_arms:
        arm_scores = {}
        configs_to_run: list[tuple[str, tuple[str, ...]]] = [
            ("hybrid", arms),
            ("dense", ("dense",)),
            ("sparse (BM25)", ("sparse",)),
            ("headings", ("headings",)),
        ]
        for name, arm_sub in configs_to_run:
            sub_scores: list[QuestionScores] = []
            for q in golden_set.answerable:
                res = hybrid_search(
                    store,
                    cfg,
                    q.question,
                    embedder=embedder if "dense" in arm_sub else None,
                    workspace_id=workspace_id,
                    k=eval_k,
                    arms=arm_sub,
                )
                for arm in arm_sub:
                    if arm not in res.arms:
                        raise EvaluationError(
                            f"Retrieval arm {arm!r} was requested in comparison for {name!r} "
                            f"but did not execute."
                        )
                ranked_ids = [hit.chunk_id for hit in res.hits]
                sub_scores.append(score_question(q.id, ranked_ids, resolved[q.id]))
            arm_scores[name] = aggregate(
                sub_scores, unanswerable=len(golden_set.unanswerable)
            )

    return EvalRunResult(
        provenance=provenance,
        golden_set_path=golden_set_path,
        main_scores=main_scores,
        arm_scores=arm_scores,
        gate_problems=gate_problems,
        question_details=question_details,
    )
