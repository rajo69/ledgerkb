"""Parser dispatch.

Order matters: the first parser that claims a file wins, so specific formats are
registered before the text catch-all. A file nobody claims raises a named
``ParseError`` rather than being guessed at as text, because a DOCX silently
decoded as latin-1 produces plausible-looking rubbish that would then be
embedded, cited and quoted.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import ParsedDocument, ParseHint, Parser
from ledgerkb.ingest.parsers.html import HtmlParser
from ledgerkb.ingest.parsers.office import DocxParser, PptxParser, XlsxParser
from ledgerkb.ingest.parsers.pdf import PdfParser
from ledgerkb.ingest.parsers.plain import CsvParser, EmailParser, JsonParser, TextParser

DEFAULT_PARSERS: tuple[Parser, ...] = (
    PdfParser(),
    DocxParser(),
    XlsxParser(),
    PptxParser(),
    HtmlParser(),
    EmailParser(),
    CsvParser(),
    JsonParser(),
    TextParser(),          # last: it claims anything text/*
)

# Extensions we recognise but cannot read at tier 0. Naming them produces a
# useful message instead of a confusing one.
KNOWN_UNSUPPORTED = {
    ".doc": "legacy Word (.doc)",
    ".xls": "legacy Excel (.xls)",
    ".ppt": "legacy PowerPoint (.ppt)",
    ".rtf": "RTF",
    ".pages": "Apple Pages",
    ".odt": "OpenDocument Text",
}


class ParserRegistry:
    def __init__(self, parsers: tuple[Parser, ...] = DEFAULT_PARSERS) -> None:
        self.parsers = parsers

    def for_file(self, path: str, mime: str | None = None) -> Parser:
        mime = mime or guess_mime(path)
        for parser in self.parsers:
            if parser.can_parse(mime, path):
                return parser

        suffix = Path(path).suffix.lower()
        if suffix in KNOWN_UNSUPPORTED:
            raise ParseError(
                path,
                f"{KNOWN_UNSUPPORTED[suffix]} is not supported at tier 0. "
                "Convert it, or install the 'docling' extra.",
            )
        raise ParseError(path, f"no parser handles {suffix or mime!r}")

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        path = hint.filename or hint.uri or ""
        parser = self.for_file(path, hint.mime)
        return parser.parse(data, hint)


def guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


registry = ParserRegistry()

__all__ = ["DEFAULT_PARSERS", "KNOWN_UNSUPPORTED", "ParserRegistry", "guess_mime", "registry"]
