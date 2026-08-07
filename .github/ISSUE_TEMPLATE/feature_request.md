---
name: Feature request
about: Propose a capability
labels: enhancement
---

**What you are trying to do**

**Why the existing extension points do not cover it**

The ports in `src/ledgerkb/core/ports.py` let you supply your own `Store`,
`Chunker`, `Reranker`, `ChatModel` or `Parser`. If one of those would work, that
is usually the faster path.

**Does this touch an invariant?**

Quote verification, zero tools in extraction, the append-only ledger, unmerged
contradictions, required evidence, the closed predicate schema, path-traversal
guards and budget aborts are not configurable, by design. A proposal that needs
one of them relaxed needs to argue the guarantee is wrong, not that the switch
is convenient.
