# Architecture

A bird's eye view of `ledgerkb`, written for somebody about to make their first
change. It describes the things unlikely to move: the organising idea, where code
lives, and the rules that must hold. It is revisited a few times a year rather
than kept in step with every commit.

For why a particular technology was chosen, read
[`docs/design/00-research-log.md`](docs/design/00-research-log.md). For what is
built and what is not, read [ROADMAP.md](ROADMAP.md).

## 1. Bird's eye view

A team accumulates documents faster than anybody can read them: minutes, reports,
risk registers, email. Tools in this category answer questions about that pile and
then forget. Ask twice, get two independently derived answers. Add a document and
nothing happens until somebody thinks to ask the right question again.

`ledgerkb` takes a different shape. It compiles documents once into an
append-only ledger of evidence-bearing assertions, and everything a user sees is
a projection of that ledger.

```
                    ┌──────────────────────────────────┐
   sources  ─────►  │      DOCUMENT VERSIONS           │  immutable, hashed
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │      CHUNKS (+ context header)   │  addressable spans
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │      ASSERTION LEDGER            │  ◄── the source of truth
                    │  subject · predicate · object    │      append-only
                    │  evidence · valid_from/to        │      bitemporal
                    │  invalid_at · modality · conf.   │
                    └────────────────┬─────────────────┘
                                     │
        ┌──────────────┬─────────────┼─────────────┬──────────────┐
        ▼              ▼             ▼             ▼              ▼
    retrieval      graph          wiki          exports      change report
    (chunks +      (nodes/        (markdown     (pdf/json/    (ledger diff
     vectors)       edges)         bundle)       graphml)      across runs)
```

Four consequences fall out of that shape rather than being features built on top
of it:

- Belief revision is setting `invalid_at`, never deleting, so history stays
  queryable.
- The change report is a diff of the ledger between two ingest runs.
- Governance is a query over `stale_after`, confidence, source count and whether
  an owner is null.
- Citations cannot drift between projections, because every projection carries
  the same `chunk_id`.

The alternative, which this design rejects, is writing a vector index, a graph and
a wiki concurrently from the same documents. That is three sources of truth that
will disagree, with nothing to reconcile them.

The top two boxes and the retrieval projection exist in code today. The assertion
ledger has its tables, its constraints and its triggers, but nothing writes to
them yet, and the other four projections are not built. Section 2 says which
directories are still empty.

## 2. Code map

Everything ships from `src/ledgerkb/`. Types and filenames are named here but not
linked: symbol search costs nothing to maintain and teaches you the codebase on
the way past.

### `core/`

The domain, and nothing else. `models.py` holds the Pydantic models: `Document`,
`DocumentVersion`, `Chunk`, `Entity`, `Assertion`, `Evidence`, `ChangeEvent`,
`Hit`, `Claim`, `Answer`, `RunRecord`. `ports.py` holds every Protocol the rest
of the library depends on: `ChatModel`, `Embedder`, `Reranker`, `Reader`,
`Parser`, `Chunker`, `Store`. `config.py` is the entire tuning surface, with each
field carrying its tunability tier as annotated metadata. `errors.py` is the error
taxonomy, rooted at `LedgerKBError`.

`core/` performs no I/O and imports nothing but the standard library and
pydantic. That is what lets the whole test suite run with no network and no
credentials, and it is checked in CI rather than trusted.

### `storage/`

`base.py` holds the migration runner: plain numbered SQL files with a
`schema_version` table, no migration framework. `sqlite/store.py` is the default
store and the only one implemented. `postgres/` is an empty package reserved for
the scale backend behind the same `Store` protocol.

The SQLite schema is not a passive container. It refuses deletes on the ledger,
refuses a second write to `invalid_at`, refuses to mutate a document version's
hashes, maintains the full-text index from a generated column by trigger, and
rejects an inferred assertion claiming full confidence. Read
`migrations/001_init.sql` through `005_embedding_space.sql` before changing
anything about how data is written.

### `providers/`

Adapters behind the `ChatModel`, `Embedder` and `Reranker` ports.
`openai_compat.py` speaks `/chat/completions` and `/embeddings`, which covers
most hosted providers and every local server that imitates them.  `local.py`
runs an embedding model in-process through fastembed, with a table of known model
dimensions so a config mismatch is refused before a corpus is embedded rather
than surfacing as a shape error on the first search. `fake.py` is a deterministic
chat, embedder and reranker; every test uses it. `factory.py` is the one place a
provider name in config becomes a class.

