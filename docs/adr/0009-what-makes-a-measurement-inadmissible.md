# 0009. What makes a measurement inadmissible

**Date:** 2026-08-21 · **Status:** accepted

## Context

[0006](0006-measurement-provenance.md) decided what a committed measurement
carries, and said two things about the git state: the header records the commit
"with a dirty flag if the tree was not clean", and "a result whose tree was
dirty at run time is marked and is not admissible as gate evidence".

Writing `src/ledgerkb/evals/provenance.py` turned that into three questions the
record does not answer, and all three change whether a given run counts as
evidence for an L2 criterion.

Does an untracked file make the tree dirty? `git status --porcelain` says yes by
default. Almost every working checkout has an untracked scratch file in it, so
taken literally the rule would mark nearly every local run inadmissible, and a
rule that fires constantly stops being read.

Is a run with no git checkout at all admissible? 0006 does not contemplate it,
because it assumes the measurement runs from the repository. Installing the
wheel and running the harness is a legitimate thing to do, and it produces a
header with no commit in it.

Is the dirty flag part of the commit string or its own field? "A git SHA with a
dirty flag" reads naturally as `f861118-dirty`.

## Decision

`dirty` means modifications to **tracked** files, from
`git status --porcelain --untracked-files=no`. Untracked files do not count.

A run that names no commit is **also** inadmissible, on the same ground rather
than a new one.

`dirty` is its own boolean field beside `ledgerkb_commit`, not a suffix on it.

## Alternatives

**Count untracked files as dirty.** The literal reading, and defensible: an
untracked `.py` file beside the package can shadow an import and change
behaviour. Rejected because the cost is paid on every run and the benefit is
paid on almost none. What the field exists to answer is whether
`git checkout <sha>` reproduces the tree the numbers came from, and an untracked
file is absent from both the commit and the checkout, so it does not change the
answer. The shadowing case is real but is not what this flag is for.

**Treat a missing commit as admissible, since nothing was modified.** Rejected.
It inverts the rule. A dirty tree can at least be described as "this commit plus
a diff somebody could produce"; a header with no commit cannot be re-derived
from anything at all. Admitting the weaker case while refusing the stronger one
would be an accident of how the rule was phrased.

**Put the flag in the SHA string.** Rejected. Every machine reader would have to
strip a suffix before comparing two commits, and the one that forgets compares
`f861118` against `f861118-dirty` and reports a difference that is not there.
Two fields cost one line in the table.

## Consequences

`Provenance.admissible` is one place, and `inadmissible_because` says which of
the two reasons applied, so a result file states why it does not count rather
than leaving a reader to work it out from a boolean.

The untracked-file decision is invisible in the output: a run with an untracked
file beside it looks exactly like a clean one. That is the point, and it is also
the risk, so it is asserted in `tests/integration/test_provenance.py` rather
than left to the module docstring.

This record does not change 0006. It fills in three gaps that only appeared when
the header was built, and 0006's rule is unchanged for the case it addressed.
