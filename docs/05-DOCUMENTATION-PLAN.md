# Documentation Plan

**Version:** 1.0 · **Date:** 2026-08-19
**Purpose:** A complete, executable plan for rewriting this project's documentation so that a
stranger can understand it, use it, and contribute to it. Written to be run in a fresh session
with no prior context.

**Scope rule for the session that executes this:** do the documentation work described here and
nothing else. Do not grow the fixture corpus. Do not write the golden set. Those are the next
piece of work and they are deliberately out of scope, because documentation that is written
after a rush of feature work never gets written.

---

## 1. How to use this document

Read section 2 to learn where the project is. Read section 4 to understand why the plan is
shaped the way it is, so you do not re-litigate decisions that already have evidence behind
them. Read section 5 before writing a single word, because the style rules are strict and
retrofitting them is painful.

Then work through sections 7 to 12 in order. Each phase ends at a point where the repository is
consistent and you can stop.

Section 3 lists four decisions the project owner needs to make. Ask for them before starting
phase 2. Everything in phase 1 can proceed without them.

---

## 2. Where the project is

`ledgerkb` is a Python library, published from <https://github.com/rajo69/ledgerkb> under
Apache-2.0. It turns scattered documents into an append-only, bitemporal ledger of
evidence-bearing assertions. The retrieval index, the knowledge graph, a portable wiki export,
a briefing document and a change report are all projections of that one ledger rather than
separate subsystems.

The work is organised into fifteen gated stages: nine library stages (L0 to L8, ending at
version 1.0.0 on PyPI) and six product stages (P1 to P6). No stage begins until the previous
gate is green.

**Current position: L0 and L1 complete, L2 half complete.** The retrieval machinery is built
and merged. What remains in L2 is the measurement: a golden set, and numbers that show hybrid
retrieval beating either half alone. That measurement is blocked on the size of the fixture
corpus, which is documented in `docs/04-BUILD-HANDOFF.md` section 10.

### 2.1 What actually works today

This list matters more than any other content in this plan, because the largest single risk in
a documentation rewrite is claiming more than the code delivers.

| Capability | State |
|---|---|
| Ingest from files, directories and ZIP archives | Works |
| Tier-0 parsers for ten formats (PDF, DOCX, XLSX, PPTX, HTML, EML, CSV, JSON, MD, TXT) | Works |
| Unicode sanitisation, hidden-text removal, instruction quarantine | Works |
| Structure-first chunking with an exact-offset guarantee | Works, property-tested |
| SQLite store with FTS5, float32 vectors, append-only triggers | Works |
| In-process embedding with no API key | Works |
| Hybrid retrieval: dense, sparse and heading arms, fused by rank | Works |
| Retrieval scoped to current document versions | Works |
| Per-candidate rank explanation | Works |
| Grounded answering with verified quotes | Not built. L3 |
| Honest abstention with named gaps | Not built. L3 |
| Assertion ledger and extraction | Not built. L4 |
| Entity resolution and graph | Not built. L5 |
| Change report | Not built. L6 |
| Exports: wiki bundle, briefing, governance guide | Not built. L7 |
| Evaluation harness and observability | Not built. L8 |
| Web product | Not built. P1 to P6 |

Everything in the second block is design work with a written gate, not vapour, but it is not
code and the documentation must never imply otherwise.

### 2.2 What is unusual about it

These are the claims worth leading with, because they are true today and they are rare.

1. **Chunk text is sliced, never constructed.** For every chunk,
   `document_text[chunk.char_start:chunk.char_end] == chunk.text` exactly. A Hypothesis
   property test checks this over arbitrary input, including after sanitisation, which deletes
   characters and remaps every offset. This is what makes a citation a precise character span
   rather than a gesture at a page.
2. **Invariants live in the database, not in convention.** Deleting from the ledger raises. A
   version is immutable once written. The full-text index is a generated column maintained by
   trigger, so the dense and sparse indexes cannot disagree even if a caller forgets to
   reindex.
3. **Tier-4 settings do not exist.** Quote verification, zero tools in extraction calls, the
   append-only ledger, unmerged contradictions, required evidence, path-traversal guards and
   budget aborts have no configuration key at any level. The rule is that if a setting could
   make the system lie, it is not a setting.
4. **It runs with no API key and no network.** Ingest, chunking, embedding, retrieval and the
   whole test suite. A CI job runs the suite plus a full ingest inside a network namespace to
   prove it.
