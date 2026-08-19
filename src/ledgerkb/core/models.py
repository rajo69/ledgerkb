"""Core domain models.

Pure: stdlib + pydantic only. No I/O, no provider SDKs. CI enforces this.

Two invariants are encoded as validators rather than conventions, because
"discouraged" is not the same as "impossible":

1. An ``Assertion`` cannot be constructed without at least one ``Evidence``.
2. ``modality == "inferred"`` requires ``confidence < 1.0``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- shared vocabulary -------------------------------------------------------

SourceKind = Literal["gdrive", "link", "upload"]
DocStatus = Literal["active", "unavailable", "failed"]
Modality = Literal["explicit", "inferred"]
AssertionStatus = Literal["active", "invalidated", "disputed"]
InvalidationReason = Literal["superseded", "contradicted", "corrected", "source_withdrawn"]
MergeMethod = Literal["exact", "alias", "trigram", "embedding", "llm", "human"]
ChangeKind = Literal[
    "new",
    "confirmed",
    "outdated",
    "contradicted",
    "action_completed",
    "owner_changed",
    "question_raised",
]
RetrievalGrade = Literal["correct", "ambiguous", "incorrect"]
IngestTrigger = Literal["manual", "scheduled", "initial"]

Id = Annotated[str, Field(min_length=1)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def new_id() -> str:
    """Opaque identifier. UUID4 as text, so SQLite and Postgres agree."""
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(BaseModel):
    """Strict by default: unknown fields are a bug, not something to swallow."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --- workspace, sources, documents -------------------------------------------


class Workspace(Base):
    id: Id = Field(default_factory=new_id)
    name: str
    profile: str = "default"
    created_at: datetime = Field(default_factory=utcnow)


class Source(Base):
    id: Id = Field(default_factory=new_id)
    workspace_id: Id
    kind: SourceKind
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    connector_state: dict[str, Any] = Field(default_factory=dict)
    last_refreshed_at: datetime | None = None
    status: str = "ready"
    created_at: datetime = Field(default_factory=utcnow)


class Document(Base):
    id: Id = Field(default_factory=new_id)
    workspace_id: Id
    source_id: Id
    external_id: str
    """Drive file id, URL, or path within an uploaded archive."""
    uri: str | None = None
    title: str | None = None
    doc_type: str | None = None
    meeting_or_project: str | None = None
    published_at: date | None = None
    authors: list[str] = Field(default_factory=list)
    status: DocStatus = "active"
    current_version_id: Id | None = None


class DocumentVersion(Base):
    """Immutable. A new content hash is a new row, never an update."""

    id: Id = Field(default_factory=new_id)
    document_id: Id
    version_no: int = Field(ge=1)
    content_hash: str
    """sha256 of the raw bytes."""
    text_hash: str
    """sha256 of the extracted text."""
    blob_uri: str | None = None
    mime: str | None = None
    bytes: int | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    parser: str | None = None
    parse_quality: Confidence | None = None
    ingested_at: datetime = Field(default_factory=utcnow)
    superseded_by: Id | None = None

    text: str | None = None
    """The canonical sanitised text. Every chunk offset indexes into this."""
    parse_warnings: list[str] = Field(default_factory=list)
    """Named degradations — an unreadable page, a low density probe. Never silent."""
    metadata_misses: list[str] = Field(default_factory=list)
    """Required fields that could not be found. Reported, never silently null."""


# --- chunks ------------------------------------------------------------------


class Chunk(Base):
    id: Id = Field(default_factory=new_id)
    workspace_id: Id
    version_id: Id
    ordinal: int = Field(ge=0)
    heading_path: list[str] = Field(default_factory=list)
    page_from: int | None = None
    page_to: int | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str
    """The verbatim source span. NEVER rewritten — quote verification depends on it."""
    context_header: str | None = None
    """A 50-100 token situating summary, concatenated only for indexing."""
    token_count: int | None = Field(default=None, ge=0)
    embedding: list[float] | None = None

    @property
    def embed_text(self) -> str:
        """What actually gets indexed, dense and sparse alike.

        Both indexes derive from this one property so they cannot disagree.
        """
        return f"{self.context_header or ''}\n\n{self.text}"

    @model_validator(mode="after")
    def _span_is_ordered(self) -> Chunk:
        if self.char_end < self.char_start:
            raise ValueError(
                f"chunk span is inverted: char_start={self.char_start} > char_end={self.char_end}"
            )
        return self


# --- entities ----------------------------------------------------------------


class Entity(Base):
    id: Id = Field(default_factory=new_id)
    workspace_id: Id
    type: str
    canonical_name: str
    normalised_name: str
    """Lowercased, punctuation-stripped. Used for blocking during resolution."""
    aliases: list[str] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    first_seen: date | None = None
    last_seen: date | None = None
    merged_into: Id | None = None
    """Soft merge. Reversible — over-merging is the failure that matters."""
    status: str = "active"


class EntityMerge(Base):
    id: Id = Field(default_factory=new_id)
    winner_id: Id
    loser_id: Id
    method: MergeMethod
    score: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    decided_by: str
    decided_at: datetime = Field(default_factory=utcnow)
    reverted_at: datetime | None = None


