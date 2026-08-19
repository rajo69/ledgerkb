# Product Spec: The Intelligence Engine

> **Design record, written 2026-08-07.** The product this library is eventually
> for: users, flows, states and the demo it should be able to run. None of it is
> built. Product work begins at P1, after the library reaches v1.0.0. It is a
> record of intent, not current reference. See [ROADMAP.md](../../ROADMAP.md).

**Version:** 1.0 · **Date:** 2026-08-07
**Companion docs:** [`00-research-log.md`](./00-research-log.md) (evidence) · [`02-architecture.md`](./02-architecture.md) (build)

---

## 1. What this is

**A workspace that turns a pile of scattered documents into a knowledge base you can interrogate, export, and, critically, *update* without losing the history of what you used to believe.**

The one-line positioning:

> Most tools answer questions about your documents. This one **maintains a position** on them, tells you when that position changes, and shows its working.

### 1.1 The insight the product is built on

Every "chat with your documents" tool is stateless. Ask the same question twice, get two independently-derived answers. Add a new document and nothing happens until someone asks the right question.

This product inverts that. Documents are **compiled once** into a persistent knowledge layer: entities, relationships, decisions, actions, risks, each carrying its evidence. Questions are answered *from the knowledge layer*, with the raw documents underneath for verification. When a new document arrives, the system **diffs it against what it already believes** and reports what changed.

That produces a capability nothing in the "upload a PDF and chat" category has: **a defensible answer to "has anything changed, and what does it mean?"**

### 1.2 Scope decisions taken from the brief

| Decision | Rationale |
|---|---|
| **No live data, no continuous ingest.** Manual refresh only. | Continuous-ingest machinery solves a problem this product does not have. A "Refresh" button is honest and demoable. |
| **Three ingest paths only:** one OAuth (Google Drive), link(s), file upload. | Enough surface to prove the connector abstraction without a quarter of connector work. |
| **The output is a picker, not a fixed report.** | Different users need different artifacts from the same corpus. |
| **Abstention is a first-class success state.** | The brief grades "says when there is insufficient evidence". We treat a clean refusal as a win, not a failure. |

---

## 2. Users

We are designing for three, in priority order.

### 2.1 The Newcomer, *primary*
Joins a project or a patch mid-flight. Faces two years of minutes, four half-finished workstreams, and no idea who owns what.
- **Needs:** orientation in under ten minutes; who's who; what's decided; what's still open.
- **Job:** *"Get me to the point where I can ask a sensible question in a meeting."*
- **Artifact:** `Briefing.pdf`.

### 2.2 The Custodian, *the differentiator*
Responsible for this body of knowledge over time. Officer, project lead, community organiser.
- **Needs:** to know what's gone stale, what contradicts what, which actions have no owner, and what a new document changed.
- **Job:** *"Tell me what I need to look at this month."*
- **Artifact:** `Governance_Guide.md` + the **Change Report**.

### 2.3 The Analyst, *proves the depth*
Wants the structure, not the prose. Feeding it onward into a graph tool, a database, another agent.
- **Needs:** machine-readable entities and relationships, explicit-vs-inferred distinction, confidence, source references.
- **Job:** *"Give me the network so I can query it my way."*
- **Artifact:** `Entities_Relationships.json` + `Knowledge_Graph.okf`.

> The Newcomer gets people in the door. **The Custodian is why they stay.** No competing tool serves them.

---

## 3. The core loop

```
CONNECT → COMPILE → INTERROGATE → EXPORT
                 ↖___________________↙
                      REFRESH
```

Everything else is detail.

---

## 4. Ingest

### 4.1 Design principle

Three connector types, **one interface**. Each yields a sequence of `(external_id, uri, bytes|text, native_metadata)`. Everything downstream is connector-agnostic. Adding SharePoint or Notion later is one adapter, not a pipeline change.

### 4.2 Connector A: Google Drive (OAuth)

**Flow:** Connect Google Drive → Google consent (`drive.file` only) → **Google Picker** opens → user selects files and/or folders → we index exactly those.

**Why the Picker, in the UI copy:**

> *"We can only see the files you pick. Not your Drive."*

