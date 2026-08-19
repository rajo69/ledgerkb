"""Stage 6 — structure-first chunking.

Council minutes carry their own structure: numbered agenda items, decision
headings, resolution blocks. Splitting on those boundaries beats
cosine-similarity breakpoints, because a decision and its rationale are
structurally adjacent even when they are semantically dissimilar. A whole
decision stays whole. Only a section that will not fit gets split further.

**The invariant this module exists to protect:** for every chunk,
``document_text[chunk.char_start:chunk.char_end] == chunk.text``, exactly.

That is what makes a citation a precise span rather than a gesture at a page,
and it is what deterministic quote verification checks against later. So chunk
text is never constructed — it is only ever *sliced*. There is no code path here
that builds a chunk's text by joining, stripping or normalising anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ledgerkb.core.config import ChunkingConfig
from ledgerkb.core.models import Chunk
from ledgerkb.core.ports import Heading, ParsedDocument

PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
SENTENCE_END = re.compile(r"(?<=[.!?])[ \t]+(?=[A-Z(\"'\[])|(?<=[.!?])\n")
CHARS_PER_TOKEN = 4.0
"""Rough, deterministic, and dependency-free.

A real tokenizer is a locked setting (changing it shifts every boundary and
breaks stored offsets), so L1 uses a stable estimate rather than pulling in a
tokenizer whose version would silently change chunking under us. Substitute a
real one through the ``Chunker`` port when the cost of being wrong exceeds the
cost of the dependency.
"""


def count_tokens(text: str) -> int:
    """Estimate tokens. Deterministic across platforms and Python versions."""
    if not text:
        return 0
    words = len(text.split())
    return max(words, int(len(text) / CHARS_PER_TOKEN + 0.5))


@dataclass(frozen=True)
class Section:
    """A span of the document under one heading path."""

    char_start: int
    char_end: int
    heading_path: tuple[str, ...]
    page_from: int | None = None
    page_to: int | None = None


def build_sections(doc: ParsedDocument, structure_first: bool = True) -> list[Section]:
    """Turn the heading list into non-overlapping spans covering the document.

    A heading owns everything from its own start until the next heading at the
    same level or shallower. Text before the first heading is its own section
    rather than being discarded — front matter is often where the date lives.

    With ``structure_first`` off the heading tree is ignored and the document is
    one section, so splitting falls through to paragraphs and sentences. That is
    the knob's whole meaning; it is gated because turning it off moves every
    boundary.
    """
    text = doc.text
    if not text:
        return []

    headings = sorted(doc.headings, key=lambda h: h.char_start) if structure_first else []
    if not headings:
        return [Section(0, len(text), ())]

    sections: list[Section] = []

    if headings[0].char_start > 0:
        sections.append(Section(0, headings[0].char_start, ()))

    stack: list[Heading] = []
    for i, h in enumerate(headings):
        while stack and stack[-1].level >= h.level:
            stack.pop()
        stack.append(h)

        end = headings[i + 1].char_start if i + 1 < len(headings) else len(text)
        if end <= h.char_start:
            continue
        sections.append(
            Section(
                char_start=h.char_start,
                char_end=end,
                heading_path=tuple(x.text for x in stack),
            )
        )
    return sections


def chunk_document(
    doc: ParsedDocument,
    workspace_id: str,
    version_id: str,
    cfg: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Structure first, splitting only what will not fit."""
    cfg = cfg or ChunkingConfig()
    text = doc.text
    chunks: list[Chunk] = []
    ordinal = 0

    for section in build_sections(doc, cfg.structure_first):
        for start, end in _split(text, section, cfg):
            start, end = _trim(text, start, end)
            if start >= end:
                continue
            chunks.append(
                Chunk(
                    workspace_id=workspace_id,
                    version_id=version_id,
                    ordinal=ordinal,
                    heading_path=list(section.heading_path),
                    char_start=start,
                    char_end=end,
                    # Sliced, never constructed. This is the invariant.
                    text=text[start:end],
                    token_count=count_tokens(text[start:end]),
                    page_from=_page_of(doc, start),
                    page_to=_page_of(doc, end - 1),
                )
            )
            ordinal += 1

    return chunks


