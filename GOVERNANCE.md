# Governance

Honest and small, because a fictional committee helps nobody.

## Who decides

One maintainer: Rajarshi Nandi ([@rajo69](https://github.com/rajo69)), listed in
[`.github/CODEOWNERS`](.github/CODEOWNERS). They review and merge everything, and
they are accountable for the decisions below.

This will change if the project grows. The trigger is two or more people
sustaining review work over a few months, at which point maintainers get named in
`CODEOWNERS` per area and merge rights follow.

## What is not the maintainer's to change

Some rules are constitutional. Changing one is not a maintainer decision, it is a
change to what the project claims to be, and it needs a written argument in an
issue and a note in the decision record.

- **The tier-4 rule.** If a setting could make the system lie, it is not a
  setting. The list is in
  [`docs/design/04-build-handoff.md` section 8.1](docs/design/04-build-handoff.md)
  and the invariants it protects are in [ARCHITECTURE.md](ARCHITECTURE.md).
- **The gating rule.** No stage begins until the previous gate is green, and a
  gate criterion is measurable. Weakening a criterion to make a stage pass is the
  failure this rule exists to prevent.
- **The licence.** Apache-2.0, with DCO sign-off rather than a CLA. Contributors
  keep their copyright.

## How decisions get recorded

- **Technology choices** go in
  [`docs/design/00-research-log.md`](docs/design/00-research-log.md) with the
  evidence and a verdict.
- **Decisions that constrain later work** go in the decision record in
  [`docs/design/02-architecture.md` section 12](docs/design/02-architecture.md)
  and the locked list in
  [`docs/design/04-build-handoff.md` section 2](docs/design/04-build-handoff.md).
- **From here on**, a decision significant enough to be re-litigated gets its own
  file in `docs/adr/`, numbered and dated, saying what was decided, what the
  alternative was, and why. Superseding an ADR means writing a new one that says
  so, not editing the old one.
- **Stage status** lives in [`docs/stages.toml`](docs/stages.toml) and nowhere
  else.

Reversing a recorded decision is fine. Reversing one without recording that it
was reversed is not, because the next person then has to re-derive the argument
from scratch. That is the whole reason the design records survive in
[`docs/design/`](docs/design/) rather than being tidied away.

## How a change lands

An issue or a pull request, reviewed by the maintainer against
[CONTRIBUTING.md](CONTRIBUTING.md). Nothing more elaborate is warranted at this
size. Branch protection on `main` and required review are planned and not enabled
yet, which is recorded rather than glossed over.

## If the maintainer disappears

The project is Apache-2.0 and every design decision is written down. Fork it. The
records in [`docs/design/`](docs/design/) exist partly for that case.
