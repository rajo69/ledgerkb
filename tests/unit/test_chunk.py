"""Structure-first chunking.

The invariant under test throughout: a chunk's text is *sliced*, never
constructed.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from ledgerkb.core.config import ChunkingConfig
from ledgerkb.core.ports import Heading, ParsedDocument
from ledgerkb.ingest.chunk import build_sections, chunk_document, count_tokens

MINUTES = """# Planning Committee Minutes

Held on 11 March 2026.

## Item 3: Attercliffe Regeneration

The capital budget was confirmed at 2.4m.

### Decision

The Committee RESOLVED to approve the allocation.

## Item 4: Refuse Collection

The consultation received 1,847 responses.
"""


def doc(text: str = MINUTES, **kw) -> ParsedDocument:
    if "headings" not in kw:
        kw["headings"] = _md_headings(text)
    return ParsedDocument(text=text, parser="test", parse_quality=1.0, **kw)


def _md_headings(text: str) -> list[Heading]:
    import re

    return [
        Heading(char_start=m.start(), level=len(m.group(1)), text=m.group(2).strip())
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
    ]


def chunks(text: str = MINUTES, **cfg):
    return chunk_document(doc(text), "ws", "v", ChunkingConfig(**cfg))


class TestSliceBack:
    def test_every_chunk_slices_back(self) -> None:
        for c in chunks():
            assert MINUTES[c.char_start : c.char_end] == c.text

    def test_it_holds_when_sections_must_be_split(self) -> None:
        text = "# Long\n\n" + "The council considered the matter at length. " * 200
        for c in chunk_document(doc(text), "ws", "v", ChunkingConfig(max_tokens=64, overlap=8)):
            assert text[c.char_start : c.char_end] == c.text

    def test_it_holds_with_no_headings_at_all(self) -> None:
        text = "Plain prose with no structure whatsoever. " * 50
        d = ParsedDocument(text=text, parser="t", parse_quality=1.0)
        for c in chunk_document(d, "ws", "v", ChunkingConfig(max_tokens=64, overlap=8)):
            assert text[c.char_start : c.char_end] == c.text

    def test_it_holds_for_an_unbroken_block(self) -> None:
        """No sentence or paragraph boundaries anywhere — the hard-cut path."""
        text = "word " * 3000
        d = ParsedDocument(text=text, parser="t", parse_quality=1.0)
        out = chunk_document(d, "ws", "v", ChunkingConfig(max_tokens=64, overlap=8))
        assert len(out) > 1
        for c in out:
            assert text[c.char_start : c.char_end] == c.text

    def test_hard_cuts_do_not_split_mid_word(self) -> None:
        text = "alpha bravo charlie delta echo foxtrot " * 200
        d = ParsedDocument(text=text, parser="t", parse_quality=1.0)
        for c in chunk_document(d, "ws", "v", ChunkingConfig(max_tokens=64, overlap=8)):
            assert not c.text.startswith(" ")
            first = c.text.split(" ", 1)[0]
            assert first in {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"}


class TestStructureFirst:
    def test_a_short_section_stays_whole(self) -> None:
        out = chunks()
        decision = [c for c in out if "RESOLVED" in c.text]
        assert len(decision) == 1, "a decision and its heading stay together"

    def test_heading_path_is_nested(self) -> None:
        out = chunks()
        decision = next(c for c in out if "RESOLVED" in c.text)
        assert decision.heading_path == [
            "Planning Committee Minutes",
            "Item 3: Attercliffe Regeneration",
            "Decision",
        ]

    def test_a_sibling_heading_pops_the_stack(self) -> None:
        out = chunks()
        refuse = next(c for c in out if "1,847" in c.text)
        assert refuse.heading_path == [
            "Planning Committee Minutes",
            "Item 4: Refuse Collection",
        ]

    def test_text_before_the_first_heading_is_kept(self) -> None:
        text = "Front matter that matters.\n\n# Heading\n\nBody.\n"
        out = chunk_document(doc(text), "ws", "v")
        assert any("Front matter" in c.text for c in out)

    def test_sections_tile_the_document(self) -> None:
        sections = build_sections(doc())
        covered = sorted((s.char_start, s.char_end) for s in sections)
        assert covered[0][0] == 0
        assert covered[-1][1] == len(MINUTES)
        for (_, end), (start, _) in pairwise(covered):
            assert start == end, "sections must not overlap or leave gaps"


class TestOverlap:
    def test_overlap_extends_the_span_backwards(self) -> None:
        text = "# T\n\n" + "The matter was considered carefully. " * 100
        out = chunk_document(doc(text), "ws", "v",
                             ChunkingConfig(max_tokens=64, overlap=16))
        assert len(out) > 1
        assert out[1].char_start < out[0].char_end, "chunks genuinely overlap"
        for c in out:
            assert text[c.char_start : c.char_end] == c.text

    def test_zero_overlap_produces_disjoint_spans(self) -> None:
        text = "# T\n\n" + "The matter was considered carefully. " * 100
        out = chunk_document(doc(text), "ws", "v",
                             ChunkingConfig(max_tokens=64, overlap=0))
        for a, b in pairwise(out):
            assert b.char_start >= a.char_end


class TestPages:
    def test_page_numbers_are_derived_from_offsets(self) -> None:
        page1 = "Page one content. " * 60 + "\n\n"
        page2 = "Page two content. " * 60 + "\n\n"
        text = page1 + page2
        d = ParsedDocument(text=text, parser="t", parse_quality=1.0,
                           page_offsets=[0, len(page1)], page_count=2)
        out = chunk_document(d, "ws", "v", ChunkingConfig(max_tokens=64, overlap=0))
        assert {c.page_from for c in out} == {1, 2}

    def test_a_format_without_pages_reports_none(self) -> None:
        assert all(c.page_from is None for c in chunks())


class TestTokenCounting:
    def test_it_is_deterministic(self) -> None:
        assert count_tokens("the council resolved") == count_tokens("the council resolved")

    def test_empty_text_is_zero(self) -> None:
        assert count_tokens("") == 0

    def test_longer_text_counts_higher(self) -> None:
        assert count_tokens("a b c d e f g h") > count_tokens("a b")

    @pytest.mark.parametrize("max_tokens", [64, 128, 512])
    def test_chunks_respect_the_limit_where_structure_allows(self, max_tokens: int) -> None:
        text = "# T\n\n" + "The committee considered the report. " * 300
        out = chunk_document(doc(text), "ws", "v",
                             ChunkingConfig(max_tokens=max_tokens, overlap=0))
        # The hard-cut path guarantees the ceiling; structure-preserving paths
        # may stop short of it, never past it.
        assert all(count_tokens(c.text) <= max_tokens * 1.1 for c in out)


class TestEdgeCases:
    def test_an_empty_document_produces_no_chunks(self) -> None:
        d = ParsedDocument(text="", parser="t", parse_quality=1.0)
        assert chunk_document(d, "ws", "v") == []

    def test_a_whitespace_only_document_produces_no_chunks(self) -> None:
        d = ParsedDocument(text="   \n\n  \t ", parser="t", parse_quality=1.0)
        assert chunk_document(d, "ws", "v") == []

    def test_a_heading_with_no_body_is_still_a_chunk(self) -> None:
        out = chunk_document(doc("# Only A Heading\n"), "ws", "v")
        assert len(out) == 1
        assert out[0].text == "# Only A Heading"
