"""OpenDocument Text (.odt) via native XML parsing.

Tier 0 for ODF formats: an .odt file is a ZIP archive containing structured XML
(content.xml and meta.xml), so there is nothing to infer, no external tool required,
and no OCR to run.

Exact offsets and heading hierarchies are tracked during parsing so heading offsets
match the source text without string searching.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint

# XML namespaces used across OpenDocument standard
_NS_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_NS_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_NS_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_NS_DC = "{http://purl.org/dc/elements/1.1/}"
_NS_META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"

# Security guards for ZIP extraction of XML members in ODT
MAX_ENTRY_BYTES = 64 * 1024 * 1024  # 64 MiB decompressed limit for XML payloads
MAX_RATIO = 100.0                   # Max compression expansion ratio


def _safe_read_xml(archive: zipfile.ZipFile, entry_name: str, uri: str) -> bytes:
    """Read an XML entry from the archive applying decompression size and ratio guards."""
    try:
        info = archive.getinfo(entry_name)
    except KeyError as exc:
        raise ParseError(uri, f"missing entry {entry_name!r} in ODT archive") from exc

    if info.file_size > MAX_ENTRY_BYTES:
        raise ParseError(
            uri,
            f"entry {entry_name!r} exceeds decompressed size limit "
            f"({info.file_size} > {MAX_ENTRY_BYTES} bytes)",
        )

    if info.compress_size > 0 and info.file_size > 1024 * 1024:
        ratio = info.file_size / info.compress_size
        if ratio > MAX_RATIO:
            raise ParseError(
                uri,
                f"entry {entry_name!r} trips compression ratio guard "
                f"({ratio:.1f} > {MAX_RATIO})",
            )

    return archive.read(entry_name)


class _Builder:
    """Accumulates lines and records heading offsets as it goes."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.headings: list[Heading] = []
        self.cursor = 0

    def add(self, line: str, *, heading: bool = False, level: int = 2) -> None:
        if heading and line.strip():
            self.headings.append(
                Heading(char_start=self.cursor, level=level, text=line.strip())
            )
        self.parts.append(line)
        self.cursor += len(line) + 1

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


class OdtParser:
    name = "odf-xml"
    extensions = (".odt", ".ott")

    def can_parse(self, mime: str, path: str) -> bool:
        accepted_mimes = (
            "application/vnd.oasis.opendocument.text",
            "application/x-vnd.oasis.opendocument.text",
        )
        return mime in accepted_mimes or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        uri = hint.uri or hint.filename or "<bytes>"

        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ParseError(uri, f"unreadable ODT archive: {exc}") from exc

        with archive:
            if "content.xml" not in archive.namelist():
                raise ParseError(uri, "invalid ODT: missing content.xml")

            try:
                content_bytes = _safe_read_xml(archive, "content.xml", uri)
                root = ET.fromstring(content_bytes)
            except ParseError:
                raise
            except Exception as exc:
                raise ParseError(uri, f"malformed content.xml in ODT: {exc}") from exc

            meta_title: str | None = None
            meta_authors: list[str] = []
            meta_published: date | None = None

            if "meta.xml" in archive.namelist():
                try:
                    meta_bytes = _safe_read_xml(archive, "meta.xml", uri)
                    meta_root = ET.fromstring(meta_bytes)
                    meta_title, meta_authors, meta_published = _extract_metadata(meta_root)
                except (ET.ParseError, ValueError, KeyError):
                    # Malformed metadata in an otherwise readable document is ignored
                    meta_title = None
                    meta_authors = []
                    meta_published = None

        b = _Builder()
        _parse_body(root, b)

        title = meta_title or (b.headings[0].text if b.headings else hint.filename)

        return ParsedDocument(
            text=b.text,
            parser=self.name,
            parse_quality=1.0,
            mime="application/vnd.oasis.opendocument.text",
            headings=b.headings,
            title=title,
            authors=meta_authors,
            published_at=meta_published,
        )