That is literally true with `drive.file` and it is a strong trust statement for anyone handling council or community data. It also avoids Google's restricted-scope verification and security assessment entirely (see research §1.1), a product-unblocking decision disguised as a privacy feature.

**Behaviours**
- Folder selection is expanded at pick time; a **stored folder reference** is re-enumerated on refresh so new files in that folder are found.
- Native Drive metadata (`modifiedTime`, `owners`, `webViewLink`, MIME) is preserved as document metadata.
- Google-native formats are exported (Docs → text/markdown, Sheets → CSV).
- Revoked or trashed files are marked `unavailable` on refresh, **never deleted**, their assertions stay in history.

### 4.3 Connector B: Links

One field, four accepted shapes, auto-detected:

| Input | Behaviour |
|---|---|
| Single URL | Fetch and extract one page |
| Multiple URLs (newline/comma) | Batch, each becomes its own document |
| `sitemap.xml` | Enumerate, then let the user filter by path prefix before indexing |
| Domain + depth (`example.gov.uk`, depth 2) | Bounded crawl, same-origin, `robots.txt` respected, hard page cap |

**Rules**
- Every URL is previewed (title, word count, detected type) **before** indexing. No blind crawls.
- PDFs found at URLs route into the document parser, not the HTML extractor.
- A visible page budget with a running count. The user always knows what they are about to spend.

### 4.4 Connector C: Upload

Drag-and-drop or file picker. Accepts **multiple files** and **`.zip`**.

- Uploads go **browser → blob storage directly** (no server body-size limit), with progress per file.
- ZIPs are expanded server-side; **directory structure is preserved as metadata**: `2024/planning/minutes-04-12.pdf` yields year, category and type hints for free, which materially improves the metadata the brief asks for.
- ZIP safety: path traversal blocked, expansion-ratio bomb detection, per-file and total size caps, nested-archive depth limit.
- Accepted: PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, HTML, JSON, EML. Rejected types are listed explicitly rather than silently skipped.

### 4.5 The source list

After connecting, one table is the home of the workspace:

| Source | Type | Docs | Last refreshed | Status |
|---|---|---|---|---|
| Drive › Planning Committee | OAuth | 34 | 2 days ago | ● Ready |
| sheffield.gov.uk/committees | Link | 112 | 6 hours ago | ● Ready |
| archive-2024.zip | Upload | 58 | 12 days ago | ⚠ 3 failed |

Per-source: **Refresh**, **View documents**, **Disconnect** (keeps indexed content), **Delete** (removes it).

### 4.6 Refresh semantics: manual, cheap, honest

Pressing **Refresh** on a source:
1. Re-enumerates the source (folder contents, sitemap, URL list).
2. Content-hashes everything found.
3. Classifies each item: **unchanged** (skip entirely), **modified** (new document version), **new**, **disappeared**.
4. Re-ingests only what changed.
5. Runs **reconciliation** and produces a **Change Report** (§6).

Unchanged documents cost nothing. This is what makes manual refresh viable as a permanent design choice rather than a shortcut: a refresh over 200 documents where 3 changed processes 3 documents.

Also available: **Refresh all**, and an *optional* `pg_cron` weekly refresh per source, off by default.

---

## 5. Interrogate

### 5.1 The answer contract

Every answer is a structured object rendered into three visually distinct zones. This is not decoration. The brief explicitly requires separating facts from interpretation and stating when evidence is insufficient.

```
┌─ ANSWER ───────────────────────────────────────────────┐
│ The Attercliffe regeneration project is active. Phase 1 │
│ was approved on 12 March 2026.                          │
├─ FROM THE DOCUMENTS ──────────────────── 3 sources ────┤
│ ✓ "Phase 1 approved subject to funding confirmation"    │
│   Planning Committee Minutes, 12 Mar 2026, p.4     [↗]  │
│ ✓ "Attercliffe regeneration - status: active"           │
│   Q1 Project Register, 31 Mar 2026, row 12         [↗]  │
├─ INTERPRETATION ───────────────────────────────────────┤
│ ~ The funding condition appears unresolved, no later   │
│   document confirms it. Inferred from absence.          │
├─ NOT ANSWERED ─────────────────────────────────────────┤
│ ! No document states the current phase-2 timeline.      │
│   Coverage gap: nothing from this project after Mar 26. │
└────────────────────────────────────────────────────────┘
```

