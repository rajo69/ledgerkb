# Roadmap

Fifteen stages: nine library stages ending at v1.0.0 on PyPI, then six product
stages. The detail below is generated from [`docs/stages.toml`](docs/stages.toml),
which is the only place stage status is recorded.

## The gating rule

**No stage begins until the previous stage's gate is green.** A gate is a list of
measurable checks, not a feeling that the work is finished. Every criterion is
something you can run, count or point at.

| Colour | Meaning | What happens |
|---|---|---|
| Green | Every criterion met, CI passing | Start the next stage |
| Amber | Criteria met, with a known defect | Proceed only once the defect is written into the risk register with an owner |
| Red | Any criterion unmet | Stop. Fix it, or descope it in writing. Never carry it forward silently |

This is why the project looks slow. L2's machinery has been merged for a while,
and L2 is still open, because four of its seven criteria are measurements that
have not been made. Shipping L3 first would be faster and would mean the
retrieval numbers never get taken.

There is one sanctioned exception, recorded in
[`docs/design/03-implementation-plan.md`](docs/design/03-implementation-plan.md)
section 9: a two-day path that ships L0 through L3 and then jumps to L6, skipping
extraction, resolution and the exports. It exists so that a demo deadline
produces an honest subset rather than four half-built features.

## Stages

<!-- generated: roadmap-table. Edit docs/stages.toml, then run scripts/render_docs.py -->
| Stage | Title | Status | Gate | Ships |
|---|---|---|---|---|
| L0 | Skeleton and contracts | done | 5/5 | - |
| L1 | Ingest, parse, chunk | done | 6/6 | - |
| **L2** | Index and retrieve | in progress | 3/7 | - |
| L3 | Grounded answering | not started | 0/5 | v0.1.0 |
| L4 | Assertion ledger and extraction | not started | 0/6 | - |
| L5 | Entity resolution and graph | not started | 0/5 | v0.3.0 |
| L6 | Refresh and change report | not started | 0/6 | v0.4.0 |
| L7 | Projections and exports | not started | 0/6 | v0.5.0 |
| L8 | Evals, guardrails, observability | not started | 0/8 | v1.0.0 |
| P1 | Service layer | not started | 0/1 | - |
| P2 | Web UI core | not started | 0/1 | - |
| P3 | Connectors | not started | 0/1 | - |
| P4 | Change report and export picker | not started | 0/1 | - |
| P5 | Deploy artifacts | not started | 0/1 | - |
| P6 | Hardening | not started | 0/2 | - |
<!-- end generated: roadmap-table -->

Gate counts are met criteria over total criteria. A stage marked done has all of
them; L2's count is what makes its half-finished state legible.

## Detail

<!-- generated: roadmap-detail. Edit docs/stages.toml, then run scripts/render_docs.py -->
### L0. Skeleton and contracts

*done · effort ~0.5 day · risk low*

**Goal.** The shape everything else fills in.

Domain models, Protocol ports, config with four tunability tiers, the SQLite store and its
migrations, deterministic fake providers, and the first CLI commands.

Gate:

- [x] Clean install on Linux, macOS and Windows, under 60s and under 120MB
- [x] mypy --strict passes on core
- [x] lkb init and lkb doctor succeed with zero API keys set
- [x] Every core model round-trips through SQLite unchanged
- [x] PyPI name confirmed available (it is claimed on first publish at L8)

### L1. Ingest, parse, chunk

*done · effort ~1 day · risk medium*

**Goal.** Documents become chunks with correct metadata and exact offsets, entirely offline.

Filesystem and ZIP readers with traversal, bomb-ratio, depth and size guards. Tier-0 parsers
for PDF, DOCX, XLSX, PPTX, HTML, EML, CSV, JSON, MD and TXT. A sanitiser that removes
invisible text and quarantines instruction-shaped spans rather than deleting them.
Structure-first chunking, deterministic metadata extraction, and a pipeline that dedupes by
content hash and isolates per-document failures.

Gate:

- [x] A mixed-format fixture corpus ingests with zero unhandled exceptions
- [x] Every chunk's char_start:char_end slices back to byte-identical source text,
      checked by a Hypothesis property over arbitrary input as well as over the corpus
- [x] All five required metadata fields populated on at least 90% of fixtures, with
      every miss reported rather than silently null
- [x] The nine injection fixtures are all caught and the benign decoy is left
      untouched
- [x] All five malicious archive fixtures are refused
- [x] The whole path runs with no network and no API key, enforced by a CI job inside
      a network namespace

### L2. Index and retrieve

*in progress · effort ~1 day · risk medium*

**Goal.** Hybrid retrieval that beats either half alone.

