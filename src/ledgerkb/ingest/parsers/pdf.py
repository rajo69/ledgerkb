"""PDF, tier 0 — ``pypdfium2``.

Apache-2.0/BSD licensed, which is why it is the default rather than
``pymupdf4llm``: AGPL-3.0 in a library that other people embed would reach
further than this project has any right to.

A text-density probe decides whether tier 0 is enough. Born-digital council
PDFs — the large majority — go down this free path; scanned or heavily tabular
documents are routed to the ``[docling]`` extra instead of being silently
parsed into rubbish.
"""

from __future__ import annotations

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import ParsedDocument, ParseHint

PAGE_SEPARATOR = "\n\n"


class PdfParser:
    """Implements :class:`ledgerkb.core.ports.Parser` for born-digital PDFs."""

    name = "pypdfium2"
    extensions = (".pdf",)

    def can_parse(self, mime: str, path: str) -> bool:
        return mime == "application/pdf" or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        pdfium = _import_pdfium(hint)
        uri = hint.uri or hint.filename or "<bytes>"

        try:
            pdf = pdfium.PdfDocument(data)
        except Exception as exc:
            raise ParseError(uri, f"could not open PDF: {exc}") from exc

        try:
            pages: list[str] = []
            page_offsets: list[int] = []
            areas: list[float] = []
            warnings: list[str] = []
            cursor = 0

            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    text = page.get_textpage().get_text_bounded()
                except Exception as exc:
                    # One bad page must not cost the other fifty-five. The gap
                    # is named rather than silently swallowed.
                    text = ""
                    warnings.append(f"page {index + 1} unreadable: {exc}")

                width, height = page.get_size()
                areas.append(max(width * height, 1.0))

                text = text.replace("\r\n", "\n").replace("\r", "\n")
                page_offsets.append(cursor)
                pages.append(text)
                cursor += len(text) + len(PAGE_SEPARATOR)

            full = PAGE_SEPARATOR.join(pages)
            quality = _density(pages, areas)
            warnings.extend(_quality_warning(quality, hint))

            return ParsedDocument(
                text=full,
                parser=self.name,
                parse_quality=quality,
                mime="application/pdf",
                page_count=len(pages),
                page_offsets=page_offsets,
                title=_title(pdf) or hint.filename,
                warnings=warnings,
            )
        finally:
            pdf.close()


def _import_pdfium(hint: ParseHint):  # noqa: ANN202 - the module object
    try:
        import pypdfium2
    except ImportError as exc:
        raise ParseError(
            hint.uri or hint.filename or "<bytes>",
            "PDF support needs the 'local' extra: pip install 'ledgerkb[local]'",
        ) from exc
    return pypdfium2


def _density(pages: list[str], areas: list[float]) -> float:
    """Extractable characters per unit of page area, squashed into 0..1.

    A scanned page yields almost nothing and scores near zero; a born-digital
    page of prose scores near one. The number is a routing signal, not a
    quality judgement, and it is recorded on the version so a later reader can
    see why a document went the way it did.
    """
    if not pages:
        return 0.0
    total_chars = sum(len(p.strip()) for p in pages)
    total_area = sum(areas) or 1.0
    # ~1 character per 400 square points is dense prose at typical body sizes.
    return min(1.0, (total_chars / total_area) * 400.0)


def _quality_warning(quality: float, hint: ParseHint) -> list[str]:
    threshold = hint.density_probe if hint.density_probe is not None else 0.6
    if quality >= threshold:
        return []
    if quality < 0.1:
        return [
            "text density near zero - this is probably a scanned PDF. "
            "Install the 'docling' extra for OCR; tier 0 cannot read it."
        ]
    return [
        f"text density {quality:.2f} is below the {threshold:.2f} probe - "
        "tables or columns may be mis-ordered. Consider the 'docling' extra."
    ]


def _title(pdf) -> str | None:  # noqa: ANN001 - pdfium document
    try:
        meta = pdf.get_metadata_dict()
    except Exception:
        return None
    title = (meta or {}).get("Title")
    return title.strip() if isinstance(title, str) and title.strip() else None


__all__ = ["PdfParser"]