**Rules enforced in code, not by prompt:**
- Every `✓` fact carries a quote that has been **verified to exist in the cited chunk**. Fails verification → demoted or dropped.
- `~` interpretation is styled differently and never counted as a citation.
- `!` gaps name *what* is missing and *why*: a coverage window, an entity with no documents, a date range with nothing in it.
- **A confident wrong answer is a bug. An abstention with a named gap is correct behaviour.**

### 5.2 Query modes

| Mode | Route | For |
|---|---|---|
| **Ask** | Hybrid retrieval → rerank → grounded synthesis | Point questions |
| **Explore** | Entity-centred graph view + evidence | "Show me everything about X" |
| **Audit** | Contradictions, orphan actions, staleness | Custodian's weekly sweep |

### 5.3 Suggested questions

On an empty workspace we seed the brief's own examples: *What projects are currently active? What decisions have been made? Which actions remain outstanding? Who is responsible for each? What risks or blockers exist? Has any decision changed over time?*, plus one deliberately unanswerable probe, so users see abstention working before they hit it by accident.

---

## 6. The Change Report: the thing worth demoing

Triggered by any refresh that finds changes. This is the Shared Final Challenge, and it is the product's sharpest moment.

```
CHANGE REPORT · 7 Aug 2026 · 1 new document
Source: Planning Committee Minutes, 5 Aug 2026

  NEW KNOWLEDGE                                        4
  ├ Decision: Phase 2 budget approved (£2.4m)
  ├ Risk: Contractor availability flagged
  ├ Person: Priya Raman → Project Lead, Attercliffe
  └ Action: Funding confirmation - now COMPLETE

  STILL VALID                                         31
  └ 31 assertions re-confirmed by this document

  NOW OUTDATED                                         2
  ├ "Phase 2 timeline: Q4 2026"  →  superseded by Q1 2027
  │   was: Project Register, 31 Mar 26 · now: Minutes, 5 Aug 26
  └ "Action owner: unassigned"   →  now Priya Raman

  CONTRADICTIONS                                       1
  ⚠ Budget stated as £2.4m (Minutes, 5 Aug)
    vs      stated as £2.1m (Finance Report, 20 Jul)
    Both retained. Not merged. Needs a human.

  NEW QUESTIONS RAISED                                 2
  ├ Was the £2.1m figure revised, or is one wrong?
  └ Does the contractor risk affect the Q1 2027 date?

  [ View diff ]  [ Export change report ]  [ Mark reviewed ]
```

**Non-negotiable behaviours:**
- **Nothing is deleted.** Superseded assertions get `invalid_at` set and remain queryable. "What did we believe in June?" is answerable.
- **Contradictions are never blended into one answer.** The brief says so, and blending is the single most common failure of summarisation tools.
- Every line links to both sides of the evidence.

---

## 7. Export: the output picker

### 7.1 The picker

Multi-select. Any combination. "All of the above" is one click.

```
EXPORT KNOWLEDGE                              Workspace: Attercliffe

 ☑ Briefing.pdf                    Newcomer briefing + executive overview
   └ Exec overview · projects · people · decisions · actions · risks
     timeline · disagreements · open questions · 5 questions to ask next
     ▸ Audience:  ( ) Newcomer   (•) Executive   ( ) Full detail

 ☑ Knowledge_Graph.okf             Structured knowledge catalogue
   └ OKF v0.2 bundle (zipped) · markdown + YAML frontmatter · per-claim
     sources · trust tiers · staleness dates · index.md + log.md

 ☐ Entities_Relationships.json     Machine-readable semantic network
   └ Nodes, edges, confidence, explicit vs inferred, source refs
     ▸ Also emit:  ☐ GraphML   ☐ Mermaid   ☐ Cypher

 ☑ Governance_Guide.md             Two-year maintenance & ownership plan
   └ What ages fastest · what needs evidence · what needs an owner
     missing links · refresh cadence · review schedule

 ────────────────────────────────────────────────────────────────────
 ☑ Include change history (log.md / change reports)
 ☑ Include build receipt (models, versions, counts, coverage)

           [ Select all ]              [ Export 3 artifacts → ]
```

