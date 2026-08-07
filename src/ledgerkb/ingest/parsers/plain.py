"""Tier-0 native parsers: TXT, MD, CSV, JSON, EML.

No third-party dependency, no network. These handle the formats where the bytes
already are the text, or nearly so.

Every parser here builds its output by appending to a list and tracking the
running length, so heading and page offsets are exact by construction rather
than recovered by searching afterwards.
"""

from __future__ import annotations

import csv
import io
import json
import re
from email import policy
from email.parser import BytesParser
from typing import Any

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$", re.MULTILINE)
SETEXT_HEADING = re.compile(r"^(?P<text>[^\n]+)\n(?P<rule>=+|-+)[ \t]*$", re.MULTILINE)


def decode(data: bytes, uri: str = "<bytes>") -> str:
    """Decode with a short, ordered fallback chain.

    UTF-8 first, then the two encodings that actually turn up in council
    exports. Latin-1 last because it cannot fail — which makes it a terminator,
    not a guess worth reporting as success.
    """
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("latin-1")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 cannot fail
        raise ParseError(uri, f"undecodable bytes: {exc}") from exc


def _normalise_newlines(text: str) -> str:
    """CRLF to LF, before any offset is taken.

    The test matrix includes Windows. If this ran later, the same document would
    produce different offsets on different platforms.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TextParser:
    """TXT and MD. Markdown headings become the heading tree."""

    name = "text"
    extensions = (".txt", ".md", ".markdown", ".text", ".log")

    def can_parse(self, mime: str, path: str) -> bool:
        return mime.startswith("text/") or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        text = _normalise_newlines(decode(data, hint.uri or "<bytes>"))
        headings: list[Heading] = [
            Heading(char_start=m.start(), level=len(m.group(1)), text=m.group(2).strip())
            for m in MD_HEADING.finditer(text)
        ]
        headings.extend(
            Heading(
                char_start=m.start("text"),
                level=1 if m.group("rule").startswith("=") else 2,
                text=m.group("text").strip(),
            )
            for m in SETEXT_HEADING.finditer(text)
        )
        headings.sort(key=lambda h: h.char_start)

        title = None
        if headings:
            title = headings[0].text
        elif text.strip():
            title = text.strip().splitlines()[0][:200]

        return ParsedDocument(
            text=text,
            parser=self.name,
            parse_quality=1.0,          # the bytes are the text; nothing was inferred
            mime=hint.mime or "text/plain",
            headings=headings,
            title=title,
        )


class CsvParser:
    """CSV and TSV rendered as a markdown table.

    A table is flattened to text because that is what gets embedded and quoted.
    Rendering is deterministic so the same file always yields the same offsets.
    """

    name = "csv"
    extensions = (".csv", ".tsv")

    def can_parse(self, mime: str, path: str) -> bool:
        return "csv" in mime or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        raw = _normalise_newlines(decode(data, hint.uri or "<bytes>"))
        delimiter = "\t" if (hint.filename or "").lower().endswith(".tsv") else ","
        try:
            rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
        except csv.Error as exc:
            raise ParseError(hint.uri or "<bytes>", f"malformed CSV: {exc}") from exc

        if not rows:
            return ParsedDocument(text="", parser=self.name, parse_quality=1.0,
                                  mime=hint.mime or "text/csv")

        parts: list[str] = []
        header, *body = rows
        parts.append("| " + " | ".join(header) + " |")
        parts.append("| " + " | ".join("---" for _ in header) + " |")
        for row in body:
            padded = row + [""] * (len(header) - len(row))
            parts.append("| " + " | ".join(padded[: len(header)]) + " |")

        text = "\n".join(parts)
        return ParsedDocument(
            text=text,
            parser=self.name,
            parse_quality=1.0,
            mime=hint.mime or "text/csv",
            title=(hint.filename or None),
        )


class JsonParser:
    """JSON pretty-printed. Stable key order, so offsets are reproducible."""

    name = "json"
    extensions = (".json", ".jsonl", ".ndjson")

    def can_parse(self, mime: str, path: str) -> bool:
        return "json" in mime or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        raw = decode(data, hint.uri or "<bytes>")
        name = (hint.filename or "").lower()
        try:
            if name.endswith((".jsonl", ".ndjson")):
                parsed: Any = [json.loads(line) for line in raw.splitlines() if line.strip()]
            else:
                parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParseError(hint.uri or "<bytes>", f"invalid JSON: {exc}") from exc

        text = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
        return ParsedDocument(
            text=_normalise_newlines(text),
            parser=self.name,
            parse_quality=1.0,
            mime=hint.mime or "application/json",
            title=(hint.filename or None),
        )


class EmailParser:
    """EML. Headers carry the metadata the brief asks for, so they are kept as
    visible text rather than stripped into a side channel."""

    name = "email"
    extensions = (".eml", ".mbox")

    def can_parse(self, mime: str, path: str) -> bool:
        return "rfc822" in mime or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        try:
            msg = BytesParser(policy=policy.default).parsebytes(data)
        except Exception as exc:
            raise ParseError(hint.uri or "<bytes>", f"unreadable email: {exc}") from exc

        parts: list[str] = []
        headings: list[Heading] = []
        cursor = 0

        def add(line: str, *, heading: bool = False) -> None:
            nonlocal cursor
            if heading:
                headings.append(Heading(char_start=cursor, level=2, text=line.strip()))
            parts.append(line)
            cursor += len(line) + 1

        subject = str(msg.get("Subject", "") or "")
        for field_name in ("From", "To", "Cc", "Date", "Subject"):
            value = msg.get(field_name)
            if value:
                add(f"{field_name}: {value}")
        add("")

        body = msg.get_body(preferencelist=("plain", "html"))
        if body is not None:
            content = body.get_content()
            if body.get_content_subtype() == "html":
                content = re.sub(r"<[^>]+>", " ", content)
            for line in _normalise_newlines(str(content)).split("\n"):
                add(line)

        attachments = [
            a.get_filename() for a in msg.iter_attachments() if a.get_filename()
        ]
        if attachments:
            add("")
            add("Attachments", heading=True)
            for a in attachments:
                add(f"- {a}")

        published = None
        if (date_header := msg.get("Date")) is not None:
            published = _parse_email_date(str(date_header))

        return ParsedDocument(
            text="\n".join(parts),
            parser=self.name,
            parse_quality=1.0,
            mime=hint.mime or "message/rfc822",
            headings=headings,
            title=subject or (hint.filename or None),
            authors=[str(msg.get("From"))] if msg.get("From") else [],
            published_at=published,
            warnings=[f"attachment not ingested: {a}" for a in attachments],
        )


def _parse_email_date(raw: str):  # noqa: ANN202 - returns date | None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


__all__ = ["CsvParser", "EmailParser", "JsonParser", "TextParser", "decode"]