def _split(text: str, section: Section, cfg: ChunkingConfig) -> list[tuple[int, int]]:
    """Yield spans for one section, descending only as far as needed.

    Whole section, then paragraphs, then sentences, then a hard cut. Each level
    is tried only when the level above overflows, so structure is preserved
    wherever it can be.
    """
    body = text[section.char_start : section.char_end]
    if count_tokens(body) <= cfg.max_tokens:
        return [(section.char_start, section.char_end)]

    units = _units(text, section)
    spans: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end = 0

    for u_start, u_end in units:
        unit_tokens = count_tokens(text[u_start:u_end])

        if unit_tokens > cfg.max_tokens:
            if cur_start is not None:
                spans.append((cur_start, cur_end))
                cur_start = None
            spans.extend(_hard_cut(text, u_start, u_end, cfg))
            continue

        if cur_start is None:
            cur_start, cur_end = u_start, u_end
            continue

        if count_tokens(text[cur_start:u_end]) <= cfg.max_tokens:
            cur_end = u_end
        else:
            spans.append((cur_start, cur_end))
            cur_start, cur_end = u_start, u_end

    if cur_start is not None:
        spans.append((cur_start, cur_end))

    return _apply_overlap(text, spans, section.char_start, cfg)


def _units(text: str, section: Section) -> list[tuple[int, int]]:
    """Paragraphs, falling back to sentences when a paragraph is one block."""
    paragraphs = _by_pattern(text, section.char_start, section.char_end, PARAGRAPH_BREAK)
    if len(paragraphs) > 1:
        return paragraphs
    return _by_pattern(text, section.char_start, section.char_end, SENTENCE_END)


def _by_pattern(text: str, start: int, end: int, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Split a span at every match, keeping absolute offsets.

    The separator is assigned to the preceding unit, so the spans tile the
    section exactly — no character belongs to two units, and none to neither.
    """
    spans: list[tuple[int, int]] = []
    cursor = start
    for m in pattern.finditer(text, start, end):
        if m.end() <= cursor:
            continue
        spans.append((cursor, m.end()))
        cursor = m.end()
    if cursor < end:
        spans.append((cursor, end))
    return spans or [(start, end)]


def _hard_cut(text: str, start: int, end: int, cfg: ChunkingConfig) -> list[tuple[int, int]]:
    """Last resort for an unbroken block: cut on a word boundary near the limit.

    A single 4000-token paragraph with no sentence punctuation does occur —
    scanned tables and minutes exported without line breaks both produce it.
    Cutting mid-word would corrupt a quote, so the cut walks back to whitespace.
    """
    limit = max(1, int(cfg.max_tokens * CHARS_PER_TOKEN))
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + limit, end)
        if stop < end:
            window = text.rfind(" ", cursor + limit // 2, stop)
            if window > cursor:
                stop = window + 1
        spans.append((cursor, stop))
        cursor = stop
    return spans


def _apply_overlap(
    text: str, spans: list[tuple[int, int]], floor: int, cfg: ChunkingConfig
) -> list[tuple[int, int]]:
    """Extend each span backwards by the overlap.

    Overlap is expressed as extra *source* characters, so the chunks genuinely
    overlap in the document rather than carrying a copied prefix. A copied
    prefix would break the slice-back invariant the moment anyone checked it.
    """
    if cfg.overlap <= 0 or len(spans) < 2:
        return spans

    back = int(cfg.overlap * CHARS_PER_TOKEN)
    out = [spans[0]]
    for start, end in spans[1:]:
        new_start = max(floor, start - back)
        window = text.rfind(" ", new_start, start)
        if window != -1:
            new_start = window + 1
        out.append((new_start, end))
    return out


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span past leading and trailing whitespace.

    Moving the boundaries keeps the slice-back guarantee intact; calling
    ``.strip()`` on the text would silently break it.
    """
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _page_of(doc: ParsedDocument, offset: int) -> int | None:
    """1-based page containing an offset, or None when the format has no pages."""
    if not doc.page_offsets:
        return None
    lo, hi = 0, len(doc.page_offsets) - 1
    page = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if doc.page_offsets[mid] <= offset:
            page, lo = mid, mid + 1
        else:
            hi = mid - 1
    return page + 1


class StructureFirstChunker:
    """Implements :class:`ledgerkb.core.ports.Chunker`."""

    def __init__(self, cfg: ChunkingConfig | None = None) -> None:
        self.cfg = cfg or ChunkingConfig()

    def chunk(self, doc: ParsedDocument, workspace_id: str, version_id: str) -> list[Chunk]:
        return chunk_document(doc, workspace_id, version_id, self.cfg)


__all__ = [
    "CHARS_PER_TOKEN",
    "Section",
    "StructureFirstChunker",
    "build_sections",
    "chunk_document",
    "count_tokens",
]
