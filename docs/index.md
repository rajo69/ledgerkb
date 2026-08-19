# ledgerkb

Most tools answer questions about your documents. This one keeps a position on
them, tells you when that position changes, and shows its working.

```bash
uv pip install -e ".[local]" --group dev
lkb init . && lkb ingest ./documents && lkb index
lkb search "who owns the footbridge decision?" --explain
```

No API key. No network. No account.

## Where to go

**[Tutorial](tutorial/first-knowledge-base.md)** if you have not used it. Twenty
minutes, from nothing to a searchable corpus with a citation you can verify.

**How-to guides** when you know what you want:

- [Ingest your own documents](how-to/ingest-your-own-documents.md)
- [Run without an API key](how-to/run-without-an-api-key.md)
- [Use a hosted provider](how-to/use-a-hosted-provider.md)
- [Tune retrieval](how-to/tune-retrieval.md)
- [Add a parser](how-to/add-a-parser.md)

**Reference** when you need to look something up:

- [CLI](reference/cli.md), every command and flag
- [Configuration](reference/configuration.md), every key, its tier and what
  changing it costs
- [Data model](reference/data-model.md) and [Ports](reference/ports.md)
- [Store schema](reference/store-schema.md), tables, triggers and migrations

**Explanation** when you want to know why:

- [One ledger, and why everything else is a projection](explanation/the-ledger.md)
- [Citations and the offset invariant](explanation/citations-and-offsets.md)
- [Why the checks are code, not model calls](explanation/determinism.md)
- [The four tunability tiers](explanation/tunability-tiers.md)
- [Injection as an architectural problem](explanation/security-model.md)

**[Design records](design/00-research-log.md)** are how the project got here: the research behind
each technology choice, the product it is eventually for, and the plan it is being
built to. They are records rather than current reference, and each says so.

## What is built

<!-- generated: status-brief. Edit docs/stages.toml, then run scripts/render_docs.py -->
L0 and L1 are complete. L2, index and retrieve, is under way with 2 of its 7 gate criteria
met. Everything after it is designed and gated but not written.
<!-- end generated: status-brief -->

The list of what works, and the gate criteria for every stage, is in
[the roadmap](https://github.com/rajo69/ledgerkb/blob/main/ROADMAP.md), generated
from the same machine-readable file as the paragraph above, so neither can drift
from what is claimed elsewhere.

The documentation names the stage for anything that is not built. If you find a
page claiming a capability that does not exist, that is the most useful bug report
this project can receive.