### 7.2 What each artifact is

#### `Briefing.pdf`
Typeset via Typst. Sections map to the brief's Challenge-4 list: executive overview, projects/topics, people and organisations, **decisions made**, **proposed decisions not yet confirmed** (kept separate: this distinction is usually lost), actions with owners and deadlines, risks and blockers, timeline, **disagreements and conflicting information**, unanswered questions. Closes with a one-page newcomer briefing and **the five most important questions to ask next**.

Every significant statement carries a source and date. Inferences are visually marked. Where sources conflict, both are printed.

#### `Knowledge_Graph.okf`
A **ZIP of a conformant OKF v0.2 bundle**, stated plainly in the manifest, because OKF is a directory format and inventing a single-file variant would break interop. Unzip and it validates.

```
knowledge_graph/
  index.md          okf_version: "0.2" - progressive-disclosure catalogue
  log.md            chronological history - every ingest, change, revision
  projects/         one .md per project
  people/           one .md per person
  organisations/
  meetings/
  decisions/        includes superseded ones, status: deprecated
  actions/
  risks/
```

Each concept file carries `type`, `title`, `description`, `sources[]` with per-claim footnotes, `generated: {by, at}`, `verified[]` where a human has reviewed, `status`, `stale_after`, and `tags`. Because the format is markdown, **it opens in Obsidian, VS Code, or a text editor**, a genuinely portable deliverable, not a proprietary blob.

#### `Entities_Relationships.json`
```jsonc
{
  "schema_version": "1.0",
  "generated_at": "2026-08-07T14:22:00Z",
  "workspace": "attercliffe",
  "nodes": [
    { "id": "person:priya-raman", "type": "Person", "label": "Priya Raman",
      "aliases": ["P. Raman"], "first_seen": "2026-08-05",
      "sources": ["doc:minutes-2026-08-05#p2"],
      "merged_from": [], "confidence": 1.0 }
  ],
  "edges": [
    { "id": "e_0412", "type": "is_assigned_to",
      "from": "action:funding-confirmation", "to": "person:priya-raman",
      "modality": "explicit", "confidence": 0.95,
      "valid_from": "2026-08-05", "valid_to": null, "invalid_at": null,
      "sources": [{ "doc": "doc:minutes-2026-08-05", "page": 2,
                    "quote": "Priya Raman to confirm funding by 30 September" }] }
  ],
  "superseded": [ /* edges with invalid_at set, and what replaced them */ ]
}
```
`modality` (`explicit` | `inferred`) and `confidence` are mandatory on every edge. The brief requires distinguishing inferred relationships and recording confidence for them.

Optional co-exports: **GraphML** (yEd/Gephi), **Mermaid** (paste into any markdown), **Cypher** (`CREATE` statements for Neo4j/Memgraph).

#### `Governance_Guide.md`
Not a generic essay. **Generated from the workspace's actual state**, which is what makes it worth having:

- **Ages fastest**: assertions ranked by computed `stale_after`, with the reasoning (deadlines, "subject to", quarterly cadence, explicit review dates).
- **Needs stronger evidence**: single-source claims, low-confidence inferences, claims resting on one ambiguous sentence.
- **Needs an owner**: actions with no assignee; projects with no responsible organisation.
- **Missing relationships**: entities that co-occur repeatedly but are never explicitly linked.
- **Where a future document changes the picture**: pending decisions, open conditions, unresolved contradictions.
- **Recommended cadence**: per source type, derived from observed publication rhythm.
- **Review schedule**: a 24-month calendar of what to re-check and when.

#### Build receipt
Ships with every export: document count and version hashes, models and versions used at each stage, chunk/entity/assertion counts, coverage window (earliest → latest document date), unresolved-duplicate count, contradiction count, retrieval configuration. Makes the export **reproducible and auditable** rather than a snapshot of unknown provenance.

### 7.3 Export mechanics
- Runs as a background job with progress; large workspaces do not block the UI.
- "All of the above" produces one ZIP with a top-level `MANIFEST.md`.
- Exports are addressable and re-downloadable; each is stamped with the workspace state it was built from.

