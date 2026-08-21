# Tune retrieval

Retrieval runs three arms and fuses them by rank. Tuning means changing how many
candidates each arm contributes, how the fusion weights rank position, and how
many results survive.

Before changing anything, look at what is actually happening:

```bash
lkb search "your query" --explain
```

The last line of each result is where every arm placed that candidate. A result
that is `dense#37 headings#1` was rescued by the heading arm. A result that only
one arm found tells you which notion of relevance is carrying the query.

## Isolate an arm

```bash
lkb search "SCC/2026/114" --arms dense
lkb search "SCC/2026/114" --arms sparse
lkb search "SCC/2026/114" --arms headings
```

This is the diagnostic that matters. If dense-only already returns the right
answer at rank 1, fusion is not your problem. If sparse-only finds it and dense
does not, the query is lexical: reference numbers, names, codes, anything an
embedding smooths into its neighbours.

## The knobs

All free-tier: change them, rerun, no rebuild.

| Key | Default | What it does |
|---|---|---|
| `retrieval.dense_k` | 50 | Candidates from the vector arm |
| `retrieval.sparse_k` | 50 | Candidates from BM25, and from the heading arm |
| `retrieval.rrf_k` | 60 | The rank-fusion constant |
| `retrieval.fuse_to` | 30 | How many fused candidates survive to reranking |
| `retrieval.rerank_to` | 8 | Final result count. `--k` overrides per query |

Validation rejects incoherent combinations at startup: `rerank_to` above
`fuse_to`, because reranking cannot invent candidates, and `fuse_to` above
`dense_k + sparse_k`.

## What `rrf_k` actually does

Fusion scores a candidate as the sum over arms of `1 / (rrf_k + rank)`.

A **larger** `rrf_k` flattens the contribution of the top ranks, so a document
found by two arms beats one found first by a single arm. A **smaller** `rrf_k`
sharpens it, so a confident single-arm hit can win.

60 is the value from the original TREC work. Raise it if you want agreement
between arms to dominate. Lower it if one arm is clearly better on your corpus and
you want it to win outright, though at that point consider dropping the weak arm
with `--arms` instead.

Rank rather than score, because a cosine similarity of 0.83 and a BM25 score of
-7.2 are not on the same scale and never will be. Any attempt to combine the
numbers directly is a fudge factor wearing a formula's clothes.

## Sizing `dense_k` and `sparse_k` to your corpus

The defaults assume a corpus much larger than the anchor fixture set. On a
55-chunk store `dense_k = 50` asks the dense arm for 91 percent of everything, so
both lists contain nearly the whole corpus and fusion has almost nothing to
discriminate with.

Rule of thumb: each arm should retrieve a small fraction of your chunks. If your
store is under a few hundred chunks, drop both to 10 or 20 and the fused ordering
starts to mean something.

This is also why L2's own measurement runs against a generated corpus of 4,433
chunks rather than the 55-chunk anchor set: at that size the gate could not go
red, so passing it would have proved nothing. See
[build the measurement corpus](build-the-measurement-corpus.md).

## Chunking, which matters more

If retrieval is bad, chunking is a likelier cause than fusion.

`chunking.max_tokens` (default 512) and `chunking.overlap` (default 64) are
**gated**: changing either forces a full re-chunk and re-index, and the CLI says
so rather than leaving half the store chunked one way. Chunk ids change when
boundaries move, which is why this is not a free setting.

Chunking is structure-first: a section that fits stays whole. If your documents
have no heading structure, every section is one blob and `max_tokens` is doing all
the work. Fixing the parser's heading recovery beats tuning the number.

## Contextual headers

`chunking.contextual_headers` defaults to `False`, and that is deliberate rather
than an oversight.

Contextual headers are one language-model call per chunk, which makes them the
highest-volume call in the system. The plan gates them on a 5-point recall
improvement, and a knob that is on before the measurement makes the gate
decorative.

The baseline they have to beat is not "no context". It is the **heading arm**,
which already carries "Planning Committee Minutes > Item 4 > Decision"
deterministically, offline and free. If the deterministic path captures most of
the gain on structured documents, that is a publishable result and it deletes the
most expensive call in the system.

Turning them on is a gated change forcing a full re-index.

## Reranking

`retrieval.rerank_to` exists and the `Reranker` port exists. No reranker
implementation ships, because a cross-encoder is either an API call, which breaks
the offline guarantee, or a torch dependency, which breaks the install budget.

You can supply your own: implement `rerank(query, docs, top_k) -> [(index, score)]`
and pass it to `search()`. See [Ports](../reference/ports.md).

## Do not tune by feel

The golden set is the arbiter, and a knob changed without a measured delta is a
guess. That set does not exist yet, which is exactly why L2 is still open. Until it
does, `--explain` and `--arms` on your own queries are the honest tools, and any
claim about which setting is better should say which queries it was checked on.
