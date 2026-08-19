# CLI

Eight commands. All of them run with no API key and no network.

`lkb --help` and `lkb <command> --help` print the same information from the code.
This page is the version you can search.

## `lkb version`

Print the installed version. No options.

## `lkb init [DIRECTORY]`

Create `ledgerkb.toml`, `profiles/default.toml` and an empty migrated store.
`DIRECTORY` defaults to `.`.

| Option | Effect |
|---|---|
| `--force` | Overwrite an existing config. Without it, `init` refuses rather than replacing one |

The store is created at `store.path`, which defaults to `.lkb/store.db`, and is
migrated to the current schema version immediately.

## `lkb doctor`

Check the environment, config and store. Never needs an API key, and reports what
still works when one is absent rather than treating it as an error.

| Option | Effect |
|---|---|
| `--tiers` | Print every configuration key that exists, its tier, and what changing it forces |

It reports: the config file it found and its `config_version`; the profile and how
many entity types and predicates it carries; the store path, schema version and a
row count per table; the configured chat model and whether its API key variable is
set; and the embedding model with its dimensions.

Include the output of `lkb doctor` in a bug report. It contains no secrets:
configuration names an environment variable rather than holding a key.

## `lkb ingest PATH`

Read, parse, sanitise and chunk documents. No network, no API key.

`PATH` is a file, a directory or a `.zip`. Directories are walked; archives are
expanded with guards against path traversal, compression ratio, nesting depth and
total size.

| Option | Effect |
|---|---|
| `--source NAME` | Name for this source. Defaults to `local` |

Formats: PDF, DOCX, XLSX, PPTX, HTML, EML, CSV, JSON, MD, TXT. A file no parser
claims raises a named error rather than being guessed at as text.

Output is one row per document with its status, chunk count and the parser that
handled it, then a summary and a metadata coverage table. A document whose content
hash is unchanged is reported as `unchanged` and costs one hash rather than one
parse. A document that fails is reported by name and the run continues.

## `lkb docs`

List ingested documents with their metadata: title, type, publication date, and
the meeting or project they belong to. Fields that could not be determined are
shown as misses rather than as blanks.

## `lkb chunks DOC_ID`

Show a document's chunks. `DOC_ID` may be a unique prefix.

| Option | Effect |
|---|---|
| `--verify` | Re-slice every chunk from the stored document text and confirm it comes back byte-identical |

`--verify` is the offset invariant, checkable against the store at any time. See
[Citations and offsets](../explanation/citations-and-offsets.md).

## `lkb index`

Embed the chunks. The default embedder runs in-process through fastembed, so this
needs no API key and no network. Only chunks without an embedding are processed.

| Option | Effect |
|---|---|
| `--rebuild` | Re-embed every chunk, not just new ones |

Chunks belonging to superseded document versions are kept but not indexed.

## `lkb search QUERY`

Hybrid retrieval. Retrieval only: grounded answering with verified quotes is L3
and is not built.

| Option | Effect |
|---|---|
| `--k N` | How many results. Defaults to 8 |
| `--explain` | Show each arm's rank and the fused score for every candidate |
| `--arms LIST` | Comma-separated subset of `dense,sparse,headings`. Defaults to all three |
| `--json` | Machine-readable output |

`--arms` exists so you can measure one arm against another on the same query,
which is the only honest way to claim hybrid beats either half.

With `--explain`, the last line of each result is the chunk id followed by where
each arm placed it:

```
0e22c996  dense#37  headings#1  sparse#1
```

An arm that ran and found nothing is absent from that line. An arm that was not
run is absent from the header count too, so the two cases stay distinguishable.

## Exit codes

`0` on success. `1` on a named `ledgerkb` error, with the message on stderr and no
traceback. A traceback means a bug; please report it.

## Commands that do not exist yet

`lkb ask`, `lkb compile`, `lkb assertions`, `lkb refresh`, `lkb changes`,
`lkb history`, `lkb graph`, `lkb entities`, `lkb export`, `lkb eval`, `lkb runs`
and `lkb cost` are designed and gated. See [ROADMAP.md](https://github.com/rajo69/ledgerkb/blob/main/ROADMAP.md) for
which stage each arrives in.
