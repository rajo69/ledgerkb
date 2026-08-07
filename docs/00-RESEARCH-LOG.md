# Research Log — Evidence Base for the Intelligence Engine

**Date:** 2026-08-07
**Purpose:** Verify every load-bearing technology choice before writing a line of code. Bias: maximum open source, minimum operational surface, deployable on Railway + Vercel today.

Each finding below is marked with a **verdict**: `ADOPT`, `REJECT`, `DEFER`, or `WATCH`.

---

## 0. The two findings that reshaped the design

### 0.1 OKF v0.2 is real, current, and richer than the PRD assumed — `ADOPT`

Google Cloud's Data Cloud team published the **Open Knowledge Format** on 2026-06-12 (v0.1), now at **v0.2**. It is not a niche curiosity — it is a vendor-neutral formalisation of exactly the Karpathy LLM-wiki pattern the hackathon brief points at.

An OKF bundle is a **directory of markdown files with YAML frontmatter**. `type` is the only always-required key. What matters for us is everything it *optionally* carries:

| OKF field | What our product needs it for |
|---|---|
| `sources: [{id, resource, title, author, last_modified}]` | Citations — Challenge 1's "show where the answer came from" |
| `generated: {by, at}` | Which agent/model produced this page, and when |
| `verified: [{by, at}]` | Trust tier. `human:` prefix ⇒ human-reviewed; agent-only ⇒ machine-confirmed; absent ⇒ unverified |
| `status: draft \| stable \| deprecated` | Lifecycle — supports "decisions that were superseded" |
| `stale_after: YYYY-MM-DD` | **The entire Governance_Guide deliverable falls out of this field** |
| `log.md` (reserved) | Chronological update history — **this is the belief-revision change report** |
| `index.md` (reserved) | Progressive disclosure / the wiki index |
| Actor convention | `human:<id>`, `<producer>/<version>`, `process:<id>` |

Conformance is deliberately permissive: consumers **MUST NOT** reject a bundle for missing optional fields, unknown `type` values, unknown extra keys, or broken cross-links. That means we can extend it with our own keys without breaking interop.

**Consequence for the design:** the four deliverables the user asked for are not four separate systems. `Knowledge_Graph.okf`, `Governance_Guide.md` and most of `Briefing.pdf` are **projections of a single OKF-shaped store**. The `stale_after` + `status` + `verified` triple is the governance product. `log.md` is the change report.

**One correction to note:** OKF is a *directory bundle*, not a single file. `Knowledge_Graph.okf` will therefore be a **ZIP of a conformant bundle** — unzip it and it validates. We state this in the export manifest rather than inventing a non-conformant single-file format.

