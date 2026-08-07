# Steel City AI — Intelligence Engine

Turning scattered information into usable knowledge.

An open-source Python library (`ledgerkb`) that compiles scattered documents into a queryable,
exportable knowledge base which **maintains a position over time** — and tells you what changed
when a new document arrives. A web product is built on top of it.

**Core idea:** one append-only ledger of evidence-bearing assertions. The RAG index, knowledge
graph, OKF wiki, briefing PDF and change report are all *projections* of that one ledger.

---

## Status

**L0 complete — the skeleton stands.** Core models, ports, config, the SQLite
store, deterministic fake providers and the CLI are in. Next is L1: readers,
tier-0 parsers, the sanitiser, the structure-first chunker and a 20-document
fixture corpus. Stage gates are in [`docs/03-IMPLEMENTATION-PLAN.md`](docs/03-IMPLEMENTATION-PLAN.md).

```bash
uv venv
uv pip install -e . --group dev
lkb init .          # config, profile, migrated store
lkb doctor          # works with zero API keys
lkb doctor --tiers  # every knob that exists, and what changing it costs
pytest              # 80 tests, no network, no credentials
```

Nothing in the test suite touches a provider. That is enforced, not hoped for:
a separate CI workflow runs the whole suite with egress blocked.

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
