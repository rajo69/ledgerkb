# ledgerkb

A Python library for searching mixed documents with provenance you can check to
the character. It ingests eleven formats into SQLite, chunks on document
structure so every chunk's offsets slice back exactly to the source text
(property-tested with Hypothesis), flags instruction-shaped text at ingest, and
runs three-arm hybrid search (dense vectors, BM25, heading path) fused by
reciprocal rank fusion; `--explain` shows each arm's rank and the fused score. Embeddings
run locally: no API key, no server.

Where it is going: most tools answer questions about your documents. ledgerkb is
being built to keep a position on them, tell you when that position changes, and
show its working. Grounded answering, the assertion ledger and the change report
are the roadmap, not the present; [Status](#status) says exactly where it stands.

[![ci](https://github.com/rajo69/ledgerkb/actions/workflows/ci.yml/badge.svg)](https://github.com/rajo69/ledgerkb/actions/workflows/ci.yml)
[![offline](https://github.com/rajo69/ledgerkb/actions/workflows/offline.yml/badge.svg)](https://github.com/rajo69/ledgerkb/actions/workflows/offline.yml)
[![licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)
[![python: 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)

## The problem

A team accumulates two years of meeting minutes, reports, risk registers and
email. Every tool in this category answers questions about that pile and then
forgets. Ask the same question twice and you get two independently derived
answers. Add a new document and nothing happens until somebody thinks to ask the
right question again. Plenty of tools serve the person with a question. Nobody
serves the person who owns that body of knowledge over time.

## What it does today

```console
$ lkb ingest ./corpus
document                                      status    chunks  parser
action-log-2026-03.csv                        ingested       1  csv
annual-governance-statement-2025-26.pdf       ingested       1  pypdfium2
attercliffe-programme-board-2026-04.pptx      ingested       3  python-pptx
cabinet-minutes-2026-04-08.md                 ingested       4  text
footbridge-options-appraisal.docx             ingested       4  python-docx
planning-committee-minutes-2026-03-11.md      ingested       8  text
[14 more rows, elided]

20 ingested, 0 unchanged, 0 failed - 55 chunks

metadata coverage
  title                100%
  published_at         95%
  doc_type             100%
  meeting_or_project   95%
  uri                  100%

$ lkb search "who owns the footbridge decision?" --k 3 --explain
dense 50, headings 8, sparse 34 -> 3 shown

1. Footbridge Options Appraisal  0.0477
   Footbridge Options Appraisal Prepared for the Attercliffe Programme Board,
   8 April 2026.
   1220ab17  dense#1  headings#2  sparse#6

2. Planning Committee Minutes > Item 3: Attercliffe Regeneration Programme >
   Decision  0.0455
   ### Decision  The Committee RESOLVED to approve the revised capital
   allocation of £2.4m and to delegate authority for contract award to the
   Director of Regeneration.
   0b3abb1b  dense#5  headings#8  sparse#5

3. Newcomer Briefing: Regeneration Directorate > Who we are  0.0431
   ## Who we are  The Regeneration Directorate leads capital programmes across
   the city.
   0e22c996  dense#37  headings#1  sparse#1
```

No API key was set for either command. The third line under each result is the
chunk id and where every retrieval arm placed it: `dense#37 headings#1 sparse#1`
is a passage the vectors nearly lost and both keyword arms ranked first. (This
transcript was captured on 19 Aug 2026; the fixture corpus has since gained an
RTF document, and the offline CI ingest now reports 21 documents and 59 chunks.)

## Why it is different

**Chunk text is sliced, never constructed.** For every chunk,
`document_text[chunk.char_start:chunk.char_end] == chunk.text`, exactly. A
Hypothesis property test checks it over arbitrary input, including after
sanitisation, which deletes characters and remaps every offset. That is what
makes a citation a precise character span rather than a gesture at a page, and
what will let quote verification be mechanical instead of another model's
opinion.

**Invariants live in the database, not in convention.** The ledger's tables are
append-only by trigger before anything writes to them: deleting an assertion or
its evidence raises. A document version's content hash, text hash and ingest time cannot be updated: a trigger rejects it, so new content is a new row. The full-text
index follows a generated column by trigger, so the sparse index always matches
the stored chunk text, header included, even if a caller forgets to reindex.

**Tier-4 settings do not exist.** The append-only tables, required evidence,
path-traversal guards on archives and budget aborts have no configuration key at
any level, and quote verification, zero tools in extraction calls and unmerged
contradictions will ship the same way when their stages land.
The rule is that if a setting could make the system lie, it is not a setting. The
extension point is the Protocol ports instead: bring your own `Store`, `Parser`,
`Chunker`, `Reranker` or `ChatModel` and you have full power through code you own.

**It runs with no API key, and offline after a one-time model download.**
Ingest, chunking, embedding and retrieval all run in-process, with a local ONNX
embedder by default. A separate CI workflow runs the whole test suite plus a full
ingest inside a network namespace, and fails loudly if the network turns out to
be reachable, so a job that proves nothing cannot report green.

**Contradictions will never be merged.** When two sources disagree, both
assertions stay active and marked disputed, and the store never picks a winner.
That is the opposite of what most temporal knowledge systems do. The schema and
the rule are settled; the reconciliation that produces disputed pairs is L6 and
is not built. Retrieval already follows the rule: two documents in the fixture
corpus give different budget figures (£2.4m and £2.9m), both stay indexed, and
search ranks each on its own merits rather than choosing one.

## Status

<!-- generated: status. Edit docs/stages.toml, then run scripts/render_docs.py -->
**Current stage: L2, index and retrieve.** 3 of its 7 gate criteria are met.

- **Library** (L0 to L8): L0 and L1 done; L2 in progress; L3 to L8 not started.
- **Product** (P1 to P6): not started.

Documents go in and ranked passages come out. Ingest reads files, directories and ZIP
archives; tier-0 parsers cover eleven formats; the sanitiser strips invisible text and flags
instruction-shaped spans, recording each with its offsets in a quarantine table; the chunker
slices on document structure, and every chunk's character offsets slice back to identical
source text. Search runs three arms (dense, BM25 and heading path), fuses them by reciprocal
rank fusion, and explains where each arm placed every candidate. None of it needs an API
key, and after a one-time download of the local embedding model none of it needs the
network.

Grounded answering, the assertion ledger, the knowledge graph, the change report and the
exports are designed and gated but not built.

Which L2 criteria are outstanding, and what every other stage commits to, is in
[ROADMAP.md](ROADMAP.md).
<!-- end generated: status -->

## Install and first run

Requires Python 3.11 or newer. The no-API-key path is first because it is the
surprising one.

```bash
git clone https://github.com/rajo69/ledgerkb
cd ledgerkb

uv venv
uv pip install -e ".[local]" --group dev   # [local] adds the parsers and the local embedder

lkb init .          # writes ledgerkb.toml, profiles/default.toml and a migrated store
lkb doctor          # environment check. Succeeds with zero API keys set
lkb doctor --tiers  # every knob that exists, its tier, and what changing it costs
```

Then point it at some documents. Anything in PDF, DOCX, XLSX, PPTX, HTML, RTF,
EML, CSV, JSON, MD or TXT, as a file, a directory or a ZIP archive:

```bash
lkb ingest ./your-documents
lkb docs                     # what was ingested, with its metadata
lkb chunks <doc_id> --verify # re-slice every chunk from the stored text

lkb index                    # embeds in-process, no API key (model downloads once)
lkb search "your question" --explain
```

If you have no documents to hand, the fixture corpus generator makes twenty-one:

```bash
python tests/fixtures/build_corpus.py /tmp/demo && lkb ingest /tmp/demo/corpus
```

To use a hosted embedder instead, set `[embeddings]` in `ledgerkb.toml` to any
OpenAI-compatible endpoint (`[chat]` takes one too, for the answering stage,
L3). Configuration names an
environment variable rather than holding a key, so the file stays safe to commit.

As a library, the pieces are importable on their own. Rank fusion, for instance,
is pure and takes any number of named ranked lists:

```python
from ledgerkb.core.models import Hit
from ledgerkb.index.rrf import fuse

dense = [Hit(chunk_id=c, score=s, text="", method="dense")
         for c, s in [("budget", 0.91), ("footbridge", 0.88), ("membership", 0.71)]]
sparse = [Hit(chunk_id=c, score=s, text="", method="sparse")
          for c, s in [("footbridge", 9.2), ("scc-2026-114", 8.1), ("budget", 6.4)]]

for hit in fuse({"dense": dense, "sparse": sparse}, k=60)[:3]:
    print(hit.chunk_id, hit.ranks)
    #> footbridge {'dense': 2, 'sparse': 1}
    #> budget {'dense': 1, 'sparse': 3}
    #> scc-2026-114 {'sparse': 2}
```

`scc-2026-114` is the case for running both arms: a reference number the
embedding smooths into its neighbours, and BM25 finds it second.

## How it works

```
documents ──► read ──► dedupe by content hash ──► parse ──► sanitise ──► chunk
                          (unchanged: stop)      (tier 0)   (quarantine)  (structure-first)
                                                                            │
                                                                            ▼
              search ◄── fuse by rank ◄── dense + BM25 + heading arms ◄── embed
```

The design puts one append-only ledger of evidence-bearing assertions under all
of it, with the retrieval index, the knowledge graph, the wiki export, the
briefing and the change report as projections of that one ledger rather than
separate subsystems. The retrieval index is built, and it is what the
transcript above shows; the ledger (L4) and the other projections are on the
roadmap.

[ARCHITECTURE.md](ARCHITECTURE.md) has the code map, the invariants and where to
start reading.

## Who it is for

Three readers. Search with `--explain` serves the first today; the second and
third are what the ledger, the change report and the exports (L4 to L7) are
designed for.

**Somebody joining a body of work mid-flight.** Two years of minutes, four
half-finished workstreams, and nobody with time to explain. You need to know what
is going on, who is responsible, and what has already been decided, without
reading four hundred pages first.

**Somebody responsible for that body of work over time.** This is the one nothing
else serves. You already know what the documents say. What you cannot see is what
changed when the new report landed, which of last year's decisions have quietly
been superseded, which claims now rest on a single ageing source, and which
actions have no owner. A system that answers questions cannot tell you any of
that, because it has no memory of what it used to believe.

**Somebody who wants the structured data out.** Entities, relationships,
decisions with dates and evidence, in JSON, GraphML, Cypher or a flat table, to
push into a graph tool, a spreadsheet or a database of your own (the exports
stage, L7).

## How it compares

Fair comparison against the categories this will be confused with. Cells marked
"Planned" with a stage are `ledgerkb`'s design position for work that is not
built yet; the rest describe what runs today.

| | ledgerkb | Retrieval frameworks (LlamaIndex, Haystack) | Graph construction (Microsoft GraphRAG, LightRAG) | Agent memory (Graphiti, Mem0) |
|---|---|---|---|---|
| Conflicting sources | Planned (L6): both kept active and marked disputed; the store never picks a winner. Today retrieval returns each source on its own rank | Not modelled. Both passages are retrieved and the model reconciles them | Reconciled during entity and community summarisation | Graphiti invalidates the older fact and keeps it queryable; Mem0 updates the memory in place |
| Citation checking | Planned (L3): a quote absent from its cited chunk cannot reach the caller. Today every hit names its chunk, and every chunk's character span slices back exactly to the source | Source nodes are returned; verifying the quote is the application's job | Provenance back to source text units, with no verification step | Provenance back to episodes, with no verification step |
| Declining to answer | Planned (L3): a first-class outcome, with the coverage gaps named | Buildable, not built in | Not a design goal | Not a design goal |
| Running with no credentials | Yes, including embedding (a local ONNX model, downloaded once). A CI job runs the test suite and a full ingest with the network cut | Depends on configuration. Fully local paths exist | No. Extraction is LLM-driven throughout | No |
| Shape | A library on SQLite, no server; the `Store` port takes a backend of your own | A framework | A pipeline and framework | A service, or a library against a graph database |

All four are good at what they are for, and none of them is trying to do this.
Retrieval frameworks are the right tool when the question is the unit of work.
Graph construction frameworks build a richer graph than this will, at a cost
Microsoft's own reporting puts at tens of dollars per long document. Agent memory
systems are built for an agent's working memory over a conversation, not for a
document corpus somebody is accountable for. Pick this one today for retrieval
you can audit to the character; it is being built for the case where the thing
you care about is what changed.

## Roadmap

Fifteen gated stages: nine library stages ending at v1.0.0 on PyPI, then six
product stages. No stage begins until the previous stage's gate is green, and a
gate is a list of measurable checks rather than a feeling that the work is done.

[ROADMAP.md](ROADMAP.md) has every stage and every criterion, generated from
[`docs/stages.toml`](docs/stages.toml).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) walks a first change through end to end, from
clone to pull request, and lists the things that will get a pull request
rejected. Those are worth reading first, because they are the reasons the claims
above hold.

Most useful right now, in order:

1. **A parser for a format not yet covered.** ODT, EPUB, or a better PDF
   path. The `Parser` protocol is five lines and the registry makes it one
   registration.
2. **Questions for the L2 golden set.** The measurement corpus is 196 documents
   and 4,437 chunks. What it still needs is 40 questions, at least 7 of them
   unanswerable, written from the documents before retrieval is run.
3. **A how-to guide for a provider you actually use.** vLLM, LM Studio, TEI.
   If you got it working, that is the guide;
   [Run with Ollama](docs/how-to/run-with-ollama.md) is an example.

[Good first issues](https://github.com/rajo69/ledgerkb/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
are kept few and reviewed promptly, because the failure that matters is inviting
work and then not looking at it.

## Licence

Apache-2.0. See [LICENSE](LICENSE).

## Acknowledgements

Prompted by the Steel City AI challenge, set by Alex Paul Kelly.