> Sources: [OKF SPEC.md](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) · [knowledge-catalog repo (Apache-2.0)](https://github.com/GoogleCloudPlatform/knowledge-catalog) · [Google Cloud announcement coverage](https://www.searchenginejournal.com/google-cloud-announces-the-open-knowledge-format/579253/) · [MarkTechPost writeup](https://www.marktechpost.com/2026/06/16/google-cloud-introduces-open-knowledge-format-okf-a-vendor-neutral-markdown-spec-for-giving-ai-agents-curated-context/)

### 0.2 Karpathy's LLM Wiki gives us the *operations*, OKF gives us the *format* — `ADOPT`

The gist defines three layers — `raw/` (immutable, never edited), `wiki/` (LLM-owned, compiled), and a schema file that tells the agent how to behave — and three operations: **ingest**, **query**, **lint**. Plus `index.md` and an append-only `log.md`.

The `lint` operation is the one everyone skips and it is the most valuable: periodic health checks for contradictions, stale claims, orphaned pages, missing cross-references. That is a scheduled job in our system, and it feeds the Governance Guide directly.

> Sources: [Karpathy llm-wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) · [Beyond RAG: the LLM Wiki pattern](https://levelup.gitconnected.com/beyond-rag-how-andrej-karpathys-llm-wiki-pattern-builds-knowledge-that-actually-compounds-31a08528665e)

---

## 1. Ingestion

### 1.1 Google Drive — use `drive.file` + Google Picker, never a restricted scope — `ADOPT`

This is a **product-blocking decision, not a technical preference.**

Drive scopes split into non-sensitive, sensitive, and restricted. `drive.readonly` and `drive` are **restricted** — using them requires Google's restricted-scope verification *plus* a third-party security assessment (CASA), which costs money and takes weeks. That is fatal for a hackathon and painful for a small product.

`https://www.googleapis.com/auth/drive.file` is **non-sensitive**. It grants per-file access to files the user explicitly picks via the **Google Picker API** or that they share with the app. Combined with `setOptOutIncludingGrantedScopes(true)`, the returned token is scoped to `drive.file` alone.

**Decision:** the Drive connector is *picker-first*. The user selects files/folders in the Picker; we get access to exactly those. No verification gauntlet, and it is a better privacy story to put in front of a council.

Refresh tokens: Google only issues one on **first** consent. Set `accessType: "offline"` and `prompt: "consent"`. If using Better Auth, require **≥ 1.2.7** to avoid "Social account already linked" errors when requesting additional scopes on the same provider.

> Sources: [Choose Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) · [Google Picker integration guide](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker) · [Better Auth — Google](https://better-auth.com/docs/authentication/google) · [Google OAuth 2.0 web server flow](https://developers.google.com/identity/protocols/oauth2/web-server)

### 1.2 Link ingestion: Crawl4AI over Firecrawl — `ADOPT`

| | Crawl4AI | Firecrawl |
|---|---|---|
| License | **Apache-2.0** | AGPL-3.0 (self-host core), hosted service closed |
| Model | Self-hosted library | Managed API first |
| Cost | Infrastructure only (~2GB RAM for Chromium) | $19–$399/mo tiers |

AGPL-3.0 on an ingestion component that sits inside our server is exactly the kind of licence friction to avoid when the stated goal is "as much open source as possible" *and* the output may be redistributed. Crawl4AI's Apache-2.0 has no such reach.

> Sources: [Firecrawl vs Crawl4AI comparison](https://www.webfuse.com/compare/firecrawl-vs-crawl4ai) · [Best open-source web crawlers 2026](https://www.firecrawl.dev/blog/best-open-source-web-crawler)

### 1.3 File upload: Vercel Blob client uploads — `ADOPT` (with an OSS escape hatch)

Serverless functions cap request bodies (historically 4.5MB; now up to 100MB on Vercel Functions). Neither is the right path for a multi-file ZIP drop. `@vercel/blob/client` `handleUpload` uploads **browser → Blob directly**, up to **500MB**, with `maximumSizeInBytes` enforced in `onBeforeGenerateToken`, and multipart (`createMultipartUpload` / `uploadPart` / `completeMultipartUpload`) for larger payloads.

Vercel Blob is proprietary. The fully-OSS alternative is **MinIO on Railway** behind the same presigned-PUT interface. We define a `BlobStore` port with two adapters so this is a one-line swap.

> Sources: [Vercel Blob client uploads](https://vercel.com/docs/vercel-blob/client-upload) · [Bypassing the body size limit](https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions)

### 1.4 Document parsing: two-tier, because Docling is a memory hazard — `ADOPT with mitigation`

**Docling** (IBM → Linux Foundation, **MIT**) is the right primary parser: PDF, DOCX, PPTX, XLSX, HTML, images, audio, LaTeX; OCR is *optional and pluggable*, so born-digital PDFs read the text layer directly — faster and more accurate than forcing OCR. Ships Granite-Docling-258M (Apache-2.0).

**But:** the Docling server container uses **~4 GB RAM after startup**, and there are open issues reporting that memory is not released after parsing — periodic container restarts are currently the only guaranteed reclamation. Railway bills RAM at roughly **$10/GB-month**. A naive "Docling in the API container" design is both expensive and unstable.

**Mitigation — tiered parsing:**

1. **Tier 0 (in-process, cheap):** `pymupdf4llm` for born-digital PDFs, `python-docx`/`openpyxl`, `trafilatura`/`selectolax` for HTML, native readers for MD/TXT/CSV/JSON. Covers the large majority of council documents.
2. **Tier 1 (isolated service):** `docling-serve` in its **own Railway service**, concurrency 1, memory cap, restart-after-N-jobs. Invoked only when Tier 0 yields low text density, detects a scanned page, or hits a complex table.
3. **Tier 2 (opt-in):** VLM page-parse via AI Gateway for genuinely hard scans.

Rejected alternatives: **Marker** — GPL-3.0 code plus a RAIL-M weights licence with a commercial revenue threshold; a licensing trap. **MinerU** — best raw accuracy (English text error 0.061) but heaviest, and its edge is CJK, which we do not need for Sheffield.

> Sources: [Docling vs Marker vs MinerU benchmark](https://adityamangal98.medium.com/docling-vs-marker-vs-mineru-the-ultimate-open-source-pdf-parser-benchmark-2026-which-is-best-a36ecbb6c6b1) · [docling-serve memory issue #474](https://github.com/docling-project/docling-serve/issues/474) · [docling-serve memory issue #366](https://github.com/docling-project/docling-serve/issues/366) · [Docker deployment notes](https://deepwiki.com/docling-project/docling/10.1-docker-deployment)

---

## 2. Chunking and retrieval

### 2.1 Contextual Retrieval is the highest-ROI technique available — `ADOPT`

Anthropic's method: before embedding, prepend a short (**50–100 token**) LLM-generated context sentence to each chunk describing where it came from and what it is about. Do it for the **embedding index and the BM25/FTS index**. Measured: contextual embeddings + contextual BM25 + reranking cut top-20 retrieval failure from **5.7% → 1.9% (-67%)**.

This is precisely what the PRD called "situated contextual summaries" — the idea was sound, the attribution was missing. Using only one of the two indexes leaves accuracy on the table.

Cost control: generate the context header with a cheap model, and cache the parent document in the prompt so the per-chunk marginal cost is small.

> Sources: [Anthropic — Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) · [Contextual embeddings + hybrid search](https://www.freecodecamp.org/news/how-contextual-embeddings-and-hybrid-search-fix-retrieval-failures/)

### 2.2 Chunker: Chonkie — `ADOPT`

MIT, ~15MB install vs 80–170MB for framework-bundled chunkers, up to 33× faster token chunking, and ships `RecursiveChunker`, `SentenceChunker`, `SemanticChunker`, `SDPMChunker`, `LateChunker`, `NeuralChunker`.

**Important nuance:** the brief asks for "meaningful sections rather than arbitrary fixed-size chunks". For council documents the *strongest* signal is structural, not embedding-based — agenda item numbers, decision headings, minute numbering. So: **structure-first splitting** (Docling/Tier-0 gives us a heading tree), with Chonkie's semantic chunker only as the within-section splitter when a section overruns the token budget. Semantic-similarity breakpoints are the fallback, not the primary strategy.

> Sources: [Chonkie open source docs](https://docs.chonkie.ai/common/open-source) · [Chonkie on Haystack](https://haystack.deepset.ai/integrations/chonkie)

### 2.3 Vector store: pgvector, not a dedicated vector DB — `ADOPT`

pgvector is the right answer **under ~5M vectors when the vectors are metadata, not the product**. That is us: a workspace of council documents is tens of thousands of chunks, not millions. Consensus guidance is explicit that pgvector wins here and Qdrant's advantage appears with heavy metadata filtering at scale.

**pgvector 0.8 matters specifically for us:** it adds **iterative index scans** (`hnsw.iterative_scan` = `strict_order` | `relaxed_order`, bounded by `hnsw.max_scan_tuples`, default 20,000). Without this, an HNSW scan with default `ef_search = 40` filtered to 10% of rows returns ~4 usable rows. We filter *hard* — by workspace, by source, by document version, by date. Iterative scan is what makes filtered retrieval correct rather than silently thin. Also `halfvec` for high-dimension models.

> Sources: [pgvector 0.8.0 release](https://www.postgresql.org/about/news/pgvector-080-released-2952) · [pgvector 0.8 on Nile](https://www.thenile.dev/blog/pgvector-080) · [Vector DB comparison 2026](https://4xxi.com/articles/vector-database-comparison/) · [Crunchy Data — hybrid vector search](https://www.crunchydata.com/blog/hybrid-vector-search)

### 2.4 Keyword side: Postgres FTS + RRF now; BM25 extension later — `ADOPT` / `DEFER`

True BM25 in Postgres exists — **ParadeDB `pg_search`**, TigerData **`pg_textsearch`**, **VectorChord-bm25** — and all support hybrid. But **none of them are in Railway's Postgres image** (see §4.1), so adopting one means maintaining a custom Postgres Docker image on day one.

At our corpus size, `tsvector` + `ts_rank_cd` fused with dense results via **Reciprocal Rank Fusion** is well within acceptable quality, and RRF is what does the heavy lifting anyway. We isolate ranking behind a `KeywordIndex` port so swapping in `pg_search` later is contained.

**Honest caveat to record:** `ts_rank` is *not* BM25 — no document-length normalisation, no saturating term frequency. If eval shows keyword recall is the bottleneck, that is the trigger to build the custom image.

> Sources: [ParadeDB — Hybrid Search in PostgreSQL: The Missing Manual](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual) · [pg_textsearch / true BM25](https://www.tigerdata.com/blog/introducing-pg_textsearch-true-bm25-ranking-hybrid-retrieval-postgres) · [Hybrid search: BM25 + pgvector with RRF](https://dev.to/gabrielanhaia/hybrid-search-in-100-lines-bm25-pgvector-with-rrf-merge-58cn)

### 2.5 Embeddings + reranker: abstract the port, default to the gateway — `ADOPT`

**BGE-M3** (MIT) is the most versatile open embedder: 100+ languages, dense + sparse + ColBERT multi-vector from one model. **Qwen3-Embedding-4B/8B** tops MMTEB. Rerankers: `bge-reranker-v2-m3`, `Qwen3-Reranker`.

Serving them ourselves means **TEI** (HF Text Embeddings Inference — batching, Flash Attention, OpenAI-compatible) or Ollama. But BGE-M3 wants ~8GB VRAM on GPU, and CPU-only serving on Railway means paying ~$10/GB-month for RAM that sits idle between refreshes — a bad trade for a **manual-refresh, bursty** workload.

**Decision:** define an `Embedder` / `Reranker` port with two adapters.
- **Default (hackathon + low volume):** Vercel AI Gateway's OpenAI-compatible `/embeddings` endpoint — one key, pass-through pricing, no idle cost.
- **Fully-OSS path (documented, one env var):** TEI serving BGE-M3 + bge-reranker-v2-m3 on Railway or any GPU box.

This keeps "maximum open source" as a *reachable configuration* rather than an expensive default. The models are open-weight either way; only the hosting differs. **The embedding model and dimension must be fixed before first index build** — changing it later forces a full re-index.

> Sources: [Open-source embedding models guide](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models) · [HF Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference) · [Vercel AI Gateway embeddings](https://vercel.com/docs/ai-gateway/modalities/embeddings)

### 2.6 Corrective RAG — adopt the loop, **reject the default web-search branch** — `ADOPT with a change`

CRAG grades retrieval and routes: `Correct` → refine, `Incorrect` → discard + re-search (canonically via web search), `Ambiguous` → combine.

The PRD copied this verbatim, including "trigger external search via Serper/Google Search API" on `Incorrect`. **That is wrong for this product.** The brief's success criterion is answers traceable to *the supplied documents*, and the system must "say when there is insufficient evidence". Silently reaching for the open web to fill a gap converts an honest abstention into an unciteable answer — it fails the exact thing the challenge is grading.

**Our routing:**

| Grade | Action |
|---|---|
| Correct | Refine / decompose-then-recompose, generate with citations |
| Ambiguous | Expand evidence via the **knowledge graph** (entity neighbourhood), re-rank, retry once |
| Incorrect | Rewrite query → retry once → **abstain**: "insufficient evidence", name the entities/date-range that had no coverage, and suggest which document would answer it |

Web search stays available but **off by default**, and any external result is rendered in a visually separate "outside the corpus" block that can never be cited as a corpus fact.

> Sources: [CRAG implementation with LangGraph](https://www.datacamp.com/tutorial/corrective-rag-crag) · [Corrective RAG workflow](https://www.meilisearch.com/blog/corrective-rag) · [Agentic RAG production guide 2026](https://www.marsdevs.com/guides/agentic-rag-2026-guide)

---

## 3. Knowledge graph

### 3.1 Kùzu is dead — do not use it — `REJECT`

Kùzu Inc. was **acquired by Apple in October 2025**; the GitHub repo is archived and the website is down. Existing releases still run; there is no development. Community forks (LadybugDB, Kineviz's `bighorn`) are early-stage with no funding or roadmap.

Any 2024–2025-era tutorial recommending Kùzu as *the* embedded graph DB — and there are many — is now stale advice. Worth flagging loudly because Graphiti's docs still list Kùzu as a backend.

> Sources: [The Register — KuzuDB abandoned](https://www.theregister.com/2025/10/14/kuzudb_abandoned/) · [Kuzu's legacy and the embedded graph landscape](https://gdotv.com/blog/kuzu-legacy-embedded-graph-database-landscape/)

### 3.2 No graph database at all — plain relational tables — `ADOPT`

Options considered:

| Option | Verdict |
|---|---|
| Neo4j Community | GPL-licensed, separate server, second thing to operate and secure |
| Apache AGE | Apache-2.0, graph inside Postgres — **but not in Railway's image**, and slower on deep variable-length traversals |
| Kùzu | Dead (§3.1) |
| **Plain `node` / `edge` tables + recursive CTEs** | **Chosen** |

The queries the brief actually asks for are **1–2 hops**: "which people are responsible for actions relating to project X", "which risks affect more than one project", "which decisions superseded earlier decisions". None of them need a traversal engine. A real migration case study moved *off* Neo4j to AGE precisely because the graph queries were straightforward and the advanced features went unused — we are further down that curve still.

Relational tables also mean the graph shares transactions with the documents and assertions that justify it, so an export can never show an edge whose evidence has been rolled back. We render to Mermaid / JSON / GraphML / Cypher on export, so "we have a knowledge graph" remains fully true.

> Sources: [Apache AGE vs Neo4j](https://www.puppygraph.com/learn/apache-age-vs-neo4j) · [Migrating graph operations to Apache AGE (Trendyol)](https://medium.com/trendyol-tech/migrating-graph-operations-to-apache-age-from-writes-to-reads-3b8334628e1c)

### 3.3 GraphRAG frameworks: borrow the model, skip the dependency — `REJECT` (framework) / `ADOPT` (bitemporal pattern)

- **Microsoft GraphRAG** — LLM calls at every stage; reported ~$40–60 in API cost for a 10,000-word document, ~$33K to index a large corpus. Disqualifying.
- **LightRAG** (MIT) — 70–90% of GraphRAG quality at ~1/100th cost, ~$0.50 to index 500 pages. Genuinely good. **But**: storage backend and embedding config are locked before first upload with no supported migration path, and the server component has had a JWT algorithm-confusion vulnerability and a hardcoded JWT signing secret allowing auth bypass. Do not run its server.
- **Graphiti** (Apache-2.0) — built for *temporal agent memory*, not document Q&A, and its backends are Neo4j/FalkorDB/(dead Kùzu).

**What we take instead is Graphiti's bitemporal invalidation model**, which is the single most important idea for the Shared Final Challenge:

> Track **valid time** (when the fact was true in the world) separately from **ingestion/transaction time** (when the system learned it). When new information contradicts an existing fact, **write an `invalid_at` timestamp — never delete**. Distinguish *superseded* from *forgotten* via `status` + `reason`.

That single pattern lets the system answer "what did we believe on 12 June, and what changed?" — which is precisely the change report the final challenge demands, and which a latest-state snapshot structurally cannot produce.

> Sources: [Graph RAG in production 2026](https://www.paperclipped.de/en/blog/graph-rag-production/) · [LightRAG repo](https://github.com/hkuds/lightrag) · [LightRAG security advisories](https://github.com/HKUDS/LightRAG/security) · [Temporal knowledge graphs](https://www.getzep.com/ai-agents/temporal-knowledge-graph/) · [TOKI: bitemporal operator algebra for contradiction resolution](https://arxiv.org/pdf/2606.06240)

### 3.4 Entity resolution: cascade, and log every merge — `ADOPT`

Entity resolution is documented as *the stage knowledge-graph pipelines do worst* — the same entity scatters into duplicate surface forms. The brief anticipates this from both sides: "merge entities that refer to the same real-world person/org/project" **and** "avoid merging similarly named entities without sufficient evidence".

Standard tooling: **Splink** (probabilistic Fellegi–Sunter; ABS is using it for 2026 Census QA), **Zingg**, **dedupe**. Recommended scale guidance: <1M records → dedupe-class tools; 1–100M → Splink/Zingg. We are at thousands.

**Our cascade — Rules → Vectors → LLM**, which is the documented cost/latency/accuracy balance:
1. **Block** on normalised name / type / acronym expansion (cheap, high precision).
2. **Score** with `pg_trgm` similarity + embedding cosine on entity context.
3. **Adjudicate** ambiguous pairs (score in the grey band only) with an LLM that must cite the evidence spans supporting the merge.
4. **Record** every decision in `entity_merge_log` with method, score, evidence and reversibility. Merges are **reversible**; nothing is destroyed.

Default is *conservative*: unresolved duplicates are shown to the user as "possible duplicates" rather than silently merged. Two councillors named J. Smith staying separate is a better failure than merging them.

> Sources: [Splink](https://moj-analytical-services.github.io/splink/index.html) · [Best OSS entity resolution libraries](https://tilores.io/content/best-open-source-entity-resolution-and-record-linkage-libraries-splink-zingg-dedupe-and-when-to-move-beyond-them/) · [Entity resolution at scale for KG construction](https://medium.com/@shereshevsky/entity-resolution-at-scale-deduplication-strategies-for-knowledge-graph-construction-7499a60a97c3)

---

## 4. Platform

### 4.1 Railway's Postgres image is the whole backend — `ADOPT`

Railway's template ships **PostgreSQL 18** with extensions **pre-compiled into the image**, enabled at deploy time via a single `EXTENSIONS` environment variable; an entrypoint validates the selection, configures `shared_preload_libraries`, and runs `CREATE EXTENSION IF NOT EXISTS` on boot.

Confirmed available: **pgvector, pgmq, pg_cron, pg_trgm, pgcrypto, pg_partman, PostGIS** (11 total; 7 named in the docs). `PGDATA` sits on a persistent volume, so indexes survive redeploys.

**Not available: Apache AGE, ParadeDB `pg_search`.** This is what settles §2.4 and §3.2.

**Consequence — one datastore does five jobs:**

| Job | Mechanism |
|---|---|
| Relational store | Postgres |
| Vector index | `pgvector` |
| Keyword index | `tsvector` + `pg_trgm` |
| Job queue | **`pgmq`** — no Redis, no RabbitMQ, no Celery broker |
| Scheduler | **`pg_cron`** — staleness sweeps and lint runs, in-database |

That removes Redis and a broker from the stack entirely. Every ingest job is a row in a transaction alongside the data it produces — no dual-write between queue and database, which is the classic source of half-ingested documents.

> Sources: [Railway PostgreSQL Extensions template](https://railway.com/deploy/postgresql-extensions) · [Railway RAG pipeline with pgvector guide](https://docs.railway.com/guides/rag-pipeline-pgvector) · [Railway blog — hosting Postgres with pgvector](https://blog.railway.com/p/hosting-postgres-with-pgvector)

### 4.2 Queue: pgmq over Celery/arq — `ADOPT`

Postgres-backed queues (pgmq, PgQueuer, Procrastinate) use `LISTEN/NOTIFY` + `FOR UPDATE SKIP LOCKED` and give **full ACID guarantees with no separate broker**. Celery is the mature default but is documented as awkward with async FastAPI; arq is async-native but adds Redis.

Since `pgmq` is already in the image, adding Redis would mean paying for and operating a second stateful service to gain nothing.

> Sources: [PgQueuer](https://github.com/janbjorge/pgqueuer) · [Background jobs & task queue architecture 2026](https://appscale.blog/en/blog/background-jobs-task-queue-architecture-bullmq-celery-sqs-2026)

### 4.3 Railway cost reality — `NOTE`

Hobby is **$5/month, which is a minimum spend, not a cap**: CPU, memory, volumes and egress bill on top. RAM is **~$0.00000386/GB-second ≈ $10/GB-month**, billed per second for what the app *holds*.

Two direct design consequences:
1. A permanently-resident 4GB Docling service is ~$40/month of RAM alone. Scale-to-zero or on-demand start for the parser service.
2. A permanently-resident CPU embedding server is similarly wasteful for a manual-refresh workload. This is the concrete reason §2.5 defaults to the gateway.

> Sources: [Railway pricing 2026](https://www.srvrlss.io/provider/railway/) · [Railway pricing calculator](https://makerkit.dev/pricing-calculator/railway) · [Railway hosting review — production limits](https://diyai.io/ai-tools/hosting/reviews/railway-hosting-review/)

### 4.4 Split: Vercel front, Railway back — `ADOPT`

The documented 2026 pattern is Next.js on Vercel, FastAPI + Postgres + workers on Railway. Railway also publishes a Next.js + FastAPI + Postgres + Redis + worker monorepo starter if we ever want everything in one place.

We split because the workloads genuinely differ: the UI is edge-cached and token-streaming; ingestion is long-running, memory-hungry, and stateful. Note `NEXT_PUBLIC_*` is inlined into the browser bundle at build time — never a secret — and FastAPI CORS must be pinned to exact origins.

> Sources: [Railway Next.js + FastAPI starter](https://railway.com/deploy/nextjs-fastapi-full-stack-starter) · [Deploying Next.js + FastAPI + Postgres](https://www.vintasoftware.com/blog/next-js-fastapi-template)

### 4.5 Model access: Vercel AI Gateway — `ADOPT`

One OpenAI-compatible endpoint, one key, **275+ models across 25+ providers**, `provider/model` strings, **pass-through pricing at provider list rates with zero markup**, $5/month free tier, BYOK supported, plus an `/embeddings` endpoint.

Critically for the open-source goal: open-weight models — **Qwen, DeepSeek, Kimi, GPT-OSS, Gemma** — are first-class, and open-weight traffic reached **29% of gateway volume by June 2026**. So "use open models" and "don't operate GPUs" are compatible. On uncached DeepSeek pricing the gateway is reported *cheaper* than DeepSeek direct ($0.09/$0.18 per M vs $0.14/$0.28).

Model routing policy: cheap open-weight model for the high-volume mechanical work (chunk context headers, entity extraction, grading), a stronger model for synthesis and contradiction adjudication.

> Sources: [AI Gateway Production Index, July 2026](https://vercel.com/blog/ai-gateway-production-index-july-2026) · [AI Gateway deep dive](https://www.rabinarayanpatra.com/blogs/vercel-ai-gateway-deep-dive) · [AI Gateway embeddings docs](https://vercel.com/docs/ai-gateway/modalities/embeddings)

---

## 5. Quality, safety, observability

### 5.1 Structured extraction: Instructor default, BAML if TS/Python must share schemas — `ADOPT`

**Instructor** — Pydantic-based, works across every provider, 11K+ stars, near-zero learning curve, the safest default. **BAML** — schema-first DSL with generated clients for Python *and* TypeScript and a schema-aligned parser that tolerates messy output; attractive because our extraction schema must be shared with a Next.js frontend. **Outlines** — FSM token-masking guarantees schema compliance with zero retries; the right choice only if we self-host models.

Decision: **Instructor** now; revisit BAML if schema drift between the Python worker and the TS frontend becomes a real problem.

> Sources: [Top 5 structured output libraries 2026](https://dev.to/thedailyagent/top-5-structured-output-libraries-for-llms-in-2026-48g0) · [BAML vs Instructor](https://www.glukhov.org/llm-performance/benchmarks/baml-vs-instruct-for-structured-output-llm-in-python/)

### 5.2 Prompt injection is *the* live threat here — `ADOPT` (lightweight, targeted)

We ingest untrusted PDFs and arbitrary web pages and feed them to an LLM. That is textbook **indirect prompt injection — LLM01, the most widely exploited vulnerability in production deployments**. Attackers embed instructions in documents using invisible text (white-on-white CSS, zero-width characters) that hijack the model when retrieved. A poisoned knowledge-base document compromises **every user whose query retrieves it**, and organisations routinely make the mistake of treating their own knowledge base as trusted.

The PRD's answer was a three-product guardrail stack (NeMo Guardrails + Guardrails AI + Llama Guard 3). That is aimed mostly at *user-input* safety and is heavy for what we need. Our threat is **document content**, so the controls belong at ingest and at the tool boundary:

1. **Sanitise at ingest** — strip zero-width/bidi control characters, drop text whose rendered colour matches its background, strip HTML comments and `display:none` content, normalise Unicode.
2. **Quarantine, don't discard** — flag instruction-shaped spans ("ignore previous", "you are now…"), store them, exclude from prompts, and surface them in the UI as *"this document contains text that looks like an injection attempt"*. For a public-records product that finding is itself a feature.
3. **Extraction runs with no tools.** The high-volume LLM calls that touch untrusted text have zero tool access and zero privileges. This is the architectural control — the rest is defence in depth.
4. **Spotlighting** — untrusted content is always delimited and labelled as data.
5. **Verify citations mechanically** — see §5.3.
6. **`promptfoo`** in CI for adversarial regression (50+ vulnerability types, YAML in-repo).

Deliberately noted: **over-defence is a real cost.** Standard guardrails drop to ~60% accuracy on benign data because trigger words like "ignore" appear innocently — and council minutes are full of phrases like "the committee resolved to ignore the previous recommendation". Blunt keyword filters would be actively harmful on this corpus.

> Sources: [OWASP LLM Top 10 2026](https://repello.ai/blog/owasp-llm-top-10-2026) · [Layered security framework against prompt injection in RAG chatbots](https://arxiv.org/pdf/2606.19660) · [Hidden-in-Plain-Text: indirect prompt injection in RAG](https://arxiv.org/pdf/2601.10923) · [promptfoo OWASP LLM Top 10](https://www.promptfoo.dev/docs/red-team/owasp-llm-top-10/)

### 5.3 Grounding: verify quotes in code, not with a model — `ADOPT` (own idea, cheap and strong)

Every generated claim must carry `chunk_id` + a verbatim quote. Before the answer is returned, a **deterministic check** confirms the quote actually appears in that chunk (normalised exact match, then fuzzy ≥ threshold). Claims that fail are demoted from "fact" to "unsupported" or dropped.

This costs microseconds, needs no judge model, and directly satisfies the brief's hardest requirements: cite the passages used, separate facts from inference, and never invent. LLM-judge faithfulness scoring (§5.4) then measures what remains, rather than being the only line of defence.

### 5.4 Evaluation: Ragas + DeepEval + promptfoo — `ADOPT`

The documented division of labour, which matches our needs exactly:

| Tool | Role |
|---|---|
| **Ragas** | Deepest RAG-specific metric library — faithfulness, answer relevancy, context precision/recall, context utilisation, noise sensitivity. Dashboards for chunking/embedding/retriever experiments. |
| **DeepEval** | pytest-native metric **gates in CI**. |
| **promptfoo** | CLI red-teaming, 50+ vulnerability types, configs in-repo. |

The RAG Triad (context relevance, faithfulness, answer relevance) from the PRD is real and is Ragas's core. Mandatory addition: a **golden set including unanswerable questions**, because the brief grades abstention explicitly. Our headline metric is not faithfulness — it is **correct-abstention rate**, and Ragas will not give us that for free.

> Sources: [Top 5 LLM evaluation frameworks 2026](https://deepeval.com/blog/top-5-llm-evaluation-frameworks) · [promptfoo vs DeepEval vs RAGAS](https://genai.qa/blog/promptfoo-vs-deepeval-vs-ragas/) · [DeepEval vs Ragas](https://qaskills.sh/blog/deepeval-vs-ragas-rag-evaluation-2026)

### 5.5 Observability: Langfuse (hosted), OTel GenAI as the wire format — `ADOPT` / `WATCH`

**Langfuse** — MIT core, ~21K stars, most widely adopted OSS LLM observability tool. **Acquired by ClickHouse in January 2026**; MIT core, self-hosting and cloud endpoints unchanged. Self-hosting it means web + worker + Postgres + **ClickHouse** + Redis + S3 — heavier than our entire application. **Use Langfuse Cloud during the build; self-host only if data residency demands it.**

Alternatives if that changes: **Opik** (Apache-2.0, full server) and **OpenObserve** (AGPL-3.0, single binary, stores LLM spans next to infra telemetry, plain OTel with no proprietary SDK). **Arize Phoenix is Elastic License 2.0 — source-available, not OSI-approved** — so it fails an "open source only" bar; worth knowing before someone suggests it.

**OTel GenAI conventions: still `Development`, not stable.** As of 2026-07-17 no GenAI span, event, metric or attribute is marked Stable, and as of the v1.42.0 release (2026-06-12) all `gen_ai.*` attributes moved *out* of the main semconv repo into a dedicated GenAI repo — an organisational split for faster cadence, **not** a graduation to stable. There is no public stabilisation timeline.

So: emit `gen_ai.*` attributes (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, spans `chat` / `execute_tool` / `invoke_agent`) because they are the direction of travel and vendors already consume them — but **pin the semconv version and expect churn**. The PRD's presentation of these as a settled standard was optimistic.

> Sources: [State of the OTel GenAI semantic conventions, July 2026](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/) · [Langfuse vs Arize Phoenix — license & self-hosting](https://www.agenticwire.news/article/langfuse-vs-arize-phoenix) · [Langfuse alternatives 2026](https://openobserve.ai/blog/langfuse-alternatives/)

### 5.6 PDF generation: Typst — `ADOPT`

`Briefing.pdf` needs to look like a real briefing document. Three engines exist: LaTeX (Pandoc + TeX), Chromium (headless print), and **Typst**.

Typst is a single Rust binary of a few tens of MB, versus multiple gigabytes across hundreds of files for a TeX Live install, and compiles orders of magnitude faster. In a container that we may cold-start, that difference is decisive. Pandoc can drive Typst as its PDF engine, so we keep Pandoc's markdown handling if we want it. **WeasyPrint** remains the alternative if we want to reuse the web design system's CSS directly for pixel-matching between screen and PDF.

Decision: **Typst**, with the briefing template as a `.typ` file under version control.

> Sources: [Typst with Pandoc as a LaTeX alternative](https://slhck.info/software/2025/10/25/typst-pdf-generation-xelatex-alternative.html) · [Using Pandoc and Typst to produce PDFs](https://imaginarytext.ca/posts/2024/pandoc-typst-tutorial/)

---

## 6. Corpus note

Sheffield City Council publishes an open data portal (ArcGIS Hub) covering FOI data, INSPIRE/spatial releases, city statistics and reports, plus a Guide to Information under the ICO Model Publication Scheme, and is required by the Local Government Acts 1972/1985/2000 to keep records of council meetings. A dedicated ModernGov committee-minutes API was **not** confirmed in this research — treat committee minutes as HTML/PDF pages to crawl, not an API to call.

**This matters for the demo:** the folder currently contains no corpus. Build against a stand-in set (council meeting minutes, project reports, decision notices) and design the connectors so the real supplied folder drops in unchanged.

> Sources: [Sheffield City Council Open Data](https://sheffield-city-council-open-data-sheffieldcc.hub.arcgis.com/) · [Access to information — Sheffield City Council](https://www.sheffield.gov.uk/your-city-council/access-to-information) · [data.gov.uk — Sheffield City Council](https://ckan.publishing.service.gov.uk/dataset/?organization=sheffield-city-council)

---

## 7. Summary of verdicts

| Layer | Choice | Licence | Why |
|---|---|---|---|
| Parsing (fast) | pymupdf4llm, trafilatura, python-docx | AGPL¹/Apache/MIT | Cheap, in-process, covers most docs |
| Parsing (hard) | Docling (isolated service) | MIT | Best-in-class; RAM-hazardous, so isolated |
| Crawling | Crawl4AI | Apache-2.0 | Avoids Firecrawl's AGPL |
| Chunking | Structure-first + Chonkie | MIT | Headings beat cosine breakpoints on minutes |
| Context | Anthropic Contextual Retrieval | technique | −67% retrieval failure |
| Store | Postgres 18 + pgvector + pgmq + pg_cron + pg_trgm | OSS | One datastore does five jobs |
| Keyword | tsvector + RRF (pg_search later) | OSS | Not in Railway image yet |
| Embeddings | BGE-M3 / Qwen3 via port | MIT / Apache | Gateway by default, TEI for full OSS |
| Graph | Relational tables + recursive CTE | n/a | 1–2 hop queries; Kùzu dead, AGE unavailable |
| Temporal | Bitemporal invalidation (`invalid_at`) | pattern | Powers the change report |
| Entity res. | Rules → vectors → LLM, fully logged | pattern | Conservative by default, reversible |
| Extraction | Instructor | MIT | Safest default |
| Retrieval loop | CRAG **minus** default web search | pattern | Abstention is the graded behaviour |
| Grounding | Deterministic quote verification | own | Free, strong, no judge model |
| Evals | Ragas + DeepEval + promptfoo | OSS | Dashboards + CI gates + red team |
| Tracing | Langfuse Cloud, OTel GenAI attrs | MIT | Self-host is heavier than the app |
| PDF | Typst | Apache-2.0 | Single binary vs 4GB TeX |
| Host | Vercel (UI) + Railway (API/worker/PG) | — | Matches workload shapes |
| Models | AI Gateway, open-weight default | — | Open models without operating GPUs |

¹ `pymupdf4llm` is AGPL-3.0 (PyMuPDF). It runs as an isolated ingest step; if AGPL reach is unacceptable, substitute `pypdfium2` (Apache/BSD) — flagged in §Open Questions of the architecture doc.

---

## 8. What I could not verify

Recorded honestly so no one treats these as settled:

1. **Docling's exact steady-state RAM on our workload.** ~4GB and a non-releasing pattern come from maintainer-tracked GitHub issues, not our own measurement. **Action:** measure on a 50-document sample before sizing the service.
2. **The full 11-extension list in Railway's Postgres image.** Seven are named in the docs; four are not. **Action:** `SELECT * FROM pg_available_extensions;` after first deploy, before committing to §2.4.
3. **Whether the OKF repo ships a validator/CLI.** The repo is Apache-2.0 with `okf/`, `samples/`, `toolbox/` directories, but tooling was not enumerated. **Action:** read `okf/` directly; if no validator exists, write a ~100-line conformance checker — it is a small spec and worth owning.
4. **Sheffield committee-minutes API.** Assume crawling, not an API, until proven otherwise.
5. **OKF v0.2 stability.** The spec moved 0.1 → 0.2 in under two months with breaking changes (`timestamp` → `generated{by,at}`; body `# Citations` → `sources` frontmatter). **Action:** keep OKF emission in one serialiser module, version-stamped, so a v0.3 is a single-file change.