An OpenAI-compatible embedder and a local in-process one, reciprocal rank fusion, and three
retrieval arms: dense vectors, FTS5 BM25 and the heading path. Search is scoped to current
document versions and every candidate carries a per-arm rank explanation. The machinery is
merged, the store now records which model made its vectors and refuses a second one on the
index path, and the corpus that blocked the measurement is built: 196 documents and 4,437
chunks, against 50 dense candidates. What remains is the golden set and the four numbers
that come from running it.

Gate:

- [x] --explain prints each candidate's per-arm rank and fused score
- [x] Retrieval is scoped to current document versions, enforced in the schema
- [ ] A golden set of 40 questions, at least 7 of them unanswerable, written from the
      documents before retrieval is run
- [ ] recall@20 at or above 0.90 on the answerable questions
- [ ] Hybrid beats dense-only and BM25-only on the same set, measured, printed and
      committed
- [ ] Contextual headers improve recall@20 by at least 5 points, which is what would
      justify their cost
- [x] The embedding model and dimension are recorded in the store and a change is
      detected on the index path, not only by lkb doctor

### L3. Grounded answering

*not started · ships v0.1.0 · effort ~1 day · risk medium*

**Goal.** Cited answers and honest abstention.

A structured Answer whose every claim carries a chunk id, a verbatim quote, a modality and a
confidence. Quote verification runs deterministically before any answer reaches the caller.
CRAG routing retries once and then abstains with named coverage gaps rather than reaching
for the open web.

Gate:

- [ ] Citation validity is 1.00, asserted rather than measured: a claim whose quote is
      absent from its cited chunk cannot reach the caller
- [ ] Correct abstention at or above 0.90 on the unanswerable subset
- [ ] Zero hallucinated chunk ids across the golden set
- [ ] Facts and inferences are never conflated in output
- [ ] Published to PyPI, and pip install ledgerkb[local] to ingest to ask works in a
      clean container in under 5 minutes

### L4. Assertion ledger and extraction

*not started · effort ~1.5 days · risk high*

**Goal.** Documents become claims with evidence.

The assertion and evidence tables, append-only. Extraction against a closed predicate
schema, with post-conditions checked in code rather than trusted from the model. Extraction
calls carry zero tools, which is the architectural control against indirect prompt
injection. Staleness dates are computed from review dates, deadlines, conditional language
and source cadence.

Gate:

- [ ] Every assertion has at least one evidence row, enforced by a database constraint
- [ ] Every evidence quote verifies against its chunk
- [ ] Extraction precision at or above 0.85 on a 100-assertion hand-labelled sample
- [ ] Zero out-of-schema predicates across the corpus
- [ ] A test asserts the outgoing extraction request body carries no tools key
- [ ] Cost per 100 documents recorded and within 2x of the architecture estimate

### L5. Entity resolution and graph

*not started · ships v0.3.0 · effort ~1.5 days · risk high*

**Goal.** The network, without wrong merges.

Ten node types and a resolution cascade running exact, alias, trigram, embedding grey-band,
LLM adjudication with cited evidence, and finally a review queue. Merges are soft and logged
with evidence, so every one of them is reversible. Graph queries run as recursive CTEs over
relational tables. Exports to JSON, GraphML, Mermaid and Cypher.

Gate:

- [ ] Over-merge rate at or below 0.02 on a labelled pair set, because over-merging is
      the failure that matters
- [ ] Every merge is reversible and a reversal test passes
- [ ] All five example queries execute and return sensible results on the fixture
      corpus
- [ ] Graph exports validate: GraphML against its schema, Mermaid renders, Cypher
      parses
- [ ] Zero edges without a source document reference

### L6. Refresh and change report

*not started · ships v0.4.0 · effort ~1.5 days · risk high*

**Goal.** Belief revision with preserved history. This is the differentiator.

Content-hash diffing classifies every document as unchanged, modified, new or disappeared.
Reconciliation produces the seven update categories. Invalidation is bitemporal: set
invalid_at and record what invalidated it, never delete. Contradictions become two active
disputed assertions and are never merged. The change report is rendered from stored change
events rather than recomputed.

Gate:

- [ ] Unchanged documents cost zero LLM calls, asserted by a call-counting test
- [ ] "What did we believe on date D?" returns the correct historical state
- [ ] All seven update categories are produced on a scripted document containing each
- [ ] Contradictions surface as two assertions, and a blended single answer is a test
      failure
- [ ] Change-report precision at or above 0.90 against human review of the scripted
      document
- [ ] A full replay from scratch yields the same final ledger state with LLM calls
      stubbed

### L7. Projections and exports

*not started · ships v0.5.0 · effort ~1.5 days · risk medium*