5. **Contradictions are never merged.** When two sources disagree, both assertions stay active
   and marked as disputed. The store never picks a winner. This is the opposite of what most
   temporal knowledge systems do.

---

## 3. Decisions, resolved

Answered by the project owner on 2026-08-19. Do not reopen these; build to them.

**D1. Name: `ledgerkb`, everywhere.** One name across the README, `pyproject.toml`, the GitHub
repository description, the documentation site and PyPI. No display name separate from the
package name. The README H1 becomes `ledgerkb` and stops naming the challenge event.

**D2. Description: use both, on different surfaces.** They do different jobs.

Short form, for `pyproject.toml`, the PyPI summary and the GitHub repository description. This
is already the value in `pyproject.toml`, so nothing needs to change there:

> Turn scattered documents into a knowledge base that maintains a position over time.

Long form, as the opening line of the README, directly under the H1:

> Most tools answer questions about your documents. This one keeps a position on them, tells you
> when that position changes, and shows its working.

The long form works because it names the category before naming the difference, which is what
gives a reader something to compare against in the first five seconds. If it reads as too long
in place, the clause to cut is "and shows its working", because the citation guarantee is
covered immediately below in the differentiators. Cut nothing else.

**D3. Documentation site: yes.** MkDocs with the Material theme, deployed to GitHub Pages by a
workflow. Build it in this pass, as phase 3.

**D4. Author: Rajarshi Nandi.** Full name in `pyproject.toml` `authors` and in `CITATION.cff`.
GitHub handle `@rajo69` in `CODEOWNERS`. Remove the challenge event from the `authors` field.

---

## 4. What the research says, and the strategy it implies

I researched what actually moves contributor numbers rather than assuming. The findings are
partly counterintuitive and they should shape the plan.

### 4.1 Documentation is necessary and not sufficient

A study of 4,226 README files and 714 CONTRIBUTING files from Debian-packaged projects found no
evidence that introducing either file causally increases contribution. Both tend to appear
after an influx of activity rather than before it, and both are usually published nearly empty:
median reading time was about 15 seconds for a README and 20 seconds for a CONTRIBUTING file.
The authors describe most such files as ritualistic.

Two content signals did correlate with later activity: READMEs containing installation
instructions, and CONTRIBUTING files containing code style guidance.

**Implication.** Do not expect the rewrite to produce contributors on its own. Treat
documentation as the thing that stops interested people from bouncing, and pair it with the
mechanisms in section 12 that actually correlate with contribution.

### 4.2 The real bottleneck is orientation, not willingness

The strongest single finding for a project of this shape: contributors unfamiliar with a
codebase take roughly ten times longer to work out *where* to make a change than people who
know it. The recommended fix is a short, stable `ARCHITECTURE.md` giving a bird's eye view, a
code map answering "where is the thing that does X", and an explicit statement of architectural
invariants, including invariants expressed as absences.

This project is 5,881 lines of source and 3,319 lines of tests across 25 modules, which is just
under the usual threshold where an `ARCHITECTURE.md` starts paying off. Its conceptual load is
well above its line count, and it crosses the threshold at L4. Write the file.

### 4.3 Good first issues work, but only with review capacity

A longitudinal study of 406,826 issues and 1,117 newcomer pull requests across 37 popular
repositories, covering July 2021 to June 2025, found newcomer engagement with issues labelled
"good first issue" stable at about 27 percent. Over the same period the merge rate of those
newcomer pull requests fell from 61.9 percent to 42.2 percent.

**Implication.** Labelling without reviewing is worse than not labelling, because it invites
people to spend effort that then goes nowhere. Only create good first issues you are willing to
review promptly. Section 12 sizes this deliberately small.

### 4.4 Structure the documentation set, do not just write more of it

Diátaxis separates documentation into four kinds by the need it serves: tutorials for learning,
how-to guides for a specific task, reference for looking things up, and explanation for
understanding. It is the most widely adopted framework of its kind, it is incremental, and
applying it to even part of a documentation set produces a benefit.

This project has an unusual amount of explanation material already written, buried inside design
documents. Reorganising is mostly moving and reframing rather than authoring from scratch.

### 4.5 Agent-readable repository conventions are now mainstream