def _extract_text_content(elem: ET.Element) -> str:
    """Extract full inner text of an element handling text nodes, spans, tabs, and spaces."""
    parts: list[str] = []

    def _traverse(node: ET.Element) -> None:
        tag = node.tag
        if tag == f"{_NS_TEXT}s":
            # Repeated space tag: text:c attribute indicates count (default 1)
            count = int(node.attrib.get(f"{_NS_TEXT}c", 1))
            parts.append(" " * count)
        elif tag == f"{_NS_TEXT}tab":
            parts.append("\t")
        elif tag == f"{_NS_TEXT}line-break":
            parts.append("\n")

        if node.text:
            parts.append(node.text)

        for child in node:
            _traverse(child)
            if child.tail:
                parts.append(child.tail)

    if elem.text:
        parts.append(elem.text)

    for child in elem:
        _traverse(child)
        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _parse_body(root: ET.Element, b: _Builder) -> None:
    """Find text container and recursively parse headings, paragraphs, lists, and tables."""
    # Locate <office:body> -> <office:text>
    body = root.find(f".//{_NS_OFFICE}text")
    if body is None:
        body = root.find(f".//{_NS_OFFICE}body")
        if body is None:
            body = root

    _parse_element_children(body, b)


def _parse_element_children(parent: ET.Element, b: _Builder, list_depth: int = 0) -> None:
    for child in parent:
        tag = child.tag

        if tag == f"{_NS_TEXT}h":
            level_str = child.attrib.get(f"{_NS_TEXT}outline-level", "2")
            try:
                level = int(level_str)
                level = max(1, min(6, level))
            except ValueError:
                level = 2
            text = _extract_text_content(child).strip()
            if text:
                b.add(text, heading=True, level=level)

        elif tag == f"{_NS_TEXT}p":
            text = _extract_text_content(child)
            if list_depth > 0:
                indent = "  " * (list_depth - 1)
                text = f"{indent}- {text.strip()}"
            b.add(text)

        elif tag == f"{_NS_TEXT}list":
            for item in child:
                if item.tag == f"{_NS_TEXT}list-item":
                    _parse_element_children(item, b, list_depth=list_depth + 1)

        elif tag == f"{_NS_TABLE}table":
            b.add("")
            for row in child.findall(f".//{_NS_TABLE}table-row"):
                cells: list[str] = []
                for cell in row.findall(f".//{_NS_TABLE}table-cell"):
                    # Table cell might have multiple paragraphs
                    cell_text = " ".join(
                        _extract_text_content(p).strip()
                        for p in cell.findall(f".//{_NS_TEXT}p")
                    )
                    cells.append(cell_text.replace("\n", " "))
                if cells:
                    b.add("| " + " | ".join(cells) + " |")
            b.add("")

        elif tag in (f"{_NS_TEXT}section", f"{_NS_OFFICE}text", f"{_NS_OFFICE}body"):
            _parse_element_children(child, b, list_depth=list_depth)


def _extract_metadata(meta_root: ET.Element) -> tuple[str | None, list[str], date | None]:
    title_elem = meta_root.find(f".//{_NS_DC}title")
    title = (title_elem.text or "").strip() if title_elem is not None and title_elem.text else None

    creator_elem = meta_root.find(f".//{_NS_DC}creator")
    if creator_elem is None or not creator_elem.text:
        creator_elem = meta_root.find(f".//{_NS_META}initial-creator")

    authors: list[str] = []
    if creator_elem is not None and creator_elem.text:
        author = creator_elem.text.strip()
        if author:
            authors.append(author)

    date_elem = meta_root.find(f".//{_NS_DC}date")
    if date_elem is None or not date_elem.text:
        date_elem = meta_root.find(f".//{_NS_META}creation-date")

    published: date | None = None
    if date_elem is not None and date_elem.text:
        published = _parse_date_str(date_elem.text.strip())

    return title, authors, published


def _parse_date_str(val: str) -> date | None:
    # Handles ISO formats like 2026-03-15T10:00:00Z, 2026-03-15, 2026-03-15T10:00:00+00:00
    cleaned = val.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).date()
    except (ValueError, TypeError):
        pass

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", val)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


__all__ = ["OdtParser"]