# --- the ledger --------------------------------------------------------------


class Evidence(Base):
    """A verbatim span in a chunk that supports an assertion."""

    chunk_id: Id
    quote: str = Field(min_length=1)
    """Verbatim. Must occur in the referenced chunk's text — checked mechanically."""
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class Assertion(Base):
    """One evidence-bearing claim. The unit the whole system is built from.

    Append-only: ``invalid_at`` is the sole mutation and it is set once.
    """

    id: Id = Field(default_factory=new_id)
    workspace_id: Id

    # the claim
    subject_id: Id | None = None
    predicate: str
    object_id: Id | None = None
    object_literal: str | None = None
    """For value claims: "£2.4m", "Q1 2027"."""
    claim_text: str = Field(min_length=1)

    # epistemics
    modality: Modality
    confidence: Confidence = 1.0

    # evidence — an assertion cannot exist without it
    evidence: list[Evidence] = Field(min_length=1)

    # bitemporal: valid_* is world time, asserted_at/invalid_at is system time
    valid_from: date | None = None
    valid_to: date | None = None
    asserted_at: datetime = Field(default_factory=utcnow)
    invalid_at: datetime | None = None
    invalidated_by: Id | None = None
    invalidation_reason: InvalidationReason | None = None

    status: AssertionStatus = "active"
    stale_after: date | None = None

    # governance
    verified_by: str | None = None
    """'human:rajarshi' | 'agent/qwen3-235b-a22b'."""
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def _inferred_cannot_be_certain(self) -> Assertion:
        if self.modality == "inferred" and self.confidence >= 1.0:
            raise ValueError(
                "modality='inferred' requires confidence < 1.0; "
                f"got {self.confidence}. Inference is never certain."
            )
        return self

    @model_validator(mode="after")
    def _invalidation_is_coherent(self) -> Assertion:
        if self.invalid_at is not None and self.invalidation_reason is None:
            raise ValueError("invalid_at requires an invalidation_reason")
        if self.invalidation_reason is not None and self.invalid_at is None:
            raise ValueError("invalidation_reason requires invalid_at")
        return self

    @model_validator(mode="after")
    def _world_time_is_ordered(self) -> Assertion:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError(f"valid_to {self.valid_to} precedes valid_from {self.valid_from}")
        return self


# --- change tracking ---------------------------------------------------------


class IngestRun(Base):
    id: Id = Field(default_factory=new_id)
    workspace_id: Id
    source_id: Id | None = None
    trigger: IngestTrigger
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    docs_seen: int = 0
    docs_changed: int = 0
    docs_new: int = 0
    docs_gone: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)


class ChangeEvent(Base):
    id: Id = Field(default_factory=new_id)
    run_id: Id
    kind: ChangeKind
    assertion_id: Id | None = None
    prior_assertion_id: Id | None = None
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


# --- retrieval and answering -------------------------------------------------


class Hit(Base):
    """One retrieval result. ``score`` is comparable only within a single method."""

    chunk_id: Id
    score: float
    text: str
    method: Literal["dense", "sparse", "rrf", "rerank", "graph"]
    ranks: dict[str, int] = Field(default_factory=dict)
    """Where each retriever placed this candidate, by retriever name.

    Carried through fusion so an explanation can show why something ranked
    where it did without re-running either half.
    """
    document_id: Id | None = None
    version_id: Id | None = None
    heading_path: list[str] = Field(default_factory=list)
    page_from: int | None = None


class Claim(Base):
    """One sentence of an answer, bound to the span that supports it."""

    text: str
    chunk_id: Id
    quote: str
    modality: Modality = "explicit"
    verified: bool = False
    """Set only by deterministic quote verification. Never by a model."""

    def demoted(self) -> Claim:
        """Return this claim marked unsupported. Verification failure is not fatal."""
        return self.model_copy(update={"verified": False, "modality": "inferred"})


class Answer(Base):
    query: str
    claims: list[Claim] = Field(default_factory=list)
    grade: RetrievalGrade | None = None
    abstained: bool = False
    gaps: list[str] = Field(default_factory=list)
    """Named coverage gaps. Populated when the system abstains."""

    @model_validator(mode="after")
    def _abstention_names_its_gaps(self) -> Answer:
        if self.abstained and not self.gaps:
            raise ValueError("an abstention must name its gaps — silence is not an answer")
        return self


# --- observability -----------------------------------------------------------


class RunRecord(Base):
    id: Id = Field(default_factory=new_id)
    run_id: Id | None = None
    stage: str
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    duration_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "Answer",
    "Assertion",
    "AssertionStatus",
    "Base",
    "ChangeEvent",
    "ChangeKind",
    "Chunk",
    "Claim",
    "Confidence",
    "DocStatus",
    "Document",
    "DocumentVersion",
    "Entity",
    "EntityMerge",
    "Evidence",
    "Hit",
    "Id",
    "IngestRun",
    "IngestTrigger",
    "InvalidationReason",
    "MergeMethod",
    "Modality",
    "RetrievalGrade",
    "RunRecord",
    "Source",
    "SourceKind",
    "Workspace",
    "new_id",
    "utcnow",
]
