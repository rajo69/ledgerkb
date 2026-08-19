# Add a parser

A worked example of the Protocol ports, using the smallest one. This is also the
friendliest first contribution to the repository.

## The contract

```python test="skip"
class Parser(Protocol):
    name: str
    def can_parse(self, mime: str, path: str) -> bool: ...
    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument: ...
```

Two methods. There is nothing to subclass and nothing to register with a
framework: a class with these methods satisfies the port.

## The one rule that matters

`ParsedDocument.text` is the single source of truth for every offset downstream.
Every `Heading.char_start` and every entry in `page_offsets` must index into that
exact string.

Get this wrong and chunk offsets are wrong, which means citations point at the
wrong characters, which means the guarantee the whole system rests on is broken.
There is a property test that will catch you, and it is easier to be right the
first time.

The technique the existing parsers use: build the text by appending to a list
while tracking the running length, so an offset is recorded at the moment the text
is appended rather than recovered by searching for it afterwards.

```python test="skip"
parts: list[str] = []
headings: list[Heading] = []
cursor = 0

for section in source_sections:
    headings.append(Heading(char_start=cursor, level=section.level, text=section.title))
    block = f"{section.title}\n\n{section.body}\n\n"
    parts.append(block)
    cursor += len(block)

text = "".join(parts)
```

Normalise newlines **before** taking any offset. `\r\n` to `\n`, `\r` to `\n`. The
test matrix includes Windows, and a parser that normalises later produces
different offsets on different platforms for the same document.

## A worked example: RTF

RTF is in `KNOWN_UNSUPPORTED`, so it currently raises a helpful error. Here is
what replacing that with a parser looks like.

```python test="skip"
# src/ledgerkb/ingest/parsers/rtf.py
"""Tier-0 RTF. Enough for documents that are text with a little formatting."""

from __future__ import annotations

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint


class RtfParser:
    name = "rtf"
    extensions = (".rtf",)

    def can_parse(self, mime: str, path: str) -> bool:
        return mime == "application/rtf" or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        try:
            text, headings = _strip_control_words(data)
        except ValueError as exc:
            raise ParseError(hint.uri or "<bytes>", f"not readable as RTF: {exc}") from exc

        return ParsedDocument(
            text=text,
            parser=self.name,
            parse_quality=0.8,
            mime="application/rtf",
            headings=headings,
            title=headings[0].text if headings else None,
            warnings=[],
        )
```

Then register it, before the text catch-all:

```python test="skip"
# src/ledgerkb/ingest/parsers/registry.py
DEFAULT_PARSERS: tuple[Parser, ...] = (
    PdfParser(),
    DocxParser(),
    XlsxParser(),
    PptxParser(),
    HtmlParser(),
    RtfParser(),           # new
    EmailParser(),
    CsvParser(),
    JsonParser(),
    TextParser(),          # last: it claims anything text/*
)
```

Order matters. The first parser that claims a file wins, so specific formats go
before general ones and `TextParser` stays last.

Remove `.rtf` from `KNOWN_UNSUPPORTED` in the same change, or the helpful error
will now be a lie.

## Failing well

Raise `ParseError(path, reason)` when you cannot read a file. Never return
half-decoded text: a DOCX decoded as latin-1 produces plausible-looking rubbish
that would then be embedded, cited and quoted back to somebody as evidence.

The pipeline catches `ParseError`, names the document and continues with the rest
of the run. One bad file does not cost the other fifty-five.

Put anything recoverable in `warnings` instead. Those land on the document version
as `parse_warnings`, so a later reader can see why a document came out the way it
did.

## `parse_quality`

A 0 to 1 confidence. Native formats where the bytes already are the text score
1.0. A PDF text layer scores by extractable characters per page area, which is
also what routes a document to a heavier parser when tier 1 arrives.

Be honest with this number. It is what a future tiered cascade will route on.

## Dependencies

If your parser needs a third-party package, it goes in the `parsers` extra in
`pyproject.toml` with a version floor, and the import must be lazy so the base
install still works without it.

Licence check first. Copyleft is not automatically out, but it must be an opt-in
extra rather than a default, which is why `pypdfium2` (Apache/BSD) is the default
PDF parser and AGPL-licensed PyMuPDF is an extra.

## Testing it

Add a document of your format to `tests/fixtures/build_corpus.py`. It is
generative, so this is a function that writes a file rather than a binary to
commit. Then:

```bash
uv run pytest tests/unit -k rtf
uv run pytest tests/property/test_offsets.py   # the invariant, over the whole corpus
uv run pytest                                  # everything
```

The property test is the one that matters. It slices every chunk back out of every
document and compares byte for byte, including after sanitisation.

## The same pattern for the other ports

`Store`, `Chunker`, `Reranker`, `ChatModel`, `Embedder` and `Reader` work
identically: implement the methods, pass the object in. Nothing downstream asks
where an object came from, which is what makes the extension point real rather
than nominal. See [Ports](../reference/ports.md).