**Goal.** The four deliverables, all read from the ledger and none recomputing knowledge.

An OKF v0.2 serialiser in one version-stamped module, plus a conformance checker. A briefing
document rendered with Typst. A governance guide generated from live ledger state. A
machine-readable entities and relationships export, plus a flat knowledge-items table. Every
export carries a build receipt recording the resolved config that produced it.

Gate:

- [ ] The OKF bundle passes the conformance checker and opens correctly in Obsidian
- [ ] Every briefing statement carries a source and a date, with inferences visually
      marked
- [ ] Disagreements appear in the output as disagreements
- [ ] Every governance guide item traces to a real ledger row, with no generic filler
- [ ] --all produces one archive with a manifest and a build receipt
- [ ] Exports are reproducible: the same store state gives byte-identical output,
      timestamps excluded

### L8. Evals, guardrails, observability

*not started · ships v1.0.0 · effort ~2 days · risk medium*

**Goal.** Production posture.

The eval runner and its deterministic metrics, red-team regression in CI, OpenTelemetry
spans against a pinned GenAI semantic-convention version, cost and token accounting, and
budget guards that abort a runaway run. This is the stage that claims the PyPI name and
commits to core's stability.

Gate:

- [ ] lkb eval run reports every deterministic metric with no LLM judge and no API key
- [ ] DeepEval gates are wired into CI and block a merge
- [ ] The promptfoo red-team suite reports zero critical findings
- [ ] OTel spans validate against the pinned semconv version, verified end to end
      against an OTLP backend
- [ ] Cost and token accounting is accurate to within 5% of provider-reported usage
- [ ] The budget guard aborts a runaway run at the configured ceiling
- [ ] The documentation site is published and public-API docstring coverage is at or
      above 90%
- [ ] v1.0.0 on PyPI, with a stability commitment on core

### P1. Service layer

*not started · effort ~1 day · risk medium*

**Goal.** An HTTP surface over the library.

FastAPI wrapping ledgerkb, with endpoints for sources, ingest, ask, entities, changes and
export. A job queue for the long-running work, and server-sent events for token streaming.

Gate:

- [ ] Every endpoint is a thin call into the library, with zero domain logic in the
      API layer

### P2. Web UI core

*not started · effort ~2 days · risk medium*

**Goal.** The ask view, the document list and the graph view.

Next.js with the three-zone answer contract: facts, interpretation and gaps, kept visually
distinct.

Gate:

- [ ] Answer rendering is faithful to the library's Answer model: facts and inferences
      visually distinct, gaps always shown

### P3. Connectors

*not started · effort ~2 days · risk medium*

**Goal.** Getting documents in from somewhere other than a local folder.

Multi-file and archive upload, link ingestion (single URL, list, sitemap, bounded crawl with
a preview), and Google Drive through the file picker only.

Gate:

- [ ] The Drive connector never requests a restricted scope, asserted in a test

### P4. Change report and export picker

*not started · effort ~1.5 days · risk medium*

**Goal.** The refresh loop, visible.

A refresh view, the change report, a multi-select export picker and a download history.

Gate:

- [ ] The five-minute demo script in the product spec runs end to end without
      intervention

### P5. Deploy artifacts

*not started · effort ~1 day · risk low*

**Goal.** Somebody else can run it.

A compose file, platform configuration, a documented environment, and deploy instructions.

Gate:

- [ ] A stranger following the README deploys successfully in under 15 minutes, tested
      on someone who has not seen the repository

### P6. Hardening

*not started · effort ~1.5 days · risk medium*

**Goal.** The parts that make it usable rather than demonstrable.

Reranking, tier-1 parsing, tracing wired up, red-team suite in CI, and a pass over error
states, empty states and accessibility.

Gate:

- [ ] Every state described in the product spec is implemented
- [ ] Lighthouse score at or above 90
<!-- end generated: roadmap-detail -->

## Influencing this

The stage order is fixed by dependency, not by preference. Retrieval cannot be
measured before there is a corpus, answers cannot be grounded before retrieval
works, and the change report needs a ledger to diff. Arguing to move a stage
earlier means arguing that its dependency is not real, which is a conversation
worth having in an issue.

What is genuinely open:

- **The contents of a gate.** If a criterion measures the wrong thing, say so.
  L2's original gate was written so that it could not go red on a 55-chunk
  corpus, and it was rewritten once that was noticed.
- **What goes inside a stage.** The gate fixes the outcome, not the
  implementation.
- **Anything not on this list at all.** A parser for a format nobody has covered,
  a provider adapter, a how-to guide. Those do not need a stage.

Open an issue with the `needs discussion` label, or start a thread in
Discussions. See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes land.
