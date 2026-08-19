# Injection as an architectural problem

The threat here is not a user typing a jailbreak into a prompt box. It is a
document.

This library ingests files its operator does not control, and feeds them to a
language model. That is indirect prompt injection, and it has a property that
direct injection does not: one poisoned document compromises every user whose
query happens to retrieve it. The attacker does not need access to the system. They
need a file to end up in a folder.

## Why filtering is the wrong shape

The instinctive defence is a filter: scan text for instruction-like phrases and
block them.

It does not work on this kind of corpus, for a reason that is easy to demonstrate.
Meeting minutes routinely contain sentences like:

> The committee resolved to ignore the previous recommendation.

A trigger-word filter flags that. Standard guardrail products drop to roughly 60
percent accuracy on benign data for exactly this reason: the words that appear in
attacks also appear innocently, and in records work they appear constantly. A
blunt filter on this corpus does more damage than the attack it is meant to
prevent, because it silently drops real content from real documents.

So there is no keyword blocklist here, and adding one is a rejected change.

## What is done instead

Four controls, in rough order of how much they matter.

**Extraction calls carry zero tools.** This is the real control and everything else
is defence in depth. The calls that process untrusted document text at high volume
have no tool access and no privileges, so an injected instruction has nothing to
call. It can say "delete the database" all it likes. There is no function bound to
the request.

That is why it has no configuration key. A flag would turn an architectural
property into a preference, and preferences get changed.

**Quote verification.** An injected instruction can make a model claim anything.
It cannot make the claimed quote appear in a chunk that was stored before the
attack ran. Since a claim whose quote fails verification never reaches the caller,
injection cannot manufacture a surviving citation. See
[Citations and offsets](citations-and-offsets.md).

**Sanitisation, and quarantine rather than deletion.** Two different things happen
at ingest, and the difference matters.

Invisible text is *removed*: zero-width characters, bidi overrides, control
characters, text coloured to match its background, `display:none` content, HTML
comments. Anything a human reader cannot see has no business influencing an answer
they will read.

Instruction-shaped text is *kept and quarantined*. It stays in the document text,
because removing it would silently rewrite the record, and it is recorded in the
`quarantine` table with its offsets and the reason it was flagged. It is excluded
from prompts and surfaced as a finding. The operator gets to see what was in their
documents, which is more useful than a clean-looking corpus.

Detection requires an instruction verb *and* a token addressing a model, together,
in a short window. That is what keeps the committee sentence above out of the
findings.

**A closed schema.** Extraction returns one of ten predicates. There is no
free-text field an injection can steer into meaning something else, because the
vocabulary is a `Literal` and an unknown value is rejected rather than accepted
with low confidence.

## Guards that are not about models at all

Archive expansion checks path traversal, compression ratio, nesting depth and
total size, so a malicious ZIP cannot write outside the workspace or exhaust the
disk. Five malicious archive fixtures test it. None of those guards is
configurable.

Budget ceilings abort a run. You set the ceiling; there is no "proceed anyway",
because the whole point is that a runaway generation induced by a document stops.

Console output escapes anything a document controls before printing. Output is
styled with rich markup, and a crafted document title could otherwise forge a
heading, a colour or a status in what looks like tool output.

## Credentials

The library never stores an API key. Configuration names an *environment variable*
through `api_key_env`, never a key value. A `ledgerkb.toml` is therefore safe to
commit, and safe to include verbatim in an export's build receipt.

## What is built, and what is not

Built: sanitisation and quarantine, the archive and path guards, the budget
ceiling, console escaping.

Not built: quote verification is L3, and the closed schema and the no-tools rule
are L4, because extraction itself does not exist yet. Until then those are design
positions with a test waiting to be written, not code.

[SECURITY.md](https://github.com/rajo69/ledgerkb/blob/main/SECURITY.md) has the reporting process and the scope. Please
report privately.
