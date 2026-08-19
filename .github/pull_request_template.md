## What this changes

## Why

## Checks

- [ ] `ruff check .` clean
- [ ] `mypy` clean (strict, on `core`)
- [ ] `lint-imports` clean
- [ ] `pytest` green, with tests covering the change
- [ ] `python scripts/render_docs.py --check` clean
- [ ] `python scripts/check_docs.py` clean
- [ ] Commits signed off (`git commit -s`), Conventional Commits subject

## Definition of done

- [ ] Behaviour changed? The reference page for it is updated in this pull request
- [ ] Stage status changed? `docs/stages.toml` is updated and the renderer has run
- [ ] New capability? A how-to guide is added or updated
- [ ] Invariant added or changed? `ARCHITECTURE.md` is updated
- [ ] Anything user-visible? There is a `CHANGELOG.md` entry

## Rejections to check yourself against

- [ ] No new config key for a tier-4 invariant
- [ ] Nothing new imported into `core/` beyond the stdlib and pydantic
- [ ] No code branch for a particular corpus
- [ ] Chunk text is still sliced, never constructed
- [ ] If a knob changed, the eval delta is in the description, not a feel judgement
