"""The golden set: what a question is, and what counts as the right answer.

L2's gate asks for 40 questions, at least 7 of them unanswerable, written from
the documents before retrieval is run even once. Nobody can write those 40 until
there is a format to write them in, so this is the format, and it deliberately
contains no questions.

**Relevance is a quote, not a chunk id.** Chunk ids are UUIDs minted at ingest,
so they change every time the corpus is rebuilt, and a golden set keyed on them
would rot the first time anybody re-ran the pipeline. A question therefore names
the document by its filename and the answer by a span of its text, and
``resolve`` turns that into chunk ids against a live store. That is the same
idiom the rest of the project uses for citations: a quote either occurs in the
text or it does not, and the store can be asked.

It also gives the golden set a self-check the ordering rule cannot provide on its
own. A quote that no chunk contains means the question is wrong about the corpus,
and ``resolve`` refuses rather than quietly scoring the question zero. A silent
zero is indistinguishable from a retrieval failure, which is the one confusion a
measurement of retrieval cannot afford.

Structural rules are enforced on load, because a malformed file is a mistake.
Gate rules, the counts in ``docs/stages.toml``, are reported by
``gate_problems`` rather than raised, because a half-written golden set is a
normal thing to have on disk while writing one.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ledgerkb.core.errors import GoldenSetError
from ledgerkb.core.models import Document
from ledgerkb.storage.sqlite.store import SqliteStore

# The count and the minimum in L2's gate. They live in `docs/stages.toml`, which
# is the source of truth; these are here so the harness can check a file without
# parsing the roadmap, and a test asserts the two agree.
GATE_QUESTIONS = 40
GATE_UNANSWERABLE = 7

# The shapes `docs/how-to/build-the-measurement-corpus.md` says discriminate.
# Closed rather than free text: a typo would otherwise invent a category of one
# and nobody would see it. Adding a shape is a one-line reviewable change.
SHAPES = frozenset(
    {
        "figure-across-quarters",
        "single-format",
        "spans-two-documents",
        "unanswerable",
    }
)


@dataclass(frozen=True)
class RelevantSpan:
    """A document and a span of its text that answers the question.

    ``quote`` must occur verbatim in the document's chunk text. It does not have
    to be a whole chunk, and it should be the shortest span that actually carries
    the answer, because a long quote silently becomes a test of the chunker's
    boundaries rather than of retrieval.
    """

    document: str
    quote: str


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    question: str
    answerable: bool
    relevant: tuple[RelevantSpan, ...] = ()
    shape: str | None = None
    note: str = ""


@dataclass(frozen=True)
class GoldenSet:
    path: Path
    corpus_scale: int
    questions: tuple[GoldenQuestion, ...] = field(default_factory=tuple)

    @property
    def answerable(self) -> tuple[GoldenQuestion, ...]:
        """The questions recall is scored on. The gate says so explicitly."""
        return tuple(q for q in self.questions if q.answerable)

    @property
    def unanswerable(self) -> tuple[GoldenQuestion, ...]:
        return tuple(q for q in self.questions if not q.answerable)

    def gate_problems(self) -> list[str]:
        """What stops this file satisfying L2's first criterion, in plain words.

        Reported rather than raised: a file with 12 questions in it is what
        writing a golden set looks like on the way to 40.
        """
        problems = []
        if len(self.questions) != GATE_QUESTIONS:
            problems.append(
                f"the gate asks for {GATE_QUESTIONS} questions, this file has "
                f"{len(self.questions)}"
            )
        if len(self.unanswerable) < GATE_UNANSWERABLE:
            problems.append(
                f"the gate asks for at least {GATE_UNANSWERABLE} unanswerable "
                f"questions, this file has {len(self.unanswerable)}"
            )
        return problems

    def resolve(self, store: SqliteStore, workspace_id: str) -> dict[str, frozenset[str]]:
        """Chunk ids per question id, found by locating each quote in the store.

        Raises rather than returning an empty set for a quote nothing contains.
        An unfindable quote is a claim about the corpus that the corpus does not
        support, and scoring it as a miss would report a wrong question as a
        retrieval failure.
        """
        by_name = _documents_by_name(store, workspace_id)
        out: dict[str, frozenset[str]] = {}

        for question in self.questions:
            found: set[str] = set()
            for span in question.relevant:
                document = by_name.get(span.document)
                if document is None:
                    raise GoldenSetError(
                        f"{question.id}: no document named {span.document!r} in this "
                        f"workspace. The golden set and the corpus disagree."
                    )
                matches = _chunks_containing(store, document, span.quote)
                if not matches:
                    raise GoldenSetError(
                        f"{question.id}: no chunk of {span.document} contains the quote "
                        f"{_shorten(span.quote)!r}. Either the quote is wrong or the "
                        f"corpus has changed since the question was written."
                    )
                found.update(matches)
            out[question.id] = frozenset(found)
        return out


def load(path: Path) -> GoldenSet:
    """Read and structurally validate a golden set file.

    Every structural problem in the file is reported together, because fixing
    them one exception at a time is miserable when a file holds 40 entries.
    """
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GoldenSetError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GoldenSetError(f"{path} is not valid TOML: {exc}") from exc

    scale = raw.get("corpus_scale")
    if not isinstance(scale, int):
        raise GoldenSetError(
            f"{path}: corpus_scale is required and must be an integer. A golden set "
            f"is written against one corpus, and the results header records which."
        )

    entries = raw.get("question", [])
    if not isinstance(entries, list):
        raise GoldenSetError(f"{path}: 'question' must be an array of tables")

    questions: list[GoldenQuestion] = []
    problems: list[str] = []
    seen: set[str] = set()

    for index, entry in enumerate(entries):
        where = f"question {index + 1}"
        parsed = _parse_question(entry, where, problems)
        if parsed is None:
            continue
        if parsed.id in seen:
            problems.append(f"{where}: duplicate id {parsed.id!r}")
            continue
        seen.add(parsed.id)
        questions.append(parsed)

    if problems:
        joined = "\n  ".join(problems)
        raise GoldenSetError(f"{path} is malformed:\n  {joined}")

    return GoldenSet(path=path, corpus_scale=scale, questions=tuple(questions))


def _parse_question(
    entry: object, where: str, problems: list[str]
) -> GoldenQuestion | None:
    if not isinstance(entry, dict):
        problems.append(f"{where}: expected a table")
        return None

    ident = entry.get("id")
    if not isinstance(ident, str) or not ident.strip():
        problems.append(f"{where}: id is required and must be a non-empty string")
        return None
    where = f"{where} ({ident})"

    text = entry.get("question")
    if not isinstance(text, str) or not text.strip():
        problems.append(f"{where}: question text is required")
        return None

    answerable = entry.get("answerable")
    if not isinstance(answerable, bool):
        problems.append(
            f"{where}: answerable is required and must be true or false. It is not "
            f"inferred from whether relevant spans were given, because a question "
            f"somebody forgot to finish would then silently become unanswerable."
        )
        return None

    shape = entry.get("shape")
    if shape is not None and shape not in SHAPES:
        problems.append(
            f"{where}: unknown shape {shape!r}. Known shapes: {', '.join(sorted(SHAPES))}"
        )
        return None

    spans = _parse_spans(entry.get("relevant", []), where, problems)
    if spans is None:
        return None

    if answerable and not spans:
        problems.append(f"{where}: answerable, so it needs at least one relevant span")
        return None
    if not answerable and spans:
        problems.append(
            f"{where}: unanswerable, so it must have no relevant spans. If the corpus "
            f"does answer it, the question is answerable."
        )
        return None

    return GoldenQuestion(
        id=ident,
        question=text,
        answerable=answerable,
        relevant=spans,
        shape=shape,
        note=str(entry.get("note", "")),
    )


def _parse_spans(
    raw: object, where: str, problems: list[str]
) -> tuple[RelevantSpan, ...] | None:
    if not isinstance(raw, list):
        problems.append(f"{where}: relevant must be an array")
        return None

    spans: list[RelevantSpan] = []
    for item in raw:
        if not isinstance(item, dict):
            problems.append(f"{where}: each relevant entry must be a table")
            return None
        document = item.get("document")
        quote = item.get("quote")
        if not isinstance(document, str) or not document.strip():
            problems.append(f"{where}: a relevant entry is missing 'document'")
            return None
        if not isinstance(quote, str) or not quote.strip():
            problems.append(f"{where}: a relevant entry is missing 'quote'")
            return None
        spans.append(RelevantSpan(document=document, quote=quote))
    return tuple(spans)


def _documents_by_name(store: SqliteStore, workspace_id: str) -> dict[str, Document]:
    """Every document in the workspace, keyed by filename, read once.

    The limit is well past the measurement corpus rather than the store default,
    because a golden set that silently could not see the last few documents
    would fail with a confusing message about a missing file.
    """
    documents = store.list_documents(workspace_id, limit=1_000_000)
    return {d.external_id: d for d in documents}


def _chunks_containing(store: SqliteStore, document: Document, quote: str) -> set[str]:
    version = store.latest_version_for(document.id)
    if version is None:
        return set()
    return {c.id for c in store.chunks_for_version(version.id) if quote in c.text}


def _shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


__all__ = [
    "GATE_QUESTIONS",
    "GATE_UNANSWERABLE",
    "SHAPES",
    "GoldenQuestion",
    "GoldenSet",
    "RelevantSpan",
    "load",
]