Nothing outside this directory may import a provider SDK.

### `ingest/`

The path from bytes to stored chunks. `readers/fs.py` walks the filesystem;
`readers/archive.py` expands ZIP archives with guards against path traversal,
compression ratio, nesting depth and total size. `parsers/` holds tier-0 parsers
for eleven formats behind `registry.py`, which dispatches on the first parser to
claim a file and raises a named `ParseError` rather than guessing. `sanitise.py`
removes invisible text and quarantines instruction-shaped spans without deleting
them. `chunk.py` splits on document structure. `metadata.py` extracts five fields
deterministically and reports every miss. `pipeline.py` wires the stages together,
dedupes by content hash before parsing, and isolates per-document failures.

### `index/`

Retrieval. `embed.py` embeds chunks and queries, and holds
`guard_embedding_space`, which is what stops one index from collecting vectors
from two models. `rrf.py` is reciprocal rank fusion, and is pure: no store, no
provider, no I/O. `hybrid.py` runs the three
arms (dense vectors, FTS5 BM25 over the chunk body, and FTS5 over the heading
path), fuses them, optionally reranks, and keeps each arm's own ranked list so
`--explain` and the evals can tell a retrieval win from a lucky ordering.

### `cli/`

`main.py` is the whole command line, built with typer. It formats, it does not
decide: every command opens the config and the store, calls into the library, and
prints. Anything a document controls is escaped before it reaches the console,
because output is styled with Rich markup and a document is untrusted input.

### Still empty

`extract/`, `ledger/`, `project/` and `obs/` are packages with nothing in them
but an `__init__.py`. So is `storage/postgres/`, and so is `apps/` at the
repository root. They are named here because the layering contract already knows
about them, so the shape of the system is settled even where the code is not.
What each will hold is in [ROADMAP.md](ROADMAP.md) under L4 to L8 and P1.

`evals/` is no longer among them. It holds the measurement machinery L2 needs:
the provenance header a committed result carries, the golden set format, and the
retrieval metrics. None of it runs retrieval, and no measurement has been taken.

## 3. Invariants

Each of these is a rule plus the mechanism that enforces it. A rule with no
mechanism is a wish, and this section only lists the ones with mechanisms.

**Chunk text is sliced, never constructed.** For every chunk,
`document_text[chunk.char_start:chunk.char_end] == chunk.text`, exactly. No code
path builds a chunk's text by joining, stripping or normalising. Whitespace
trimming moves the boundaries instead; overlap extends a span backwards into the
source rather than copying a prefix. *Enforced by* a Hypothesis property test over
arbitrary input, plus `lkb chunks --verify`, which re-slices every stored chunk
from the stored document text.

**Sanitisation happens once, before any offset is taken.** It deletes characters,
so it remaps every heading and page offset as it goes. There is exactly one
coordinate system. *Enforced by* the same property test, which runs over
post-sanitisation text.

**The ledger is append-only.** `invalid_at` is the only mutation and it is written
once. *Enforced by* database triggers that abort a delete on `assertion` or
`assertion_evidence`, and abort a second write to `invalid_at`.

**A document version is immutable.** A new content hash is a new row.
*Enforced by* a trigger that aborts an update to `content_hash`, `text_hash` or
`ingested_at`.

**The dense and sparse indexes cannot disagree.** The full-text index reads a
generated column combining the context header and the chunk text, maintained by
trigger. A caller who writes a context header and forgets to reindex cannot
desynchronise them. *Enforced by* `003_fts_and_versions.sql`.

**Retrieval returns only current document versions.** Re-ingesting a changed
document must not leave two generations of its chunks live in the index, or a
citation can point at text no longer in the document. *Enforced by*
`superseded_by` being written on ingest and filtered on search.

**An assertion cannot exist without evidence, and an inference cannot claim
certainty.** *Enforced by* a Pydantic validator on `Assertion` and a `CHECK`
constraint in the schema, so it is impossible to construct rather than
discouraged.

**One index holds vectors from one model.** Two models of the same width produce
vectors in different geometries, and cosine distance between them is still a
number, so a mixed index returns a confidently ranked list of noise without
raising and without looking empty. `embedding_space` records the model each
workspace was indexed with, taken from what the embedder reported rather than
from what the config asked for. *Enforced by* `guard_embedding_space` on the
index path, which refuses a mismatch even when there is nothing left to embed,
and by `lkb index --rebuild` being the only way to change model. `lkb doctor`
reports it, but reporting is not the mechanism: the damage would be done by a
command the report does not stop.

