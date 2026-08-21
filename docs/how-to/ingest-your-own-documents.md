# Ingest your own documents

```bash
lkb ingest ./your-folder          # a directory, walked recursively
lkb ingest ./report.pdf           # one file
lkb ingest ./export.zip           # an archive, expanded with guards
lkb ingest ./folder --source drive-export
```

`--source` names the origin. It matters once you have more than one, because
refresh works per source and documents are unique on `(source, external_id)`.

## What parses

| Format | Parser | Notes |
|---|---|---|
| PDF | `pypdfium2` | Born-digital text layer. Scanned pages need tier 1, which is L7 |
| DOCX | `python-docx` | Headings become the heading path |
| XLSX | `openpyxl` | One chunk per sheet, cells flattened row-wise |
| PPTX | `python-pptx` | One chunk per slide, title as heading |
| HTML | `selectolax` | Scripts, styles, comments and `display:none` removed |
| RTF | native | Stylesheet and outline levels become the heading path; images are skipped and reported |
| EML | stdlib `email` | Headers become metadata; the text part is the body |
| CSV | stdlib `csv` | Header row becomes the field names |
| JSON | stdlib `json` | Flattened to readable key paths |
| MD, TXT | native | Markdown headings become the heading path |

Anything else raises a named error naming the file. It is not guessed at as text,
because a DOCX decoded as latin-1 produces plausible-looking rubbish that would
then be embedded, cited and quoted.

## What you get per document

Five metadata fields, extracted deterministically: `title`, `published_at`,
`doc_type`, `meeting_or_project` and `uri`. Coverage is printed after every run.
A field that could not be determined is recorded as a miss on the version, not
written as null and forgotten.

If coverage is poor on your corpus, that is information rather than a bug. Look at
`metadata_misses` on the versions and consider whether a profile would help:
`doc_types` in `profiles/<name>.toml` is the vocabulary the classifier matches
against.

## Structure matters more than size

Chunking is structure-first. A section that fits stays whole, so a decision and
its rationale stay in one chunk. Only a section that overruns
`chunking.max_tokens` is split further.

This means documents with real headings chunk well and a wall of undifferentiated
text chunks poorly. If your PDFs come out as one giant chunk per page, the heading
tree is not being recovered, and that is worth an issue with the document
attached.

`chunking.max_tokens` and `chunking.overlap` are gated settings: changing either
forces a full re-chunk and re-index, and the CLI will tell you so rather than
leaving half your store chunked one way.

## Archives

ZIPs are expanded in memory with four guards, none of them configurable:

- **Path traversal.** An entry that would write outside the workspace is refused.
- **Compression ratio.** A bomb that expands beyond a sane ratio is refused.
- **Nesting depth.** Archives inside archives, bounded.
- **Total size.** Bounded.

A refused archive names why. Five malicious archive fixtures in the test suite
cover these.

## Re-ingesting

Run `lkb ingest` on the same path again and everything comes back `unchanged`.
Dedupe is by SHA-256 of the raw bytes and happens before parsing, so an unchanged
document costs one hash.

A document whose bytes changed gets a **new immutable version**. The old version
is kept, marked superseded, and stops being returned by search. Its chunks stay in
the store, so a historical query can reach them at L6, but a citation can never
point at text that is no longer in the current document.

## Failures do not stop the run

A parse failure names its document and the run continues. All-or-nothing ingest of
somebody's document set is useless in practice: one corrupt PDF should not cost
you the other fifty-five.

Failed documents appear in the output with status `failed` and the error. They are
recorded, not swallowed.

## What ingest does not do

No network. No API key. No language model. Ingest is stages 1 to 6 of eleven, and
it is entirely deterministic. Embedding is a separate command, and everything
after that does not exist yet.

## Sanitisation, and what it will tell you

Two different things happen to hostile content, and the difference matters:

- **Invisible text is removed.** Zero-width characters, bidi overrides, text
  coloured to match its background, `display:none`, HTML comments.
- **Instruction-shaped text is kept and quarantined.** It stays in the document,
  because deleting it would silently rewrite the record, and it is recorded in the
  `quarantine` table with its offsets and the reason.

If your corpus produces quarantine rows, that is worth looking at. See
[the security model](../explanation/security-model.md).
