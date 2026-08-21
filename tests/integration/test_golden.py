"""The golden set format.

There are no questions yet, and there is deliberately none here either. What is
tested is the contract the 40 questions will be written against: that a
malformed file is refused with every problem named at once, that the counts in
L2's gate are the counts this module checks, and that relevance resolves through
quotes rather than through chunk ids.

The resolution tests matter most. A golden set keyed on chunk ids would look
fine and rot silently the next time the corpus was rebuilt, and the failure
would arrive as a bad recall number rather than as an error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ledgerkb.core.errors import GoldenSetError
from ledgerkb.evals import golden
from ledgerkb.storage.sqlite.store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]

MINUTES = "planning-committee-minutes-2026-03-11.md"
REGISTER = "risk-register-2026-q1.xlsx"


def write(tmp_path: Path, body: str, *, scale: int = 11) -> Path:
    path = tmp_path / "golden.toml"
    path.write_text(f"corpus_scale = {scale}\n\n{body}", encoding="utf-8")
    return path


# The nested-table form rather than an inline table, because TOML requires an
# inline table to fit on one line and a real quote plus a real filename does not.
# Both forms parse to the same thing; this is the one the how-to shows.
ONE_GOOD_QUESTION = """
[[question]]
id = "attercliffe-allocation"
question = "What capital allocation was approved for Attercliffe in 2026/27?"
answerable = true
shape = "figure-across-quarters"

[[question.relevant]]
document = "planning-committee-minutes-2026-03-11.md"
quote = "capital allocation of GBP 2.4m"
"""


class TestTheGateNumbersComeFromTheRoadmap:
    def test_the_constants_match_what_stages_toml_asks_for(self) -> None:
        """Otherwise the harness could pass a file the roadmap would fail.

        The criterion is prose, so this reads the numbers out of it rather than
        restating them. If somebody rewords the criterion, this test says so.
        """
        text = (ROOT / "docs" / "stages.toml").read_text(encoding="utf-8")
        criterion = next(
            line for line in text.splitlines() if "golden set of" in line
        )
        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", criterion)]
        assert golden.GATE_QUESTIONS in numbers
        assert golden.GATE_UNANSWERABLE in numbers


class TestLoading:
    def test_a_well_formed_file_loads(self, tmp_path: Path) -> None:
        gs = golden.load(write(tmp_path, ONE_GOOD_QUESTION))
        assert gs.corpus_scale == 11
        assert len(gs.questions) == 1
        assert gs.questions[0].relevant[0].document == MINUTES

    def test_the_corpus_scale_is_required(self, tmp_path: Path) -> None:
        """A golden set is written against one corpus, and the results header
        records which. A file that does not say is not scoreable."""
        path = tmp_path / "golden.toml"
        path.write_text(ONE_GOOD_QUESTION, encoding="utf-8")
        with pytest.raises(GoldenSetError, match="corpus_scale"):
            golden.load(path)

    def test_broken_toml_says_so(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.toml"
        path.write_text("corpus_scale = = 11", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="not valid TOML"):
            golden.load(path)

    def test_a_missing_file_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(GoldenSetError, match="cannot read"):
            golden.load(tmp_path / "absent.toml")

    def test_every_problem_is_reported_at_once(self, tmp_path: Path) -> None:
        """Fixing 40 entries one exception per run is miserable, and the second
        problem is usually the one that explains the first."""
        body = """
[[question]]
id = "no-text"
answerable = true

[[question]]
id = "no-answerable-flag"
question = "Who owns the footbridge decision?"

[[question]]
id = "bad-shape"
question = "What was the Q3 figure?"
answerable = false
shape = "invented"
"""
        with pytest.raises(GoldenSetError) as exc:
            golden.load(write(tmp_path, body))
        message = str(exc.value)
        assert "no-text" in message
        assert "no-answerable-flag" in message
        assert "bad-shape" in message

    def test_duplicate_ids_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(GoldenSetError, match="duplicate id"):
            golden.load(write(tmp_path, ONE_GOOD_QUESTION + ONE_GOOD_QUESTION))


class TestAnswerableIsStatedNotInferred:
    def test_an_answerable_question_needs_a_relevant_span(self, tmp_path: Path) -> None:
        body = """
[[question]]
id = "unfinished"
question = "What was the allocation?"
answerable = true
"""
        with pytest.raises(GoldenSetError, match="at least one relevant span"):
            golden.load(write(tmp_path, body))

    def test_an_unanswerable_question_must_have_none(self, tmp_path: Path) -> None:
        body = """
[[question]]
id = "contradictory"
question = "What was the allocation?"
answerable = false
relevant = [{ document = "a.md", quote = "something" }]
"""
        with pytest.raises(GoldenSetError, match="must have no relevant spans"):
            golden.load(write(tmp_path, body))

    def test_the_flag_is_required_rather_than_derived_from_the_spans(
        self, tmp_path: Path
    ) -> None:
        """If it were inferred, a question somebody forgot to finish would
        silently become one of the seven unanswerable ones, and the gate would
        be met by an oversight."""
        body = """
