# Implementation Plan — Library First, Product Second

**Version:** 1.0 · **Date:** 2026-08-07
**Companion docs:** [`00-RESEARCH-LOG.md`](./00-RESEARCH-LOG.md) · [`01-PRODUCT-SPEC.md`](./01-PRODUCT-SPEC.md) · [`02-ARCHITECTURE.md`](./02-ARCHITECTURE.md)

---

## 0. The gating rule

**Every stage ends with a hard, measurable gate. A stage does not begin until the previous gate is green.**

| Gate colour | Meaning | Action |
|---|---|---|
| 🟢 **GREEN** | All exit criteria met, CI passing | Proceed to next stage |
| 🟡 **AMBER** | Criteria met but with a known defect logged | Proceed **only** if the defect is written into the risk register with an owner |
| 🔴 **RED** | Any criterion unmet | Stop. Fix or explicitly descope in writing. Never carry forward silently |

Stages are numbered `L*` (library) and `P*` (product). **No `P` stage begins before `L8` is green** — with one deliberate exception noted in §9 for the hackathon fast path.

---

## 1. Package shape

**Working name:** `ledgerkb` (CLI: `lkb`). Alternates if PyPI is taken: `okfkit`, `attestkb`. *Check availability at L0.*

```
ledgerkb/
  core/         domain models, Protocol definitions. ZERO I/O, ZERO provider deps.
  storage/      Store protocol → SQLiteStore | PostgresStore
  providers/    ChatModel | Embedder | Reranker protocols → adapters
  ingest/       readers · parsers · sanitiser · chunker
  index/        hybrid retrieval · RRF · rerank
  extract/      assertion + entity extraction · resolution cascade
  ledger/       bitemporal ops · reconciliation · change report
  project/      okf · graph · governance · briefing renderers
  evals/        golden-set runner · deterministic metrics
  obs/          OpenTelemetry instrumentation · run records
  cli/          typer CLI
```

**Hard rule:** `core/` imports nothing but `pydantic` and the stdlib. Every outward dependency crosses a Protocol boundary. This is what makes the library testable without network, and what lets the product layer swap implementations without forking.

### 1.1 Dependency policy

Base install stays small. Everything heavy is an extra.

```toml
[project]
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.9", "httpx>=0.27", "numpy>=1.26",
  "typer>=0.12", "rich>=13", "pyyaml>=6", "python-dateutil>=2.9",
  "instructor>=1.6",
]

[project.optional-dependencies]
parsers  = ["pypdfium2>=4,<6", "python-docx>=1.1,<2", "openpyxl>=3.1,<4",
            "selectolax>=0.3,<1", "python-pptx>=1.0,<2"]
embed    = ["fastembed>=0.4,<1"]
extract  = ["instructor>=1.6,<2"]
local    = ["ledgerkb[parsers,embed]"]
postgres = ["psycopg[binary]>=3.2", "pgvector>=0.3"]
docling  = ["docling>=2"]
obs      = ["opentelemetry-sdk>=1.27", "opentelemetry-exporter-otlp-proto-http>=1.27"]
litellm  = ["litellm>=1.50"]
pdf      = ["typst>=0.11"]
vec      = ["sqlite-vec>=0.1.7"]
all      = ["ledgerkb[local,extract,postgres,docling,obs,pdf,vec]"]

[dependency-groups]                      # PEP 735 — dev only, never shipped via PyPI
dev = ["pytest", "pytest-asyncio", "ruff", "mypy", "hypothesis", "respx"]
```

Build backend **hatchling ≥1.26**, managed with **uv**. Note the distinction: `[project.optional-dependencies]` are installable from PyPI; `[dependency-groups]` are not — dev tooling belongs in the latter.

### 1.2 Storage: SQLite by default

The single most important decision for a library. `pip install ledgerkb && lkb ingest ./docs` must work with **no Docker, no server, no extension**.

| | SQLite (default) | Postgres (scale) |
|---|---|---|
| Vector search | float32 BLOB + **numpy brute force**; optional `sqlite-vec` | `pgvector` HNSW + iterative scan |
| Keyword search | **FTS5 `bm25()` — true BM25** | `tsvector` + `ts_rank_cd` |
| Queue | in-process | `pgmq` |
| Schedule | none | `pg_cron` |
| Ceiling | ~100k chunks | millions |

