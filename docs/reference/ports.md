# Ports

Seven Protocols in `src/ledgerkb/core/ports.py`. They are the whole extension
surface: supply your own implementation and nothing downstream notices, because
nothing downstream asks where an object came from.

These are `typing.Protocol`, so there is nothing to subclass and nothing to
register. A class with the right methods satisfies the port.

## Providers

```python
class ChatModel(Protocol):
    name: str
    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> str: ...
    def structured(self, messages: list[dict[str, Any]], schema: type[T], **kw: Any) -> T: ...
    def capabilities(self) -> Capabilities: ...

class Embedder(Protocol):
    name: str
    dimensions: int
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

class Reranker(Protocol):
    def rerank(self, query: str, docs: Sequence[str], top_k: int) -> list[tuple[int, float]]: ...
```

`Embedder.dimensions` is not decoration. It is checked against
`embeddings.dimensions` in config at construction, so a mismatch is refused
before a corpus is embedded rather than surfacing as a shape error on the first
search.

`Reranker.rerank` returns `(index, score)` pairs into the input list rather than
the documents themselves, so a caller keeps its own objects and their metadata.

**`Capabilities`** is what a provider can actually do, so callers degrade instead
of crashing: `structured_output`, `tools`, `max_input_tokens`,
`max_output_tokens`, `supports_temperature`, and per-million-token costs. `tools`
is recorded for completeness and is irrelevant to extraction, which passes zero
tools by design.

Implementations: `providers/openai_compat.py`, `providers/local.py` and
`providers/fake.py`.

## Ingest

```python
class Reader(Protocol):
    kind: str
    def list_documents(self, config, state) -> Iterable[Document]: ...
    def fetch(self, doc: Document) -> bytes: ...

class Parser(Protocol):
    name: str
    def can_parse(self, mime: str, path: str) -> bool: ...
    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument: ...

class Chunker(Protocol):
    name: str
    def chunk(self, doc: ParsedDocument, workspace_id: str, version_id: str) -> list[Chunk]: ...
```

`Reader.list_documents` takes and returns connector state (page tokens, etags,
cursors), which is what makes an incremental refresh possible without the reader
owning a database.

**`ParseHint`** is what the caller already knows so the parser need not re-derive
it: `mime`, `filename`, `uri`, `doc_type`, and `density_probe`, a text-density
heuristic that drives the tiered parser cascade.

**`ParsedDocument`** is parser output, and its `text` is the single source of
truth for every offset downstream.

| Field | Meaning |
|---|---|
| `text` | The extracted document text |
| `parser`, `parse_quality` | Which parser ran, and how confident it is |
| `page_offsets` | Character offset at which each page starts, which makes a page citation exact |
| `headings` | `Heading(char_start, level, text)` in document order |
| `title`, `authors`, `published_at` | Metadata the parser could recover natively |
| `warnings` | Everything that went wrong but did not stop the parse |

`Heading.level` is what lets the chunker build a `heading_path`, so a citation
can read "Planning Committee Minutes > Item 4 > Decision" rather than naming a
page and leaving the reader to hunt.

A `Chunker` implementation must preserve the offset invariant: every chunk's text
must be a slice of `ParsedDocument.text` at its recorded offsets. That is not
enforced by the type system, so it is enforced by a property test.

## Storage

```python
class Store(Protocol):
    def upsert_document(self, doc: Document) -> str: ...
    def add_version(self, v: DocumentVersion) -> str: ...
    def find_version_by_hash(self, document_id: str, content_hash: str) -> DocumentVersion | None: ...
    def add_chunks(self, chunks: Iterable[Chunk]) -> None: ...
    def search_dense(self, vec: list[float], k: int, **f: Any) -> list[Hit]: ...
    def search_sparse(self, query: str, k: int, **f: Any) -> list[Hit]: ...
    def add_assertion(self, a: Assertion, ev: list[Evidence]) -> str: ...
    def invalidate(self, id: str, by: str, reason: InvalidationReason) -> None: ...
    def assertions_as_of(self, workspace_id: str, when: datetime, **f: Any) -> list[Assertion]: ...
    def migrate(self) -> int: ...
    ...
```

Abridged. The full surface also covers entities and merges, ingest runs and
change events, run records, and schema version. `SqliteStore` adds
`search_headings`, which the third retrieval arm uses.

A `Store` implementation carries obligations the signatures cannot express:

- `invalidate` sets `invalid_at` once and never revises it. There is no delete.
- A `DocumentVersion` is immutable once written.
- `assertions_as_of` answers from system time, not from the latest state.
- `search_dense` and `search_sparse` return only chunks belonging to current
  document versions unless asked otherwise.

`SqliteStore` enforces the first two with database triggers rather than with
Python, which is the reason to read
[the store schema](store-schema.md) before writing another backend.

## Why Protocols rather than settings

Config cannot switch off a guarantee, by design. What you can do instead is
supply an object. Bring your own `Store` and the ledger lives wherever you want;
bring your own `Chunker` and boundaries are yours; bring your own `ChatModel` and
the provider question disappears. That is full power, through code you own, and
it does not require the library to offer a flag that makes its own claims false.

See [Tunability tiers](../explanation/tunability-tiers.md).