`AGENTS.md` is read natively by more than 30 tools, is used by over 60,000 repositories, and is
stewarded by the Agentic AI Foundation under the Linux Foundation. This repository is largely
built by an AI agent working with a human, and the next several stages will be too, so the file
is not decoration here. It is the place to record the invariants an agent must not break.

`llms.txt` remains a community convention with contested value. Treat it as optional and low
priority.

---

## 5. Style rules

These are mandatory for every Markdown file in the repository. Section 11 adds a CI check so
they stay true.

### 5.1 Punctuation

**No em dashes.** Not one, if it can be avoided. The repository currently contains 327 of them
across the design documents and 8 in the README. Replace each with a comma, a colon, a full
stop, or parentheses, choosing by what the sentence actually needs. Where a dash genuinely is
the right mark, use a spaced hyphen.

Also avoid: semicolons used to staple two unrelated clauses together, and long parenthetical
asides mid-sentence.

### 5.2 Language

Write plainly. Say what a thing does and what it costs. Assume an experienced reader who is
short on time.

Do not use these patterns. They are the current signature of machine-written prose and readers
now discount text containing them:

- "X is not just Y, it is Z" and its variants
- "Let's dive in", "buckle up", "in today's fast-paced world"
- "seamlessly", "effortlessly", "robust", "leverage" as a verb, "delve", "elevate", "unlock",
  "harness", "empower", "game-changing", "cutting-edge", "revolutionise"
- "It is worth noting that", "It is important to understand that"
- Three-item lists used as a rhetorical rhythm rather than because there are three things
- Emoji as section markers or bullet decoration
- Bold applied to whole sentences for emphasis. Bold a term, not a paragraph.
- Rhetorical questions as headings
- Closing paragraphs that summarise what was just said

Prefer the concrete. "55 chunks from 20 documents" beats "a small corpus". "Runs with no API
key" beats "flexible deployment options".

Numbers and claims must be checkable. If a figure appears in a document, it should be
reproducible by running something.

### 5.3 Attribution

Remove every reference to the originating challenge event and the person who ran it from every
file except one line at the bottom of the README, under an "Acknowledgements" heading, phrased
as inspiration. Current occurrences:

- `README.md` line 1, in the H1 heading
- `README.md` line 71, in a "Source material" section
- `pyproject.toml` line 13, in the `authors` field

The two source PDFs sitting in the repository root are untracked and ignored by git. Leave them
on disk, remove the section of the README that describes them, and do not reference them in any
new file.

---

## 6. Known problems the rewrite must fix

These come from an audit run on 2026-08-15. They are documentation defects that exist right now.

1. **`docs/02-ARCHITECTURE.md` section 11 is a superseded build plan.** It instructs a reader to
   start with Postgres, Railway, FastAPI and Next.js, which contradicts the locked decision that
   SQLite is the default store and the library ships before any product. Section 12 item 2 says
   "Postgres for everything" for the same reason. Section 14 lists open questions that are
   resolved elsewhere. Mark all three as superseded, in place, with a pointer to what replaced
   them.
2. **Governance claims that are not true.** `docs/04-BUILD-HANDOFF.md` section 9 states that the
   default branch is protected, that pull request review is required, and that Renovate,
   Conventional Commits and DCO sign-off are enforced. Renovate now exists. The branch is not
   protected, review is not required, and there is no DCO check. Either enable them or move them
   to a "planned" list.
3. **A self-contradictory claim about injection fixtures.** Several files say "10/10 injection
   fixtures caught with the benign decoy untouched". There are ten fixtures: nine attacks and
   one deliberate benign decoy. State it as "nine attacks caught, benign decoy untouched".
4. **Workflow inventory is wrong.** Files list five CI workflows. Three exist: `ci.yml`,
   `offline.yml`, and whatever this plan adds. `drift.yml`, `redteam.yml` and `release.yml` are
   planned for L8.
5. **A documentation site is described that does not exist.** No `mkdocs.yml` is present.
6. **Stage status is stated in prose in at least four files** and has already drifted once.
   Phase 1 fixes the cause rather than the symptom.

---

## 7. Phase 1: one source of truth for status

Do this first. Every document that states where the project is will be generated from it, so
nothing downstream can drift.

### 7.1 `docs/stages.toml`

A machine-readable description of all fifteen stages. Sketch:

