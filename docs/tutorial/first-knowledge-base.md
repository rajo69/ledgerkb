# Your first knowledge base

Twenty minutes, from nothing to a searchable corpus with a citation you can
verify. No API key, no network beyond the install, no account anywhere.

By the end you will have ingested twenty documents in ten formats, searched them
three different ways, and checked that a citation points at exactly the characters
it claims to.

## Before you start

Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/rajo69/ledgerkb
cd ledgerkb
uv venv
uv pip install -e ".[local]" --group dev
```

`[local]` brings the tier-0 parsers and the in-process embedder. That is the
difference between needing an API key and not.

## 1. Make a workspace

```bash
mkdir ~/lkb-tutorial && cd ~/lkb-tutorial
lkb init .
```

Three things now exist: `ledgerkb.toml` with every knob at its default,
`profiles/default.toml` with the generic domain vocabulary, and `.lkb/store.db`
migrated to the current schema.

Check the environment:

```bash
lkb doctor
```

It reports the config it found, the profile, the store and its row counts, and the
configured models. The line that matters is near the bottom:

```
embed    mixedbread-ai/mxbai-embed-large-v1  1024 dims (locked after first index)
         no key set - ingest, chunking, retrieval and every eval still run.

ok - the deterministic path is fully operational.
```

No key is set, and nothing in this tutorial needs one.

## 2. Get some documents

If you have a folder of your own, use it. If not, the repository can generate a
corpus of twenty council-shaped documents across ten formats:

```bash
python /path/to/ledgerkb/tests/fixtures/build_corpus.py ./demo
```

That writes `./demo/corpus` with twenty documents, plus `./demo/injections` and
`./demo/archives`, which are the hostile fixtures the test suite uses. Ignore
those two for now.

## 3. Ingest

```bash
lkb ingest ./demo/corpus
```

```
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
```

Read the last block. Metadata coverage is reported rather than assumed, and the
two 95% figures mean one document each had no recoverable date and no recoverable
programme. Those are misses, recorded on the version, not silent nulls.

Run the same command again. Everything comes back `unchanged`, because dedupe is
by content hash and happens before parsing. An unchanged document costs one hash,
not one parse. That is the property that makes refresh nearly free at L6.

## 4. Look at what arrived

```bash
lkb docs
```

```
id        title                 type      date        meeting/project        chunks
d991ce28  action-log-2026-03.…  register  2026-04-30  Programme              1
641810dc  Annual Governance     policy    -           The Council            1
          Statement
409d4957  Attercliffe drawdown  report    2026-04-14  Following Cabinet      1
          profile
```

The `-` in the date column is one of the two misses. Nothing was invented to fill
it.

## 5. Search, without embedding anything

Search works before you index. The dense arm simply does not run.

```bash
lkb search "capital allocation" --k 3
```

You get BM25 and heading-path results. This is worth doing once, because it makes
the next step's difference visible.

## 6. Index and search properly

```bash
lkb index
```

```
embedding 55 chunks with mixedbread-ai/mxbai-embed-large-v1 (1024 dims, local)
55 embedded in 1 batches
superseded versions are kept, but not indexed
```

The model downloads the first time and then runs in-process. No key, no request.

Now the interesting command:

```bash
lkb search "who owns the footbridge decision?" --k 3 --explain
```

```
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

The last line of each result is the argument for hybrid retrieval. Result 3 placed
37th in the dense arm and 1st in the heading arm, so on a dense-only system it
would not have been shown at all. Try it:

```bash
lkb search "who owns the footbridge decision?" --k 3 --arms dense
lkb search "who owns the footbridge decision?" --k 3 --arms sparse
lkb search "who owns the footbridge decision?" --k 3 --arms headings
```

Three different orderings from three different notions of relevance. Fusing them
by rank is what `--arms dense,sparse,headings` does, and rank is used rather than
score because a cosine similarity and a BM25 score are not on the same scale.

## 7. Notice the contradiction

Search for the budget:

```bash
lkb search "capital budget Attercliffe" --k 4
```

Two documents disagree. The Planning Committee minutes of 11 March approve
£2.4m. The Cabinet minutes of 8 April note £2.9m, superseding it. Both come back,
and at L6 that pair becomes a `contradicted` change event with both assertions
kept active rather than one of them being quietly dropped.

## 8. Verify a citation

Take a document id from `lkb docs` and ask for its chunks:

```bash
lkb chunks 07920375 --verify
```

```
8 chunks from version b6d2b10b (text, quality 1.00)
all chunks slice back byte-identical

0 Planning Committee Minutes 0:92 ~23 tokens
  # Planning Committee Minutes  **Date:** 11 March 2026 **Venue:** Town Hall,
Committee Room 2

4 Planning Committee Minutes > Item 3: Attercliffe Regeneration Programme >
Decision 581:746 ~41 tokens
  ### Decision  The Committee RESOLVED to approve the revised capital allocation
of £2.4m and to delegate authority for contract award to the Director of
Regeneration.
```

`581:746` is a character range in the stored document text, and `--verify`
re-slices every chunk at its recorded offsets and confirms it comes back
byte-identical. That is the invariant everything else rests on: a citation is a
span, not a gesture at a page. See
[Citations and offsets](../explanation/citations-and-offsets.md).

## 9. See every knob that exists

```bash
lkb doctor --tiers
```

Every configuration key, its tier, and what changing it costs. Keys you do not
find in that list do not exist, deliberately. See
[Tunability tiers](../explanation/tunability-tiers.md).

## The same thing from Python

The CLI is a thin layer. Everything it does is available directly, which is how
you would embed this in something else:

```python
import tempfile
from pathlib import Path

from ledgerkb.core.config import Config
from ledgerkb.core.models import Source, Workspace
from ledgerkb.ingest.pipeline import IngestPipeline
from ledgerkb.storage.sqlite.store import SqliteStore

folder = Path(tempfile.mkdtemp())
(folder / "minutes.md").write_text(
    "# Planning Committee Minutes\n\n"
    "## Item 3: Attercliffe Regeneration\n\n"
    "The capital budget was confirmed at 2.4m for 2026/27.\n\n"
    "### Decision\n\n"
    "The Committee RESOLVED to approve the revised capital allocation.\n",
    encoding="utf-8",
)

store = SqliteStore(folder / "store.db")
store.migrate()

workspace = Workspace(name="demo")
store.add_workspace(workspace)
source = Source(workspace_id=workspace.id, kind="upload", label="local")
store.add_source(source)

report = IngestPipeline(store, Config()).ingest_path(folder, workspace.id, source)
print(len(report.ingested), "documents,", report.total_chunks, "chunks")
#> 1 documents, 3 chunks

for hit in store.search_sparse("capital allocation", 3, workspace_id=workspace.id):
    print(" > ".join(hit.heading_path))
    #> Planning Committee Minutes > Item 3: Attercliffe Regeneration > Decision
    #> Planning Committee Minutes > Item 3: Attercliffe Regeneration
```

That block runs as a test in CI, so it cannot rot.

## Where to go next

- [Ingest your own documents](../how-to/ingest-your-own-documents.md), including
  the formats that need care.
- [Tune retrieval](../how-to/tune-retrieval.md) if the results are not what you
  expected.
- [One ledger](../explanation/the-ledger.md) for why the system is shaped this
  way, and what the four unbuilt projections will do.
- [ROADMAP.md](https://github.com/rajo69/ledgerkb/blob/main/ROADMAP.md) for what does not exist yet. Grounded answering
  with verified quotes is L3, and the change report is L6.