Two things worth stating plainly:

1. **Brute-force KNN is the right call at this scale.** 50k chunks × 1024 dims float32 = ~200MB, cosine over the whole matrix in single-digit milliseconds. `sqlite-vec` is still at `0.1.7.alpha` as of Feb 2026 — fine as an *optional* accelerator, wrong as a hard dependency for a library that must install cleanly everywhere.
2. **A known asymmetry:** SQLite gets *real* BM25 via FTS5; Postgres gets `ts_rank`, which is not BM25 (no length normalisation, no saturating term frequency). Local dev therefore has better lexical ranking than production until `pg_search` is added. Documented, not hidden — see risk R4.

---

## 2. Library stages

### L0 — Skeleton and contracts
**Goal:** the shape everything else fills in.

**Build**
- Repo, `pyproject.toml`, uv lockfile, ruff + mypy strict on `core/`, pytest, GitHub Actions matrix (3.11/3.12/3.13 × linux/macos/windows).
- `core/models.py` — `Document`, `DocumentVersion`, `Chunk`, `Entity`, `Assertion`, `Evidence`, `ChangeEvent` as Pydantic models.
- `core/ports.py` — `Store`, `ChatModel`, `Embedder`, `Reranker`, `Parser`, `Chunker`, `BlobStore` Protocols.
- `storage/sqlite.py` — schema + migrations (a plain numbered-SQL migrator; no Alembic).
- `providers/fake.py` — deterministic fake chat/embedder for tests.
- `lkb init`, `lkb version`, `lkb doctor` (environment diagnostics).

**Exit gate 🟢**
- [ ] `pip install -e .` clean on all three OSes, **base install < 60s and < 120MB**
- [ ] `mypy --strict ledgerkb/core` passes
- [ ] `lkb init && lkb doctor` green with zero API keys set
- [ ] Round-trip test: every core model persists and reloads from SQLite unchanged
- [ ] PyPI name confirmed available and reserved

**Effort:** ~0.5 day · **Risk:** low

---

### L1 — Ingest, parse, chunk *(no LLM, no network)*
**Goal:** documents → chunks with correct metadata and offsets. Entirely offline.

**Build**
- Readers: PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, HTML, JSON, EML. **`.zip` expansion** with traversal, bomb-ratio, depth and size guards.
- Tier-0 parsers: `pypdfium2` (born-digital PDF), `trafilatura` (HTML), native readers. Tier-1 `docling` behind the `[docling]` extra and a text-density probe.
- Sanitiser: zero-width and bidi-control stripping, hidden-text removal (colour==background, `display:none`, HTML comments), Unicode NFKC, **instruction-shape quarantine** (stored, not deleted).
- Structure-first chunker: heading tree → sections; Chonkie `SemanticChunker` only for oversized sections.
- Metadata extraction: title, date, `doc_type`, `meeting_or_project`, source URL, page/section — **the exact five the brief names**.
- `lkb ingest <path|url> [--source NAME]`, `lkb docs`, `lkb chunks <doc_id>`.

**Exit gate 🟢**
- [ ] 20-document fixture corpus (mixed formats) ingests with **zero unhandled exceptions**
- [ ] **Every chunk's `char_start:char_end` slices back to byte-identical text in its source document** — property test over the full corpus
- [ ] All five required metadata fields populated on ≥ 90% of fixtures; misses reported, never silently null
- [ ] Sanitiser catches all 10 hand-built injection fixtures (zero-width, white-on-white, comment-embedded, …)
- [ ] ZIP guards reject all 5 malicious archive fixtures
- [ ] **Runs with no network and no API key** — enforced by a CI job with egress blocked

**Effort:** ~1 day · **Risk:** medium (parser edge cases)

---

### L2 — Index and retrieve
**Goal:** hybrid retrieval that beats either half alone.

**Build**
- `Embedder` adapters: OpenAI-compatible HTTP; `fastembed` local (ONNX, no torch).
- Contextual headers (Anthropic Contextual Retrieval) — batched, parent-document prompt caching, applied to **both** indexes.
- Hybrid: dense KNN + FTS5 BM25 → **RRF (k=60)** → optional cross-encoder rerank.
- Retrieval config object, persisted per workspace so results are reproducible.
- `lkb index`, `lkb search "<q>" [--k N] [--explain]`.

