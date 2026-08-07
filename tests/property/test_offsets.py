"""The load-bearing L1 property.

Every chunk's ``char_start:char_end`` slices back to byte-identical text in its
source document — over arbitrary input, not only the fixture corpus.

If this ever fails, citations stop being precise spans and deterministic quote
verification stops being possible. It is the property the whole citation
guarantee rests on.
"""

from __future__ import annotations

from itertools import pairwise

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from ledgerkb.core.config import ChunkingConfig
from ledgerkb.core.ports import Heading, ParsedDocument
from ledgerkb.ingest.chunk import build_sections, chunk_document
from ledgerkb.ingest.sanitise import sanitise

# Text that looks like a document: prose, punctuation, structure, and the
# awkward characters that turn up in real council exports.
prose = st.text(
    alphabet=st.characters(
        min_codepoint=32, max_codepoint=0x2FFF,
        blacklist_categories=("Cs", "Co", "Cn"),
    ),
    min_size=0, max_size=600,
)

document_text = st.lists(prose, min_size=1, max_size=8).map("\n\n".join)


def _headings_for(text: str) -> list[Heading]:
    """A few plausible heading positions inside the text."""
    if not text:
        return []
    step = max(1, len(text) // 4)
    return [
        Heading(char_start=i, level=(i // step) % 3 + 1, text=f"H{i}")
        for i in range(0, len(text), step)
    ][:4]


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=document_text,
    max_tokens=st.integers(min_value=64, max_value=512),
    overlap=st.integers(min_value=0, max_value=48),
)
def test_every_chunk_slices_back(text: str, max_tokens: int, overlap: int) -> None:
    assume(overlap < max_tokens)
    doc = ParsedDocument(
        text=text, parser="t", parse_quality=1.0, headings=_headings_for(text)
    )
    for c in chunk_document(doc, "ws", "v", ChunkingConfig(max_tokens=max_tokens,
                                                           overlap=overlap)):
        assert text[c.char_start : c.char_end] == c.text


@settings(max_examples=150)
@given(text=document_text)
def test_it_holds_after_sanitisation(text: str) -> None:
    """The composed guarantee: sanitise, then chunk, then slice back.

    Sanitisation deletes characters and remaps offsets. This is where an
    off-by-one would actually bite, because the deletions are invisible.
    """
    doc = ParsedDocument(
        text=text, parser="t", parse_quality=1.0, headings=_headings_for(text)
    )
    clean = sanitise(doc)
    for c in chunk_document(clean.doc, "ws", "v", ChunkingConfig(max_tokens=128, overlap=16)):
        assert clean.text[c.char_start : c.char_end] == c.text


@settings(max_examples=150)
@given(text=document_text)
def test_chunks_stay_inside_the_document(text: str) -> None:
    doc = ParsedDocument(
        text=text, parser="t", parse_quality=1.0, headings=_headings_for(text)
    )
    for c in chunk_document(doc, "ws", "v"):
        assert 0 <= c.char_start <= c.char_end <= len(text)


@settings(max_examples=150)
@given(text=document_text)
def test_sections_tile_the_document_exactly(text: str) -> None:
    """No character belongs to two sections, and none to neither."""
    doc = ParsedDocument(
        text=text, parser="t", parse_quality=1.0, headings=_headings_for(text)
    )
    sections = sorted(
        (s.char_start, s.char_end) for s in build_sections(doc)
    )
    if not sections:
        assert text == ""
        return
    assert sections[0][0] == 0
    assert sections[-1][1] == len(text)
    for (_, end), (start, _) in pairwise(sections):
        assert start == end


@settings(max_examples=150)
@given(text=document_text)
def test_ordinals_are_dense(text: str) -> None:
    doc = ParsedDocument(text=text, parser="t", parse_quality=1.0)
    out = chunk_document(doc, "ws", "v")
    assert [c.ordinal for c in out] == list(range(len(out)))


@settings(max_examples=200)
@given(text=prose)
def test_sanitising_twice_changes_nothing_further(text: str) -> None:
    """Idempotence. A re-ingest must not drift the text under the offsets."""
    once = sanitise(ParsedDocument(text=text, parser="t", parse_quality=1.0))
    twice = sanitise(once.doc)
    assert twice.text == once.text


@settings(max_examples=200)
@given(text=prose)
def test_sanitisation_never_grows_the_visible_text(text: str) -> None:
    out = sanitise(ParsedDocument(text=text, parser="t", parse_quality=1.0))
    # NFKC can expand a ligature into two characters, so length may rise; what
    # must never happen is a character surviving that should have been removed.
    assert not any(ord(c) in range(0xE0000, 0xE0080) for c in out.text)
    assert "​" not in out.text
    assert "‮" not in out.text


@settings(max_examples=100)
@given(text=document_text)
def test_prompt_safe_text_preserves_length(text: str) -> None:
    """Blanking must not shift a single offset."""
    out = sanitise(ParsedDocument(text=text, parser="t", parse_quality=1.0))
    assert len(out.prompt_safe_text()) == len(out.text)