```toml
schema_version = 1
current = "L2"

[[stage]]
id = "L0"
track = "library"
title = "Skeleton and contracts"
status = "done"              # done | in-progress | not-started
goal = "The shape everything else fills in."
summary = "Domain models, Protocol ports, config with four tunability tiers, the SQLite store and its migrations, deterministic fake providers, and the first CLI commands."
ships = ""                   # version this stage releases, if any
gate = [
  { text = "Clean install on three operating systems, under 60s and under 120MB", met = true },
  { text = "mypy --strict passes on core", met = true },
  { text = "lkb init and lkb doctor succeed with zero API keys", met = true },
  { text = "Every core model round-trips through SQLite unchanged", met = true },
]
```

Fill every stage from `docs/03-IMPLEMENTATION-PLAN.md`, which already contains the goals, the
gate criteria, the effort estimates and the risk ratings. Mark L2's gate items honestly: the
retrieval machinery items are met, the measurement items are not.

### 7.2 `scripts/render_docs.py`

A small script, standard library plus `tomllib` only, that reads `stages.toml` and writes
generated regions into `README.md` and `ROADMAP.md`. Use explicit markers:

```markdown
<!-- generated: status. Edit docs/stages.toml, then run scripts/render_docs.py -->
...generated content...
<!-- end generated: status -->
```

Two modes:

- default: rewrite the files in place
- `--check`: regenerate into memory, compare, exit non-zero with a diff if anything differs

Regions to generate:

- `status` in README: the current stage, one line per track, and a short "what works today"
  summary
- `roadmap-table` in ROADMAP: all fifteen stages with status
- `roadmap-detail` in ROADMAP: per-stage goal, summary and gate checklist

Keep the generated content small and let the prose around it stay hand-written. Generated
documentation reads badly when it tries to do everything.

### 7.3 Wire it into CI

Add a `docs` job to `.github/workflows/ci.yml`, or a new `docs.yml`, that runs
`python scripts/render_docs.py --check`. A stage status change that does not regenerate the
documents fails the build.

---

## 8. Phase 2: root documents

### 8.1 `README.md`, full rewrite

This is the highest-value file in the repository. Structure, in order, because the first screen
does most of the work:

**1. Name and one line.** The name from D1, the description from D2. No heading decoration.

**2. Badges.** CI status, coverage, licence, supported Python versions. Add PyPI and downloads
at L3 when the package is published. Four to six badges. More reads as noise.

**3. The problem, in about four lines.** Concrete and specific. Something close to: a team
accumulates two years of meeting minutes, reports, risk registers and email. Every tool in this
category answers questions about that pile and forgets. Ask twice, get two independently derived
answers. Add a document and nothing happens until somebody thinks to ask the right question.
Nobody serves the person who owns that body of knowledge over time.

**4. What it does, shown as a terminal transcript.** Real commands with real output, copied from
an actual run, not invented. Today the honest demonstration is ingest followed by a search with
per-arm explanation. Keep it under 25 lines. When L6 lands, replace it with the change report,
which is the strongest thing this project will ever show.

**5. Why it is different.** The five points from section 2.2 of this plan, one or two sentences
each. This is the section that earns a star. Do not pad it and do not add anything that is not
yet true.

**6. Status.** Generated region from phase 1. Honest about L2 being half done.

**7. Install and first run.** Installation instructions correlate with contribution, per section
4.1, so make them exact and make them tested. Include the no-API-key path first because it is
the surprising one.

**8. How it works.** A six to eight line pipeline sketch, then a link to `ARCHITECTURE.md`. Do
not try to explain the architecture in the README.

**9. Who it is for.** Three short paragraphs: someone joining a body of work mid-flight, someone
responsible for it over time, someone who wants the structured data out of it. The middle one is
the differentiator and should read like it.

**10. How it compares.** A short, fair table against the categories it will be confused with:
general retrieval frameworks, graph-construction frameworks, and temporal memory systems for
agents. Compare on axes this project actually differs on: whether contradictions are preserved
or resolved, whether citations are verified mechanically, whether the system will decline to
answer, whether it runs without credentials. Name real projects, describe them accurately, and
do not build a strawman. A reader who catches an unfair comparison discounts everything else on
the page.

**11. Roadmap.** Three lines and a link to `ROADMAP.md`.

**12. Contributing.** Link to `CONTRIBUTING.md`, and a direct link to the good-first-issue
filter. Say what kind of help is most useful right now, specifically.

