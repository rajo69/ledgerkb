# AGENTS.md

Instructions for coding agents working in this repository. Humans want
[CONTRIBUTING.md](CONTRIBUTING.md); most of this applies to them too.

## Stack

Python 3.11+, uv, hatchling. pydantic for models, typer and rich for the CLI,
httpx for HTTP, numpy for vectors, SQLite for storage. fastembed for in-process
embedding. Tests are pytest plus hypothesis. Source is in `src/ledgerkb/`.

## Commands

```bash
uv pip install -e ".[local]" --group dev
uv run pytest                       # full suite: no network, no credentials
uv run pytest -q -k <expr>          # one idea
uv run ruff check .
uv run mypy                         # strict, on core only
uv run lint-imports                 # purity and layering contracts
python scripts/render_docs.py       # after editing docs/stages.toml
python scripts/check_docs.py        # documentation lint
```

Run all of them before saying you are done. `pytest` alone is not the bar.

## Invariants you must not break

Breaking one of these is a rejected change regardless of what it enables.

1. **Chunk text is sliced, never constructed.**
   `document_text[chunk.char_start:chunk.char_end] == chunk.text`, exactly. Do
   not join, strip or normalise into `chunk.text`. Context headers go in
   `context_header`.
2. **`core/` imports only the standard library and pydantic.** No I/O, no
   provider SDK, no framework. Enforced by import-linter.
3. **No config key for a tier-4 setting.** Quote verification, zero tools in
   extraction calls, the append-only ledger, unmerged contradictions, required
   evidence, the closed predicate schema, path-traversal guards and budget
   aborts have no key at any level. If a setting could make the system lie, it is
   not a setting. Add a Protocol implementation instead.
4. **Never delete from the ledger.** `invalid_at` is the only mutation and it is
   written once. The database has triggers that refuse anything else.
5. **No code branch for a particular corpus.** Domain knowledge goes in
   `profiles/*.toml`. If you are writing `if doc_type == ...` in `src/`, stop.
6. **Deterministic over probabilistic.** If a check can be code rather than a
   model call, it must be code.
7. **Everything works offline.** Nothing on the default path may require a
   network or an API key, including the tests.

Full list with the enforcing mechanism: [ARCHITECTURE.md](ARCHITECTURE.md)
section 3.

## Writing style, for anything in Markdown

Enforced by `scripts/check_docs.py`, so a violation fails CI.

- **No em dashes.** Use a comma, a colon, a full stop or parentheses, whichever
  the sentence needs. A spaced hyphen where a dash is genuinely right.
- **No machine-prose tells.** Not "X is not just Y, it is Z". Not "seamlessly",
  "robust", "leverage" as a verb, "delve", "unlock", "harness", "empower",
  "cutting-edge". Not "it is worth noting that". No emoji as section markers. No
  closing paragraph that summarises what was just said.
- **Bold a term, not a sentence.** No rhetorical questions as headings.
- **Prefer the concrete.** "55 chunks from 20 documents" beats "a small corpus".
  Any figure in a document should be reproducible by running something.
- **Claim only what the code does.** The largest risk in this repository's
  documentation is describing designed work as built. Check
  [ROADMAP.md](ROADMAP.md) before writing that something works.

## Definition of done

Same list as [CONTRIBUTING.md](CONTRIBUTING.md) and the pull request template:

- Behaviour changed? Update the reference page for it in the same change.
- Stage status changed? Update `docs/stages.toml` and run the renderer.
- New capability? Add or update the how-to guide.
- Invariant added or changed? Update `ARCHITECTURE.md`.
- Anything user-visible? Add a `CHANGELOG.md` entry.

Commits use Conventional Commits and are signed off with `git commit -s`.

## Notes that save time

- Every test uses `providers/fake.py`. Do not reach for a real provider; a test
  that needs credentials is marked `@pytest.mark.live` and does not run in CI.
- The CLI prints with rich markup, and documents are untrusted input. Anything a
  document controls goes through `safe()` in `cli/main.py` before printing.
- `mypy` is configured to check `src/ledgerkb/core` only. Running it on more is
  fine locally; do not widen the config as a side effect of another change.
- The store's schema carries invariants as triggers and constraints. Read
  `storage/migrations/*.sql` in order before changing how anything is written.
