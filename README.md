# Steel City AI — Intelligence Engine

Turning scattered information into usable knowledge.

An open-source Python library (`ledgerkb`) that compiles scattered documents into a queryable,
exportable knowledge base which **maintains a position over time** — and tells you what changed
when a new document arrives. A web product is built on top of it.

**Core idea:** one append-only ledger of evidence-bearing assertions. The RAG index, knowledge
graph, OKF wiki, briefing PDF and change report are all *projections* of that one ledger.

---

## Status

**L1 complete. L2 half done — documents go in, hybrid retrieval comes out.**
Core models, ports, config, the SQLite store, tier-0 parsers for ten formats,
the sanitiser, the structure-first chunker, the OpenAI-compatible and local
provider adapters, embedding, RRF and three-arm hybrid search are in. What is
left in L2 is the measurement: a golden set, and the numbers that prove hybrid
beats either half. Stage gates are in
[`docs/03-IMPLEMENTATION-PLAN.md`](docs/03-IMPLEMENTATION-PLAN.md).

```bash
uv venv
uv pip install -e ".[local]" --group dev

lkb init .                 # config, profile, migrated store
lkb doctor                 # works with zero API keys
lkb doctor --tiers         # every knob that exists, and what changing it costs

lkb ingest ./documents     # PDF, DOCX, XLSX, PPTX, HTML, EML, CSV, JSON, MD, TXT, ZIP
lkb docs                   # what was ingested, with its metadata
lkb chunks <id> --verify   # re-slice every chunk from the stored text

lkb index                  # embed, in-process, no API key
lkb search "who owns the footbridge decision?" --explain

pytest                     # full suite, no network, no credentials
```

**Retrieval runs three arms and fuses them by rank.** Dense finds the passage
that never uses your words; BM25 finds `SCC/2026/114` and every other reference
number an embedding smooths away; and a third arm matches the heading path
(*"Planning Committee Minutes > Item 4 > Decision"*), which costs one FTS query
and no model at all. `--explain` prints where each arm placed every candidate
and what the fused score was.

Nothing in the test suite touches a provider, and no stage up to here needs an
API key — embedding included, because the default embedder runs in-process. That is enforced, not hoped for: a separate CI workflow runs the whole
suite, and a full ingest, with egress blocked.

**The invariant everything rests on:** for every chunk,
`document_text[chunk.char_start:chunk.char_end] == chunk.text`, exactly. Chunk
text is sliced, never constructed. That is what makes a citation a precise span
rather than a gesture at a page, and what lets quote verification be mechanical
instead of another model's opinion.

## Documents

| Doc | What it covers |
|---|---|
| [`docs/04-BUILD-HANDOFF.md`](docs/04-BUILD-HANDOFF.md) | **Start here.** Locked decisions, open questions, L0/L1 scaffolding, CI |
| [`docs/03-IMPLEMENTATION-PLAN.md`](docs/03-IMPLEMENTATION-PLAN.md) | Gated stages L0–L8 (library) and P1–P6 (product), with exit criteria |
| [`docs/02-ARCHITECTURE.md`](docs/02-ARCHITECTURE.md) | Data model, pipeline, retrieval, exports, costs, risks, decision record |
| [`docs/01-PRODUCT-SPEC.md`](docs/01-PRODUCT-SPEC.md) | Users, flows, output picker, states, success criteria, demo script |
| [`docs/00-RESEARCH-LOG.md`](docs/00-RESEARCH-LOG.md) | Every technology choice with evidence, verdict, and what couldn't be verified |

## Source material

Two PDFs — the Steel City AI challenge brief by Alex Paul Kelly, and the original
Technical PRD this plan revises — are kept out of the repository. Everything
derived from them is in `docs/`.

## Deliverables it produces

| Artifact | What it is |
|---|---|
| `Briefing.pdf` | Newcomer briefing + executive overview |
| `Knowledge_Graph.okf` | OKF v0.2 bundle (zipped) — portable markdown, opens in any editor |
| `Entities_Relationships.json` | Machine-readable semantic network (+ GraphML / Mermaid / Cypher) |
| `Governance_Guide.md` | Two-year maintenance and ownership plan, generated from live state |
| Change report | What's new, still valid, outdated, contradicted — with preserved history |

## Licence

Apache-2.0 (planned). Contributions via DCO sign-off.