**Exit gate 🟢**
- [ ] Golden set (**written in this stage, not later**): 40 questions, ≥ 7 unanswerable
- [ ] **recall@20 ≥ 0.90** on answerable questions
- [ ] Hybrid beats dense-only *and* BM25-only on the same set — measured, printed, committed
- [ ] Contextual headers improve recall@20 by ≥ 5 points (the A/B is the justification for the cost)
- [ ] Embedding model + dimension recorded in the store; **re-index required and detected on change**
- [ ] `--explain` prints per-candidate dense rank, BM25 rank, fused score

**Effort:** ~1 day · **Risk:** medium

---

### L3 — Grounded answering → 📦 **v0.1.0 on PyPI**
**Goal:** cited answers, honest abstention. **This alone satisfies Challenge 1 of the brief.**

**Build**
- Structured `Answer` model: `claims[]` each with `chunk_id`, verbatim `quote`, `modality` (`fact`|`inference`), `confidence`.
- **Deterministic quote verification** — normalised exact match, then fuzzy ≥ 0.95. Unverified claims demoted or dropped. *Runs before the answer is returned, every time.*
- CRAG routing: `correct` → generate · `ambiguous` → expand + retry once · `incorrect` → rewrite, retry once, then **abstain with named coverage gaps**. No default web search.
- `lkb ask "<q>" [--json] [--cite]`, `lkb serve --repl`.
- **README** covering the five things the brief requires: retrieval approach, chunking strategy, why this search method, limitations, how to add documents.

**Exit gate 🟢**
- [ ] **Citation validity = 1.00.** Not a target — a hard assertion. Any claim whose quote is absent from its cited chunk cannot reach the caller.
- [ ] **Correct-abstention ≥ 0.90** on the unanswerable subset
- [ ] Zero hallucinated `chunk_id`s across the full golden set
- [ ] `facts` and `inference` never conflated in output
- [ ] Published to PyPI; `pip install ledgerkb[local]` → ingest → ask works in a clean container in **< 5 minutes**
- [ ] README completed and accurate

**Effort:** ~1 day · **Risk:** medium

---

### L4 — Assertion ledger and extraction
**Goal:** documents become claims with evidence.

**Build**
- `assertion` + `assertion_evidence` tables; append-only enforcement in the store layer.
- Instructor-based extraction with a **closed** predicate schema (10 relationship types from the brief).
- Post-conditions in code: quote must exist in chunk; `inferred` ⇒ `confidence < 1.0`; unknown predicate ⇒ reject.
- **Extraction calls carry zero tools.** Enforced by a test that asserts the outgoing request body has no `tools` key.
- `stale_after` computation: explicit review dates, deadlines, conditional language, source cadence.
- Decision status: `proposed` | `confirmed` — the brief distinguishes these and nothing else in the model does.
- `lkb compile`, `lkb assertions [--entity X]`.

**Exit gate 🟢**
- [ ] **100% of assertions have ≥ 1 evidence row** — DB constraint, not convention
- [ ] 100% of evidence quotes verify against their chunk
- [ ] Extraction precision ≥ 0.85 on a 100-assertion hand-labelled sample
- [ ] Zero out-of-schema predicates across the whole corpus
- [ ] No-tools test passes
- [ ] Cost per 100 documents recorded and **within 2× of the §10 estimate**

**Effort:** ~1.5 days · **Risk:** high (extraction quality is the quality ceiling of everything downstream)

---

### L5 — Entity resolution and graph → 📦 **v0.3.0**
**Goal:** the network, without wrong merges.

**Build**
- Ten node types (Person, Organisation, Project, Meeting, Document, Decision, Action, Risk, Location, Policy).
- Cascade: exact → alias → trigram → embedding grey-band → LLM adjudication with cited evidence → **review queue**.
- Soft merges (`merged_into`) + `entity_merge_log` with evidence. **Reversible.**
- Graph queries via recursive CTE (1–2 hop).
- Exports: JSON, GraphML, Mermaid, Cypher.
- **Shipped artifacts the brief explicitly asks for:** a written graph-schema description and **five example queries**, both in `docs/graph/`.
- `lkb graph export --format json|graphml|mermaid|cypher`, `lkb entities --duplicates`.

