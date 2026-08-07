"""DOCX, XLSX and PPTX via their native readers.

Tier 0 for office formats: these files are structured XML, so there is nothing
to infer and no OCR to run. Docling (the ``[docling]`` extra) is reserved for
documents where layout genuinely has to be reconstructed.

All three build text by appending and tracking the cursor, so heading offsets
are exact rather than found by searching for the heading text afterwards —
which would pick the wrong occurrence whenever a heading repeats.
"""

from __future__ import annotations

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint


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


class DocxParser:
    name = "python-docx"
    extensions = (".docx",)

    def can_parse(self, mime: str, path: str) -> bool:
        return (
            mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or path.lower().endswith(self.extensions)
        )

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        import io

        uri = hint.uri or hint.filename or "<bytes>"
        docx = _require("docx", uri, "DOCX")
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(uri, f"unreadable DOCX: {exc}") from exc

        b = _Builder()
        for para in document.paragraphs:
            style = (para.style.name or "") if para.style else ""
            b.add(para.text, heading=_is_heading(style), level=_heading_level(style))

        for table in document.tables:
            b.add("")
            for row in table.rows:
                b.add("| " + " | ".join(c.text.replace("\n", " ") for c in row.cells) + " |")

        core = document.core_properties
        title = (core.title or "").strip() or None
        authors = [a for a in [(core.author or "").strip()] if a]
        published = core.created.date() if core.created else None

        return ParsedDocument(
            text=b.text,
            parser=self.name,
            parse_quality=1.0,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headings=b.headings,
            title=title or (b.headings[0].text if b.headings else hint.filename),
            authors=authors,
            published_at=published,
        )


class XlsxParser:
    name = "openpyxl"
    extensions = (".xlsx", ".xlsm")

    def can_parse(self, mime: str, path: str) -> bool:
        return (
            "spreadsheetml" in mime or path.lower().endswith(self.extensions)
        )

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        import io

        uri = hint.uri or hint.filename or "<bytes>"
        openpyxl = _require("openpyxl", uri, "XLSX")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as exc:
            raise ParseError(uri, f"unreadable XLSX: {exc}") from exc

        b = _Builder()
        try:
            for sheet in wb.worksheets:
                b.add(f"## {sheet.title}", heading=True, level=1)
                b.add("")
                for row in sheet.iter_rows(values_only=True):
                    if row is None or all(c is None for c in row):
                        continue
                    cells = ["" if c is None else str(c) for c in row]
                    b.add("| " + " | ".join(cells) + " |")
                b.add("")
        finally:
            wb.close()

        props = wb.properties
        return ParsedDocument(
            text=b.text,
            parser=self.name,
            parse_quality=1.0,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headings=b.headings,
            title=(props.title or "").strip() or hint.filename,
            authors=[a for a in [(props.creator or "").strip()] if a],
            published_at=props.created.date() if props.created else None,
        )


class PptxParser:
    name = "python-pptx"
    extensions = (".pptx",)

    def can_parse(self, mime: str, path: str) -> bool:
        return "presentationml" in mime or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        import io

        uri = hint.uri or hint.filename or "<bytes>"
        pptx = _require("pptx", uri, "PPTX")
        try:
            deck = pptx.Presentation(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(uri, f"unreadable PPTX: {exc}") from exc

        b = _Builder()
        page_offsets: list[int] = []
        count = 0

        for index, slide in enumerate(deck.slides, start=1):
            page_offsets.append(b.cursor)
            count += 1
            title_shape = slide.shapes.title
            label = (title_shape.text or "").strip() if title_shape is not None else ""
            b.add(f"## Slide {index}{': ' + label if label else ''}", heading=True, level=2)

            for shape in slide.shapes:
                if shape is title_shape or not getattr(shape, "has_text_frame", False):
                    continue
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        b.add(line)

            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
                if notes:
                    # Speaker notes do not appear on the rendered slide. They are
                    # kept, but marked, so a claim sourced from them is visibly
                    # sourced from them.
                    b.add(f"[speaker notes] {notes}")
            b.add("")

        props = deck.core_properties
        return ParsedDocument(
            text=b.text,
            parser=self.name,
            parse_quality=1.0,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            page_count=count,
            page_offsets=page_offsets,
            headings=b.headings,
            title=(props.title or "").strip() or hint.filename,
            authors=[a for a in [(props.author or "").strip()] if a],
            published_at=props.created.date() if props.created else None,
        )


def _is_heading(style: str) -> bool:
    return style.startswith("Heading") or style == "Title"


def _heading_level(style: str) -> int:
    """Word's "Heading 3" maps to level 3; "Title" outranks everything."""
    if style == "Title":
        return 1
    tail = style.removeprefix("Heading").strip()
    return int(tail) if tail.isdigit() and 1 <= int(tail) <= 6 else 2


def _require(module: str, uri: str, label: str):  # noqa: ANN202
    try:
        return __import__(module)
    except ImportError as exc:
        raise ParseError(
            uri, f"{label} support needs the 'local' extra: pip install 'ledgerkb[local]'"
        ) from exc


__all__ = ["DocxParser", "PptxParser", "XlsxParser"]