### Invariants that are absences

These are the ones you cannot infer by reading the source, because there is
nothing to read. They are as load-bearing as the rules above.

**There is no configuration key for a tier-4 setting.** Quote verification, zero
tools in extraction calls, the append-only ledger, unmerged contradictions,
required evidence, the closed predicate schema, path-traversal guards and budget
aborts have no key at any level, and a pull request adding one is rejected however
convenient it would be. The rule is that if a setting could make the system lie,
it is not a setting. The escape hatch is the Protocol ports: supply your own
`Store`, `Chunker`, `Reranker`, `ChatModel` or `Parser` and you have full power
through code you own. What is not on offer is a flag that quietly disables a
guarantee.

**There is no delete path on the ledger.** Not a soft one, not an admin one. Entity
merges are soft and reversible for the same reason.

**There is no code branch for a particular corpus.** Domain knowledge lives in
`profiles/*.toml`: entity types, predicates, document types, staleness defaults,
extraction hints. If you find yourself writing `if doc_type == "minutes"` in
`src/`, the knowledge belongs in a profile.

**There is no LLM call where deterministic code would do.** Quote verification is
string matching. The predicate schema is a `Literal`. Rank fusion is arithmetic.
Metadata extraction is rules. These are cheap, they cannot be prompted away, and
they do not change under you when a provider ships a new checkpoint.

**There is no keyword blocklist.** Trigger words appear innocently in real
documents, and council minutes genuinely contain sentences like "the committee
resolved to ignore the previous recommendation". Injection detection requires an
instruction verb and a token addressing a model together, in a short window.

## 4. Cross-cutting concerns

**The offset guarantee.** Section 3 states it. What matters architecturally is
that it constrains every stage downstream: anything that rewrites chunk text
breaks citation verification, which is the guarantee the whole system rests on.
Context headers go in `context_header`, never into `text`.

**Four tunability tiers.** Every config field is annotated with its tier, and
validation enforces the tier rather than documentation asking nicely. Free
settings are hot. Gated settings invalidate derived data, and changing one raises
unless the caller has confirmed the rebuild, so the store is never left
inconsistent. Locked settings need an explicit destructive command. Tier 4 has no
field at all. `lkb doctor --tiers` prints the whole table from the code, so it
cannot drift from what is implemented.

**Layering, enforced by import-linter.** Three contracts run in CI: `core`
imports nothing else from `ledgerkb`; `core` imports no third-party package
except pydantic; and the packages form a strict layering with `cli` at the top
and `core` at the bottom. A violation fails the build rather than being noticed
in review.

**Fail loud, degrade gracefully.** These are not in tension. A parse failure names
its document and the run continues with the rest, because all-or-nothing ingest of
somebody's document set is useless in practice. But a failure is never silent, and
a value that could not be determined is reported as a miss rather than written as
null. Errors are typed: `ConfigError`, `LockedSettingError`, `GatedSettingError`,
`InvariantError`, `ParseError`, `StorageError`, `ProviderError`,
`BudgetExceededError`.

**Offline by default.** Ingest, chunking, embedding, retrieval and the entire test
suite run with no network and no API key. The default embedder runs in-process.
A separate CI workflow runs the whole suite plus a full ingest inside a network
namespace, and fails if the network turns out to be reachable, so a job that
proves nothing cannot report green.

## 5. Where to start reading

- `src/ledgerkb/core/models.py` and `core/ports.py`. Between them they define
  every noun and every seam in the system. Half an hour here saves a day.
- `src/ledgerkb/ingest/chunk.py`. The offset invariant is easiest to understand
  where it is created, and this module exists to protect it.
- `src/ledgerkb/index/hybrid.py` and `index/rrf.py`. About 180 lines that contain
  the whole retrieval argument.
- `src/ledgerkb/storage/migrations/`. Read the four files in order. The comments
  explain why each invariant moved out of Python and into the schema.

For a first change, `src/ledgerkb/ingest/parsers/` is the friendliest place: the
`Parser` protocol is small, the registry makes a new format a single
registration, and the fixture corpus generator gives you something to test
against. [CONTRIBUTING.md](CONTRIBUTING.md) walks a change through end to end.