**13. Licence.** Apache-2.0, one line.

**14. Acknowledgements.** One line naming the challenge that prompted the work. This is the only
permitted mention.

Target length: 250 to 350 lines. Long enough to answer the obvious questions, short enough to
scroll.

### 8.2 `ARCHITECTURE.md`, new, at the repository root

Follow the established shape for this kind of file. Keep it short and stable, describing only
things unlikely to change often, and revisit it a few times a year rather than trying to keep it
synchronised with the code.

Sections:

1. **Bird's eye view.** The problem, and the single organising idea: one append-only ledger of
   evidence-bearing assertions, everything else a projection of it. Reuse the diagram from
   `docs/02-ARCHITECTURE.md` section 1, which is good.
2. **Code map.** Every top-level module under `src/ledgerkb/`, one short paragraph each: what
   lives there, what it is responsible for, what it must not do. Name files and types, but do
   not hyperlink them. Symbol search needs no maintenance and teaches the reader the codebase.
   Cover: `core`, `storage`, `providers`, `ingest`, `index`, `extract`, `ledger`, `project`,
   `evals`, `obs`, `cli`. Say plainly which of these are still empty.
3. **Invariants.** State them as rules with the mechanism that enforces each one. Include the
   invariants that are absences: no configuration key for tier-4 settings, no delete path on the
   ledger, no code branch for a specific corpus, no LLM call where deterministic code will do.
   Absences are exactly what a newcomer cannot infer from reading the source.
4. **Cross-cutting concerns.** The offset guarantee, the four tunability tiers, the layering
   contract enforced by import-linter, error handling and the "fail loud, degrade gracefully"
   rule, and the rule that everything works offline by default.
5. **Where to start reading.** Three or four named entry points for someone making their first
   change.

Target length: 200 to 300 lines.

### 8.3 `ROADMAP.md`, new

Mostly generated. Hand-written parts: a short preamble explaining the gating rule and what the
gate colours mean, then the generated table and per-stage detail, then a short section on how to
influence the roadmap.

Make the gating rule prominent, because it is unusual and it explains why the project looks
slow. No stage begins until the previous gate is green, and a gate is a measurable check rather
than a feeling.

### 8.4 `CONTRIBUTING.md`, rewrite

The existing file is good in substance. The section listing what will get a pull request
rejected is genuinely distinctive and should survive almost unchanged. Keep it and add:

- **A first change, walked through end to end.** Clone, install, run the suite, make a small
  change, run the checks, commit with sign-off, open the pull request. Concrete commands. This
  is the single highest-leverage addition.
- **What the checks are and what each one protects.** `ruff`, `mypy` strict on core,
  `lint-imports` for the purity and layering contracts, `pytest`, the coverage ratchet, the
  dependency floors job. Explain why each exists in one sentence.
- **Definition of done.** A checklist that includes documentation: any change that alters
  behaviour updates the relevant document in the same pull request, and any stage status change
  updates `docs/stages.toml` and regenerates.
- **Review expectations.** How quickly you intend to respond, and what happens to a pull request
  that goes quiet. Section 4.3 shows that unreviewed newcomer contributions are the failure mode
  that matters. Promise something you can keep.
- **Where help is most wanted.** Be specific and current.

Fix the stage number, which currently says L1.

### 8.5 Smaller root files

- **`SUPPORT.md`**, new. Where to ask what: issues for bugs, discussions for questions, security
  advisories for vulnerabilities. Ten lines.
- **`GOVERNANCE.md`**, new and short. Who decides, how decisions get recorded, and how that
  changes if the project grows. Honest single-maintainer governance is better than a fictional
  committee. Point at the decision record and at the tier-4 rule as the constitutional part.
- **`CITATION.cff`**, new. GitHub renders a "Cite this repository" link from it. Cheap, and it
  matters if any of this ends up referenced in writing.
- **`AGENTS.md`**, new. 30 to 60 lines. Stack, commands, the invariants an agent must not break,
  the style rules from section 5, and the definition of done. Keep it short and add to it only
  when an agent repeatedly makes a specific mistake.
- **`SECURITY.md`**, keep. The threat model section is good. Update it to note that the CLI
  escapes document-controlled text before printing, which was fixed on 2026-08-19.
