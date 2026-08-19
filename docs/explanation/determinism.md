# Why the checks are code, not model calls

There is a version of this system where a language model does the checking. It
grades whether a citation supports a claim. It decides whether two entity names
refer to the same person. It judges whether an answer is faithful. That version is
easier to build, and it is worse in four specific ways.

**It costs money per check**, so the checks get sampled, then run nightly, then
quietly dropped. An eval that costs money is an eval that stops being run, and an
eval that stops being run stops being true.

**It cannot run offline.** Which means the test suite needs credentials, which
means contributors need credentials, which means CI needs secrets, which means a
fork cannot run the tests at all.

**It is not stable.** The provider ships a new checkpoint and yesterday's passing
suite fails, or worse, yesterday's failing case starts passing. You then cannot
tell a regression in your code from a change in somebody else's model.

**It can be talked out of it.** A checker that reads untrusted text and makes a
judgement is a checker that untrusted text can address. The whole threat model
here is documents that carry instructions.

So the rule is: if a check can be code instead of a model call, it is code.

## Where that rule shows up

**Quote verification** is normalised string matching, then a fuzzy match with a
floor. Not "does this evidence support this claim" but "does this exact string
occur in this exact chunk". Microseconds, no key, and no way to argue with it.

**The predicate schema is closed.** Extraction returns a `Literal` of ten
predicates. An eleventh is not a low-confidence result, it is a rejected one.
Extending the vocabulary is a profile change, not a prompt change.

**Rank fusion is arithmetic.** Reciprocal rank fusion sums `1 / (k + rank)` across
arms. It has one parameter, it is deterministic, and the same inputs always give
the same order because ties break on chunk id.

**Metadata extraction is rules.** Title, date, document type, meeting or project,
source. Deterministic, with every miss reported rather than silently null, so the
coverage number means something.

**Injection detection is a pattern**, not a classifier and not a blocklist. It
requires an instruction verb and a token addressing a model, together, in a short
window. That is why "the committee resolved to ignore the previous recommendation"
is not a finding, and a blunt trigger-word filter would flag it.

**The offset invariant is a property test**, not a review checklist.

## Where a model is the right tool

Not everywhere. The rule is about checks, not about work.

A model is the right tool for extraction: turning a paragraph of minutes into a
subject, a predicate and an object is not a job for a regular expression. It is the
right tool for a context header, and for adjudicating an entity pair that sits in
the grey band between "obviously the same" and "obviously different", where the
alternative is a coin flip.

The pattern in each case is the same: **the model proposes, code disposes.**
Extraction runs, and then post-conditions checked in code decide what survives.
The quote must occur in the chunk. An inferred claim cannot have full confidence.
An unknown predicate is rejected. None of those are trusted from the model, and
none of them cost anything.

## The consequence for evaluation

The headline metrics require no judge and no API key. Citation validity is
enforced rather than measured, and it is 1.00 by construction. Correct abstention
is counted against a labelled set. Retrieval recall is counted against labelled
chunk ids. Over-merge rate is counted against labelled pairs. All of it runs in
CI, on a fork, for free.

LLM-judged metrics have a place after that, measuring residual quality rather than
being the only line of defence. They live behind an extra, and they are not the
number the project quotes.
