"""Ports — the extension surface.

Every capability starts life as a Protocol here, before any implementation
exists. This is also the escape hatch described in the handoff: you may supply
your own ``Store``, ``Chunker``, ``Reranker``, ``ChatModel`` or ``Parser`` and
get full power through code you own. What is deliberately *not* available is a
flag that silently disables a guarantee.

Protocols are ``runtime_checkable`` so ``lkb doctor`` can report which port a
substituted implementation satisfies.

Note on typing: ``structured`` uses a ``TypeVar`` rather than PEP 695 syntax
because the support matrix includes Python 3.11.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

from ledgerkb.core.models import (
    Assertion,
    Base,
    ChangeEvent,
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    Evidence,
    Hit,
    Id,
    IngestRun,
    InvalidationReason,
    MergeMethod,
    RunRecord,
)

T = TypeVar("T", bound=BaseModel)


# --- adapter contract types --------------------------------------------------


class Capabilities(Base):
    """What a provider can actually do, so callers degrade instead of crashing."""

    structured_output: bool = False
    """Native JSON-schema-constrained output."""
    tools: bool = False
    """Irrelevant for extraction, which always passes zero tools by design."""
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_temperature: bool = True
    cost_per_1m_input_usd: float | None = None
    cost_per_1m_output_usd: float | None = None


class ParseHint(Base):
    """What the caller already knows, so the parser need not re-derive it."""

    mime: str | None = None
    filename: str | None = None
    uri: str | None = None
    doc_type: str | None = None
    density_probe: float | None = None
    """Text-density heuristic, 0..1. Drives the tiered parser cascade."""


class Heading(Base):
    """A heading and where it starts.

    ``level`` is what lets the chunker build a ``heading_path``, so a citation
    can read "Planning Committee Minutes > Item 4 > Decision" rather than
    naming a page number and leaving the reader to hunt.
    """

    char_start: int = Field(ge=0)
    level: int = Field(ge=1, le=6)
    text: str


class ParsedDocument(Base):
    """Parser output. ``text`` is the single source of truth for every offset."""

    text: str
    parser: str
    parse_quality: float = Field(ge=0.0, le=1.0)
    mime: str | None = None
    page_count: int | None = None
    page_offsets: list[int] = Field(default_factory=list)
    """char offset at which each page starts — makes page citation exact."""
    headings: list[Heading] = Field(default_factory=list)
    """In document order."""
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: date | None = None
    warnings: list[str] = Field(default_factory=list)


# --- model providers ---------------------------------------------------------


@runtime_checkable
class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> str: ...

    def structured(self, messages: list[dict[str, Any]], schema: type[T], **kw: Any) -> T: ...

    def capabilities(self) -> Capabilities: ...


@runtime_checkable
class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(self, query: str, docs: Sequence[str], top_k: int) -> list[tuple[int, float]]:
        """Return ``(original_index, score)`` pairs, best first."""
        ...


# --- ingest ------------------------------------------------------------------


@runtime_checkable
class Reader(Protocol):
    """Fetches bytes from somewhere. The only component that touches the network."""

    kind: str

    def list_documents(self, config: dict[str, Any], state: dict[str, Any]) -> Iterable[Document]:
        ...

    def fetch(self, doc: Document) -> bytes: ...


@runtime_checkable
class Parser(Protocol):
    name: str

    def can_parse(self, mime: str, path: str) -> bool: ...

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument: ...


@runtime_checkable
class Chunker(Protocol):
    """Must preserve offsets: every chunk slices back byte-identical from ``text``."""

    def chunk(self, doc: ParsedDocument, workspace_id: str, version_id: str) -> list[Chunk]: ...


# --- storage -----------------------------------------------------------------


@runtime_checkable
class Store(Protocol):
    """The persistence port. SQLite is the default; Postgres is the scale backend."""

    # documents
    def upsert_document(self, doc: Document) -> str: ...
    def get_document(self, id: str) -> Document | None: ...
    def add_version(self, v: DocumentVersion) -> str: ...
    def get_version(self, id: str) -> DocumentVersion | None: ...
    def find_version_by_hash(self, document_id: str, content_hash: str) -> DocumentVersion | None:
        """The content-hash check that makes refresh cheap."""
        ...

    # chunks and retrieval
    def add_chunks(self, chunks: Iterable[Chunk]) -> None: ...
    def get_chunk(self, id: str) -> Chunk | None: ...
    def search_dense(self, vec: list[float], k: int, **f: Any) -> list[Hit]: ...
    def search_sparse(self, query: str, k: int, **f: Any) -> list[Hit]: ...

    # entities
    def upsert_entity(self, e: Entity) -> str: ...
    def get_entity(self, id: str) -> Entity | None: ...
    def find_entities(self, workspace_id: str, normalised_name: str) -> list[Entity]: ...
    def merge_entities(
        self, winner_id: str, loser_id: str, method: MergeMethod, decided_by: str, **kw: Any
    ) -> None:
        """Soft merge — sets ``merged_into`` and logs it. Always reversible."""
        ...

    def unmerge_entity(self, loser_id: str, decided_by: str) -> None: ...

    # the ledger
    def add_assertion(self, a: Assertion, ev: list[Evidence]) -> str: ...
    def get_assertion(self, id: str) -> Assertion | None: ...
    def invalidate(self, id: str, by: str, reason: InvalidationReason) -> None:
        """The sole mutation on the ledger. Never a delete."""
        ...

    def active_assertions(self, workspace_id: str, **f: Any) -> list[Assertion]: ...
    def assertions_as_of(self, workspace_id: str, when: datetime, **f: Any) -> list[Assertion]:
        """Bitemporal query: what did we believe on this date?"""
        ...

    # runs and change events
    def start_run(self, run: IngestRun) -> str: ...
    def finish_run(self, run: IngestRun) -> None: ...
    def add_change_event(self, ev: ChangeEvent) -> None: ...
    def changes_for_run(self, run_id: str) -> list[ChangeEvent]: ...
    def record(self, r: RunRecord) -> None: ...

    # lifecycle
    def migrate(self) -> int:
        """Apply pending migrations. Returns the resulting schema version."""
        ...

    def schema_version(self) -> int: ...
    def close(self) -> None: ...


__all__ = [
    "Capabilities",
    "ChatModel",
    "Chunker",
    "Embedder",
    "Heading",
    "Id",
    "ParseHint",
    "ParsedDocument",
    "Parser",
    "Reader",
    "Reranker",
    "Store",
]
