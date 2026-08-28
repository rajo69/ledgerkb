"""Unit tests for the Tier-0 OpenDocument Text (.odt) parser."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from ledgerkb.core.config import ChunkingConfig
from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import ParseHint
from ledgerkb.ingest.chunk import chunk_document
from ledgerkb.ingest.parsers.odt import OdtParser
from ledgerkb.ingest.parsers.registry import registry


def make_odt(
    content_xml: str,
    meta_xml: str | None = None,
    *,
    mimetype: str = "application/vnd.oasis.opendocument.text",
) -> bytes:
    """Build an in-memory ODT archive with given XML strings."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", mimetype)
        zf.writestr("content.xml", content_xml.strip())
        if meta_xml is not None:
            zf.writestr("meta.xml", meta_xml.strip())
    return buf.getvalue()


SAMPLE_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
                         xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Executive Summary</text:h>
      <text:p>This report outlines the <text:span>quarterly</text:span> performance.</text:p>
      <text:h text:outline-level="2">Financial Review</text:h>
      <text:p>The budget allocation was approved<text:s text:c="3"/>with conditions.</text:p>
      <text:list>
        <text:list-item>
          <text:p>Infrastructure maintenance</text:p>
        </text:list-item>
        <text:list-item>
          <text:p>Capital allocation</text:p>
        </text:list-item>
      </text:list>
      <table:table>
        <table:table-row>
          <table:table-cell><text:p>Project</text:p></table:table-cell>
          <table:table-cell><text:p>Cost</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>Attercliffe</text:p></table:table-cell>
          <table:table-cell><text:p>£2.4m</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""

SAMPLE_META = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                      xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
                      xmlns:dc="http://purl.org/dc/elements/1.1/">
  <office:meta>
    <dc:title>Q1 Performance Report</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:date>2026-03-15T10:00:00Z</dc:date>
  </office:meta>
</office:document-meta>
"""


class TestOdtParser:
    def test_parse_content_and_structure(self) -> None:
        data = make_odt(SAMPLE_CONTENT, SAMPLE_META)
        parser = OdtParser()
        doc = parser.parse(data, ParseHint(filename="test.odt"))

        assert "Executive Summary" in doc.text
        assert "Financial Review" in doc.text
        assert "- Infrastructure maintenance" in doc.text
        assert "| Project | Cost |" in doc.text
        assert "| Attercliffe | £2.4m |" in doc.text

        # 3 spaces from <text:s text:c="3"/>
        assert "approved   with conditions." in doc.text

        # Headings and outline levels
        assert len(doc.headings) == 2
        assert doc.headings[0].text == "Executive Summary"
        assert doc.headings[0].level == 1
        assert doc.headings[1].text == "Financial Review"
        assert doc.headings[1].level == 2

        # Verify heading character offsets match exact locations in doc.text
        for h in doc.headings:
            assert doc.text[h.char_start : h.char_start + len(h.text)] == h.text

        # Metadata
        assert doc.title == "Q1 Performance Report"
        assert doc.authors == ["Jane Doe"]
        assert doc.published_at == date(2026, 3, 15)
        assert doc.parser == "odf-xml"

    def test_slice_back_invariant(self) -> None:
        """Every chunk produced from the parsed ODT document slices back byte-identically."""
        data = make_odt(SAMPLE_CONTENT, SAMPLE_META)
        doc = OdtParser().parse(data, ParseHint(filename="report.odt"))

        chunks = chunk_document(doc, "ws_test", "ver_1", ChunkingConfig(max_tokens=64, overlap=8))
        assert len(chunks) >= 1
        for c in chunks:
            assert doc.text[c.char_start : c.char_end] == c.text

    def test_missing_content_xml_raises(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
            zf.writestr("other.xml", "<root/>")

        with pytest.raises(ParseError, match=r"missing content\.xml"):
            OdtParser().parse(buf.getvalue(), ParseHint(filename="bad.odt"))

    def test_corrupt_archive_raises(self) -> None:
        with pytest.raises(ParseError, match=r"unreadable ODT archive"):
            OdtParser().parse(b"not a valid zip file", ParseHint(filename="corrupt.odt"))

    def test_malformed_xml_raises(self) -> None:
        data = make_odt("<broken><unclosed>", None)
        with pytest.raises(ParseError, match=r"malformed content\.xml in ODT"):
            OdtParser().parse(data, ParseHint(filename="broken.odt"))

    def test_oversized_xml_entry_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ledgerkb.ingest.parsers.odt as odt_mod

        monkeypatch.setattr(odt_mod, "MAX_ENTRY_BYTES", 100)
        data = make_odt(SAMPLE_CONTENT, SAMPLE_META)
        with pytest.raises(ParseError, match=r"exceeds decompressed size limit"):
            OdtParser().parse(data, ParseHint(filename="oversized.odt"))

    def test_registry_dispatches_odt(self) -> None:
        p = registry.for_file("minutes.odt")
        assert isinstance(p, OdtParser)
        assert p.can_parse("application/vnd.oasis.opendocument.text", "minutes.odt")
        assert p.can_parse("", "template.ott")