[[question]]
id = "half-written"
question = "What was the allocation?"
"""
        with pytest.raises(GoldenSetError, match="answerable is required"):
            golden.load(write(tmp_path, body))


class TestGateProblems:
    def test_a_short_file_is_reported_not_refused(self, tmp_path: Path) -> None:
        """A golden set with 1 question in it is what writing one looks like."""
        gs = golden.load(write(tmp_path, ONE_GOOD_QUESTION))
        problems = gs.gate_problems()
        assert any(str(golden.GATE_QUESTIONS) in p for p in problems)
        assert any(str(golden.GATE_UNANSWERABLE) in p for p in problems)

    def test_recall_is_scored_on_the_answerable_ones(self, tmp_path: Path) -> None:
        body = (
            ONE_GOOD_QUESTION
            + """
[[question]]
id = "no-such-programme"
question = "What was allocated to the Hillsborough Skyway Programme?"
answerable = false
shape = "unanswerable"
"""
        )
        gs = golden.load(write(tmp_path, body))
        assert [q.id for q in gs.answerable] == ["attercliffe-allocation"]
        assert [q.id for q in gs.unanswerable] == ["no-such-programme"]


class TestResolvingQuotesToChunks:
    """Relevance is a quote because chunk ids are minted at ingest and change
    every time the corpus is rebuilt."""

    @pytest.fixture
    def corpus_store(self, store: SqliteStore, workspace, source):
        """Two documents with their own versions.

        Built here rather than through the shared `chunk_factory`, which pins
        every chunk to one version and so cannot express a corpus of more than
        one document.
        """
        from ledgerkb.core.models import Chunk, Document, DocumentVersion, new_id

        def add(external_id: str, texts: list[str]) -> None:
            doc_id = store.upsert_document(
                Document(
                    workspace_id=workspace.id,
                    source_id=source.id,
                    external_id=external_id,
                    title=external_id,
                )
            )
            version = DocumentVersion(
                document_id=doc_id,
                version_no=1,
                content_hash=external_id.ljust(64, "x")[:64],
                text_hash=external_id.ljust(64, "y")[:64],
            )
            store.add_version(version)
            store.add_chunks(
                [
                    Chunk(
                        id=new_id(),
                        workspace_id=workspace.id,
                        version_id=version.id,
                        ordinal=i,
                        char_start=0,
                        char_end=len(text),
                        text=text,
                    )
                    for i, text in enumerate(texts)
                ]
            )

        add(
            MINUTES,
            [
                "The Committee RESOLVED to approve the capital allocation of GBP 2.4m.",
                "Item 5 concerned the footbridge options appraisal.",
            ],
        )
        add(REGISTER, ["Risk owner for the footbridge works is the Director."])
        return store

    def test_a_quote_resolves_to_the_chunk_that_contains_it(
        self, tmp_path: Path, corpus_store: SqliteStore, workspace
    ) -> None:
        gs = golden.load(write(tmp_path, ONE_GOOD_QUESTION))
        resolved = gs.resolve(corpus_store, workspace.id)
        chunk_ids = resolved["attercliffe-allocation"]
        assert len(chunk_ids) == 1
        found = corpus_store.get_chunk(next(iter(chunk_ids)))
        assert found is not None
        assert "GBP 2.4m" in found.text

    def test_an_unanswerable_question_resolves_to_nothing(
        self, tmp_path: Path, corpus_store: SqliteStore, workspace
    ) -> None:
        body = """
[[question]]
id = "no-such-programme"
question = "What was allocated to the Hillsborough Skyway Programme?"
answerable = false
"""
        gs = golden.load(write(tmp_path, body))
        assert gs.resolve(corpus_store, workspace.id) == {"no-such-programme": frozenset()}

    def test_a_quote_no_chunk_contains_is_an_error_not_a_miss(
        self, tmp_path: Path, corpus_store: SqliteStore, workspace
    ) -> None:
        """The failure this whole design exists to prevent.

        Scored as a miss it is indistinguishable from a retriever that failed,
        so a wrong question would be reported as a property of retrieval.
        """
        body = f"""
[[question]]
id = "wrong-quote"
question = "What was the allocation?"
answerable = true
relevant = [{{ document = "{MINUTES}", quote = "capital allocation of GBP 9.9m" }}]
"""
        with pytest.raises(GoldenSetError, match="no chunk of"):
            golden.load(write(tmp_path, body)).resolve(corpus_store, workspace.id)

    def test_a_document_the_corpus_does_not_have_is_an_error(
        self, tmp_path: Path, corpus_store: SqliteStore, workspace
    ) -> None:
        body = """
[[question]]
id = "wrong-document"
question = "What was the allocation?"
answerable = true
relevant = [{ document = "minutes-that-do-not-exist.md", quote = "anything" }]
"""
        with pytest.raises(GoldenSetError, match="no document named"):
            golden.load(write(tmp_path, body)).resolve(corpus_store, workspace.id)

    def test_a_question_can_need_two_documents(
        self, tmp_path: Path, corpus_store: SqliteStore, workspace
    ) -> None:
        """One of the shapes the how-to calls out: the contractor is in the
        report and the completion date is in the slides."""
        body = f"""
[[question]]
id = "spans-two"
question = "Who owns the footbridge works and where was it discussed?"
answerable = true
shape = "spans-two-documents"
relevant = [
  {{ document = "{MINUTES}", quote = "footbridge options appraisal" }},
  {{ document = "{REGISTER}", quote = "Risk owner for the footbridge works" }},
]
"""
        gs = golden.load(write(tmp_path, body))
        assert len(gs.resolve(corpus_store, workspace.id)["spans-two"]) == 2
