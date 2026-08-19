# Contributing

Thanks for looking. The project is early. L1 of the plan in
[`docs/design/03-implementation-plan.md`](docs/design/03-implementation-plan.md). Current
state, and where the next stage starts, are in
[`docs/design/04-build-handoff.md`](docs/design/04-build-handoff.md).

## Getting set up

```bash
uv venv
uv pip install -e ".[local]" --group dev   # [local] brings the tier-0 parsers
pytest                                     # the full suite: no network, no API key
```

Nothing in the test suite calls a real provider. Tests that need credentials are
marked `@pytest.mark.live` and run only in the nightly drift workflow.

## Before you open a PR

```bash
ruff check .
mypy                       # strict, on src/ledgerkb/core
lint-imports               # the core-purity and layering contracts
pytest
```

## Sign your commits off

We use a [DCO](https://developercertificate.org/), not a CLA. Add a sign-off line
to every commit:

```bash
git commit -s -m "feat: add the thing"
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

## Things that will get a PR rejected

These are not style preferences. They are the reason the system's claims hold.

- **Adding a config key for a tier-4 invariant.** Quote verification, zero tools
  in extraction calls, the append-only ledger, unmerged contradictions, required
  evidence, the closed predicate schema, path-traversal guards and budget aborts
  have no setting at any level, however convenient one would be. If a setting
  could make the system lie, it is not a setting. See
  [`docs/design/04-build-handoff.md` §8.1](docs/design/04-build-handoff.md).
- **Importing anything into `core/` beyond the stdlib and pydantic.** CI enforces
  it. That purity is what makes everything testable without a network.
- **Deleting from the ledger.** `invalid_at` is the only mutation, and the
  database has triggers that refuse anything else.
- **Adding a code branch for a particular corpus.** Domain knowledge goes in a
  profile. That is what keeps the engine corpus-agnostic.
- **Replacing a deterministic check with an LLM call.** If a check can be code,
  it should be code.
- **Tuning a knob by feel.** The golden set is the arbiter; show the eval delta.

## Extending it

The extension point is the Protocol ports in
[`src/ledgerkb/core/ports.py`](src/ledgerkb/core/ports.py): supply your own
`Store`, `Chunker`, `Reranker`, `ChatModel` or `Parser` and you get full power
through code you own. A new capability starts as a Protocol, before any
implementation exists.

## Dependencies

Every dependency needs a licence check before it lands; the reasoning behind the
current set is recorded in [`docs/design/00-research-log.md`](docs/design/00-research-log.md).
Copyleft licences are not automatically out, but they must be an opt-in extra
rather than a default, which is why `pypdfium2` (Apache/BSD) is the default PDF
parser and AGPL-licensed PyMuPDF is an extra.
