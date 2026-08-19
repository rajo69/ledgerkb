# Security policy

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/rajo69/ledgerkb/security/advisories/new)
rather than opening a public issue. We aim to acknowledge within 72 hours.

## Supported versions

Pre-1.0. Only the latest release gets fixes.

## The threat model

`ledgerkb` ingests documents that the operator does not control, and feeds them
to a language model. **Prompt injection through document content is the primary
threat**, and it is treated as an architectural problem rather than a filtering
one.

The controls that matter:

| Control | What it prevents |
|---|---|
| **Extraction calls carry zero tools** | An injected instruction has nothing to call. This is why it is not a config option. |
| **Sanitisation and quarantine** | Suspicious spans are recorded in the `quarantine` table rather than silently dropped, so the operator can see what was found. |
| **Deterministic quote verification** | A fabricated citation cannot survive, because the quote must occur verbatim in the stored chunk. |
| **Closed predicate schema** | Extraction cannot invent relationship types outside the profile. |
| **Path-traversal and zip guards** | A malicious archive cannot write outside the workspace. |
| **Budget ceilings abort the run** | A prompt that induces runaway generation hits a hard stop. |
| **Console output escapes document-controlled text** | A document cannot inject rich markup into `lkb` output and forge a heading, a colour or a status. Added 2026-08-19; see `safe()` in `cli/main.py`. |

None of these has a setting that turns it off. That is deliberate: a guarantee
with an off switch is not a guarantee.

**What is implemented today** is sanitisation and quarantine, the ZIP and
path-traversal guards, the budget ceiling, and the console escaping. Quote
verification is L3, the closed predicate schema and the no-tools rule are L4, and
until those land the controls that depend on them are design positions rather
than code. [ROADMAP.md](ROADMAP.md) is the source of truth for what exists.

## Credentials

`ledgerkb` never stores an API key. Configuration references an *environment
variable name* (`api_key_env`), never a key value, so a config file is safe to
commit and safe to include in an export's build receipt.

## Reporting scope

In scope: injection that escapes the controls above, path traversal, SQL
injection, credential leakage into logs, exports or traces, and dependency
vulnerabilities.

Out of scope: a model producing a low-quality answer that is nonetheless
correctly cited and grounded. That is an evaluation issue. Please open a normal
issue with the golden-set case.
