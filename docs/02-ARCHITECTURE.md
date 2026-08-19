# Architecture: The Intelligence Engine

**Version:** 1.0 · **Date:** 2026-08-07
**Companion docs:** [`00-RESEARCH-LOG.md`](./00-RESEARCH-LOG.md) (why these choices) · [`01-PRODUCT-SPEC.md`](./01-PRODUCT-SPEC.md) (what we're building)

---

## 1. The organising idea

> **One append-only ledger of evidence-bearing assertions. Everything else is a projection of it.**

The RAG index, the knowledge graph, the OKF wiki, the briefing PDF and the change report are not four subsystems. They are **five views over one table**.

The PRD proposed a "parallel tri-engine" writing three semantic formats concurrently. That is three sources of truth that will drift: the vector store says one thing, the graph says another, the wiki a third, and nothing reconciles them. Replacing it with a ledger plus projections costs one rebuild step and buys consistency by construction.

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
    retrieval      graph          OKF wiki      exports      change report
    (chunks +      (nodes/        (markdown     (pdf/json/    (ledger diff
     vectors)       edges)         bundle)       graphml)      across runs)
```

**The consequences fall out for free:**
- Belief revision = setting `invalid_at`, never deleting → history is queryable.
- The change report = a diff of the ledger between two ingest runs.
- Governance = a query over `stale_after`, `confidence`, source count and owner-nullity.
- Citations cannot drift, because every projection carries the same `chunk_id`.

---

## 2. System topology

```
┌─ VERCEL ─────────────────────┐        ┌─ RAILWAY ────────────────────────────┐
│                              │        │                                      │
│  Next.js 16 (App Router)     │        │  api          FastAPI                │
│   · UI, token streaming      │◄──────►│                │                     │
│   · Better Auth (Google)     │  HTTPS │                ▼                     │
│   · Google Picker            │        │  worker       pgmq consumer          │
│   · Blob client uploads      │        │   · ingest · extract · export        │
│                              │        │                │                     │
│  AI SDK v6 ──► AI Gateway    │        │                ▼                     │
│                              │        │  parser       docling-serve          │
│  Vercel Blob (raw files)     │        │   (isolated, memory-capped)          │
└──────────────────────────────┘        │                │                     │
                                        │                ▼                     │
                                        │  postgres     PG 18                  │
                                        │   pgvector · pgmq · pg_cron          │
                                        │   pg_trgm · pgcrypto                 │
                                        └──────────────────────────────────────┘
```

**Why this split.** The UI is token-streaming, edge-cached and iterated on constantly: Vercel. Ingestion is long-running, memory-hungry, stateful and bursty: Railway. Forcing either onto the other's platform means fighting it.

**Service sizing** (revise after measurement, research §8.1):

| Service | Memory | Scaling | Notes |
|---|---|---|---|
| `api` | 512MB–1GB | Always on | Thin; delegates to queue |
| `worker` | 1–2GB | 1–2 replicas | Concurrency from `WORKER_CONCURRENCY` |
| `parser` | 4GB cap | **Scale to zero / restart after N jobs** | Docling leaks; see research §1.4 |
| `postgres` | 1–2GB | Always on, volume-backed | `EXTENSIONS=pgvector,pgmq,pg_cron,pg_trgm,pgcrypto` |

The `parser` service is separated for exactly one reason: Docling's ~4GB footprint with no memory release would otherwise take down the API. Isolated, concurrency 1, restart-after-N, it is merely expensive-when-used rather than destabilising.

---

## 3. Data model

Abridged to the load-bearing tables. Every table carries `workspace_id`.

### 3.1 Sources and documents

```sql
create table source (
  id              uuid primary key default gen_random_uuid(),
  workspace_id    uuid not null references workspace(id) on delete cascade,
  kind            text not null check (kind in ('gdrive','link','upload')),
  label           text not null,
  config          jsonb not null default '{}',   -- folder ids, urls, crawl depth
  connector_state jsonb not null default '{}',   -- page tokens, etags, cursors
  last_refreshed_at timestamptz,
  status          text not null default 'ready',
  created_at      timestamptz not null default now()
);

create table document (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null,
  source_id     uuid not null references source(id) on delete cascade,
  external_id   text not null,             -- drive file id / url / zip path
  uri           text,
  title         text,
  doc_type      text,                      -- minutes | report | register | policy | email
  meeting_or_project text,
  published_at  date,
  authors       text[],
  status        text not null default 'active',  -- active | unavailable | failed
  current_version_id uuid,
  unique (source_id, external_id)
);

-- immutable. a new content hash is a new row, never an update.
create table document_version (
  id             uuid primary key default gen_random_uuid(),
  document_id    uuid not null references document(id) on delete cascade,
  version_no     int  not null,
  content_hash   text not null,            -- sha256 of raw bytes
  text_hash      text not null,            -- sha256 of extracted text
  blob_uri       text,
  mime           text,
  bytes          bigint,
  page_count     int,
  parser         text,                     -- pymupdf4llm | docling | trafilatura
  parse_quality  real,                     -- 0..1 text-density heuristic
  ingested_at    timestamptz not null default now(),
  superseded_by  uuid references document_version(id),
  unique (document_id, content_hash)
);
```

`document_version` being immutable and hash-keyed is what makes refresh cheap **and** makes "what did this document say in March?" answerable. It is the foundation of the change report.

### 3.2 Chunks

```sql
create table chunk (
  id              uuid primary key default gen_random_uuid(),
  workspace_id    uuid not null,
  version_id      uuid not null references document_version(id) on delete cascade,
  ordinal         int  not null,
  heading_path    text[],          -- ['Item 4','Attercliffe Regeneration','Decision']
  page_from       int,
  page_to         int,
  char_start      int not null,
  char_end        int not null,
  text            text not null,   -- verbatim source span. never rewritten.
  context_header  text,            -- 50-100 token LLM-generated situating summary
  embed_text      text generated always as
                    (coalesce(context_header,'') || E'\n\n' || text) stored,
  embedding       vector(1024),
  tsv             tsvector generated always as
                    (to_tsvector('english',
                       coalesce(context_header,'') || ' ' || text)) stored,
  token_count     int
);

create index on chunk using hnsw (embedding vector_cosine_ops);
create index on chunk using gin (tsv);
create index on chunk (workspace_id, version_id);
```

**Three deliberate details:**

1. `text` is the **verbatim source span, never rewritten**. This is what deterministic quote verification (§6.4) checks against. If we ever paraphrased into `text`, citation verification would become impossible.
2. `context_header` is separate and is concatenated only for indexing. Anthropic's Contextual Retrieval, applied to **both** the dense and the keyword index. The generated column guarantees they can never disagree.
3. `char_start`/`char_end` make every citation a **precise span**, not a whole page.

### 3.3 The assertion ledger

The centre of the system.

```sql
create table assertion (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null,

  -- the claim
  subject_id    uuid references entity(id),
  predicate     text not null,        -- attended | owns | was_made_at | is_assigned_to
                                      -- relates_to | threatens | supersedes | depends_on
  object_id     uuid references entity(id),
  object_literal text,                -- for value claims: "£2.4m", "Q1 2027"
  claim_text    text not null,        -- one-sentence natural language form

  -- epistemics
  modality      text not null check (modality in ('explicit','inferred')),
  confidence    real not null default 1.0,

  -- bitemporal
  valid_from    date,                 -- when true in the world
  valid_to      date,
  asserted_at   timestamptz not null default now(),   -- when we learned it
  invalid_at    timestamptz,          -- when we stopped believing it
  invalidated_by uuid references assertion(id),
  invalidation_reason text check (invalidation_reason in
                  ('superseded','contradicted','corrected','source_withdrawn')),

  status        text not null default 'active',   -- active | invalidated | disputed
  stale_after   date,                             -- computed review date

  -- governance
  verified_by   text,                 -- 'human:rajarshi' | 'agent/qwen3-...'
  verified_at   timestamptz
);

-- evidence. an assertion with zero rows here is invalid by construction.
create table assertion_evidence (
  assertion_id  uuid not null references assertion(id) on delete cascade,
  chunk_id      uuid not null references chunk(id),
  quote         text not null,        -- verbatim, must exist in chunk.text
  char_start    int,
  char_end      int,
  primary key (assertion_id, chunk_id)
);

create index on assertion (workspace_id, status) where invalid_at is null;
create index on assertion (workspace_id, stale_after) where status = 'active';
```

**Rules enforced in code:**
- `INSERT`-only. `invalid_at` is the sole mutation, and it is set once.
- No assertion without at least one `assertion_evidence` row.
- `modality='inferred'` **requires** `confidence < 1.0` and evidence for the premises.
- Contradictions produce **two active assertions marked `disputed`**, never a merge.

**The bitemporal pair is what makes belief revision work.** `valid_from/valid_to` is world time; `asserted_at/invalid_at` is system time. That combination answers *"as of 12 June, what did we believe was true about Q3?"*, a question a latest-state snapshot structurally cannot answer.

### 3.4 Entities and resolution

```sql
create table entity (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   uuid not null,
  type           text not null,   -- Person | Organisation | Project | Meeting
                                  -- Document | Decision | Action | Risk | Location | Policy
  canonical_name text not null,
  normalised_name text not null,  -- lowercased, punctuation-stripped, for blocking
  aliases        text[] default '{}',
  attrs          jsonb default '{}',
  embedding      vector(1024),    -- of the entity's aggregated context
  first_seen     date,
  last_seen      date,
  merged_into    uuid references entity(id),   -- soft merge. reversible.
  status         text not null default 'active'
);
create index on entity using gin (normalised_name gin_trgm_ops);

create table entity_merge_log (
  id          uuid primary key default gen_random_uuid(),
  winner_id   uuid not null, loser_id uuid not null,
  method      text not null,    -- exact | alias | trigram | embedding | llm | human
  score       real,
  evidence    jsonb,            -- the spans that justified it
  decided_by  text not null,
  decided_at  timestamptz not null default now(),
  reverted_at timestamptz
);
```

Merges are **soft** (`merged_into`) and **logged with evidence**. Reversal is an `UPDATE ... SET merged_into = null` plus a log row. The brief warns against merging similarly-named entities without evidence; the only safe way to honour that is to make merging undoable.

### 3.5 Knowledge pages (the OKF projection)

```sql
create table knowledge_page (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null,
  path          text not null,          -- 'projects/attercliffe-regeneration.md'
  okf_type      text not null,          -- frontmatter `type`
  frontmatter   jsonb not null,         -- serialised to YAML at export
  body_md       text not null,
  entity_id     uuid references entity(id),
  built_from    uuid[],                 -- assertion ids
  generated_by  text not null,
  generated_at  timestamptz not null default now(),
  verified      jsonb default '[]',
  okf_status    text default 'stable',
  stale_after   date,
  unique (workspace_id, path)
);
```

Fully derived, droppable and rebuildable from the ledger at any time. It exists as a table so the wiki is browsable in-app without an export, and so human `verified` entries survive rebuilds.

### 3.6 Change events

```sql
create table ingest_run (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null, source_id uuid,
  trigger text not null,          -- manual | scheduled | initial
  started_at timestamptz not null default now(), finished_at timestamptz,
  docs_seen int, docs_changed int, docs_new int, docs_gone int,
  stats jsonb
);

create table change_event (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references ingest_run(id) on delete cascade,
  kind text not null,   -- new | confirmed | outdated | contradicted
                        -- action_completed | owner_changed | question_raised
  assertion_id uuid references assertion(id),
  prior_assertion_id uuid references assertion(id),
  summary text not null,
  detail jsonb
);
```

The change report is `SELECT * FROM change_event WHERE run_id = ?`, rendered, not recomputed. Reports are therefore stable artifacts, identical every time they are opened.

---

## 4. The pipeline

Eleven stages, each an idempotent `pgmq` job keyed by `(version_id, stage)`. Any stage can be replayed without corrupting state, essential when parsing costs money and workers get OOM-killed.

```
 1 discover    enumerate source → external ids + hashes
 2 fetch       pull bytes → blob storage
 3 dedupe      content hash → unchanged? stop here.
 4 parse       tier 0 fast → tier 1 docling → tier 2 vlm
 5 sanitise    strip invisible text, quarantine instruction-shaped spans
 6 chunk       structure-first, semantic fallback
 7 contextualise  50-100 token header per chunk (cheap model, cached doc)
 8 embed       batch → pgvector; tsvector generated automatically
 9 extract     entities + assertions with evidence spans (structured output)
10 resolve     entity resolution cascade
11 reconcile   diff vs ledger → new/confirmed/outdated/contradicted
12 materialise rebuild knowledge_page projections
```

*(Stage 3's early exit is what makes refresh nearly free, see §5.)*

### 4.1 Parse: tiered

```
                    ┌─ text density > 0.6 ─────► pymupdf4llm     (fast, cheap)
  PDF ──► probe ────┼─ tables/columns detected ► docling-serve   (isolated)
                    └─ scanned / density < 0.1 ► docling + OCR, else VLM
  DOCX/PPTX/XLSX ──► docling (native, no OCR)
  HTML ────────────► trafilatura + selectolax
  MD/TXT/CSV/JSON ─► native readers
```

The probe is a cheap heuristic: extractable characters per page area. It routes the large majority of council PDFs, which are born-digital, down the free path and reserves the 4GB service for documents that genuinely need it.

Output is normalised markdown **plus a heading tree with character offsets**. The offsets are what make chunk citations page- and span-precise.

### 4.2 Chunk: structure first

```python
def chunk(doc):
    for section in doc.heading_tree.leaves():        # agenda items, minute numbers
        if section.tokens <= MAX:
            yield Chunk(section)                      # a whole decision stays whole
        else:
            yield from SemanticChunker(...).split(section)   # Chonkie, within-section
```

Council minutes carry their own structure: numbered items, decision headings, resolution blocks. Splitting on those boundaries beats cosine-similarity breakpoints because a decision and its rationale are structurally adjacent even when semantically dissimilar. Chonkie's semantic chunker handles the overflow case where a single section is too long.

`heading_path` is retained on every chunk and shown in citations, which is why a citation can read *"Planning Committee Minutes, 12 Mar 2026 › Item 4 › Decision, p.4"*.

### 4.3 Contextualise

```
Prompt (cheap open-weight model, parent document cached):
  <document>{{ full_document }}</document>
  <chunk>{{ chunk_text }}</chunk>
  Give a 50-100 token context situating this chunk in the document.
  State the document, date, and what this section concerns.
  Output the context only.
```

Written to `chunk.context_header`; the generated `embed_text` and `tsv` columns pick it up automatically, guaranteeing both indexes carry identical context. Measured impact: **−67% retrieval failure** (research §2.1).

Cost control: batch chunks per document, cache the document prefix, and use the cheapest capable open-weight model. This is the highest-volume LLM call in the system and the only one worth optimising hard.

### 4.4 Extract

One structured-output call per chunk group, via Instructor:

```python
class ExtractedAssertion(BaseModel):
    predicate: Literal['attended','owns','was_made_at','is_assigned_to',
                       'relates_to','threatens','mentions','supersedes',
                       'depends_on','supports']
    subject: EntityRef
    object: EntityRef | str
    claim_text: str
    modality: Literal['explicit','inferred']
    confidence: float = Field(ge=0, le=1)
    valid_from: date | None
    quote: str        # MUST be verbatim from the chunk
    quote_start: int
```

**Post-conditions checked in code, not trusted from the model:**
- `quote` must appear in `chunk.text` (normalised exact, then fuzzy ≥ 0.95). Fails → assertion discarded.
- `modality='inferred'` with `confidence == 1.0` → rejected as incoherent.
- Unknown predicate → rejected. The schema is closed.

This runs with **zero tool access**, the architectural control against indirect prompt injection (§8).

### 4.5 Resolve: the cascade

```
1. exact normalised name + type match            → merge, method='exact'
2. known alias / acronym expansion               → merge, method='alias'
3. pg_trgm similarity > 0.85 AND type match      → merge, method='trigram'
4. embedding cosine 0.80–0.92 (the grey band)    → LLM adjudication
5. LLM must cite spans supporting sameness       → merge if yes, else flag
6. anything unresolved                           → duplicate review queue (UI)
```

Default is conservative. Unresolved pairs surface to the user rather than being auto-merged. Every decision writes an `entity_merge_log` row with its evidence.

### 4.6 Reconcile: where belief revision happens

For each newly extracted assertion, against active ledger assertions on the same `(subject, predicate)`:

| Relationship to existing | Action |
|---|---|
| Identical claim, new source | Add evidence row. Emit `confirmed`. Raise confidence. |
| Same subject+predicate, different object, **later** `valid_from` | Set old `invalid_at`, `reason='superseded'`, link `invalidated_by`. Emit `outdated`. |
| Same subject+predicate, different object, **same/ambiguous** date | Both stay `active`, both marked `disputed`. Emit `contradicted`. **Never merged.** |
| Action status → complete | Emit `action_completed`. |
| Owner null → set | Emit `owner_changed`. |
| No prior | Emit `new`. |

The **contradicted** branch is the one that matters. The instinct is to pick a winner; the brief explicitly forbids blending disagreements into one answer, and in public-records work an unexplained figure change is the *finding*, not noise.

`stale_after` is computed here from: explicit review dates in text, deadlines, conditional language ("subject to", "pending"), and the source's observed publication cadence.

---

## 5. Refresh

```
Refresh(source)
  ├─ re-enumerate                    (folder listing / sitemap / url list)
  ├─ hash everything found
  ├─ classify: unchanged | modified | new | disappeared
  │    unchanged  → stop. zero cost.
  │    modified   → new document_version → full pipeline
  │    new        → full pipeline
  │    disappeared→ document.status='unavailable'  (assertions retained)
  ├─ reconcile   → change_event rows
  └─ materialise → rebuild affected knowledge_page rows
```

A refresh over 200 documents where 3 changed costs three documents of work. This is what lets "manual refresh" be a permanent design position rather than a shortcut. Content hashing solves the freshness-cost problem for free at this scale, so no continuous-ingest machinery is needed.

Optional `pg_cron` schedules per source, default off. A nightly `pg_cron` job also sweeps `stale_after < today` and raises governance flags with no LLM cost at all.

---

## 6. Retrieval and answering

### 6.1 Hybrid + RRF

```sql
with dense as (
  select id, row_number() over (order by embedding <=> $1) rank
  from chunk where workspace_id = $2 order by embedding <=> $1 limit 50
),
sparse as (
  select id, row_number() over (order by ts_rank_cd(tsv, q) desc) rank
  from chunk, websearch_to_tsquery('english', $3) q
  where workspace_id = $2 and tsv @@ q limit 50
)
select id, sum(1.0/(60 + rank)) score
from (select * from dense union all select * from sparse) u
group by id order by score desc limit 30;
```

RRF with `k=60`. Set `hnsw.iterative_scan = 'relaxed_order'` for the session. Without it, workspace and date filters over an HNSW index silently return too few candidates (research §2.3).

### 6.2 Rerank
Top 30 → cross-encoder (`bge-reranker-v2-m3`) → top 8. Behind the `Reranker` port, so it can be the gateway or a self-hosted TEI instance.

### 6.3 Graph augmentation
Entities detected in the query pull their assertion neighbourhood (1 hop, 2 for `supersedes`/`depends_on`). This is how *"which risks affect more than one project"* gets answered, a question no amount of chunk retrieval reaches, because the answer exists in no single passage. Merged into the evidence set with graph provenance marked.

### 6.4 Grounded generation with mechanical verification

```python
answer = llm.generate(Answer, evidence=evidence_set)   # structured

for claim in answer.claims:
    chunk = get(claim.chunk_id)
    if not quote_present(claim.quote, chunk.text):     # normalised, then fuzzy
        claim.demote()                                  # fact → unsupported
answer.claims = [c for c in answer.claims if c.verified or c.modality == 'inferred']

if not answer.claims:
    return Abstention(gaps=describe_coverage_gaps(query, workspace))
```

**This is the cheapest high-value control in the system.** Microseconds, no judge model, and it makes the citation guarantee structural rather than aspirational. LLM-based faithfulness scoring then measures residual quality instead of being the only defence.

### 6.5 CRAG routing

| Grade | Action |
|---|---|
| `correct` | Generate |
| `ambiguous` | Expand via graph neighbourhood, rerank, retry **once** |
| `incorrect` | Rewrite query, retry **once**, then **abstain with named gaps** |

**Deliberate deviation from canonical CRAG:** the `incorrect` branch does *not* fall back to web search by default. The brief grades traceability to the supplied corpus and explicit insufficiency; silently sourcing the open web converts an honest abstention into an uncitable answer. Web search is available behind a toggle and its results render in a separate "outside the corpus" block that can never be cited as a corpus fact.

---

## 7. Exports

All four renderers read the ledger. None recompute knowledge.

| Artifact | Renderer | Notes |
|---|---|---|
| `Briefing.pdf` | Typst template + ledger query | Single binary, ~50MB, no TeX |
| `Knowledge_Graph.okf` | OKF v0.2 serialiser → ZIP | Bundle, not a single file |
| `Entities_Relationships.json` | Direct projection | +GraphML / Mermaid / Cypher |
| `Governance_Guide.md` | Query over `stale_after`/`confidence`/owners | Generated from real state |

### 7.1 OKF serialiser

Isolated in **one module**, version-stamped `okf_version: "0.2"`. The spec moved 0.1 → 0.2 in under two months with breaking changes; containment is deliberate.

```
knowledge_graph/
  index.md          okf_version: "0.2", grouped catalogue
  log.md            ## 2026-08-07 \n * **Update**: ...
  projects/attercliffe-regeneration.md
  people/priya-raman.md
  decisions/2026-03-12-phase-1-approval.md      status: deprecated
  ...
```

```yaml
---
type: Project
title: Attercliffe Regeneration
description: Mixed-use regeneration, phases 1-3.
status: stable
stale_after: 2026-11-05
tags: [regeneration, planning, attercliffe]
generated: { by: "intelligence-engine/qwen3-max", at: 2026-08-07T14:22:00Z }
verified:
  - { by: "human:rajarshi", at: 2026-08-07T15:10:00Z }
sources:
  - id: minutes-2026-08-05
    resource: https://sheffield.gov.uk/.../minutes-2026-08-05.pdf
    title: Planning Committee Minutes, 5 August 2026
    last_modified: 2026-08-05
---

Phase 2 budget was approved at £2.4m.[^minutes-2026-08-05]

> **Conflicting evidence.** The Finance Report (20 Jul 2026) states £2.1m.
> Both retained; unresolved.

[^minutes-2026-08-05]: Planning Committee Minutes, 5 Aug 2026, p.3.
```

Mapping to OKF's own semantics: `verified` with a `human:` actor is what promotes a page from *machine-confirmed* to *human-reviewed* in OKF's trust tiers. `status: deprecated` is how a superseded decision stays present but visibly dead, matching the ledger's `invalid_at`, not overwriting it.

### 7.2 Governance guide: generated, not templated

| Section | Query |
|---|---|
| Ages fastest | `stale_after` ascending, with the reason it was computed |
| Needs evidence | `count(evidence) = 1` or `confidence < 0.7` |
| Needs an owner | Actions with null assignee; projects with no responsible org |
| Missing relationships | Entity pairs with high co-occurrence and no edge |
| Where the picture may change | Pending decisions, open conditions, `disputed` assertions |
| Cadence | Observed publication rhythm per source |
| 24-month schedule | `stale_after` bucketed by month |

---

## 8. Security

The threat here is **not** a malicious user typing a jailbreak. It is **indirect prompt injection from ingested documents**, OWASP LLM01, the most widely exploited vulnerability in production deployments, where one poisoned document compromises every user whose query retrieves it.

| Control | Where | What it does |
|---|---|---|
| Unicode sanitisation | Stage 5 | Strip zero-width, bidi-override, control chars |
| Invisible-text detection | Stage 5 | Drop text whose colour matches background; `display:none`; HTML comments |
| Instruction quarantine | Stage 5 | Flag instruction-shaped spans → stored, excluded from prompts, **shown in UI as a finding** |
| **No tools in extraction** | Stage 9 | The high-volume calls touching untrusted text have zero privileges. **This is the real control.** |
| Spotlighting | All prompts | Untrusted content always delimited and labelled as data |
| Quote verification | §6.4 | Injected instructions cannot manufacture a citation that survives |
| `promptfoo` in CI | Build | Adversarial regression, 50+ vulnerability classes |

**Explicitly rejected: keyword-based guardrails.** Standard guardrails drop to roughly 60% accuracy on benign data because trigger words like "ignore" appear innocently, and council minutes are full of *"the committee resolved to ignore the previous recommendation"*. On this corpus a blunt filter does more damage than the attack it prevents. The PRD's three-product guardrail stack (NeMo + Guardrails AI + Llama Guard) is aimed mostly at user-input safety and is the wrong shape for a document-ingestion threat model.

Data handling: `drive.file` scope only; raw bytes in blob storage with signed URLs; secrets in Railway/Vercel env, never in `NEXT_PUBLIC_*`; per-workspace row-level isolation on every query.

---

## 9. Evaluation

### 9.1 Golden set: build this before the pipeline
~40 questions over a fixed corpus snapshot:
- 20 answerable single-hop
- 8 multi-hop (require graph augmentation)
- **7 unanswerable** (the brief grades these)
- 3 contradiction-surfacing
- 2 temporal ("what changed between March and August?")

### 9.2 Metrics

| Layer | Tool | Gate |
|---|---|---|
| Retrieval | Ragas, context precision/recall | recall@20 ≥ 0.95 |
| Generation | Ragas, faithfulness, answer relevancy | faithfulness ≥ 0.85 |
| **Abstention** | Custom | correct-abstention ≥ 0.90 |
| **Citation validity** | Deterministic | **1.00, hard gate** |
| Entity resolution | Labelled pairs | over-merge ≤ 0.02 |
| Change report | Human review | precision ≥ 0.90 |
| CI gates | DeepEval (pytest) | blocks merge |
| Red team | promptfoo | zero critical |

Correct-abstention is our headline number and no framework provides it off the shelf. It is also the metric most systems in this category quietly fail.

### 9.3 Tracing
Langfuse Cloud (MIT core; self-hosting needs ClickHouse + Redis + S3, heavier than this entire application). Emit OTel `gen_ai.*` attributes, **pinned to a semconv version**: these conventions are still `Development`, none are Stable, and they moved to a separate repo in June 2026. Treat them as a moving target, not a standard.

---

## 10. Cost model

Assumption: 500 documents, ~15k chunks, one initial build plus weekly refreshes.

**Build (one-off, per 500 docs)**

| Stage | Calls | Est. |
|---|---|---|
| Context headers | 15k cheap calls, cached prefixes | $2–5 |
| Embeddings | 15k × ~400 tok | $0.50–2 |
| Extraction | ~4k chunk groups, cheap model | $4–10 |
| Entity adjudication | ~200 grey-band pairs | $0.50 |
| **Total** | | **~$8–18** |

**Monthly running**

| Item | Est. |
|---|---|
| Railway: postgres + api + worker | $15–30 |
| Railway: parser (scale-to-zero) | $3–10 |
| Vercel: hobby/pro + Blob | $0–20 |
| LLM: refreshes + queries | $5–20 |
| Langfuse Cloud | $0 (free tier) |
| **Total** | **~$25–80/mo** |

The dominant lever is the context-header stage. If cost becomes a problem, generate headers only for chunks above a length threshold and inherit the section header otherwise, expected to cut that line by ~60% at small recall cost. **Measure before optimising.**

Compare: Microsoft GraphRAG is reported at $40–60 in API cost for a *single* 10,000-word document. Choosing our own extraction over that framework is roughly a 100× cost decision (research §3.3).

---

## 11. Build phases

Ordered so that **something demoable exists after every phase**.

### Phase 0: Skeleton *(~half a day)*
Railway PG18 with `EXTENSIONS=pgvector,pgmq,pg_cron,pg_trgm,pgcrypto`. Verify with `SELECT * FROM pg_available_extensions;` (research §8.2). FastAPI + `pgmq` worker. Next.js + Better Auth. Schema migrated. Health checks green.

### Phase 1: Ingest → Ask *(~1 day)* ← **first demo**
Upload + link connectors. Tier-0 parsing. Structure-first chunking. Context headers. Hybrid + RRF. Grounded answers with verified citations and abstention. **Golden set written before this phase, not after.**

### Phase 2: Compile *(~1 day)*
Entity + assertion extraction. Resolution cascade. Explore view. `Entities_Relationships.json`. `Briefing.pdf` via Typst.

### Phase 3: Refresh & change report *(~1 day)* ← **the winning demo**
`document_version` diffing. Reconciliation. Bitemporal invalidation. Change report UI. Do not let this slip; steps 1–4 of the demo are table stakes and this is the differentiator.

### Phase 4: Knowledge layer & governance *(~1 day)*
OKF v0.2 serialiser. `knowledge_page` materialisation. `stale_after` computation. `Governance_Guide.md`. Full export picker with "all of the above".

### Phase 5: Harden *(ongoing)*
Google Drive connector (Picker). Docling tier-1. Reranking. CRAG routing. Ragas/DeepEval/promptfoo in CI. Langfuse. Injection defences.

**Drive is Phase 5, not Phase 1, on purpose.** It is the highest-friction connector (OAuth app, consent screen, Picker API key) and the *least* important for proving the idea. Upload and links demonstrate the same pipeline with a fraction of the setup.

---

## 12. Decision record

| # | Decision | Alternative | Why |
|---|---|---|---|
| 1 | Assertion ledger + projections | PRD's parallel tri-engine | Three write paths drift; one ledger cannot |
| 2 | Postgres for everything | A broker, stream processor, dedicated vector DB, graph DB and cache | One datastore does five jobs; ~$25/mo vs hundreds |
| 3 | Manual refresh + content hashing | Continuous ingest | Unchanged docs cost zero; live ingest explicitly out of scope |
| 4 | Relational graph tables | Neo4j / AGE / Kùzu | 1–2 hop queries; **Kùzu is archived**; AGE not in image |
| 5 | Bitemporal invalidation | Overwrite on update | The entire change-report feature depends on it |
| 6 | `drive.file` + Picker | `drive.readonly` | Avoids restricted-scope verification + CASA assessment |
| 7 | CRAG **without** default web search | Canonical CRAG | Traceability to corpus is the graded criterion |
| 8 | Deterministic quote verification | LLM-judge only | Free, structural, cannot be prompted away |
| 9 | Tiered parsing | Docling everywhere | Docling ~4GB + no memory release ≈ $40/mo idle |
| 10 | Own extraction, no GraphRAG framework | MS GraphRAG / LightRAG | ~100× cost; LightRAG locks storage + had auth CVEs |
| 11 | Gateway embeddings by default, TEI documented | Self-host always | Bursty workload; idle GPU/RAM is the wrong bill |
| 12 | Contradictions preserved | Pick a winner | Brief forbids blending; the disagreement is the finding |
| 13 | Typst for PDF | Pandoc + LaTeX | ~50MB binary vs ~4GB TeX Live |
| 14 | Conservative entity resolution | Aggressive auto-merge | Over-merging is unrecoverable and misleading |

---

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Docling RAM exhausts the worker | **High** | Isolated service, cap, restart-after-N, tier-0 handles most docs. **Measure on 50 docs before sizing.** |
| Extraction cost scales badly | Medium | Cheap model + cached prefixes; header threshold as the lever |
| Entity over-merging corrupts the graph | **High** | Conservative thresholds, soft merges, full audit log, review queue |
| `ts_rank` under-performs true BM25 | Medium | Isolated behind `KeywordIndex`; eval triggers a custom PG image with `pg_search` |
| Injected instructions in council PDFs | **High** | Sanitisation + quarantine + **no tools in extraction** + quote verification |
| OKF v0.3 breaks the serialiser | Low | Single module, version-stamped |
| Google OAuth verification blocks Drive | Medium | `drive.file` + Picker sidesteps it entirely; Drive is Phase 5 regardless |
| Change report produces noise | **High** | Confirmations collapsed to a count; only material changes itemised; tune against human review |
| No corpus in the folder yet | **High** | Build against a stand-in set now; connectors are corpus-agnostic |

---

## 14. Open questions

1. **`pymupdf4llm` is AGPL-3.0** (PyMuPDF). It runs as an isolated ingest step, but if AGPL reach is unacceptable for the intended distribution, substitute `pypdfium2` (Apache/BSD) with some table-quality loss. **Needs a call before Phase 1.**
2. **Embedding model and dimension must be fixed before the first index build**. Changing either forces a full re-index. Decide BGE-M3 (1024) vs Qwen3-Embedding at Phase 1 start.
3. **Does the OKF repo ship a validator?** If not, write a ~100-line conformance checker, the spec is small and worth owning.
4. **Confirm the full extension list** on the deployed Railway image (7 of 11 are documented).
5. **Is there a real corpus?** Every challenge assumes a supplied folder of Sheffield documents that is not present.