- **`CODE_OF_CONDUCT.md`**, keep as is.
- **`CHANGELOG.md`**, add the L2 entries. Keep the existing format.

### 8.6 `.github/`

- **`CODEOWNERS`**, new.
- **`pull_request_template.md`**, update with the definition of done checklist.
- **Issue templates.** Keep the two that exist. Add a documentation template. Consider
  converting to issue forms, which validate better than free text.
- **`FUNDING.yml`**, only if the owner wants it.

---

## 9. Phase 3: the documentation site

Only if D3 is yes.

Use MkDocs with the Material theme, deployed to GitHub Pages by a workflow. Organise by
Diátaxis, which splits material by the need it serves:

```
docs/
  index.md               landing page, short, points at the four sections
  tutorial/
    first-knowledge-base.md    ingest a folder, search it, inspect a citation
  how-to/
    ingest-your-own-documents.md
    run-without-an-api-key.md
    use-a-hosted-provider.md
    tune-retrieval.md
    add-a-parser.md            the Protocol ports, as a worked example
  reference/
    cli.md                     every command and flag
    configuration.md           every key, its tier, and what changing it costs
    data-model.md              the core models
    ports.md                   the Protocol surface
    store-schema.md            tables, triggers, migrations
  explanation/
    the-ledger.md              why one ledger with projections
    citations-and-offsets.md   the offset invariant and why it matters
    determinism.md             why checks are code and not model calls
    tunability-tiers.md        the four tiers and the rule behind them
    security-model.md          injection as an architectural problem
  design/                      the existing 00 to 04 documents, moved
    00-research-log.md
    01-product-spec.md
    02-architecture.md
    03-implementation-plan.md
    04-build-handoff.md
    05-documentation-plan.md   this file
  adr/                         from here on, one file per significant decision
```

Two rules for the move:

1. **Do not rewrite the design documents wholesale.** They are a record of how the project got
   here and they have value as a record. Add a short header to each saying what it is, when it
   was written, and that it is a design record rather than current reference. Fix only the
   superseded sections listed in section 6, and the em dashes.
2. **Most explanation pages already exist** inside those documents. Extract and tighten rather
   than writing from scratch.

`reference/configuration.md` can be generated from `core/config.py`, which already carries the
tier as field metadata and has a `tier_table()` function backing `lkb doctor --tiers`. Generate
it and check it in CI, the same way as phase 1.

---

## 10. Phase 4: keeping documentation current automatically

This is the part the owner specifically asked for. Four mechanisms, in descending order of
value.

### 10.1 Generated status, checked in CI

Phase 1. Nothing that is generated can drift, and CI enforces regeneration.

### 10.2 Executable documentation

`pytest-examples` is already a declared development dependency and has never been used. Wire it
so that code blocks in `README.md`, the tutorial and the how-to guides are executed as tests.

A quickstart that CI runs cannot rot. This is worth more than any amount of review discipline,
and for this project it is close to free.

Practical notes: mark blocks that cannot run, for example ones needing a hosted provider, with a
directive so they are skipped rather than silently ignored. Keep the executed blocks short.

### 10.3 A documentation lint

A CI job, or an extension of the existing static job, that fails on:

- any em dash (U+2014) in a tracked Markdown file, outside fenced code blocks, since a
  rule about a character has to be able to quote the character
- any word from the banned list in section 5.2
- a relative link that does not resolve
- a stage status in prose outside a generated region, found by pattern

Write it as a small Python script under `scripts/`. Around 60 lines. Keep the banned-word list
in a file so it can be extended without touching code.

### 10.4 Definition of done, enforced socially and then mechanically

Put the same checklist in three places so it is unavoidable: `CONTRIBUTING.md`, the pull request
template, and `AGENTS.md`. It should say:

- Behaviour changed? Update the reference page for it in the same pull request.
- Stage status changed? Update `docs/stages.toml` and run the renderer.
- New capability? Add or update the how-to guide.
- Invariant added or changed? Update `ARCHITECTURE.md`.
- Anything user-visible? Add a `CHANGELOG.md` entry.

Later, add a CI check that a change touching `src/ledgerkb/cli/` also touches
`docs/reference/cli.md`. Start with the checklist and add the mechanism when it is proven
necessary.

---

## 11. Phase 5: the contributor on-ramp

Documentation gets people to the point of wanting to help. This is what happens next.

