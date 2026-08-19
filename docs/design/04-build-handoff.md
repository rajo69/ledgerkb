# Build Handoff: Start Here

> **Design record, written 2026-08-07 and last revised 2026-08-19.** Written to
> hand the build to a fresh session. It is the best single account of why the code
> is shaped the way it is, and section 10 is still the live description of what
> finishing L2 requires. Stage status in section 0 is historical: the current
> status is in [ROADMAP.md](https://github.com/rajo69/ledgerkb/blob/main/ROADMAP.md).

**Version:** 1.2 · **Date:** 2026-08-07
**Purpose:** Everything a fresh session needs to continue development without re-deriving prior decisions.

---

## 0. Where the build actually is

**L0 and L1 are complete and their gates are green. L2 is under way.**

Repository: <https://github.com/rajo69/ledgerkb> (public, Apache-2.0). CI runs on every pull request; `main` is not branch-protected yet, see section 9.

| Stage | State |
|---|---|
| **L0**, skeleton and contracts | ✅ done |
| **L1**, ingest, parse, chunk | ✅ done |
| **L2**, index and retrieve | 🟡 **half done**, machinery in, measurement outstanding |
| L3–L8, P1–P6 | not started |

```bash
uv venv && uv pip install -e ".[local]" --group dev
pytest                                    # full suite, no network, no credentials
ruff check . && mypy && lint-imports      # what CI runs
```

**What exists and works today:**

- `core/`: models, ports, config with the four tunability tiers, error taxonomy. Pure: stdlib + pydantic, CI-enforced.
- `storage/sqlite/`: migrations 001 and 002, FTS5 for BM25, float32 vector columns, database triggers refusing any delete on the ledger. `search_dense` is an exact scan; `search_sparse` works today.
- `ingest/`: filesystem and ZIP readers, tier-0 parsers for ten formats, the sanitiser, the structure-first chunker, deterministic metadata extraction, and the pipeline that wires them with content-hash dedupe and per-document failure isolation.
- `providers/fake.py`: deterministic chat, embedder and reranker. Every test uses these.
- `cli/`: `init`, `version`, `doctor`, `doctor --tiers`, `ingest`, `docs`, `chunks --verify`.
- `tests/fixtures/build_corpus.py`: generates 20 mixed-format documents, 10 injection fixtures (nine attacks and one benign decoy) and 5 malicious archives. Nothing is committed as a binary.
- CI: `ci.yml` (ruff, mypy strict on `core`, import contracts, 3 OS × 3 Python, coverage floor) and `offline.yml` (the whole suite **plus a full ingest** inside a network namespace).

**Still empty:** `index/`, `extract/`, `ledger/`, `project/`, `evals/`, `obs/`, `storage/postgres/`, `apps/`.

### 0.1 The invariant that constrains everything downstream

For every chunk, `version.text[chunk.char_start:chunk.char_end] == chunk.text`, exactly.

Chunk text is **sliced, never constructed**. There is no code path that builds a chunk by joining or stripping. Whitespace trimming moves the boundaries; overlap extends spans backwards into the source rather than copying a prefix. Sanitisation runs once, before any offset is taken, and remaps heading and page offsets so there is exactly one coordinate system.

This is what makes a citation a precise span, and it is what deterministic quote verification (L3, Arch §6.4) will check against. Anything at L2+ that rewrites chunk text breaks the citation guarantee.

### 0.2 Deviations from this document, and why

Four things differ from what is written below. All four are deliberate.

| Deviation | Reason |
|---|---|
| `ports.py` uses `TypeVar`, not PEP 695 `def structured[T: BaseModel]` | PEP 695 is 3.12+; `requires-python` and the CI matrix both include 3.11 |
| `ParsedDocument.headings` is `list[Heading]`, not `list[tuple[int, str]]` | A `heading_path` needs heading *levels*; a tuple of (offset, text) cannot express nesting |
| Migration `002_version_text` adds `text`, `parse_warnings`, `metadata_misses` to `document_version` | Storing canonical text makes the offset invariant checkable against the store, and lets re-chunking happen without re-parsing |
| `python-pptx` added to the `local` extra | PPTX is in L1's required format list but was missing from §5. MIT licensed |

---

## 1. Read this first

**What we're building:** `ledgerkb`, an open-source Python library that turns scattered documents into a queryable, exportable knowledge base that **maintains a position over time**. A web product is built on top of it later.

**The organising idea:** one append-only ledger of evidence-bearing assertions. The RAG index, knowledge graph, OKF wiki, briefing PDF and change report are all **projections** of that one ledger, not separate subsystems.

**Document map:**

| Doc | Read when |
|---|---|
| **`04-build-handoff.md`** (this) | First. Current state (§0), locked decisions, open questions, and the next stage's starting point (§10) |
| [`03-implementation-plan.md`](./03-implementation-plan.md) | Before starting any stage: it has the exit gates |
| [`02-architecture.md`](./02-architecture.md) | Designing a component: data model, pipeline, retrieval |
| [`01-product-spec.md`](./01-product-spec.md) | Building UI or deciding behaviour |
| [`00-research-log.md`](./00-research-log.md) | Tempted to change a dependency: the evidence is here |

**Order of work:** L0 → L1 → … → L8 (library, v1.0.0 on PyPI) → P1 → P6 (product). No stage starts until the previous gate is green. **L0 and L1 are done; L2 is next, see §0 and §10.**

---

## 2. Locked decisions. Do not re-litigate

Each was researched. If you want to change one, read the cited section first.

| # | Decision | Ref |
|---|---|---|
| 1 | **SQLite is the default store.** Postgres is the scale backend behind the same `Store` protocol | Plan §1.2 |
| 2 | **No Kafka, Flink, CDC, or live ingest.** Manual refresh + content hashing only | Arch §5 |
| 3 | **No graph database.** Relational `entity`/`assertion` tables + recursive CTEs. Kùzu is archived; Apache AGE isn't in Railway's image | Research §3.1–3.2 |
| 4 | **No GraphRAG framework.** Own extraction. MS GraphRAG ~100× cost; LightRAG locks storage + had auth CVEs | Research §3.3 |
| 5 | **Bitemporal invalidation**, set `invalid_at`, never delete | Arch §3.3 |
| 6 | **Quote verification is deterministic**, not an LLM judge | Arch §6.4 |
| 7 | **CRAG without a default web-search branch.** `incorrect` → abstain with named gaps | Arch §6.5 |
| 8 | **Extraction calls carry zero tools.** The architectural anti-injection control | Arch §8 |
| 9 | **Contradictions are never merged.** Two `disputed` assertions | Arch §4.6 |
| 10 | **Conservative entity resolution.** Over-merging is the failure that matters | Research §3.4 |
| 11 | **Providers behind Protocols.** OpenAI-compatible is the base adapter | Plan §6 |
| 12 | **Observability is OTel over OTLP.** No vendor SDK as a hard dependency | Plan §5 |
| 13 | **Headline evals are deterministic**, no API key required | Plan §3 |
| 14 | **Licence: Apache-2.0.** DCO sign-off, not a CLA | - |
| 15 | **Corpus-agnostic via profiles**, never via code branches | §8 below |
| 16 | **npm package is a typed API client**, not a port of the engine | - |

---

## 3. Open questions

| # | Question | State |
|---|---|---|
| Q1 | **PyPI name.** Is `ledgerkb` available? | ✅ **Resolved.** Available (so are `okfkit` and `attestkb`). Availability is not reservation, the name is only claimed on first publish at L8 |
| Q2 | **Embedding model + dimension** | 🔴 **Open, and blocking L2**, see below |
| Q3 | **PDF parser default.** `pymupdf4llm` is AGPL-3.0 | ✅ **Resolved.** `pypdfium2` (BSD-3/Apache-2.0) is the default and is implemented. Every parser dependency was licence-checked: all permissive, no AGPL anywhere |
| Q4 | **Is there a real corpus?** | ✅ **Resolved by its documented default.** None exists. `tests/fixtures/build_corpus.py` generates 20 council-shaped documents across ten formats. See the caveat below |
| Q5 | **Second corpus for the agnosticism gate** | ⬜ Open, not needed until v1.0. Pick any public document set unlike council minutes |

### Q2: resolved, but not the way this document proposed

**The recommendation here was `BAAI/bge-m3` via `fastembed`. That is not
implementable: bge-m3 is in no fastembed model list: not dense, not sparse,
not late-interaction.** The research log (§2) had always assumed bge-m3 would
be served by TEI or a gateway; the in-process path was invented in this
document and never checked.

**Resolved: `mixedbread-ai/mxbai-embed-large-v1`.** 1024 dimensions, so the
tier-3 locked field is exactly what both design documents already agreed on;
Apache-2.0; and the smallest of the permissively-licensed 1024-dimension models
fastembed actually serves. It runs in-process with no API key, which is what
the original reasoning was really protecting: `offline.yml` keeps proving
something past L1 and the eval loop stays free.

Other permissively-licensed 1024-dim options, if the corpus ever argues for
one: `BAAI/bge-large-en-v1.5` (MIT), `snowflake/snowflake-arctic-embed-l`
(Apache-2.0), `intfloat/multilingual-e5-large` (MIT, and the one to reach for
if documents stop being English). **`jinaai/jina-embeddings-v3` is excluded on
purpose**, 1024 dims and otherwise a fine model, but CC-BY-NC-4.0 is
non-commercial.

`providers/local.py` carries these widths in `KNOWN_DIMENSIONS` and checks them
against the config at construction, so a mismatch is refused before a corpus is
embedded rather than surfacing as a shape error on the first search.

### Q4: the caveat worth knowing

The fixture corpus is synthetic and was written by the same process that wrote the extractors. When metadata coverage came in below the 90% gate, **both** the extractor and the fixtures were changed: a format-based `doc_type` fallback was added (a real gap), *and* three fixtures gained approval dates while four gained programme references (making the corpus more like real council papers, but also adjusting the thing being measured). Real documents will behave differently. Treat the current coverage figures as a floor on a friendly corpus, not as a measured property of the extractor.

---

## 4. Repository layout

```
ledgerkb/
├── pyproject.toml
├── README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md  CHANGELOG.md
├── .github/workflows/            ci.yml  offline.yml   (drift/release/redteam are L8)
├── docs/                         mkdocs (Diátaxis) + design/ (the design records)
├── profiles/                     default.toml  council.toml
├── golden/                       fixtures + golden sets (YAML)
├── tests/
│   ├── unit/  integration/  property/
│   └── fixtures/corpus/          the 20-doc mixed-format fixture set
├── src/ledgerkb/
│   ├── core/                     models.py  ports.py  config.py  errors.py   ← no I/O, no provider deps
│   ├── storage/                  base.py  sqlite/  postgres/  migrations/
│   ├── providers/                openai_compat.py  anthropic.py  litellm.py  local.py  fake.py
│   ├── ingest/                   readers/  parsers/  sanitise.py  chunk.py  metadata.py
│   ├── index/                    embed.py  hybrid.py  rrf.py  rerank.py
│   ├── extract/                  assertions.py  entities.py  resolve.py  schemas.py
│   ├── ledger/                   reconcile.py  temporal.py  changes.py
│   ├── project/                  okf.py  graph.py  governance.py  briefing.py
│   ├── evals/                    runner.py  metrics.py  goldenset.py
│   ├── obs/                      otel.py  runs.py  cost.py
│   └── cli/                      main.py
└── apps/                         (empty until P1)
    ├── api/  worker/  web/  infra/
```

**Hard rule:** `core/` imports only `pydantic` and the stdlib. Enforced by a CI import-linter check. This is what makes everything testable without a network.

---

## 5. `pyproject.toml`

```toml
[build-system]
requires = ["hatchling>=1.26"]
build-backend = "hatchling.build"

[project]
name = "ledgerkb"
version = "0.0.1"
description = "Turn scattered documents into a knowledge base that maintains a position over time."
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
  "pydantic>=2.9", "httpx>=0.27", "numpy>=1.26",
  "typer>=0.12", "rich>=13", "pyyaml>=6",
  "python-dateutil>=2.9", "instructor>=1.6",
]

[project.optional-dependencies]
local    = ["fastembed>=0.4", "chonkie>=0.4", "trafilatura>=1.12",
            "pypdfium2>=4", "python-docx>=1.1", "openpyxl>=3.1", "selectolax>=0.3"]
postgres = ["psycopg[binary]>=3.2", "pgvector>=0.3"]
docling  = ["docling>=2"]
crawl    = ["crawl4ai>=0.4"]
obs      = ["opentelemetry-sdk>=1.27", "opentelemetry-exporter-otlp-proto-http>=1.27"]
eval     = ["ragas>=0.2", "deepeval>=1.4"]
litellm  = ["litellm>=1.50"]
pdf      = ["typst>=0.11"]
vec      = ["sqlite-vec>=0.1.7"]        # optional accelerator; still alpha
all      = ["ledgerkb[local,postgres,docling,crawl,obs,eval,pdf]"]

[project.scripts]
lkb = "ledgerkb.cli.main:app"

[dependency-groups]                      # PEP 735, dev only, never shipped
dev = ["pytest>=8", "pytest-asyncio", "pytest-cov", "hypothesis", "respx",
       "ruff", "mypy", "import-linter", "pytest-examples"]

[tool.ruff]
line-length = 100
target-version = "py311"
[tool.ruff.lint]
select = ["E","F","I","N","UP","B","SIM","RUF","ANN","S"]

[tool.mypy]
strict = true
files = ["src/ledgerkb/core"]

[tool.pytest.ini_options]
addopts = "-q --cov=ledgerkb --cov-report=term-missing"
markers = ["live: requires real provider credentials"]
```

---

## 6. Core contracts. Write these first

`src/ledgerkb/core/ports.py`:

```python
from typing import Protocol, Sequence, Iterable, Any
from pydantic import BaseModel

class ChatModel(Protocol):
    name: str
    def complete(self, messages: list[dict], **kw: Any) -> str: ...
    def structured[T: BaseModel](self, messages: list[dict], schema: type[T], **kw) -> T: ...
    def capabilities(self) -> "Capabilities": ...

class Embedder(Protocol):
    name: str
    dimensions: int
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

class Reranker(Protocol):
    def rerank(self, query: str, docs: Sequence[str], top_k: int) -> list[tuple[int, float]]: ...

class Parser(Protocol):
    def can_parse(self, mime: str, path: str) -> bool: ...
    def parse(self, data: bytes, hint: "ParseHint") -> "ParsedDocument": ...

class Store(Protocol):
    def upsert_document(self, doc: "Document") -> str: ...
    def add_version(self, v: "DocumentVersion") -> str: ...
    def add_chunks(self, chunks: Iterable["Chunk"]) -> None: ...
    def search_dense(self, vec: list[float], k: int, **f) -> list["Hit"]: ...
    def search_sparse(self, query: str, k: int, **f) -> list["Hit"]: ...
    def add_assertion(self, a: "Assertion", ev: list["Evidence"]) -> str: ...
    def invalidate(self, id: str, by: str, reason: str) -> None: ...
    # ... see 02-architecture.md §3 for the full surface
```

`core/models.py`: Pydantic models for `Document`, `DocumentVersion`, `Chunk`, `Entity`, `Assertion`, `Evidence`, `ChangeEvent`, `Answer`, `Claim`, `RunRecord`. Field definitions are in [`02-architecture.md §3`](./02-architecture.md).

**Two invariants to encode as validators, not conventions:**
- An `Assertion` cannot be constructed without at least one `Evidence`.
- `modality == "inferred"` requires `confidence < 1.0`.

---

## 7. SQLite schema (L0)

The Postgres DDL is in `02-architecture.md §3`. This is its SQLite counterpart.

```sql
CREATE TABLE workspace (id TEXT PRIMARY KEY, name TEXT NOT NULL,
  profile TEXT NOT NULL DEFAULT 'default', created_at TEXT NOT NULL);

CREATE TABLE source (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('gdrive','link','upload')),
  label TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}',
  connector_state TEXT NOT NULL DEFAULT '{}',
  last_refreshed_at TEXT, status TEXT NOT NULL DEFAULT 'ready');

CREATE TABLE document (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  external_id TEXT NOT NULL, uri TEXT, title TEXT, doc_type TEXT,
  meeting_or_project TEXT, published_at TEXT, authors TEXT,
  status TEXT NOT NULL DEFAULT 'active', current_version_id TEXT,
  UNIQUE (source_id, external_id));

CREATE TABLE document_version (id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL, content_hash TEXT NOT NULL, text_hash TEXT NOT NULL,
  blob_uri TEXT, mime TEXT, bytes INTEGER, page_count INTEGER,
  parser TEXT, parse_quality REAL, ingested_at TEXT NOT NULL,
  superseded_by TEXT, UNIQUE (document_id, content_hash));

CREATE TABLE chunk (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  version_id TEXT NOT NULL REFERENCES document_version(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL, heading_path TEXT, page_from INTEGER, page_to INTEGER,
  char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
  text TEXT NOT NULL,            -- verbatim source span. NEVER rewritten.
  context_header TEXT, token_count INTEGER,
  embedding BLOB);               -- float32 little-endian

-- true BM25, built into SQLite
CREATE VIRTUAL TABLE chunk_fts USING fts5(
  body, chunk_id UNINDEXED, tokenize='porter unicode61');

CREATE TABLE entity (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  type TEXT NOT NULL, canonical_name TEXT NOT NULL, normalised_name TEXT NOT NULL,
  aliases TEXT DEFAULT '[]', attrs TEXT DEFAULT '{}', embedding BLOB,
  first_seen TEXT, last_seen TEXT, merged_into TEXT REFERENCES entity(id),
  status TEXT NOT NULL DEFAULT 'active');

CREATE TABLE assertion (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  subject_id TEXT REFERENCES entity(id), predicate TEXT NOT NULL,
  object_id TEXT REFERENCES entity(id), object_literal TEXT,
  claim_text TEXT NOT NULL,
  modality TEXT NOT NULL CHECK (modality IN ('explicit','inferred')),
  confidence REAL NOT NULL DEFAULT 1.0,
  valid_from TEXT, valid_to TEXT, asserted_at TEXT NOT NULL,
  invalid_at TEXT, invalidated_by TEXT REFERENCES assertion(id),
  invalidation_reason TEXT CHECK (invalidation_reason IN
    ('superseded','contradicted','corrected','source_withdrawn')),
  status TEXT NOT NULL DEFAULT 'active', stale_after TEXT,
  verified_by TEXT, verified_at TEXT);

CREATE TABLE assertion_evidence (assertion_id TEXT NOT NULL
    REFERENCES assertion(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES chunk(id), quote TEXT NOT NULL,
  char_start INTEGER, char_end INTEGER, PRIMARY KEY (assertion_id, chunk_id));

CREATE TABLE entity_merge_log (id TEXT PRIMARY KEY, winner_id TEXT NOT NULL,
  loser_id TEXT NOT NULL, method TEXT NOT NULL, score REAL, evidence TEXT,
  decided_by TEXT NOT NULL, decided_at TEXT NOT NULL, reverted_at TEXT);

CREATE TABLE quarantine (id TEXT PRIMARY KEY, version_id TEXT NOT NULL,
  char_start INTEGER, char_end INTEGER, text TEXT NOT NULL,
  reason TEXT NOT NULL, detected_at TEXT NOT NULL);

CREATE TABLE ingest_run (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  source_id TEXT, trigger TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, docs_seen INTEGER, docs_changed INTEGER,
  docs_new INTEGER, docs_gone INTEGER, stats TEXT);

CREATE TABLE change_event (id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES ingest_run(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, assertion_id TEXT, prior_assertion_id TEXT,
  summary TEXT NOT NULL, detail TEXT);

CREATE TABLE run_record (id TEXT PRIMARY KEY, run_id TEXT, stage TEXT NOT NULL,
  model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
  duration_ms INTEGER, error TEXT, created_at TEXT NOT NULL);

CREATE INDEX idx_chunk_ws ON chunk(workspace_id, version_id);
CREATE INDEX idx_assert_active ON assertion(workspace_id, status) WHERE invalid_at IS NULL;
CREATE INDEX idx_assert_stale ON assertion(workspace_id, stale_after) WHERE status = 'active';
```

Migrations are plain numbered SQL (`001_init.sql`, `002_…`) with a `schema_version` table. No Alembic, the schema is small and additive.

---

## 8. Config and profiles: the tuning surface

**One file holds every knob that exists.** Versioned, and stamped into every export's build receipt so any output is reproducible.

The governing rule: **tunable = quality/cost tradeoffs. Not tunable = correctness invariants.** If a setting could make the system lie, it is not a setting.

`ledgerkb.toml`:

```toml
config_version = 1
profile = "default"

[store]      backend = "sqlite"   path = ".lkb/store.db"

[chat]       provider = "openai_compatible"
             base_url = "https://openrouter.ai/api/v1"
             model = "qwen/qwen3-235b-a22b"
             api_key_env = "OPENROUTER_API_KEY"
[chat.cheap] model = "deepseek/deepseek-v3.2"     # headers, extraction, grading

[embeddings] provider = "openai_compatible"
             model = "qwen/qwen3-embedding-8b"
             dimensions = 1024                     # LOCKED after first index

[chunking]   max_tokens = 512   overlap = 64   structure_first = true
[retrieval]  dense_k = 50   sparse_k = 50   rrf_k = 60   rerank_to = 8
[resolution] trigram = 0.85   grey_band = [0.80, 0.92]   auto_merge = false
[parsing]    density_probe = 0.6   tier1 = "docling"
[budget]     max_cost_usd_per_run = 5.0   max_docs_per_run = 1000
[obs]        otlp_endpoint = ""   semconv_version = "1.42.0"
```

### 8.1 Four tiers of tunability

Approximately **20 free · 4 gated · 3 locked · 8 fixed**. Implement the tier as an attribute of each config field, so validation enforces it rather than documentation asking nicely.

**Tier 1: free.** Hot, no rebuild:
`dense_k` · `sparse_k` · `rrf_k` · `rerank_to` · `max_tokens` · `overlap` · `density_probe` · `tier1` parser · chat model per stage · temperature · concurrency · `max_cost_usd_per_run` · `max_docs_per_run` · staleness defaults · `otlp_endpoint` · `semconv_version` · log level · store path

**Tier 2: gated.** Changing these invalidates derived data. The CLI must state what will be rebuilt and refuse to leave the store inconsistent:

| Knob | Forces |
|---|---|
| `resolution.trigram` / `grey_band` | Re-run resolution (merges are reversible, so this is safe) |
| `contextual_headers` on/off | Full re-index |
| Profile `entity_types` / `predicates` | Re-extraction |
| `auto_merge` | Re-run resolution |

**Tier 3: locked after first use.** Requires an explicit destructive command (`lkb reindex --confirm`):

| Knob | Why |
|---|---|
| **Embedding model + `dimensions`** | Every stored vector becomes meaningless |
| Store backend | A migration, not a setting |
| Tokenizer | Chunk boundaries shift, breaking existing offsets |

**Tier 4: not exposed.** These have **no config key at any level**. Do not add one, and reject PRs that do:

| Invariant | Why it must not be switchable |
|---|---|
| **Quote verification** | If switchable, "this system verifies citations" degrades to "it might, depending on config", and every downstream claim weakens. Fuzzy floor is *clamped* to `[0.90, 1.0]`, not free |
| **Zero tools in extraction calls** | The anti-injection control is architectural |
| **Append-only ledger / never delete** | History preservation is the product |
| **Contradictions stay unmerged** | Display may vary; the store may never pick a winner |
| **Evidence required per assertion** | DB constraint |
| **Closed predicate schema** | Extend via profile; never disable validation |
| **ZIP / path-traversal guards** | Not negotiable |
| **Budget guards abort** | You set the ceiling; you cannot set "ignore it" |

### 8.2 The escape hatch

Config-only would be too rigid for a library, but the extension point is **Protocol ports, not weakened invariants.** Supply your own `Store`, `Chunker`, `Reranker`, `ChatModel` or `Parser`. That is full power, through code you own. What is *not* available is a flag that silently disables a guarantee.

Two supporting behaviours to build at L0:
- Config validation **rejects incoherent combinations loudly at startup**, never misbehaves later.
- The fully-resolved config is stamped into every export's build receipt, so any artifact can be audited for how it was produced, including whether a custom port was substituted.

### 8.3 Profiles

**Profiles carry domain knowledge so the code stays corpus-agnostic.** `profiles/default.toml` ships generic; `profiles/council.toml` overrides.

```toml
entity_types = ["Person","Organisation","Project","Meeting","Decision",
                "Action","Risk","Document","Location","Policy"]
predicates   = ["attended","owns","was_made_at","is_assigned_to","relates_to",
                "threatens","mentions","supersedes","depends_on","supports"]
doc_types    = ["minutes","report","register","policy","email","note"]

[staleness]  default_days = 180
             minutes = 90
             register = 120

[extraction] hints = "Documents are formal meeting records with numbered agenda items."
```

**The tuning loop.** The golden set is the only arbiter:

```bash
lkb eval run --tag baseline
# change exactly one knob
lkb eval run --tag trigram-090
lkb eval compare baseline trigram-090     # metric deltas + per-question regressions
```

---

## 9. CI workflows

Three workflows exist: `ci.yml`, `offline.yml` and the `docs` job inside
`ci.yml`. The other three below are planned for L8 and are marked as such.

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | PR, push | ruff · mypy strict on `core` · import-linter · pytest matrix (3.11/3.12/3.13 × linux/mac/win) · coverage ratchet |
| `offline.yml` | PR | Full ingest→chunk suite **with egress blocked**. Proves no accidental network dependency |
| `drift.yml` *(planned, L8)* | Nightly | Golden set against pinned models. **Catches silent provider behaviour changes** |
| `redteam.yml` *(planned, L8)* | PR + weekly | promptfoo injection suite; zero criticals |
| `release.yml` *(planned, L8)* | Tag | Build · test · **PyPI Trusted Publishing (OIDC)** · sigstore attestation · CycloneDX SBOM · GitHub release |

**All tests default to the fake provider**, zero API calls, zero cost, zero flake. Real-provider tests are marked `@pytest.mark.live` and run only in `drift.yml` with credentials.

Enforced today: `pip-audit` in `ci.yml`, and Renovate for dependency updates.

Planned, and not true yet: branch protection on `main`, required pull request
review, a DCO sign-off check, and a Conventional Commits check. Sign-off and
Conventional Commits are asked for in
[CONTRIBUTING.md](https://github.com/rajo69/ledgerkb/blob/main/CONTRIBUTING.md) and followed by hand; nothing rejects a
commit that omits them. Enabling the first two is item 5 of phase 5 in the
documentation plan.

---

## 10. Next session: finish L2

**Half of L2 is in.** `providers/openai_compat.py`, `providers/local.py`,
`providers/factory.py`, `index/embed.py`, `index/rrf.py`, `index/hybrid.py`,
`lkb index` and `lkb search --explain --json` all work, offline, with no key.
Migrations 003 and 004 moved two invariants into the schema.

**What is left is the measurement, and it is blocked on the corpus.**

### The corpus problem, read this before writing a golden set

The fixture corpus produces **55 chunks**. The defaults are `dense_k = 50` and
`sparse_k = 50`, so each arm is asked for roughly 91% of the entire corpus and
RRF fuses two lists that both contain nearly everything. `recall@20` asks the
retriever to return 36% of the corpus. Every strategy scores about 1.0.

**The L2 gate as written cannot go red**, which means passing it would prove
nothing. Two of its criteria, "hybrid beats dense-only *and* BM25-only" and
"contextual headers improve recall@20 by ≥ 5 points", are unmeasurable at this
size. Fix the corpus before writing the questions, not after.

1. **Grow it to ~200 documents / 3–5k chunks.** `tests/fixtures/build_corpus.py`
   is generative, so this is parameterisation rather than authoring, and the
   corpus stays reviewable source instead of a committed binary.
2. **Change the metrics.** `recall@5` and `nDCG@10` as headline, plus MRR, plus
   a hard-negatives subset: questions whose answer chunk shares vocabulary with
   at least three decoys. Those are the only questions that discriminate.
3. **Require a bootstrap confidence interval on the hybrid delta**, not merely a
   positive number. With 40 questions a 5-point difference is two questions.
4. **Write the questions from the documents alone, before running retrieval.**
   Q4's caveat, that the extractor and the fixtures were adjusted together,
   applies doubly here, where both the questions and the documents would be
   synthetic and written by the same process.
5. **Bring Q5's second corpus forward** from v1.0 to now. Any public document
   set unlike council minutes will do.

### Then

6. **`index/contextualise.py`**, but default it **off** and make the A/B earn
   it. `chunking.contextual_headers` is now `False` by default for exactly this
   reason. The baseline to beat is not "no context": it is the **heading arm**,
   which already carries "Planning Committee Minutes > Item 4 > Decision"
   deterministically, offline and free. If the deterministic path captures most
   of the gain on structured minutes, that is a publishable result and it
   deletes the highest-volume LLM call in the system.
7. **`index/rerank.py`**, behind the existing `Reranker` port, defaulted off,
   in its own extra. A cross-encoder is either an API call (breaks
   `offline.yml`) or a torch dependency (breaks the install gate).
8. **Record the embedding model in the store and detect a change**, which the
   gate asks for. `search_dense` now raises a named `InvariantError` on a width
   mismatch, but nothing yet compares the stamped model to the configured one on
   the index path, `check_transition` is still only called by `lkb doctor`.

### Watch out for

- **Never write to `chunk.text`.** Context headers go in `context_header`;
  `chunk.body` is a generated column and the FTS index follows it by trigger.
- **The budget guard aborts.** `max_cost_usd_per_run` has no override, by design.
- **Keep `offline.yml` green.** The default embedder is local, but fastembed
  downloads weights on *first use*, so a job inside a network namespace must
  warm the model cache before it enters, or stay on the fake providers.

### Earlier gates, for reference

**L0 gate** ✅, clean install on all three OSes · `mypy --strict` green · `lkb init && lkb doctor` with zero API keys · every core model round-trips through SQLite unchanged.

**L1 gate** ✅, 20/20 fixtures ingest with zero unhandled exceptions · 55/55 chunks slice back byte-identical (plus a Hypothesis property over arbitrary input) · all five metadata fields ≥ 95% · nine attack fixtures caught and the benign decoy untouched · 5/5 malicious archives refused · the whole path runs with no network and no API key.

---

## 11. Conventions

- **`core/` stays pure.** No I/O, no provider SDKs, no framework imports. CI-enforced.
- **Ports before implementations.** A new capability starts as a Protocol.
- **Invariants are constraints, not conventions.** Assertions without evidence must be *impossible to construct*, not merely discouraged.
- **Tier 4 invariants get no config key.** See §8.1. A PR that adds one is rejected regardless of how convenient it is.
- **Deterministic over probabilistic.** If a check can be code instead of an LLM, make it code, that is the design principle behind quote verification, the closed schema, and RRF.
- **The golden set is the arbiter.** No knob is tuned by feel.
- **Fail loud, degrade gracefully.** A parse failure names the document and keeps the other 55 usable, never all-or-nothing.
- **Product contains no domain logic.** If a `P` stage needs some, it belongs in the library.
- Conventional Commits · DCO sign-off · SemVer · `core/` gets a stability commitment at v1.0.0.