**Exit gate 🟢**
- [ ] **Over-merge rate ≤ 0.02** on a labelled pair set — *over-merging is the failure that matters; under-merging is visible and fixable*
- [ ] Every merge reversible; reversal test passes
- [ ] All 5 example queries execute and return sensible results on the fixture corpus
- [ ] Graph exports validate (GraphML against XSD, Mermaid renders, Cypher parses)
- [ ] **Zero edges without a source document reference** — the brief's "do not generate relationships that cannot be supported"

**Effort:** ~1.5 days · **Risk:** high

---

### L6 — Refresh and change report → 📦 **v0.4.0**
**Goal:** the differentiator. Belief revision with preserved history.

**Build**
- Content-hash diffing → `unchanged | modified | new | disappeared`.
- Reconciliation → `new | confirmed | outdated | contradicted | action_completed | owner_changed | question_raised` (the brief's seven update categories).
- Bitemporal invalidation: set `invalid_at` + `invalidated_by` + `reason`. **Never delete.**
- Contradictions → **two active `disputed` assertions**, never merged.
- Change report renderer with the six required sections: previous understanding, new evidence, updated understanding, affected items, changed actions, supporting sources.
- `lkb refresh [--source X]`, `lkb changes [--run ID]`, `lkb history <assertion_id>`.

**Exit gate 🟢**
- [ ] Unchanged documents cost **zero LLM calls** — asserted by a call-counting test
- [ ] "What did we believe on date D?" returns correct historical state
- [ ] All 7 brief update-categories produced on a scripted new document containing each
- [ ] Contradictions surface as two assertions; **a blended single answer is a test failure**
- [ ] Change-report precision ≥ 0.90 against human review of the scripted document
- [ ] Full replay: rebuilding from scratch yields the same final ledger state (determinism check, LLM calls stubbed)

**Effort:** ~1.5 days · **Risk:** high (noise control)

---

### L7 — Projections and exports → 📦 **v0.5.0**
**Goal:** the four deliverables.

**Build**
- **OKF v0.2 serialiser** in one version-stamped module → `index.md`, `log.md`, concept files with `sources`, `generated`, `verified`, `status`, `stale_after`.
- OKF conformance checker (~100 lines — the spec is small and worth owning).
- `Briefing.pdf` via Typst; all 10 Challenge-4 sections including proposed-vs-confirmed decisions and preserved disagreements.
- `Governance_Guide.md` generated from live state.
- `Entities_Relationships.json` + **a flat CSV knowledge-items table** (the brief asks for a DB-importable table).
- Duplicate detection with **first-appearance attribution**.
- Build receipt on every export.
- `lkb export --briefing --okf --graph --governance --all -o ./out`.

**Exit gate 🟢**
- [ ] OKF bundle passes the conformance checker; **opens correctly in Obsidian**
- [ ] Every briefing statement carries a source and date; inferences visually marked
- [ ] Disagreements appear in output as disagreements
- [ ] Governance guide items all trace to real ledger rows — **no generic filler text**
- [ ] `--all` produces one ZIP with `MANIFEST.md` + build receipt
- [ ] Exports reproducible: same store state → byte-identical output (timestamps excluded)

**Effort:** ~1.5 days · **Risk:** medium

---

### L8 — Evals, guardrails, observability → 📦 **v1.0.0**
**Goal:** production posture. Detail in §3–§5.

**Exit gate 🟢**
- [ ] `lkb eval run` reports all deterministic metrics **with no LLM judge and no API key**
- [ ] DeepEval gates wired into CI and blocking
- [ ] promptfoo red-team suite: **zero critical findings**
- [ ] OTel spans validate against the pinned GenAI semconv version; verified end-to-end against Langfuse OTLP
- [ ] Cost and token accounting accurate within 5% of provider-reported usage
- [ ] Budget guard aborts a runaway run at the configured ceiling
- [ ] Docs site published; ≥ 90% public-API docstring coverage
- [ ] **v1.0.0 on PyPI with a stability commitment on `core/`**

**Effort:** ~2 days · **Risk:** medium

---

## 3. Evaluation *(what the library ships)*

**Principle: the headline metrics require no LLM judge and no API key.** Evals that cost money get skipped, and skipped evals stop being true.

### Built in — deterministic, zero dependencies

| Metric | How | Gate |
|---|---|---|
| **Citation validity** | Quote present in cited chunk | **1.00, enforced not measured** |
| **Correct abstention** | Unanswerable subset | ≥ 0.90 |
| Retrieval recall@k / MRR / nDCG | Labelled chunk ids | recall@20 ≥ 0.90 |
| Evidence completeness | Assertions with ≥1 evidence row | 1.00 |
| Schema conformance | Out-of-schema predicates | 0 |
| Over-merge rate | Labelled entity pairs | ≤ 0.02 |
| Change-report precision | Scripted update document | ≥ 0.90 |
| Determinism | Replay → identical ledger | pass |
| Cost / latency per stage | Run records | tracked |

Golden sets are YAML in-repo; `lkb eval run --set golden/sheffield.yaml`. A starter set ships with the package.

### Optional — `pip install ledgerkb[eval]`
- **Ragas** — faithfulness, answer relevancy, context precision/recall, noise sensitivity (LLM-judge; dashboards for chunking/embedding experiments).
- **DeepEval** — pytest-native metric gates for CI.
- **promptfoo** — npm, so it ships as a `promptfoo.yaml` config in the repo rather than a Python dependency. Red-team, 50+ vulnerability classes.

---

## 4. Guardrails *(what the library ships)*

### Tier 1 — always on, deterministic, no dependencies

| Control | Stage | Purpose |
|---|---|---|
| Unicode sanitisation | ingest | Zero-width, bidi override, control chars |
| Hidden-text removal | ingest | colour==background, `display:none`, comments |
| Instruction quarantine | ingest | Injection-shaped spans stored, excluded from prompts, **surfaced in output as a finding** |
| ZIP / path guards | ingest | Traversal, bombs, depth, size |
| **No tools in extraction** | extract | The architectural control. Untrusted text never reaches a privileged context |
| Spotlighting | all prompts | Untrusted content delimited and labelled as data |
| Closed schema | extract | Unknown predicates rejected |
| **Quote verification** | answer | Injected instructions cannot manufacture a surviving citation |
| Budget guards | all | Max tokens / cost / docs per run → abort, never runaway |
| PII redaction hook | ingest | Opt-in callback; no default classifier |

### Tier 2 — a `guard` extra, if it is ever built
**Not shipped.** No `guard` extra exists; this section describes adapters we have
not written. If it lands, the candidates are: **Prompt Guard 2** (injection classifier), **Llama Guard 4** (content classification — note it is *itself* susceptible to injection, so Prompt Guard layers in front), **LLM-Guard**, **NeMo Guardrails** (Colang orchestration).

### Explicitly rejected
**Keyword blocklists.** Standard guardrails drop to ~60% accuracy on benign data because trigger words appear innocently — and council minutes routinely contain *"the committee resolved to ignore the previous recommendation."* On this corpus a blunt filter causes more damage than the attack it prevents.

---

## 5. Observability *(what the library ships)*

**OpenTelemetry-native, vendor-neutral. No observability SDK is a hard dependency.**

### Two layers

**1. Run records — always on, zero config, no collector.**
A `run_record` table in the store logs every stage: inputs, counts, tokens, cost, duration, errors, model+version. `lkb runs`, `lkb trace <run_id>`. Works offline, works in CI, works when nobody has set up a backend.

**2. OTel spans — `pip install ledgerkb[obs]`.**
Emits **GenAI semantic conventions**: spans `chat`, `embeddings`, `execute_tool`; attributes `gen_ai.request.model`, `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.provider.name`. Plus our own `lkb.ingest`, `lkb.chunk`, `lkb.extract`, `lkb.reconcile`, `lkb.export`.

Ship via OTLP to **anything**: Langfuse (native OTLP backend at `/api/public/otel`, HTTP JSON + protobuf), Arize Phoenix, Comet Opik, OpenObserve, Grafana, Datadog. One instrumentation, every backend, no lock-in.

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://cloud.langfuse.com/api/public/otel"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 pk:sk>"
```

**Pin the semconv version.** GenAI conventions are still `Development` — none are Stable, and all `gen_ai.*` attributes moved to a separate repo in June 2026. Treat as a moving target: `LKB_SEMCONV_VERSION` is explicit and upgraded deliberately.

### Cost accounting
Token counts × a configurable price table, per stage and per run. `lkb cost --run <id>` and `lkb cost --workspace`. Provider-reported usage is reconciled against local counts when available.

---

## 6. Provider support

### The architecture
Three Protocols in `core/ports.py` — `ChatModel`, `Embedder`, `Reranker`. `core/` never imports a provider SDK.

### Adapter 1 — OpenAI-compatible *(base install, covers ~95%)*
One adapter speaking `/chat/completions` and `/embeddings`. Configure `base_url` + `api_key` + `model`.

| Category | Works today |
|---|---|
| Aggregators | **OpenRouter**, Vercel AI Gateway, LiteLLM Proxy, Requesty |
| Frontier | OpenAI, Azure OpenAI, Mistral, xAI, DeepSeek |
| Fast inference | Groq, Together, Fireworks, DeepInfra, Cerebras, Nebius, Baseten |
| **Local / self-hosted** | **Ollama**, vLLM, llama.cpp, LM Studio, SGLang, TGI |
| Embeddings servers | HF **TEI**, **Infinity**, Ollama, fastembed (in-process) |

### Adapter 2 — native extras
`[anthropic]` (Messages API + prompt caching), `[bedrock]`, `[vertex]`.

### Adapter 3 — `[litellm]`
Unlocks 100+ providers including non-OpenAI-compatible ones, plus routing, fallbacks and load balancing. One extra, one config line.

### Capability probing
Not every provider does structured output the same way. On first use per `(base_url, model)` the library probes and caches a capability record, then degrades through Instructor's modes:

```
TOOLS  →  JSON_SCHEMA  →  MD_JSON
```

Plus per-provider flags for prompt caching, parallel tool calls, and max context. This is what makes "works with any provider" true rather than aspirational.

### Configuration
```toml
# ledgerkb.toml
[chat]
provider = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
model    = "qwen/qwen3-235b-a22b"
api_key_env = "OPENROUTER_API_KEY"

[chat.cheap]                    # high-volume: context headers, extraction, grading
model = "deepseek/deepseek-v3.2"

[embeddings]
provider = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
model    = "qwen/qwen3-embedding-8b"
dimensions = 1024
```

### Three reference configurations

| Config | Chat | Embeddings | Store | Cost |
|---|---|---|---|---|
| **Fully offline** | Ollama | fastembed (local ONNX) | SQLite | **$0**, no API key |
| **Single key** | OpenRouter | OpenRouter | SQLite | pay-per-token |
| **Production** | AI Gateway / OpenRouter | AI Gateway / TEI | Postgres | pay-per-token |

---

## 7. OpenRouter — yes, first class

Supported with **zero extra code** — it is OpenAI-compatible, so it uses the base adapter.

**It can be your only provider.** OpenRouter added an embeddings endpoint (`POST /api/v1/embeddings`, OpenAI format) serving Qwen3-Embedding-8B, Cohere Embed v1 0.6B and text-embedding-3-small. So chat *and* embeddings come from one key — which is not true of every aggregator.

| | |
|---|---|
| Coverage | **400+ models, 70+ providers** |
| Chat | `/api/v1/chat/completions` — OpenAI format |
| Embeddings | `/api/v1/embeddings` — OpenAI format |
| Fees | No inference markup; **5.5% on credit purchase** (5% crypto, $0.80 min per transaction) |
| BYOK | First **1M requests/month free**, then 5% of equivalent platform cost |
| Free tier | 25+ free models at 50 requests/day |
| Bonus | Provider routing and automatic fallbacks — pairs well with our retry logic |

Implementation notes: send optional `HTTP-Referer` and `X-Title` headers for attribution; some routed models lack strict `json_schema`, so the capability probe (§6) matters more here than with a single-vendor endpoint.

**Caveat to log:** OpenRouter's free tier at 50 requests/day is nowhere near enough for an ingest run — a 100-document corpus makes thousands of calls. Free tier is for trying `lkb ask`, not for compiling a workspace.

---

## 8. Product stages *(begin after L8 🟢)*

The product is a **thin shell over the library**. If a `P` stage needs new domain logic, that is a signal the logic belongs in the library instead.

### P1 — Service layer *(~1 day)*
FastAPI wrapping `ledgerkb`. Endpoints for sources, ingest, ask, entities, changes, export. Job queue via `pgmq`. SSE for token streaming. **Gate:** every endpoint is a thin call into the library — zero domain logic in the API layer, verified by review.

### P2 — Web UI core *(~2 days)*
Next.js 16, AI SDK v6. Ask view with the three-zone answer contract (facts / interpretation / gaps). Documents list. Explore graph view. **Gate:** answer rendering is faithful to the library's `Answer` model — facts and inference visually distinct, gaps always shown.

### P3 — Connectors *(~2 days)*
Upload (Blob client upload, multi-file + ZIP), links (URL / list / sitemap / bounded crawl with preview), Google Drive (**`drive.file` + Picker only**). **Gate:** Drive connector never requests a restricted scope — asserted in test.

### P4 — Change report + export picker *(~1.5 days)*
Refresh UI, change report view, multi-select export picker, download history. **Gate:** the 5-minute demo script in the product spec runs end to end without intervention.

### P5 — Deploy artifacts *(~1 day)*
`docker-compose.yml` (Postgres + api + worker + Ollama), `railway.json`, `vercel.json`, `.env.example`, deploy docs. **Gate:** a stranger following the README deploys successfully in **under 15 minutes** — tested on someone who has not seen the repo.

### P6 — Hardening *(~1.5 days)*
Rerank, Docling tier-1, Langfuse wiring, promptfoo in CI, error states, empty states, accessibility pass. **Gate:** all product-spec states implemented; Lighthouse ≥ 90.

---

## 9. Timeline

| Track | Stages | Effort |
|---|---|---|
| Library → v1.0.0 | L0–L8 | **~11.5 days** |
| Product | P1–P6 | **~9 days** |
| **Total** | | **~20 working days** |

### Hackathon fast path — 2 days

The **only** sanctioned exception to the gating rule. Ship `L0 → L1 → L2 → L3` (a complete, honest Challenge-1 system with real citations and real abstention), then **jump to L6** using a simplified ledger, because the change report is what wins. Skip L4's full extraction, L5's resolution cascade, L7's OKF bundle.

Explicitly accept: no knowledge graph, no OKF export, no entity resolution. Say so out loud rather than implying they exist. A working `lkb ask` with verified citations plus a working change report beats four half-built challenges.

---

## 10. Risk register

| # | Risk | Sev | Stage | Mitigation |
|---|---|---|---|---|
| R1 | Extraction quality caps everything downstream | **High** | L4 | Hand-labelled sample gate; iterate prompts before L5 |
| R2 | Entity over-merging corrupts the graph irreversibly | **High** | L5 | ≤2% gate, soft merges, full audit log, review queue |
| R3 | Change report is noisy and untrusted | **High** | L6 | Collapse confirmations to a count; itemise only material changes |
| R4 | `ts_rank` ≠ BM25 on Postgres | Med | L2 | Isolated behind `KeywordIndex`; eval triggers custom image with `pg_search` |
| R5 | `sqlite-vec` still alpha | Med | L0 | Optional accelerator only; numpy brute force is the default path |
| R6 | Docling ~4GB RAM, no memory release | **High** | L1 | Extra-only, isolated service, tier-0 handles most documents |
| R7 | Provider structured-output inconsistency | Med | L4 | Capability probe + Instructor mode degradation |
| R8 | OKF v0.3 breaks the serialiser | Low | L7 | One version-stamped module |
| R9 | Cost overrun on large corpora | Med | L4 | Budget guards abort; header-threshold lever |
| R10 | AGPL reach via PyMuPDF | Med | L1 | **Default to `pypdfium2` (Apache/BSD)**; `pymupdf4llm` opt-in extra |
| R11 | Scope creep into the product before v1.0 | Med | all | The gating rule exists precisely for this |
| R12 | No real corpus available | **High** | L1 | Build the fixture corpus at L1; connectors are corpus-agnostic |

---

## 11. Decisions locked by this plan

1. **SQLite is the default store.** A library that requires a server is not a library.
2. **Evals that need an API key are not the headline evals.** Citation validity and correct-abstention are deterministic.
3. **Observability is OTel, not a vendor SDK.** One instrumentation, every backend.
4. **Providers sit behind Protocols; OpenAI-compatible is the base adapter.** OpenRouter, Ollama and 20+ others work with a config change, not code.
5. **The product never contains domain logic.** If it needs some, it belongs in the library.
6. **`core/` gets a stability commitment at v1.0.0.** Everything else may move.