1. **Labels.** `good first issue`, `help wanted`, `documentation`, `needs discussion`, and one
   per stage (`L2`, `L3`, and so on) so the roadmap and the issue tracker line up.
2. **Between five and ten good first issues, no more.** Section 4.3 is the reason for the cap:
   newcomer pull request merge rates have been falling because projects label faster than they
   review. Each one needs a description of the problem, a pointer to the file, an idea of the
   shape of the fix, and how to verify it. Genuine candidates in this repository today:
   - Add a parser for a format not yet covered, behind the existing `Parser` port
   - Extend the fixture corpus generator with a new document type
   - Add `lkb doctor` output for which projections are stale
   - Improve the `--explain` output formatting
   - Write a how-to guide for running against Ollama
3. **A public statement of review turnaround** in `CONTRIBUTING.md`, and keeping it.
4. **Enable GitHub Discussions**, and answer in it.
5. **Branch protection on the default branch**, so the claim in the documentation becomes true.

---

## 12. Acceptance checks

The documentation phase is done when all of these pass.

- [ ] `python scripts/render_docs.py --check` exits zero, and fails if `stages.toml` is edited
      without regenerating
- [ ] No tracked Markdown file contains U+2014, checked by the lint rather than by a grep
      that would itself contain the character
- [ ] The documentation lint passes
- [ ] Every code block in the README and tutorial runs in CI
- [ ] No tracked file mentions the originating event except one line in the README
      acknowledgements
- [ ] `pyproject.toml` carries a real author, and matches `CITATION.cff` and `CODEOWNERS`
- [ ] Every relative link in every Markdown file resolves
- [ ] `ARCHITECTURE.md` names every module under `src/ledgerkb/` and says which are empty
- [ ] The README states the current stage and it matches `stages.toml`
- [ ] No document claims a capability from the "not built" half of section 2.1
- [ ] The GitHub community standards checklist is complete
- [ ] A person who has never seen the repository can install it and run the quickstart from the
      README alone. Test this on somebody, not by inspection.

That last one is the only check that matters if the others pass and it fails.

---

## 13. Out of scope for the documentation session

- Growing the fixture corpus
- Writing the golden set
- Any change to `src/` beyond what the documentation lint or the renderer require
- Renaming the package, unless D1 comes back as a rename, in which case do it first and
  separately
- The product documentation for P1 to P6, which do not exist yet

---

## 14. Suggested order of work

1. Read section 3. The decisions are made; build to them.
2. Phase 1: `stages.toml`, the renderer, the CI check. Commit.
3. Strip the attribution and the em dashes across all existing files, mechanically. Commit.
4. `ARCHITECTURE.md`. Commit.
5. `README.md`. Commit. This is the one to spend the most time on.
6. `ROADMAP.md`, `CONTRIBUTING.md`, and the smaller root files. Commit.
7. Fix the superseded sections listed in section 6. Commit.
8. Phase 3, the documentation site, if D3 is yes. Commit.
9. Phase 4, the lint and the executable examples. Commit.
10. Phase 5, labels and issues. This is repository configuration rather than code.

Each numbered step leaves the repository consistent. Stop after any of them.

---

## 15. Sources

Research conducted 2026-08-19.

- [The Introduction of README and CONTRIBUTING Files in Open Source Software
  Development](https://arxiv.org/html/2502.18440v2), on documentation timing and content, and
  the absence of a causal link to contributor growth
- [A Longitudinal Analysis of Good First Issue Practices and Newcomer Pull
  Requests](https://arxiv.org/html/2604.27532v2), on labelling, engagement and falling merge
  rates
- [ARCHITECTURE.md](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html), on codebase
  orientation and the ten times figure
- [Diátaxis](https://diataxis.fr/), the four-way documentation split
- [The secrets to onboarding new open source
  contributors](https://github.com/readme/featured/contributor-onboarding), GitHub's own write-up
- [AGENTS.md specification](https://asdlc.io/practices/agents-md-spec/) and
  [best practices](https://www.betterclaw.io/blog/agents-md-best-practices)
- [GitHub community health files](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
  and [CITATION files](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files)
- [OpenSSF Best Practices Badge](https://www.bestpractices.dev/en/criteria/0), a checklist worth
  reading even if the badge is not pursued
- [State of llms.txt 2026](https://presenc.ai/research/state-of-llms-txt-2026), on why it is
  optional