---

## 8. Information architecture

```
Workspace
├── Sources          connect · refresh · status · errors
├── Documents        list · versions · parse quality · injection flags
├── Ask              query · answer · evidence · gaps
├── Explore          entity view · graph neighbourhood · timeline
├── Audit            contradictions · staleness · orphans · duplicates
├── Changes          change reports, newest first
└── Export           picker · history
```

Multi-workspace from day one. It is a `workspace_id` column and it prevents the "everything in one pile" failure the moment a second project appears.

---

## 9. States that must be designed

The states below are where this class of product usually feels broken. They are specified, not left to chance.

| State | Behaviour |
|---|---|
| **Empty workspace** | Three connect cards + a sample corpus button. Never a blank chat box. |
| **Compiling** | Per-document stage pipeline visible (`fetched → parsed → chunked → indexed → extracted`). Questions answerable against what's already indexed, with a banner saying coverage is partial. |
| **Partial failure** | 3 of 58 failed → named, with reason and **Retry**. The other 55 are fully usable. Never all-or-nothing. |
| **Unparseable document** | Marked `low confidence`, kept, excluded from extraction, flagged in the audit view. A scanned fax is not a crash. |
| **No answer** | The `!` block with named coverage gaps, not "I couldn't find anything". |
| **Contradiction** | Both sides shown side by side with sources. Never resolved silently. |
| **Injection detected** | Document badged *"contains text resembling instructions to an AI"*, quarantined text viewable, excluded from prompts. Presented as a finding. |
| **Possible duplicate entities** | Shown as a review queue, not auto-merged. One click to merge or reject; both are logged and reversible. |
| **Stale workspace** | Banner: *"Newest document is 94 days old. 12 assertions are past their review date."* → Refresh, or Audit. |

---

## 10. What we are deliberately not building

Named so scope stays honest.

| Not building | Why |
|---|---|
| Live / continuous ingest | Explicitly cut. Manual refresh is sufficient and honest. |
| Multi-tenant orgs, roles, SSO | Workspace-scoped auth only. |
| Document editing / annotation | Sources are immutable. That is the model. |
| A chat product with memory of the user | Knowledge is about the corpus, not the conversation. |
| Web search as a default answer path | Breaks traceability (research §2.6). Off by default, always labelled. |
| Fine-tuning anything | No evidence any of this needs it. |
| An agent framework | This is a pipeline with a query layer. Framing it as agents adds vocabulary, not capability. |

---

## 11. Success criteria

### 11.1 Product
1. A newcomer with zero context can connect a corpus and read a useful briefing **in under 10 minutes**.
2. Every factual claim in every artifact traces to a document, page and verbatim quote.
3. Adding one new document produces a change report that **a person who knows the material agrees with**.
4. The system abstains rather than guesses, and names the gap when it does.
5. Contradictions survive to the output instead of being smoothed away.

### 11.2 Measurable
| Metric | Target |
|---|---|
| Citation validity (quote present in cited chunk) | **100%**, enforced, not measured |
| Correct-abstention rate on unanswerable golden set | ≥ 90% |
| Retrieval failure rate (top-20, golden set) | ≤ 5% |
| Ragas faithfulness | ≥ 0.85 |
| Change-report precision (human-agreed changes) | ≥ 90% |
| Entity over-merge rate | ≤ 2% (over-merging is worse than under-merging) |
| Time-to-first-answer, 50-doc corpus | ≤ 5 min |

### 11.3 Demo script (5 minutes)
1. Drop a ZIP of council documents. Watch the pipeline compile. **(30s)**
2. Ask an answerable question → cited answer with facts and inference separated. **(45s)**
3. Ask an unanswerable one → clean abstention naming the gap. **(30s)**
4. Open Explore → the entity graph nobody could see by reading the documents individually. **(45s)**
5. **Drop the new document. Refresh. Read the change report**: decision superseded, action completed, contradiction flagged. **(90s)**
6. Export all four artifacts. Open the `.okf` bundle in a text editor to show it is portable markdown, not a black box. **(60s)**

Step 5 is the one that wins. Everything before it is table stakes.
