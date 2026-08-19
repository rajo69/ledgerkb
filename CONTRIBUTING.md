# Contributing

Thanks for looking. The project is early, and it moves through fifteen gated
stages. What is built, what is not, and what the open stage still needs are in
[ROADMAP.md](ROADMAP.md). Where the code lives and what must not break are in
[ARCHITECTURE.md](ARCHITECTURE.md).

## A first change, end to end

This is the whole loop. It should take about ten minutes on a machine with
[uv](https://docs.astral.sh/uv/) installed, and it needs no API key and no
network beyond the clone and the install.

```bash
git clone https://github.com/rajo69/ledgerkb
cd ledgerkb

uv venv
uv pip install -e ".[local]" --group dev
uv run pytest                       # the full suite: no network, no credentials
```

Make a branch and a change. If you want a real one to practise on, the parser
registry is the friendliest place in the codebase:

```bash
git switch -c feat/odt-parser
```

Write the test first, because that is the loop you will spend the most time in:

```bash
uv run pytest tests/unit/test_chunk.py -q       # one file, fast
uv run pytest -q -k odt                         # one idea, faster
```

Run everything CI runs, in the order CI runs it:

```bash
uv run ruff check .
uv run mypy
uv run lint-imports
uv run pytest
python scripts/render_docs.py --check
python scripts/check_docs.py
```

Commit with a sign-off and a Conventional Commits subject, then open the pull
request:

```bash
git commit -s -m "feat(parsers): add an ODT parser behind the Parser port"
git push -u origin feat/odt-parser
gh pr create --fill
```

`-s` adds the `Signed-off-by` line. That is the whole of the
[DCO](https://developercertificate.org/): there is no CLA to sign.

## The checks, and what each one protects

| Check | What it protects |
|---|---|
| `ruff check .` | Style and a set of correctness lints, including `S` for common security mistakes. Line length is 100 |
| `mypy` | Strict typing on `src/ledgerkb/core`. `core` is the surface everything else depends on, so it gets a stability commitment at v1.0.0 and has to be worth committing to |
| `lint-imports` | Three contracts: `core` imports nothing else from `ledgerkb`; `core` imports no third-party package except pydantic; the packages form a strict layering. This purity is what lets the whole suite run offline |
| `pytest` | Correctness. Every test runs against the fake providers, so a green suite costs nothing and never flakes on somebody's rate limit |
| `coverage report --fail-under=85` | A ratchet, not a target. Raise it as coverage grows; never lower it |
| The floors job | Runs the suite resolved to the lowest version every `>=` in `pyproject.toml` allows. It turns each floor into a claim rather than a guess, and it is the job that caught typer 0.12 silently mis-parsing `--force` |
| `offline.yml` | Runs the suite and a full ingest inside a network namespace, and fails if the network is reachable at all. Without that last check the job could pass while proving nothing |
| `render_docs.py --check` | Stage status is generated from `docs/stages.toml`. Editing it without regenerating fails here |
| `check_docs.py` | No em dashes, no banned words, every relative link resolves, no stage status stated in prose outside a generated region |

## Definition of done

Same list as the pull request template and [AGENTS.md](AGENTS.md), so it is hard
to miss:

- **Behaviour changed?** Update the reference page for it in the same pull
  request.
- **Stage status changed?** Update `docs/stages.toml` and run
  `python scripts/render_docs.py`.
- **New capability?** Add or update the how-to guide.
- **Invariant added or changed?** Update `ARCHITECTURE.md`.
- **Anything user-visible?** Add a `CHANGELOG.md` entry.

Documentation in the same pull request as the change, not a follow-up. A
follow-up is a promise, and this repository has already drifted once on exactly
that promise.

## Things that will get a pull request rejected

These are not style preferences. They are the reason the system's claims hold.

- **Adding a config key for a tier-4 invariant.** Quote verification, zero tools
  in extraction calls, the append-only ledger, unmerged contradictions, required
  evidence, the closed predicate schema, path-traversal guards and budget aborts
  have no setting at any level, however convenient one would be. If a setting
  could make the system lie, it is not a setting. See
  [`docs/design/04-build-handoff.md` section 8.1](docs/design/04-build-handoff.md).
- **Importing anything into `core/` beyond the stdlib and pydantic.** CI enforces
  it. That purity is what makes everything testable without a network.
- **Deleting from the ledger.** `invalid_at` is the only mutation, and the
  database has triggers that refuse anything else.
- **Adding a code branch for a particular corpus.** Domain knowledge goes in a
  profile. That is what keeps the engine corpus-agnostic.
- **Replacing a deterministic check with an LLM call.** If a check can be code,
  it should be code.
- **Tuning a knob by feel.** The golden set is the arbiter; show the eval delta.
- **Rewriting chunk text.** Anywhere. The offset invariant is the foundation the
  citation guarantee stands on.

## Review expectations

One maintainer, so the honest promise is a small one and it is kept:

- **A first response within seven days**, on every issue and every pull request.
  It may be a question rather than a review, but it will not be silence.
- **A decision within three weeks** on anything labelled `good first issue`.
  Those are labelled because they are ready to be reviewed, and inviting work
  that then goes nowhere is worse than not labelling at all.
- **A pull request that goes quiet** gets a comment after 30 days and is closed
  as stale after 60. Closing is not a judgement and reopening needs no
  explanation.
- **Larger changes: open an issue first.** Not for permission, but so nobody
  spends a weekend on something that conflicts with a stage gate.

## Where help is most wanted

Current, and specific:

1. **A parser for a format not yet covered.** ODT, RTF, EPUB, or a better PDF
   path for scanned documents. The `Parser` protocol is two methods, and
   `ingest/parsers/registry.py` makes a new format a single registration. Read
   `parsers/plain.py` for the smallest complete example.
2. **More document types in the fixture corpus generator.**
   `tests/fixtures/build_corpus.py` is generative, so this is parameters rather
   than authoring, and the corpus stays reviewable source instead of committed
   binaries. This is the work blocking L2's gate: 55 chunks cannot support a
   recall measurement.
3. **A how-to guide for a provider you actually run.** Ollama, vLLM, LM Studio,
   TEI. If you got it working, that is the guide.
4. **`lkb doctor` reporting which projections are stale.** Useful now, and more
   useful at every later stage.

## Extending it without changing it

The extension point is the Protocol ports in
[`src/ledgerkb/core/ports.py`](src/ledgerkb/core/ports.py). Supply your own
`Store`, `Chunker`, `Reranker`, `ChatModel` or `Parser` and you get full power
through code you own. A new capability starts as a Protocol, before any
implementation exists.

## Dependencies

Every dependency needs a licence check before it lands; the reasoning behind the
current set is recorded in
[`docs/design/00-research-log.md`](docs/design/00-research-log.md). Copyleft
licences are not automatically out, but they must be an opt-in extra rather than
a default, which is why `pypdfium2` (Apache/BSD) is the default PDF parser and
AGPL-licensed PyMuPDF is an extra.

Every entry carries a version floor, because the floors job resolves to the
lowest direct version and an unbounded dependency resolves to a 2011 placeholder
that does not build.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
