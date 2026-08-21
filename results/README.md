# Results

Committed measurements live here, as a pair per run: a Markdown file to read and
a JSON file with the same stem for machines. Both carry the same provenance
header, and the header is written by the eval runner, never by hand.

Nothing is here yet. No measurement has been taken.

[ADR 0006](../docs/adr/0006-measurement-provenance.md) fixed the format before
any result existed, which was the last moment at which it could be decided
honestly: a provenance rule written after the first number is a rule the first
number was never held to. `ledgerkb.evals.provenance.collect` is that decision
in code, and there is no argument through which a value can be typed in.

A run whose working tree had uncommitted changes to tracked files is marked and
is **not admissible as gate evidence**, along with a run that names no commit at
all. [ADR 0009](../docs/adr/0009-what-makes-a-measurement-inadmissible.md)
settles what counts as either.

This directory is not ignored by git, and it should not grow without limit. If a
stage starts producing a result per commit, keep the last one per gate and let
the history hold the rest.
